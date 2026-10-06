"""Offline regressions for the repository audit; never use real credentials."""
import os
import io
import runpy
import sys
import tempfile
import unittest
from itertools import permutations
from pathlib import Path
from unittest.mock import Mock, patch

os.environ['DEEPSEEK_API_KEY'] = 'test-only'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
sys.path.insert(0, 'src')
import app
import Benchmark
from BenchmarkStore import atomic_json, path_for
from test_benchmark_recovery import dataset
from test_memory_integration import FakeOpenAIClient
from test_binary_benchmark import judgment
from FactStore import FactStore
from MemoryEntry import MemoryEntry
from test_semantic_memory import FakeEmbeddings, extraction


class PublicAssetTests(unittest.TestCase):
    def test_private_files_are_not_served(self):
        # Sentinel files make this safe even before the exposure is fixed.
        with tempfile.TemporaryDirectory() as directory:
            for name in ('.env', '.env.example', 'app.py', 'index.html'):
                Path(directory, name).write_text('private sentinel', encoding='utf-8')
            with patch.object(app.app, 'root_path', directory):
                for name in ('.env', '.env.example', 'app.py', 'index.html'):
                    with self.subTest(name=name):
                        response = app.app.test_client().get('/' + name)
                        try:
                            self.assertEqual(response.status_code, 404)
                        finally:
                            response.close()

    def test_pages_and_public_assets_load(self):
        client = app.app.test_client()
        for path in ('/', '/chat', '/benchmark', '/style.css', '/workspace.js', '/assets/favicon.png'):
            with self.subTest(path=path):
                response = client.get(path)
                try:
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.data)
                finally:
                    response.close()

    def test_default_host_is_loopback(self):
        with patch.dict(os.environ, {}, clear=False), patch.object(app.app, 'run') as run:
            os.environ.pop('HOST', None)
            app.main()
        self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')


class FactBatchTests(unittest.TestCase):
    def test_interacting_operations_are_order_independent(self):
        batches = [
            ([{'op': 'replace', 'id': 'fact-1', 'text': 'B'},
              {'op': 'replace', 'id': 'fact-2', 'text': 'C'}], ['B', 'C']),
            ([{'op': 'replace', 'id': 'fact-1', 'text': 'B'},
              {'op': 'remove', 'id': 'fact-2'}], ['B']),
            ([{'op': 'replace', 'id': 'fact-1', 'text': 'B'},
              {'op': 'replace', 'id': 'fact-2', 'text': 'A'}], ['A', 'B']),
            ([{'op': 'add', 'text': 'B'},
              {'op': 'replace', 'id': 'fact-2', 'text': 'C'}], ['A', 'B', 'C']),
            ([{'op': 'add', 'text': 'B'},
              {'op': 'remove', 'id': 'fact-2'}], ['A', 'B']),
            ([{'op': 'replace', 'id': 'fact-1', 'text': 'C'},
              {'op': 'replace', 'id': 'fact-2', 'text': 'C'},
              {'op': 'add', 'text': ' c '}], ['C']),
        ]
        for operations, expected in batches:
            snapshots = []
            for ordering in permutations(operations):
                with self.subTest(operations=ordering):
                    extractor = Mock(side_effect=[
                        extraction({'op': 'add', 'text': 'A'}, {'op': 'add', 'text': 'B'}),
                        extraction(*ordering),
                    ])
                    store = FactStore(FakeEmbeddings(), extractor)
                    store.write(MemoryEntry('initial'))
                    store.write(MemoryEntry('update'))
                    entries = store.inspect()['entries']
                    self.assertEqual(sorted(e['text'] for e in entries), expected)
                    snapshots.append(entries)
                    # No stale vectors or removed IDs survive the transaction.
                    self.assertEqual(sorted(e.text for e in store.retrieve('facts', 10)), expected)
            self.assertTrue(all(s == snapshots[0] for s in snapshots))

    def test_embedding_failure_rolls_back_entire_batch(self):
        extractor = Mock(side_effect=[
            extraction({'op': 'add', 'text': 'A'}, {'op': 'add', 'text': 'B'}),
            extraction({'op': 'replace', 'id': 'fact-1', 'text': 'B'},
                       {'op': 'remove', 'id': 'fact-2'}),
        ])
        embedder = FakeEmbeddings()
        store = FactStore(embedder, extractor, max_stored_entries=2)
        store.write(MemoryEntry('initial'))
        before = store.inspect()
        with patch.object(embedder, 'embed', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                store.write(MemoryEntry('update'))
        self.assertEqual(store.inspect(), before)


class BenchmarkRegressionTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = directory.name
        for name, value in (('RUN_STORE', self.root), ('jobs', {})):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.app.test_client()
        logger = patch.object(app.app.logger, 'exception')
        logger.start()
        self.addCleanup(logger.stop)

    def test_start_failures_do_not_block_later_runs(self):
        for background in (False, True):
            for failure in ('snapshot', 'input', 'launch'):
                with self.subTest(background=background, failure=failure):
                    def write(path, value):
                        if failure == 'snapshot' or (failure == 'input' and str(path).endswith('.input.json')):
                            raise PermissionError('test disk failure')
                        atomic_json(path, value)
                    with patch.object(app, 'atomic_json', side_effect=write), \
                         patch.object(app, 'launch', side_effect=OSError('test launch failure')), \
                         patch.object(app, 'Thread') as thread:
                        thread.return_value.start.side_effect = RuntimeError('test thread failure')
                        response = self.client.post('/api/benchmarks', json={
                            'dataset': dataset(), 'options': {'module': 'full_context', 'background': background}})
                    self.assertEqual(response.status_code, 503)
                    run_id = response.json['run_id']
                    self.assertEqual(self.client.get('/api/benchmarks/' + run_id).json['status'], 'failed')
                    self.assertFalse(any(j.result['status'] in ('queued', 'running') for j in app.jobs.values()))
                    # A real subsequent job can finish, even if a stale queued
                    # snapshot remains on disk from the failed startup.
                    empty = dataset(); empty[0]['qa'] = []
                    with patch.object(app, 'Thread', InlineWorker):
                        retry = self.client.post('/api/benchmarks', json={
                            'dataset': empty, 'options': {'module': 'full_context'}})
                    self.assertEqual(retry.status_code, 202)
                    self.assertEqual(app.jobs[retry.json['run_id']].result['status'], 'completed')

    def test_first_worker_checkpoint_failure_is_terminal(self):
        previous_cancel = Benchmark.cancel_event.get()
        calls = 0
        def write(path, value):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise PermissionError('disk failed after starting thread')
            atomic_json(path, value)
        with patch.object(app, 'atomic_json', side_effect=write), patch.object(app, 'Thread', InlineWorker):
            response = self.client.post('/api/benchmarks', json={
                'dataset': dataset(), 'options': {'module': 'full_context'}})
        self.assertEqual(app.jobs[response.json['run_id']].result['status'], 'failed')
        self.assertIs(Benchmark.cancel_event.get(), previous_cancel)

    def test_numeric_and_string_selections_execute_the_same_questions(self):
        data = dataset(); data[0]['sample_id'] = 123
        for selection in ([123], ['123']):
            with self.subTest(selection=selection):
                job = Benchmark.BenchmarkJob(data, {'module': 'full_context', 'sample_ids': selection, 'question_limit': 1})
                fake = FakeOpenAIClient(['Rome', judgment(1)])
                with patch.object(Benchmark, 'client', fake):
                    job.run()
                self.assertEqual(job.options['sample_ids'], ['123'])
                self.assertEqual(len(job.result['question_manifest']), 1)
                self.assertEqual(len(job.result['cases']), 1)
                self.assertEqual(len(fake.calls), 2)
                self.assertEqual(job.result['status'], 'completed')
                self.assertEqual(data[0]['sample_id'], 123)
        duplicate = data + [{**data[0], 'sample_id': '123'}]
        with self.assertRaisesRegex(ValueError, 'unique'):
            Benchmark.BenchmarkJob(duplicate)

    def saved_run(self, persist_input=True):
        data = dataset(); data[0]['qa'] = []
        job = Benchmark.BenchmarkJob(data, {'module': 'full_context'})
        job.result['status'] = 'interrupted'
        if persist_input:
            atomic_json(path_for(self.root, job.result['run_id'], '.input.json'), {'dataset': data, 'snapshot': job.snapshot()})
        app.jobs[job.result['run_id']] = Benchmark.BenchmarkJob.restore(job.snapshot())
        return job, data

    def test_resume_prefers_original_persisted_dataset(self):
        job, original = self.saved_run()
        unrelated = dataset(); unrelated[0]['sample_id'] = 'bundled'
        with patch.object(app, 'Thread', InlineWorker):
            response = self.client.post('/api/benchmarks/' + job.result['run_id'] + '/resume', json={'dataset': unrelated})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(app.jobs[job.result['run_id']].data, original)
        self.assertEqual(app.jobs[job.result['run_id']].result['status'], 'completed')

    def test_missing_dataset_requests_upload_then_validates_it(self):
        job, original = self.saved_run(persist_input=False)
        url = '/api/benchmarks/' + job.result['run_id'] + '/resume'
        response = self.client.post(url, json={})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json['code'], 'dataset_required')
        wrong = dataset(); wrong[0]['sample_id'] = 'wrong'
        self.assertEqual(self.client.post(url, json={'dataset': wrong}).status_code, 400)
        with patch.object(app, 'Thread', InlineWorker):
            self.assertEqual(self.client.post(url, json={'dataset': original}).status_code, 202)

    def test_resume_start_failure_is_terminal_and_retryable(self):
        job, _ = self.saved_run()
        url = '/api/benchmarks/' + job.result['run_id'] + '/resume'
        with patch.object(app, 'atomic_json', side_effect=PermissionError('disk unavailable')):
            response = self.client.post(url, json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(app.jobs[job.result['run_id']].result['status'], 'failed')
        with patch.object(app, 'Thread', InlineWorker):
            self.assertEqual(self.client.post(url, json={}).status_code, 202)


class InlineWorker:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class TerminalStartupTests(unittest.TestCase):
    def test_start_metrics_and_quit_without_provider_calls(self):
        output = io.StringIO()
        with patch('dotenv.load_dotenv'), patch('openai.OpenAI') as client, \
             patch('builtins.input', side_effect=['', 'metrics', 'quit']), \
             patch('sys.stdout', output):
            runpy.run_path('src/TerminalInterface.py', run_name='__main__')
        client.return_value.chat.completions.create.assert_not_called()
        self.assertIn('No performance metrics to display.', output.getvalue())
        self.assertIn('Exiting...', output.getvalue())
