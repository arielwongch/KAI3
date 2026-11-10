"""Offline compaction contracts: budgets, rollback, lineage, chat, and frozen QA."""
import json
import os
import sys
import threading
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
sys.path.insert(0, 'src')
import app
import Benchmark
import Compaction as compact_module
import ReAct
from Compaction import Compaction, validate_options
from Diagnostics import collector, memory_response
from MemoryContext import build_memory_context
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from RequestPolicy import cancel_event, RequestCancelled
from ResultAnalysis import enrich_report
from benchmark_helpers import FakeTokenizer
from test_controlled_comparison import dataset
from test_memory_integration import FakeOpenAIClient
from test_binary_benchmark import judgment


def response(text='Alice: cat', usage=7):
    return text, 0, usage


class CompactionTests(unittest.TestCase):
    def make(self, text='a'*100, **options):
        module = Compaction(tokenizer=FakeTokenizer(), compressor=Mock(return_value=response()), **options)
        if text:
            module.write(MemoryEntry(text, {'dialogue_id': 'D1:1'}))
        return module

    def test_variable_percentage_rounding_framing_unicode_and_no_query(self):
        module = self.make('Alice: 香港 123\n' * 10, retain_percent=33.3)
        before = module.inspect()['config']['active_tokens']
        module.write(MemoryEntry('Bob: tomorrow', {'dialogue_id': 'D1:2'}))
        before += 2 + len('Bob: tomorrow')
        event = module.compact()
        self.assertEqual(event['target_tokens'], int(before * .333))
        self.assertLessEqual(event['after_tokens'], event['target_tokens'])
        packed = build_memory_context(module, 'SECRET QUESTION', 2000, FakeTokenizer())
        self.assertEqual(packed['text'], 'Alice: cat')
        self.assertNotIn('SECRET QUESTION', module.compressor.call_args.args[1])
        self.assertEqual(module.retrieve()[0].metadata['source_ids'], ['D1:1', 'D1:2'])
        self.assertTrue(module.retrieve()[0].metadata['lineage_only'])
        self.assertTrue(event['committed'])

    def test_one_hundred_and_empty_are_noops(self):
        for text in ('', 'same raw memory'):
            module = self.make(text, retain_percent=100)
            before = module.retrieve()
            self.assertEqual(module.compact()['status'], 'noop')
            self.assertEqual(module.retrieve(), before)
            module.compressor.assert_not_called()

    def test_reject_invalid_controls_and_inapplicable_settings(self):
        for value in (True, False, 0, -1, 101, '50', float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_options({'retain_percent': value})
        for options in ({'compaction_mode': 'other'}, {'compaction_trigger_tokens': True},
                        {'compaction_source_entries': 0}, {'compaction_mode': 'repeated', 'compaction_source_entries': 5}):
            with self.assertRaises(ValueError):
                self.make(**options)
        with self.assertRaises(ValueError):
            MemoryFactory.create_memory_module('sliding_window', retain_percent=50)
        with self.assertRaises(ValueError):
            Benchmark.options_for(dataset(), {'module': 'summarization', 'retain_percent': 50})
        with self.assertRaises(ValueError):
            Benchmark.options_for(dataset(), {'module': 'compaction', 'retrieval_k': 1})

    def test_overbudget_regenerates_and_accounts_for_both_attempts(self):
        module = self.make()
        module.compressor.side_effect = [response('x'*60), response('short')]
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            event = module.compact()
        finally:
            collector.reset(token)
        self.assertEqual(metrics['memory_llm_calls'], 2)
        self.assertEqual(metrics['memory_tokens'], 14)
        self.assertEqual([a['status'] for a in event['attempts']], ['invalid', 'accepted'])
        self.assertTrue(metrics['compaction_events'][0]['committed'])
        self.assertNotIn('x'*60, module.compressor.call_args.args[1])

    def test_terminal_failure_preserves_active_state_and_unknown_usage(self):
        for outputs in ([response(''), response(None)], [response('x'*90)]*2, [RuntimeError('network')]):
            module = self.make()
            module.compressor.side_effect = outputs
            before = module.retrieve()
            metrics = dict(memory_llm_calls=0, memory_tokens=0)
            token = collector.set(metrics)
            try:
                with self.assertRaises((ValueError, RuntimeError)):
                    module.compact()
            finally:
                collector.reset(token)
            self.assertEqual(module.retrieve(), before)
            self.assertEqual(module.depth, 0)
            self.assertFalse(module.events[-1]['committed'])
            if isinstance(outputs[0], Exception):
                self.assertIsNone(metrics['memory_tokens'])
            self.assertLessEqual(module.compressor.call_count, 2)

    def test_length_stop_is_not_accepted_as_complete_summary(self):
        module = self.make()
        def incomplete(*args):
            memory_response.set({'finish_reason': 'length'})
            return response('short')
        module.compressor.side_effect = incomplete
        with self.assertRaises(ValueError):
            module.compact()
        self.assertEqual(module.compressor.call_count, 2)

    def test_tiny_budget_and_provider_guard_fail_without_calling(self):
        for text, percent in [('a', .1), ('x'*1_000_000, 50)]:
            module = self.make(text, retain_percent=percent)
            with self.assertRaises(ValueError):
                module.compact()
            module.compressor.assert_not_called()

    def test_repeated_lineage_reuses_only_compacted_state(self):
        module = self.make('', compaction_mode='repeated', compaction_trigger_tokens=45)
        module.compressor.side_effect = [response('first'), response('second')]
        module.write(MemoryEntry('A'*30, {'dialogue_id': 'D1:1'}))
        module.write(MemoryEntry('B'*30, {'dialogue_id': 'D1:2'}))
        module.write(MemoryEntry('C'*30, {'dialogue_id': 'D1:3'}))
        second_source = module.compressor.call_args.args[1]
        self.assertIn('first', second_source)
        self.assertNotIn('A'*30, second_source)
        self.assertEqual(module.depth, 2)
        self.assertEqual(module.events[1]['parent_event_id'], module.events[0]['event_id'])
        self.assertEqual(module.retrieve()[0].metadata['source_ids'], ['D1:1', 'D1:2'])
        self.assertEqual(module.retrieve()[-1].metadata['dialogue_id'], 'D1:3')

    def test_failed_oversized_append_rolls_back_prior_staged_compaction(self):
        module = self.make('A'*30, compaction_mode='repeated', compaction_trigger_tokens=40)
        module.compressor.side_effect = [response('short'), response('bad'*50), response('bad'*50)]
        before = module.retrieve()
        with self.assertRaises(ValueError):
            module.write(MemoryEntry('B'*100))
        self.assertEqual(module.retrieve(), before)
        self.assertEqual(module.depth, 0)
        self.assertEqual(module.ingested_entries, 1)
        self.assertTrue(all(not e['committed'] for e in module.events))

    def test_oversized_first_entry_and_final_fit_failure(self):
        module = self.make('', compaction_mode='repeated', compaction_trigger_tokens=20)
        module.compressor.return_value = response('x'*30)
        with self.assertRaises(ValueError):
            module.write(MemoryEntry('A'*100))
        self.assertEqual(module.retrieve(), [])
        self.assertFalse(module.events[-1]['committed'])
        module.compressor.return_value = response('short')
        module.write(MemoryEntry('A'*100))
        self.assertEqual(module.depth, 1)

    def test_cancel_after_generation_preserves_state(self):
        module = self.make()
        cancel = threading.Event()
        def stop(*args):
            cancel.set()
            return response()
        module.compressor.side_effect = stop
        token = cancel_event.set(cancel)
        try:
            with self.assertRaises(RequestCancelled):
                module.compact()
        finally:
            cancel_event.reset(token)
        self.assertEqual(module.retrieve()[0].text, 'a'*100)
        self.assertFalse(module.events[-1]['committed'])

    def test_source_scope_incomplete_entries_and_inspection_detachment(self):
        module = self.make('', compaction_source_entries=2)
        for text in ('first', 'second', 'third'):
            module.write(MemoryEntry(text))
        module.write(MemoryEntry('unfinished', {'completed': False}))
        module.write(MemoryEntry(' '))
        self.assertEqual([e.text for e in module.retrieve()], ['second', 'third'])
        self.assertEqual(module.inspect()['config']['omitted_source_entries'], 1)
        state = module.inspect()
        state['entries'][0]['text'] = 'changed'
        self.assertEqual(module.retrieve()[0].text, 'second')

    def test_complete_context_is_not_silently_packed_or_ranked(self):
        module = self.make()
        with self.assertRaisesRegex(ValueError, 'No secondary packing'):
            build_memory_context(module, 'query', 20, FakeTokenizer())
        with self.assertRaises(ValueError):
            build_memory_context(module, 'query', 200, FakeTokenizer(), 1)
        self.assertEqual(build_memory_context(module, '', 100, FakeTokenizer())['memory_context_tokens'], 100)

    def test_frozen_artifact_roundtrip_and_identity_mismatches(self):
        module = self.make()
        module.compact()
        artifact = module.export_state()
        restored = self.make('')
        restored.restore_state(artifact)
        self.assertEqual(restored.inspect(), module.inspect())
        restored.compressor.assert_not_called()
        broken = deepcopy(artifact)
        broken['state']['entries'][0]['text'] = 'tampered'
        with self.assertRaises(ValueError):
            restored.restore_state(broken)
        with self.assertRaises(ValueError):
            self.make('', retain_percent=25).restore_state(artifact)
        invalid = deepcopy(artifact)
        invalid['state']['config']['depth'] = -1
        invalid['sha256'] = compact_module.digest(invalid['state'])
        before = restored.inspect()
        with self.assertRaises(ValueError):
            restored.restore_state(invalid)
        self.assertEqual(restored.inspect(), before)

    def test_write_waits_for_manual_compaction_without_losing_new_turn(self):
        module = self.make()
        entered, release, wrote = threading.Event(), threading.Event(), threading.Event()
        errors = []
        def blocked(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test did not release compressor')
            return response('short')
        module.compressor.side_effect = blocked
        def compact():
            try:
                module.compact()
            except Exception as error:
                errors.append(error)
        def write():
            module.write(MemoryEntry('new turn'))
            wrote.set()
        first = threading.Thread(target=compact)
        second = threading.Thread(target=write)
        first.start()
        try:
            self.assertTrue(entered.wait(5))
            second.start()
            self.assertFalse(wrote.wait(.05))
        finally:
            release.set()
            first.join(5)
            if second.ident:
                second.join(5)
        self.assertEqual(errors, [])
        self.assertEqual([e.text for e in module.retrieve()], ['short', 'new turn'])

    def test_sweep_conditions_share_raw_identity_and_use_separate_ratios(self):
        sys.path.insert(0, 'tools')
        from compaction_sweep import make_campaign
        data = dataset()
        campaign = make_campaign(data, [100, 50, 12.5], source_entries=10, repeats=2)
        self.assertEqual(len(campaign['conditions']), 6)
        self.assertEqual([c['options']['retain_percent'] for c in campaign['conditions'][:3]], [100, 50, 12.5])
        self.assertEqual(campaign['sources'][0]['conversation_sha256'], compact_module.digest(data[0]['conversation']))


class CompactionIntegrationTests(unittest.TestCase):
    def run_job(self, **options):
        job = Benchmark.BenchmarkJob(dataset(2), dict(module='compaction', **options))
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compact_module, 'call_api', return_value=response('Bob: Google')), \
             patch.object(Benchmark, 'client', FakeOpenAIClient()), \
             patch.object(Benchmark, 'judge_answer', return_value=judgment(1)):
            job.run()
        return job

    def test_one_shot_reuses_one_state_without_claiming_evidence_recall(self):
        job = self.run_job(retain_percent=50)
        result = job.snapshot()
        self.assertEqual(len(result['cases']), 2)
        memory = result['memories'][0]
        self.assertEqual(memory['ingestion']['memory_llm_calls'], 1)
        hashes = {c['diagnostics']['compaction_state_sha256'] for c in result['cases']}
        self.assertEqual(len(hashes), 1)
        self.assertTrue(all(c['evidence_recall'] is None for c in result['cases']))
        derived = enrich_report(result)['comparison']['rows'][0]['overall']['compaction']
        self.assertEqual(derived['attempt_count'], 1)
        self.assertEqual(derived['requested_retain_percent'], 50)
        self.assertGreater(derived['total_seconds'], 0)

    def test_repeated_mode_does_not_force_final_compaction(self):
        result = self.run_job(compaction_mode='repeated', compaction_trigger_tokens=2000).snapshot()
        self.assertEqual(result['memories'][0]['ingestion']['memory_llm_calls'], 0)
        self.assertEqual(result['memories'][0]['memory']['config']['depth'], 0)
        self.assertEqual(enrich_report(result)['comparison']['rows'][0]['overall']['compaction']['attempt_count'], 0)

    def test_resume_reuses_frozen_memory_and_preserves_original_cost(self):
        previous = self.run_job().snapshot()
        previous['cases'][0].update(correct=None, judge_error='retry')
        resumed = Benchmark.BenchmarkJob.resume(dataset(2), previous)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compact_module, 'call_api', side_effect=AssertionError('must reuse')), \
             patch.object(Benchmark, 'judge_answer', return_value=judgment(1)):
            resumed.run()
        current = resumed.snapshot()
        self.assertEqual(current['memories'][0]['ingestion']['memory_llm_calls'], 0)
        self.assertIn('reused_artifact_sha256', current['memories'][0]['ingestion'])
        metric = enrich_report(current)['comparison']['rows'][0]['overall']['compaction']
        self.assertEqual(metric['attempt_count'], 1)
        previous['memory_prompt_hash'] = 'different'
        with self.assertRaises(ValueError):
            Benchmark.BenchmarkJob.resume(dataset(2), previous)

    def test_chat_manual_compaction_and_fixed_settings(self):
        app.chat_memory_modules.clear()
        self.addCleanup(app.chat_memory_modules.clear)
        client = app.app.test_client()
        with patch('MemoryContext.get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(ReAct, 'client', FakeOpenAIClient()), \
             patch.object(compact_module, 'call_api', return_value=response('cat')):
            options = dict(compaction_mode='one_shot', retain_percent=50)
            sent = client.post('/get', json=dict(message='cat', chat_id='compact-test', memory_module='compaction', memory_options=options))
            self.assertEqual(sent.status_code, 200, sent.json)
            result = client.post('/api/chats/compact-test/compact', json={'retain_percent': 25})
            self.assertEqual(result.status_code, 200, result.json)
            self.assertLessEqual(result.json['event']['actual_retain_percent'], 25)
            snapshot = client.get('/api/chats/compact-test/diagnostics').json
            self.assertEqual(snapshot['turns'][-1]['operation'], 'manual_compaction')
            self.assertEqual(snapshot['turns'][-1]['memory_tokens'], 7)
            self.assertEqual(snapshot['memory_options']['retain_percent'], 50)
            self.assertEqual(client.post('/api/chats/compact-test/compact', json={'retain_percent': True}).status_code, 400)
            self.assertEqual(client.post('/api/chats/missing/compact', json={}).status_code, 404)


if __name__ == '__main__':
    unittest.main()
