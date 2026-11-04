"""Offline regressions for stable batch references and transactional recovery."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path[:0] = ['src', 'tests']
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')

import API
import TemporalFactStore as temporal
from Diagnostics import collector, memory_request_options, memory_response
from MemoryEntry import MemoryEntry
from test_memory_integration import FakeOpenAIClient
from test_semantic_memory import FakeEmbeddings
from WindowHybridMemory import WindowedFactStore


def turn(source, speaker='Bob'):
    return MemoryEntry('A source assertion.', dict(speaker=speaker, dialogue_id=source,
        session='session_1', timestamp='2026-01-01'))


def add(source, handle, text='Bob owns a cat.', supports=None):
    return dict(op='add', text=text, result_ref=handle, source_ids=[source],
                supporting_version_ids=supports or [])


def response(*turns):
    return json.dumps(dict(turns=[dict(dialogue_id=source, operations=ops)
                                  for source, ops in turns])), 0, 7


class BatchRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        patcher = patch.object(temporal, 'BATCH_FAILURE_DIR', Path(self.folder.name))
        patcher.start()
        self.addCleanup(patcher.stop)

    def store(self, extractor, **kwargs):
        return temporal.TemporalFactStore(embedder=FakeEmbeddings(), extractor=extractor, **kwargs)

    def test_duplicate_handles_resolve_to_survivor_and_supports_preserve_provenance(self):
        extract = Mock(return_value=response(
            ('D1', [add('D1', 'new:first')]),
            ('D2', [add('D2', 'new:duplicate', '  BOB owns a cat.  ')]),
            ('D3', [dict(op='confirm', id='new:duplicate', source_ids=['D3']),
                    add('D3', 'new:second', 'Bob owns an animal.', ['new:first'])])))
        store = self.store(extract)
        store.write_batch([turn('D1'), turn('D2'), turn('D3')])
        entries = store.inspect()['entries']
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['metadata']['source_ids'], ['D1', 'D2', 'D3'])
        self.assertEqual(entries[1]['metadata']['source_ids'], ['D1', 'D2', 'D3'])
        self.assertEqual(store._next_id, 3)
        self.assertEqual(extract.call_count, 1)

    def test_repair_uses_original_snapshot_and_accounts_for_both_calls(self):
        extract = Mock(side_effect=[response(('D1', [add('D1', 'new:a')]),
            ('D2', [dict(op='confirm', id='new:missing', source_ids=['D2'])])),
            response(('D1', [add('D1', 'new:a')]), ('D2', []))])
        store = self.store(extract)
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            store.write_batch([turn('D1'), turn('D2')])
        finally:
            collector.reset(token)
        self.assertEqual(len(store._records), 1)
        self.assertEqual(store._next_id, 2)
        repaired = json.loads(extract.call_args.args[1])
        self.assertEqual(repaired['versions'], [])
        self.assertEqual(repaired['validation_error']['operation_index'], 0)
        self.assertEqual(repaired['validation_error']['dialogue_id'], 'D2')
        self.assertEqual(metrics['memory_validation_repairs'], 1)
        self.assertEqual(metrics['memory_llm_calls'], 2)
        self.assertEqual(metrics['memory_tokens'], 14)
        artifact = json.loads(next(Path(self.folder.name).glob('*.json')).read_text())
        self.assertIn('new:missing', artifact['raw_response'])
        self.assertEqual(artifact['input']['versions'], [])

    def test_batches_share_vectors_but_isolate_metadata_on_success_and_failure(self):
        class ReadOnlyVector(list):
            def __deepcopy__(self, memo):
                raise AssertionError('Stored vectors must not be copied')

        extract = Mock(return_value=response(('D1', [add('D1', 'new:a')])))
        store = self.store(extract)
        store.write_batch([turn('D1')])
        original, vector = store._records['version-1']
        vector = ReadOnlyVector(vector)
        store._records['version-1'] = (original, vector)
        before = store.inspect()
        confirm = dict(op='confirm', id='version-1', source_ids=['D2'])
        extract.return_value = response(('D2', [confirm]),
            ('D3', [dict(op='confirm', id='new:missing', source_ids=['D3'])]))
        with self.assertRaises(temporal.BatchValidationError):
            store.write_batch([turn('D2'), turn('D3')])
        self.assertEqual(store.inspect(), before)
        self.assertIs(store._records['version-1'][1], vector)

        extract.return_value = response(('D2', [confirm]))
        store.write_batch([turn('D2')])
        updated, retained_vector = store._records['version-1']
        self.assertIs(retained_vector, vector)
        self.assertEqual(original.metadata['source_ids'], ['D1'])
        self.assertEqual(updated.metadata['source_ids'], ['D1', 'D2'])
        self.assertEqual(len(original.metadata['source_observations']), 1)
        self.assertEqual(len(updated.metadata['source_observations']), 2)

    def test_invalid_references_exhaust_repair_without_committing(self):
        for target, speaker in [('new:future', 'Bob'), ('version-1', 'Bob'),
                                ('new:first', 'Alice')]:
            with self.subTest(target=target, speaker=speaker):
                extract = Mock(return_value=response(('D1', [add('D1', 'new:first')]),
                    ('D2', [dict(op='retract', id=target, source_ids=['D2'])])))
                store = self.store(extract)
                before = store.inspect()
                with self.assertRaises(temporal.BatchValidationError):
                    store.write_batch([turn('D1'), turn('D2', speaker)])
                self.assertEqual(store.inspect(), before)
                self.assertEqual((store._next_id, store._revision), (1, 0))
                self.assertEqual(extract.call_count, 2)

    def test_evicted_or_retracted_handles_cannot_be_targeted(self):
        for capacity, middle in [(1, [add('D2', 'new:other', 'Bob owns a dog.')]),
                                 (None, [dict(op='retract', id='new:first', source_ids=['D2'])])]:
            extract = Mock(return_value=response(('D1', [add('D1', 'new:first')]),
                ('D2', middle), ('D3', [dict(op='confirm', id='new:first', source_ids=['D3'])])))
            store = self.store(extract, max_stored_entries=capacity)
            with self.assertRaises(temporal.BatchValidationError):
                store.write_batch([turn('D1'), turn('D2'), turn('D3')])
            self.assertEqual(store._records, {})
            self.assertEqual(store.evicted_count, 0)

    def test_same_turn_handles_duplicate_handles_and_missing_turns_rejected(self):
        invalid = [response(('D1', [add('D1', 'new:x'), add('D1', 'new:x')])),
                   response(('D1', [add('D1', 'new:x'),
                       dict(op='confirm', id='new:x', source_ids=['D1'])])),
                   response(), ('{"operations":[]}', 0, 7), ('broken JSON', 0, 7),
                   response(('wrong', []))]
        for raw in invalid:
            store = self.store(Mock(return_value=raw))
            with self.assertRaises(temporal.BatchValidationError):
                store.write_batch([turn('D1')])
            self.assertEqual(store._records, {})

    def test_embedding_error_is_not_a_validation_repair_and_window_rolls_back(self):
        extract = Mock(return_value=response(('D1', [add('D1', 'new:a')]), ('D2', [])))
        module = WindowedFactStore(max_items=2, embedder=FakeEmbeddings(),
            extractor=extract, fact_history_mode='versioned')
        module.write(turn('D1'))
        before = module.inspect()
        with patch.object(module.long_term.embedder, 'embed', side_effect=ValueError('bad vectors')):
            with self.assertRaisesRegex(ValueError, 'bad vectors'):
                module.write(turn('D2'))
        self.assertEqual(module.inspect(), before)
        self.assertEqual(extract.call_count, 1)
        module.write(turn('D2'))
        self.assertEqual(module.inspect()['config']['pending_entries'], 0)

    def test_budget_prevents_call_and_compaction_keeps_stored_provenance(self):
        extract = Mock(return_value=response(('D1', [add('D1', 'new:a')])) )
        store = self.store(extract)
        store.write_batch([turn('D1')])
        before = store.inspect()
        compact = store._batch_versions()
        self.assertNotIn('source_text', compact[0])
        self.assertNotIn('metadata', compact[0])
        self.assertIn('source_text', before['entries'][0]['metadata'])
        with patch.dict(temporal.BATCH_POLICY, max_input_bytes=1):
            with self.assertRaisesRegex(ValueError, 'input byte budget'):
                store.write_batch([turn('D2')])
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(store.inspect(), before)

    def test_scoped_output_settings_and_truncation_diagnostics(self):
        def extract(*args):
            self.assertEqual(memory_request_options.get()['max_tokens'], 16384)
            memory_response.set(dict(finish_reason='length', response_id='truncated'))
            return response(('D1', []))
        store = self.store(Mock(side_effect=extract))
        with self.assertRaisesRegex(temporal.BatchValidationError, 'truncated'):
            store.write_batch([turn('D1')])
        self.assertEqual(memory_request_options.get(), {})
        self.assertIsNone(memory_response.get())
        artifact = json.loads(next(Path(self.folder.name).glob('*.json')).read_text())
        self.assertEqual(artifact['provider']['response_id'], 'truncated')

    def test_api_keeps_three_value_contract_and_applies_scoped_options(self):
        fake = FakeOpenAIClient('{}')
        token = memory_request_options.set(dict(max_tokens=16384, response_format={'type': 'json_object'}))
        info_token = memory_response.set(None)
        try:
            with patch.object(API, 'client', fake):
                result = API.call_api('system', 'input')
            self.assertEqual(len(result), 3)
            self.assertEqual(fake.calls[0]['max_tokens'], 16384)
            self.assertIn('finish_reason', memory_response.get())
        finally:
            memory_request_options.reset(token)
            memory_response.reset(info_token)

    def test_existing_numeric_reference_and_aliases_validate_resolved_targets(self):
        extract = Mock(side_effect=[response(('D1', [add('D1', 'new:a')])),
            response(('D2', [dict(op='confirm', id='version-1', source_ids=['D2'])]))])
        store = self.store(extract)
        store.write_batch([turn('D1')])
        store.write_batch([turn('D2')])
        before = store.inspect()
        extract.return_value = response(('D3', [add('D3', 'new:b')]),
            ('D4', [dict(op='confirm', id='version-1', source_ids=['D4']),
                    dict(op='confirm', id='new:b', source_ids=['D4'])]))
        extract.side_effect = None
        with self.assertRaisesRegex(temporal.BatchValidationError, 'Repeated resolved'):
            store.write_batch([turn('D3'), turn('D4')])
        self.assertEqual(store.inspect(), before)

    def test_benchmark_blocks_qa_and_reports_ingestion_errors_after_repair_exhaustion(self):
        import Benchmark
        from benchmark_helpers import FakeTokenizer
        from test_hybrid_integration import dataset
        original = Benchmark.MemoryFactory.create_memory_module
        def create(mode, **options):
            return original(mode, **{**options, 'embedder': FakeEmbeddings()})
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Benchmark.MemoryFactory, 'create_memory_module', side_effect=create), \
             patch.object(Benchmark, 'call_api', return_value=('{"operations":[]}', 0, 7)) as extract, \
             patch.object(Benchmark, 'client') as answer_client:
            job = Benchmark.BenchmarkJob(dataset(), dict(module='windowed_fact_store', window_size=2))
            job.run()
        report = job.snapshot()
        self.assertEqual(report['status'], 'completed')
        self.assertEqual(report['ingestion_outcome']['status'], 'completed_with_errors')
        self.assertEqual(report['ingestion_outcome']['failed_conversations'], 1)
        self.assertTrue(all(c['diagnostics']['status'] == 'ingestion_blocked' for c in report['cases']))
        self.assertEqual(extract.call_count, 2)
        answer_client.with_options.assert_not_called()
        self.assertEqual(len(report['memories'][0]['ingestion']['memory_failure_artifacts']), 2)
