"""Formation allocation and query timing regressions; all provider work is mocked."""
from copy import deepcopy
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
from ResultAnalysis import enrich_report
import Benchmark
from NoMemory import NoMemory
from benchmark_helpers import FakeTokenizer
from test_binary_benchmark import judgment
from test_benchmark_recovery import ProviderError


def build(sample, identity, seconds, module='vector_store'):
    return dict(module=module, sample_id=sample,
                ingestion=dict(ingestion_id=identity, write_seconds=seconds, preparation_seconds=seconds, total_seconds=1000))


def case(sample, category=4, retrieval=1, answer=2, module='vector_store'):
    return dict(module=module, sample_id=sample, category=category,
                diagnostics=dict(retrieval_seconds=retrieval, answer_seconds=answer,
                                 judge_seconds=900, total_seconds=1000))


class RuntimeAnalysisTests(unittest.TestCase):
    def fixture(self):
        return dict(cases=[case('a', 2), case('a'), case('b', retrieval=4, answer=5)],
                    memories=[build('a', 'a1', 60), build('b', 'b1', 6)])

    def row(self, value):
        return enrich_report(value)['comparison']['rows'][0]

    def test_formation_allocation_filtering_and_source_preservation(self):
        source = self.fixture()
        original = deepcopy(source)
        report = enrich_report(source)
        row = report['comparison']['rows'][0]
        r = row['overall']['runtime']
        self.assertEqual(r['total_formation_seconds'], 66)
        self.assertEqual(r['total_seconds'], 81)
        self.assertEqual(r['recorded_total_seconds'], 81)
        self.assertEqual(r['mean_total_seconds'], 27)
        self.assertEqual(r['mean_formation_seconds'], 22)
        self.assertEqual(r['mean_retrieval_seconds'], 2)
        self.assertEqual(r['mean_answer_seconds'], 3)
        self.assertEqual(r['count'], 3)
        self.assertEqual(row['categories']['2']['runtime']['mean_total_seconds'], 33)
        self.assertEqual(row['categories']['4']['runtime']['mean_total_seconds'], 24)
        self.assertEqual(row['categories']['2']['runtime']['mean_formation_seconds'], 30)
        self.assertEqual(row['overall']['mean_question_seconds'], 1000)
        self.assertEqual(report['comparison']['version'], 3)
        self.assertEqual(source, original)
        self.assertEqual(enrich_report(report), report)

    def test_resumed_builds_deduplicate_and_missing_ids_are_distinct(self):
        source = self.fixture()
        source['previous_ingestions'] = [deepcopy(source['memories'][0]), build('a', 'a2', 10)]
        r = self.row(source)['overall']['runtime']
        self.assertEqual(r['total_formation_seconds'], 76)
        self.assertEqual(r['formation_build_count'], 3)
        self.assertEqual(r['mean_total_seconds'], 91 / 3)
        for memory in [*source['previous_ingestions'], *source['memories']]:
            memory['ingestion'].pop('ingestion_id')
        r = self.row(source)['overall']['runtime']
        self.assertEqual(r['total_formation_seconds'], 136)
        self.assertEqual(r['formation_build_count'], 4)

    def test_conflicting_builds_invalidate_affected_conversations(self):
        for change in ('time', 'sample'):
            source = self.fixture()
            duplicate = deepcopy(source['memories'][0])
            if change == 'time':
                duplicate['ingestion']['preparation_seconds'] = 99
            else:
                duplicate['sample_id'] = 'b'
            source['previous_ingestions'] = [duplicate]
            row = self.row(source)
            self.assertTrue(row['overall']['runtime']['conflicting_ingestion_ids'])
            self.assertIsNone(row['overall']['runtime']['total_formation_seconds'])
            self.assertIsNone(row['categories']['2']['runtime']['mean_total_seconds'])
            self.assertEqual(row['overall']['runtime']['count'], 1 if change == 'time' else 0)

    def test_missing_measurements_stay_unknown_and_means_share_a_cohort(self):
        source = self.fixture()
        source['cases'][0]['diagnostics'].pop('answer_seconds')
        r = self.row(source)['overall']['runtime']
        self.assertEqual(r['count'], 2)
        self.assertEqual(r['record_count'], 3)
        self.assertIsNone(r['mean_total_seconds'])
        self.assertEqual(r['mean_formation_seconds'], 22)
        self.assertEqual(r['mean_retrieval_seconds'], 2)
        self.assertIsNone(r['mean_answer_seconds'])
        self.assertIsNone(r['total_seconds'])
        self.assertIsNone(r['recorded_total_seconds'])
        source['memories'][0]['ingestion'].pop('preparation_seconds')
        source['memories'][0]['ingestion'].pop('total_seconds')
        r = self.row(source)['overall']['runtime']
        self.assertEqual(r['count'], 1)
        self.assertIsNone(r['total_formation_seconds'])
        self.assertEqual(r['formation_runtime_count'], 1)
        # A missing preparation timer is not replaced by the narrower write timer.
        self.assertIsNone(self.row(source)['categories']['2']['runtime']['formation_seconds'])

    def test_invalid_values_and_unknown_cumulative_values_do_not_fall_back(self):
        for invalid in (None, -1, float('nan'), float('inf'), True):
            source = self.fixture()
            source['cases'][0]['diagnostics']['execution_answer_seconds'] = invalid
            row = self.row(source)
            self.assertEqual(row['overall']['runtime']['count'], 2)
            self.assertIsNone(row['categories']['2']['runtime']['mean_total_seconds'])

    def test_cumulative_query_times_override_latest_attempt(self):
        source = self.fixture()
        source['cases'][0]['diagnostics'].update(execution_retrieval_seconds=10, execution_answer_seconds=20)
        row = self.row(source)
        self.assertEqual(row['categories']['2']['runtime']['mean_total_seconds'], 60)
        self.assertEqual(row['overall']['runtime']['total_seconds'], 108)

    def test_zero_baseline_missing_conversation_and_empty_category(self):
        source = dict(cases=[case('a', retrieval=0, answer=0, module='question_only')],
                      memories=[build('a', 'a1', 0, module='question_only')],
                      question_manifest=[dict(module='question_only', category=2)])
        row = self.row(source)
        self.assertEqual(row['overall']['runtime']['mean_total_seconds'], 0)
        self.assertIsNone(row['categories']['2']['runtime']['mean_total_seconds'])
        self.assertEqual(row['categories']['2']['runtime']['count'], 0)
        source['cases'][0].pop('sample_id')
        self.assertEqual(self.row(source)['overall']['runtime']['mean_total_seconds'], 0)
        self.assertIsNone(self.row(source)['categories']['4']['runtime']['mean_total_seconds'])
        source['memories'] = []
        self.assertIsNone(self.row(source)['overall']['runtime']['total_formation_seconds'])

    def test_module_isolation_and_unallocated_formation(self):
        source = self.fixture()
        source['memories'].extend([build('orphan', 'orphan', 9), build('a', 'other', 10000, module='other')])
        r = self.row(source)['overall']['runtime']
        self.assertEqual(r['total_formation_seconds'], 75)
        self.assertEqual(r['unallocated_formation_seconds'], 9)
        self.assertEqual(r['allocated_total_seconds'], 81)
        self.assertEqual(r['total_seconds'], 90)
        self.assertEqual(r['recorded_total_seconds'], 90)
        self.assertEqual(r['mean_total_seconds'], 30)

    def test_previous_ingestion_validation(self):
        for previous in ([None], [dict(ingestion=None)], [dict(ingestion=dict(ingestion_id=[]))]):
            with self.subTest(previous=previous), self.assertRaises(ValueError):
                enrich_report(dict(cases=[], previous_ingestions=previous))


class RuntimeRecordingTests(unittest.TestCase):
    def dataset(self):
        return [dict(sample_id='one', conversation={}, qa=[dict(question='Where?', answer='Rome', category=4)])]

    def answer(self, module, question, diagnostics, **kwargs):
        diagnostics.update(retrieval_seconds=2, answer_seconds=3, retrieved=[])
        return 'Rome'

    def judge(self):
        return json.loads(judgment(1)), 900, 7

    def test_failed_answer_time_survives_resume_and_prediction_checkpoint(self):
        job = Benchmark.BenchmarkJob(self.dataset(), dict(module='question_only'))
        def fail(*args, **kwargs):
            self.answer(*args, **kwargs)
            raise ProviderError(402)
        with patch.object(Benchmark, 'direct_answer', side_effect=fail):
            job.run()
        previous = job.snapshot()
        self.assertEqual(previous['status'], 'failed')
        self.assertEqual(previous['cases'][0]['diagnostics']['execution_answer_seconds'], 3)
        resumed = Benchmark.BenchmarkJob.resume(self.dataset(), previous)
        checkpoints = []
        resumed.set_persistence_callback(checkpoints.append)
        with patch.object(Benchmark, 'direct_answer', side_effect=self.answer), patch.object(Benchmark, 'judge_answer', return_value=self.judge()):
            resumed.run()
        report = resumed.snapshot()
        self.assertEqual(report['status'], 'completed')
        d = report['cases'][0]['diagnostics']
        self.assertEqual(d['execution_retrieval_seconds'], 4)
        self.assertEqual(d['execution_answer_seconds'], 6)
        timing = enrich_report(report)['comparison']['rows'][0]['overall']['runtime']
        self.assertAlmostEqual(timing['mean_total_seconds'] - timing['total_formation_seconds'], 10)
        saved_prediction = next(s['cases'][0] for s in checkpoints if s['cases'][0].get('prediction'))
        self.assertEqual(saved_prediction['diagnostics']['execution_answer_seconds'], 6)

    def test_judge_only_resume_does_not_repeat_query_time(self):
        job = Benchmark.BenchmarkJob(self.dataset(), dict(module='question_only'))
        with patch.object(Benchmark, 'direct_answer', side_effect=self.answer), patch.object(Benchmark, 'judge_answer', side_effect=ProviderError(402)):
            job.run()
        previous = job.snapshot()
        resumed = Benchmark.BenchmarkJob.resume(self.dataset(), previous)
        with patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('Prediction must be reused')), patch.object(Benchmark, 'judge_answer', return_value=self.judge()):
            resumed.run()
        report = resumed.snapshot()
        d = report['cases'][0]['diagnostics']
        self.assertTrue(d['prediction_reused'])
        self.assertEqual(d['execution_retrieval_seconds'], 2)
        self.assertEqual(d['execution_answer_seconds'], 3)
        r = enrich_report(report)['comparison']['rows'][0]['overall']['runtime']
        self.assertAlmostEqual(r['mean_total_seconds'] - r['total_formation_seconds'], 5)
        self.assertEqual(r['formation_build_count'], 2)

    def test_retrieval_and_answer_errors_record_elapsed_time(self):
        memory = NoMemory()
        d = {}
        with patch.object(memory, 'retrieve', side_effect=RuntimeError('retrieval')), patch.object(Benchmark.time, 'perf_counter', side_effect=[10, 12]):
            with self.assertRaisesRegex(RuntimeError, 'retrieval'):
                Benchmark.direct_answer(memory, 'Where?', d)
        self.assertEqual(d['retrieval_seconds'], 2)
        self.assertEqual(d['answer_seconds'], 0)
        d = {}
        with patch.object(Benchmark, 'completion', side_effect=RuntimeError('answer')), patch.object(Benchmark.time, 'perf_counter', side_effect=[10, 12, 13, 17]):
            with self.assertRaisesRegex(RuntimeError, 'answer'):
                Benchmark.direct_answer(memory, 'Where?', d)
        self.assertEqual(d['retrieval_seconds'], 2)
        self.assertEqual(d['answer_seconds'], 4)

    def test_failed_formation_records_time_and_does_not_discard_prior_query_time(self):
        data = self.dataset()
        data[0]['conversation'] = {'session_1': [dict(speaker='Alice', text='Rome', dia_id='D1:1')]}
        job = Benchmark.BenchmarkJob(data, dict(module='sliding_window'))
        memory = NoMemory()
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), patch.object(Benchmark.MemoryFactory, 'create_memory_module', return_value=memory), patch.object(memory, 'write', side_effect=RuntimeError('write failed')):
            job.run()
        report = job.snapshot()
        self.assertGreater(report['memories'][0]['ingestion']['write_seconds'], 0)
        r = enrich_report(report)['comparison']['rows'][0]['overall']['runtime']
        self.assertEqual(r['mean_retrieval_seconds'], 0)
        self.assertEqual(r['mean_answer_seconds'], 0)
        self.assertEqual(r['mean_total_seconds'], r['total_formation_seconds'])
        previous = report['cases'][0]
        previous['diagnostics'].update(execution_retrieval_seconds=2, execution_answer_seconds=3)
        existing = {('sliding_window', 'one', 0): previous}
        job.mark_ingestion_blocked('sliding_window', data[0], [(0, data[0]['qa'][0])], 'another write failure', existing)
        self.assertEqual(job.snapshot()['cases'][0]['diagnostics']['execution_answer_seconds'], 3)


if __name__ == '__main__':
    unittest.main()
