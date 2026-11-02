import os
import json
import re
from pathlib import Path
from copy import deepcopy
from threading import RLock, Thread
from uuid import uuid4
from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from MemoryFactory import MemoryFactory
from HybridMemory import HYBRIDS
from NoMemory import NoMemory
from MemoryConfig import window_size_for, retrieval_policy, RERANKED_MODULES
from MemoryContext import retrieval_k
from ReAct import run_ReAct
from Diagnostics import totals
from Benchmark import BenchmarkJob, MODULES, BENCHMARK_MODULES, MODULE_CAPABILITIES, PROTOCOL_VERSION
from BenchmarkStore import ACTIVE, atomic_json, path_for, read_json, launch, worker_active, delete_run_files
from ResultAnalysis import enrich_report

app = Flask(__name__, template_folder='.', static_folder=None)
# Keep the existing asset URLs without exposing the source/configuration directory.
PUBLIC_ASSETS = frozenset(('style.css', 'workspace.js', 'workspace-shell.js', 'compare.js', 'compare.css', 'assets/favicon.png'))

@app.get('/<path:filename>', endpoint='static')
def public_asset(filename):
    if filename not in PUBLIC_ASSETS:
        abort(404)
    return send_from_directory(app.root_path, filename)

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

def read_benchmark_snapshot(path):
    path = Path(path)
    snapshot = read_json(path)
    if not isinstance(snapshot, dict):
        raise ValueError('A benchmark snapshot must be a JSON object.')
    run_id = snapshot.get('run_id')
    if path_for(path.parent, run_id).name != path.name:
        raise ValueError('Snapshot run_id must match its filename.')
    return snapshot


def restore_benchmarks():
    for filename in os.listdir(RUN_STORE):
        if not filename.endswith('.json') or filename.endswith(('.input.json', '.continue.json')):
            continue
        try:
            snapshot = read_benchmark_snapshot(os.path.join(RUN_STORE, filename))
            job = BenchmarkJob.restore(snapshot)
            if worker_active(RUN_STORE, snapshot):
                job.result = snapshot
            jobs[job.result['run_id']] = job
        except (OSError, ValueError, KeyError, TypeError) as error:
            app.logger.warning(
                'Skipping unreadable benchmark snapshot %s (%s). File left unchanged; '
                'restore a valid JSON backup or move it out of %s.',
                filename, error, RUN_STORE)

def refresh_jobs():
    # Active in-process jobs are authoritative; disk is authoritative for detached workers.
    for filename in os.listdir(RUN_STORE):
        if not filename.endswith('.json') or filename.endswith(('.input.json', '.continue.json')):
            continue
        try:
            snapshot = read_benchmark_snapshot(os.path.join(RUN_STORE, filename))
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

def fail_benchmark(job, error):
    # The in-memory terminal state must survive even if saving it also fails.
    # Clearing worker makes it authoritative over any stale queued disk snapshot.
    job.set_persistence_callback(None)
    job.update(status='failed', worker=None, error=f'Benchmark execution failed: {error}')
    try:
        persist_benchmark(job.snapshot())
    except Exception:
        app.logger.exception('Could not persist failed benchmark %s', job.result['run_id'])


def run_benchmark_thread(job):
    try:
        job.run()
    except Exception as error:
        fail_benchmark(job, error)

def benchmark_stopped(job):
    thread = getattr(job, '_thread', None)
    return job.result['status'] not in ACTIVE and not (thread is not None and thread.is_alive())


def start_benchmark(job):
    try:
        job.set_persistence_callback(persist_benchmark)
        persist_benchmark(job.snapshot())
        atomic_json(path_for(RUN_STORE, job.result['run_id'], '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
        if job.options.get('background'):
            launch(RUN_STORE, job)
        else:
            job._thread = Thread(target=lambda: run_benchmark_thread(job), daemon=True)
            job._thread.start()
    except Exception as error:
        fail_benchmark(job, error)
        raise


restore_benchmarks()

class ChatSession:
    def __init__(self, mode, memory_options=None, window_size=None):
        self.mode = mode
        self.memory_options = deepcopy(memory_options or {})
        options = deepcopy(self.memory_options)
        self.window_size = window_size_for(mode, {} if window_size is None else {"window_size": window_size}, 10)
        if self.window_size is not None:
            options["max_items"] = self.window_size
        if 'max_summary_tokens' in options:
            from MemoryContext import get_benchmark_tokenizer
            options['tokenizer'] = get_benchmark_tokenizer()
        self.module = NoMemory() if mode == 'no_memory' else MemoryFactory.create_memory_module(mode, **options)
        self.lock = RLock()
        self.turns = []
    def snapshot(self, chat_id):
        with self.lock:
            return dict(schema_version=1, chat_id=chat_id, memory_module=self.mode,
                        memory_options=deepcopy(self.memory_options),
                        model="deepseek-flash", retrieval_k=retrieval_k(self.module), max_iterations=10,
                        window_size=self.window_size, retrieval_policy=retrieval_policy(self.mode, self.window_size),
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
result_library_lock = RLock()

@app.get('/compare')
def compare_page():
    return render_template('compare.html')


def result_display_name(name):
    """Keep original basenames; hide the prefix used by older uploads."""
    parts = name.split('/')
    if len(parts) == 2 and parts[0] == 'uploads':
        return re.sub(r'^[a-f0-9]{32}-', '', parts[-1])
    return parts[-1]


def valid_result_filename(name):
    """Accept a JSON basename, never a directory or Windows device name."""
    if not isinstance(name, str):
        return False
    try:
        size = len(name.encode('utf-8'))
    except UnicodeError:
        return False
    return (bool(name) and name.lower().endswith('.json') and size <= 200
            and not any(ord(char) < 32 or ord(char) == 127 or char in '/\\<>:"|?*' for char in name)
            and name.split('.')[0].rstrip(' .').upper() not in {'CON', 'PRN', 'AUX', 'NUL',
                *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))})


def result_location(name):
    """Resolve only canonical relative JSON paths inside the result folder.

    Reject traversal, absolute/drive paths, and linked files/directories (also
    Windows junctions). Every library read and mutation uses this boundary.
    """
    if (not isinstance(name, str) or not name or '\\' in name or ':' in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)):
        return None
    parts = name.split('/')
    if any(part in ('', '.', '..') for part in parts):
        return None
    try:
        if RESULT_LIBRARY.is_symlink() or RESULT_LIBRARY.is_junction():
            return None
        root = RESULT_LIBRARY.resolve()
        candidate = root
        for part in parts:
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                return None
        if candidate.resolve().is_relative_to(root) and candidate.suffix.lower() == '.json':
            return candidate
    except (OSError, ValueError):
        pass
    return None


def result_path(name):
    candidate = result_location(name)
    return candidate if candidate is not None and candidate.is_file() else None


def result_sort_key(name):
    return ([int(part) if part.isdigit() else part for part in re.split(r'(\d+)', result_display_name(name).casefold())], name.casefold())


def result_library_paths():
    if RESULT_LIBRARY.is_symlink() or RESULT_LIBRARY.is_junction():
        return []
    root = RESULT_LIBRARY.resolve()
    files = []
    if root.is_dir():
        # Do not traverse symlinks/junctions even when they point back inside.
        for directory, folders, names in os.walk(root, followlinks=False):
            folders[:] = [folder for folder in folders if not (Path(directory)/folder).is_symlink() and not (Path(directory)/folder).is_junction()]
            for name in names:
                relative = (Path(directory)/name).relative_to(root).as_posix()
                if result_path(relative) is not None:
                    files.append(relative)
    return sorted(files, key=result_sort_key)


def numbered_result_name(name, files):
    used = {result_display_name(path).casefold() for path in files}
    original = Path(name)
    index = 1
    while True:
        candidate = f'{original.stem} ({index}){original.suffix}'
        if candidate.casefold() not in used:
            return candidate
        index += 1


@app.post('/api/results/import')
def import_result():
    upload = request.files.get('file')
    if upload is None or not upload.filename or not upload.filename.lower().endswith('.json'):
        return jsonify(error='Choose a benchmark .json file.'), 400
    action = request.form.get('action', 'ask')
    if action not in ('ask', 'duplicate', 'replace'):
        return jsonify(error='Choose how to handle the duplicate upload.'), 400
    try:
        report = enrich_report(json.loads(upload.read().decode('utf-8-sig'),
                                          parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number.'))))
        name = upload.filename
        if not valid_result_filename(name):
            return jsonify(error='Use a .json filename without folders or reserved characters (maximum 200 UTF-8 bytes).'), 400
        # Decide names and write under one lock so simultaneous uploads cannot
        # silently claim the same display name or numbered suffix.
        with result_library_lock:
            files = result_library_paths()
            matches = [path for path in files if result_display_name(path).casefold() == name.casefold()]
            target = request.form.get('replace_path')
            if (action == 'ask' and matches) or (action == 'replace' and target not in matches):
                return jsonify(error='A file with this name already exists. Choose what to do.'
                               if action == 'ask' else 'The replacement target changed. Choose again.',
                               conflicts=matches, duplicate_name=numbered_result_name(name, files)), 409
            if action == 'replace':
                candidate = result_path(target)
                if candidate is None:
                    return jsonify(error='The replacement file is unavailable. Refresh the library.'), 404
                atomic_json(candidate, report)
                return jsonify(path=target, report=report, replaced=True), 200
            if action == 'duplicate':
                name = numbered_result_name(name, files)
                if not valid_result_filename(name):
                    return jsonify(error='Choose a shorter filename before keeping both copies.'), 400
            candidate = result_location(name)
            if candidate is None:
                return jsonify(error='The result filename is unavailable.'), 400
            if candidate.exists():
                return jsonify(error='The result filename is already in use.'), 409
            atomic_json(candidate, report)
            return jsonify(path=name, report=report), 201
    except (ValueError, TypeError, UnicodeError) as error:
        return jsonify(error=str(error)), 400
    except OSError:
        return jsonify(error='Could not save the result in the local repository.'), 503


@app.post('/api/results/enrich')
def enrich_result():
    payload = request.get_json(silent=True)
    name = payload.get('path') if isinstance(payload, dict) else None
    if not isinstance(name, str) or not name:
        return jsonify(error='Choose a result file.'), 400
    with result_library_lock:
        candidate = result_path(name)
        if candidate is None:
            return jsonify(error='Result file is unavailable.'), 404
        try:
            report = enrich_report(json.loads(candidate.read_text(encoding='utf-8-sig')))
            atomic_json(candidate, report)
            return jsonify(path=name, report=report)
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 400
        except OSError:
            return jsonify(error='Could not update the result file.'), 503

@app.get('/api/results')
def result_library():
    return jsonify(files=result_library_paths())

@app.get('/api/results/file')
def result_library_file():
    name = request.args.get('path', '')
    candidate = result_path(name)
    if candidate is None:
        return jsonify(error='Result file is unavailable.'), 404
    try:
        with candidate.open(encoding='utf-8-sig') as source:
            report = json.load(source)
        if not isinstance(report, dict) or not isinstance(report.get('cases'), list):
            return jsonify(error='This file is not a benchmark results export.'), 400
        if request.args.get('download') == '1':
            return send_file(candidate, as_attachment=True, download_name=result_display_name(name))
        return jsonify(report=enrich_report(report) if request.args.get('analysis') == '1' else report)
    except (OSError, ValueError):
        return jsonify(error='Could not read this results JSON file.'), 400


@app.post('/api/results/rename')
def rename_result():
    payload = request.get_json(silent=True)
    previous = payload.get('path') if isinstance(payload, dict) else None
    name = payload.get('name') if isinstance(payload, dict) else None
    if not valid_result_filename(name):
        return jsonify(error='Use a .json filename without folders or reserved characters (maximum 200 UTF-8 bytes).'), 400
    with result_library_lock:
        candidate = result_path(previous)
        if candidate is None:
            return jsonify(error='Result file is unavailable.'), 404
        relative = (candidate.parent / name).relative_to(RESULT_LIBRARY.resolve()).as_posix()
        destination = result_location(relative)
        if destination is None:
            return jsonify(error='The result filename is unavailable.'), 400
        conflicts = [path for path in result_library_paths() if result_display_name(path).casefold() == name.casefold() and result_path(path) != candidate]
        if conflicts or (destination.exists() and destination != candidate):
            return jsonify(error='A result with this filename already exists. Choose another name.'), 409
        try:
            if candidate.name != name:
                candidate.rename(destination)
            return jsonify(path=relative, previous_path=previous)
        except OSError:
            return jsonify(error='Could not rename this result file.'), 503


@app.delete('/api/results/file')
def delete_result():
    name = request.args.get('path', '')
    with result_library_lock:
        candidate = result_path(name)
        if candidate is None:
            return jsonify(error='Result file is unavailable.'), 404
        try:
            candidate.unlink()
            return jsonify(deleted=name)
        except OSError:
            return jsonify(error='Could not delete this result file.'), 503

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
    try:
        window_size = window_size_for(mode, payload, 10)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    memory_options = payload.get('memory_options', {})
    if mode in HYBRIDS:
        allowed = {'hybrid_shares', 'component_options', 'memory_context_tokens', 'retrieval_k',
                   'max_stored_entries', 'max_summary_tokens', 'summary_limit', 'candidate_k'}
    elif mode in RERANKED_MODULES:
        allowed = {'candidate_k', 'max_stored_entries'}
    elif mode == 'windowed_summarization':
        allowed = {'summary_limit', 'max_summary_tokens'}
    else:
        allowed = set()
    if not isinstance(memory_options, dict) or memory_options.keys() - allowed:
        return jsonify(error='memory_options must contain supported settings for the selected module.'), 400
    chat_id = chat_id.strip()
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
        if session is None:
            # Restored browser histories must not silently recreate lost memory.
            if payload.get('requires_existing'):
                return jsonify(error='Server memory is unavailable. Start a new chat.'), 410
            try:
                session = ChatSession(mode, memory_options, window_size)
            except (ValueError, TypeError) as error:
                return jsonify(error=str(error)), 400
            chat_memory_modules[chat_id] = session
    with session.lock:
        if session.mode != mode:
            return jsonify(error='The memory module cannot be changed during a chat.'), 409
        if 'window_size' in payload and session.window_size != window_size:
            return jsonify(error='The window size cannot be changed during a chat.'), 409
        if 'memory_options' in payload and session.memory_options != memory_options:
            return jsonify(error='Memory settings cannot be changed during a chat.'), 409
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
        try:
            start_benchmark(job)
        except Exception:
            return jsonify(run_id=job.result['run_id'], error=job.result['error']), 503
    return jsonify(run_id=job.result['run_id']), 202

@app.get('/api/benchmarks')
def list_benchmarks():
    with registry_lock:
        refresh_jobs()
        runs = [dict(run_id=j.result['run_id'], status=j.result['status'], progress=j.result.get('progress', {}), deletable=benchmark_stopped(j),
                     module=j.result.get('config', {}).get('modules', [None])[0], condition=j.result.get('condition'), no_memory_context=j.result.get('config', {}).get('no_memory_context'), protocol=j.result.get('protocol'), updated_at=j.result.get('updated_at'),
                     background=bool(j.result.get('worker')), resumable=j.result.get('protocol_version') == PROTOCOL_VERSION and (len(j.result.get('cases', [])) < len(j.result.get('question_manifest', [])) or any(c.get('correct') is None and c.get('diagnostics', {}).get('status') != 'context_limit_exceeded' for c in j.result.get('cases', [])))) for j in jobs.values()]
    return jsonify(runs=sorted(runs, key=lambda r: r.get('updated_at') or 0, reverse=True))

@app.delete('/api/benchmarks/<run_id>')
def delete_benchmark(run_id):
    try:
        path_for(RUN_STORE, run_id)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    with registry_lock:
        refresh_jobs()
        job = jobs.get(run_id)
        if job is None:
            return jsonify(error='Benchmark run is unavailable.'), 404
        with job.lock:
            if not benchmark_stopped(job):
                return jsonify(error='Cancel the run and wait until it stops before deleting it.'), 409
            try:
                if not delete_run_files(RUN_STORE, run_id):
                    return jsonify(error='The worker is still finishing. Wait a moment and retry deletion.'), 409
            except OSError:
                return jsonify(error='Could not remove all run files. The run remains listed; retry deletion.'), 503
            job.set_persistence_callback(None)
            del jobs[run_id]
    return jsonify(deleted=run_id)

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
            # Saved input is authoritative; the browser may currently show an
            # unrelated dataset. Uploads are a fallback for older/missing inputs.
            try:
                data = read_json(path_for(RUN_STORE, run_id, '.input.json'))['dataset']
            except (OSError, ValueError, KeyError, TypeError):
                data = previous.data
            if not data:
                data = payload.get('dataset')
            if data is None or data == []:
                return jsonify(code='dataset_required', error='The original dataset is unavailable. Upload it to resume this run.'), 409
            job = BenchmarkJob.resume(data, previous.snapshot())
        except (OSError, ValueError, TypeError, KeyError) as error:
            return jsonify(error=str(error)), 400
        jobs[run_id] = job
        try:
            start_benchmark(job)
        except Exception:
            return jsonify(run_id=run_id, error=job.result['error']), 503
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

def main():
    # The watchdog reloader restarts the process when OneDrive or an editor
    # touches a source file. Benchmark jobs run in-process, so reloads interrupt
    # them. Keep the server stable during long runs; opt into the debugger only.
    app.run(host=os.environ.get('HOST', '127.0.0.1'), port=int(os.environ.get('PORT', '5000')),
            debug=os.environ.get('KAI3_DEBUG') == '1', use_reloader=False)

if __name__ == '__main__':
    main()
