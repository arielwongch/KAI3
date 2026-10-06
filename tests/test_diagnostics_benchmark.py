import json
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
from benchmark_helpers import FakeTokenizer
import ReAct
import Summarization as summary_module
from Diagnostics import totals
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from test_memory_integration import FakeOpenAIClient

class Embedder:
    def chunks(self, text):
        return [text]
    def embed(self, texts):
        return [[1, 0] for text in texts]

def fixture():
    return [{'sample_id': 'fixture', 'conversation': {
        'session_2': [{'speaker': 'Bob', 'text': 'I like tea.', 'dia_id': 'D2:1'}],
        'session_1_date_time': '1 May 2024',
        'session_1': [{'speaker': 'Alice', 'text': 'I live in Rome.', 'dia_id': 'D1:1', 'blip_caption': 'A city.'}],
    }, 'qa': [{'question': 'Where does Alice live?', 'answer': 'Rome', 'category': 4, 'evidence': ['D1:1']},
              {'question': 'Unknown?', 'category': 5, 'evidence': []}]}]

class DiagnosticsTests(unittest.TestCase):
    def test_snapshots_detached_and_no_model_calls(self):
        for mode in Benchmark.MODULES[:-1]:
            module = MemoryFactory.create_memory_module(mode, embedder=Embedder(), extractor=lambda *a: ('{"operations":[{"op":"add","text":"Rome"}]}', 0, 3))
            with patch.object(summary_module, 'call_api', return_value=('Rome', 0, 2)):
                module.write(MemoryEntry('Rome', {'nested': {'key': 'value'}}))
            with patch.object(module, 'retrieve', side_effect=AssertionError('retrieve used')), patch.object(ReAct.client.chat.completions, 'create', side_effect=AssertionError('API used')):
                before = module.inspect()
                json.dumps(before)
                before['entries'][0]['text'] = 'changed'
                before['config']['extra'] = True
                self.assertEqual(module.inspect()['entries'][0]['text'], 'Rome')
                self.assertNotIn('extra', module.inspect()['config'])

    def test_clock_and_writeback(self):
        module = MemoryFactory.create_memory_module('sliding_window')
        module.write(MemoryEntry('prior'))
        fake = FakeOpenAIClient(['Thought: working\nAction: echo: x', 'Thought: I have the final answer.\nFinal Answer: Rome'])
        diagnostics = {}
        with patch.object(ReAct, 'client', fake), patch.object(ReAct.time, 'perf_counter', side_effect=range(100)):
            result = ReAct.run_ReAct('question', memory_module=module, diagnostics=diagnostics, write_back=False)
        self.assertEqual(len(result), 3)
        self.assertEqual(diagnostics['agent_seconds'], 2)
        self.assertEqual(diagnostics['agent_tokens'], 14)
        self.assertEqual(diagnostics['agent_llm_calls'], 2)
        self.assertEqual(diagnostics['retrieved'][0]['text'], 'prior')
        self.assertEqual(diagnostics['stored_before'], diagnostics['stored_after'])
        self.assertEqual(diagnostics['write_seconds'], 0)
        self.assertEqual(diagnostics['final_answer'], 'Rome')

    def test_failed_write_preserves_trace_and_memory(self):
        module = MemoryFactory.create_memory_module('summarization')
        module.summary = 'old'
        d = {}
        with patch.object(ReAct, 'client', FakeOpenAIClient()), patch.object(summary_module, 'call_api', side_effect=RuntimeError('write failed')):
            with self.assertRaises(RuntimeError):
                ReAct.run_ReAct('question', memory_module=module, diagnostics=d)
        self.assertEqual(module.summary, 'old')
        self.assertEqual(d['status'], 'error')
        self.assertEqual(d['retrieved'][0]['text'], 'old')
        self.assertEqual(d['memory_llm_calls'], 1)
        self.assertIsNone(d['memory_tokens'])
        self.assertIsNone(totals([d])['memory_tokens'])

    def test_memory_token_accounting(self):
        for mode, tokens in [('summarization', 4), ('fact_store', 6)]:
            module = MemoryFactory.create_memory_module(mode, embedder=Embedder(), extractor=lambda *a: ('{"operations":[]}', 0, tokens))
            d = {}
            with patch.object(ReAct, 'client', FakeOpenAIClient()), patch.object(summary_module, 'call_api', return_value=('summary', 0, tokens)):
                ReAct.run_ReAct('question', memory_module=module, diagnostics=d)
            self.assertEqual(d['memory_tokens'], tokens)
            self.assertEqual(d['memory_llm_calls'], 1)

class SessionTests(unittest.TestCase):
    def setUp(self):
        app.chat_memory_modules.clear()
        app.jobs.clear()
        token_patch = patch.object(Benchmark, "get_benchmark_tokenizer", return_value=FakeTokenizer())
        token_patch.start(); self.addCleanup(token_patch.stop)
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        store_patch = patch.object(app, "RUN_STORE", directory.name)
        store_patch.start(); self.addCleanup(store_patch.stop)
        self.client = app.app.test_client()
    def send(self, chat='one', **extra):
        return self.client.post('/get', json=dict(message='Hello', chat_id=chat, memory_module='sliding_window', **extra))
    def test_sessions_restart_and_export(self):
        with patch.object(ReAct, 'client', FakeOpenAIClient()):
            response = self.send()
            self.assertEqual(response.status_code, 200)
            self.send('two')
        data = self.client.get('/api/chats/one/diagnostics').json
        self.assertEqual(len(data['turns']), 1)
        self.assertEqual(data['turns'][0]['turn_id'], response.json['turn_id'])
        self.assertEqual(len(data['memory']['entries']), 1)
        self.assertIn('attachment', self.client.get('/api/chats/one/export').headers['Content-Disposition'])
        app.chat_memory_modules.clear()
        self.assertEqual(self.send(requires_existing=True).status_code, 410)
        self.assertEqual(self.client.get('/api/chats/one').status_code, 404)
    def test_inspection_waits_for_session_operation(self):
        with patch.object(ReAct, 'client', FakeOpenAIClient()):
            self.send()
        session = app.chat_memory_modules['one']
        entered = threading.Event()
        finished = threading.Event()
        def inspect():
            entered.set()
            session.snapshot('one')
            finished.set()
        with session.lock:
            thread = threading.Thread(target=inspect)
            thread.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(finished.wait(.02))
        thread.join(1)
        self.assertTrue(finished.is_set())

    def test_frontend_api_runner_and_export(self):
        # Execute the worker synchronously to make endpoint assertions deterministic.
        class Worker:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        with patch.object(app, 'Thread', Worker), patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')):
            response = self.client.post('/api/benchmarks', json={'dataset': fixture(), 'options': {'modules': ['sliding_window'], 'question_limit': 1}})
        self.assertEqual(response.status_code, 202)
        run_id = response.json['run_id']
        result = self.client.get('/api/benchmarks/' + run_id).json
        self.assertEqual(result['cases'][0]['score'], 1)
        self.assertEqual(result['status'], 'completed')
        export = self.client.get('/api/benchmarks/' + run_id + '/export')
        self.assertEqual(export.json, result)
        self.assertIn('attachment', export.headers['Content-Disposition'])
        self.assertEqual(self.client.post('/api/benchmarks/' + run_id + '/cancel').status_code, 200)

    def test_error_diagnostics_and_validation(self):
        with patch.object(ReAct, 'client', FakeOpenAIClient()), patch.object(ReAct, '_run_ReAct', side_effect=RuntimeError('provider')), patch.object(app.app.logger, 'exception'):
            self.assertEqual(self.send().status_code, 503)
        self.assertEqual(self.client.get('/api/chats/one').json['turns'][0]['status'], 'error')
        self.assertEqual(self.client.post('/get', json={'message': 123}).status_code, 400)
        self.assertEqual(self.client.post('/api/benchmarks', json={'dataset': []}).status_code, 400)

class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        token_patch = patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer())
        token_patch.start(); self.addCleanup(token_patch.stop)

    def test_upstream_scoring(self):
        self.assertEqual(Benchmark.score('Rome', 'Rome', 4), 1)
        self.assertEqual(Benchmark.score('Rome', 'Rome; Italy', 3), 1)
        self.assertEqual(Benchmark.score('tea, Rome', 'Rome, tea', 1), 1)
        self.assertEqual(Benchmark.score('Not mentioned', '', 5), 1)
        self.assertEqual(Benchmark.score('guessed', '', 5), 0)
        self.assertEqual(Benchmark.score('running', 'runs', 2), 1)
    def test_isolation_order_no_leakage_and_recall(self):
        created = []
        data = fixture(); data[0]['qa'][0]['answer'] = 'SECRET ANSWER'
        from SlidingWindow import SlidingWindow
        from VectorStore import VectorStore
        from test_binary_benchmark import judgment
        def create(mode, **kwargs):
            module = SlidingWindow() if mode == 'sliding_window' else VectorStore(Embedder())
            created.append(module)
            return module
        for mode in ('sliding_window', 'vector_store'):
            job = Benchmark.BenchmarkJob(data, {'module': mode, 'categories': [4]})
            fake = FakeOpenAIClient(['Rome', judgment(1)])
            with patch.object(Benchmark.MemoryFactory, 'create_memory_module', side_effect=create), patch.object(Benchmark, 'client', fake):
                job.run()
            result = job.snapshot()
            self.assertEqual(result['status'], 'completed')
            self.assertEqual(result['cases'][0]['evidence_recall'], 1)
            self.assertNotIn('SECRET ANSWER', str(fake.calls[0]))
            self.assertEqual(result['progress']['completed'], 1)
        self.assertEqual(len(created), 2)
        for module in created:
            self.assertEqual(len(module.inspect()['entries']), 2)
            self.assertIn('Alice', module.inspect()['entries'][0]['text'])
            self.assertIn('1 May', module.inspect()['entries'][0]['text'])

    def test_cancellation_and_partial_failure(self):
        job = Benchmark.BenchmarkJob(fixture(), {'module': 'sliding_window'})
        original = Benchmark.direct_answer
        def stop(*args, **kwargs):
            result = original(*args, **kwargs)
            job.cancel.set()
            return result
        with patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')), patch.object(Benchmark, 'direct_answer', side_effect=stop):
            job.run()
        self.assertEqual(job.snapshot()['status'], 'cancelled')
        self.assertEqual(len(job.snapshot()['cases']), 1)
        job = Benchmark.BenchmarkJob(fixture(), {'module': 'summarization'})
        with patch.object(summary_module, 'call_api', side_effect=RuntimeError('failure')):
            job.run()
        self.assertEqual(len(job.snapshot()['errors']), 1)
        self.assertEqual(job.snapshot()['memories'][0]['memory']['entries'], [])
        self.assertEqual(job.snapshot()['scores'][0]['failure_counts']['ingestion_blocked'], 1)

    def test_cli_matches_shared_runner(self):
        with tempfile.TemporaryDirectory() as directory:
            dataset = directory + '/dataset.json'; output = directory + '/out.json'
            with open(dataset, 'w') as f:
                json.dump(fixture(), f)
            args = ['benchmark', '--dataset', dataset, '--output', output, '--modules', 'sliding_window', '--question-limit', '1']
            with patch.object(sys, 'argv', args), patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')):
                Benchmark.main()
            with open(output) as f:
                result = json.load(f)
            self.assertEqual(result['cases'][0]['score'], 1)
            self.assertEqual(result['config']['question_limit'], 1)
    def test_fact_adapter_preserves_speakers(self):
        with patch.object(Benchmark, 'call_api', return_value=('{}', 0, 1)) as call:
            Benchmark.benchmark_extractor('prompt', 'Alice and Bob')
        self.assertIn('Both named speakers', call.call_args.args[0])
        self.assertEqual(call.call_args.args[1], 'Alice and Bob')

if __name__ == '__main__':
    unittest.main()
