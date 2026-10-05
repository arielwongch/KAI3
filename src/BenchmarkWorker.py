"""Independent benchmark process; survives the web server exiting."""
import argparse
import threading
import time
from BenchmarkStore import Lease, atomic_json, path_for, read_json

class DiskCancel:
    def __init__(self, path):
        self.path = path
    def is_set(self):
        return self.path.exists()
    def wait(self, seconds):
        deadline = time.monotonic() + seconds
        while not self.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(.2, remaining))
        return True

def run_worker(root, run_id):
    lease = Lease(path_for(root, run_id, '.lease'))
    global_lease = None
    job = None
    try:
        from Benchmark import BenchmarkJob
        payload = read_json(path_for(root, run_id, '.input.json'))
        snapshot = payload['snapshot']
        job = BenchmarkJob(payload['dataset'], snapshot['config'])
        job.result = snapshot
        job.result['worker'] = dict(mode='detached')
        job.cancel = DiskCancel(path_for(root, run_id, '.cancel'))
        job.set_persistence_callback(lambda value: atomic_json(path_for(root, run_id), value))
        try:
            global_lease = Lease(path_for(root, 'worker-global', '.lease'))
        except OSError:
            job.update(status='failed', error='Another background benchmark is already running.')
            return
        def approved(token):
            try:
                return read_json(path_for(root, run_id, '.continue.json')).get('token') == token
            except (OSError, ValueError):
                return False
        job.review_waiter = approved
        job.run()
    except Exception as error:
        if job is not None:
            job.update(status='failed', error=str(error))
        raise
    finally:
        if global_lease:
            global_lease.close()
        lease.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--store', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    run_worker(args.store, args.run_id)
