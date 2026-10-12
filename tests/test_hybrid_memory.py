"""Offline contract tests for independent hybrid stores and their public surfaces."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
sys.path.insert(0, 'src')
import Benchmark
import Summarization
import app
import ReAct
from Diagnostics import collector
from Embeddings import LocalEmbeddings
from HybridMemory import HYBRIDS, HYBRID_PACKING_POLICY, hybrid_settings
from MemoryContext import build_memory_context
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from benchmark_helpers import FakeTokenizer
from test_semantic_memory import FakeEmbeddings, extraction
from test_diagnostics_benchmark import fixture
from test_memory_integration import FakeOpenAIClient
from test_binary_benchmark import judgment


def temporal_extract(prompt, payload):
    turn = json.loads(payload)['turn']
    return extraction(dict(op='add', text=turn['text'],
                           source_ids=[turn['metadata']['dialogue_id']], supporting_version_ids=[]))


class HybridTests(unittest.TestCase):
    def make(self, mode='delta', **options):
        return MemoryFactory.create_memory_module(mode, embedder=FakeEmbeddings(),
                    tokenizer=FakeTokenizer(), **options)

    def test_independent_original_input_batch_and_detached_inspection(self):
        entries = list(Benchmark.conversation_entries(fixture()[0]['conversation']))
        for mode in HYBRIDS:
            with self.subTest(mode=mode):
                extractor = Mock(side_effect=temporal_extract)
                module = self.make(mode, extractor=extractor, fact_history_mode='versioned') if mode != 'delta' else self.make(mode)
                with patch.object(Summarization, 'call_api', return_value=('Summary', 0, 4)) as summary:
                    module.write_batch(entries)
                snapshot = module.inspect()
                if 'summarization' in module.components:
                    self.assertEqual(summary.call_count, 1)
                    self.assertIn('\n\n'.join(e.text for e in entries), summary.call_args.args[1])
                if 'vector_store' in module.components:
                    self.assertEqual([e['text'] for e in snapshot['components']['vector_store']['entries']], [e.text for e in entries])
                if 'fact_store' in module.components:
                    self.assertEqual(extractor.call_count, len(entries))
                    self.assertEqual([json.loads(c.args[1])['turn']['metadata']['dialogue_id'] for c in extractor.call_args_list], ['D1:1', 'D2:1'])
                snapshot['entries'][0]['text'] = 'mutated'
                snapshot['components'][next(iter(module.components))]['entries'][0]['text'] = 'mutated'
                self.assertNotEqual(module.inspect()['entries'][0]['text'], 'mutated')

    def test_atomic_rollback_retains_failed_call_usage(self):
        for mode in HYBRIDS:
            with self.subTest(mode=mode):
                module = self.make(mode, extractor=lambda *args: extraction(dict(op='add', text='cat')))
                with patch.object(Summarization, 'call_api', return_value=('old', 0, 3)):
                    module.write(MemoryEntry('old'))
                before = module.inspect()['components']
                last = module.components[HYBRIDS[mode][-1]]
                original_write = last.write
                def fail_after_write(entry):
                    original_write(entry)
                    raise RuntimeError('second component failed')
                metrics = dict(memory_llm_calls=0, memory_tokens=0)
                token = collector.set(metrics)
                try:
                    with patch.object(Summarization, 'call_api', return_value=('new', 0, 7)), patch.object(last, 'write', side_effect=fail_after_write):
                        with self.assertRaisesRegex(RuntimeError, 'second component'):
                            module.write(MemoryEntry('new'))
                finally:
                    collector.reset(token)
                self.assertEqual(module.inspect()['components'], before)
                if mode != 'zeta':
                    self.assertGreaterEqual(metrics['memory_tokens'], 7)

    def test_reserved_budget_spillover_and_finite_candidate_limits(self):
        module = self.make('zeta', extractor=lambda *a: extraction(dict(op='add', text='fact')),
                           component_options={'vector_store': {'retrieval_k': 1}, 'fact_store': {'retrieval_k': 1}})
        module.write(MemoryEntry('older'))
        module.write(MemoryEntry('newest'))
        packed = build_memory_context(module, 'query', 100, FakeTokenizer())
        self.assertEqual(packed['candidate_count'], 2)
        self.assertEqual(packed['included_count'], 2)
        self.assertEqual({e.metadata['component'] for e in packed['entries']}, {'vector_store', 'fact_store'})
        self.assertNotIn('older', packed['text'])
        self.assertEqual(packed['memory_context_tokens'], len(packed['text']))
        self.assertLessEqual(packed['memory_context_tokens'], 100)
        self.assertEqual(packed['packing_policy'], HYBRID_PACKING_POLICY)
        # The large record cannot use its reservation but can borrow an empty fact share.
        empty_facts = self.make('zeta', extractor=lambda *a: extraction(),
                               hybrid_shares={'vector_store': .2, 'fact_store': .8})
        empty_facts.write(MemoryEntry('x' * 60))
        packed = build_memory_context(empty_facts, 'query', 100, FakeTokenizer(), 1)
        self.assertEqual(packed['included_count'], 1)
        self.assertGreater(packed['components']['vector_store']['memory_context_tokens'], 20)
        # No candidate beyond k may be used to replace an oversized record.
        empty_facts.write(MemoryEntry('x' * 150))
        self.assertEqual(build_memory_context(empty_facts, 'query', 100, FakeTokenizer(), 1)['included_count'], 0)

    def test_summary_context_shortening_does_not_mutate_storage(self):
        module = self.make()
        with patch.object(Summarization, 'call_api', return_value=('S' * 180, 0, 1)):
            module.write(MemoryEntry('turn'))
        packed = build_memory_context(module, 'query', 200, FakeTokenizer())
        self.assertTrue(packed['context_truncated'])
        self.assertEqual(len(packed['entries']), 2)
        self.assertLessEqual(len(packed['text']), 200)
        self.assertEqual(module.components['summarization'].summary, 'S' * 180)
        # Whole records are skipped; tiny budgets must not emit broken labels.
        self.assertEqual(build_memory_context(module, 'query', 5, FakeTokenizer())['entries'], [])
        module.components['summarization'].summary = 'S' * 1000
        module.components['vector_store']._records = []
        packed = build_memory_context(module, 'query', 200, FakeTokenizer())
        self.assertGreater(len(packed['text']), 100)
        self.assertLessEqual(len(packed['text']), 200)

    def test_later_turn_failure_rolls_back_batch_evictions_and_fact_versions(self):
        extractor = Mock(side_effect=temporal_extract)
        module = self.make('zeta', extractor=extractor, fact_history_mode='versioned', max_stored_entries=1)
        turns = list(Benchmark.conversation_entries(fixture()[0]['conversation']))
        module.write(turns[0])
        before = module.inspect()['components']
        extractor.side_effect = [temporal_extract('', json.dumps({'turn': dict(text=turns[1].text, metadata=turns[1].metadata)})), RuntimeError('late failure')]
        with self.assertRaisesRegex(RuntimeError, 'late failure'):
            module.write_batch([turns[1], turns[0]])
        self.assertEqual(module.inspect()['components'], before)

    def test_settings_validation_and_component_capacity(self):
        for shares in ({}, {'vector_store': .5, 'fact_store': .6}, {'vector_store': True, 'fact_store': 0},
                       {'vector_store': float('nan'), 'fact_store': .5}):
            with self.assertRaises(ValueError):
                hybrid_settings('zeta', shares)
        for options in ({'summarization': {}}, {'vector_store': {'retrieval_k': 0}}, {'fact_store': {'unknown': 1}}):
            with self.assertRaises(ValueError):
                hybrid_settings('zeta', component_options=options)
        module = self.make('zeta', extractor=lambda *a: extraction(),
                           component_options={'vector_store': {'max_stored_entries': 1}})
        module.write(MemoryEntry('first')); module.write(MemoryEntry('second'))
        self.assertEqual(module.inspect()['config']['evicted_count'], 1)
        self.assertEqual(len(module.components['vector_store'].inspect()['entries']), 1)
        with self.assertRaises(ValueError):
            self.make('zeta', max_summary_tokens=5)


class HybridIntegrationTests(unittest.TestCase):
    def setUp(self):
        for target, name, value in ((Benchmark, 'get_benchmark_tokenizer', FakeTokenizer()),):
            patcher = patch.object(target, name, return_value=value)
            patcher.start(); self.addCleanup(patcher.stop)
        for name in ('chunks', 'embed'):
            patcher = patch.object(LocalEmbeddings, name, getattr(FakeEmbeddings(), name))
            patcher.start(); self.addCleanup(patcher.stop)

    def test_benchmarks_reach_qa_preserve_component_provenance_and_resume(self):
        for mode in HYBRIDS:
            with self.subTest(mode=mode):
                job = Benchmark.BenchmarkJob(fixture(), dict(module=mode, question_limit=1))
                with patch.object(Benchmark, 'call_api', side_effect=temporal_extract), patch.object(Summarization, 'call_api', return_value=('Alice lives in Rome', 0, 3)), patch.object(Benchmark, 'client', FakeOpenAIClient(['Rome', judgment(1)])):
                    job.run()
                result = job.snapshot()
                self.assertEqual(result['status'], 'completed', result.get('errors'))
                case = result['cases'][0]
                self.assertEqual(case['correct'], 1, case)
                self.assertEqual(set(case['component_evidence_recall']), set(HYBRIDS[mode]))
                self.assertLessEqual(case['diagnostics']['memory_context_tokens'], 2000)
                final = result['memories'][0]['ingestion']['final_storage']
                self.assertEqual(set(final['components']), set(HYBRIDS[mode]))
                self.assertEqual(Benchmark.BenchmarkJob.resume(fixture(), result).options, job.options)
                result['config']['hybrid_shares'] = dict(zip(HYBRIDS[mode], (.3, .7)))
                with self.assertRaisesRegex(ValueError, 'config_hash'):
                    Benchmark.BenchmarkJob.resume(fixture(), result)

    def test_chat_accepts_hybrid_settings_and_rejects_mid_chat_changes(self):
        client = app.app.test_client()
        self.addCleanup(app.chat_memory_modules.pop, 'hybrid-test', None)
        payload = dict(chat_id='hybrid-test', memory_module='delta', message='remember Rome',
                       memory_options=dict(hybrid_shares={'summarization': .3, 'vector_store': .7}, memory_context_tokens=200))
        with patch('MemoryContext.get_benchmark_tokenizer', return_value=FakeTokenizer()), patch.object(Summarization, 'call_api', return_value=('Rome', 0, 3)), patch.object(ReAct, 'client', FakeOpenAIClient()):
            response = client.post('/get', json=payload)
        self.assertEqual(response.status_code, 200, response.get_json())
        snapshot = client.get('/api/chats/hybrid-test/diagnostics').get_json()
        self.assertEqual(snapshot['memory']['config']['hybrid_shares']['summarization'], .3)
        payload['memory_options']['memory_context_tokens'] = 300
        self.assertEqual(client.post('/get', json=payload).status_code, 409)
        payload['chat_id'] = 'invalid-hybrid'
        payload['memory_options']['hybrid_shares']['summarization'] = -1
        self.assertEqual(client.post('/get', json=payload).status_code, 400)
        self.assertNotIn('invalid-hybrid', app.chat_memory_modules)

    def test_summary_batches_leave_facts_per_turn_and_preserve_session_boundaries(self):
        data = fixture()
        data[0]['conversation']['session_1'].extend([
            dict(speaker='Alice', text='I like cats', dia_id='D1:2'),
            dict(speaker='Alice', text='I like tea', dia_id='D1:3')])
        for mode in ('delta', 'epsilon'):
            job = Benchmark.BenchmarkJob(data, dict(module=mode, question_limit=1))
            with patch.object(Benchmark, 'call_api', side_effect=temporal_extract) as facts, patch.object(Summarization, 'call_api', return_value=('Summary', 0, 3)) as summary, patch.object(Benchmark, 'client', FakeOpenAIClient(['Rome', judgment(1)])):
                job.run()
            result = job.snapshot()
            self.assertEqual(result['cases'][0]['correct'], 1)
            self.assertEqual(summary.call_count, 2)
            self.assertIn('D1:3', summary.call_args_list[0].args[1])
            self.assertNotIn('D2:1', summary.call_args_list[0].args[1])
            self.assertEqual(result['memories'][0]['ingestion']['ingested_turns'], 4)
            if mode == 'epsilon':
                self.assertEqual(facts.call_count, 4)
                self.assertEqual(result['memories'][0]['ingestion']['memory_llm_calls'], 6)
            else:
                records = result['memories'][0]['memory']['components']['vector_store']['entries']
                self.assertEqual(len(records), 4)

    def test_cli_and_pages_expose_hybrids(self):
        for page in ('/chat', '/benchmark'):
            html = app.app.test_client().get(page).get_data(as_text=True)
            for mode in HYBRIDS:
                self.assertIn(f'value="{mode}"', html)
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'data.json', Path(directory)/'out.json'
            source.write_text(json.dumps(fixture()), encoding='utf-8')
            args = ['Benchmark.py', '--dataset', str(source), '--output', str(output), '--modules', 'zeta',
                    '--hybrid-shares', '{"vector_store":0.3,"fact_store":0.7}',
                    '--component-options', '{"vector_store":{"retrieval_k":2}}']
            with patch.object(sys, 'argv', args), patch.object(Benchmark.BenchmarkJob, 'run'):
                Benchmark.main()
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(saved['config']['hybrid_shares']['vector_store'], .3)
            self.assertEqual(saved['config']['component_options']['vector_store']['retrieval_k'], 2)


if __name__ == '__main__':
    unittest.main()
