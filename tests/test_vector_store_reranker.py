import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')

import app
import Benchmark
import ReAct
import Reranker
from Embeddings import LocalEmbeddings
from MemoryContext import build_memory_context
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from VectorStoreReranker import VectorStoreReranker
from benchmark_helpers import FakeTokenizer
from test_semantic_memory import FakeEmbeddings
from test_memory_integration import FakeOpenAIClient
from test_diagnostics_benchmark import fixture
from test_binary_benchmark import judgment


class RerankedStoreTests(unittest.TestCase):
    def make(self, **kwargs):
        return VectorStoreReranker(embedder=FakeEmbeddings(), **kwargs)

    def test_shortlist_then_rerank_then_k_preserving_provenance_and_copies(self):
        reranker = Mock(score=Mock(return_value=[-4., 8.]))
        store = self.make(reranker=reranker, candidate_k=2)
        original = MemoryEntry('cat correct', {'dialogue_id': 'D1', 'nested': {'x': 1}})
        store.write(original)
        store.write(MemoryEntry('cat distractor'))
        store.write(MemoryEntry('unrelated'))
        original.metadata['nested']['x'] = 2
        result = store.retrieve('feline', 1)
        reranker.score.assert_called_once_with('feline', ['cat distractor', 'cat correct'])
        self.assertEqual(result[0].text, 'cat correct')
        self.assertEqual(result[0].metadata['dialogue_id'], 'D1')
        self.assertEqual(result[0].metadata['nested']['x'], 1)
        self.assertEqual(result[0].metadata['vector_rank'], 2)
        self.assertEqual(result[0].metadata['vector_score'], 1.)
        self.assertEqual(result[0].metadata['retrieval_rank'], 1)
        self.assertEqual(result[0].metadata['retrieval_score'], 8.)
        self.assertEqual(result[0].metadata['retrieval_score_type'], 'cross_encoder_logit')
        result[0].metadata['nested']['x'] = 99
        self.assertEqual(store.inspect()['entries'][0]['metadata']['nested']['x'], 1)
        self.assertNotIn('retrieval_rank', store.inspect()['entries'][0]['metadata'])

    def test_all_candidates_ties_and_empty_queries(self):
        reranker = Mock(score=lambda q, texts: [0.] * len(texts))
        store = self.make(reranker=reranker, candidate_k=None)
        self.assertEqual(store.retrieve('cat'), [])
        for i in range(55):
            store.write(MemoryEntry(f'cat {i}'))
        self.assertEqual(store.retrieve('   '), [])
        self.assertEqual(len(store.iter_context_candidates('cat')), 55)
        self.assertEqual([e.text for e in store.retrieve('cat', 2)], ['cat 54', 'cat 53'])
        store.candidate_k = 50
        self.assertEqual(len(store.iter_context_candidates('cat')), 50)

    def test_lazy_inspect_capacity_and_write_failure(self):
        with patch.object(Reranker, '_load_model', side_effect=AssertionError('model loaded')):
            store = self.make(max_stored_entries=1)
            self.assertEqual(store.retrieve('cat'), [])
            store.write(MemoryEntry('cat old'))
            store.write(MemoryEntry('cat new'))
            snapshot = store.inspect()
            self.assertEqual(snapshot['config']['evicted_count'], 1)
            self.assertEqual(snapshot['config']['reranker'], Reranker.reranker_identity())
            snapshot['config']['reranker']['model'] = 'mutated'
            self.assertEqual(store.inspect()['config']['reranker']['model'], Reranker.MODEL_NAME)
            with patch.object(store.embedder, 'embed', side_effect=RuntimeError('embedding failed')):
                with self.assertRaises(RuntimeError):
                    store.write(MemoryEntry('cat broken'))
            self.assertEqual(store.inspect()['entries'][0]['text'], 'cat new')
            self.assertEqual(store.inspect()['config']['evicted_count'], 1)

    def test_errors_preserve_storage_and_do_not_fallback(self):
        reranker = Mock()
        store = self.make(reranker=reranker)
        store.write(MemoryEntry('cat'))
        for invalid in ([], [float('nan')], [float('inf')], [1, 2]):
            reranker.score.return_value = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                store.retrieve('cat')
        reranker.score.side_effect = RuntimeError('model unavailable')
        with self.assertRaisesRegex(RuntimeError, 'model unavailable'):
            store.retrieve('cat')
        self.assertEqual(store.inspect()['entries'][0]['text'], 'cat')

    def test_whole_turn_packing_applies_after_reranked_k(self):
        store = self.make(reranker=Mock(score=lambda q, texts: [len(t) for t in texts]))
        store.write(MemoryEntry('cat short'))
        store.write(MemoryEntry('cat ' + 'x' * 1000))
        packed = build_memory_context(store, 'cat', 50, FakeTokenizer(), 1)
        self.assertEqual(packed['entries'], [])
        self.assertTrue(packed['all_candidates_over_budget'])
        packed = build_memory_context(store, 'cat', 50, FakeTokenizer(), 2)
        self.assertEqual([e.text for e in packed['entries']], ['cat short'])

    def test_validation_and_factory_isolation(self):
        for value in (0, -1, True, 1.5, 'all'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.make(candidate_k=value)
        store = MemoryFactory.create_memory_module('vector_store_reranker', embedder=FakeEmbeddings(), candidate_k=None)
        self.assertIsInstance(store, VectorStoreReranker)
        for value in (0, True, None):
            with self.assertRaises(ValueError):
                store.retrieve('q', value)
        for mode in ('vector_store', 'fact_store', 'sliding_window', 'summarization', 'delta'):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                MemoryFactory.create_memory_module(mode, candidate_k=5)


class WindowTokenizer(FakeTokenizer):
    def num_special_tokens_to_add(self, pair=False):
        return 3 if pair else 2


class LocalRerankerTests(unittest.TestCase):
    def test_bounded_batches_long_query_and_late_document_evidence(self):
        seen = []
        def predict(pairs, **kwargs):
            self.assertLessEqual(len(pairs), Reranker.BATCH_SIZE)
            seen.extend(pairs)
            for query, document in pairs:
                self.assertLessEqual(len(query), Reranker.MAX_QUERY_TOKENS)
                self.assertLessEqual(len(query) + len(document) + 3, Reranker.MAX_LENGTH)
            return [10. if 'secret' in document else -3. for query, document in pairs]
        model = SimpleNamespace(tokenizer=WindowTokenizer(), predict=predict)
        with patch.object(Reranker, '_load_model', return_value=model) as load:
            reranker = Reranker.LocalReranker()
            self.assertEqual(reranker.score('q', []), [])
            load.assert_not_called()
            scores = reranker.score('q' * 1000, ['a' * 15000 + ' secret', 'unrelated'])
        self.assertEqual(scores, [10., -3.])
        self.assertGreater(len(seen), Reranker.BATCH_SIZE)
        self.assertEqual(seen[0][1][-32:], seen[1][1][:32])

    def test_decode_expansion_rechecked_without_losing_tail(self):
        class ExpandingTokenizer(WindowTokenizer):
            def decode(self, tokens, **kwargs):
                return ''.join(tokens) + '!!'
        tokenizer = ExpandingTokenizer()
        pairs = list(Reranker._pairs(tokenizer, 'q' * 200, ['x' * 600 + 'TAIL']))
        self.assertTrue(any('TAIL' in text for _, (_, text) in pairs))
        self.assertTrue(all(len(q) + len(t) + 3 <= Reranker.MAX_LENGTH for _, (q, t) in pairs))

    def test_bad_window_scores_rejected(self):
        for values in ([float('nan')], []):
            model = SimpleNamespace(tokenizer=WindowTokenizer(), predict=Mock(return_value=values))
            with patch.object(Reranker, '_load_model', return_value=model), self.assertRaises(ValueError):
                Reranker.LocalReranker().score('q', ['text'])


class RerankerIntegrationTests(unittest.TestCase):
    def setUp(self):
        for name in ('chunks', 'embed'):
            p = patch.object(LocalEmbeddings, name, getattr(FakeEmbeddings(), name))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(Reranker.LocalReranker, 'score', lambda self, q, texts: [10. if 'Rome' in t else -2. for t in texts])
        p.start(); self.addCleanup(p.stop)
        p = patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer())
        p.start(); self.addCleanup(p.stop)

    def test_benchmark_evidence_export_and_resume_compatibility(self):
        job = Benchmark.BenchmarkJob(fixture(), dict(module='vector_store_reranker', question_limit=1, candidate_k=20, retrieval_k=1))
        with patch.object(Benchmark, 'client', FakeOpenAIClient(['Rome', judgment(1)])):
            job.run()
        result = json.loads(json.dumps(job.snapshot()))
        self.assertEqual(result['status'], 'completed', result.get('error'))
        case = result['cases'][0]
        self.assertEqual(case['correct'], 1, case)
        self.assertEqual(case['evidence_recall'], 1.)
        self.assertEqual(case['evidence_recall_basis'], 'original_turn')
        self.assertEqual(case['diagnostics']['retrieved'][0]['metadata']['reranker_score'], 10.)
        self.assertEqual(result['memories'][0]['memory']['config']['candidate_k'], 20)
        self.assertEqual(result['memories'][0]['ingestion']['memory_llm_calls'], 0)
        self.assertEqual(Benchmark.BenchmarkJob.resume(fixture(), result).options, job.options)
        for key in ('model', 'revision', 'policy'):
            changed = deepcopy(result)
            changed['reranker'][key] = 'changed'
            with self.assertRaisesRegex(ValueError, 'reranker'):
                Benchmark.BenchmarkJob.resume(fixture(), changed)
        changed = deepcopy(result)
        changed['config']['candidate_k'] = 10
        with self.assertRaisesRegex(ValueError, 'config_hash'):
            Benchmark.BenchmarkJob.resume(fixture(), changed)

    def test_chat_settings_diagnostics_and_failure(self):
        client = app.app.test_client()
        self.addCleanup(app.chat_memory_modules.pop, 'reranker-test', None)
        payload = dict(chat_id='reranker-test', memory_module='vector_store_reranker', message='Rome',
                       memory_options=dict(candidate_k=12, max_stored_entries=2))
        with patch.object(ReAct, 'client', FakeOpenAIClient()):
            self.assertEqual(client.post('/get', json=payload).status_code, 200)
            self.assertEqual(client.post('/get', json=payload).status_code, 200)
        snapshot = client.get('/api/chats/reranker-test/export').get_json()
        self.assertEqual(snapshot['memory']['config']['candidate_k'], 12)
        self.assertEqual(snapshot['turns'][1]['retrieved'][0]['metadata']['reranker_score'], 10.)
        payload['memory_options']['candidate_k'] = 13
        self.assertEqual(client.post('/get', json=payload).status_code, 409)
        payload['memory_options']['candidate_k'] = 12
        with patch.object(Reranker.LocalReranker, 'score', side_effect=RuntimeError('reranker unavailable')), patch.object(ReAct, 'client') as llm:
            self.assertEqual(client.post('/get', json=payload).status_code, 503)
            llm.chat.completions.create.assert_not_called()
        self.assertEqual(len(app.chat_memory_modules['reranker-test'].module.inspect()['entries']), 2)
        for options in ({'candidate_k': True}, {'retrieval_k': 3}, {'hybrid_shares': {}}):
            payload.update(chat_id='invalid-reranker', memory_options=options)
            self.assertEqual(client.post('/get', json=payload).status_code, 400)
        self.assertNotIn('invalid-reranker', app.chat_memory_modules)

    def test_cli_pages_and_benchmark_validation(self):
        for page in ('/chat', '/benchmark'):
            html = app.app.test_client().get(page).get_data(as_text=True)
            self.assertIn('Vector Store + Reranker', html)
            self.assertIn('value="vector_store_reranker"', html)
        for options in (dict(module='vector_store', candidate_k=5), dict(module='vector_store_reranker', candidate_k=True)):
            with self.assertRaises(ValueError):
                Benchmark.options_for(fixture(), options)
        with tempfile.TemporaryDirectory() as directory:
            source, output = Path(directory)/'data.json', Path(directory)/'out.json'
            source.write_text(json.dumps(fixture()), encoding='utf-8')
            args = ['Benchmark.py', '--dataset', str(source), '--output', str(output), '--modules',
                    'vector_store_reranker', '--candidate-k', 'all', '--retrieval-k', '3']
            with patch.object(sys, 'argv', args), patch.object(Benchmark.BenchmarkJob, 'run'):
                Benchmark.main()
            saved = json.loads(output.read_text(encoding='utf-8'))
            self.assertIsNone(saved['config']['candidate_k'])
            self.assertEqual(saved['config']['retrieval_k'], 3)
            self.assertEqual(saved['reranker'], Reranker.reranker_identity())


if __name__ == '__main__':
    unittest.main()
