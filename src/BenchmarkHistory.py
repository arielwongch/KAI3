"""Small disk-backed history summaries and lazy, isolated report snapshots."""
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock, Thread

from BenchmarkConfig import PROTOCOL_VERSION
from BenchmarkStore import ACTIVE, atomic_json, path_for, read_json, worker_active, lease_held


def fingerprint(path):
    stat = Path(path).stat()
    return [stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size]


def summarize(snapshot):
    cases = snapshot.get('cases', [])
    config = snapshot.get('config', {})
    manifest = snapshot.get('question_manifest', [])
    if (not isinstance(config, dict) or not isinstance(cases, list)
            or not isinstance(manifest, list) or not isinstance(snapshot.get('status'), str)
            or not isinstance(snapshot.get('progress', {}), dict)
            or any(not isinstance(case, dict) or not isinstance(case.get('diagnostics', {}), dict)
                   for case in cases)):
        raise ValueError('Invalid benchmark snapshot fields.')
    modules = config.get('modules') or [None]
    if not isinstance(modules, list):
        raise ValueError('Benchmark modules must be a list.')
    return dict(run_id=snapshot['run_id'], status=snapshot['status'],
                progress=deepcopy(snapshot.get('progress', {})),
                module=modules[0], config=deepcopy(config), condition=snapshot.get('condition'),
                no_memory_context=snapshot.get('config', {}).get('no_memory_context'),
                protocol=snapshot.get('protocol'), updated_at=snapshot.get('updated_at'),
                background=bool(snapshot.get('worker')),
                resumable=snapshot.get('protocol_version') == PROTOCOL_VERSION and (
                    len(cases) < len(manifest) or any(
                        c.get('correct') is None and c.get('diagnostics', {}).get('status') != 'context_limit_exceeded'
                        for c in cases)))


def cache_summary(path, snapshot, signature=None):
    """An advisory cache: the snapshot remains authoritative if caching fails."""
    path = Path(path)
    try:
        atomic_json(path_for(path.parent, snapshot['run_id'], '.summary.json'),
                    dict(version=2, fingerprint=signature or fingerprint(path), summary=summarize(snapshot)))
    except (OSError, ValueError, KeyError, TypeError):
        pass


class DiskJob:
    """A restored job loads its full report only when a detail operation needs it."""
    def __init__(self, index, path, signature, summary):
        self.index, self.path, self.signature = index, path, signature
        self.summary = summary
        self.lock = RLock()
        self.cancel = Event()
        self.data = []
        self._persistence_callback = None
        self._result = None

    @property
    def result(self):
        with self.lock:
            if self._result is None:
                self._result = self.index.effective(self.index.read_snapshot(self.path))
            return self._result

    @result.setter
    def result(self, value):
        with self.lock:
            self._result = value

    @property
    def options(self):
        return self.result.get('config', {})

    def snapshot(self):
        with self.lock:
            return deepcopy(self.result)

    def set_persistence_callback(self, callback):
        self._persistence_callback = callback


class HistoryIndex:
    def __init__(self, root, jobs, lock, read_snapshot, persist, logger):
        self.root, self.jobs, self.lock = Path(root), jobs, lock
        self.read_snapshot, self.persist, self.logger = read_snapshot, persist, logger
        self.pending = set()
        self.failed = {}
        self.thread = None

    def effective(self, snapshot):
        if snapshot.get('status') in ACTIVE and not worker_active(self.root, snapshot):
            snapshot.update(status='interrupted', error=(
                'Background worker stopped. Resume the saved run to continue.' if snapshot.get('worker') else
                'The server restarted while this run was active. Partial results are available.'))
        return snapshot

    def _warn(self, path, error):
        self.logger.warning(
            'Skipping unreadable benchmark snapshot %s (%s). File left unchanged; '
            'restore a valid JSON backup or move it out of %s.', path.name, error, self.root)

    def _install(self, path, signature, snapshot):
        # Parsing happens without the registry lock. Recheck ownership and source
        # identity before publishing so deletion/writes cannot resurrect old data.
        with self.lock:
            if fingerprint(path) != signature:
                return False
            existing = self.jobs.get(snapshot['run_id'])
            if existing is not None and not isinstance(existing, DiskJob) and not existing.result.get('worker'):
                return True
            cache_summary(path, snapshot, signature)
            summary = summarize(self.effective(snapshot))
            self.jobs[snapshot['run_id']] = DiskJob(self, path, signature, summary)
            self.failed.pop(str(path), None)
            return True

    def _load(self, path, signature, warn):
        try:
            snapshot = self.read_snapshot(path)
            return self._install(path, signature, snapshot)
        except (OSError, ValueError, KeyError, TypeError) as error:
            if isinstance(error, OSError):
                # A locked/cloud-synced file or busy artifact database is not
                # corrupt. Never memoize temporary I/O failures as corruption.
                self.failed.pop(str(path), None)
                if warn:
                    self.logger.warning('Temporarily unable to read benchmark snapshot %s (%s). '
                                        'File left unchanged; retrying on the next request.', path.name, error)
                return False
            missing = False
            with self.lock:
                try:
                    if fingerprint(path) != signature:
                        return False
                except FileNotFoundError:
                    missing = True
                self.failed[str(path)] = signature
                existing = self.jobs.get(path.stem)
                if isinstance(existing, DiskJob):
                    del self.jobs[path.stem]
            if warn and not missing:
                self._warn(path, error)
            return True

    def _build(self, work):
        try:
            for path, signature in work:
                self._load(path, signature, True)
        finally:
            with self.lock:
                self.pending.difference_update(str(path) for path, _ in work)

    def refresh(self, background=False, force=False, warn=False, target_id=None):
        """Caller owns the registry lock; only cache misses parse full reports."""
        self.root.mkdir(parents=True, exist_ok=True)
        paths = {path.stem: path for path in self.root.glob('*.json')
                 if not path.name.endswith(('.input.json', '.continue.json', '.summary.json'))}
        if target_id is not None:
            # Directory enumeration can miss a Windows replacement in flight.
            # Detail requests probe their exact path instead of trusting a scan.
            target = path_for(self.root, target_id)
            try:
                target.stat()
                paths[target_id] = target
            except FileNotFoundError:
                pass
        for run_id, job in list(self.jobs.items()):
            if isinstance(job, DiskJob) and run_id not in paths:
                try:
                    job.path.stat()
                    paths[run_id] = job.path
                except FileNotFoundError:
                    if not lease_held(path_for(self.root, run_id, '.lease')):
                        del self.jobs[run_id]
                except OSError:
                    pass  # An unreadable file is not evidence of deletion.
        work = []
        for run_id, path in paths.items():
            if target_id is not None and run_id != target_id:
                continue
            existing = self.jobs.get(run_id)
            if existing is not None and not isinstance(existing, DiskJob) and not existing.result.get('worker'):
                continue
            try:
                signature = fingerprint(path)
                if not force and isinstance(existing, DiskJob) and existing.signature == signature:
                    # A worker can exit without changing its snapshot. Recheck its
                    # lease even when the source fingerprint is unchanged.
                    if existing.summary['status'] in ACTIVE and existing.summary['background']:
                        probe = dict(run_id=run_id, status=existing.summary['status'], worker=True,
                                     updated_at=existing.summary.get('updated_at') or 0)
                        if not worker_active(self.root, probe):
                            snapshot = self.effective(self.read_snapshot(path))
                            self.persist(snapshot)
                            self._install(path, fingerprint(path), snapshot)
                    continue
                if not force and self.failed.get(str(path)) == signature:
                    continue
                if not force:
                    try:
                        cache = read_json(path_for(self.root, run_id, '.summary.json'))
                        summary = cache['summary']
                        if (cache['version'] == 2 and cache['fingerprint'] == signature
                                and summary['run_id'] == run_id
                                and isinstance(summary.get('status'), str)
                                and isinstance(summary.get('background'), bool)):
                            status = summary['status']
                            if status in ACTIVE:
                                probe = dict(run_id=run_id, status=status, worker=summary['background'],
                                             updated_at=summary.get('updated_at') or 0)
                                if not worker_active(self.root, probe):
                                    summary['status'] = 'interrupted'
                            self.jobs[run_id] = DiskJob(self, path, signature, summary)
                            continue
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                if not background or str(path) not in self.pending:
                    if background and signature[2] <= 65536:
                        self._load(path, signature, True)
                    else:
                        work.append((path, signature))
            except (OSError, ValueError, KeyError, TypeError) as error:
                if warn:
                    self._warn(path, error)
        if background and work:
            self.pending.update(str(path) for path, _ in work)
            self.thread = Thread(target=self._build, args=(work,), daemon=True)
            self.thread.start()
        else:
            for path, signature in work:
                stable = self._load(path, signature, warn)
                if not stable and target_id is not None:
                    # Retry one changed checkpoint, without publishing a stale
                    # read or looping indefinitely behind a busy writer.
                    try:
                        self._load(path, fingerprint(path), warn)
                    except OSError:
                        pass

    def rows(self):
        rows = []
        for job in self.jobs.values():
            row = deepcopy(job.summary) if isinstance(job, DiskJob) else summarize(job.result)
            thread = getattr(job, '_thread', None)
            row['deletable'] = row['status'] not in ACTIVE and not (
                thread and getattr(thread, 'is_alive', lambda: False)())
            rows.append(row)
        return sorted(rows, key=lambda row: row.get('updated_at') or 0, reverse=True)

    def has_active(self):
        return any((job.summary if isinstance(job, DiskJob) else job.result)['status'] in ACTIVE
                   or (getattr(job, '_thread', None) is not None and
                       getattr(job._thread, 'is_alive', lambda: False)())
                   for job in self.jobs.values()) or lease_held(path_for(self.root, 'worker-global', '.lease'))
