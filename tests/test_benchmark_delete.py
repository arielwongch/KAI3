"""Saved-run deletion removes owned files and cannot race active execution."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
from BenchmarkStore import ACTIVE, Lease, atomic_json, path_for
from test_benchmark_lifecycle import data


class BenchmarkDeleteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('RUN_STORE', self.temp.name), ('jobs', {})]:
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = app.app.test_client()

    def saved(self, status='completed', worker=False):
        job = Benchmark.BenchmarkJob(data(), dict(module='question_only'))
        job.result.update(status=status, worker={'mode': 'detached'} if worker else None,
                          updated_at=time.time())
        run_id = job.result['run_id']
        atomic_json(path_for(self.root, run_id), job.snapshot())
        for suffix in ('.input.json', '.log', '.cancel', '.continue.json', '.lease'):
            path_for(self.root, run_id, suffix).write_text('synthetic run data', encoding='utf-8')
        job.set_persistence_callback(app.persist_benchmark)
        app.jobs[run_id] = job
        return job, run_id

    def test_delete_terminal_runs_removes_owned_files_and_registry(self):
        for status in ('completed', 'failed', 'cancelled', 'interrupted'):
            with self.subTest(status=status):
                job, run_id = self.saved(status)
                response = self.client.delete('/api/benchmarks/' + run_id)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {'deleted': run_id})
                self.assertNotIn(run_id, app.jobs)
                self.assertEqual(list(self.root.glob(run_id + '*')), [])
                self.assertEqual(self.client.get('/api/benchmarks/' + run_id).status_code, 404)
                self.assertIsNone(job._persistence_callback)
                job.persist()
                self.assertFalse(path_for(self.root, run_id).exists())
        app.restore_benchmarks()
        self.assertEqual(self.client.get('/api/benchmarks').json['runs'], [])

    def test_other_runs_exports_backups_and_global_lease_are_preserved(self):
        _, run_id = self.saved()
        _, other_id = self.saved()
        sentinels = [path_for(self.root, 'worker-global', '.lease'),
                     self.root / (run_id + '.json.backup'), self.root / 'exported-results.json']
        for path in sentinels:
            path.write_bytes(b'preserve')
        other = {p: p.read_bytes() for p in self.root.glob(other_id + '*')}
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 200)
        for path in sentinels:
            self.assertEqual(path.read_bytes(), b'preserve')
        for path, original in other.items():
            self.assertEqual(path.read_bytes(), original)

    def test_active_runs_and_recently_queued_workers_are_rejected(self):
        for status in ACTIVE:
            _, run_id = self.saved(status)
            before = {p: p.read_bytes() for p in self.root.glob(run_id + '*')}
            self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 409)
            self.assertFalse(next(r for r in self.client.get('/api/benchmarks').json['runs']
                                  if r['run_id'] == run_id)['deletable'])
            self.assertEqual(before, {p: p.read_bytes() for p in self.root.glob(run_id + '*')})
        _, run_id = self.saved('queued', worker=True)
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 409)

    def test_finishing_thread_cannot_recreate_a_deleted_snapshot(self):
        job, run_id = self.saved('queued')
        finishing, release = threading.Event(), threading.Event()
        def finish():
            job.update(status='completed')
            finishing.set()
            release.wait(5)
            job.persist()
        with patch.object(job, 'run', side_effect=finish):
            app.start_benchmark(job)
            try:
                self.assertTrue(finishing.wait(5))
                self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 409)
            finally:
                release.set()
                job._thread.join(5)
        self.assertFalse(job._thread.is_alive())
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 200)
        self.assertFalse(path_for(self.root, run_id).exists())

    def test_terminal_worker_with_held_lease_is_rejected_until_released(self):
        _, run_id = self.saved(worker=True)
        lease = Lease(path_for(self.root, run_id, '.lease'))
        try:
            self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 409)
            self.assertTrue(path_for(self.root, run_id, '.input.json').exists())
        finally:
            lease.close()
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 200)

    def test_unlink_failure_keeps_snapshot_and_run_for_retry(self):
        _, run_id = self.saved()
        unlink = Path.unlink
        def fail_log(path, *args, **kwargs):
            if path == path_for(self.root, run_id, '.log'):
                raise PermissionError('synthetic locked log')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_log):
            self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 503)
        self.assertIn(run_id, app.jobs)
        self.assertTrue(path_for(self.root, run_id).exists())
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 200)

    def test_directory_is_not_recursively_removed_and_no_files_are_deleted(self):
        _, run_id = self.saved()
        path_for(self.root, run_id, '.log').unlink()
        path_for(self.root, run_id, '.log').mkdir()
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 503)
        self.assertTrue(path_for(self.root, run_id, '.input.json').exists())
        self.assertTrue(path_for(self.root, run_id).exists())

    def test_unknown_invalid_and_already_deleted_runs(self):
        self.assertEqual(self.client.delete('/api/benchmarks/missing').status_code, 404)
        self.assertEqual(self.client.delete('/api/benchmarks/bad..id').status_code, 400)
        _, run_id = self.saved()
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 200)
        self.assertEqual(self.client.delete('/api/benchmarks/' + run_id).status_code, 404)
        for suffix in ('/cancel', '/continue', '/review', '/resume'):
            self.assertEqual(self.client.post('/api/benchmarks/' + run_id + suffix, json={}).status_code, 404)
        self.assertEqual(list(self.root.iterdir()), [])
