r"""Measure the real app entry point without opening a port or calling a provider.

Run with the environment to measure:
    .\venv\Scripts\python.exe tools/profile_startup.py --repeat 3
    .\venv\Scripts\python.exe tools/profile_startup.py --empty-store
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

PROBE = r'''
import sys, time, runpy, json, os
t0 = time.perf_counter()
sys.path.insert(0, 'src')
from flask import Flask
import BenchmarkStore
reads = {'count': 0, 'seconds': 0.0}
original_read = BenchmarkStore.read_json
def read(path):
    started = time.perf_counter()
    try:
        reads['count'] += 1
        return original_read(path)
    finally:
        reads['seconds'] += time.perf_counter() - started
BenchmarkStore.read_json = read
original_init = Flask.__init__
def init(self, *args, **kwargs):
    if os.environ.get('KAI3_PROFILE_STORE'):
        kwargs['instance_path'] = os.environ['KAI3_PROFILE_STORE']
    original_init(self, *args, **kwargs)
Flask.__init__ = init
def ready(self, *args, **kwargs):
    result = dict(ready_seconds=time.perf_counter()-t0, instance_path=self.instance_path,
                  snapshot_reads=dict(reads))
    started = time.perf_counter()
    with self.test_client() as client:
        response = client.get('/')
    result.update(home_status=response.status_code, home_seconds=time.perf_counter()-started,
                  heavy_modules=[name for name in ('openai', 'nltk', 'scipy', 'sklearn',
                      'torch', 'transformers', 'sentence_transformers') if name in sys.modules])
    print(json.dumps(result), flush=True)
Flask.run = ready
runpy.run_path('src/app.py', run_name='__main__')
'''


def main():
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repeat', type=int, default=3)
    parser.add_argument('--timeout', type=float, default=30)
    parser.add_argument('--empty-store', action='store_true')
    args = parser.parse_args()
    if args.repeat < 1 or args.timeout <= 0:
        parser.error('repeat and timeout must be positive')
    with tempfile.TemporaryDirectory() as empty:
        env = os.environ.copy()
        if args.empty_store:
            env['KAI3_PROFILE_STORE'] = empty
        for attempt in range(args.repeat):
            started = time.perf_counter()
            process = subprocess.run([sys.executable, '-X', 'utf8', '-c', PROBE],
                cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True,
                text=True, encoding='utf-8', timeout=args.timeout, check=True)
            result = json.loads(process.stdout)
            result.update(attempt=attempt+1, process_seconds=time.perf_counter()-started)
            print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
