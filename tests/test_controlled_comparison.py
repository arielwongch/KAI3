import json
import os
import sys
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import Benchmark
from MemoryContext import build_memory_context, truncate_summary
from MemoryFactory import MemoryFactory
from MemoryEntry import MemoryEntry
from SlidingWindow import SlidingWindow
from VectorStore import VectorStore
from TemporalFactStore import TemporalFactStore
from benchmark_helpers import FakeTokenizer
from test_semantic_memory import FakeEmbeddings, extraction
from test_memory_integration import FakeOpenAIClient
from test_binary_benchmark import judgment
from test_benchmark_recovery import ProviderError


def dataset(n=2):
    return [dict(sample_id='one', conversation={'session_1': [dict(
        speaker='Bob', text='Bob works at Google.', dia_id='D1:1')]},
        qa=[dict(question=f'Where {i}?', answer='Google', category=4, evidence=['D1:1']) for i in range(n)])]


def turn(text, dia, speaker='Bob', session='session_1'):
    return MemoryEntry(text, dict(speaker=speaker, dialogue_id=dia, session=session, timestamp='1 May 2023'))


def add(text, source, **extra):
    return dict(op='add', text=text, source_ids=[source], supporting_version_ids=[], **extra)


class ContextTests(unittest.TestCase):
    def test_window_all_k_and_capacity_are_independent(self):
        store = SlidingWindow(10)
        for i in range(12):
            store.write(MemoryEntry(str(i)))
        packed = build_memory_context(store, 'ignored', 100, FakeTokenizer())
        self.assertEqual([e.text for e in packed['entries']], list(map(str, range(2,12))))
        self.assertEqual(store.inspect()['config']['evicted_count'], 2)
        packed = build_memory_context(store, 'ignored', 100, FakeTokenizer(), 5)
        self.assertEqual([e.text for e in packed['entries']], list(map(str, range(7,12))))
        self.assertEqual(packed['memory_context_tokens'], len(packed['text']))

    def test_first_k_candidates_and_separator_budget(self):
        store = VectorStore(FakeEmbeddings())
        for text in ('cat short', 'cat also', 'cat ' + 'x'*100):
            store.write(MemoryEntry(text))
        packed = build_memory_context(store, 'cat', 20, FakeTokenizer(), 1)
        self.assertEqual(packed['entries'], [])
        self.assertTrue(packed['all_candidates_over_budget'])
        packed = build_memory_context(store, 'cat', 20, FakeTokenizer(), 2)
        self.assertEqual([e.text for e in packed['entries']], ['cat also'])
        self.assertEqual(packed['candidate_count'], 2)
        packed = build_memory_context(store, 'cat', 19, FakeTokenizer())
        self.assertEqual(packed['memory_context_tokens'], 19)
        self.assertEqual(packed['included_count'], 2)

    def test_vector_capacity_and_more_than_five(self):
        store = VectorStore(FakeEmbeddings(), max_stored_entries=7)
        for i in range(10):
            store.write(MemoryEntry(f'cat {i}'))
        packed = build_memory_context(store, 'cat', 1000, FakeTokenizer())
        self.assertEqual(packed['included_count'], 7)
        self.assertEqual(store.inspect()['config']['evicted_count'], 3)
        with patch.object(store.embedder, 'embed', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                store.write(MemoryEntry('new'))
        self.assertEqual(store.inspect()['config']['evicted_count'], 3)

    def test_summary_size_only_preserves_original_case(self):
        text, cut = truncate_summary('Bob Works At Google. ' * 10, 60, FakeTokenizer())
        self.assertTrue(cut)
        self.assertIn('Bob Works', text)
        self.assertLessEqual(len(text), 60)
        module = MemoryFactory.create_memory_module('summarization', max_summary_tokens=60, tokenizer=FakeTokenizer())
        with patch('Summarization.call_api', return_value=('Bob Works At Google. '*10, 0, 7)):
            module.write(MemoryEntry('new'))
        self.assertLessEqual(len(module.summary), 60)
        packed = build_memory_context(module, 'where', 60, FakeTokenizer())
        self.assertTrue(packed['context_truncated'])
        with self.assertRaises(ValueError):
            list(module.iter_context_candidates('q', 1))


class TemporalFactTests(unittest.TestCase):
    def test_history_provenance_and_correction(self):
        extractor = Mock(side_effect=[extraction(add('Bob works at Google', 'D1')),
            extraction(dict(op='supersede', id='version-1', text='Bob works at Microsoft',
                            source_ids=['D2'], supporting_version_ids=[])),
            extraction(dict(op='correct', id='version-2', text='Bob works at Apple',
                            source_ids=['D3'], supporting_version_ids=[]))])
        store = TemporalFactStore(FakeEmbeddings(), extractor)
        store.write(turn('Google', 'D1'))
        store.write(turn('Microsoft', 'D2', session='session_2'))
        store.write(turn('Actually Apple', 'D3', session='session_3'))
        records = store.inspect()['entries']
        self.assertEqual([r['metadata']['status'] for r in records], ['superseded', 'corrected', 'current'])
        self.assertEqual([r['metadata']['source_ids'] for r in records], [['D1'], ['D2'], ['D3']])
        self.assertTrue(all(r['metadata']['valid_from'] is None for r in records))
        retrieved = store.retrieve('before Microsoft', 10)
        self.assertTrue(any('superseded' in r.text and 'Google' in r.text for r in retrieved))
        self.assertTrue(any('corrected' in r.text and 'Microsoft' in r.text for r in retrieved))

    def test_confirm_support_and_retraction(self):
        extractor = Mock(side_effect=[extraction(add('Bob likes cats', 'D1')),
            extraction(dict(op='confirm', id='version-1', source_ids=['D2'])),
            extraction(dict(op='add', text='Bob owns a cat', source_ids=['D3'], supporting_version_ids=['version-1'])),
            extraction(dict(op='retract', id='version-1', source_ids=['D4']))])
        store = TemporalFactStore(FakeEmbeddings(), extractor)
        for i in range(1,5):
            store.write(turn('assertion', f'D{i}'))
        records = store.inspect()['entries']
        self.assertEqual(records[0]['metadata']['source_ids'], ['D1','D2'])
        self.assertEqual(records[0]['metadata']['transition_source_ids'], ['D4'])
        self.assertEqual(records[1]['metadata']['source_ids'], ['D1','D2','D3'])
        self.assertEqual(records[0]['metadata']['status'], 'retracted')

    def test_invalid_operations_and_embeddings_are_atomic(self):
        extractor = Mock(return_value=extraction(add('Bob likes cats', 'D1')))
        embedder = FakeEmbeddings()
        store = TemporalFactStore(embedder, extractor)
        store.write(turn('cat', 'D1'))
        before = deepcopy(store.inspect())
        for operation in (dict(op='confirm', id='version-1', source_ids=['forged']),
                          dict(op='confirm', id='missing', source_ids=['D2'])):
            extractor.return_value = extraction(operation)
            with self.assertRaises(ValueError):
                store.write(turn('cat', 'D2'))
            self.assertEqual(store.inspect(), before)
        extractor.return_value = extraction(dict(op='confirm', id='version-1', source_ids=['D2']))
        with self.assertRaises(ValueError):
            store.write(turn('cat', 'D2', speaker='Alice'))
        extractor.return_value = extraction(add('new', 'D2'))
        with patch.object(embedder, 'embed', side_effect=RuntimeError('offline')):
            with self.assertRaises(RuntimeError):
                store.write(turn('new', 'D2'))
        self.assertEqual(store.inspect(), before)

    def test_finite_capacity_and_version_links(self):
        extractor = Mock(side_effect=[extraction(add('Google', 'D1')),
            extraction(dict(op='supersede', id='version-1', text='Microsoft', source_ids=['D2'], supporting_version_ids=[]))])
        store = TemporalFactStore(FakeEmbeddings(), extractor, max_stored_entries=1)
        store.write(turn('Google', 'D1')); store.write(turn('Microsoft', 'D2'))
        snapshot = store.inspect()
        self.assertEqual(snapshot['config']['evicted_count'], 1)
        self.assertFalse(snapshot['entries'][0]['metadata']['prior_version_id_available'])


class ControlledBenchmarkTests(unittest.TestCase):
    def setUp(self):
        patched = patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer())
        patched.start(); self.addCleanup(patched.stop)

    def test_module_capabilities_and_validation(self):
        for mode in Benchmark.BENCHMARK_MODULES:
            options = Benchmark.options_for(dataset(), dict(module=mode))
            self.assertEqual('retrieval_k' in options, mode in ('sliding_window','vector_store','fact_store'))
            self.assertEqual('max_summary_tokens' in options, mode == 'summarization')
        for options in (dict(module='summarization', retrieval_k=None),
                        dict(module='summarization', max_stored_entries=1),
                        dict(module='full_context', memory_context_tokens=2000),
                        dict(module='sliding_window', retrieval_k=True),
                        dict(module='sliding_window', max_stored_entries=None),
                        dict(module='vector_store', retrieval_k=0),
                        dict(module='fact_store', max_stored_entries=1.5),
                        dict(module='summarization', max_summary_tokens=3000)):
            with self.subTest(options=options), self.assertRaises(ValueError):
                Benchmark.options_for(dataset(), options)
        options = Benchmark.options_for(dataset(), dict(module='no_memory', no_memory_context='question_only'))
        self.assertEqual(options['modules'], ['question_only'])
        for mode, settings in (('summarization', dict(max_stored_entries=1)),
                               ('vector_store', dict(max_summary_tokens=100)),
                               ('sliding_window', dict(max_items=10, max_stored_entries=20))):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                MemoryFactory.create_memory_module(mode, **settings)

    def test_cli_suppresses_inapplicable_defaults(self):
        import tempfile
        from pathlib import Path
        for mode, arguments in (('question_only', []),
                                ('sliding_window', ['--retrieval-k', '1', '--max-stored-entries', '3']),
                                ('summarization', ['--max-summary-tokens', '100'])):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                data_path, out_path = Path(directory)/'data.json', Path(directory)/'out.json'
                data_path.write_text(json.dumps(dataset(1)), encoding='utf-8')
                args = ['benchmark', '--dataset', str(data_path), '--output', str(out_path), '--modules', mode] + arguments
                with patch.object(sys,'argv',args), patch.object(Benchmark,'client',FakeOpenAIClient(['Google',judgment(1)])), patch('Summarization.call_api',return_value=('Bob works at Google',0,7)):
                    Benchmark.main()
                result = json.loads(out_path.read_text(encoding='utf-8'))
                self.assertEqual(result['status'], 'completed')
                self.assertEqual('retrieval_k' in result['config'], mode == 'sliding_window')
                self.assertEqual(result['config']['modules'], [mode])

    def test_cancellation_and_answer_failure_keep_manifest_denominator(self):
        for failure in ('cancel', 'answer'):
            job = Benchmark.BenchmarkJob(dataset(), dict(module='question_only',question_limit=0))
            if failure == 'cancel':
                job.cancel.set()
                job.run()
            else:
                with patch.object(Benchmark,'direct_answer',side_effect=ProviderError(402)):
                    job.run()
            row = next(r for r in job.result['scores'] if r['category']=='overall')
            self.assertEqual(row['selected_count'], 2)
            self.assertEqual(row['end_to_end_success_rate'], 0)
            self.assertEqual(row['failure_counts']['not_attempted'], 2 if failure=='cancel' else 1)
            self.assertEqual(row['failure_counts']['answer_failed'], 0 if failure=='cancel' else 1)

    def test_judge_failure_does_not_inflate_end_to_end(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='full_context', question_limit=0))
        with patch.object(Benchmark, 'client', FakeOpenAIClient(['Google', judgment(1), 'Google', '{}'])):
            job.run()
        row = next(r for r in job.result['scores'] if r['category']=='overall')
        self.assertEqual(row['judged_accuracy'], 1)
        self.assertEqual(row['end_to_end_success_rate'], .5)
        self.assertEqual(row['completion_rate'], .5)
        self.assertEqual(row['failure_counts']['judge_failed'], 1)
        self.assertEqual(sum(row['failure_counts'].values()), 2)

    def test_ingestion_failure_blocks_all_selected_questions(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='summarization', question_limit=0))
        fake = FakeOpenAIClient()
        with patch('Summarization.call_api', side_effect=ProviderError(402)), patch.object(Benchmark,'client',fake):
            job.run()
        row = next(r for r in job.result['scores'] if r['category']=='overall')
        self.assertEqual(job.result['status'], 'failed')
        self.assertEqual(row['failure_counts']['ingestion_blocked'], 2)
        self.assertEqual(row['end_to_end_success_rate'], 0)
        self.assertEqual(fake.calls, [])

    def test_tokenizer_failure_prevents_ingestion_calls(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='summarization'))
        with patch.object(Benchmark,'get_benchmark_tokenizer',side_effect=RuntimeError('no tokenizer')), patch('Summarization.call_api') as api:
            job.run()
        api.assert_not_called()
        self.assertEqual(job.result['status'], 'failed')
        self.assertEqual(job.result['scores'][0]['failure_counts']['not_attempted'], 2)

    def test_resume_rejects_changed_controls_and_legacy(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='vector_store'))
        previous = job.snapshot()
        previous['config']['retrieval_k'] = 1
        with self.assertRaises(ValueError):
            Benchmark.BenchmarkJob.resume(dataset(), previous)
        previous = job.snapshot(); previous.pop('protocol_version')
        with self.assertRaises(ValueError):
            Benchmark.BenchmarkJob.resume(dataset(), previous)

    def test_fact_qa_provenance_and_no_writeback(self):
        extractor = Mock(return_value=extraction(add('Bob works at Google', 'D1:1')))
        store = TemporalFactStore(FakeEmbeddings(), extractor)
        job = Benchmark.BenchmarkJob(dataset(1), dict(module='fact_store'))
        fake = FakeOpenAIClient(['Google',judgment(1)])
        with patch.object(Benchmark.MemoryFactory, 'create_memory_module', return_value=store), patch.object(Benchmark,'client',fake):
            job.run()
        case = job.result['cases'][0]
        self.assertEqual(case['evidence_recall'], 1)
        self.assertEqual(case['evidence_recall_basis'], 'fact_source_provenance')
        self.assertTrue(case['evidence_complete'])
        self.assertEqual(case['diagnostics']['stored_before'], case['diagnostics']['stored_after'])
        self.assertEqual(extractor.call_count, 1)
        self.assertEqual(job.result['efficiency'][0]['evidence_complete']['accuracy'], 1)


if __name__ == '__main__':
    unittest.main()
