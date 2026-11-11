import os
import json
import re
from pathlib import Path
from copy import deepcopy
from threading import RLock, Thread
from uuid import uuid4
from weakref import WeakValueDictionary
from flask import Flask, abort, jsonify, render_template, request, send_file, send_from_directory
from MemoryFactory import MemoryFactory
from MemoryConfig import window_size_for, retrieval_policy, RERANKED_MODULES, HYBRIDS, MODULES
from MemoryContext import retrieval_k
from Diagnostics import totals
from BenchmarkConfig import BENCHMARK_MODULES, MODULE_CAPABILITIES, PROTOCOL_VERSION
from BenchmarkStore import ACTIVE, atomic_json, write_snapshot, path_for, read_json, launch, worker_active, delete_run_files, lease_held
from ResultAnalysis import enrich_report
from BenchmarkHistory import HistoryIndex, cache_summary
from ExperimentRecording import validate as validate_recording, polling_view, get as get_artifact
import ExperimentRecording as Recording

app = Flask(__name__, template_folder='.', static_folder=None)
# Keep the existing asset URLs without exposing the source/configuration directory.
PUBLIC_ASSETS = frozenset(('style.css', 'workspace.js', 'workspace-shell.js', 'loading.js', 'compare.js', 'compare.css', 'assets/favicon.png'))

@app.get('/<path:filename>', endpoint='static')
def public_asset(filename):
    if filename not in PUBLIC_ASSETS:
        abort(404)
    return send_from_directory(app.root_path, filename)

app.config['MAX_CONTENT_LENGTH'] = 32 * 1024 * 1024


@app.errorhandler(413)
def upload_too_large(error):
    return jsonify(code='upload_too_large', error=(
        'Upload exceeds the server request-size limit (32 MiB by default). '
        'For larger result exports, place the JSON file in data/result and refresh saved results.')), 413


AVAILABLE_MEMORY_MODULES = MODULES
chat_memory_modules = {}
registry_lock = RLock()
# Model/tokenizer initialization can be slow. Serialize creation per chat so
# unrelated chats and diagnostic requests never wait on the registry lock.
chat_initialization_locks = WeakValueDictionary()
jobs = {}
RUN_STORE = os.path.join(app.instance_path, 'benchmark_runs')
os.makedirs(RUN_STORE, exist_ok=True)

def persist_benchmark(snapshot):
    run_id = snapshot.get('run_id')
    if not isinstance(run_id, str) or not run_id.replace('-', '').isalnum():
        return
    path = path_for(RUN_STORE, run_id)
    write_snapshot(path, snapshot)
    cache_summary(path, snapshot)

def read_benchmark_snapshot(path):
    path = Path(path)
    snapshot = read_json(path)
    if not isinstance(snapshot, dict):
        raise ValueError('A benchmark snapshot must be a JSON object.')
    run_id = snapshot.get('run_id')
    if path_for(path.parent, run_id).name != path.name:
        raise ValueError('Snapshot run_id must match its filename.')
    return snapshot


_history_index = None


def history_index():
    global _history_index
    if (_history_index is None or _history_index.root != Path(RUN_STORE)
            or _history_index.jobs is not jobs):
        _history_index = HistoryIndex(RUN_STORE, jobs, registry_lock,
                                     read_benchmark_snapshot, persist_benchmark, app.logger)
    return _history_index


def restore_benchmarks():
    # Explicit recovery remains available to tools/tests. Normal startup does no
    # snapshot I/O; the history panel reconciles legacy reports on first access.
    with registry_lock:
        history_index().refresh(force=True, warn=True)


def refresh_jobs(run_id=None, background=False, force=False):
    with registry_lock:
        history_index().refresh(background=background, force=force, target_id=run_id)


def benchmark_lookup_error(run_id, error=None):
    """An absent index entry is not proof that a checkpoint was deleted."""
    try:
        path = path_for(RUN_STORE, run_id)
    except ValueError:
        response = jsonify(code='benchmark_not_found', error='Invalid benchmark run ID.', retryable=False)
        response.status_code = 404
    else:
        index = history_index()
        try:
            exists = path.exists()
            known = exists or str(path) in index.pending or lease_held(path_for(RUN_STORE, run_id, '.lease'))
        except OSError:
            exists, known = False, True
        unreadable = ((error is not None and not isinstance(error, OSError)) or
                      (exists and str(path) in index.failed))
        if unreadable:
            response = jsonify(code='benchmark_snapshot_unreadable', retryable=False,
                error='The saved checkpoint could not be read. Its files were left unchanged; inspect the server log or restore a valid backup.')
            response.status_code = 409
        elif known or error is not None:
            response = jsonify(code='benchmark_temporarily_unavailable', retryable=True,
                error='The saved checkpoint is temporarily unavailable or changing. Retrying will not restart the benchmark.')
            response.status_code = 503
            response.headers['Retry-After'] = '2'
        else:
            response = jsonify(code='benchmark_not_found', retryable=False,
                error='The saved run could not be found. Choose another saved run or New benchmark.')
            response.status_code = 404
        if error is not None:
            app.logger.warning('Could not load benchmark %s (%s): %s', run_id, response.status_code, error)
    response.headers['Cache-Control'] = 'no-store'
    return response


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
        write_snapshot(path_for(RUN_STORE, job.result['run_id'], '.input.json'), dict(dataset=job.data, snapshot=job.snapshot()))
        if job.options.get('background'):
            launch(RUN_STORE, job)
        else:
            job._thread = Thread(target=lambda: run_benchmark_thread(job), daemon=True)
            job._thread.start()
    except Exception as error:
        fail_benchmark(job, error)
        raise


def run_ReAct(*args, **kwargs):
    from ReAct import run_ReAct as run
    return run(*args, **kwargs)


class ChatSession:
    def __init__(self, mode, memory_options=None, window_size=None):
        self.mode = mode
        self.memory_options = deepcopy(memory_options or {})
        options = deepcopy(self.memory_options)
        self.window_size = window_size_for(mode, {} if window_size is None else {"window_size": window_size}, 10)
        if self.window_size is not None:
            options["max_items"] = self.window_size
        if 'max_summary_tokens' in options or mode == 'compaction':
            from MemoryContext import get_benchmark_tokenizer
            options['tokenizer'] = get_benchmark_tokenizer()
        self.module = MemoryFactory.create_memory_module(mode, **options)
        self.lock = RLock()
        self.turns = []
        self.requests = {}
        self.recording = Recording.new_archive()
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
                report = enrich_report(report, source_name=target)
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
            report = enrich_report(report, source_name=name)
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
            report = enrich_report(json.loads(candidate.read_text(encoding='utf-8-sig')), source_name=name)
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
            validate_recording(report)
            return send_file(candidate, as_attachment=True, download_name=result_display_name(name))
        return jsonify(report=enrich_report(report, source_name=name) if request.args.get('analysis') == '1' else report)
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
    request_id = payload.get('request_id')
    if request_id is not None and (not isinstance(request_id, str) or not request_id.strip() or len(request_id) > 200):
        return jsonify(error='request_id must be a nonblank string up to 200 characters.'), 400
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
    elif mode == 'compaction':
        from Compaction import OPTION_KEYS
        allowed = {*OPTION_KEYS, 'memory_context_tokens'}
    else:
        allowed = set()
    if not isinstance(memory_options, dict) or memory_options.keys() - allowed:
        return jsonify(error='memory_options must contain supported settings for the selected module.'), 400
    chat_id = chat_id.strip()
    with registry_lock:
        initialization_lock = chat_initialization_locks.setdefault(chat_id, RLock())
    with initialization_lock:
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
            with registry_lock:
                chat_memory_modules[chat_id] = session
    with session.lock:
        if session.mode != mode:
            return jsonify(error='The memory module cannot be changed during a chat.'), 409
        if 'window_size' in payload and session.window_size != window_size:
            return jsonify(error='The window size cannot be changed during a chat.'), 409
        if 'memory_options' in payload and session.memory_options != memory_options:
            return jsonify(error='Memory settings cannot be changed during a chat.'), 409
        if request_id in session.requests:
            saved = session.requests[request_id]
            if saved['message'] != message.strip():
                return jsonify(error='This request ID belongs to another message.'), 409
            return jsonify(deepcopy(saved['body'])), saved['status']
        pending = next((t for t in session.turns if t.get('pending_write')), None)
        if pending is not None:
            return jsonify(error='Retry the pending memory update before sending another message.',
                           code='memory_write_pending', turn_id=pending['turn_id']), 409
        d = {'turn_id': str(uuid4()), 'request_id': request_id}
        archive_token = Recording.active_archive.set(session.recording)
        try:
            result, latency, tokens = run_ReAct(message.strip(), memory_module=session.module, diagnostics=d)
            body = dict(reply=result, latency=round(latency, 2), tokens=tokens,
                        memory_module=session.module.__class__.__name__, turn_id=d['turn_id'],
                        memory_write_status=d.get('memory_write_status'), warning=d.get('warning'))
            status = 200
        except Exception as error:
            app.logger.exception('Chat request failed')
            body, status = dict(error=str(error), turn_id=d['turn_id']), 503
        finally:
            Recording.active_archive.reset(archive_token)
            session.turns.append(d)
        if request_id is not None:
            session.requests[request_id] = dict(message=message.strip(), body=deepcopy(body), status=status)
        return jsonify(body), status


@app.post('/api/chats/<chat_id>/turns/<turn_id>/retry-memory')
def retry_chat_memory(chat_id, turn_id):
    from Diagnostics import collector
    from MemoryEntry import MemoryEntry
    from ReAct import _write
    import time
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
    if session is None:
        return jsonify(error='Server memory is unavailable.'), 404
    with session.lock:
        turn = next((t for t in session.turns if t.get('turn_id') == turn_id), None)
        if turn is None:
            return jsonify(error='Chat turn is unavailable.'), 404
        if not turn.get('pending_write'):
            return jsonify(turn_id=turn_id, memory_write_status=turn.get('memory_write_status'))
        retry = dict(turn_id=str(uuid4()), operation='retry_memory', original_turn_id=turn_id,
                     agent_tokens=0, agent_llm_calls=0, agent_seconds=0., retrieval_seconds=0.,
                     memory_tokens=0, memory_llm_calls=0, write_seconds=0.)
        token = collector.set(retry)
        archive_token = Recording.active_archive.set(session.recording)
        started = time.perf_counter()
        try:
            _write(session.module, retry, MemoryEntry(**deepcopy(turn['pending_write'])))
        finally:
            retry['total_seconds'] = time.perf_counter() - started
            # The original turn owns the retry payload, not the operation record.
            retry.pop('pending_write', None)
            retry['status'] = 'completed' if retry.get('memory_write_status') == 'completed' else 'error'
            session.turns.append(retry)
            collector.reset(token)
            Recording.active_archive.reset(archive_token)
        turn['memory_write_status'] = retry['memory_write_status']
        if retry['status'] == 'completed':
            for key in ('pending_write', 'warning', 'memory_write_error'):
                turn.pop(key, None)
            for saved in session.requests.values():
                if saved['body'].get('turn_id') == turn_id:
                    saved['body'].update(memory_write_status='completed', warning=None)
        return jsonify(turn_id=turn_id, memory_write_status=turn['memory_write_status'],
                       warning=retry.get('warning'), error=retry.get('memory_write_error')), 200 if retry['status'] == 'completed' else 503

@app.get('/api/chats/<chat_id>')
@app.get('/api/chats/<chat_id>/diagnostics')
@app.get('/api/chats/<chat_id>/export')
def chat_diagnostics(chat_id):
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
    if session is None:
        return jsonify(error='Server memory is unavailable.'), 404
    with session.lock:
        snapshot = session.snapshot(chat_id)
        if request.path.endswith('/export'):
            if hasattr(session.module, 'audit_archive'):
                session.recording['artifacts'].update(deepcopy(session.module.audit_archive['artifacts']))
            snapshot['recording'] = deepcopy(session.recording)
            validate_recording(snapshot)
    response = jsonify(snapshot)
    if request.path.endswith('/export'):
        response.headers['Content-Disposition'] = 'attachment; filename="chat-diagnostics.json"'
    return response


@app.post('/api/chats/<chat_id>/compact')
def compact_chat(chat_id):
    from Compaction import Compaction
    from Diagnostics import collector
    import time
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.keys() - {'retain_percent'}:
        return jsonify(error='Expected an optional retain_percent in a JSON object.'), 400
    with registry_lock:
        session = chat_memory_modules.get(chat_id)
    if session is None:
        return jsonify(error='Server memory is unavailable.'), 404
    if not isinstance(session.module, Compaction):
        return jsonify(error='Manual compaction requires a Compaction chat.'), 400
    if 'retain_percent' in payload:
        from Compaction import validate_options
        try:
            validate_options(payload)
        except ValueError as error:
            return jsonify(error=str(error)), 400
    with session.lock:
        if any(t.get('pending_write') for t in session.turns):
            return jsonify(error='Retry the pending memory update before compacting.'), 409
        d = dict(turn_id=str(uuid4()), operation='manual_compaction', memory_llm_calls=0,
                 memory_tokens=0, memory_prompt_tokens=0, memory_completion_tokens=0,
                 agent_llm_calls=0, agent_tokens=0, retrieval_seconds=0, agent_seconds=0,
                 retrieved=[], status='running')
        token = collector.set(d)
        archive_token = Recording.active_archive.set(session.recording)
        started = time.perf_counter()
        try:
            event = session.module.compact(payload.get('retain_percent'))
            d['status'] = 'completed'
            return jsonify(event=event)
        except Exception as error:
            d.update(status='error', error=str(error))
            return jsonify(error=str(error)), 503
        finally:
            d['write_seconds'] = d['total_seconds'] = time.perf_counter() - started
            session.turns.append(d)
            collector.reset(token)
            Recording.active_archive.reset(archive_token)

@app.post('/api/benchmarks')
def create_benchmark():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Expected dataset and options.'), 400
    try:
        if not isinstance(payload.get('options', {}), dict):
            raise ValueError('Options must be an object.')
        from Benchmark import BenchmarkJob, MAX_QUESTION_WORKERS
        job = BenchmarkJob(payload.get('dataset'), {**payload.get('options', {}), 'question_workers': MAX_QUESTION_WORKERS})
    except (ValueError, TypeError) as error:
        return jsonify(error=str(error)), 400
    with registry_lock:
        refresh_jobs()
        if history_index().has_active():
            return jsonify(error='A benchmark is running or still finishing. Cancel it or wait for completion.'), 409
        jobs[job.result['run_id']] = job
        try:
            start_benchmark(job)
        except Exception:
            return jsonify(run_id=job.result['run_id'], error=job.result['error']), 503
    return jsonify(run_id=job.result['run_id']), 202

@app.get('/api/benchmarks')
def list_benchmarks():
    with registry_lock:
        refresh_jobs(background=True, force=request.args.get('refresh') == '1')
        index = history_index()
        runs, loading = index.rows(), bool(index.pending)
    return jsonify(runs=runs, loading=loading)


@app.delete('/api/benchmarks/<run_id>')
def delete_benchmark(run_id):
    try:
        path_for(RUN_STORE, run_id)
    except ValueError as error:
        return jsonify(error=str(error)), 400
    with registry_lock:
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
        if job is None:
            return benchmark_lookup_error(run_id)
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
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
        if job is None:
            return benchmark_lookup_error(run_id)
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
    try:
        with registry_lock:
            refresh_jobs(run_id=run_id)
            job = jobs.get(run_id)
        if job is None:
            return benchmark_lookup_error(run_id)
        if hasattr(job, 'lock') and hasattr(job, 'result'):
            with job.lock:
                snapshot = (job.snapshot() if request.path.endswith('/export') or (
                    request.args.get('analysis') == '1' and job.result.get('status') not in ACTIVE)
                    else polling_view(job.result))
        else:
            snapshot = job.snapshot()
    except (OSError, ValueError, KeyError, TypeError) as error:
        return benchmark_lookup_error(run_id, error)
    if request.args.get('analysis') == '1' and snapshot.get('status') not in ACTIVE:
        snapshot = enrich_report(snapshot)
    if request.path.endswith('/export'):
        try:
            validate_recording(snapshot)
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 409
    elif not (snapshot.get('recording') or {}).get('payloads_omitted'):
        snapshot = polling_view(snapshot)
    response = jsonify(snapshot)
    if request.path.endswith('/export'):
        response.headers['Content-Disposition'] = 'attachment; filename="locomo-results.json"'
    return response


@app.get('/api/benchmarks/<run_id>/artifacts/<identity>')
def benchmark_artifact(run_id, identity):
    if not re.fullmatch(r'[0-9a-f]{64}', identity):
        return jsonify(error='Invalid artifact identity.'), 400
    with registry_lock:
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
    if job is None:
        return benchmark_lookup_error(run_id)
    with job.lock:
        archive = job.result.get('recording')
        try:
            value = get_artifact(archive, {'artifact_sha256': identity})
            kind = archive['artifacts'][identity]['kind']
        except (ValueError, TypeError) as error:
            return jsonify(error=str(error)), 409
    # JSON data only; no HTML interpretation of archived conversation text.
    response = jsonify(artifact_sha256=identity, kind=kind, value=value)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response

@app.post('/api/benchmarks/<run_id>/resume')
def resume_benchmark(run_id):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error='Expected the original dataset.'), 400
    with registry_lock:
        refresh_jobs()
        refresh_jobs(run_id=run_id)
        previous = jobs.get(run_id)
        if previous is None:
            return benchmark_lookup_error(run_id)
        if history_index().has_active():
            return jsonify(error='A benchmark is running or still finishing. Wait until it stops.'), 409
        if not benchmark_stopped(previous):
            return jsonify(error='The previous worker is still finishing. Wait a moment and resume again.'), 409
        if previous.result.get('worker'):
            # A terminal snapshot can be written before the detached process
            # finishes its final checkpoints and releases ownership of the run.
            from BenchmarkStore import Lease
            try:
                lease = Lease(path_for(RUN_STORE, run_id, '.lease'))
            except OSError:
                return jsonify(error='The previous worker is still finishing. Wait a moment and resume again.'), 409
            lease.close()
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
            from Benchmark import BenchmarkJob, MAX_QUESTION_WORKERS
            job = BenchmarkJob.resume(data, previous.snapshot(), question_workers=MAX_QUESTION_WORKERS)
        except (OSError, ValueError, TypeError, KeyError) as error:
            return jsonify(error=str(error)), 400
        if payload.get('validate_only') is True:
            return jsonify(run_id=run_id, resumable=True, saved_cases=len(job.result['cases'])), 200
        jobs[run_id] = job
        try:
            start_benchmark(job)
        except Exception:
            return jsonify(run_id=run_id, error=job.result['error']), 503
    return jsonify(run_id=run_id), 202

@app.post('/api/benchmarks/<run_id>/cancel')
def cancel_benchmark(run_id):
    with registry_lock:
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
        if job is None:
            return benchmark_lookup_error(run_id)
        if job.result.get('worker'):
            path_for(RUN_STORE, run_id, '.cancel').touch()
        else:
            job.cancel.set()
        return jsonify(status='cancellation_requested')

@app.get('/api/benchmarks/<run_id>/review')
def benchmark_review_export(run_id):
    with registry_lock:
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
    if job is None:
        return benchmark_lookup_error(run_id)
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
        refresh_jobs(run_id=run_id)
        job = jobs.get(run_id)
        if job is None:
            return benchmark_lookup_error(run_id)
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
            debug=os.environ.get('KAI3_DEBUG') == '1', use_reloader=False, threaded=True)

if __name__ == '__main__':
    main()
