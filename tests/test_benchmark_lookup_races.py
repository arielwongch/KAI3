"""A live checkpoint/index race must never masquerade as deleted benchmark data."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import ExperimentRecording as recording
from BenchmarkStore import Lease, atomic_json, write_snapshot, path_for


class BenchmarkLookupRaceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (('RUN_STORE', directory.name), ('jobs', {}), ('_history_index', None)):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.run_id = 'race-run'
        self.path = path_for(self.root, self.run_id)
        self.snapshot = dict(run_id=self.run_id, status='running', worker={'mode': 'detached'},
            updated_at=time.time(), config={'modules': ['compaction']}, cases=[], question_manifest=[],
            progress={'completed': 1, 'total': 100})
        atomic_json(self.path, self.snapshot)
        self.lease = Lease(path_for(self.root, self.run_id, '.lease'))
        self.addCleanup(self.lease.close)
        self.index = app.history_index()
        self.client = app.app.test_client()

    def get(self):
        return self.client.get(f'/api/benchmarks/{self.run_id}?analysis=1')

    def test_repeated_replacement_during_indexing_returns_retryable_503_then_recovers(self):
        read = self.index.read_snapshot
        def replace_after_read(path):
            value = read(path)
            value['changing'] = value.get('changing', '') + 'x'
            atomic_json(path, value)
            return value
        self.index.read_snapshot = replace_after_read
        response = self.get()
        self.assertEqual(response.status_code, 503, response.json)
        self.assertEqual(response.json['code'], 'benchmark_temporarily_unavailable')
        self.assertTrue(response.json['retryable'])
        self.assertEqual(response.headers['Retry-After'], '2')
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertTrue(self.path.exists())
        self.index.read_snapshot = read
        response = self.get()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['run_id'], self.run_id)

    def test_one_replacement_is_retried_before_answering_detail(self):
        read = self.index.read_snapshot
        calls = []
        def replace_once(path):
            value = read(path)
            calls.append(path)
            if len(calls) == 1:
                newer = dict(value, progress={'completed': 2, 'total': 100})
                atomic_json(path, newer)
            return value
        self.index.read_snapshot = replace_once
        response = self.get()
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['progress']['completed'], 2)

    def test_permission_error_is_not_negative_cached_until_next_write(self):
        read = self.index.read_snapshot
        self.index.read_snapshot = lambda path: (_ for _ in ()).throw(PermissionError('OneDrive lock'))
        signature = self.path.stat().st_mtime_ns
        response = self.get()
        self.assertEqual(response.status_code, 503, response.json)
        self.assertNotIn(str(self.path), self.index.failed)
        self.index.read_snapshot = read
        self.assertEqual(self.path.stat().st_mtime_ns, signature)
        self.assertEqual(self.get().status_code, 200)

    def test_busy_sqlite_is_retryable_and_not_classified_as_corruption(self):
        snapshot = dict(self.snapshot, recording=recording.new_archive())
        recording.put(snapshot['recording'], 'diagnostic', 'data')
        write_snapshot(self.path, snapshot)
        with patch('BenchmarkStore.sqlite3.connect', side_effect=sqlite3.OperationalError('database is locked')):
            response = self.get()
        self.assertEqual(response.status_code, 503, response.json)
        self.assertNotIn(str(self.path), self.index.failed)
        self.assertEqual(self.get().status_code, 200)

    def test_directory_scan_omission_does_not_lose_existing_or_targeted_run(self):
        with patch.object(Path, 'glob', return_value=iter([])):
            self.assertEqual(self.get().status_code, 200)
        with patch.object(Path, 'glob', return_value=iter([])):
            response = self.client.get('/api/benchmarks')
        self.assertEqual([row['run_id'] for row in response.json['runs']], [self.run_id])

    def test_missing_live_manifest_keeps_registry_and_returns_retryable_status(self):
        self.assertEqual(self.get().status_code, 200)
        self.index.jobs[self.run_id]._result = None
        self.path.unlink()
        response = self.get()
        self.assertEqual(response.status_code, 503, response.json)
        self.assertIn(self.run_id, self.index.jobs)
        atomic_json(self.path, self.snapshot)
        self.assertEqual(self.get().status_code, 200)

    def test_real_missing_run_and_corrupt_checkpoint_have_distinct_errors(self):
        missing = self.client.get('/api/benchmarks/never-existed')
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json['code'], 'benchmark_not_found')
        self.assertFalse(missing.json['retryable'])
        self.path.write_text('{broken', encoding='utf-8')
        response = self.get()
        self.assertEqual(response.status_code, 409, response.json)
        self.assertEqual(response.json['code'], 'benchmark_snapshot_unreadable')
        self.assertFalse(response.json['retryable'])
        self.assertEqual(self.path.read_text(), '{broken')


if __name__ == '__main__':
    unittest.main()
