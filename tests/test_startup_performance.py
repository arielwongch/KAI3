"""Structural startup guarantees and history-cache lifecycle regressions."""
from concurrent.futures import ThreadPoolExecutor
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from threading import Event, RLock
import unittest
from unittest.mock import Mock

sys.path.insert(0, 'src')
from BenchmarkConfig import PROTOCOL_VERSION
from BenchmarkHistory import HistoryIndex, cache_summary
from BenchmarkStore import Lease, atomic_json, path_for, read_json
from ProviderClient import LazyClient


class StartupTests(unittest.TestCase):
    def test_real_entry_point_and_pages_do_no_history_or_heavy_imports(self):
        code = r'''
import builtins, json, pathlib, runpy, socket, sys, tempfile
sys.path.insert(0, 'src')
original_import = builtins.__import__
blocked = {'openai','nltk','scipy','sklearn','torch','transformers','sentence_transformers'}
def guarded(name, *args, **kwargs):
    assert name.split('.')[0] not in blocked, name
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded
def forbidden(*args, **kwargs):
    raise AssertionError('Unexpected history read or network request at page startup')
socket.socket.connect = forbidden
from flask import Flask
import BenchmarkStore
BenchmarkStore.read_json = forbidden
original_init = Flask.__init__
with tempfile.TemporaryDirectory() as root:
    store = pathlib.Path(root) / 'benchmark_runs'
    store.mkdir()
    report = store / 'large.json'
    report.write_text(json.dumps(dict(run_id='large', status='completed', cases=[], payload='x'*1000000)))
    before = report.read_bytes()
    def init(self, *args, **kwargs):
        kwargs['instance_path'] = root
        original_init(self, *args, **kwargs)
    Flask.__init__ = init
    def ready(self, *args, **kwargs):
        with self.test_client() as client:
            for route in ('/', '/chat', '/benchmark', '/compare'):
                assert client.get(route).status_code == 200, route
        assert not blocked.intersection(sys.modules)
    Flask.run = ready
    runpy.run_path('src/app.py', run_name='__main__')
    assert report.read_bytes() == before
    assert len(list(store.iterdir())) == 1
'''
        process = subprocess.run([sys.executable, '-X', 'utf8', '-c', code],
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_provider_initialization_is_shared_under_concurrent_first_use(self):
        service = object()
        factory = Mock(return_value=Mock(service=service))
        client = LazyClient(factory)
        self.assertEqual(factory.call_count, 0)
        with ThreadPoolExecutor(8) as pool:
            results = list(pool.map(lambda _: client.service, range(32)))
        self.assertTrue(all(result is service for result in results))
        factory.assert_called_once()

    def test_failed_provider_initialization_can_be_retried(self):
        client = LazyClient(Mock(side_effect=[ValueError('missing key'), Mock(service='ready')]))
        with self.assertRaises(ValueError):
            client.service
        self.assertEqual(client.service, 'ready')


class HistoryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.jobs = {}
        self.lock = RLock()
        self.read = Mock(side_effect=self.read_snapshot)
        self.index = HistoryIndex(self.root, self.jobs, self.lock, self.read,
                                  self.persist, logging.getLogger(__name__))

    def read_snapshot(self, path):
        snapshot = read_json(path)
        if not isinstance(snapshot, dict) or path_for(self.root, snapshot.get('run_id')) != Path(path):
            raise ValueError('Invalid snapshot identity')
        return snapshot

    def persist(self, snapshot):
        path = path_for(self.root, snapshot['run_id'])
        atomic_json(path, snapshot)
        cache_summary(path, snapshot)

    def save(self, run_id='one', cached=False, **kwargs):
        snapshot = dict(run_id=run_id, status='completed', config={'modules':['question_only']},
                        protocol_version=PROTOCOL_VERSION, question_manifest=[{}],
                        cases=[], updated_at=0, **kwargs)
        path = path_for(self.root, run_id)
        atomic_json(path, snapshot)
        if cached:
            cache_summary(path, snapshot)
        return snapshot

    def refresh(self, **kwargs):
        with self.lock:
            self.index.refresh(**kwargs)

    def test_cached_listing_never_reads_full_reports_and_detail_loads_once(self):
        snapshot = self.save(cached=True, payload='x'*100000)
        self.refresh()
        self.assertTrue(self.index.rows()[0]['resumable'])
        self.assertEqual(self.read.call_count, 0)
        job = self.jobs['one']
        with ThreadPoolExecutor(8) as pool:
            copies = list(pool.map(lambda _: job.snapshot(), range(16)))
        self.assertEqual(self.read.call_count, 1)
        copies[0]['cases'].append('changed')
        self.assertEqual(job.result['cases'], [])
        self.assertEqual(job.result, snapshot)
        self.refresh()
        self.assertEqual(self.read.call_count, 1)

    def test_listing_preserves_config_and_upgrades_older_summary_cache(self):
        snapshot = self.save()
        snapshot['config'].update(retrieval_k=20, candidate_k=None,
                                  component_options={'vector_store': {'retrieval_k': 7}})
        self.persist(snapshot)
        cache_path = path_for(self.root, 'one', '.summary.json')
        cache = read_json(cache_path)
        cache['version'] = 1
        cache['summary'].pop('config')
        atomic_json(cache_path, cache)
        self.refresh()
        self.assertEqual(self.read.call_count, 1)
        row = self.index.rows()[0]
        self.assertEqual(row['config'], snapshot['config'])
        row['config']['component_options']['vector_store']['retrieval_k'] = 99
        self.assertEqual(self.index.rows()[0]['config'], snapshot['config'])
        self.assertEqual(read_json(cache_path)['version'], 2)
        self.refresh()
        self.assertEqual(self.read.call_count, 1)

    def test_legacy_background_index_build_does_not_hold_registry_lock(self):
        self.save(payload='x'*100000)
        entered, release = Event(), Event()
        def slow(path):
            entered.set()
            self.assertTrue(release.wait(5))
            return self.read_snapshot(path)
        self.read.side_effect = slow
        try:
            self.refresh(background=True)
            self.assertTrue(entered.wait(5))
            self.assertTrue(self.index.pending)
            self.assertTrue(self.lock.acquire(timeout=1))
            self.lock.release()
        finally:
            release.set()
            self.index.thread.join(5)
        self.assertFalse(self.index.pending)
        self.assertIsNone(self.jobs['one']._result)
        self.assertTrue(path_for(self.root, 'one', '.summary.json').exists())

    def test_changes_deletion_and_forced_refresh_invalidate_cache(self):
        self.save(cached=True)
        self.refresh()
        self.save(payload='updated')
        self.refresh()
        self.assertEqual(self.read.call_count, 1)
        self.assertEqual(self.jobs['one'].result['payload'], 'updated')
        self.refresh(force=True)
        self.assertEqual(self.read.call_count, 3)
        path_for(self.root, 'one').unlink()
        self.refresh()
        self.assertEqual(self.jobs, {})

    def test_live_lease_and_exit_are_checked_without_snapshot_changes(self):
        snapshot = self.save(cached=True, worker={'mode':'detached'})
        snapshot['status'] = 'waiting_review'
        self.persist(snapshot)
        lease = Lease(path_for(self.root, 'one', '.lease'))
        try:
            self.refresh()
            self.assertEqual(self.index.rows()[0]['status'], 'waiting_review')
            self.assertEqual(self.read.call_count, 0)
        finally:
            lease.close()
        self.refresh()
        self.assertEqual(self.index.rows()[0]['status'], 'interrupted')
        self.assertEqual(read_json(path_for(self.root, 'one'))['status'], 'interrupted')

    def test_cached_inprocess_active_run_restores_as_interrupted(self):
        snapshot = self.save()
        snapshot['status'] = 'running'
        self.persist(snapshot)
        self.refresh()
        self.assertEqual(self.index.rows()[0]['status'], 'interrupted')
        self.assertEqual(self.jobs['one'].result['status'], 'interrupted')
        self.assertEqual(read_json(path_for(self.root, 'one'))['status'], 'running')

    def test_inprocess_job_is_authoritative_before_disk_read(self):
        snapshot = self.save()
        snapshot['status'] = 'running'
        self.jobs['one'] = Mock(result=snapshot)
        self.refresh(force=True)
        self.read.assert_not_called()
        self.assertTrue(self.index.has_active())

    def test_corrupt_summary_falls_back_to_source(self):
        self.save(cached=True)
        path_for(self.root, 'one', '.summary.json').write_text('{broken')
        self.refresh()
        self.read.assert_called_once()
        self.assertEqual(self.index.rows()[0]['status'], 'completed')

    def test_deleted_report_cannot_be_reinstalled_by_background_indexing(self):
        self.save(payload='x'*100000)
        entered, release = Event(), Event()
        def slow(path):
            snapshot = self.read_snapshot(path)
            entered.set()
            self.assertTrue(release.wait(5))
            return snapshot
        self.read.side_effect = slow
        try:
            self.refresh(background=True)
            self.assertTrue(entered.wait(5))
            with self.lock:
                path_for(self.root, 'one').unlink()
        finally:
            release.set()
            self.index.thread.join(5)
        self.assertEqual(self.jobs, {})
        self.assertFalse(path_for(self.root, 'one', '.summary.json').exists())

    def test_corrupt_changed_report_is_not_served_from_old_cache(self):
        self.save(cached=True)
        self.refresh()
        path_for(self.root, 'one').write_text('{broken')
        self.refresh()
        self.assertEqual(self.jobs, {})
        self.read.assert_called_once()
        # An unchanged corrupt file is not parsed repeatedly on every poll.
        self.refresh()
        self.read.assert_called_once()

    def test_detail_refresh_loads_only_requested_report(self):
        self.save('one', payload='x'*100000)
        self.save('two', payload='x'*100000)
        self.refresh(target_id='one')
        self.assertEqual(set(self.jobs), {'one'})
        self.read.assert_called_once_with(path_for(self.root, 'one'))

    def test_invalid_field_shapes_warn_without_blocking_other_reports(self):
        self.save('good')
        for run_id, fields in [('config', {'config':None}), ('cases', {'cases':[None]}),
                               ('progress', {'progress':[]})]:
            snapshot = self.save(run_id)
            snapshot.update(fields)
            atomic_json(path_for(self.root, run_id), snapshot)
        with self.assertLogs(__name__, level='WARNING') as logs:
            self.refresh(warn=True)
        self.assertEqual(set(self.jobs), {'good'})
        self.assertEqual(len(logs.records), 3)


if __name__ == '__main__':
    unittest.main()
