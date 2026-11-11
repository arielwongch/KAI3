"""Bounded API overlap, conversation barriers, cancellation and frozen resume."""
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
import ExperimentRecording as recording
from BenchmarkStore import read_json, write_snapshot
from benchmark_helpers import FakeTokenizer
from test_benchmark_recovery import ProviderError
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


def dataset(count=6, samples=('A', 'B')):
    return [dict(sample_id=sample, conversation={'session_1': [
        dict(speaker='Alice', text='I live in Rome.', dia_id='D1:1')]},
        qa=[dict(question=f'{sample}-{i}: Where?', answer='Rome', category=4) for i in range(count)])
        for sample in samples]


class ParallelQuestionTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer())
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, job, create):
        fake = FakeOpenAIClient('Rome')
        original = fake.chat.completions.create
        def request(**kwargs):
            response = original(**kwargs)
            return create(response, kwargs)
        with patch.object(Benchmark, 'client', fake), \
             patch.object(fake.chat.completions, 'create', side_effect=request):
            job.run()
        return fake

    def test_questions_overlap_with_bound_and_next_ingestion_waits_for_all_judges(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='sliding_window', all_conversations=True,
                                                    question_limit=0, question_workers=3))
        barrier = threading.Barrier(3)
        lock = threading.Lock()
        active, peak, first_answers, a_judged = 0, 0, 0, 0
        progress = job.live_progress
        def check_barrier(phase=None, **kwargs):
            if phase == 'ingestion' and kwargs.get('sample_id') == 'B':
                self.assertEqual(a_judged, 6, 'Next ingestion started before all judges finished')
            return progress(phase, **kwargs)
        job.live_progress = check_barrier
        def request(response, kwargs):
            nonlocal active, peak, first_answers, a_judged
            judging = 'response_format' in kwargs
            text = json.dumps(kwargs['messages'])
            with lock:
                active += 1
                peak = max(peak, active)
                synchronize = not judging and first_answers < 3
                if synchronize:
                    first_answers += 1
            try:
                if synchronize:
                    barrier.wait(5)
                response.choices[0].message.content = judgment(1) if judging else 'Rome'
                if judging and 'A-' in text:
                    with lock:
                        a_judged += 1
                return response
            finally:
                with lock:
                    active -= 1
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, job.result['run_id'] + '.json')
            job.set_persistence_callback(lambda snapshot: write_snapshot(path, snapshot))
            self.run_job(job, request)
            current = read_json(path)
            self.assertEqual(current['status'], 'completed', current.get('error'))
            self.assertEqual(peak, 3)
            self.assertEqual(len(current['cases']), 12)
            self.assertEqual([(c['sample_id'], c['question_index']) for c in current['cases']],
                             [(s, i) for s in ('A', 'B') for i in range(6)])
            for case in current['cases']:
                self.assertEqual(case['correct'], 1)
                d = case['diagnostics']
                context = recording.get(current['recording'], d['context_artifact'])
                self.assertEqual(context['memory_state_artifact'], d['memory_state_artifact'])
                self.assertEqual({q['phase'] for q in d['provider_requests']}, {'answer', 'judge'})
                self.assertTrue(all(q['request_artifact'] and q['response_artifact'] for q in d['provider_requests']))
                answer = next(q for q in d['provider_requests'] if q['phase'] == 'answer')
                request_data = recording.get(current['recording'], answer['request_artifact'])
                self.assertIn(case['question'], request_data['messages'][-1]['content'])
            recording.validate(current)

    def test_fatal_failure_stops_pending_questions_and_joins_inflight_work(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='question_only', all_conversations=True,
                                                    question_limit=0, question_workers=3))
        barrier = threading.Barrier(3)
        entered = []
        guard = threading.Lock()
        def request(response, kwargs):
            judging = 'response_format' in kwargs
            text = json.dumps(kwargs['messages'])
            match = re.search(r'([AB]-\d+)', text)
            if not judging:
                with guard:
                    entered.append(match.group(1))
                barrier.wait(5)
                if 'A-0' in text:
                    raise ProviderError(402)
                deadline = time.monotonic() + 5
                while not Benchmark.cancel_event.get().is_set() and time.monotonic() < deadline:
                    time.sleep(.001)
            response.choices[0].message.content = judgment(1) if judging else 'Rome'
            return response
        self.run_job(job, request)
        self.assertEqual(job.result['status'], 'failed', job.result.get('error'))
        self.assertEqual(job.result['failure_status_code'], 402)
        self.assertEqual(set(entered), {'A-0', 'A-1', 'A-2'})
        self.assertFalse(job.cancel.is_set(), 'Fatal failure must remain resumable as failed, not cancelled')
        self.assertEqual(job.result['progress']['active_questions'], [])
        self.assertEqual(len(job.result['memories']), 1)

    def test_user_cancellation_stops_queued_work_and_retains_paid_predictions(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='question_only', all_conversations=True,
                                                    question_limit=0, question_workers=3))
        barrier = threading.Barrier(3)
        entered = []
        def request(response, kwargs):
            if 'response_format' not in kwargs:
                entered.append(kwargs)
                barrier.wait(5)
                job.cancel.set()
            response.choices[0].message.content = 'Rome'
            return response
        self.run_job(job, request)
        self.assertEqual(job.result['status'], 'cancelled')
        self.assertEqual(len(entered), 3)
        self.assertEqual(len(job.result['memories']), 1)
        self.assertEqual(job.result['progress']['active_questions'], [])
        self.assertTrue(all(c.get('prediction') == 'Rome' for c in job.result['cases']))
        recording.validate(job.result)

    def test_worker_limit_validation_and_resume_override_preserve_question_config_hash(self):
        for invalid in (0, 9, True, 2.5, '3'):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, 'question_workers'):
                Benchmark.BenchmarkJob(dataset(), dict(question_workers=invalid))
        job = Benchmark.BenchmarkJob(dataset(2, ('A',)), dict(module='question_only'))
        def request(response, kwargs):
            response.choices[0].message.content = judgment(1) if 'response_format' in kwargs else 'Rome'
            return response
        self.run_job(job, request)
        previous = job.snapshot()
        resumed = Benchmark.BenchmarkJob.resume(dataset(2, ('A',)), previous, question_workers=3)
        self.assertEqual(resumed.result['config_hash'], previous['config_hash'])
        self.assertEqual(resumed.options['question_workers'], 3)
        with patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('completed answers must be skipped')), \
             patch.object(Benchmark, 'judge_answer', side_effect=AssertionError('completed judges must be skipped')):
            resumed.run()
        self.assertEqual(resumed.result['status'], 'completed')
        self.assertEqual(resumed.result['cases'], previous['cases'])

    def test_retry_diagnostics_are_isolated_per_parallel_question(self):
        job = Benchmark.BenchmarkJob(dataset(4, ('A',)), dict(module='question_only',
                                                            question_limit=0, question_workers=3))
        retried = set()
        lock = threading.Lock()
        def request(response, kwargs):
            text = json.dumps(kwargs['messages'])
            judging = 'response_format' in kwargs
            with lock:
                if not judging and 'A-0' in text and not retried:
                    retried.add('A-0')
                    raise ProviderError(429)
            response.choices[0].message.content = judgment(1) if judging else 'Rome'
            return response
        with patch.object(Benchmark.QuestionCancellation, 'wait', return_value=False):
            self.run_job(job, request)
        self.assertEqual(job.result['status'], 'completed', job.result.get('error'))
        for case in job.result['cases']:
            self.assertEqual(case['diagnostics']['answer_llm_calls'], 2 if case['question_index'] == 0 else 1)
        recording.validate(job.result)

    def test_parallel_resume_reuses_a_paid_prediction_and_frozen_memory(self):
        data = dataset(4, ('A',))
        job = Benchmark.BenchmarkJob(data, dict(module='sliding_window', question_limit=0))
        def fail_judge(response, kwargs):
            if 'response_format' in kwargs:
                raise ProviderError(402)
            response.choices[0].message.content = 'Rome'
            return response
        self.run_job(job, fail_judge)
        previous = job.snapshot()
        self.assertEqual(previous['status'], 'failed')
        resumed = Benchmark.BenchmarkJob.resume(data, previous, question_workers=3)
        direct = Benchmark.direct_answer
        def answer(module, question, *args, **kwargs):
            self.assertNotIn('A-0', question, 'Paid answer was generated again')
            return direct(module, question, *args, **kwargs)
        def request(response, kwargs):
            response.choices[0].message.content = judgment(1) if 'response_format' in kwargs else 'Rome'
            return response
        with patch.object(Benchmark, 'direct_answer', side_effect=answer):
            fake = self.run_job(resumed, request)
        self.assertEqual(resumed.result['status'], 'completed', resumed.result.get('error'))
        self.assertEqual(len(fake.calls), 7)
        self.assertEqual(resumed.result['memories'][0]['ingestion']['construction_action'], 'frozen_reuse')
        self.assertEqual(resumed.result['cases'][0]['diagnostics']['context_artifact'],
                         previous['cases'][0]['diagnostics']['context_artifact'])
        recording.validate(resumed.result)


if __name__ == '__main__':
    unittest.main()
