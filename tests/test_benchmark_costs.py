"""Run totals per question exclude judging; no provider calls are made."""
from copy import deepcopy
import sys
import unittest

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


if __name__ == '__main__':
    unittest.main()
