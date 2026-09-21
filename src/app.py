import re

from flask import Flask, jsonify, render_template, request

from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html')


@app.route('/get', methods=['POST'])
def get_reply():
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Message is required.'}), 400

    module_type = payload.get('memory_module', 'sliding_window')
    if module_type not in {'sliding_window', 'summarization'}:
        return jsonify({'error': 'Unknown memory module.'}), 400

    history = payload.get('history', [])
    memory = [
        f"{item.get('role', 'user').title()}: {item.get('content', '')}"
        for item in history[-10:]
        if isinstance(item, dict) and item.get('content')
    ]

    try:
        module = MemoryFactory.create_memory_module(module_type)
        result, latency, total_tokens = run_ReAct(message, memory=memory)
        final_answer = re.search(r'Final Answer:\s*(.*)', result, re.DOTALL)
        reply = final_answer.group(1).strip() if final_answer else result
        return jsonify({
            'reply': reply,
            'latency': round(latency, 2),
            'tokens': total_tokens,
            'memory_module': module.__class__.__name__,
        })
    except Exception as error:
        app.logger.exception('Chat request failed')
        return jsonify({'error': str(error)}), 503

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)