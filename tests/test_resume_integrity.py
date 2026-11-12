"""Offline restart-to-completion checks for paid answers and frozen compaction."""
from copy import deepcopy
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
import BenchmarkWorker
import Compaction
import ExperimentRecording as recording
from AuditProvenance import digest
from BenchmarkStore import Lease, atomic_json, path_for, read_json
from benchmark_helpers import FakeTokenizer
from test_benchmark_recovery import ProviderError
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


def dataset():
    return [dict(sample_id='one', conversation={'session_1': [
        dict(speaker='Alice', dia_id='D1:1', text='I live in Rome. ' * 40)]},
        qa=[dict(question=f'Where {i}?', answer='Rome', category=4) for i in range(3)])]


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.target()
    def is_alive(self):
        return False


class ResumeIntegrityTests(unittest.TestCase):
    def failed_run(self, background=False):
        job = Benchmark.BenchmarkJob(dataset(), dict(module='compaction', question_limit=0,
                                                     background=background))
        fake = FakeOpenAIClient(['Rome', judgment(0), 'Rome'])
        create = fake.chat.completions.create
        def request(**kwargs):
            if len(fake.calls) == 3:
                raise ProviderError(402)
            return create(**kwargs)
        with patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
             patch.object(Compaction, 'call_api', return_value=('Rome.', 0, 7)), \
             patch.object(Benchmark, 'client', fake), \
             patch.object(fake.chat.completions, 'create', side_effect=request):
            job.run()
        previous = job.snapshot()
        self.assertEqual(previous['status'], 'failed', previous.get('error'))
        self.assertEqual(previous['cases'][0]['correct'], 0)
        self.assertEqual(previous['cases'][1]['prediction'], 'Rome')
        self.assertIsNone(previous['cases'][1]['correct'])
        return previous

    def test_disk_restart_resume_preserves_answers_and_frozen_memory_in_both_workers(self):
        for background in (False, True):
            with self.subTest(background=background), tempfile.TemporaryDirectory() as directory, \
                 patch.object(app, 'RUN_STORE', directory), patch.object(app, 'jobs', {}), \
                 patch.object(app, '_history_index', None):
                previous = self.failed_run(background)
                run_id = previous['run_id']
                atomic_json(path_for(directory, run_id), previous)
                atomic_json(path_for(directory, run_id, '.input.json'), dict(dataset=dataset(), snapshot=previous))
                # No browser dataset or in-memory job survives the simulated restart.
                fake = FakeOpenAIClient('Rome')
                create = fake.chat.completions.create
                def response(**kwargs):
                    value = create(**kwargs)
                    value.choices[0].message.content = judgment(1) if 'response_format' in kwargs else 'Rome'
                    return value
                def launch(root, job):
                    job.result['worker'] = dict(mode='detached')
                    atomic_json(path_for(root, run_id, '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
                    BenchmarkWorker.run_worker(root, run_id)
                with patch.object(app, 'Thread', ImmediateThread), patch.object(app, 'launch', side_effect=launch), \
                     patch.object(Benchmark, 'get_benchmark_tokenizer', return_value=FakeTokenizer()), \
                     patch.object(Benchmark, 'client', fake), \
                     patch.object(fake.chat.completions, 'create', side_effect=response), \
                     patch.object(Compaction, 'call_api', side_effect=AssertionError('must reuse frozen compaction')):
                    response = app.app.test_client().post(f'/api/benchmarks/{run_id}/resume', json={})
                    self.assertEqual(response.status_code, 202, response.json)
                    current = read_json(path_for(directory, run_id))
                    self.assertEqual(current['status'], 'completed', current.get('error'))
                    self.assertEqual(len(fake.calls), 3)  # judge saved prediction + answer/judge pending question
                    self.assertEqual(len(current['cases']), 3)
                    self.assertEqual(current['cases'][0], previous['cases'][0])
                    self.assertEqual(current['cases'][1]['diagnostics']['context_artifact'],
                                     previous['cases'][1]['diagnostics']['context_artifact'])
                    self.assertEqual(current['memories'][0]['ingestion']['construction_action'], 'frozen_reuse')
                    self.assertEqual(current['memories'][0]['ingestion']['memory_llm_calls'], 0)
                    recording.validate(current)
                    # Another resume of a fully judged run must make no paid calls.
                    response = app.app.test_client().post(f'/api/benchmarks/{run_id}/resume', json={})
                    self.assertEqual(response.status_code, 202, response.json)
                    self.assertEqual(len(fake.calls), 3)
                    self.assertEqual(read_json(path_for(directory, run_id))['resume_count'], 2)

    def test_terminal_detached_worker_must_release_lease_before_resume(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RUN_STORE', directory), \
             patch.object(app, 'jobs', {}), patch.object(app, '_history_index', None):
            previous = self.failed_run(True)
            previous['worker'] = dict(mode='detached')
            run_id = previous['run_id']
            atomic_json(path_for(directory, run_id), previous)
            lease = Lease(path_for(directory, run_id, '.lease'))
            try:
                with patch.object(Benchmark.BenchmarkJob, 'resume') as resume:
                    response = app.app.test_client().post(f'/api/benchmarks/{run_id}/resume', json={})
                self.assertEqual(response.status_code, 409, response.json)
                self.assertIn('still finishing', response.json['error'])
                resume.assert_not_called()
            finally:
                lease.close()

    def test_code_compatibility_allows_checkpoint_repairs_but_rejects_algorithm_changes(self):
        original = self.failed_run()
        for source, compatible in (('src/BenchmarkStore.py', True), ('src/Benchmark.py', False),
                                   ('src/Compaction.py', False)):
            previous = deepcopy(original)
            previous['code_identity']['source_files'][source] = 'older-version'
            previous['code_identity']['source_sha256'] = digest(previous['code_identity']['source_files'])
            with self.subTest(source=source):
                if compatible:
                    Benchmark.BenchmarkJob.resume(dataset(), previous)
                else:
                    with self.assertRaisesRegex(ValueError, 'code_identity'):
                        Benchmark.BenchmarkJob.resume(dataset(), previous)

    def test_audited_compaction_retry_repair_preserves_saved_work_and_provenance(self):
        original = self.failed_run()
        for source_hash in ('a4917866f7b34aa71a46bc950e865952bb9e675f9c7da3ee5ccd6136703ec59c',
                            '45b40b2412d0514983a9364aa1f012a385029510f471adb5b83345d601debdbd',
                            'b3d53abd2b8d5751b263d85118a13697d84d6ed6cd0a69fc2ba31515766b5234',
                            '081b437c33667986e0287977130e1d3b07fbe5ed58fe59edb78c3b3a13f930c6',
                            'beb160157b02bbb0a8437e2b461a8669a7afb735b52ee9a2f78f7ad576dc7968',
                            'c2c68668e43e1f284ef1fba9899d5bdea869713dfb855bc4bb5082d0cef50ff4'):
            previous = deepcopy(original)
            previous['code_identity']['source_files']['src/Compaction.py'] = source_hash
            previous['code_identity']['source_sha256'] = digest(previous['code_identity']['source_files'])
            resumed = Benchmark.BenchmarkJob.resume(dataset(), previous)
            self.assertEqual(resumed.result['cases'][0], previous['cases'][0])
            self.assertEqual(resumed._frozen_cache['one']['memory_state_artifact'],
                             previous['memories'][0]['memory_state_artifact'])
            self.assertEqual(resumed.result['previous_code_identities'][-1], previous['code_identity'])

    def test_terminal_thread_must_finish_before_resume(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RUN_STORE', directory), \
             patch.object(app, 'jobs', {}), patch.object(app, '_history_index', None):
            previous = self.failed_run()
            job = Benchmark.BenchmarkJob.restore(previous)
            job._thread = Mock()
            job._thread.is_alive.return_value = True
            app.jobs[previous['run_id']] = job
            with patch.object(Benchmark.BenchmarkJob, 'resume') as resume:
                response = app.app.test_client().post(f"/api/benchmarks/{previous['run_id']}/resume", json={})
            self.assertEqual(response.status_code, 409, response.json)
            resume.assert_not_called()

    def test_validate_only_checks_disk_resume_without_starting_or_overwriting_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RUN_STORE', directory), \
             patch.object(app, 'jobs', {}), patch.object(app, '_history_index', None):
            previous = self.failed_run()
            run_id = previous['run_id']
            snapshot = path_for(directory, run_id)
            atomic_json(snapshot, previous)
            atomic_json(path_for(directory, run_id, '.input.json'), dict(dataset=dataset(), snapshot=previous))
            before = snapshot.read_bytes()
            with patch.object(app, 'start_benchmark') as start:
                response = app.app.test_client().post(f'/api/benchmarks/{run_id}/resume', json={'validate_only': True})
            self.assertEqual(response.status_code, 200, response.json)
            self.assertTrue(response.json['resumable'])
            self.assertEqual(response.json['saved_cases'], 2)
            start.assert_not_called()
            self.assertEqual(snapshot.read_bytes(), before)
            self.assertEqual(app.jobs[run_id].result['status'], 'failed')


if __name__ == '__main__':
    unittest.main()
