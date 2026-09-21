import re

from flask import Flask, jsonify, render_template, request

from MemoryFactory import MemoryFactory
from ReAct import run_ReAct

app = Flask(__name__, template_folder='.', static_folder='.', static_url_path='')

AVAILABLE_MEMORY_MODULES = ['sliding_window', 'summarization']
chat_memory_modules = {}

@app.route('/', methods=['GET'])
def home():
    return render_template('index.html', memory_modules=AVAILABLE_MEMORY_MODULES)


@app.route('/get', methods=['POST'])
def get_reply():
    payload = request.get_json(silent=True) or {}
    message = payload.get('message', '').strip()
    if not message:
        return jsonify({'error': 'Message is required.'}), 400

    chat_id = payload.get('chat_id', '').strip()
    module_type = payload.get('memory_module', '')
    if not chat_id or not module_type:
        return jsonify({'error': 'Choose a memory module before sending a message.'}), 400
    if module_type not in AVAILABLE_MEMORY_MODULES:
        return jsonify({'error': 'Unknown memory module.'}), 400

    try:
        chat_memory = chat_memory_modules.get(chat_id)
        if chat_memory is None:
            module = MemoryFactory.create_memory_module(module_type)
            chat_memory_modules[chat_id] = (module_type, module)
        else:
            selected_module_type, module = chat_memory
            if selected_module_type != module_type:
                return jsonify({'error': 'The memory module cannot be changed during a chat.'}), 409

        result, latency, total_tokens = run_ReAct(message, memory_module=module)
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