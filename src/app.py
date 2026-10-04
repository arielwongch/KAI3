import os
from copy import deepcopy
from threading import RLock, Thread
from uuid import uuid4
from flask import Flask, jsonify, render_template, request
from MemoryFactory import MemoryFactory
from ReAct import run_ReAct
from Diagnostics import totals
from Benchmark import BenchmarkJob, MODULES

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')
app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024
AVAILABLE_MEMORY_MODULES = MODULES
chat_memory_modules = {}
registry_lock = RLock()
jobs = {}

class ChatSession:
    def __init__(self, mode):
        self.mode = mode
        self.module = MemoryFactory.create_memory_module(mode)
        self.lock = RLock()
        self.turns = []
    def snapshot(self, chat_id):
        with self.lock:
            return dict(schema_version=1, chat_id=chat_id, memory_module=self.mode,
                        model="deepseek-flash", retrieval_k=5, max_iterations=10,
                        memory=self.module.inspect(), turns=deepcopy(self.turns), totals=totals(self.turns))

@app.get('/')
def home():
    return render_template('index.html', memory_modules=AVAILABLE_MEMORY_MODULES)

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
        if any(j.snapshot()['status'] in ('queued', 'running') for j in jobs.values()):
            return jsonify(error='A benchmark is already running. Cancel it or wait for completion.'), 409
        jobs[job.result['run_id']] = job
    Thread(target=job.run, daemon=True).start()
    return jsonify(run_id=job.result['run_id']), 202

@app.get('/api/benchmarks/<run_id>')
@app.get('/api/benchmarks/<run_id>/export')
def benchmark_status(run_id):
    with registry_lock:
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    response = jsonify(job.snapshot())
    if request.path.endswith('/export'):
        response.headers['Content-Disposition'] = 'attachment; filename="locomo-results.json"'
    return response

@app.post('/api/benchmarks/<run_id>/cancel')
def cancel_benchmark(run_id):
    with registry_lock:
        job = jobs.get(run_id)
    if job is None:
        return jsonify(error='Benchmark run is unavailable.'), 404
    job.cancel.set()
    return jsonify(status='cancellation_requested')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '5000')), debug=True)
