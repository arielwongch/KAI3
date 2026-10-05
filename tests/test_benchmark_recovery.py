import json
import os
import sys
import threading
import unittest
from unittest.mock import patch
sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
import RequestPolicy
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient

class ProviderError(RuntimeError):
    def __init__(self, code):
        self.status_code = code
        super().__init__(f'Error code: {code} - provider failure')


def dataset():
    return [dict(sample_id='one', conversation={}, qa=[
        dict(question=f'Question {i}', answer='Rome', category=4) for i in range(3)])]

class RecoveryTests(unittest.TestCase):
    def test_transient_backoff_and_bounded_attempts(self):
        fake = FakeOpenAIClient('Rome')
        original = fake.chat.completions.create
        attempts = []
        def request(**kwargs):
            attempts.append(kwargs)
            if len(attempts) < 3:
                raise ProviderError(429)
            return original(**kwargs)
        diagnostics = {}
        with patch.object(fake.chat.completions, 'create', side_effect=request), patch.object(RequestPolicy.time, 'sleep') as sleep:
            result = RequestPolicy.completion(fake, diagnostics, model='deepseek-flash')
        self.assertEqual(result.choices[0].message.content, 'Rome')
        self.assertEqual(diagnostics['answer_llm_calls'], 3)
        self.assertEqual(len(diagnostics['answer_retries']), 2)
        self.assertEqual(sleep.call_count, 2)
        with patch.object(fake.chat.completions, 'create', side_effect=ProviderError(503)) as request, patch.object(RequestPolicy.time, 'sleep'):
            with self.assertRaises(ProviderError):
                RequestPolicy.completion(fake)
            self.assertEqual(request.call_count, 5)

    def test_balance_failure_stops_then_resume_skips_scored_answers(self):
        fake = FakeOpenAIClient(['Rome', judgment(0)])
        original = fake.chat.completions.create
        def request(**kwargs):
            if len(fake.calls) == 2:
                raise ProviderError(402)
            return original(**kwargs)
        job = Benchmark.BenchmarkJob(dataset(), dict(module='no_memory', question_limit=0))
        checkpoints = []
        job.set_persistence_callback(checkpoints.append)
        with patch.object(Benchmark, 'client', fake), patch.object(fake.chat.completions, 'create', side_effect=request):
            job.run()
        previous = job.snapshot()
        self.assertEqual(previous['status'], 'failed')
        self.assertEqual(previous['failure_status_code'], 402)
        self.assertEqual(len(previous['cases']), 2)
        self.assertEqual(previous['cases'][0]['correct'], 0)
        self.assertIsNone(previous['cases'][1]['diagnostics']['answer_tokens'])
        self.assertTrue(any(len(s['cases']) == 1 for s in checkpoints))
        resumed = Benchmark.BenchmarkJob.resume(dataset(), previous)
        fake = FakeOpenAIClient(['Rome', judgment(1), 'Rome', judgment(1)])
        with patch.object(Benchmark, 'client', fake):
            resumed.run()
        result = resumed.snapshot()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(fake.calls), 4)
        self.assertEqual(len(result['cases']), 3)
        self.assertEqual(result['cases'][0], previous['cases'][0])
        self.assertNotIn('Question 0', str(fake.calls))

    def test_judge_balance_failure_retains_and_reuses_prediction(self):
        data = dataset(); data[0]['qa'] = data[0]['qa'][:1]
        fake = FakeOpenAIClient('SAVED PREDICTION')
        original = fake.chat.completions.create
        def request(**kwargs):
            if fake.calls:
                raise ProviderError(402)
            return original(**kwargs)
        job = Benchmark.BenchmarkJob(data, dict(module='no_memory'))
        with patch.object(Benchmark, 'client', fake), patch.object(fake.chat.completions, 'create', side_effect=request):
            job.run()
        previous = job.snapshot()
        self.assertEqual(previous['status'], 'failed')
        self.assertEqual(previous['cases'][0]['prediction'], 'SAVED PREDICTION')
        resumed = Benchmark.BenchmarkJob.resume(data, previous)
        fake = FakeOpenAIClient(judgment(1))
        with patch.object(Benchmark, 'client', fake):
            resumed.run()
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(resumed.snapshot()['cases'][0]['prediction'], 'SAVED PREDICTION')
        self.assertTrue(resumed.snapshot()['cases'][0]['diagnostics']['prediction_reused'])

    def test_resume_endpoint_after_restart(self):
        import app
        job = Benchmark.BenchmarkJob(dataset(), dict(module='no_memory', question_limit=1))
        previous = job.snapshot(); previous['status'] = 'failed'
        restored = Benchmark.BenchmarkJob.restore(previous)
        app.jobs.clear(); app.jobs[previous['run_id']] = restored
        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        fake = FakeOpenAIClient(['Rome', judgment(1)])
        with patch.object(app, 'persist_benchmark'), patch.object(app, 'Thread', Worker), patch.object(Benchmark, 'client', fake):
            response = app.app.test_client().post('/api/benchmarks/' + previous['run_id'] + '/resume', json=dict(dataset=dataset()))
        self.assertEqual(response.status_code, 202)
        result = app.jobs[previous['run_id']].snapshot()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['resume_count'], 1)
        app.jobs.clear()

    def test_resume_rejects_changed_dataset(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='no_memory'))
        data = dataset(); data[0]['qa'][0]['question'] = 'changed'
        with self.assertRaises(ValueError):
            Benchmark.BenchmarkJob.resume(data, job.snapshot())

    def test_cancel_interrupts_retry_wait(self):
        fake = FakeOpenAIClient()
        class Event:
            def is_set(self):
                return False
            def wait(self, seconds):
                return True
        token = RequestPolicy.cancel_event.set(Event())
        try:
            with patch.object(fake.chat.completions, 'create', side_effect=ProviderError(429)) as request:
                with self.assertRaises(RequestPolicy.RequestCancelled):
                    RequestPolicy.completion(fake)
                self.assertEqual(request.call_count, 1)
        finally:
            RequestPolicy.cancel_event.reset(token)

if __name__ == '__main__':
    unittest.main()
