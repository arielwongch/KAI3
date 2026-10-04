/* Versioned browser sessions; server memory remains process-local. */
const $ = id => document.getElementById(id);
const key = 'kai3-workspace-v1';
function readJSON(key, fallback) { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } }
function newSession() { return {id: crypto.randomUUID(), title: 'New chat', module: null, messages: [], started: false}; }
let workspace = readJSON(key, null);
if (!workspace || workspace.version !== 1 || !Array.isArray(workspace.sessions) || !workspace.sessions.length) {
    const session = newSession();
    session.messages = readJSON('kai3-chat-history', []);
    session.id = localStorage.getItem('kai3-chat-id') || session.id;
    session.module = localStorage.getItem('kai3-memory-module');
    session.started = session.messages.length > 0;
    session.title = session.messages.find(m => m.role === 'user')?.content.slice(0, 60) || 'New chat';
    workspace = {version: 1, sessions: [session], active: session.id};
}
let busy = false, unavailable = false, checking = false;
let inspection = null, inspectionTab = 'contents', inspectionSource = 'chat', benchmark = null, runId = null;
let pollTimer = null, inspectionRequest = 0;
function active() { return workspace.sessions.find(s => s.id === workspace.active) || workspace.sessions[0]; }
function save() { localStorage.setItem(key, JSON.stringify(workspace)); }
function markdown(text) { return DOMPurify.sanitize(marked.parse(String(text))); }
function controlState() {
    const session = active();
    $('userInput').disabled = busy || checking || unavailable || !session.module;
    $('sendButton').disabled = $('userInput').disabled;
    $('moduleStatus').textContent = unavailable ? 'Server memory unavailable — start a new chat' : checking ? 'Checking server memory…' : session.module?.replaceAll('_', ' ') || 'No memory module selected';
    document.querySelectorAll('.memory-choice').forEach(b => { b.disabled = !!session.module || busy || checking; b.classList.toggle('selected', b.dataset.module === session.module); });
    $('userInput').placeholder = session.module ? 'Ask anything, or tell KAI3 what to remember...' : 'Choose a memory module to begin...';
}
function render() {
    const session = active();
    $('chatMessages').replaceChildren();
    $('emptyState').hidden = session.messages.length > 0;
    session.messages.forEach(message => {
        const row = document.createElement('article'); row.className = `message-row ${message.role === 'user' ? 'user' : 'assistant'}`;
        const avatar = document.createElement('div'); avatar.className = 'message-avatar'; avatar.textContent = message.role === 'user' ? 'A' : '✦';
        const content = document.createElement('div'); content.className = 'message-content';
        const label = document.createElement('div'); label.className = 'message-label'; label.textContent = message.role === 'user' ? 'You' : 'KAI3';
        const body = document.createElement('div'); body.className = 'message-body';
        if (message.role === 'user') { body.textContent = message.content; body.style.whiteSpace = 'pre-wrap'; } else body.innerHTML = markdown(message.content);
        body.querySelectorAll('pre').forEach(block => { const b = document.createElement('button'); b.className = 'copy-button'; b.textContent = 'Copy'; b.onclick = async () => { await navigator.clipboard.writeText(block.querySelector('code')?.textContent || ''); b.textContent = 'Copied'; }; block.append(b); });
        content.append(label, body); row.append(avatar, content); $('chatMessages').append(row);
    });
    $('chatHistory').replaceChildren();
    workspace.sessions.slice().reverse().forEach(s => {
        const b = document.createElement('button'); b.className = 'history-item' + (s.id === session.id ? ' active' : ''); b.textContent = s.title; b.disabled = busy;
        b.onclick = () => { workspace.active = s.id; save(); inspectionSource = 'chat'; inspection = null; render(); refreshInspection(); document.body.classList.remove('sidebar-open'); };
        $('chatHistory').append(b);
    });
    $('historyCount').textContent = workspace.sessions.length;
    controlState(); $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
}
async function jsonRequest(url, options) {
    const response = await fetch(url, options);
    const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || 'Request failed'); error.status = response.status; throw error; }
    return data;
}
function card(title, value) {
    const el = document.createElement('article'); el.className = 'inspection-card';
    const heading = document.createElement('h3'); heading.textContent = title;
    const pre = document.createElement('pre'); pre.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    el.append(heading, pre); return el;
}
function drawInspection() {
    const body = $('inspectionBody'); body.replaceChildren();
    document.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('selected', b.dataset.tab === inspectionTab));
    if (!inspection) return;
    const turns = inspection.turns || [];
    const index = Number($('turnSelector').value) || 0;
    const turn = turns[index];
    if (inspectionTab === 'contents') {
        body.append(card('Configuration', inspection.memory.config));
        if (!inspection.memory.entries.length) body.append(card('Empty memory', 'No stored contents.'));
        inspection.memory.entries.forEach((e, i) => { body.append(card(`Entry ${i + 1}`, e.text), card('Metadata', {...e.metadata, ...(e.chunk_count !== undefined ? {chunk_count: e.chunk_count} : {})})); });
    } else if (inspectionTab === 'retrieved') {
        if (!turn) body.append(card('No turns', 'Send a message to record retrieval.'));
        else {
            body.append(card('Query', turn.query), card('Status', turn.status));
            if (!turn.retrieved?.length) body.append(card('Retrieved context', 'No context retrieved.'));
            (turn.retrieved || []).forEach((e, i) => body.append(card(`Retrieved ${i + 1}`, e)));
            if (turn.final_answer) body.append(card('Final answer', turn.final_answer));
            if (turn.error) body.append(card('Error', turn.error));
        }
    } else {
        body.append(card('Session totals', inspection.totals || {}));
        if (turn) { const {retrieved, query, final_answer, ...metrics} = turn; body.append(card('Selected turn metrics', metrics)); }
        body.append(card('Metric definitions', 'Times are seconds. Agent tokens and memory LLM tokens are separate. null means unavailable. Embeddings have no API token count. Total time includes all measured work.'));
    }
}
function setInspection(data, status) {
    inspection = data; $('inspectionStatus').textContent = status;
    const selector = $('turnSelector'), old = selector.value;
    selector.replaceChildren();
    (data.turns || []).forEach((t, i) => { const option = document.createElement('option'); option.value = i; option.textContent = `${i + 1}. ${t.query?.slice(0, 55) || t.status}`; selector.append(option); });
    selector.value = old && Number(old) < (data.turns || []).length ? old : String(Math.max(0, (data.turns || []).length - 1));
    drawInspection();
}
async function refreshInspection() {
    if (inspectionSource === 'benchmark') { if (benchmark) inspectBenchmark(); return; }
    const requestId = ++inspectionRequest, session = active();
    checking = session.started; unavailable = false; controlState();
    $('inspectionStatus').textContent = 'Loading…';
    try {
        const data = await jsonRequest(`/api/chats/${encodeURIComponent(session.id)}/diagnostics`);
        if (requestId !== inspectionRequest || active().id !== session.id) return;
        setInspection(data, session.module?.replaceAll('_', ' ') || 'Memory');
    } catch (error) {
        if (requestId !== inspectionRequest || active().id !== session.id) return;
        inspection = null; drawInspection();
        if (error.status === 404) { unavailable = session.started; $('inspectionStatus').textContent = session.started ? 'Server memory unavailable. Browser messages remain; start a new chat to continue.' : 'Empty session. Memory is created with the first message.'; }
        else { unavailable = session.started; $('inspectionStatus').textContent = error.message; }
    } finally { if (requestId === inspectionRequest && active().id === session.id) { checking = false; controlState(); } }
}
$('chatForm').onsubmit = async event => {
    event.preventDefault(); if ($('sendButton').disabled) return;
    const session = active(), message = $('userInput').value.trim(); if (!message) return;
    const requiresExisting = session.started;
    session.messages.push({role: 'user', content: message}); session.title = session.messages.find(m => m.role === 'user').content.slice(0, 60);
    $('userInput').value = ''; busy = true; save(); render(); document.body.classList.add('is-loading');
    const loader = card('KAI3', 'Thinking…'); $('chatMessages').append(loader);
    try {
        const data = await jsonRequest('/get', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({message, chat_id: session.id, memory_module: session.module, requires_existing: requiresExisting})});
        session.started = true; session.messages.push({role: 'assistant', content: data.reply, turn_id: data.turn_id});
    } catch (error) { session.started = true; session.messages.push({role: 'assistant', content: `Request failed: ${error.message}`}); }
    finally { busy = false; document.body.classList.remove('is-loading'); save(); render(); inspectionSource = 'chat'; await refreshInspection(); $('userInput').focus(); }
};
$('userInput').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); $('chatForm').requestSubmit(); } };
document.querySelectorAll('.memory-choice').forEach(b => b.onclick = () => { if (active().module) return; active().module = b.dataset.module; save(); render(); });
$('newChat').onclick = () => { if (busy) return; const s = newSession(); workspace.sessions.push(s); workspace.active = s.id; unavailable = false; checking = false; inspectionSource = 'chat'; inspection = null; save(); render(); refreshInspection(); };
$('collapseSidebar').onclick = () => document.body.classList.toggle('sidebar-collapsed');
$('openSidebar').onclick = () => document.body.classList.toggle('sidebar-open');
$('openInspector').onclick = () => { $('inspector').hidden = false; document.body.classList.add('inspector-open'); inspectionSource = 'chat'; refreshInspection(); };
$('closeInspector').onclick = () => { $('inspector').hidden = true; document.body.classList.remove('inspector-open'); };
$('refreshInspector').onclick = refreshInspection;
$('turnSelector').onchange = drawInspection;
document.querySelectorAll('[data-tab]').forEach(b => b.onclick = () => { inspectionTab = b.dataset.tab; drawInspection(); });
function download(url) { const a = document.createElement('a'); a.href = url; a.download = ''; a.click(); }
$('exportInspector').onclick = () => { if (inspection) download(inspectionSource === 'chat' ? `/api/chats/${encodeURIComponent(active().id)}/export` : `/api/benchmarks/${runId}/export`); };
$('openTesting').onclick = () => { $('testing').hidden = false; };
$('closeTesting').onclick = () => { $('testing').hidden = true; };
function csv(id) { return $(id).value.split(',').map(v => v.trim()).filter(Boolean); }
$('benchmarkForm').onsubmit = async event => {
    event.preventDefault(); $('runBenchmark').disabled = true;
    try {
        const file = $('datasetFile').files[0]; if (!file) throw new Error('Choose a dataset JSON file.');
        const dataset = JSON.parse(await file.text());
        const options = {modules: [...document.querySelectorAll('[name=benchmarkModule]:checked')].map(b => b.value), sample_ids: $('allConversations').checked ? dataset.map(s => String(s.sample_id)) : csv('sampleIds'), categories: csv('categories').map(Number), question_limit: Number($('questionLimit').value)};
        const result = await jsonRequest('/api/benchmarks', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({dataset, options})});
        runId = result.run_id; localStorage.setItem('kai3-benchmark-run', runId); pollBenchmark();
    } catch (error) { $('benchmarkStatus').textContent = error.message; $('runBenchmark').disabled = false; }
};
async function pollBenchmark() {
    clearTimeout(pollTimer);
    try {
        benchmark = await jsonRequest(`/api/benchmarks/${runId}`);
        $('benchmarkStatus').textContent = `${benchmark.status}: ${benchmark.progress.completed}/${benchmark.progress.total} questions processed`;
        const running = ['queued', 'running'].includes(benchmark.status);
        $('runBenchmark').disabled = running; $('cancelBenchmark').disabled = !running; $('exportBenchmark').disabled = false;
        drawBenchmark();
        if (inspectionSource === 'benchmark') inspectBenchmark();
        if (running) pollTimer = setTimeout(pollBenchmark, 1500);
    } catch (error) { $('benchmarkStatus').textContent = error.message; $('runBenchmark').disabled = false; $('cancelBenchmark').disabled = true; }
}
function drawBenchmark() {
    const body = $('benchmarkResults'); body.replaceChildren();
    body.append(card('Mean QA scores by module and category', benchmark.scores || []));
    (benchmark.errors || []).forEach(e => body.append(card('Ingestion failed', e)));
    const memories = document.createElement('select'); memories.id = 'benchmarkMemory';
    const previous = inspection?.benchmarkIndex || 0;
    benchmark.memories.forEach((m, i) => { const o = document.createElement('option'); o.value = i; o.textContent = `${m.module} / ${m.sample_id}`; memories.append(o); });
    memories.value = previous; body.append(memories);
    const inspect = document.createElement('button'); inspect.type = 'button'; inspect.textContent = 'Inspect benchmark memory'; inspect.onclick = () => { inspectionSource = 'benchmark'; $('inspector').hidden = false; document.body.classList.add('inspector-open'); inspectBenchmark(); }; body.append(inspect);
    benchmark.cases.forEach(c => body.append(card(`${c.module} / ${c.sample_id} / question ${c.question_index + 1} — ${c.diagnostics.status}`, {question: c.question, prediction: c.prediction, answer: c.answer, qa_score: c.score, evidence_recall: c.evidence_recall, error: c.error})));
}
function inspectBenchmark() {
    const index = Number($('benchmarkMemory')?.value || 0), memory = benchmark.memories[index]; if (!memory) return;
    const turns = benchmark.cases.filter(c => c.module === memory.module && c.sample_id === memory.sample_id).map(c => c.diagnostics);
    const totals = {}; ['total_seconds','retrieval_seconds','agent_seconds','write_seconds','agent_tokens','memory_tokens','agent_llm_calls','memory_llm_calls'].forEach(k => { totals[k] = turns.some(t => t[k] == null) ? null : turns.reduce((sum, t) => sum + t[k], 0); });
    totals.ingestion = memory.ingestion;
    setInspection({memory: memory.memory, turns, totals, benchmarkIndex: index}, `${memory.module} / ${memory.sample_id}`);
}
$('cancelBenchmark').onclick = async () => { try { await jsonRequest(`/api/benchmarks/${runId}/cancel`, {method: 'POST'}); $('benchmarkStatus').textContent = 'Cancellation requested; waiting for the current operation.'; } catch (e) { $('benchmarkStatus').textContent = e.message; } };
$('exportBenchmark').onclick = () => download(`/api/benchmarks/${runId}/export`);
save(); render(); refreshInspection();
runId = localStorage.getItem('kai3-benchmark-run'); if (runId) pollBenchmark();
