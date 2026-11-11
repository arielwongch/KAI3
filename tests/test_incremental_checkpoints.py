"""Durability and bounded-work regressions for incremental run checkpoints."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, 'src')
import BenchmarkStore as store
import ExperimentRecording as recording


class IncrementalCheckpointTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.path = self.root / 'run.json'
        self.report = dict(run_id='run', status='running', progress={'completed': 1},
                           cases=[], recording=recording.new_archive())
        self.reference = recording.put(self.report['recording'], 'diagnostic', 'large payload ' * 100000)

    def test_progress_writes_never_reserialize_existing_payloads_and_export_is_portable(self):
        store.write_snapshot(self.path, self.report)
        original = self.report['recording']['artifacts'][self.reference['artifact_sha256']]
        canonical = recording.canonical
        def reject_old(value):
            if value is original:
                raise AssertionError('Old payload was serialized again')
            return canonical(value)
        with patch.object(recording, 'canonical', side_effect=reject_old):
            self.report['progress']['completed'] = 2
            store.write_snapshot(self.path, self.report)
        self.assertLess(self.path.stat().st_size, 2048)
        restored = store.read_json(self.path)
        portable = json.loads(json.dumps(restored))
        self.assertEqual(portable, self.report)
        recording.validate(portable)
        self.assertEqual(recording.get(restored['recording'], self.reference), original['value'])

    def test_failed_manifest_commit_leaves_old_complete_checkpoint_readable(self):
        store.write_snapshot(self.path, self.report)
        previous = self.path.read_bytes()
        recording.put(self.report['recording'], 'diagnostic', 'paid answer saved as immutable object')
        with patch.object(store, 'atomic_json', side_effect=OSError('manifest write failed')):
            with self.assertRaises(OSError):
                store.write_snapshot(self.path, self.report)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(len(store.read_json(self.path)['recording']['artifacts']), 1)
        store.write_snapshot(self.path, self.report)
        self.assertEqual(len(store.read_json(self.path)['recording']['artifacts']), 2)

    def test_polling_and_checkpoint_copy_do_not_load_or_deepcopy_payloads(self):
        store.write_snapshot(self.path, self.report)
        restored = store.read_json(self.path)
        objects = restored['recording']['artifacts']
        objects.loader = Mock(side_effect=AssertionError('Polling loaded an audit payload'))
        poll = recording.polling_view(restored)
        checkpoint = recording.checkpoint_view(restored)
        self.assertNotIn('artifacts', poll['recording'])
        self.assertEqual(poll['recording']['artifact_count'], 1)
        objects.loader.assert_not_called()
        checkpoint['progress']['completed'] = 7
        self.assertEqual(restored['progress']['completed'], 1)

    def test_corrupt_or_missing_artifacts_are_rejected(self):
        store.write_snapshot(self.path, self.report)
        database = self.root / 'run.artifacts.sqlite3'
        with sqlite3.connect(database) as connection:
            connection.execute('UPDATE artifacts SET payload=?', (b'{"kind":"diagnostic","value":"changed"}',))
        # Close explicitly on Windows before the run-owned database is removed.
        connection.close()
        restored = store.read_json(self.path)
        with self.assertRaisesRegex(ValueError, 'Corrupt'):
            recording.validate(restored)
        database.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing run artifact database'):
            store.read_json(self.path)

    def test_input_snapshots_and_run_owned_deletion(self):
        store.write_snapshot(self.path, self.report)
        source = self.root / 'run.input.json'
        store.write_snapshot(source, dict(dataset=[{'sample_id': 'one'}], snapshot=self.report))
        restored = store.read_json(source)
        self.assertEqual(restored['snapshot'], self.report)
        self.assertTrue(store.delete_run_files(self.root, 'run'))
        self.assertFalse((self.root / 'run.artifacts.sqlite3').exists())
        self.assertFalse(source.exists())

    def test_incremental_archive_size_matches_full_serialization(self):
        archive = self.report['recording']
        metrics = recording.archive_metrics(archive)
        self.assertEqual(metrics['audit_archive_bytes'], len(recording.canonical(archive)))
        self.assertEqual(metrics['artifact_payload_bytes'], sum(len(recording.canonical(v)) for v in archive['artifacts'].values()))
        recording.put(archive, 'unicode', '文件')
        self.assertEqual(recording.archive_metrics(archive)['audit_archive_bytes'], len(recording.canonical(archive)))
        copied = deepcopy(archive)
        self.assertEqual(copied, archive)
        self.assertEqual(recording.archive_metrics(copied), recording.archive_metrics(archive))

    def test_slow_save_does_not_immediately_trigger_the_next_turn_save(self):
        os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
        from Benchmark import BenchmarkJob
        job = BenchmarkJob.restore(dict(run_id='run', status='failed', cases=[],
                                        progress={'total': 100, 'ingestion_total': 1000}))
        clock = [10.0]
        saved = []
        def save(value):
            saved.append(value)
            clock[0] += 2.0
        job.set_persistence_callback(save)
        with patch('Benchmark.time.monotonic', side_effect=lambda: clock[0]):
            job.live_progress(turn_completed=1)
            job.live_progress(turn_completed=2)
            self.assertEqual(len(saved), 1)
            job.live_progress(force=True)
            self.assertEqual(len(saved), 2)


if __name__ == '__main__':
    unittest.main()
