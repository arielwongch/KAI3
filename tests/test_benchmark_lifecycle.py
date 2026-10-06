import json
import os
from pathlib import Path
import sys
import subprocess
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0, 'src')
os.environ.setdefault('DEEPSEEK_API_KEY', 'test-only')
import app
import Benchmark
from benchmark_helpers import FakeTokenizer
from BenchmarkStore import ACTIVE, atomic_json, launch, path_for, read_json, worker_active, Lease
from test_binary_benchmark import judgment
from test_memory_integration import FakeOpenAIClient


def data():
    return [dict(sample_id='one', conversation={'session_1': [
        dict(speaker='Alice', text='I live in Rome.', dia_id='D1:1'),
        dict(speaker='Bob', text='Hello!', dia_id='D1:2')]},
        qa=[dict(question='Where?', answer='Rome', category=4)])]

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        token_patch = patch.object(Benchmark, "get_benchmark_tokenizer", return_value=FakeTokenizer())
        token_patch.start(); self.addCleanup(token_patch.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.store = patch.object(app, 'RUN_STORE', self.temp.name)
        self.store.start(); app.jobs.clear()
    def tearDown(self):
        app.jobs.clear(); self.store.stop(); self.temp.cleanup()

    def wait_status(self, job, status):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            if job.snapshot()['status']==status:
                return
            time.sleep(.01)
        self.fail(f'Never reached {status}: {job.snapshot()["status"]}')

    def test_review_prevents_answer_calls_and_progress_moves(self):
        job=Benchmark.BenchmarkJob(data(),dict(module='sliding_window',review_memory=True))
        app.jobs[job.result['run_id']]=job
        job.set_persistence_callback(app.persist_benchmark)
        fake=FakeOpenAIClient(['Rome',judgment(1)])
        with patch.object(Benchmark,'client',fake):
            thread=threading.Thread(target=job.run);thread.start()
            try:
                self.wait_status(job,'waiting_review')
                self.assertEqual(fake.calls,[])
                snap=job.snapshot()
                self.assertGreater(snap['progress']['percent'],0)
                self.assertEqual(snap['progress']['turn_completed'],2)
                self.assertEqual(len(snap['review']['memory']['entries']),2)
                client=app.app.test_client();url='/api/benchmarks/'+job.result['run_id']+'/continue'
                self.assertEqual(client.post(url,json={'token':'stale'}).status_code,409)
                self.assertEqual(client.post(url,json={'token':snap['review']['token']}).status_code,200)
            finally:
                job.review_continue.set();thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(job.result['status'],'completed')
        self.assertEqual(job.result['progress']['percent'],100)
        self.assertEqual(job.result['progress']['answered'],1)
        self.assertEqual(job.result['progress']['judged'],1)

    def test_full_context_review_and_cancel(self):
        job=Benchmark.BenchmarkJob(data(),dict(module='no_memory',review_memory=True))
        fake=FakeOpenAIClient()
        with patch.object(Benchmark,'client',fake):
            thread=threading.Thread(target=job.run);thread.start()
            try:
                self.wait_status(job,'waiting_review')
                self.assertTrue(job.result['review']['full_context'])
                self.assertIn('Alice',job.result['review']['memory']['entries'][0]['text'])
                self.assertEqual(fake.calls,[])
            finally:
                job.cancel.set();thread.join(5)
        self.assertEqual(job.result['status'],'cancelled')

    def test_disk_listing_and_dead_worker_recovery(self):
        job=Benchmark.BenchmarkJob(data(),dict(module='no_memory',background=True))
        snapshot=job.snapshot();snapshot.update(status='running',worker={'mode':'detached'},updated_at=0)
        atomic_json(path_for(self.temp.name,snapshot['run_id']),snapshot)
        client=app.app.test_client();runs=client.get('/api/benchmarks').json['runs']
        self.assertEqual(runs[0]['status'],'interrupted')
        self.assertEqual(runs[0]['run_id'],snapshot['run_id'])
        self.assertEqual(client.get('/api/benchmarks/'+snapshot['run_id']).json['status'],'interrupted')

    def test_live_worker_lease_keeps_review_after_server_restart(self):
        job=Benchmark.BenchmarkJob(data(),dict(module='no_memory',background=True))
        snapshot=job.snapshot();snapshot.update(status='waiting_review',worker={'mode':'detached'},review={'token':'token','memory':{}})
        atomic_json(path_for(self.temp.name,snapshot['run_id']),snapshot)
        lease=Lease(path_for(self.temp.name,snapshot['run_id'],'.lease'))
        try:
            self.assertTrue(worker_active(self.temp.name,snapshot))
            client=app.app.test_client();url='/api/benchmarks/'+snapshot['run_id']
            self.assertEqual(client.get(url).json['status'],'waiting_review')
            self.assertEqual(client.post(url+'/continue',json={'token':'token'}).status_code,200)
            self.assertEqual(read_json(path_for(self.temp.name,snapshot['run_id'],'.continue.json'))['token'],'token')
            self.assertEqual(client.post(url+'/cancel').status_code,200)
            self.assertTrue(path_for(self.temp.name,snapshot['run_id'],'.cancel').exists())
        finally:
            lease.close()

    def test_worker_survives_launcher_exit_at_review_gate(self):
        dataset = data()
        root = str(Path(self.temp.name).resolve())
        code = (
            "import sys,json;sys.path.insert(0,'src');"
            "from Benchmark import BenchmarkJob;from BenchmarkStore import launch;"
            "job=BenchmarkJob(json.loads(sys.argv[2]),dict(module='no_memory',background=True,review_memory=True));"
            "child=launch(sys.argv[1],job);print(job.result['run_id'],child.pid)"
        )
        parent = subprocess.run([sys.executable,'-c',code,root,json.dumps(dataset)],
                                cwd=str(Path(__file__).resolve().parents[1]), capture_output=True,text=True,timeout=15)
        self.assertEqual(parent.returncode,0,parent.stderr)
        run_id, pid = parent.stdout.strip().split()
        deadline = time.monotonic()+30
        try:
            while time.monotonic()<deadline:
                snapshot = read_json(path_for(root,run_id))
                if snapshot['status']=='waiting_review':
                    break
                if snapshot['status']=='failed':
                    self.fail(snapshot.get('error'))
                time.sleep(.1)
            else:
                self.fail('Detached worker did not reach review after parent exited.')
            self.assertTrue(worker_active(root,snapshot))
            # Server reconnects to a process launched by a parent that already exited.
            self.assertEqual(app.app.test_client().get('/api/benchmarks/'+run_id).json['status'],'waiting_review')
            self.assertEqual(snapshot['cases'],[])
            path_for(root,run_id,'.cancel').touch()
            deadline = time.monotonic()+10
            while time.monotonic()<deadline:
                snapshot=read_json(path_for(root,run_id))
                if snapshot['status']=='cancelled' and not worker_active(root,snapshot):
                    break
                time.sleep(.1)
            else:
                self.fail('Worker did not cancel.')
            if os.name == 'nt':
                import ctypes
                kernel = ctypes.WinDLL('kernel32', use_last_error=True)
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                handle = kernel.OpenProcess(0x00100000, False, int(pid))
                if handle:
                    try:
                        self.assertEqual(kernel.WaitForSingleObject(handle, 10000), 0)
                    finally:
                        kernel.CloseHandle(handle)
        finally:
            path_for(root,run_id,'.cancel').touch()
            if worker_active(root, read_json(path_for(root, run_id))):
                try:
                    os.kill(int(pid), signal.SIGTERM)
                except (OSError, ProcessLookupError):
                    pass

    def test_detached_worker_runs_without_model_calls(self):
        # A real child process evaluates an empty QA set: never submits a paid request.
        dataset=data();dataset[0]['qa']=[]
        job=Benchmark.BenchmarkJob(dataset,dict(module='no_memory',background=True))
        worker=launch(self.temp.name,job)
        try:
            worker.wait(timeout=30)
            self.assertEqual(worker.returncode,0, path_for(self.temp.name,job.result['run_id'],'.log').read_text())
            result=read_json(path_for(self.temp.name,job.result['run_id']))
            self.assertEqual(result['status'],'completed')
            self.assertEqual(result['cases'],[])
            self.assertFalse(worker_active(self.temp.name,result))
        finally:
            if worker.poll() is None:
                worker.terminate();worker.wait(timeout=5)

if __name__=='__main__':
    unittest.main()
