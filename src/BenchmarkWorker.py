"""Independent benchmark process; survives the web server exiting."""
import argparse
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
        from Benchmark import BenchmarkJob, PROTOCOL_VERSION
        payload = read_json(path_for(root, run_id, '.input.json'))
        snapshot = payload['snapshot']
        from ExperimentRecording import validate, check_compatibility
        validate(snapshot)
        job = BenchmarkJob(payload['dataset'], snapshot['config'])
        execution_identity = job.result
        job.result = snapshot
        if snapshot.get('recording') is not None:
            job._frozen_cache = {str(m['sample_id']): m for m in
                [*snapshot.get('previous_ingestions', []), *snapshot.get('memories', [])]
                if m.get('formation_complete') and not m.get('error') and m.get('memory_state_artifact')}
        elif snapshot.get('config', {}).get('modules') == ['compaction']:
            job._compaction_cache = {str(m['sample_id']): m for m in
                [*snapshot.get('previous_ingestions', []), *snapshot.get('memories', [])]
                if not m.get('error') and m.get('compaction_artifact')}
        from BenchmarkHistory import cache_summary
        def persist(value):
            path = path_for(root, run_id)
            atomic_json(path, value)
            cache_summary(path, value)
        job.set_persistence_callback(persist)
        if snapshot.get('recording') is not None:
            check_compatibility(snapshot, execution_identity)
        job._resume_tokenizer = snapshot.get('tokenizer')
        if snapshot.get('protocol_version') != PROTOCOL_VERSION:
            job.update(status='failed', error='Legacy benchmark protocol cannot run in this worker. Start a new run.')
            return
        job.result['worker'] = dict(mode='detached')
        job.cancel = DiskCancel(path_for(root, run_id, '.cancel'))
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
