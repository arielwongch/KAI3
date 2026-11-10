"""Isolated benchmark layout fixture: real UI, synthetic read-only endpoints."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from flask import Flask, abort, jsonify, render_template, send_from_directory
from werkzeug.serving import make_server
from BenchmarkConfig import MODULES, BENCHMARK_MODULES, MODULE_CAPABILITIES

app = Flask(__name__, template_folder=str(ROOT / 'src'), static_folder=None)


@app.get('/benchmark')
def benchmark():
    html = render_template('index.html', memory_modules=MODULES,
        benchmark_modules=BENCHMARK_MODULES, module_capabilities=MODULE_CAPABILITIES)
    # Markdown is not part of this layout test; do not load external CDN scripts.
    html = html.replace('<script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>',
        '<script>window.marked={parse:s=>s};window.DOMPurify={sanitize:s=>s};</script>')
    return html.replace('<script src="https://cdn.jsdelivr.net/npm/dompurify@3.1.6/dist/purify.min.js"></script>', '')


@app.get('/api/benchmarks')
def runs():
    return jsonify(runs=[])


@app.get('/api/results')
def results():
    return jsonify(files=[])


@app.get('/api/benchmarks/dataset')
def dataset():
    return jsonify(filename='synthetic.json', dataset=[dict(sample_id='fixture', conversation={},
        qa=[dict(question='Where?', answer='Rome', category=4)])])


@app.get('/<path:filename>', endpoint='static')
def asset(filename):
    if filename not in {'style.css', 'workspace.js', 'workspace-shell.js', 'loading.js', 'assets/favicon.png'}:
        abort(404)
    return send_from_directory(ROOT / 'src', filename)


if __name__ == '__main__':
    server = make_server('127.0.0.1', 0, app)
    print(f'PREVIEW_PORT={server.server_port}', flush=True)
    server.serve_forever()
