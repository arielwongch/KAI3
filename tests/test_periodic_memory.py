"""Periodic windows, ordered fact batches, and embedded retrieval contracts."""
import json
import os
import sys
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')

import app
import Benchmark
import ReAct
import Summarization
from Diagnostics import collector
from MemoryConfig import RERANKED_MODULES
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from Reranker import RerankedMemory
from TemporalFactStore import TemporalFactStore
from VectorStore import VectorStore
from WindowHybridMemory import WindowedSummarization, WindowedFactStore
from benchmark_helpers import FakeTokenizer, offline_reranking
from test_binary_benchmark import judgment
from test_controlled_comparison import turn, add
from test_hybrid_integration import dataset
from test_memory_integration import FakeOpenAIClient
from test_semantic_memory import FakeEmbeddings, extraction


def setUpModule():
    offline_reranking()


def batch_response(*results):
    results = deepcopy(results)
    for source, ops in results:
        for index, op in enumerate(ops):
            if op['op'] in ('add', 'supersede', 'correct'):
                op.setdefault('result_ref', f'new:{source.replace(":", "_")}_{index}')
    return json.dumps({'turns': [dict(dialogue_id=source, operations=ops)
                               for source, ops in results]}), 0, 7


class PeriodicWindowTests(unittest.TestCase):
    def test_exact_k_updates_and_explicit_partial_flush_preserve_recent_entries(self):
        module = WindowedSummarization(max_items=3)
        with patch.object(Summarization, 'call_api', return_value=('summary', 0, 7)) as summarize:
            for i in range(8):
                module.write(MemoryEntry(str(i)))
                self.assertEqual(summarize.call_count, (i + 1) // 3)
            self.assertIn('New interaction:\n0\n\n1\n\n2', summarize.call_args_list[0].args[1])
            self.assertIn('New interaction:\n3\n\n4\n\n5', summarize.call_args_list[1].args[1])
            self.assertEqual([e.text for e in module.window.buffer], ['5', '6', '7'])
            self.assertEqual(module.inspect()['config']['pending_entries'], 2)
            self.assertEqual([e.text for e in module.retrieve('anything', 1)], ['summary', '5', '6', '7'])
            module.flush()
            module.flush()
            self.assertEqual(summarize.call_count, 3)
            self.assertIn('New interaction:\n6\n\n7', summarize.call_args.args[1])
            self.assertEqual(module.inspect()['config']['pending_entries'], 0)

    def test_failed_boundary_and_flush_leave_both_tiers_unchanged(self):
        module = WindowedSummarization(max_items=2)
        module.write(MemoryEntry('first'))
        before = module.inspect()
        with patch.object(Summarization, 'call_api', side_effect=RuntimeError('unavailable')):
            with self.assertRaises(RuntimeError):
                module.write(MemoryEntry('second'))
            self.assertEqual(module.inspect(), before)
            with self.assertRaises(RuntimeError):
                module.flush()
            self.assertEqual(module.inspect(), before)
        with patch.object(Summarization, 'call_api', return_value=('summary', 0, 0)):
            module.write(MemoryEntry('second'))
        self.assertEqual(module.inspect()['config']['pending_entries'], 0)

    def test_current_fact_batch_add_replace_remove_in_one_call(self):
        extractor = Mock(side_effect=[
            extraction({'op': 'add', 'text': 'cat'}, {'op': 'add', 'text': 'dog'}),
            extraction({'op': 'replace', 'id': 'fact-1', 'text': 'feline'},
                       {'op': 'remove', 'id': 'fact-2'}, {'op': 'add', 'text': 'bird'}),
        ])
        module = WindowedFactStore(max_items=2, embedder=FakeEmbeddings(), extractor=extractor)
        for text in ('I have a cat.', 'I have a dog.', 'My cat is a feline.', 'No dog; I have a bird.'):
            module.write(MemoryEntry('User: ' + text, {'user_text': text, 'assistant_text': 'context'}))
        self.assertEqual(extractor.call_count, 2)
        payload = json.loads(extractor.call_args.args[1])
        self.assertEqual([e['user_text'] for e in payload['interactions']],
                         ['My cat is a feline.', 'No dog; I have a bird.'])
        self.assertEqual(payload['interactions'][0]['assistant_context'], 'context')
        self.assertEqual([e['text'] for e in module.long_term.inspect()['entries']], ['feline', 'bird'])
        sources = module.long_term.inspect()['entries'][0]['metadata']['source']['source_turns']
        self.assertEqual(len(sources), 2)

    def test_fact_embedding_failure_rolls_back_pending_window_and_ids(self):
        embedder = FakeEmbeddings()
        module = WindowedFactStore(max_items=2, embedder=embedder,
                                   extractor=lambda *a: extraction({'op': 'add', 'text': 'cat'}))
        module.write(MemoryEntry('first'))
        before = module.inspect()
        with patch.object(embedder, 'embed', side_effect=RuntimeError('embedding failed')):
            with self.assertRaises(RuntimeError):
                module.write(MemoryEntry('second'))
        self.assertEqual(module.inspect(), before)
        module.write(MemoryEntry('second'))
        self.assertEqual(module.long_term.inspect()['entries'][0]['metadata']['fact_id'], 'fact-1')

    def test_blank_and_incomplete_entries_do_not_advance_interval(self):
        module = WindowedSummarization(max_items=2)
        module.write(MemoryEntry(' '))
        module.write(MemoryEntry('incomplete', {'completed': False}))
        self.assertEqual(module.inspect()['entries'], [])
        self.assertEqual(module.inspect()['config']['pending_entries'], 0)


class TemporalBatchTests(unittest.TestCase):
    def test_one_extraction_retains_ordered_changes_speakers_and_source_observations(self):
        extractor = Mock(return_value=batch_response(
            ('D1', [add('Bob works at Google.', 'D1')]),
            ('D2', [dict(op='supersede', id='new:D1_0', text='Bob works at Microsoft.',
                         source_ids=['D2'], supporting_version_ids=[])]),
            ('D3', [dict(op='retract', id='new:D2_0', source_ids=['D3'])]),
            ('D4', [add('Alice works at Google.', 'D4')]),
        ))
        store = TemporalFactStore(FakeEmbeddings(), extractor)
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            store.write_batch([turn('Google', 'D1'), turn('Microsoft', 'D2', session='session_2'),
                               turn('withdrawn', 'D3'), turn('Google', 'D4', speaker='Alice')])
        finally:
            collector.reset(token)
        self.assertEqual(extractor.call_count, 1)
        self.assertEqual(metrics, dict(memory_llm_calls=1, memory_tokens=7))
        entries = store.inspect()['entries']
        self.assertEqual([e['metadata']['status'] for e in entries], ['superseded', 'retracted', 'current'])
        self.assertEqual([e['metadata']['source_ids'] for e in entries], [['D1'], ['D2'], ['D4']])
        self.assertEqual(entries[0]['metadata']['observed_until']['session'], 'session_2')
        self.assertEqual(entries[1]['metadata']['transition_source_ids'], ['D3'])
        self.assertEqual(entries[2]['metadata']['speaker'], 'Alice')

    def test_invalid_later_turn_rejects_whole_batch(self):
        for second in (
            dict(op='retract', id='new:D1_0', source_ids=['wrong-source']),
            dict(op='retract', id='version-999', source_ids=['D2']),
        ):
            extractor = Mock(return_value=batch_response(('D1', [add('cat', 'D1')]), ('D2', [second])))
            store = TemporalFactStore(FakeEmbeddings(), extractor)
            before = store.inspect()
            with self.assertRaises(ValueError):
                store.write_batch([turn('cat', 'D1'), turn('withdrawn', 'D2')])
            self.assertEqual(store.inspect(), before)
            self.assertEqual(store._next_id, 1)

    def test_batch_cannot_change_other_speakers_version(self):
        store = TemporalFactStore(FakeEmbeddings(), Mock(return_value=batch_response(
            ('D1', [add('cat', 'D1')]),
            ('D2', [dict(op='retract', id='new:D1_0', source_ids=['D2'])]))))
        with self.assertRaises(ValueError):
            store.write_batch([turn('cat', 'D1'), turn('withdrawn', 'D2', speaker='Alice')])
        self.assertEqual(store.inspect()['entries'], [])


class EmbeddedRetrievalTests(unittest.TestCase):
    def test_factory_reranks_every_embedded_component_except_standalone_vector(self):
        for mode in RERANKED_MODULES:
            module = MemoryFactory.create_memory_module(mode, embedder=FakeEmbeddings(), candidate_k=3)
            stores = module.components.values() if hasattr(module, 'components') else [getattr(module, 'long_term', module)]
            embedded = [s for s in stores if hasattr(s, 'embedder')]
            self.assertTrue(embedded, mode)
            for store in embedded:
                self.assertIsInstance(store, RerankedMemory, mode)
                self.assertEqual(store.inspect()['config']['candidate_k'], 3)
        standalone = MemoryFactory.create_memory_module('vector_store', embedder=FakeEmbeddings())
        self.assertIs(type(standalone), VectorStore)
        self.assertNotIn('reranker', standalone.inspect()['config'])

    def test_current_and_historical_fact_shortlist_then_rerank_then_k(self):
        for history in ('current', 'versioned'):
            reranker = Mock(identity={'model': 'test'}, score=Mock(return_value=[-5, 9]))
            store = MemoryFactory.create_memory_module('fact_store', embedder=FakeEmbeddings(),
                        reranker=reranker, candidate_k=2, fact_history_mode=history,
                        extractor=Mock(return_value=extraction()))
            if history == 'current':
                store.extractor.return_value = extraction({'op': 'add', 'text': 'cat first'},
                        {'op': 'add', 'text': 'cat second'}, {'op': 'add', 'text': 'dog'})
                store.write(MemoryEntry('facts'))
            else:
                for i, text in enumerate(('cat first', 'cat second', 'dog')):
                    store.extractor.return_value = extraction(add(text, str(i)))
                    store.write(turn(text, str(i)))
            result = store.retrieve('cat', 1)
            self.assertEqual(len(reranker.score.call_args.args[1]), 2)
            self.assertEqual(len(result), 1)
            self.assertIn('cat first', result[0].text)
            self.assertEqual(result[0].metadata['vector_rank'], 2)
            self.assertEqual(result[0].metadata['retrieval_score'], 9)
            self.assertEqual(result[0].metadata['retrieval_score_type'], 'cross_encoder_logit')


class PeriodicIntegrationTests(unittest.TestCase):
    def test_benchmark_batches_cross_sessions_and_flush_before_qa(self):
        original = MemoryFactory.create_memory_module
        for mode in ('windowed_summarization', 'windowed_fact_store'):
            job = Benchmark.BenchmarkJob(dataset(), dict(module=mode, window_size=4))
            def create(selected, **options):
                return original(selected, **{**options, 'embedder': FakeEmbeddings()})
            def extract(prompt, payload):
                data = json.loads(payload)
                return batch_response(*[(e['metadata']['dialogue_id'],
                                        [add(e['text'], e['metadata']['dialogue_id'])]) for e in data['turns']])
            with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
                 patch.object(Benchmark.MemoryFactory, 'create_memory_module', side_effect=create), \
                 patch.object(Benchmark, 'call_api', side_effect=extract) as facts, \
                 patch.object(Summarization, 'call_api', return_value=('summary', 0, 7)) as summary, \
                 patch.object(Benchmark, 'client', FakeOpenAIClient(['cat', judgment(1)])):
                job.run()
            report = job.snapshot()
            self.assertEqual(report['status'], 'completed')
            self.assertEqual(report['ingestion_outcome']['status'], 'successful')
            self.assertEqual(report['cases'][0]['correct'], 1)
            memory = report['memories'][0]
            self.assertEqual(memory['ingestion']['memory_llm_calls'], 2)
            self.assertEqual(memory['ingestion']['memory_tokens'], 14)
            self.assertEqual(memory['memory']['config']['pending_entries'], 0)
            self.assertEqual(len([e for e in memory['memory']['entries'] if e['metadata']['memory_tier'] == 'recent']), 4)
            if mode == 'windowed_fact_store':
                self.assertEqual([len(json.loads(c.args[1])['turns']) for c in facts.call_args_list], [4, 2])
                legacy = deepcopy(report)
                legacy['memory_batch_settings'].pop('extraction')
                with self.assertRaisesRegex(ValueError, 'memory_batch_settings'):
                    Benchmark.BenchmarkJob.resume(dataset(), legacy)
            else:
                self.assertIn('D2:0', summary.call_args_list[0].args[1])
                self.assertNotIn('D2:1', summary.call_args_list[0].args[1])
            self.assertEqual(report['cases'][0]['diagnostics']['stored_before'], report['cases'][0]['diagnostics']['stored_after'])
            Benchmark.BenchmarkJob.resume(dataset(), report)
            changed = deepcopy(report)
            changed['memory_batch_settings']['flush'] = 'never'
            with self.assertRaises(ValueError):
                Benchmark.BenchmarkJob.resume(dataset(), changed)

    def test_chat_pickers_k_and_reranker_settings_are_fixed_per_session(self):
        app.chat_memory_modules.clear()
        self.addCleanup(app.chat_memory_modules.clear)
        client = app.app.test_client()
        for mode in ('windowed_summarization', 'windowed_fact_store'):
            for path in ('/chat', '/benchmark'):
                self.assertIn(mode, client.get(path).get_data(as_text=True))
            payload = dict(message='cat', chat_id=mode, memory_module=mode, window_size=2)
            with patch.object(ReAct, 'client', FakeOpenAIClient()):
                self.assertEqual(client.post('/get', json=payload).status_code, 200)
            snapshot = client.get('/api/chats/' + mode).json
            self.assertEqual(snapshot['window_size'], 2)
            self.assertEqual(snapshot['memory']['config']['pending_entries'], 1)
            self.assertEqual(client.post('/get', json={**payload, 'window_size': 3}).status_code, 409)

    def test_resume_rejects_pre_reranker_fact_protocol(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='fact_store'))
        previous = job.snapshot()
        previous.pop('reranker')
        previous['config'].pop('candidate_k')
        with self.assertRaises(ValueError):
            Benchmark.BenchmarkJob.resume(dataset(), previous)
