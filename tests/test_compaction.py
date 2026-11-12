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
from RequestPolicy import cancel_event, RequestCancelled, CheckpointError
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
        for outputs in ([response(''), response(None), response('')], [response('x'*90)]*3, [RuntimeError('network')]):
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
            self.assertEqual(module.compressor.call_count, 1 if isinstance(outputs[0], Exception) else 3)

    def test_measured_overshoot_recovery_on_third_attempt_from_original_source(self):
        # Reproduce conv-41's actual target and rejected output sizes.
        module = self.make('a'*6357, retain_percent=75)
        module.compressor.side_effect = [response('x'*5338), response('y'*4906), response('z'*4000)]
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            event = module.compact()
        finally:
            collector.reset(token)
        self.assertEqual(event['target_tokens'], 4767)
        self.assertEqual(event['max_attempts'], 3)
        self.assertEqual([a['status'] for a in event['attempts']], ['invalid', 'invalid', 'accepted'])
        budgets = [a['requested_tokens'] for a in event['attempts']]
        self.assertGreater(budgets[0], budgets[1])
        self.assertGreater(budgets[1], budgets[2])
        calls = module.compressor.call_args_list
        self.assertIn('5338 benchmark tokens', calls[1].args[0])
        self.assertIn('4906 benchmark tokens', calls[2].args[0])
        self.assertTrue(all(c.args[1] == 'Conversation:\n' + 'a'*6357 for c in calls))
        self.assertEqual(metrics['memory_llm_calls'], 3)
        self.assertEqual(metrics['memory_tokens'], 21)
        self.assertEqual(module.depth, 1)
        self.assertTrue(event['committed'])

    def test_exhausted_budget_retries_report_measurement_without_changing_state(self):
        module = self.make()
        module.compressor.return_value = response('x'*60)
        before = module.export_state()['state']['entries']
        with self.assertRaisesRegex(ValueError, 'after 3 attempts.*over_budget.*60.*50'):
            module.compact()
        self.assertEqual(module.compressor.call_count, 3)
        self.assertEqual(module.export_state()['state']['entries'], before)
        self.assertEqual(module.depth, 0)
        self.assertTrue(all(a['validation_error'] == 'over_budget' for a in module.events[-1]['attempts']))
        self.assertFalse(module.events[-1]['committed'])

    def test_retry_limit_cannot_be_configured(self):
        with self.assertRaisesRegex(ValueError, 'Unsupported compaction option'):
            self.make(max_attempts=10)
        options = Benchmark.options_for(dataset(), {'module': 'compaction', 'max_attempts': 10})
        self.assertNotIn('max_attempts', options)

    def test_length_stop_is_not_accepted_as_complete_summary(self):
        module = self.make()
        def incomplete(*args):
            memory_response.set({'finish_reason': 'length'})
            return response('short')
        module.compressor.side_effect = incomplete
        with self.assertRaises(ValueError):
            module.compact()
        self.assertEqual(module.compressor.call_count, 3)
        self.assertTrue(all(a['validation_error'] == 'incomplete_response' for a in module.events[-1]['attempts']))
        self.assertTrue(all(a['after_tokens'] == len('short') for a in module.events[-1]['attempts']))
        self.assertLess(module.events[-1]['attempts'][1]['requested_tokens'],
                        module.events[-1]['attempts'][0]['requested_tokens'])

    def test_tiny_budget_and_provider_guard_fail_without_calling(self):
        for text, percent in [('a', .1), ('x'*1_000_000, 50)]:
            module = self.make(text, retain_percent=percent)
            with self.assertRaises(ValueError):
                module.compact()
            module.compressor.assert_not_called()

    def test_empty_length_limited_response_tightens_retry_budget(self):
        module = self.make()
        def generate(*args):
            memory_response.set({'finish_reason': 'length'})
            return response('')
        module.compressor.side_effect = generate
        with self.assertRaises(ValueError):
            module.compact()
        attempts = module.events[-1]['attempts']
        self.assertTrue(all(a['validation_error'] == 'incomplete_response' for a in attempts))
        self.assertGreater(attempts[0]['requested_tokens'], attempts[1]['requested_tokens'])

    def test_oversized_append_retries_against_trigger_limit(self):
        module = self.make('', compaction_mode='repeated', compaction_trigger_tokens=20)
        module.compressor.side_effect = [response('x'*30), response('summary')]
        module.write(MemoryEntry('A'*100, {'dialogue_id': 'D1:1'}))
        self.assertEqual(module.retrieve()[0].text, 'summary')
        event = module.events[-1]
        self.assertEqual(event['target_tokens'], 50)
        self.assertEqual(event['acceptance_limit_tokens'], 20)
        self.assertEqual([a['status'] for a in event['attempts']], ['invalid', 'accepted'])
        self.assertTrue(event['committed'])
        self.assertEqual(module.ingested_entries, 1)

    def test_candidate_archive_failure_retains_known_usage_and_is_fatal(self):
        module = self.make()
        original = compact_module.capture
        def capture(kind, value):
            if kind == 'compaction-candidate':
                raise OSError('disk full')
            return original(kind, value)
        metrics = dict(memory_llm_calls=0, memory_tokens=0)
        token = collector.set(metrics)
        try:
            with patch.object(compact_module, 'capture', side_effect=capture):
                with self.assertRaises(CheckpointError) as failure:
                    module.compact()
        finally:
            collector.reset(token)
        self.assertTrue(failure.exception.persistence_failure)
        self.assertEqual(metrics['memory_llm_calls'], 1)
        self.assertEqual(metrics['memory_tokens'], 7)
        self.assertEqual(module.compressor.call_count, 1)
        self.assertEqual(module.events[-1]['attempts'][0]['tokens'], 7)
        self.assertEqual(module.retrieve()[0].text, 'a'*100)
        self.assertFalse(module.events[-1]['committed'])

    def test_budget_feedback_changes_output_of_length_estimator(self):
        import re
        module = self.make('a'*1000)
        def approximate(system, source):
            requested = int(re.search(r'Use at most (\d+)', system).group(1))
            return response('x' * int(requested * 1.25))
        module.compressor.side_effect = approximate
        event = module.compact()
        self.assertEqual(len(event['attempts']), 2)
        self.assertEqual(event['attempts'][0]['status'], 'invalid')
        self.assertLessEqual(event['after_tokens'], event['target_tokens'])

    def test_transaction_archive_failure_rolls_back_manual_and_repeated_commits(self):
        for repeated in (False, True):
            with self.subTest(repeated=repeated):
                module = self.make('A'*30, compaction_mode='repeated' if repeated else 'one_shot',
                                   compaction_trigger_tokens=40)
                before = module.inspect()
                original = compact_module.capture
                def capture(kind, value):
                    if kind == 'compaction-transaction-state':
                        raise OSError('transaction archive unavailable')
                    return original(kind, value)
                with patch.object(compact_module, 'capture', side_effect=capture):
                    with self.assertRaises(CheckpointError):
                        if repeated:
                            module.write(MemoryEntry('B'*20))
                        else:
                            module.compact()
                after = module.inspect()
                self.assertEqual(after['entries'], before['entries'])
                self.assertEqual(after['config'], before['config'])
                self.assertTrue(all(e['committed'] is False for e in module.events))

    def test_final_checkpoint_failure_is_fatal_and_preserves_active_memory(self):
        module = self.make()
        callback = Mock(side_effect=[None, OSError('checkpoint unavailable')])
        token = compact_module.checkpoint.set(callback)
        try:
            with self.assertRaises(CheckpointError) as error:
                module.compact()
        finally:
            compact_module.checkpoint.reset(token)
        self.assertTrue(error.exception.persistence_failure)
        self.assertEqual(module.retrieve()[0].text, 'a'*100)
        self.assertEqual(module.compressor.call_count, 1)
        self.assertFalse(module.events[-1]['committed'])

    def test_partial_transaction_archive_failure_restores_both_staged_operations(self):
        module = self.make('A'*30, compaction_mode='repeated', compaction_trigger_tokens=40)
        module.compressor.return_value = response('short')
        before = module.inspect()
        original = compact_module.capture
        saved = 0
        def capture(kind, value):
            nonlocal saved
            if kind == 'compaction-transaction-state':
                saved += 1
                if saved == 2:
                    raise OSError('second transaction snapshot failed')
            return original(kind, value)
        with patch.object(compact_module, 'capture', side_effect=capture):
            with self.assertRaises(CheckpointError):
                module.write(MemoryEntry('B'*100, {'dialogue_id': 'D1:2'}))
        after = module.inspect()
        self.assertEqual(after['entries'], before['entries'])
        self.assertEqual(after['config'], before['config'])
        self.assertEqual(len(module.events), 2)
        from ExperimentRecording import get
        for event in module.events:
            self.assertFalse(event['committed'])
            state = get(module.audit_archive, event['transaction_state_artifact'])
            self.assertEqual(state['entries'], before['entries'])
            self.assertEqual(state['depth'], 0)

    def test_initial_checkpoint_failure_never_sends_a_paid_request(self):
        module = self.make()
        token = compact_module.checkpoint.set(Mock(side_effect=OSError('checkpoint unavailable')))
        try:
            with self.assertRaises(CheckpointError):
                module.compact()
        finally:
            compact_module.checkpoint.reset(token)
        module.compressor.assert_not_called()
        self.assertEqual(module.depth, 0)

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
        module.compressor.side_effect = [response('short')] + [response('bad'*50)]*3
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

    def test_third_attempt_recovery_reaches_qa_and_records_all_costs(self):
        job = Benchmark.BenchmarkJob(dataset(2), dict(module='compaction'))
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compact_module, 'call_api', side_effect=[response('x'*100), response('y'*100), response('Google')]) as compressor, \
             patch.object(Benchmark, 'client', FakeOpenAIClient()), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .01, 7)):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['ingestion_outcome']['status'], 'successful')
        self.assertEqual(compressor.call_count, 3)
        self.assertTrue(all(c['correct'] == 1 for c in result['cases']))
        self.assertEqual(result['memories'][0]['ingestion']['memory_tokens'], 21)
        self.assertEqual(enrich_report(result)['comparison']['rows'][0]['overall']['compaction']['attempt_count'], 3)
        from ExperimentRecording import validate
        validate(result)

    def test_archive_failure_stops_later_conversations_without_losing_paid_usage(self):
        data = dataset(1)
        other = deepcopy(data[0])
        other['sample_id'] = 'two'
        data.append(other)
        job = Benchmark.BenchmarkJob(data, dict(module='compaction'))
        original = compact_module.capture
        def capture(kind, value):
            if kind == 'compaction-candidate':
                raise OSError('disk full')
            return original(kind, value)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compact_module, 'call_api', return_value=response('Google')) as compressor, \
             patch.object(compact_module, 'capture', side_effect=capture), \
             patch.object(Benchmark, 'client', side_effect=AssertionError('no QA after lost checkpoint')):
            job.run()
        result = job.snapshot()
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(compressor.call_count, 1)
        self.assertEqual(len(result['memories']), 1)
        self.assertEqual(result['memories'][0]['ingestion']['memory_tokens'], 7)
        self.assertFalse(result['memories'][0]['formation_complete'])

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
