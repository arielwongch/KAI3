"""Saved-run recovery must tolerate damaged local files without losing data."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

os.environ['DEEPSEEK_API_KEY'] = 'test-only'
os.environ['PYTHON_DOTENV_DISABLED'] = '1'
sys.path.insert(0, 'src')
import app


class SnapshotRestoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for name, value in (('RUN_STORE', directory.name), ('jobs', {})):
            patcher = patch.object(app, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_startup_skips_invalid_files_preserves_bytes_and_restores_valid_run(self):
        malformed = {
            'conflict.json': b'<<<<<<< HEAD\n{}\n=======\n{}\n>>>>>>> branch\n',
            'empty.json': b'',
            'array.json': b'[]',
            'missing-id.json': b'{"status":"completed"}',
            'mismatch.json': b'{"run_id":"different","status":"completed"}',
            'invalid-id.json': b'{"run_id":"../outside","status":"completed"}',
            'encoding.json': b'\xff',
        }
        for name, content in malformed.items():
            (self.root / name).write_bytes(content)
        saved = dict(run_id='valid-run', status='running', config={}, cases=[])
        (self.root / 'valid-run.json').write_text(json.dumps(saved), encoding='utf-8')
        # Control files and archived JSON must never be treated as run snapshots.
        for name in ('valid-run.input.json', 'valid-run.continue.json'):
            (self.root / name).write_text('not a snapshot', encoding='utf-8')
        recovery = self.root / 'recovery'
        recovery.mkdir()
        (recovery / 'archived.json').write_text('broken', encoding='utf-8')

        with self.assertLogs(app.app.logger, level='WARNING') as logs:
            app.restore_benchmarks()

        self.assertEqual(set(app.jobs), {'valid-run'})
        self.assertEqual(app.jobs['valid-run'].result['status'], 'interrupted')
        self.assertEqual(json.loads((self.root / 'valid-run.json').read_text())['status'], 'running')
        self.assertEqual(len(logs.records), len(malformed))
        for record in logs.records:
            self.assertIsNone(record.exc_info)
            self.assertIn('restore a valid JSON backup or move it out of', record.getMessage())
        for name, content in malformed.items():
            with self.subTest(filename=name):
                self.assertEqual((self.root / name).read_bytes(), content)
                self.assertTrue(any(name in line for line in logs.output))

        # Polling the library must tolerate the same files as startup.
        app.jobs.clear()
        app.refresh_jobs()
        self.assertEqual(set(app.jobs), {'valid-run'})
        for name, content in malformed.items():
            self.assertEqual((self.root / name).read_bytes(), content)

    def test_unreadable_file_warns_and_other_runs_load(self):
        (self.root / 'blocked.json').write_text('{}', encoding='utf-8')
        good = dict(run_id='good', status='completed', config={}, cases=[])
        (self.root / 'good.json').write_text(json.dumps(good), encoding='utf-8')
        read = app.read_json

        def read_with_permission_error(path):
            if Path(path).name == 'blocked.json':
                raise PermissionError('access denied')
            return read(path)

        with patch.object(app, 'read_json', side_effect=read_with_permission_error):
            with self.assertLogs(app.app.logger, level='WARNING') as logs:
                app.restore_benchmarks()
        self.assertEqual(set(app.jobs), {'good'})
        self.assertEqual(app.jobs['good'].result, good)
        self.assertIn('access denied', logs.output[0])
        self.assertEqual((self.root / 'blocked.json').read_text(), '{}')


if __name__ == '__main__':
    unittest.main()
