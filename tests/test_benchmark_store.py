"""Checkpoint replacement must tolerate Windows polling and sync locks."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, 'src')
import BenchmarkStore as store


class BenchmarkStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'run.json'
        store.atomic_json(self.path, {'completed': 13})

    def test_sync_lock_lasting_more_than_old_retry_budget(self):
        replace = store._replace_snapshot
        attempts = []

        def locked(source, target):
            attempts.append(source)
            self.assertEqual(store.read_json(target), {'completed': 13})
            if len(attempts) <= 6:
                raise PermissionError('Windows sync lock')
            return replace(source, target)

        with patch.object(store, '_replace_snapshot', locked), patch.object(store.time, 'sleep') as sleep:
            store.atomic_json(self.path, {'completed': 14})
        self.assertEqual(store.read_json(self.path), {'completed': 14})
        self.assertEqual(sleep.call_count, 6)
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_permanent_failure_preserves_previous_checkpoint(self):
        with patch.object(store, '_replace_snapshot', side_effect=PermissionError('denied')), patch.object(store.time, 'sleep'):
            with self.assertRaises(PermissionError):
                store.atomic_json(self.path, {'completed': 14})
        self.assertEqual(store.read_json(self.path), {'completed': 13})
        self.assertEqual(list(self.path.parent.glob('*.tmp')), [])

    def test_winerror_1175_retries_plain_oserror_without_losing_previous_snapshot(self):
        replace = store._replace_snapshot
        attempts = []
        def locked(source, target):
            attempts.append(source)
            if len(attempts) < 4:
                self.assertEqual(store.read_json(target), {'completed': 13})
                error = OSError('Unable to remove the file to be replaced.')
                error.winerror = 1175
                raise error
            return replace(source, target)
        with patch.object(store, '_replace_snapshot', locked), patch.object(store.time, 'sleep') as sleep:
            store.atomic_json(self.path, {'completed': 14})
        self.assertEqual(sleep.call_count, 3)
        self.assertEqual(store.read_json(self.path), {'completed': 14})

    def test_persistent_1175_is_bounded_and_unrelated_io_error_is_not_retried(self):
        error = OSError('Unable to remove the file to be replaced.')
        error.winerror = 1175
        with patch.object(store, '_replace_snapshot', side_effect=error) as replace, patch.object(store.time, 'sleep'):
            with self.assertRaises(OSError):
                store.atomic_json(self.path, {'completed': 14})
            self.assertEqual(replace.call_count, 12)
        self.assertEqual(store.read_json(self.path), {'completed': 13})
        with patch.object(store, '_replace_snapshot', side_effect=OSError('disk full')) as replace, patch.object(store.time, 'sleep') as sleep:
            with self.assertRaises(OSError):
                store.atomic_json(self.path, {'completed': 14})
            replace.assert_called_once()
            sleep.assert_not_called()

    @unittest.skipUnless(os.name == 'nt', 'Windows handle sharing regression')
    def test_poll_reader_allows_replacement_while_open(self):
        with open(self.path, encoding='utf-8', opener=store._snapshot_opener) as reader:
            store.atomic_json(self.path, {'completed': 14, 'text': '文件'})
            self.assertEqual(json.load(reader), {'completed': 13})
            self.assertEqual(store.read_json(self.path), {'completed': 14, 'text': '文件'})

    def test_reader_retries_temporary_replacement_gap_and_lock(self):
        opener = store._snapshot_opener
        failures = [FileNotFoundError('rename in progress'), PermissionError('locked')]

        def transient(path, flags):
            if failures:
                raise failures.pop(0)
            return opener(path, flags)

        with patch.object(store, '_snapshot_opener', transient), patch.object(store.time, 'sleep') as sleep:
            self.assertEqual(store.read_json(self.path), {'completed': 13})
        self.assertEqual(sleep.call_count, 2)


if __name__ == '__main__':
    unittest.main()
