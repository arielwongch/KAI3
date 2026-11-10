"""Budget collisions must preserve useful summary and recalled context."""
from copy import deepcopy
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')

import Benchmark
from HybridMemory import HYBRID_PACKING_POLICY
from MemoryContext import build_memory_context, format_context, WINDOW_PACKING_POLICY
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from MemoryConfig import RERANKED_MODULES
from benchmark_helpers import FakeTokenizer
from test_hybrid_integration import dataset
from test_memory_integration import FakeOpenAIClient
from test_binary_benchmark import judgment
from test_semantic_memory import FakeEmbeddings, extraction
import Summarization


class ContextBudgetRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tokenizer = FakeTokenizer()
        self.reranker = Mock(identity={'model': 'injected'}, score=lambda q, texts: list(range(len(texts), 0, -1)))

    def make(self, mode, **options):
        if mode in RERANKED_MODULES:
            options['reranker'] = self.reranker
        return MemoryFactory.create_memory_module(mode, tokenizer=self.tokenizer,
            embedder=FakeEmbeddings(),
            extractor=lambda *a: extraction(), **options)

    def test_full_size_summaries_fit_with_recent_window_without_mutating_memory(self):
        for mode in ('alpha', 'windowed_summarization'):
            with self.subTest(mode=mode):
                module = self.make(mode, max_items=9, max_summary_tokens=2000)
                module.long_term.summary = 'Earlier important fact. ' * 86
                for i in range(9):
                    module.window.write(MemoryEntry(f'Recent {i}. ' + 'r' * 45))
                before = module.inspect()
                packed = build_memory_context(module, '?', 2000, self.tokenizer)
                self.assertEqual(packed['included_count'], 10)
                self.assertLessEqual(packed['memory_context_tokens'], 2000)
                self.assertIn('Earlier important fact.', packed['text'])
                self.assertIn('[Summary truncated]', packed['text'])
                self.assertTrue(packed['context_truncated'])
                self.assertFalse(packed['long_term_context_omitted'])
                self.assertEqual(packed['tiers']['long_term']['shortened_count'], 1)
                self.assertEqual(module.inspect(), before)

    def test_all_window_hybrids_reserve_recall_when_recent_turns_fill_budget(self):
        for mode in ('alpha', 'beta', 'gamma', 'windowed_summarization', 'windowed_fact_store'):
            with self.subTest(mode=mode):
                module = self.make(mode, max_items=9)
                for i in range(9):
                    module.window.write(MemoryEntry(f'Recent {i}. ' + 'r' * 100))
                summary = mode in ('alpha', 'windowed_summarization')
                record = MemoryEntry('Earlier answer.' * (100 if summary else 1),
                                     {'type': 'summary' if summary else 'fact', 'dialogue_id': 'D1'})
                original = deepcopy(record)
                with patch.object(module.long_term, 'iter_context_candidates', return_value=[record]) as recall:
                    packed = build_memory_context(module, '?', 1000, self.tokenizer, None)
                recall.assert_called_once_with('?', None)
                self.assertEqual(packed['tiers']['long_term']['included_count'], 1)
                self.assertGreater(packed['tiers']['recent']['included_count'], 0)
                self.assertGreater(packed['tiers']['recent']['omitted_count'], 0)
                self.assertLessEqual(packed['memory_context_tokens'], 1000)
                self.assertEqual(packed['packing_policy'], WINDOW_PACKING_POLICY)
                texts = [e.text for e in packed['entries'] if e.metadata['memory_tier'] == 'recent']
                self.assertEqual(texts, sorted(texts))
                self.assertIn('Recent 8.', texts[-1])
                self.assertEqual(record, original)
                if not summary:
                    self.assertEqual(packed['entries'][0].text, record.text)

    def test_empty_archive_releases_reservation_and_oversized_facts_are_reported(self):
        module = self.make('beta', max_items=2)
        for text in ('old', 'new'):
            module.window.write(MemoryEntry(text))
        with patch.object(module.long_term, 'iter_context_candidates', return_value=[]):
            packed = build_memory_context(module, '?', 1000, self.tokenizer)
        self.assertEqual([e.text for e in packed['entries']], ['old', 'new'])
        self.assertFalse(packed['long_term_context_omitted'])
        with patch.object(module.long_term, 'iter_context_candidates', return_value=[MemoryEntry('F' * 2000)]):
            packed = build_memory_context(module, '?', 1000, self.tokenizer)
        self.assertEqual(packed['tiers']['long_term']['oversized_count'], 1)
        self.assertTrue(packed['long_term_context_omitted'])
        self.assertEqual([e.text for e in packed['entries']], ['old', 'new'])

    def test_recent_spillover_restores_chronology_after_skipping_a_large_newer_turn(self):
        module = self.make('beta', max_items=2)
        module.window.write(MemoryEntry('old'))
        module.window.write(MemoryEntry('new' * 150))
        # An oversized recalled record reserves space but cannot be supplied.
        # The large newest turn then borrows that space after the small older one.
        with patch.object(module.long_term, 'iter_context_candidates', return_value=[MemoryEntry('F' * 2000)]):
            packed = build_memory_context(module, '?', 1000, self.tokenizer)
        self.assertEqual([e.text for e in packed['entries']], ['old', 'new' * 150])
        self.assertLessEqual(packed['memory_context_tokens'], 1000)

    def test_independent_summary_borrows_spare_space_even_when_its_share_cannot_fit_a_label(self):
        for mode, component in (('delta', 'vector_store'), ('epsilon', 'fact_store')):
            with self.subTest(mode=mode):
                module = self.make(mode, hybrid_shares={'summarization': .05, component: .95})
                module.components['summarization'].summary = 'S' * 1000
                module.components['summarization'].truncated = True
                record = MemoryEntry('F' * 165, {'dialogue_id': 'D1'})
                with patch.object(module.components[component], 'iter_context_candidates', return_value=[record]):
                    packed = build_memory_context(module, '?', 300, self.tokenizer)
                # The 15-token summary share cannot fit its label. Spare record
                # capacity must still admit a shortened summary, not discard it.
                self.assertEqual(packed['included_count'], 2)
                self.assertIn('F' * 165, packed['text'])
                self.assertTrue(packed['context_truncated'])
                self.assertLessEqual(packed['memory_context_tokens'], 300)
                self.assertEqual(module.components['summarization'].summary, 'S' * 1000)
                self.assertEqual(packed['packing_policy'], HYBRID_PACKING_POLICY)
                module.components['summarization'].summary = 'short'
                with patch.object(module.components[component], 'iter_context_candidates', return_value=[]):
                    packed = build_memory_context(module, '?', 300, self.tokenizer)
                self.assertTrue(packed['context_truncated'])

    def test_record_memories_keep_whole_records_and_do_not_fetch_beyond_k(self):
        for mode in ('sliding_window', 'vector_store', 'vector_store_reranker', 'fact_store'):
            histories = ('current', 'versioned') if mode == 'fact_store' else (None,)
            for history in histories:
                with self.subTest(mode=mode, history=history):
                    options = {'fact_history_mode': history} if history else {}
                    module = self.make(mode, **options)
                    entries = [MemoryEntry('too large' * 100), MemoryEntry('fits')]
                    with patch.object(module, 'iter_context_candidates', return_value=entries[:1]) as recall:
                        packed = build_memory_context(module, '?', 100, self.tokenizer, 1)
                    recall.assert_called_once_with('?', 1)
                    self.assertEqual(packed['entries'], [])
                    self.assertTrue(packed['all_candidates_over_budget'])
                    with patch.object(module, 'iter_context_candidates', return_value=entries):
                        packed = build_memory_context(module, '?', 100, self.tokenizer)
                    self.assertEqual([e.text for e in packed['entries']], ['fits'])

    def test_standalone_summary_and_no_memory_do_not_need_tier_reservations(self):
        module = self.make('summarization', max_summary_tokens=2000)
        module.summary = 'S' * 2000
        packed = build_memory_context(module, '?', 2000, self.tokenizer)
        self.assertEqual(packed['text'], module.summary)
        self.assertFalse(packed['context_truncated'])
        empty = build_memory_context(self.make('no_memory'), '?', 2000, self.tokenizer)
        self.assertEqual(empty['text'], '')
        self.assertEqual(empty['candidate_count'], 0)
        self.assertFalse(empty['all_candidates_over_budget'])

    def test_default_benchmark_passes_summary_to_answer_and_judge(self):
        for mode in ('alpha', 'windowed_summarization'):
            with self.subTest(mode=mode):
                job = Benchmark.BenchmarkJob(dataset(), dict(module=mode, window_size=2))
                client = FakeOpenAIClient(['cat', judgment(1)])
                with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=self.tokenizer), \
                     patch.object(Summarization, 'call_api', return_value=('S' * 8000, 0, 3)), \
                     patch.object(Benchmark, 'client', client):
                    job.run()
                report = job.snapshot()
                diagnostics = report['cases'][0]['diagnostics']
                self.assertEqual(report['status'], 'completed')
                self.assertEqual(diagnostics['tiers']['long_term']['included_count'], 1)
                self.assertIn('Earlier conversation summary', diagnostics['supplied_context'])
                self.assertLessEqual(diagnostics['memory_context_tokens'], 8000)
                self.assertIn('[Summary truncated]', client.calls[0]['messages'][1]['content'])
                self.assertIn('[Summary truncated]', client.calls[1]['messages'][1]['content'])

    def test_resume_rejects_old_window_and_independent_hybrid_packing(self):
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=self.tokenizer):
            for mode in ('alpha', 'beta', 'gamma', 'windowed_summarization', 'windowed_fact_store', 'delta', 'epsilon', 'zeta'):
                with self.subTest(mode=mode):
                    previous = Benchmark.BenchmarkJob(dataset(), dict(module=mode)).snapshot()
                    previous['packing_policy'] = 'recent-newest-first-whole-record-v2' if mode not in ('delta', 'epsilon', 'zeta') else 'whole-record-first-k-greedy-v1'
                    with self.assertRaisesRegex(ValueError, 'packing_policy'):
                        Benchmark.BenchmarkJob.resume(dataset(), previous)
