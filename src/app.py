import os
import json
from pathlib import Path
from copy import deepcopy
from threading import RLock, Thread
from uuid import uuid4
from flask import Flask, jsonify, render_template, request
from MemoryFactory import MemoryFactory
from NoMemory import NoMemory
from ReAct import run_ReAct
from Diagnostics import totals
from Benchmark import BenchmarkJob, MODULES, BENCHMARK_MODULES, MODULE_CAPABILITIES, PROTOCOL_VERSION
from BenchmarkStore import ACTIVE, atomic_json, path_for, read_json, launch, worker_active

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
AVAILABLE_MEMORY_MODULES = MODULES
chat_memory_modules = {}
registry_lock = RLock()
jobs = {}
RUN_STORE = os.path.join(app.instance_path, 'benchmark_runs')
os.makedirs(RUN_STORE, exist_ok=True)

def persist_benchmark(snapshot):
    run_id = snapshot.get('run_id')
    if not isinstance(run_id, str) or not run_id.replace('-', '').isalnum():
        return
    atomic_json(path_for(RUN_STORE, run_id), snapshot)

def restore_benchmarks():
    for filename in os.listdir(RUN_STORE):
        if not filename.endswith('.json') or filename.endswith(('.input.json', '.continue.json')):
            continue
        try:
            with open(os.path.join(RUN_STORE, filename), encoding='utf-8') as source:
                snapshot = json.load(source)
            job = BenchmarkJob.restore(snapshot)
            if worker_active(RUN_STORE, snapshot):
                job.result = snapshot
            jobs[job.result['run_id']] = job
        except (OSError, ValueError, KeyError, TypeError):
            app.logger.exception('Could not restore saved benchmark run %s', filename)

def refresh_jobs():
    # Active in-process jobs are authoritative; disk is authoritative for detached workers.
    for filename in os.listdir(RUN_STORE):
        if not filename.endswith('.json') or filename.endswith(('.input.json', '.continue.json')):
            continue
        try:
            snapshot = read_json(os.path.join(RUN_STORE, filename))
            run_id = snapshot['run_id']
            existing = jobs.get(run_id)
            if existing is not None and not existing.result.get('worker'):
                continue
            if snapshot.get('worker') and snapshot.get('status') in ACTIVE and not worker_active(RUN_STORE, snapshot):
                snapshot.update(status='interrupted', error='Background worker stopped. Resume the saved run to continue.')
                persist_benchmark(snapshot)
            job = BenchmarkJob.restore(snapshot)
            job.result = snapshot
            jobs[run_id] = job
        except (OSError, ValueError, KeyError, TypeError):
            continue

def start_benchmark(job):
    job.set_persistence_callback(persist_benchmark)
    persist_benchmark(job.snapshot())
    atomic_json(path_for(RUN_STORE, job.result['run_id'], '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
    if job.options.get('background'):
        launch(RUN_STORE, job)
    else:
        Thread(target=job.run, daemon=True).start()


restore_benchmarks()

class ChatSession:
    def __init__(self, mode):
        self.mode = mode
        self.module = NoMemory() if mode == 'no_memory' else MemoryFactory.create_memory_module(mode)
        self.lock = RLock()
        self.turns = []
    def snapshot(self, chat_id):
        with self.lock:
            return dict(schema_version=1, chat_id=chat_id, memory_module=self.mode,
                        model="deepseek-flash", retrieval_k=5, max_iterations=10,
                        memory=self.module.inspect(), turns=deepcopy(self.turns), totals=totals(self.turns))

@app.get('/')
def home():
    return render_template('home.html')

@app.get('/chat')
def chat_page():
    return render_template('index.html', memory_modules=AVAILABLE_MEMORY_MODULES, benchmark_modules=BENCHMARK_MODULES, module_capabilities=MODULE_CAPABILITIES)

@app.get('/benchmark')
def benchmark_page():
    return render_template('index.html', memory_modules=AVAILABLE_MEMORY_MODULES, benchmark_modules=BENCHMARK_MODULES, module_capabilities=MODULE_CAPABILITIES)

RESULT_LIBRARY = Path(__file__).resolve().parents[1] / 'data' / 'result'

@app.get('/api/results')
def result_library():
    root = RESULT_LIBRARY.resolve()
    files = []
    if root.is_dir():
        for candidate in root.rglob('*.json'):
            resolved = candidate.resolve()
            if resolved.is_file() and resolved.is_relative_to(root):
                files.append(candidate.relative_to(root).as_posix())
    return jsonify(files=sorted(files, key=str.casefold))

@app.get('/api/results/file')
def result_library_file():
    name = request.args.get('path', '')
    root = RESULT_LIBRARY.resolve()
    candidate = (root / name).resolve()
    if not name or not candidate.is_relative_to(root) or candidate.suffix.lower() != '.json' or not candidate.is_file():
        return jsonify(error='Result file is unavailable.'), 404
    try:
        with candidate.open(encoding='utf-8-sig') as source:
            report = json.load(source)
        if not isinstance(report, dict) or not isinstance(report.get('cases'), list):
            return jsonify(error='This file is not a benchmark results export.'), 400
        return jsonify(report=report)
    except (OSError, ValueError):
        return jsonify(error='Could not read this results JSON file.'), 400

@app.get('/api/benchmarks/dataset')
def default_benchmark_dataset():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = (
        'data/lococo/lococmo10.json', 'data/lococo/locomo10.json',
        'data/locomo/lococmo10.json', 'data/locomo/locomo10.json',
    )
    for relative in candidates:
        path = os.path.join(root, relative)
        if os.path.isfile(path):
            with open(path, encoding='utf-8') as source:
                dataset = json.load(source)
            return jsonify(dataset=dataset, filename=relative)
    return jsonify(error='The bundled LoCoMo dataset was not found under data/. Upload a JSON file to continue.'), 404

@app.post('/get')
def get_reply():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Expected a JSON object.'), 400
    message = payload.get('message')
    chat_id = payload.get('chat_id')
    mode = payload.get('memory_module')
    if not isinstance(message, str) or not message.strip():
        return jsonify(error='Message is required.'), 400
    if not isinstance(chat_id, str) or not chat_id.strip() or len(chat_id) > 200:
        return jsonify(error='Valid chat ID is required.'), 400
    if mode not in AVAILABLE_MEMORY_MODULES:
        return jsonify(error='Choose a known memory module.'), 400
    chat_id = chat_id.strip()
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
        if session is None:
            # Restored browser histories must not silently recreate lost memory.
            if payload.get('requires_existing'):
                return jsonify(error='Server memory is unavailable. Start a new chat.'), 410
            session = ChatSession(mode)
            chat_memory_modules[chat_id] = session
    with session.lock:
        if session.mode != mode:
            return jsonify(error='The memory module cannot be changed during a chat.'), 409
        d = {'turn_id': str(uuid4())}
        try:
            result, latency, tokens = run_ReAct(message.strip(), memory_module=session.module, diagnostics=d)
            return jsonify(reply=result, latency=round(latency, 2), tokens=tokens,
                           memory_module=session.module.__class__.__name__, turn_id=d['turn_id'])
        except Exception as error:
            app.logger.exception('Chat request failed')
            return jsonify(error=str(error), turn_id=d['turn_id']), 503
        finally:
            session.turns.append(d)

@app.get('/api/chats/<chat_id>')
@app.get('/api/chats/<chat_id>/diagnostics')
@app.get('/api/chats/<chat_id>/export')
def chat_diagnostics(chat_id):
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
    if session is None:
        return jsonify(error='Server memory is unavailable.'), 404
    response = jsonify(session.snapshot(chat_id))
    if request.path.endswith('/export'):
        response.headers['Content-Disposition'] = 'attachment; filename="chat-diagnostics.json"'
    return response

@app.post('/api/benchmarks')
def create_benchmark():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Expected dataset and options.'), 400
    try:
        if not isinstance(payload.get('options', {}), dict):
            raise ValueError('Options must be an object.')
        job = BenchmarkJob(payload.get('dataset'), payload.get('options', {}))
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with registry_lock:
        refresh_jobs()
        if any(j.snapshot()['status'] in ACTIVE for j in jobs.values()):
            return jsonify(error='A benchmark is already running. Cancel it or wait for completion.'), 409
        jobs[job.result['run_id']] = job
    start_benchmark(job)
    return jsonify(run_id=job.result['run_id']), 202

@app.get('/api/benchmarks')
def list_benchmarks():
    with registry_lock:
        refresh_jobs()
        runs = [dict(run_id=j.result['run_id'], status=j.result['status'], progress=j.result.get('progress', {}),
                     module=j.result.get('config', {}).get('modules', [None])[0], condition=j.result.get('condition'), no_memory_context=j.result.get('config', {}).get('no_memory_context'), protocol=j.result.get('protocol'), updated_at=j.result.get('updated_at'),
                     background=bool(j.result.get('worker')), resumable=j.result.get('protocol_version') == PROTOCOL_VERSION and (len(j.result.get('cases', [])) < len(j.result.get('question_manifest', [])) or any(c.get('correct') is None and c.get('diagnostics', {}).get('status') != 'context_limit_exceeded' for c in j.result.get('cases', [])))) for j in jobs.values()]
    return jsonify(runs=sorted(runs, key=lambda r: r.get('updated_at') or 0, reverse=True))

@app.post('/api/benchmarks/<run_id>/continue')
def continue_benchmark(run_id):
    payload = request.get_json(silent=True) or {}
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
        if job is None:
            return jsonify(error='Benchmark run is unavailable.'), 404
        review = job.result.get('review') or {}
        if not isinstance(payload, dict) or job.result['status'] != 'waiting_review' or payload.get('token') != review.get('token'):
            return jsonify(error='This memory review is no longer pending. Refresh the run.'), 409
        if job.result.get('worker'):
            atomic_json(path_for(RUN_STORE, run_id, '.continue.json'), dict(token=review['token']))
        else:
            job.review_continue.set()
    return jsonify(status='continue_requested')

@app.get('/api/benchmarks/<run_id>')
@app.get('/api/benchmarks/<run_id>/export')
def benchmark_status(run_id):
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    response = jsonify(job.snapshot())
    if request.path.endswith('/export'):
        response.headers['Content-Disposition'] = 'attachment; filename="locomo-results.json"'
    return response

@app.post('/api/benchmarks/<run_id>/resume')
def resume_benchmark(run_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error='Expected the original dataset.'), 400
    with registry_lock:
        refresh_jobs()
        previous = jobs.get(run_id)
        if previous is None:
            return jsonify(error='Benchmark run is unavailable.'), 404
        refresh_jobs()
        if any(j.snapshot()['status'] in ACTIVE for j in jobs.values()):
            return jsonify(error='A benchmark is already running.'), 409
        try:
            data = payload.get('dataset') or previous.data
            if not data:
                data = read_json(path_for(RUN_STORE, run_id, '.input.json'))['dataset']
            job = BenchmarkJob.resume(data, previous.snapshot())
        except (OSError, ValueError, TypeError, KeyError) as error:
            return jsonify(error=str(error)), 400
        job.set_persistence_callback(persist_benchmark)
        jobs[run_id] = job
        persist_benchmark(job.snapshot())
    start_benchmark(job)
    return jsonify(run_id=run_id), 202

@app.post('/api/benchmarks/<run_id>/cancel')
def cancel_benchmark(run_id):
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    if job.result.get('worker'):
        path_for(RUN_STORE, run_id, '.cancel').touch()
    else:
        job.cancel.set()
    return jsonify(status='cancellation_requested')

@app.get('/api/benchmarks/<run_id>/review')
def benchmark_review_export(run_id):
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    data = job.snapshot()
    cases = [{'case_index': i, 'question': c.get('question'), 'category': c.get('category'),
              'reference': c.get('answer'), 'prediction': c.get('prediction'),
              'evidence': c.get('diagnostics', {}).get('retrieved', []),
              'judge': c.get('judge')} for i, c in enumerate(data['cases']) if c.get('prediction') is not None]
    response = jsonify(schema_version=1, run_id=run_id, rubric=['correctness','completeness','support','abstention'], cases=cases)
    response.headers['Content-Disposition'] = 'attachment; filename="locomo-review-sample.json"'
    return response

@app.post('/api/benchmarks/<run_id>/review')
def benchmark_review_import(run_id):
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    payload = request.get_json(silent=True)
    reviews = payload.get('reviews') if isinstance(payload, dict) else None
    if not isinstance(reviews, list):
        return jsonify(error='Expected a reviews array.'), 400
    if job.result['status'] in ACTIVE:
        return jsonify(error='Wait until the run stops before importing review labels.'), 409
    with job.lock:
        cases = job.result['cases']
        for review in reviews:
            if not isinstance(review, dict) or isinstance(review.get('case_index'), bool) or not isinstance(review.get('case_index'), int) or not 0 <= review['case_index'] < len(cases):
                return jsonify(error='Each review requires a valid case_index.'), 400
            ratings = review.get('ratings')
            if not isinstance(ratings, dict) or any(isinstance(ratings.get(k), bool) or ratings.get(k) not in (0,1,2) for k in ('correctness','completeness','support','abstention')):
                return jsonify(error='Each review requires 0–2 ratings for all four rubric dimensions.'), 400
        for review in reviews:
            cases[review['case_index']]['human_review'] = {'ratings': review['ratings'], 'notes': str(review.get('notes', ''))}
        agreement = {}
        dimensions = ('correctness','completeness','support','abstention')
        for dim in dimensions:
            pairs = [(c['judge'][dim], c['human_review']['ratings'][dim]) for c in cases if c.get('judge') and c.get('human_review')]
            agreement[dim] = {'exact_agreement': sum(a == b for a,b in pairs) / len(pairs) if pairs else None, 'count': len(pairs)}
        job.result['calibration'] = {'reviewed_count': sum(bool(c.get('human_review')) for c in cases), 'agreement': agreement, 'status': 'reviewed sample; agreement shown' if any(v['count'] for v in agreement.values()) else 'uncalibrated'}
    persist_benchmark(job.snapshot())
    return jsonify(calibration=job.snapshot().get('calibration'))

if __name__ == '__main__':
    # The watchdog reloader restarts the process when OneDrive or an editor
    # touches a source file. Benchmark jobs run in-process, so reloads interrupt
    # them. Keep the server stable during long runs; opt into the debugger only.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')),
            debug=os.environ.get('KAI3_DEBUG') == '1', use_reloader=False)
