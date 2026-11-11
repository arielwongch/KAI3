"""Chat settings and reproducible hybrid benchmark ingestion and retrieval."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
import ReAct
import Summarization
from MemoryFactory import MemoryFactory
from BenchmarkStore import read_json
from test_binary_benchmark import judgment
from benchmark_helpers import FakeTokenizer
from test_memory_integration import FakeOpenAIClient
from test_semantic_memory import FakeEmbeddings, extraction


def dataset():
    return [dict(sample_id='one', conversation={
        'session_1_date_time': '1 May 2024',
        'session_1': [dict(speaker='Alice', text=f'cat {i}', dia_id=f'D1:{i}') for i in range(3)],
        'session_2_date_time': '2 May 2024',
        'session_2': [dict(speaker='Bob', text=f'dog {i}', dia_id=f'D2:{i}') for i in range(3)],
    }, qa=[dict(question='What pets?', answer='cat', category=4, evidence=['D1:0', 'D2:2'])])]



def setUpModule():
    from benchmark_helpers import offline_reranking
    offline_reranking()


class HybridChatTests(unittest.TestCase):
    def setUp(self):
        app.chat_memory_modules.clear()
        self.addCleanup(app.chat_memory_modules.clear)
        self.client = app.app.test_client()
        original = MemoryFactory.create_memory_module
        def create(mode, **kwargs):
            return original(mode, **{**kwargs, 'embedder': FakeEmbeddings(), 'extractor': lambda *a: extraction()})
        self.factory = patch.object(app.MemoryFactory, 'create_memory_module', side_effect=create)
        self.factory.start()
        self.addCleanup(self.factory.stop)
        self.fake = FakeOpenAIClient()
        for patcher in (patch.object(ReAct, 'client', self.fake),
                        patch.object(Summarization, 'call_api', return_value=('summary', 0, 7))):
            patcher.start()
            self.addCleanup(patcher.stop)

    def send(self, mode='alpha', chat='one', **options):
        return self.client.post('/get', json=dict(message='cat', chat_id=chat, memory_module=mode, **options))

    def test_all_pickers_and_configurable_isolated_sessions(self):
        for page in ('/chat', '/benchmark'):
            html = self.client.get(page).get_data(as_text=True)
            for mode in ('alpha', 'beta', 'gamma'):
                self.assertIn(f'data-module="{mode}"', html)
                self.assertIn(f'value="{mode}"', html)
            self.assertIn('id="chatWindowSize"', html)
            self.assertIn('id="benchmarkWindowSize"', html)
        for mode in ('alpha', 'beta', 'gamma', 'sliding_window'):
            for _ in range(3):
                self.assertEqual(self.send(mode, mode, window_size=2).status_code, 200)
            snapshot = self.client.get(f'/api/chats/{mode}/export').json
            self.assertEqual(snapshot['window_size'], 2)
            self.assertEqual(snapshot['memory']['config']['max_items'], 2)
            self.assertEqual(snapshot['turns'][-1]['retrieved_count'], 2)
            self.assertEqual(self.send(mode, mode + '-other').status_code, 200)
            other = self.client.get(f'/api/chats/{mode}-other').json
            self.assertEqual(other['window_size'], 10)
            self.assertEqual(other['turns'][0]['retrieved_count'], 0)

    def test_settings_validation_and_immutability(self):
        for value in (0, -1, True, 1.5, '2', None):
            self.assertEqual(self.send(window_size=value).status_code, 400)
        for mode in ('summarization', 'vector_store', 'fact_store', 'no_memory'):
            self.assertEqual(self.send(mode, window_size=2).status_code, 400)
        self.assertEqual(self.send(window_size=2).status_code, 200)
        self.assertEqual(self.send(window_size=3).status_code, 409)
        self.assertEqual(self.send('beta', window_size=2).status_code, 409)
        self.assertEqual(self.send().status_code, 200)
        self.assertEqual(self.client.get('/api/chats/one').json['window_size'], 2)
        app.chat_memory_modules.clear()
        self.assertEqual(self.send(requires_existing=True).status_code, 410)

    def test_standalone_chat_supplies_full_window_larger_than_five(self):
        for _ in range(7):
            self.assertEqual(self.send('sliding_window', window_size=6).status_code, 200)
        snapshot = self.client.get('/api/chats/one').json
        self.assertEqual(snapshot['retrieval_k'], 6)
        self.assertEqual(snapshot['turns'][-1]['retrieved_count'], 6)
        self.assertEqual(len(app.chat_memory_modules['one'].module.retrieve('', 1)), 1)


class HybridBenchmarkTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.object(Benchmark, "get_benchmark_tokenizer", return_value=FakeTokenizer())
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_job(self, mode, **options):
        job = Benchmark.BenchmarkJob(dataset(), dict(module=mode, window_size=2, **options))
        original = MemoryFactory.create_memory_module
        modules = []
        def create(selected, **kwargs):
            module = original(selected, **{**kwargs, 'embedder': FakeEmbeddings()})
            modules.append(module)
            return module
        with patch.object(Benchmark.MemoryFactory, 'create_memory_module', side_effect=create), patch.object(Benchmark, 'call_api', return_value=extraction()) as extract, patch.object(Summarization, 'call_api', return_value=('summary', 0, 7)) as summarize, patch.object(Benchmark, 'client', FakeOpenAIClient(['cat', judgment(1)])) as client:
            job.run()
        return job, modules[0], extract, summarize, client

    def test_hybrid_runs_accounting_context_evidence_and_no_qa_writeback(self):
        for mode in ('alpha', 'beta', 'gamma'):
            with self.subTest(mode=mode):
                job, module, extract, summarize, client = self.run_job(mode)
                report = job.snapshot()
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(report['config']['window_size'], 2)
                self.assertEqual(report['retrieval_policy']['window_size'], 2)
                self.assertEqual(report['hybrid_context_version'], 3)
                memory = report['memories'][0]
                case = report['cases'][0]
                self.assertEqual(case['correct'], 1)
                self.assertEqual(case['diagnostics']['stored_before'], case['diagnostics']['stored_after'])
                self.assertEqual(memory['memory'], module.inspect())
                self.assertEqual(memory['ingestion']['ingested_turns'], 6)
                recent = [e for e in memory['memory']['entries'] if e['metadata']['memory_tier'] == 'recent']
                self.assertEqual([e['metadata']['dialogue_id'] for e in recent], ['D2:1', 'D2:2'])
                prompt = client.calls[0]['messages'][1]['content']
                self.assertIn('Explicit recent corrections supersede older statements', prompt)
                self.assertIn('Recent conversation (oldest to newest)', prompt)
                if mode == 'alpha':
                    self.assertEqual(summarize.call_count, 2)
                    self.assertEqual(memory['ingestion']['memory_llm_calls'], 2)
                    self.assertEqual(memory['ingestion']['memory_tokens'], 14)
                    evicted = '\n\n'.join(c.args[1].split('New interaction:\n')[1] for c in summarize.call_args_list)
                    turns = list(Benchmark.conversation_entries(dataset()[0]['conversation']))
                    self.assertEqual(evicted, '\n\n'.join(e.text for e in turns[:-2]))
                    self.assertEqual(report['memory_batch_settings']['max_turns'], 20)
                    self.assertIsNone(case.get('evidence_recall'))
                elif mode == 'beta':
                    self.assertEqual(case['evidence_recall'], 1)
                    self.assertEqual(case['diagnostics']['retrieved_count'], 6)
                    self.assertEqual(memory['ingestion']['memory_llm_calls'], 0)
                    self.assertEqual(memory['ingestion']['final_storage']['embedding_chunks'], 12)
                else:
                    self.assertEqual(extract.call_count, 6)
                    self.assertEqual(memory['ingestion']['memory_llm_calls'], 6)
                    self.assertEqual(report['memory_model'], 'deepseek-flash')
                    self.assertIn('Both named speakers', extract.call_args.args[0])
                    payload = json.loads(extract.call_args.args[1])
                    self.assertIn('Bob', payload['turn']['text'])
                    self.assertIn('2 May 2024', payload['turn']['text'])
                    self.assertIsNone(case.get('evidence_recall'))

    def test_validation_defaults_and_old_resume_compatibility(self):
        for mode in ('alpha', 'beta', 'gamma', 'sliding_window'):
            job = Benchmark.BenchmarkJob(dataset(), dict(module=mode))
            self.assertEqual(job.options.get('window_size', job.options.get('max_stored_entries')), 100 if mode != 'sliding_window' else 10)
            for value in (0, -1, True, 1.2, '3', None):
                with self.assertRaises(ValueError):
                    Benchmark.BenchmarkJob(dataset(), dict(module=mode, window_size=value))
        for mode in ('summarization', 'vector_store', 'fact_store', 'no_memory'):
            with self.assertRaises(ValueError):
                Benchmark.BenchmarkJob(dataset(), dict(module=mode, window_size=2))
        old = Benchmark.BenchmarkJob(dataset(), dict(module='sliding_window')).snapshot()
        old['config'].pop('window_size', None)
        self.assertEqual(Benchmark.BenchmarkJob.resume(dataset(), old).options['max_stored_entries'], 10)

    def test_resume_restore_and_exports_preserve_settings(self):
        for mode in ('alpha', 'beta', 'gamma'):
            job, _, _, _, _ = self.run_job(mode, summary_batch_size=2)
            saved = json.loads(json.dumps(job.snapshot()))
            restored = Benchmark.BenchmarkJob.restore(saved)
            self.assertEqual(restored.snapshot(), saved)
            resumed = Benchmark.BenchmarkJob.resume(dataset(), saved)
            self.assertEqual(resumed.options['window_size'], 2)
            self.assertEqual(resumed.options['summary_batch_size'], 2)
            self.assertEqual(resumed.result['retrieval_policy'], saved['retrieval_policy'])
            with patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('Completed answer repeated')):
                resumed.run()
            self.assertEqual(resumed.snapshot()['cases'], saved['cases'])

    def test_alpha_failed_batch_does_not_commit_or_count_turns(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='alpha', window_size=2))
        with patch.object(Summarization, 'call_api', side_effect=RuntimeError('offline')):
            job.run()
        saved = job.snapshot()
        self.assertEqual(saved['memories'][0]['memory']['entries'], [])
        self.assertEqual(saved['memories'][0]['ingestion']['ingested_turns'], 0)
        self.assertEqual(saved['errors'][0]['phase'], 'ingestion')
        self.assertTrue(all(c['diagnostics']['status'] == 'ingestion_blocked' for c in saved['cases']))

    def test_alpha_cancellation_keeps_only_completed_batch(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='alpha', window_size=2))
        def summarize(*args):
            job.cancel.set()
            return ('summary', 0, 2)
        with patch.object(Summarization, 'call_api', side_effect=summarize):
            job.run()
        saved = job.snapshot()
        self.assertEqual(saved['status'], 'cancelled')
        self.assertEqual(saved['memories'][0]['ingestion']['ingested_turns'], 3)
        self.assertEqual(saved['progress']['ingestion_completed'], 3)
        self.assertEqual(len(saved['memories'][0]['memory']['entries']), 3)
        self.assertTrue(all(c['diagnostics']['status'] == 'ingestion_blocked' for c in saved['cases']))

    def test_background_input_and_resume_api_preserve_window_size(self):
        app.jobs.clear()
        self.addCleanup(app.jobs.clear)
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RUN_STORE', directory), patch.object(app, 'launch') as launch:
            client = app.app.test_client()
            response = client.post('/api/benchmarks', json=dict(dataset=dataset(), options=dict(module='alpha', window_size=3, background=True)))
            self.assertEqual(response.status_code, 202)
            run_id = response.json['run_id']
            job = launch.call_args.args[1]
            self.assertEqual(job.options['window_size'], 3)
            saved = read_json(Path(directory) / f'{run_id}.input.json')
            restored = Benchmark.BenchmarkJob.resume(saved['dataset'], saved['snapshot'])
            self.assertEqual(restored.options['window_size'], 3)
            self.assertTrue(restored.options['background'])
            export = client.get(f'/api/benchmarks/{run_id}/export').json
            self.assertEqual(export['config']['window_size'], 3)
            self.assertEqual(export['retrieval_policy']['window_size'], 3)

    def test_cli_window_size_and_hybrid_export(self):
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory) / 'dataset.json', Path(directory) / 'report.json'
            source.write_text(json.dumps(dataset()))
            argv = ['benchmark', '--dataset', str(source), '--output', str(output), '--modules', 'alpha', '--window-size', '2']
            with patch.object(sys, 'argv', argv), patch.object(Summarization, 'call_api', return_value=('summary', 0, 2)), patch.object(Benchmark, 'client', FakeOpenAIClient(['cat', judgment(1)])):
                Benchmark.main()
            saved = json.loads(output.read_text())
            self.assertEqual(saved['status'], 'completed')
            self.assertEqual(saved['config']['window_size'], 2)
            self.assertEqual(saved['config']['modules'], ['alpha'])


if __name__ == '__main__':
    unittest.main()
