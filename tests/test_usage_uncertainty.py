"""Decision-brief accounting claims, tested without provider calls."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
from ResultAnalysis import enrich_report, phase_usage


class UsageUncertaintyTests(unittest.TestCase):
    def fixture(self):
        return dict(config=dict(window_size=50), cases=[
            dict(module='windowed_summarization', sample_id='a', category=4,
                 diagnostics=dict(answer_tokens=10, judge_tokens=5))], memories=[
            dict(module='windowed_summarization', sample_id='a', error=None,
                 ingestion=dict(ingestion_id='one', memory_tokens=20,
                                final_storage=dict(stored_text_bytes=100)))])

    def row(self, source):
        return enrich_report(source)['comparison']['rows'][0]['overall']

    def test_missing_failure_is_not_free_and_judging_stays_separate(self):
        source = self.fixture()
        source['cases'][0]['diagnostics']['provider_requests'] = [
            dict(phase='answer', status='completed', tokens=10),
            dict(phase='judge', status='error', tokens=None),
            dict(phase='judge', status='completed', tokens=5)]
        row = self.row(source)
        self.assertEqual(row['total_question_tokens'], 30)
        self.assertIsNone(row['lifecycle']['total_provider_tokens'])
        self.assertEqual(row['lifecycle']['known_recorded_provider_tokens'], 35)
        self.assertEqual(row['token_usage']['missing_failed_request_count'], 0)
        self.assertEqual(row['lifecycle']['missing_failed_request_count'], 1)

    def test_invalid_and_missing_usage_coverage_including_legacy(self):
        usage = phase_usage(dict(provider_requests=[
            dict(phase='memory', status='error', tokens=None),
            dict(phase='memory', status='completed', tokens=-1),
            dict(phase='memory', status='started'),
            dict(phase='memory', status='error', tokens=7)]), 'memory')
        self.assertIsNone(usage['tokens'])
        self.assertEqual(usage['known_recorded_tokens'], 7)
        self.assertEqual(usage['missing_request_count'], 3)
        self.assertEqual(usage['missing_failed_request_count'], 1)
        legacy = phase_usage(dict(memory_tokens=20), 'memory')
        self.assertEqual(legacy['tokens'], 20)
        self.assertEqual(legacy['records_without_ledger'], 1)

    def test_conflicting_unknown_ledgers_do_not_produce_a_recorded_lower_bound(self):
        source = self.fixture()
        d = source['memories'][0]['ingestion']
        d['provider_requests'] = [dict(phase='memory', status='error', tokens=None),
                                  dict(phase='memory', status='completed', tokens=20)]
        other = deepcopy(source['memories'][0])
        other['ingestion']['provider_requests'][1]['tokens'] = 30
        source['previous_ingestions'] = [other]
        row = self.row(source)
        self.assertTrue(row['token_usage']['conflicting_ingestion_ids'])
        self.assertIsNone(row['token_usage']['known_recorded_tokens'])
        self.assertIsNone(row['lifecycle']['known_recorded_provider_tokens'])

    def test_current_storage_and_previous_successful_build_coverage_are_distinct(self):
        source = self.fixture()
        source['cases'].append(dict(module='windowed_summarization', sample_id='b', category=4))
        previous = deepcopy(source['memories'][0])
        previous.update(sample_id='b')
        previous['ingestion'].update(ingestion_id='two', final_storage=dict(stored_text_bytes=200))
        source['previous_ingestions'] = [previous]
        row = self.row(source)
        self.assertEqual(row['stored_text_bytes'], 100)
        self.assertEqual(row['storage_conversation_count'], 1)
        self.assertEqual(row['expected_conversation_count'], 2)
        self.assertFalse(row['storage_cohort_complete'])
        self.assertEqual(row['latest_successful_storage']['stored_text_bytes'], 300)
        previous['error'] = 'failed'
        self.assertIsNone(self.row(source)['latest_successful_storage']['stored_text_bytes'])

    def test_conflicting_provenance_or_ownership_invalidates_both_token_totals(self):
        for field in ('response_id', 'sample_id'):
            with self.subTest(field=field):
                source = self.fixture()
                current = source['memories'][0]
                current['ingestion']['provider_requests'] = [dict(
                    phase='memory', status='completed', tokens=20, response_id='first')]
                previous = deepcopy(current)
                if field == 'response_id':
                    previous['ingestion']['provider_requests'][0]['response_id'] = 'other'
                else:
                    previous['sample_id'] = 'b'
                source['previous_ingestions'] = [previous]
                row = self.row(source)
                self.assertTrue(row['token_usage']['conflicting_ingestion_ids'])
                self.assertIsNone(row['total_question_tokens'])
                self.assertIsNone(row['token_usage']['known_recorded_tokens'])
                self.assertTrue(row['lifecycle']['conflicting_ingestion_ids'])
                self.assertIsNone(row['lifecycle']['known_recorded_provider_tokens'])

    def test_identical_ingestions_are_counted_once(self):
        source = self.fixture()
        source['previous_ingestions'] = deepcopy(source['memories'])
        row = self.row(source)
        self.assertEqual(row['total_question_tokens'], 30)
        self.assertEqual(row['lifecycle']['total_provider_tokens'], 35)
        self.assertEqual(row['lifecycle']['ingestion_count'], 1)
        self.assertFalse(row['token_usage']['conflicting_ingestion_ids'])

    def test_filename_warning_is_non_mutating_and_idempotent(self):
        source = self.fixture()
        original = deepcopy(source)
        report = enrich_report(source, source_name='locomo-results(windowed_summary_k=100).json')
        self.assertEqual(source, original)
        self.assertEqual(report['comparison']['warnings'][0]['configured_window'], 50)
        self.assertEqual(enrich_report(report), report)
        renamed = enrich_report(report, source_name='locomo-results(windowed_summary_k=50).json')
        self.assertEqual(renamed['comparison']['warnings'], [])

    def test_library_analysis_flags_actual_filename_without_writing_export(self):
        import app
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            path = Path(directory) / 'locomo-results(windowed_summary_k=100).json'
            path.write_text(json.dumps(self.fixture()), encoding='utf-8')
            before = path.read_bytes()
            response = app.app.test_client().get('/api/results/file', query_string=dict(path=path.name, analysis='1'))
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['report']['comparison']['warnings'][0]['filename_window'], 100)
            self.assertEqual(path.read_bytes(), before)
