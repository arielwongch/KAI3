"""Hybrid partitioning, fact freshness, atomic writes, and prompt contracts."""
import json
import os
import sys
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')

from Diagnostics import collector
from HybridMemory import Alpha, Beta, Gamma
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
import ReAct
import Summarization
from test_memory_integration import FakeOpenAIClient
from test_semantic_memory import FakeEmbeddings, extraction


def entry(text, **metadata):
    return MemoryEntry(text, metadata)



def setUpModule():
    from benchmark_helpers import offline_reranking
    offline_reranking()


class HybridMemoryTests(unittest.TestCase):
    def test_budget_counts_section_labels_and_limits_only_long_term_candidates(self):
        from benchmark_helpers import FakeTokenizer
        from MemoryContext import build_memory_context, format_context
        module = Beta(max_items=2, embedder=FakeEmbeddings())
        for text in ('cat first', 'cat second', 'cat third', 'cat fourth'):
            module.write(entry(text))
        before = module.inspect()
        packed = build_memory_context(module, 'cat', 1000, FakeTokenizer(), 1)
        self.assertEqual(packed['candidate_count'], 3)
        self.assertEqual([e.text for e in packed['entries'][-2:]], ['cat third', 'cat fourth'])
        self.assertEqual(packed['text'], format_context(packed['entries']))
        self.assertEqual(packed['memory_context_tokens'], len(packed['text']))
        for budget in (1, 100, 190, 220):
            small = build_memory_context(module, 'cat', budget, FakeTokenizer(), None)
            self.assertLessEqual(len(small['text']), budget)
            self.assertEqual(small['omitted_count'], small['candidate_count'] - len(small['entries']))
        self.assertEqual(module.inspect(), before)

    def test_alpha_fill_evict_and_repeat(self):
        module = Alpha(max_items=2)
        with patch.object(Summarization, 'call_api', return_value=('summary', 0, 3)) as call:
            module.write(entry('first'))
            module.write(entry('second'))
            call.assert_not_called()
            self.assertEqual([e.text for e in module.retrieve('', 1)], ['first', 'second'])
            module.write(entry('third'))
            self.assertEqual(call.call_args.args[1].split('New interaction:\n')[1], 'first')
            module.write(entry('fourth'))
            self.assertIn('Previous summary:\nsummary', call.call_args.args[1])
            self.assertEqual(call.call_args.args[1].split('New interaction:\n')[1], 'second')
            self.assertEqual(call.call_count, 2)
        self.assertEqual([e.text for e in module.retrieve('', 1)], ['summary', 'third', 'fourth'])

    def test_alpha_batches_preserve_individual_tail_and_only_summarize_evictions(self):
        module = Alpha(max_items=2, summary_limit=7)
        with patch.object(Summarization, 'call_api', return_value=('summary too long', 0, 3)) as call:
            module.write_batch([entry('one'), entry('two')])
            call.assert_not_called()
            module.write_batch([entry('three'), entry('four'), entry('five')])
            self.assertEqual(call.call_count, 1)
            self.assertEqual(call.call_args.args[1].split('New interaction:\n')[1], 'one\n\ntwo\n\nthree')
        self.assertEqual([e.text for e in module.retrieve('', 3)], ['summary', 'four', 'five'])

    def test_alpha_batch_failure_preserves_both_tiers(self):
        module = Alpha(max_items=1)
        with patch.object(Summarization, 'call_api', return_value=('old summary', 0, 3)):
            module.write_batch([entry('one'), entry('two')])
        before = module.inspect()
        for result in (RuntimeError('offline'), (None, 0, 3)):
            kwargs = {'side_effect': result} if isinstance(result, Exception) else {'return_value': result}
            with patch.object(Summarization, 'call_api', **kwargs):
                with self.assertRaises((RuntimeError, TypeError)):
                    module.write_batch([entry('three'), entry('four')])
            self.assertEqual(module.inspect(), before)

    def test_beta_partition_ranking_and_provenance(self):
        module = Beta(max_items=2, embedder=FakeEmbeddings())
        for text in ['cat one', 'dog two', 'dog three', 'dog four']:
            module.write(entry(text, dialogue_id=text, nested={'value': 1}))
        snapshot = module.inspect()
        self.assertEqual([e['text'] for e in snapshot['entries']], ['cat one', 'dog two', 'dog three', 'dog four'])
        self.assertEqual([e['metadata']['memory_tier'] for e in snapshot['entries']], ['long_term'] * 2 + ['recent'] * 2)
        result = module.retrieve('feline', 1)
        self.assertEqual([e.text for e in result], ['cat one', 'dog three', 'dog four'])
        self.assertEqual(result[0].metadata['dialogue_id'], 'cat one')
        self.assertEqual(result[0].metadata['retrieval_score_type'], 'cross_encoder_logit')
        self.assertEqual(snapshot['entries'][0]['chunk_count'], 1)
        self.assertEqual([e.text for e in module.retrieve(' ', 1)], ['dog three', 'dog four'])

    def test_beta_embeds_only_evicted_turns_and_failure_is_atomic(self):
        embedder = FakeEmbeddings()
        module = Beta(max_items=1, embedder=embedder)
        with patch.object(embedder, 'embed', side_effect=RuntimeError('offline')) as embed:
            module.write(entry('cat'))
            embed.assert_not_called()
            before = module.inspect()
            with self.assertRaises(RuntimeError):
                module.write(entry('dog'))
            self.assertEqual(module.inspect(), before)
        module.write(entry('dog'))
        self.assertEqual(len(module.inspect()['entries']), 2)

    def test_gamma_immediate_correction_retraction_and_user_evidence(self):
        extractor = Mock(side_effect=[extraction({'op': 'add', 'text': 'Likes cats'}),
                                     extraction({'op': 'replace', 'id': 'fact-1', 'text': 'Likes dogs'}),
                                     extraction({'op': 'remove', 'id': 'fact-1'})])
        module = Gamma(max_items=5, embedder=FakeEmbeddings(), extractor=extractor)
        module.write(entry('User likes cats; assistant guesses Rome', user_text='I like cats', assistant_text='You live in Rome'))
        payload = json.loads(extractor.call_args.args[1])
        self.assertEqual(payload['user_text'], 'I like cats')
        self.assertEqual(payload['assistant_context'], 'You live in Rome')
        self.assertIn('Assistant text is context only', extractor.call_args.args[0])
        module.write(entry('Actually dogs', user_text='Actually dogs'))
        facts = module.retrieve('pets', 1)
        self.assertEqual(facts[0].text, 'Likes dogs')
        self.assertEqual(facts[0].metadata['fact_id'], 'fact-1')
        self.assertEqual(facts[0].metadata['source_text'], 'Actually dogs')
        module.write(entry('Forget that', user_text='Forget that'))
        self.assertEqual(len(module.retrieve('pets', 1)), 3)
        module.write(entry('incomplete', completed=False))
        self.assertEqual(extractor.call_count, 3)

    def test_gamma_extraction_and_embedding_failures_preserve_both_tiers(self):
        extractor = Mock(return_value=extraction({'op': 'add', 'text': 'cat'}))
        embedder = FakeEmbeddings()
        module = Gamma(max_items=1, embedder=embedder, extractor=extractor)
        module.write(entry('cat'))
        before = module.inspect()
        extractor.return_value = ('invalid JSON', 0, 1)
        with self.assertRaises(ValueError):
            module.write(entry('dog'))
        self.assertEqual(module.inspect(), before)
        extractor.return_value = extraction({'op': 'replace', 'id': 'fact-1', 'text': 'dog'})
        with patch.object(embedder, 'embed', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                module.write(entry('dog'))
        self.assertEqual(module.inspect(), before)
        extractor.side_effect = RuntimeError('extractor offline')
        with self.assertRaises(RuntimeError):
            module.write(entry('dog'))
        self.assertEqual(module.inspect(), before)

    def test_factory_validation_copies_isolation_and_side_effect_free_inspection(self):
        for mode in ('alpha', 'beta', 'gamma'):
            with self.subTest(mode=mode):
                for value in (0, -1, True, 1.5, '2'):
                    with self.assertRaises(ValueError):
                        MemoryFactory.create_memory_module(mode, max_items=value)
                module = MemoryFactory.create_memory_module(mode, max_items=1, embedder=FakeEmbeddings(), extractor=lambda *a: extraction())
                with patch.object(module.long_term, 'write', side_effect=AssertionError('Blank write reached long-term memory')):
                    module.write(entry('  '))
                self.assertEqual(module.inspect()['entries'], [])
                original = entry('cat', nested={'value': 1})
                module.write(original)
                original.text = 'changed'
                original.metadata['nested']['value'] = 2
                for k in (0, -1, True, 1.5):
                    with self.assertRaises(ValueError):
                        module.retrieve('cat', k)
                retrieved = module.retrieve('', 1)
                retrieved[0].metadata['nested']['value'] = 3
                with patch.object(module.long_term, 'retrieve', side_effect=AssertionError('retrieved')), patch.object(Summarization, 'call_api', side_effect=AssertionError('API called')):
                    snapshot = module.inspect()
                    json.dumps(snapshot)
                    self.assertEqual(snapshot['entries'][0]['text'], 'cat')
                    self.assertEqual(snapshot['entries'][0]['metadata']['nested']['value'], 1)
                    snapshot['entries'][0]['text'] = 'changed'
                    snapshot['config']['max_items'] = 999
                    self.assertEqual(module.inspect()['config']['max_items'], 1)
                    self.assertEqual(module.inspect()['entries'][0]['text'], 'cat')
                other = MemoryFactory.create_memory_module(mode)
                self.assertEqual(other.inspect()['entries'], [])

    def test_prompt_order_original_diagnostics_and_accounting(self):
        for module in (Alpha(1), Gamma(1, FakeEmbeddings(), lambda *a: extraction())):
            with patch.object(Summarization, 'call_api', return_value=('earlier summary', 0, 3)):
                module.write(entry('old'))
                module.write(entry('recent'))
                fake, diagnostics = FakeOpenAIClient(), {}
                with patch.object(ReAct, 'client', fake):
                    ReAct.run_ReAct('question', memory_module=module, diagnostics=diagnostics)
            prompt = fake.calls[0]['messages'][0]['content']
            self.assertIn('Explicit recent corrections supersede older statements', prompt)
            self.assertIn('Recent conversation (oldest to newest):\nrecent', prompt)
            self.assertEqual(diagnostics['retrieved'][-1]['text'], 'recent')
            self.assertEqual(diagnostics['memory_llm_calls'], 1)
            self.assertIsNotNone(diagnostics['memory_tokens'])

    def test_inspection_waits_for_write_and_failed_calls_are_accounted(self):
        module = Alpha(1)
        module.write(entry('old'))
        entered, release, inspected = threading.Event(), threading.Event(), threading.Event()
        def summarize(*args):
            entered.set()
            self.assertTrue(release.wait(2))
            return ('summary', 0, 3)
        with patch.object(Summarization, 'call_api', side_effect=summarize):
            writer = threading.Thread(target=module.write, args=(entry('new'),))
            reader = threading.Thread(target=lambda: (module.inspect(), inspected.set()))
            writer.start()
            self.assertTrue(entered.wait(1))
            reader.start()
            try:
                self.assertFalse(inspected.wait(.02))
            finally:
                release.set()
                writer.join(2)
                reader.join(2)
        self.assertTrue(inspected.is_set())
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            with patch.object(Summarization, 'call_api', side_effect=RuntimeError('offline')):
                with self.assertRaises(RuntimeError):
                    module.write(entry('next'))
        finally:
            collector.reset(token)
        self.assertEqual(metrics, dict(memory_llm_calls=1, memory_tokens=None, memory_prompt_tokens=None, memory_completion_tokens=None))


if __name__ == '__main__':
    unittest.main()
