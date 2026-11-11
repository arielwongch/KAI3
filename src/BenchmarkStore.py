"""Disk snapshots and detached worker controls (no credentials stored)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import sqlite3
from copy import deepcopy
from contextlib import closing
from uuid import uuid4

ACTIVE = ('queued', 'running', 'waiting_review')

def valid_id(run_id):
    return isinstance(run_id, str) and run_id and run_id.replace('-', '').isalnum()

def path_for(root, run_id, suffix='.json'):
    if not valid_id(run_id):
        raise ValueError('Invalid run ID.')
    return Path(root) / (run_id + suffix)


def _replace_snapshot(temporary, path):
    if os.name == 'nt':
        # MoveFileEx (used by os.replace) can reject an open destination even
        # when its reader shares delete access. ReplaceFile supports that case.
        import ctypes
        from ctypes import wintypes
        replace = ctypes.WinDLL('kernel32', use_last_error=True).ReplaceFileW
        replace.argtypes = (wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.DWORD, wintypes.LPVOID, wintypes.LPVOID)
        replace.restype = wintypes.BOOL
        if replace(os.path.abspath(path), os.path.abspath(temporary), None, 0, None, None):
            return
        error = ctypes.get_last_error()
        if error != 2:  # A new checkpoint has no destination yet.
            raise ctypes.WinError(error)
    temporary.replace(path)


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        # OneDrive/antivirus can hold a Windows file longer than half a second.
        # Keep the previous complete snapshot in place while retrying the rename.
        for attempt in range(12):
            try:
                _replace_snapshot(temporary, path)
                return
            except OSError as error:
                # ReplaceFileW can report ERROR_UNABLE_TO_REMOVE_REPLACED
                # (1175) as a plain OSError rather than PermissionError.
                # Retry known sharing/replacement locks, not arbitrary I/O errors.
                if not isinstance(error, PermissionError) and getattr(error, 'winerror', None) not in (5, 32, 33, 1175):
                    raise
                if attempt == 11:
                    raise
                time.sleep(min(.05 * 2 ** attempt, 1))
    finally:
        temporary.unlink(missing_ok=True)

def _snapshot_opener(path, flags):
    if os.name != 'nt':
        return os.open(path, flags)
    # Python's normal Windows open does not share delete access. A status poll
    # reading a large report would then block the worker's atomic replacement.
    import ctypes
    from ctypes import wintypes
    import msvcrt
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    create = kernel32.CreateFileW
    create.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
    create.restype = wintypes.HANDLE
    handle = create(os.fspath(path), 0x80000000, 0x1 | 0x2 | 0x4,
                    None, 3, 0x80, None)  # GENERIC_READ, SHARE_ALL, OPEN_EXISTING
    if handle == wintypes.HANDLE(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
    except BaseException:
        close = kernel32.CloseHandle
        close.argtypes = (wintypes.HANDLE,)
        close.restype = wintypes.BOOL
        close(handle)
        raise


def _reject_nonfinite(value):
    raise ValueError('Nonfinite JSON number: ' + value)


def read_json(path):
    # Windows can briefly hide/lock the destination during ReplaceFile. Retry
    # opening it, but never retry malformed JSON or return an incomplete report.
    for attempt in range(6):
        try:
            with open(path, encoding='utf-8-sig', opener=_snapshot_opener) as source:
                value = json.load(source, parse_constant=_reject_nonfinite)
            return _hydrate_snapshot(value, Path(path).parent)
        except (FileNotFoundError, PermissionError):
            if attempt == 5:
                raise
            time.sleep(min(.01 * 2 ** attempt, .1))


def _artifact_database(root, run_id):
    path = path_for(root, run_id, '.artifacts.sqlite3')
    if path.is_symlink():
        raise ValueError('Artifact database must be a run-owned regular file.')
    return path


def _artifact_read_error(error, database):
    code = getattr(error, 'sqlite_errorcode', 0) & 255
    transient = code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_CANTOPEN)
    if transient or 'database is locked' in str(error).lower() or 'database is busy' in str(error).lower():
        return OSError('Run artifact database is temporarily unavailable: ' + database.name)
    return ValueError('Unreadable run artifact database: ' + database.name)


def _hydrate_snapshot(value, root):
    if not isinstance(value, dict):
        return value
    if isinstance(value.get('snapshot'), dict):
        value['snapshot'] = _hydrate_snapshot(value['snapshot'], root)
    archive = value.get('recording')
    if not isinstance(archive, dict) or archive.get('layout') != 'sqlite-run-owned-sha256-v1':
        return value
    from ExperimentRecording import Artifacts
    database = _artifact_database(root, value.get('run_id'))
    if not database.is_file():
        raise ValueError('Missing run artifact database: ' + database.name)
    identities = archive.get('artifact_ids')
    if not isinstance(identities, list) or any(not isinstance(k, str) or len(k) != 64
            or any(c not in '0123456789abcdef' for c in k) for k in identities):
        raise ValueError('Invalid artifact index.')
    uri = database.resolve().as_uri() + '?mode=ro'
    try:
        with closing(sqlite3.connect(uri, uri=True)) as connection:
            sizes = dict(connection.execute('SELECT identity, size FROM artifacts'))
    except sqlite3.Error as error:
        raise _artifact_read_error(error, database) from error
    if any(key not in sizes for key in identities):
        raise ValueError('Run checkpoint references a missing artifact.')

    def load(identity):
        try:
            with closing(sqlite3.connect(uri, uri=True)) as connection:
                row = connection.execute('SELECT payload FROM artifacts WHERE identity=?', (identity,)).fetchone()
            if row is None:
                raise ValueError('Missing run artifact: ' + identity)
            return json.loads(row[0], parse_constant=_reject_nonfinite)
        except sqlite3.Error as error:
            raise _artifact_read_error(error, database) from error

    value['recording'] = dict(version=archive['version'], layout='inline-run-owned-sha256-v1',
        artifacts=Artifacts(dict.fromkeys(identities), sizes={key: sizes[key] for key in identities}, loader=load))
    return value


def write_snapshot(path, value):
    """Commit new immutable artifacts first, then atomically publish the index.

    A crash can leave unused objects, never a checkpoint pointing at uncommitted
    objects. read_json rehydrates the original portable archive lazily.
    """
    path = Path(path)
    report = value.get('snapshot', value) if isinstance(value, dict) else value
    archive = report.get('recording') if isinstance(report, dict) else None
    if not archive or 'artifacts' not in archive:
        return atomic_json(path, value)
    from ExperimentRecording import canonical
    import hashlib
    path.parent.mkdir(parents=True, exist_ok=True)
    database = _artifact_database(path.parent, report['run_id'])
    objects = archive['artifacts']
    try:
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute('PRAGMA synchronous=FULL')
            connection.execute('CREATE TABLE IF NOT EXISTS artifacts (identity TEXT PRIMARY KEY, payload BLOB NOT NULL, size INTEGER NOT NULL)')
            existing = {row[0] for row in connection.execute('SELECT identity FROM artifacts')}
            for identity in objects:
                if identity in existing:
                    continue
                payload = canonical(objects[identity])
                if hashlib.sha256(payload).hexdigest() != identity:
                    raise ValueError('Corrupt artifact: ' + identity)
                connection.execute('INSERT INTO artifacts VALUES (?, ?, ?)', (identity, payload, len(payload)))
    except sqlite3.Error as error:
        raise OSError('Could not save run artifacts: ' + str(error)) from error
    manifest = dict(version=archive['version'], layout='sqlite-run-owned-sha256-v1', artifact_ids=list(objects))
    compact = deepcopy(value, {id(archive): manifest})
    atomic_json(path, compact)

class Lease:
    def __init__(self, path):
        self.file = open(path, 'a+b')
        self.file.seek(0)
        if os.name == 'nt':
            import msvcrt
            if Path(path).stat().st_size == 0:
                self.file.write(b'0'); self.file.flush(); self.file.seek(0)
            try:
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.file.close(); raise
        else:
            import fcntl
            try:
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.file.close(); raise
    def close(self):
        if not self.file.closed:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0); msvcrt.locking(self.file.fileno(), msvcrt.LK_UNLCK, 1)
            self.file.close()

def lease_held(path):
    """Probe an existing lease without creating idle control files."""
    if not Path(path).exists():
        return False
    try:
        lease = Lease(path)
    except OSError:
        return True
    lease.close()
    return False


def worker_active(root, snapshot):
    if not snapshot.get('worker') or snapshot.get('status') not in ACTIVE:
        return False
    if lease_held(path_for(root, snapshot['run_id'], '.lease')):
        return True
    # Allow a newly spawned process time to import dependencies and acquire its lease.
    return snapshot['status'] == 'queued' and time.time() - snapshot.get('updated_at', 0) < 30

def delete_run_files(root, run_id):
    """Remove only this run's files; return False while its worker owns a lease."""
    paths = [path_for(root, run_id, suffix) for suffix in
             ('.input.json', '.log', '.cancel', '.continue.json', '.summary.json',
              '.artifacts.sqlite3-journal', '.artifacts.sqlite3', '.lease', '.json')]
    for path in paths:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise OSError('Run files must be regular files inside the run store.')
    lease_path = paths[-2]
    lease = None
    if lease_path.exists():
        try:
            lease = Lease(lease_path)
        except OSError:
            return False
    try:
        for path in paths[:-2]:
            path.unlink(missing_ok=True)
    finally:
        if lease is not None:
            lease.close()
    # Windows cannot unlink the lease while our own handle remains open.
    lease_path.unlink(missing_ok=True)
    paths[-1].unlink(missing_ok=True)
    return True

def launch(root, job):
    run_id = job.result['run_id']
    path_for(root, run_id, '.cancel').unlink(missing_ok=True)
    path_for(root, run_id, '.continue.json').unlink(missing_ok=True)
    write_snapshot(path_for(root, run_id, '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
    job.result['worker'] = dict(mode='detached')
    job.result['updated_at'] = time.time()
    snapshot = job.snapshot()
    path = path_for(root, run_id)
    write_snapshot(path, snapshot)
    from BenchmarkHistory import cache_summary
    cache_summary(path, snapshot)
    args = [sys.executable, str(Path(__file__).with_name('BenchmarkWorker.py')), '--store', str(Path(root).resolve()), '--run-id', run_id]
    options = dict(stdin=subprocess.DEVNULL, close_fds=True, cwd=str(Path(__file__).resolve().parents[1]))
    if os.name == 'nt':
        # A Windows venv executable redirects to the base Python interpreter.
        # DETACHED_PROCESS leaves that child free to allocate a visible console;
        # CREATE_NO_WINDOW gives both processes a windowless console instead.
        # Do not combine these flags: Windows ignores CREATE_NO_WINDOW then.
        options['creationflags'] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        startup = subprocess.STARTUPINFO(); startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW; startup.wShowWindow = subprocess.SW_HIDE
        options['startupinfo'] = startup
    else:
        options['start_new_session'] = True
    try:
        with open(path_for(root, run_id, '.log'), 'ab') as log:
            return subprocess.Popen(args, stdout=log, stderr=log, **options)
    except Exception as error:
        job.update(status='failed', error=f'Could not start background worker: {error}')
        raise
