"""Disk snapshots and detached worker controls (no credentials stored)."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

ACTIVE = ('queued', 'running', 'waiting_review')

def valid_id(run_id):
    return isinstance(run_id, str) and run_id and run_id.replace('-', '').isalnum()

def path_for(root, run_id, suffix='.json'):
    if not valid_id(run_id):
        raise ValueError('Invalid run ID.')
    return Path(root) / (run_id + suffix)

def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + str(uuid4()) + '.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        for attempt in range(5):
            try:
                temporary.replace(path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(.05 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

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

def worker_active(root, snapshot):
    if not snapshot.get('worker') or snapshot.get('status') not in ACTIVE:
        return False
    path = path_for(root, snapshot['run_id'], '.lease')
    try:
        lease = Lease(path)
    except OSError:
        return True
    lease.close()
    # Allow a newly spawned process time to import dependencies and acquire its lease.
    return snapshot['status'] == 'queued' and time.time() - snapshot.get('updated_at', 0) < 30

def launch(root, job):
    run_id = job.result['run_id']
    path_for(root, run_id, '.cancel').unlink(missing_ok=True)
    path_for(root, run_id, '.continue.json').unlink(missing_ok=True)
    atomic_json(path_for(root, run_id, '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
    job.result['worker'] = dict(mode='detached')
    job.result['updated_at'] = time.time()
    atomic_json(path_for(root, run_id), job.snapshot())
    args = [sys.executable, str(Path(__file__).with_name('BenchmarkWorker.py')), '--store', str(Path(root).resolve()), '--run-id', run_id]
    options = dict(stdin=subprocess.DEVNULL, close_fds=True, cwd=str(Path(__file__).resolve().parents[1]))
    if os.name == 'nt':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
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
