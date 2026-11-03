"""Run totals per question exclude judging; no provider calls are made."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
from ResultAnalysis import enrich_report


class BenchmarkCostTests(unittest.TestCase):
    def fixture(self):
        return dict(cases=[
            dict(module='vector_store', sample_id='a', category=2,
                 diagnostics=dict(answer_tokens=100, judge_tokens=9000, retrieval_seconds=1, answer_seconds=6)),
            dict(module='vector_store', sample_id='a', category=4,
                 diagnostics=dict(answer_tokens=200, judge_tokens=None, retrieval_seconds=2, answer_seconds=12)),
            dict(module='vector_store', sample_id='a', category=4, error='failed before API call',
                 diagnostics=dict(answer_tokens=0, judge_tokens=0, retrieval_seconds=0, answer_seconds=0))],
            memories=[dict(module='vector_store', sample_id='a', ingestion=dict(
                ingestion_id='build-a', memory_tokens=30, write_seconds=1, total_seconds=5))])

    def row(self, source):
        return enrich_report(source)['comparison']['rows'][0]

    def test_total_memory_answering_cost_divided_by_all_recorded_questions(self):
        source = self.fixture()
        original = deepcopy(source)
        row = self.row(source)
        metrics = row['overall']
        self.assertEqual(metrics['total_question_tokens'], 330)
        self.assertEqual(metrics['mean_question_tokens'], 110)
        self.assertEqual(metrics['runtime']['total_seconds'], 26)
        self.assertAlmostEqual(metrics['runtime']['mean_total_seconds'], 26 / 3)
        self.assertEqual(row['categories']['2']['mean_question_tokens'], 110)
        self.assertEqual(row['categories']['4']['mean_question_tokens'], 110)
        self.assertEqual(source, original)

    def test_retry_ledgers_rebuilds_and_duplicate_snapshots_count_once(self):
        source = self.fixture()
        source['previous_ingestions'] = [deepcopy(source['memories'][0]), dict(
            module='vector_store', sample_id='a', ingestion=dict(ingestion_id='rebuild',
                memory_tokens=99999, provider_requests=[dict(phase='memory', tokens=60)],
                preparation_seconds=10, total_seconds=99999))]
        source['cases'][0]['diagnostics'].update(provider_requests=[
            dict(phase='answer', tokens=40), dict(phase='answer', tokens=80), dict(phase='judge', tokens=99999)],
            execution_retrieval_seconds=3, execution_answer_seconds=10)
        metrics = self.row(source)['overall']
        self.assertEqual(metrics['total_question_tokens'], 410)
        self.assertAlmostEqual(metrics['mean_question_tokens'], 410 / 3)
        self.assertEqual(metrics['runtime']['total_seconds'], 42)
        self.assertEqual(metrics['runtime']['mean_total_seconds'], 14)

    def test_preparation_without_questions_is_still_in_the_run_total(self):
        source = self.fixture()
        source['memories'].append(dict(module='vector_store', sample_id='unused',
            ingestion=dict(ingestion_id='unused', memory_tokens=60, total_seconds=9)))
        metrics = self.row(source)['overall']
        self.assertEqual(metrics['mean_question_tokens'], 130)
        self.assertAlmostEqual(metrics['runtime']['mean_total_seconds'], 35 / 3)

    def test_unknown_cost_does_not_become_a_partial_average(self):
        source = self.fixture()
        source['cases'][1]['diagnostics'].pop('answer_tokens')
        source['cases'][1]['diagnostics']['execution_answer_seconds'] = None
        metrics = self.row(source)['overall']
        self.assertIsNone(metrics['mean_question_tokens'])
        self.assertIsNone(metrics['runtime']['mean_total_seconds'])
        source = self.fixture()
        source['memories'][0]['ingestion']['preparation_seconds'] = None
        self.assertIsNone(self.row(source)['overall']['runtime']['mean_total_seconds'])

    def test_unreported_failed_retry_usage_is_ignored(self):
        for phase, aggregate in (('memory', 30), ('answer', 100)):
            with self.subTest(phase=phase):
                source = self.fixture()
                diagnostics = (source['memories'][0]['ingestion'] if phase == 'memory'
                               else source['cases'][0]['diagnostics'])
                diagnostics[phase + '_tokens'] = aggregate
                diagnostics['provider_requests'] = [
                    dict(phase=phase, attempt=1, status='error', tokens=None),
                    dict(phase=phase, attempt=2, status='completed', tokens=aggregate)]
                metrics = self.row(source)['overall']
                self.assertEqual(metrics['token_usage'][phase + '_tokens'], 30 if phase == 'memory' else 300)
                self.assertEqual(metrics['total_question_tokens'], 330)
                self.assertEqual(metrics['mean_question_tokens'], 110)

    def test_unknown_successful_or_inflight_usage_stays_unavailable(self):
        for status in ('completed', 'started', None):
            with self.subTest(status=status):
                source = self.fixture()
                source['memories'][0]['ingestion']['provider_requests'] = [dict(phase='memory', status=status, tokens=None)]
                self.assertIsNone(self.row(source)['overall']['mean_question_tokens'])

    def test_reported_tokens_on_failed_requests_still_count(self):
        source = self.fixture()
        source['memories'][0]['ingestion']['provider_requests'] = [
            dict(phase='memory', status='error', tokens=5),
            dict(phase='memory', status='error', tokens=None),
            dict(phase='memory', status='completed', tokens=30)]
        self.assertEqual(self.row(source)['overall']['mean_question_tokens'], 335 / 3)
        source['memories'][0]['ingestion']['provider_requests'] = [dict(phase='memory', status='error', tokens=None)]
        self.assertEqual(self.row(source)['overall']['mean_question_tokens'], 100)

    def test_unknown_judging_usage_does_not_affect_memory_answer_average(self):
        source = self.fixture()
        source['cases'][0]['diagnostics']['provider_requests'] = [
            dict(phase='answer', status='completed', tokens=100),
            dict(phase='judge', status='error', tokens=None),
            dict(phase='judge', status='completed', tokens=99999)]
        metrics = self.row(source)['overall']
        self.assertEqual(metrics['total_question_tokens'], 330)
        self.assertEqual(metrics['mean_question_tokens'], 110)

    def test_preparation_covers_module_initialization_when_recorded(self):
        source = self.fixture()
        source['memories'][0]['ingestion']['preparation_seconds'] = 8
        self.assertEqual(self.row(source)['overall']['runtime']['total_seconds'], 29)

    def test_conflicting_duplicate_memory_tokens_are_unknown(self):
        source = self.fixture()
        duplicate = deepcopy(source['memories'][0])
        duplicate['ingestion']['memory_tokens'] = 999
        source['previous_ingestions'] = [duplicate]
        self.assertIsNone(self.row(source)['overall']['mean_question_tokens'])

    def test_no_memory_baseline_and_zero_question_denominator(self):
        source = dict(cases=[dict(module='question_only', category=4, diagnostics=dict(answer_tokens=0))])
        self.assertEqual(self.row(source)['overall']['mean_question_tokens'], 0)
        source = dict(cases=[], question_manifest=[dict(module='question_only', category=4)])
        metrics = self.row(source)['overall']
        self.assertIsNone(metrics['mean_question_tokens'])
        self.assertIsNone(metrics['runtime']['mean_total_seconds'])

    def test_save_replaces_stale_metrics_and_disk_reload_matches_new_formula(self):
        os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
        import app
        source = self.fixture()
        for case, context in zip(source['cases'], (100, 300, 200)):
            case['diagnostics']['memory_context_tokens'] = context
        source['comparison'] = dict(version=1, rows=[dict(module='vector_store', overall=dict(
            mean_question_tokens=99999, mean_context_tokens=99999,
            runtime=dict(mean_total_seconds=99999)))])
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RESULT_LIBRARY', Path(directory)):
            path = Path(directory) / 'stale.json'
            path.write_text(json.dumps(source), encoding='utf-8')
            before = path.read_bytes()
            client = app.app.test_client()
            preview = client.get('/api/results/file', query_string={'path': 'stale.json', 'analysis': '1'})
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.json['report']['comparison']['version'], 5)
            self.assertEqual(path.read_bytes(), before, 'Viewing analysis does not silently save')
            response = client.post('/api/results/enrich', json={'path': 'stale.json'})
            self.assertEqual(response.status_code, 200)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved, response.json['report'])
            self.assertEqual(saved['comparison']['version'], 5)
            metrics = saved['comparison']['rows'][0]['overall']
            self.assertEqual(metrics['total_question_tokens'], 330)
            self.assertEqual(metrics['mean_question_tokens'], 110)
            self.assertEqual(metrics['total_context_tokens'], 600)
            self.assertEqual(metrics['mean_context_tokens'], 200)
            self.assertEqual(metrics['runtime']['total_seconds'], 26)
            self.assertAlmostEqual(metrics['runtime']['mean_total_seconds'], 26 / 3)
            self.assertEqual(saved['cases'], source['cases'])
            self.assertEqual(saved['memories'], source['memories'])
            reloaded = client.get('/api/results/file', query_string={'path': 'stale.json'})
            self.assertEqual(reloaded.json['report'], saved)
            self.assertEqual(client.post('/api/results/enrich', json={'path': 'stale.json'}).json['report'], saved,
                             'Saving twice must not add memory cost again')


if __name__ == '__main__':
    unittest.main()
