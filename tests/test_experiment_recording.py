"""Synthetic offline custody tests; no claims about compressor/reader quality."""
from copy import deepcopy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
os.environ.setdefault('PYTHON_DOTENV_DISABLED', '1')
import app
import Benchmark
import BenchmarkWorker
import API
import Compaction as compaction_module
import ExperimentRecording as R
import RequestPolicy
import Summarization
from BenchmarkStore import atomic_json, read_json, path_for, delete_run_files
from Compaction import Compaction
from MemoryEntry import MemoryEntry
from MemoryFactory import MemoryFactory
from ResultAnalysis import enrich_report, phase_usage
from benchmark_helpers import FakeTokenizer
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient
from test_benchmark_recovery import ProviderError


def dataset():
    return [dict(sample_id='audit', conversation={'session_1': [
        dict(speaker='Alice', dia_id='D1:1', text='I live in Rome. ' * 12),
        dict(speaker='Bob', dia_id='D1:2', text='I drink tea. ' * 12)]}, qa=[
        dict(question='FUTURE QUESTION ONE?', answer='GOLD ONLY', category=4, evidence=['D1:1']),
        dict(question='FUTURE QUESTION TWO?', answer='GOLD ONLY', category=1, evidence=['D1:2'])])]


class Embedder:
    def chunks(self, text):
        return [text]

    def embed(self, texts):
        return [[1., 0.] for _ in texts]


class ArchiveTests(unittest.TestCase):
    def test_content_addressing_detachment_missing_corruption_and_legacy(self):
        archive = R.new_archive()
        source = {'text': '<script>unsafe()</script>', 'ordered': ['b', 'a']}
        ref = R.put(archive, 'source', source)
        self.assertEqual(ref, R.put(archive, 'source', source))
        self.assertEqual(len(archive['artifacts']), 1)
        source['ordered'].reverse()
        self.assertEqual(R.get(archive, ref)['ordered'], ['b', 'a'])
        report = dict(recording=archive, reference=ref)
        R.validate(json.loads(json.dumps(report)))
        broken = deepcopy(report)
        broken['recording']['artifacts'][ref['artifact_sha256']]['value']['text'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'Corrupt'):
            R.validate(broken)
        broken = deepcopy(report)
        broken['recording']['artifacts'].clear()
        with self.assertRaisesRegex(ValueError, 'Missing'):
            R.validate(broken)
        R.validate(dict(cases=[]))
        self.assertIn('comparison', enrich_report(dict(cases=[])))

    def test_all_architecture_state_roundtrips_vectors_versions_pending_and_counters(self):
        def make(mode):
            return MemoryFactory.create_memory_module(mode, tokenizer=FakeTokenizer(),
                embedder=Embedder(), extractor=Mock(side_effect=AssertionError('no extraction during restore')))

        def seed(module):
            for child in getattr(module, 'components', {}).values():
                seed(child)
            for key in ('window', 'long_term'):
                if hasattr(module, key):
                    seed(getattr(module, key))
            entry = MemoryEntry('exact active text', dict(version_id='v-1', source_ids=['D1:1'], status='current'))
            if hasattr(module, 'buffer'):
                module.buffer.append(deepcopy(entry))
            if hasattr(module, 'summary'):
                module.summary = 'exact summary'
                module.truncated = True
            if hasattr(module, '_pending'):
                module._pending = [deepcopy(entry)]
            if hasattr(module, '_entries'):
                module._entries = [deepcopy(entry)]
                module.ingested_entries = 7
            for key in ('_records', '_facts'):
                if hasattr(module, key):
                    records = getattr(module, key)
                    vector = [[.25, .75]] if isinstance(records, list) else [.25, .75]
                    setattr(module, key, [(deepcopy(entry), vector)] if isinstance(records, list)
                            else {'v-1': (deepcopy(entry), vector)})
            for key in ('_next_id', '_revision', 'evicted_count'):
                if hasattr(module, key):
                    setattr(module, key, 7)

        for mode in Benchmark.MODULES:
            with self.subTest(mode=mode):
                original, restored = make(mode), make(mode)
                seed(original)
                archive = R.new_archive()
                ref = R.freeze(original, archive)
                R.validate(dict(recording=archive, state=ref))
                R.restore(restored, archive, ref)
                self.assertEqual(R.freeze(restored, archive), ref)
                self.assertEqual(restored.inspect(), original.inspect())
                sizes = R.state_storage(archive, ref)
                self.assertGreater(sizes['active_logical_state_serialized_bytes'], 0)
                self.assertGreater(sizes['frozen_snapshot_artifact_bytes'], 0)
                self.assertNotIn('test-only', json.dumps(archive))

    def test_incompatible_state_is_rejected_before_mutation(self):
        archive = R.new_archive()
        source = MemoryFactory.create_memory_module('sliding_window', max_items=3)
        source.write(MemoryEntry('before'))
        ref = R.freeze(source, archive)
        target = MemoryFactory.create_memory_module('sliding_window', max_items=2)
        before = target.inspect()
        with self.assertRaisesRegex(ValueError, 'capacity'):
            R.restore(target, archive, ref)
        self.assertEqual(target.inspect(), before)


class CompactionCustodyTests(unittest.TestCase):
    def make(self, **options):
        return Compaction(tokenizer=FakeTokenizer(), compressor=Mock(return_value=('  exact replacement\n', 0, 7)), **options)

    def test_independent_percentages_share_exact_raw_source_and_candidates_are_verbatim(self):
        sources = []
        for percent in (25, 50, 100):
            memory = self.make(retain_percent=percent)
            memory.write(MemoryEntry('raw source ' * 30, {'dialogue_id': 'D1:1'}))
            event = memory.compact()
            source = R.get(memory.audit_archive, event['source_artifact'])
            sources.append(source['rendered_text'])
            if percent != 100:
                candidate = R.get(memory.audit_archive, event['attempts'][0]['candidate_artifact'])
                self.assertEqual(candidate, '  exact replacement\n')
                replacement = R.get(memory.audit_archive, event['replacement_artifact'])
                self.assertEqual(replacement[0]['text'], candidate.strip())
                self.assertEqual(R.get(memory.audit_archive, event['transaction_state_artifact'])['entries'], replacement)
            self.assertEqual([e.text for e in memory.retrieve()], [
                'raw source ' * 30 if percent == 100 else 'exact replacement'])
        self.assertEqual(sources, [sources[0]] * 3)

    def test_repeated_parent_and_uncommitted_second_operation_rollback(self):
        memory = self.make(compaction_mode='repeated', compaction_trigger_tokens=80, retain_percent=50)
        memory.compressor.side_effect = [('x'*20, 0, 7), ('y'*60, 0, 7)]
        memory.write(MemoryEntry('a'*70, {'dialogue_id': 'D1:1'}))
        before = memory.retrieve()
        # First compaction succeeds, combined input is still oversized, second
        # candidate and both regenerations fail the 50% budget.
        memory.compressor.side_effect = [('x'*20, 0, 7), ('y'*90, 0, 7), ('z'*90, 0, None), ('w'*90, 0, 7)]
        with self.assertRaises(ValueError):
            memory.write(MemoryEntry('b'*70, {'dialogue_id': 'D1:2'}))
        first, second = memory.events
        self.assertEqual(second['parent_event_id'], first['event_id'])
        self.assertEqual(R.get(memory.audit_archive, second['source_artifact'])['rendered_text'], 'x'*20+'\n\n'+'b'*70)
        self.assertFalse(first['committed'])
        self.assertFalse(second['committed'])
        self.assertEqual(len(second['attempts']), 3)
        self.assertEqual(memory.retrieve(), before)
        for event in memory.events:
            self.assertEqual(R.get(memory.audit_archive, event['transaction_state_artifact'])['entries'][0]['text'], 'a'*70)

    def test_cancellation_after_generation_keeps_candidate_and_original_memory(self):
        memory = self.make()
        memory.write(MemoryEntry('source '*40))
        cancelled = threading.Event()
        def generate(*args):
            cancelled.set()
            return '  received before cancel\n', 0, None
        memory.compressor.side_effect = generate
        token = RequestPolicy.cancel_event.set(cancelled)
        try:
            with self.assertRaises(RequestPolicy.RequestCancelled):
                memory.compact()
        finally:
            RequestPolicy.cancel_event.reset(token)
        event = memory.events[0]
        self.assertFalse(event['committed'])
        self.assertEqual(event['attempts'][0]['status'], 'cancelled')
        self.assertEqual(R.get(memory.audit_archive, event['attempts'][0]['candidate_artifact']), '  received before cancel\n')
        self.assertEqual(memory.retrieve()[0].text, 'source '*40)


class BenchmarkRecordingTests(unittest.TestCase):
    def run_job(self, mode='compaction'):
        job = Benchmark.BenchmarkJob(dataset(), dict(module=mode, question_limit=0))
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compaction_module, 'call_api', return_value=('Alice: Rome; Bob: tea', 0, 7)), \
             patch.object(Summarization, 'call_api', return_value=('Alice: Rome; Bob: tea', 0, 7)), \
             patch.object(Benchmark, 'client', FakeOpenAIClient('Rome')), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .1, 7)):
            job.run()
        self.assertEqual(job.result['status'], 'completed', job.result.get('error'))
        return job

    def test_exact_question_context_memory_and_request_linkage_no_qa_in_compactor(self):
        report = self.run_job().snapshot()
        R.validate(report)
        memory = report['memories'][0]
        for case in report['cases']:
            d = case['diagnostics']
            self.assertEqual(d['memory_state_artifact'], memory['memory_state_artifact'])
            context = R.get(report['recording'], d['context_artifact'], 'answer-context')
            self.assertEqual(context['supplied_context'], d['supplied_context'])
            self.assertEqual(context['token_count'], len(d['supplied_context']))
            self.assertEqual(context['memory_state_artifact'], d['memory_state_artifact'])
            request = d['provider_requests'][0]
            payload = R.get(report['recording'], request['request_artifact'], 'provider-request')
            self.assertEqual(payload['messages'], context['messages'])
            self.assertEqual(request['request_sha256'], R.sha256(payload))
            self.assertIn('temperature', request['provider_default_parameters'])
            self.assertIsNone(case['evidence_recall'])
        event = memory['memory']['compaction_events'][0]
        compressor_input = R.get(report['recording'], event['attempts'][0]['request_artifact'])
        self.assertNotIn('FUTURE QUESTION', json.dumps(compressor_input))
        self.assertNotIn('GOLD ONLY', json.dumps(compressor_input))
        self.assertEqual(R.get(report['recording'], report['dataset_artifact']), dataset())

    def test_resume_reuses_summarization_and_preserves_successful_identity_across_two_resumes(self):
        previous = self.run_job('summarization').snapshot()
        original = deepcopy(previous['cases'][0])
        previous['cases'] = [original]  # A second question has not yet run.
        resumed = Benchmark.BenchmarkJob.resume(dataset(), previous)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Summarization, 'call_api', side_effect=AssertionError('frozen state must be used')), \
             patch.object(Benchmark, 'client', FakeOpenAIClient('tea')), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .1, 7)):
            resumed.run()
        current = resumed.snapshot()
        self.assertEqual(current['cases'][0], original)
        self.assertEqual(current['memories'][0]['memory_state_artifact'], previous['memories'][0]['memory_state_artifact'])
        self.assertEqual(current['memories'][0]['ingestion']['construction_action'], 'frozen_reuse')
        self.assertEqual(current['cases'][1]['diagnostics']['memory_state_artifact'], original['diagnostics']['memory_state_artifact'])
        current['cases'][1]['correct'] = None
        again = Benchmark.BenchmarkJob.resume(dataset(), current)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Summarization, 'call_api', side_effect=AssertionError('must remain frozen')), \
             patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('prediction must remain frozen')), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .1, 7)):
            again.run()
        final = again.snapshot()
        self.assertEqual(final['status'], 'completed', final.get('error'))
        accounting = enrich_report(final)['comparison']['rows'][0]['overall']['construction']
        self.assertEqual(accounting['unique_construction_count'], 1)
        self.assertEqual(accounting['frozen_reuse_count'], 2)

    def test_resume_rejects_missing_corrupt_incompatible_and_stripped_reports(self):
        original = self.run_job().snapshot()
        for problem in ('missing', 'corrupt', 'code', 'dependencies', 'stripped'):
            report = deepcopy(original)
            if problem == 'missing':
                del report['recording']['artifacts'][report['memories'][0]['memory_state_artifact']['artifact_sha256']]
            elif problem == 'corrupt':
                report['recording']['artifacts'][report['dataset_artifact']['artifact_sha256']]['value'] = []
            elif problem == 'code':
                report['code_identity']['source_sha256'] = 'other'
            elif problem == 'dependencies':
                report['dependency_versions']['openai'] = 'other'
            else:
                report = R.polling_view(report)
            before = deepcopy(report)
            with self.subTest(problem=problem), self.assertRaises(ValueError):
                Benchmark.BenchmarkJob.resume(dataset(), report)
            self.assertEqual(report, before)

    def test_retry_usage_remains_unknown_but_known_lower_bound_and_operation_survive(self):
        archive, metrics = R.new_archive(), {}
        fake = FakeOpenAIClient('received')
        original = fake.chat.completions.create
        calls = []
        def invoke(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                raise ProviderError(503)
            return original(**kwargs)
        token = R.active_archive.set(archive)
        op = R.operation.set(dict(type='compaction', event_id='event', attempt=1))
        try:
            with patch.object(fake.chat.completions, 'create', side_effect=invoke), patch.object(RequestPolicy.time, 'sleep'):
                RequestPolicy.completion(fake, metrics, phase='memory', model='deepseek-flash', messages=[{'role':'user','content':'exact'}])
        finally:
            R.operation.reset(op)
            R.active_archive.reset(token)
        usage = phase_usage(metrics, 'memory')
        self.assertIsNone(usage['tokens'])
        self.assertEqual(usage['known_recorded_tokens'], 7)
        self.assertEqual(usage['missing_failed_request_count'], 1)
        self.assertEqual(metrics['provider_requests'][0]['request_artifact'], metrics['provider_requests'][1]['request_artifact'])
        self.assertEqual(metrics['provider_requests'][1]['operation']['event_id'], 'event')

    def test_regeneration_phase_ledger_and_returned_cache_reasoning_usage(self):
        memory = Compaction(tokenizer=FakeTokenizer(), retain_percent=50)
        memory.write(MemoryEntry('raw '*100))
        fake = FakeOpenAIClient(['x'*300, 'short'])
        original = fake.chat.completions.create
        class Usage:
            total_tokens = 7
            prompt_tokens = 4
            completion_tokens = 3
            def model_dump(self, **kwargs):
                return dict(total_tokens=7, prompt_tokens=4, completion_tokens=3,
                    prompt_cache_hit_tokens=2, completion_tokens_details=dict(reasoning_tokens=1))
        def invoke(**kwargs):
            response = original(**kwargs)
            response.usage = Usage()
            return response
        archive, metrics = R.new_archive(), dict(memory_llm_calls=0, memory_tokens=0)
        token = R.active_archive.set(archive)
        from Diagnostics import collector
        metric_token = collector.set(metrics)
        try:
            with patch.object(API, 'client', fake), patch.object(fake.chat.completions, 'create', side_effect=invoke):
                event = memory.compact()
        finally:
            collector.reset(metric_token)
            R.active_archive.reset(token)
        self.assertEqual([a['status'] for a in event['attempts']], ['invalid', 'accepted'])
        self.assertEqual(phase_usage(metrics, 'memory')['tokens'], 14)
        requests = metrics['provider_requests']
        self.assertEqual([r['operation']['attempt'] for r in requests], [1, 2])
        self.assertEqual(requests[1]['usage_details']['prompt_cache_hit_tokens'], 2)
        self.assertEqual(requests[1]['usage_details']['completion_tokens_details']['reasoning_tokens'], 1)
        self.assertNotEqual(requests[0]['request_artifact'], requests[1]['request_artifact'])
        R.validate(dict(recording=archive, event=event))

    def test_context_candidates_keep_omitted_and_original_shortened_entries(self):
        for mode in ('sliding_window', 'summarization'):
            with self.subTest(mode=mode):
                module = MemoryFactory.create_memory_module(mode)
                if mode == 'summarization':
                    module.summary = 'summary text '*30
                else:
                    module.write(MemoryEntry('a'*100))
                    module.write(MemoryEntry('short'))
                archive = R.new_archive()
                d = dict(memory_state_artifact=R.freeze(module, archive))
                token = R.active_archive.set(archive)
                try:
                    with patch.object(Benchmark, 'client', FakeOpenAIClient('answer')):
                        Benchmark.direct_answer(module, 'question', d, memory_context_tokens=50, tokenizer=FakeTokenizer())
                finally:
                    R.active_archive.reset(token)
                context = R.get(archive, d['context_artifact'])
                candidates = R.get(archive, context['packing']['candidate_artifact'])['entries']
                if mode == 'summarization':
                    self.assertEqual(candidates[0]['text'], module.summary)
                    self.assertTrue(d['retrieved'][0]['metadata']['context_shortened'])
                    self.assertLess(len(context['supplied_context']), len(module.summary))
                else:
                    self.assertEqual([e['text'] for e in candidates], ['short', 'a'*100])
                    self.assertEqual(d['omitted_count'], 1)
                    self.assertEqual(context['supplied_context'], 'short')

    def test_cancelled_formation_checkpoint_retains_candidate_as_uncommitted(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='compaction'))
        snapshots = []
        job.set_persistence_callback(snapshots.append)
        def cancel_after_response(*args):
            job.cancel.set()
            return 'candidate before cancellation', 0, 7
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(compaction_module, 'call_api', side_effect=cancel_after_response), \
             patch.object(Benchmark, 'client', side_effect=AssertionError('no QA after cancellation')):
            job.run()
        saved = job.snapshot()
        self.assertEqual(saved['status'], 'cancelled')
        memory = saved['memories'][0]
        self.assertFalse(memory['formation_complete'])
        event = memory['memory']['compaction_events'][0]
        self.assertFalse(event['committed'])
        self.assertEqual(R.get(saved['recording'], event['attempts'][0]['candidate_artifact']), 'candidate before cancellation')
        self.assertTrue(any(s['memories'] for s in snapshots))
        R.validate(saved)

    def test_request_start_is_checkpointed_before_transport(self):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='sliding_window', question_limit=1))
        checkpoints = []
        job.set_persistence_callback(checkpoints.append)
        fake = FakeOpenAIClient('answer')
        original = fake.chat.completions.create
        def invoke(**kwargs):
            latest = checkpoints[-1]
            case = latest['cases'][0]
            request = case['diagnostics']['provider_requests'][-1]
            self.assertEqual(request['status'], 'started')
            self.assertEqual(request['context_artifact'], case['diagnostics']['context_artifact'])
            R.get(latest['recording'], request['request_artifact'], 'provider-request')
            return original(**kwargs)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Benchmark, 'client', fake), patch.object(fake.chat.completions, 'create', side_effect=invoke), \
             patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .1, 7)):
            job.run()
        self.assertEqual(job.result['status'], 'completed', job.result.get('error'))

    def test_cli_existing_output_is_preserved_without_provider_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'already.json'
            output.write_bytes(b'original result')
            with patch.object(sys, 'argv', ['Benchmark.py', '--dataset', 'unused.json', '--output', str(output)]), \
                 patch.object(Benchmark, 'call_api', side_effect=AssertionError('no provider')), \
                 patch.object(sys, 'stderr', io.StringIO()):
                with self.assertRaises(SystemExit) as stopped:
                    Benchmark.main()
            self.assertEqual(stopped.exception.code, 2)
            self.assertEqual(output.read_bytes(), b'original result')

    def test_portable_export_import_safe_json_inspection_and_run_owned_deletion(self):
        job = self.run_job()
        report = job.snapshot()
        # Exact raw text remains data even if it contains markup.
        hostile = R.put(job.result['recording'], 'diagnostic', '<script>alert(1)</script>')
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(app, 'RUN_STORE', directory), patch.object(app, 'RESULT_LIBRARY', Path(directory)/'library'), \
             patch.object(app, 'jobs', {report['run_id']: job}):
            app.persist_benchmark(job.snapshot())
            client = app.app.test_client()
            base = '/api/benchmarks/'+report['run_id']
            polling = client.get(base).json
            self.assertNotIn('artifacts', polling['recording'])
            exported = client.get(base+'/export')
            R.validate(exported.json)
            self.assertEqual(R.polling_view(exported.json), polling)
            inspected = client.get(base+'/artifacts/'+hostile['artifact_sha256'])
            self.assertEqual(inspected.mimetype, 'application/json')
            self.assertEqual(inspected.json['value'], '<script>alert(1)</script>')
            self.assertEqual(inspected.headers['X-Content-Type-Options'], 'nosniff')
            imported = client.post('/api/results/import', data={'file': (io.BytesIO(exported.data), 'portable.json')}, content_type='multipart/form-data')
            self.assertEqual(imported.status_code, 201, imported.json)
            portable = client.get('/api/results/file?path=portable.json&download=1')
            R.validate(portable.json)
            self.assertEqual(portable.json['recording'], exported.json['recording'])
            broken = deepcopy(exported.json)
            broken['recording']['artifacts'].clear()
            rejected = client.post('/api/results/import', data={'file': (io.BytesIO(json.dumps(broken).encode()), 'broken.json')}, content_type='multipart/form-data')
            self.assertEqual(rejected.status_code, 400)
            second = deepcopy(job.snapshot())
            second['run_id'] = 'independent-run'
            atomic_json(path_for(directory, second['run_id']), second)
            self.assertTrue(delete_run_files(directory, report['run_id']))
            R.validate(read_json(path_for(directory, second['run_id'])))
            self.assertTrue((Path(directory)/'library'/'portable.json').exists())
            portable.close()

    def test_persistence_callbacks_cannot_complete_out_of_order(self):
        job = self.run_job('sliding_window')
        entered, release, finished = threading.Event(), threading.Event(), threading.Event()
        written = []
        def persist(snapshot):
            if snapshot.get('sequence') == 1:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('test did not release write')
            written.append(snapshot.get('sequence'))
        job.set_persistence_callback(persist)
        first = threading.Thread(target=lambda: job.update(sequence=1))
        def second_write():
            job.update(sequence=2)
            finished.set()
        second = threading.Thread(target=second_write)
        first.start()
        try:
            self.assertTrue(entered.wait(5))
            second.start()
            self.assertFalse(finished.wait(.05))
        finally:
            release.set()
            first.join(5)
            if second.ident:
                second.join(5)
        self.assertEqual(written, [1, 2])

    def test_detached_worker_rehydrates_frozen_resume_state(self):
        previous = self.run_job('summarization').snapshot()
        previous['cases'][0]['correct'] = None
        resumed = Benchmark.BenchmarkJob.resume(dataset(), previous)
        with tempfile.TemporaryDirectory() as directory:
            run_id = resumed.result['run_id']
            atomic_json(path_for(directory, run_id, '.input.json'), dict(dataset=dataset(), snapshot=resumed.snapshot()))
            with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
                 patch.object(Summarization, 'call_api', side_effect=AssertionError('worker must reuse')), \
                 patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('answer already recorded')), \
                 patch.object(Benchmark, 'judge_answer', return_value=(json.loads(judgment(1)), .1, 7)):
                BenchmarkWorker.run_worker(directory, run_id)
            saved = read_json(path_for(directory, run_id))
            self.assertEqual(saved['status'], 'completed', saved.get('error'))
            self.assertEqual(saved['memories'][0]['ingestion']['construction_action'], 'frozen_reuse')
            self.assertEqual(saved['cases'][0]['diagnostics']['context_artifact'], previous['cases'][0]['diagnostics']['context_artifact'])
            R.validate(saved)

    def test_worker_rejects_changed_environment_before_any_provider_call(self):
        previous = self.run_job().snapshot()
        previous['code_identity']['source_sha256'] = 'changed-after-queueing'
        with tempfile.TemporaryDirectory() as directory:
            run_id = previous['run_id']
            atomic_json(path_for(directory, run_id, '.input.json'), dict(dataset=dataset(), snapshot=previous))
            with patch.object(Benchmark, 'call_api', side_effect=AssertionError('no provider')), \
                 patch.object(Benchmark, 'direct_answer', side_effect=AssertionError('no answering')):
                with self.assertRaisesRegex(ValueError, 'code_identity'):
                    BenchmarkWorker.run_worker(directory, run_id)
            saved = read_json(path_for(directory, run_id))
            self.assertEqual(saved['status'], 'failed')
            self.assertEqual(saved['cases'], previous['cases'])
            R.validate(saved)


if __name__ == '__main__':
    unittest.main()
