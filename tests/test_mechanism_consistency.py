"""Cross-entrypoint contracts: storage, ownership, registry, and error surfaces."""
import io
import json
import logging
import os
from pathlib import Path
import runpy
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
import BenchmarkStore as store
import ExperimentRecording as recording
from BenchmarkHistory import HistoryIndex
from BenchmarkConfig import BENCHMARK_MODULES, MODULE_CAPABILITIES
from MemoryConfig import MODULES
from MemoryFactory import MemoryFactory
from MemoryModule import MemoryModule
from benchmark_helpers import FakeTokenizer


def dataset():
    return [dict(sample_id='one', conversation={}, qa=[dict(question='Where?', answer='Rome', category=4)])]


class MechanismConsistencyTests(unittest.TestCase):
    def test_json_reader_handles_bom_and_rejects_nonfinite_numbers(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'data.json'
            path.write_text('{"value":"文件"}', encoding='utf-8-sig')
            self.assertEqual(store.read_json(path), {'value': '文件'})
            for value in ('NaN', 'Infinity', '-Infinity'):
                path.write_text('{"value":' + value + '}', encoding='utf-8')
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'Nonfinite'):
                    store.read_json(path)

    def test_cli_checkpoints_are_incremental_but_final_output_is_portable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'dataset.json', root / 'result.json'
            source.write_text(json.dumps(dataset()), encoding='utf-8')
            def run(job):
                job.update(status='running')
                checkpoint = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(checkpoint['recording']['layout'], 'sqlite-run-owned-sha256-v1')
                self.assertNotIn('artifacts', checkpoint['recording'])
                job.update(status='completed')
            with patch.object(sys, 'argv', ['Benchmark.py', '--dataset', str(source), '--output', str(output), '--modules', 'question_only']), \
                 patch.object(Benchmark.BenchmarkJob, 'run', run), \
                 patch.object(Benchmark, 'client', Mock()) as provider:
                Benchmark.main()
            portable = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(portable['recording']['layout'], 'inline-run-owned-sha256-v1')
            self.assertEqual(portable['config']['question_workers'], 8)
            recording.validate(portable)
            provider.chat.completions.create.assert_not_called()

    def test_cli_resume_and_offline_inspector_read_internal_checkpoints(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, checkpoint, output = root / 'dataset.json', root / 'internal.json', root / 'portable.json'
            source.write_text(json.dumps(dataset()), encoding='utf-8')
            job = Benchmark.BenchmarkJob(dataset(), {'module': 'question_only'})
            job.result['status'] = 'failed'
            store.write_snapshot(checkpoint, job.snapshot())
            inspected = io.StringIO()
            with patch.object(sys, 'argv', ['inspect_recording.py', str(checkpoint)]), patch('sys.stdout', inspected):
                runpy.run_path('tools/inspect_recording.py', run_name='__main__')
            self.assertTrue(json.loads(inspected.getvalue())['valid'])
            with patch.object(sys, 'argv', ['Benchmark.py', '--dataset', str(source), '--output', str(output),
                                          '--resume', str(checkpoint)]), \
                 patch.object(Benchmark.BenchmarkJob, 'run', lambda current: current.update(status='completed')):
                Benchmark.main()
            portable = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(portable['run_id'], job.result['run_id'])
            self.assertEqual(portable['config']['question_workers'], 8)
            recording.validate(portable)

    def test_finishing_thread_and_global_worker_lease_block_new_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            thread = Mock()
            thread.is_alive.return_value = True
            jobs = {'one': SimpleNamespace(result={'status': 'completed'}, _thread=thread)}
            index = HistoryIndex(directory, jobs, threading.RLock(), Mock(), Mock(), logging.getLogger(__name__))
            self.assertTrue(index.has_active())
            thread.is_alive.return_value = False
            self.assertFalse(index.has_active())
            lease = store.Lease(store.path_for(directory, 'worker-global', '.lease'))
            try:
                self.assertTrue(index.has_active())
            finally:
                lease.close()
            self.assertFalse(index.has_active())

    def test_upload_limit_is_a_json_error_without_creating_a_run(self):
        with patch.dict(app.app.config, {'MAX_CONTENT_LENGTH': 1024}), patch.object(app, 'jobs', {}):
            response = app.app.test_client().post('/api/benchmarks', data=' ' * 2048, content_type='application/json')
            self.assertEqual(response.status_code, 413)
            self.assertEqual(response.json['code'], 'upload_too_large')
            self.assertIn('data/result', response.json['error'])
            self.assertEqual(app.jobs, {})

    def test_public_create_uses_maximum_even_if_client_supplies_an_override(self):
        for override in (1, 3, 99):
            with self.subTest(override=override), tempfile.TemporaryDirectory() as directory, \
                 patch.object(app, 'RUN_STORE', directory), patch.object(app, 'jobs', {}), \
                 patch.object(app, '_history_index', None), patch.object(app, 'start_benchmark') as start:
                response = app.app.test_client().post('/api/benchmarks', json={
                    'dataset': dataset(), 'options': {'module': 'question_only', 'question_workers': override}})
                self.assertEqual(response.status_code, 202, response.json)
                self.assertEqual(start.call_args.args[0].options['question_workers'], 8)

    def test_public_resume_upgrades_legacy_worker_count_to_maximum(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(app, 'RUN_STORE', directory), \
             patch.object(app, 'jobs', {}), patch.object(app, '_history_index', None), \
             patch.object(app, 'start_benchmark') as start:
            previous = Benchmark.BenchmarkJob(dataset(), {'module': 'question_only', 'question_workers': 1})
            previous.result['status'] = 'failed'
            run_id = previous.result['run_id']
            store.write_snapshot(store.path_for(directory, run_id), previous.snapshot())
            store.write_snapshot(store.path_for(directory, run_id, '.input.json'),
                                 {'dataset': dataset(), 'snapshot': previous.snapshot()})
            response = app.app.test_client().post(f'/api/benchmarks/{run_id}/resume', json={'question_workers': 1})
            self.assertEqual(response.status_code, 202, response.json)
            self.assertEqual(start.call_args.args[0].options['question_workers'], 8)

    def test_memory_registry_factory_and_benchmark_capabilities_agree(self):
        self.assertEqual(set(BENCHMARK_MODULES), set(MODULES) - {'no_memory'} | {'question_only', 'full_context'})
        self.assertEqual(set(MODULE_CAPABILITIES), set(BENCHMARK_MODULES))
        for mode in MODULES:
            with self.subTest(mode=mode):
                memory = MemoryFactory.create_memory_module(mode, tokenizer=FakeTokenizer(),
                    embedder=Mock(), extractor=Mock(side_effect=AssertionError('construction must not call a provider')))
                self.assertIsInstance(memory, MemoryModule)
                for method in ('write', 'retrieve', 'inspect'):
                    self.assertTrue(callable(getattr(memory, method)))


if __name__ == '__main__':
    unittest.main()
