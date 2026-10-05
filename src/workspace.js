/* Versioned browser sessions; server memory remains process-local. */
const $ = id => document.getElementById(id);
const key = 'kai3-workspace-v1';
function readJSON(name, fallback) { try { return JSON.parse(localStorage.getItem(name)) ?? fallback; } catch { return fallback; } }
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
let inspection = null, inspectionTab = 'contents', inspectionSource = 'chat', selectedRecord = null;
let importedBenchmark = false, importedOriginal = null;
let benchmark = null, runId = null, pollTimer = null, inspectionRequest = 0, previewDataset = null;
const page = typeof location !== 'undefined' && location.pathname === '/benchmark' ? 'benchmark' : 'chat';
$('chatWorkspace').hidden = page !== 'chat';
$('testing').hidden = page !== 'benchmark';
document.querySelectorAll('.workspace-nav-item').forEach(link => link.classList.toggle('active', link.dataset.page === page));
function active() { return workspace.sessions.find(s => s.id === workspace.active) || workspace.sessions[0]; }
function save() { localStorage.setItem(key, JSON.stringify(workspace)); }
function markdown(text) { return DOMPurify.sanitize(marked.parse(String(text))); }
function labelMode(mode) { return (mode || 'No architecture selected').replaceAll('_', ' '); }
function controlState() {
    const session = active();
    $('userInput').disabled = busy || checking || unavailable || !session.module;
    $('sendButton').disabled = $('userInput').disabled;
    $('moduleStatus').textContent = unavailable ? 'Memory unavailable · start a new chat' : checking ? 'Checking memory…' : labelMode(session.module);
    document.querySelectorAll('.memory-choice').forEach(b => { b.disabled = !!session.module || busy || checking; b.classList.toggle('selected', b.dataset.module === session.module); });
    $('userInput').placeholder = session.module ? 'Message KAI3…' : 'Select a memory architecture to start';
}
function render() {
    const session = active();
    $('chatMessages').replaceChildren();
    $('emptyState').hidden = session.messages.length > 0;
    session.messages.forEach(message => {
        const row = document.createElement('article'); row.className = `message-row ${message.role === 'user' ? 'user' : 'assistant'}`;
        const avatar = document.createElement('div'); avatar.className = 'message-avatar'; avatar.textContent = message.role === 'user' ? 'Y' : 'K';
        const content = document.createElement('div'); content.className = 'message-content';
        const label = document.createElement('div'); label.className = 'message-label'; label.textContent = message.role === 'user' ? 'You' : 'KAI3';
        const body = document.createElement('div'); body.className = 'message-body';
        if (message.role === 'user') { body.textContent = message.content; body.style.whiteSpace = 'pre-wrap'; } else body.innerHTML = markdown(message.content);
        body.querySelectorAll('pre').forEach(block => { const button = document.createElement('button'); button.className = 'copy-button'; button.textContent = 'Copy'; button.onclick = async () => { await navigator.clipboard.writeText(block.querySelector('code')?.textContent || ''); button.textContent = 'Copied'; }; block.append(button); });
        content.append(label, body); row.append(avatar, content); $('chatMessages').append(row);
    });
    $('chatHistory').replaceChildren();
    workspace.sessions.slice().reverse().forEach(s => {
        const button = document.createElement('button'); button.className = 'history-item' + (s.id === session.id ? ' active' : ''); button.textContent = s.title; button.title = s.title; button.disabled = busy;
        button.onclick = () => { workspace.active = s.id; save(); inspectionSource = 'chat'; inspection = null; selectedRecord = null; render(); refreshInspection(); document.body.classList.remove('sidebar-open'); };
        $('chatHistory').append(button);
    });
    $('historyCount').textContent = workspace.sessions.length;
    controlState(); $('chatMessages').scrollTop = $('chatMessages').scrollHeight;
}
async function jsonRequest(url, options) {
    const response = await fetch(url, options); const data = await response.json();
    if (!response.ok) { const error = new Error(data.error || 'Request failed'); error.status = response.status; throw error; }
    return data;
}
function addCard(parent, title, value) {
    const card = document.createElement('article'); card.className = 'inspection-card';
    const heading = document.createElement('h3'); heading.textContent = title;
    const content = document.createElement('pre'); content.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    card.append(heading, content); parent.append(card); return card;
}
function addField(parent, label, value) {
    const item = document.createElement('div'); item.className = 'detail-field';
    const name = document.createElement('span'); name.textContent = label;
    const content = document.createElement('div'); content.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    item.append(name, content); parent.append(item);
}
function setInspectorViewTitle() {
    const names = {contents:['Stored records','Browse the records currently held by this architecture.'], retrieved:['Retrieved context','Inspect the context used to answer a selected turn.'], metrics:['Turn metrics','Review timing, tokens, and memory operation counts.']};
    const [title, subtitle] = names[inspectionTab]; $('memoryViewTitle').textContent = title; $('memoryViewSubtitle').textContent = subtitle;
    document.querySelectorAll('[data-tab]').forEach(button => button.classList.toggle('selected', button.dataset.tab === inspectionTab));
    $('memorySearch').hidden = inspectionTab !== 'contents';
    if ($('memorySearch').parentElement) $('memorySearch').parentElement.hidden = inspectionTab !== 'contents';
}
function drawInspection() {
    const body = $('inspectionBody'); body.replaceChildren(); setInspectorViewTitle();
    if (!inspection) return;
    const turns = inspection.turns || [], index = Number($('turnSelector').value) || 0, turn = turns[index];
    if (inspectionTab === 'contents') {
        const entries = inspection.memory?.entries || [], query = ($('memorySearch').value || '').trim().toLowerCase();
        $('recordCount').textContent = entries.length;
        const filtered = entries.map((entry, i) => ({entry, i})).filter(({entry}) => !query || `${entry.text} ${JSON.stringify(entry.metadata)}`.toLowerCase().includes(query));
        if (!filtered.length) { addCard(body, entries.length ? 'No matching records' : 'No records yet', entries.length ? 'Try a different search.' : 'Records will appear here as this chat uses its selected memory architecture.'); return; }
        const browser = document.createElement('div'); browser.className = 'record-browser';
        const tableWrap = document.createElement('div'); tableWrap.className = 'record-table-wrap';
        const table = document.createElement('table'); table.className = 'memory-table';
        table.innerHTML = '<thead><tr><th>#</th><th>Type</th><th>Record preview</th><th>Updated fields</th></tr></thead>';
        const rows = document.createElement('tbody');
        filtered.forEach(({entry, i}) => {
            const row = document.createElement('tr'); row.tabIndex = 0; row.classList.toggle('selected', selectedRecord === i);
            const vals = [String(i + 1), entry.metadata?.type || 'memory', entry.text.slice(0, 150), Object.keys(entry.metadata || {}).filter(k => k !== 'user_text' && k !== 'assistant_text').join(', ') || '—'];
            vals.forEach(value => { const cell = document.createElement('td'); cell.textContent = value; row.append(cell); });
            const select = () => { selectedRecord = i; drawInspection(); };
            row.onclick = select; row.onkeydown = event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } };
            rows.append(row);
        });
        table.append(rows); tableWrap.append(table);
        const detail = document.createElement('aside'); detail.className = 'record-detail';
        const selected = filtered.find(item => item.i === selectedRecord) || filtered[0];
        if (!filtered.some(item => item.i === selectedRecord)) selectedRecord = selected.i;
        const heading = document.createElement('h3'); heading.textContent = `Record ${selected.i + 1}`; detail.append(heading);
        addField(detail, 'Content', selected.entry.text);
        Object.entries({...selected.entry.metadata, ...(selected.entry.chunk_count !== undefined ? {chunk_count:selected.entry.chunk_count} : {})}).forEach(([key, value]) => addField(detail, key.replaceAll('_', ' '), value));
        browser.append(tableWrap, detail); body.append(browser);
    } else if (inspectionTab === 'retrieved') {
        if (!turn) { addCard(body, 'No turn selected', 'Send a message or choose a turn to see the context retrieved for it.'); return; }
        const grid = document.createElement('div'); grid.className = 'retrieved-header';
        addField(grid, 'Query', turn.query || ''); addField(grid, 'Status', turn.status || ''); body.append(grid);
        if (!turn.retrieved?.length) addCard(body, 'No context retrieved', 'The selected turn did not retrieve any memory records.');
        (turn.retrieved || []).forEach((entry, i) => { const card = document.createElement('article'); card.className = 'retrieved-record'; const heading=document.createElement('h3'); heading.textContent=`Retrieved record ${i+1}`; const text=document.createElement('p'); text.textContent=entry.text || ''; card.append(heading,text); Object.entries(entry.metadata || {}).forEach(([k,v])=>addField(card,k.replaceAll('_',' '),v)); body.append(card); });
        if (turn.final_answer) addCard(body, 'Answer', turn.final_answer);
    } else {
        const totals=inspection.totals||{};
        const totalsSection=document.createElement('section');totalsSection.className='metrics-section';
        const totalsTitle=document.createElement('h3');totalsTitle.textContent='Session totals';totalsSection.append(totalsTitle);
        Object.entries(totals).forEach(([k,v])=>addField(totalsSection,k.replaceAll('_',' '),v));body.append(totalsSection);
        if(turn){const turnSection=document.createElement('section');turnSection.className='metrics-section';const turnTitle=document.createElement('h3');turnTitle.textContent='Selected turn';turnSection.append(turnTitle);Object.entries(turn).filter(([k])=>!['retrieved','query','final_answer'].includes(k)).forEach(([k,v])=>addField(turnSection,k.replaceAll('_',' '),v));body.append(turnSection);}
    }
}
function setInspection(data, status) {
    inspection = data; $('inspectionStatus').textContent = status;
    const selector = $('turnSelector'), old = selector.value; selector.replaceChildren();
    (data.turns || []).forEach((turn, i) => { const option=document.createElement('option'); option.value=i; option.textContent=`${i+1}. ${(turn.query || turn.status || 'Turn').slice(0,52)}`; selector.append(option); });
    selector.value = old && Number(old) < (data.turns || []).length ? old : String(Math.max(0, (data.turns || []).length - 1));
    drawInspection();
}
async function refreshInspection() {
    if (inspectionSource === 'benchmark') { if (benchmark) inspectBenchmark(); return; }
    const requestId = ++inspectionRequest, session = active(); checking = session.started; unavailable = false; controlState();
    $('inspectionStatus').textContent = 'Loading memory…';
    try {
        const data = await jsonRequest(`/api/chats/${encodeURIComponent(session.id)}/diagnostics`);
        if (requestId !== inspectionRequest || active().id !== session.id) return;
        setInspection(data, labelMode(session.module));
    } catch (error) {
        if (requestId !== inspectionRequest || active().id !== session.id) return;
        inspection = null; drawInspection();
        $('inspectionStatus').textContent = error.status === 404 ? (session.started ? 'Server memory unavailable. Start a new chat to continue.' : 'Empty chat · memory is created with the first message.') : error.message;
        unavailable = session.started;
    } finally { if (requestId === inspectionRequest && active().id === session.id) { checking = false; controlState(); } }
}
$('chatForm').onsubmit = async event => {
    event.preventDefault(); if ($('sendButton').disabled) return;
    const session=active(), message=$('userInput').value.trim(); if (!message) return;
    const requiresExisting=session.started; session.messages.push({role:'user',content:message});
    session.title=session.messages.find(m=>m.role==='user').content.slice(0,60); $('userInput').value=''; busy=true; save(); render();
    const loading=document.createElement('div'); loading.className='chat-loading'; loading.textContent='KAI3 is thinking…'; $('chatMessages').append(loading);
    try { const data=await jsonRequest('/get',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message,chat_id:session.id,memory_module:session.module,requires_existing:requiresExisting})}); session.started=true; session.messages.push({role:'assistant',content:data.reply,turn_id:data.turn_id}); }
    catch(error) { session.started=true; session.messages.push({role:'assistant',content:`Request failed: ${error.message}`}); }
    finally { busy=false; save(); render(); inspectionSource='chat'; await refreshInspection(); $('userInput').focus(); }
};
$('userInput').onkeydown = event => { if (event.key==='Enter'&&!event.shiftKey) { event.preventDefault(); $('chatForm').requestSubmit(); } };
document.querySelectorAll('.memory-choice').forEach(button=>button.onclick=()=>{if(active().module)return;active().module=button.dataset.module;save();render();});
$('newChat').onclick=()=>{if(busy)return;const session=newSession();workspace.sessions.push(session);workspace.active=session.id;unavailable=false;checking=false;inspectionSource='chat';inspection=null;save();render();refreshInspection();};
$('collapseSidebar').onclick=()=>document.body.classList.toggle('sidebar-collapsed');
$('openSidebar').onclick=()=>document.body.classList.toggle('sidebar-open');
$('openSidebarBenchmark').onclick=()=>document.body.classList.toggle('sidebar-open');
$('openInspector').onclick=()=>{inspectionSource='chat';$('inspector').hidden=false;document.body.classList.add('memory-open');refreshInspection();};
$('closeInspector').onclick=()=>{ $('inspector').hidden=true; document.body.classList.remove('memory-open'); };
$('refreshInspector').onclick=refreshInspection; $('turnSelector').onchange=drawInspection;
document.querySelectorAll('[data-tab]').forEach(button=>button.onclick=()=>{inspectionTab=button.dataset.tab;drawInspection();});
$('memorySearch').oninput=drawInspection;
function downloadJSON(data, filename){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
function normalizeBenchmarkImport(value){
    const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
    const fail=message=>{throw new Error(`Cannot import results: ${message}`);};
    if(!object(value)||!Array.isArray(value.cases))fail('choose a benchmark results export, not a LoCoMo dataset or review labels.');
    if(value.schema_version!=null&&value.schema_version!==1)fail('unsupported results schema version.');
    const report=JSON.parse(JSON.stringify(value));
    for(const field of ['scores','memories','errors','efficiency']){if(report[field]==null)report[field]=[];if(!Array.isArray(report[field]))fail(`${field} must be an array.`);}
    if(report.config!=null&&!object(report.config))fail('config must be an object.');
    report.config=report.config||{};
    for(const field of ['modules','sample_ids','categories']){if(report.config[field]==null)report.config[field]=[];if(!Array.isArray(report.config[field]))fail(`config.${field} must be an array.`);}
    const metricFields=['score','exact_match','token_f1','evidence_recall','correct'];
    report.cases.forEach((c,i)=>{
        if(!object(c)||typeof c.question!=='string'||![1,2,3,4,5].includes(c.category))fail(`question ${i+1} needs question text and a category from 1 to 5.`);
        if(c.prediction!=null&&typeof c.prediction!=='string')fail(`question ${i+1} has an invalid prediction.`);
        for(const field of metricFields)if(c[field]!=null&&(typeof c[field]!=='number'||!Number.isFinite(c[field])))fail(`question ${i+1} has an invalid ${field}.`);
        if(c.judge!=null&&!object(c.judge))fail(`question ${i+1} has an invalid judge assessment.`);
        if(c.diagnostics!=null&&!object(c.diagnostics))fail(`question ${i+1} has invalid diagnostics.`);
        c.diagnostics=c.diagnostics||{};
        if(c.diagnostics.retrieved==null)c.diagnostics.retrieved=[];
        if(!Array.isArray(c.diagnostics.retrieved)||c.diagnostics.retrieved.some(e=>!object(e)||typeof e.text!=='string'||(e.metadata!=null&&!object(e.metadata))))fail(`question ${i+1} has invalid retrieved records.`);
        if(c.question_index==null)c.question_index=i;
        if(!Number.isInteger(c.question_index)||c.question_index<0)fail(`question ${i+1} has an invalid question index.`);
    });
    report.scores.forEach(row=>{
        if(!object(row)||!['1','2','3','4','5','overall'].includes(String(row.category)))fail('invalid category score row.');
        for(const field of ['mean_qa_score','mean_exact_match','mean_token_f1','mean_judge','accuracy','answer_count','judge_count','correct_count','scored_count','unscored_count'])if(row[field]!=null&&(typeof row[field]!=='number'||!Number.isFinite(row[field])))fail(`invalid score field: ${field}.`);
    });
    report.memories.forEach(m=>{
        if(!object(m)||!object(m.memory)||!Array.isArray(m.memory.entries)||m.memory.entries.some(e=>!object(e)||typeof e.text!=='string'))fail('invalid memory snapshot.');
        m.memory.config=m.memory.config||{};m.ingestion=m.ingestion||{};
    });
    if(report.efficiency.some(e=>!object(e)))fail('invalid efficiency report.');
    if(!report.config.modules.length)report.config.modules=[...new Set(report.cases.map(c=>c.module).filter(Boolean))];
    if(!report.config.sample_ids.length)report.config.sample_ids=[...new Set(report.cases.map(c=>c.sample_id).filter(v=>v!=null))];
    if(!report.config.categories.length)report.config.categories=[...new Set(report.cases.map(c=>c.category))];
    return report;
}
function showImportedBenchmark(value,filename){
    if(benchmark&&['queued','running'].includes(benchmark.status)&&!importedBenchmark)throw new Error('Finish or cancel the active benchmark before importing results.');
    const report=normalizeBenchmarkImport(value);
    importedOriginal=value;importedBenchmark=true;benchmark=report;clearTimeout(pollTimer);runId=null;
    localStorage.removeItem('kai3-benchmark-run');
    $('benchmarkSetup').hidden=true;$('benchmarkRunning').hidden=true;$('benchmarkReport').hidden=false;
    $('reportTitle').textContent='Imported benchmark results';
    $('reportSubtitle').textContent=`${filename} ? ${report.status||'Saved report'} ? ${report.cases.length} question results`;
    $('reportStatus').textContent=report.error?displayFailure(report.error):'Read-only report. No API calls are made when importing results.';
    $('resumeBenchmark').hidden=true;$('exportReview').hidden=true;$('reviewFile').disabled=true;
    drawBenchmark();
}
$('resultsFile').onchange=async()=>{
    const file=$('resultsFile').files?.[0];if(!file)return;
    try{showImportedBenchmark(JSON.parse((await file.text()).replace(/^\uFEFF/,'')),file.name);}
    catch(error){const message=error instanceof SyntaxError?'Cannot import results: the file is not valid JSON.':error.message;$(benchmark&&!$('benchmarkReport').hidden?'reportStatus':'benchmarkStatus').textContent=message;}
    finally{$('resultsFile').value='';}
};
function download(url) { const a=document.createElement('a');a.href=url;a.download='';a.click(); }
$('exportInspector').onclick=()=>{if(inspection&&importedBenchmark&&inspectionSource==='benchmark'){downloadJSON(inspection,'imported-memory.json');return;}if(inspection)download(inspectionSource==='chat'?`/api/chats/${encodeURIComponent(active().id)}/export`:`/api/benchmarks/${runId}/export`);};
$('cancelBenchmark').onclick=async()=>{try{await jsonRequest(`/api/benchmarks/${runId}/cancel`,{method:'POST'});}catch(e){$('reportStatus').textContent=e.message;}};
$('exportBenchmark').onclick=()=>importedBenchmark?downloadJSON(importedOriginal,'imported-results.json'):download(`/api/benchmarks/${runId}/export`);
$('exportReview').onclick=()=>{if(importedBenchmark)return;download(`/api/benchmarks/${runId}/review`);};
$('reviewFile').onchange=async()=>{if(importedBenchmark)return;try{const data=JSON.parse(await $('reviewFile').files[0].text());const reviews=data.reviews||data.cases.filter(c=>c.ratings).map(c=>({case_index:c.case_index,ratings:c.ratings,notes:c.notes}));const result=await jsonRequest(`/api/benchmarks/${runId}/review`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reviews})});benchmark.calibration=result.calibration;drawBenchmark();$('reportStatus').textContent='Human labels imported and agreement updated.';}catch(error){$('reportStatus').textContent=error.message;}};
$('resumeBenchmark').onclick=async()=>{if(importedBenchmark)return;try{if(!previewDataset)await loadDefaultDataset();const result=await jsonRequest(`/api/benchmarks/${runId}/resume`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:previewDataset})});runId=result.run_id;pollBenchmark();}catch(error){$('reportStatus').textContent=error.message;}};
$('newBenchmarkRun').onclick=()=>{importedBenchmark=false;importedOriginal=null;$('exportReview').hidden=false;$('reviewFile').disabled=false;clearTimeout(pollTimer);benchmark=null;runId=null;localStorage.removeItem('kai3-benchmark-run');$('benchmarkReport').hidden=true;$('benchmarkRunning').hidden=true;$('benchmarkSetup').hidden=false;$('reportStatus').textContent='';};
$('toggleAdvanced').onclick=()=>{const details=$('advancedDetails'),open=details.hidden;details.hidden=!open;$('toggleAdvanced').setAttribute('aria-expanded',String(open));$('toggleAdvanced').lastElementChild.textContent=open?'−':'＋';};
function selectedCategories(){return [...document.querySelectorAll('[name=category]:checked')].map(input=>Number(input.value));}
function selectedSamples(){return [...$('sampleIds').selectedOptions].map(option=>option.value);}
function selectedQuestionCount(data){const ids=$('allConversations').checked?data.map(s=>String(s.sample_id)):selectedSamples();const categories=selectedCategories(),limit=Number($('questionLimit').value);const samples=data.filter(s=>ids.includes(String(s.sample_id)));return samples.reduce((n,s)=>{const count=s.qa.filter(q=>categories.includes(q.category)).length;return n+(limit?Math.min(count,limit):count);},0);}
function updateRunSummary(){
    const loaded=!!previewDataset, mode=document.querySelector('[name=benchmarkModule]:checked')?.value||'sliding_window';
    const count=loaded?selectedQuestionCount(previewDataset):'—';
    $('runSummary').innerHTML='';
    const heading=document.createElement('strong');heading.textContent='Run estimate';
    const text=document.createElement('p');text.textContent=`${mode.replaceAll('_',' ')} · ${count} questions · ${count} answer calls + ${count} judge calls. Memory extraction may add calls.`;
    const metrics=document.createElement('small');metrics.textContent='LoCoMo score · normalized exact match · token F1 · correctness, completeness, support, abstention';
    $('runSummary').append(heading,text,metrics); $('runBenchmark').disabled=!loaded||!count||count<1;
}
function updateConversationChoices(){
    const select=$('sampleIds'), previous=new Set(selectedSamples());select.replaceChildren();
    (previewDataset||[]).forEach(sample=>{const option=document.createElement('option');option.value=String(sample.sample_id);option.textContent=String(sample.sample_id);option.selected=previous.has(option.value);select.append(option);});
    if(!previous.size&&select.options.length)select.options[0].selected=true;
    select.disabled=$('allConversations').checked;
}
$('datasetFile').onchange=async()=>{
    try{previewDataset=JSON.parse(await $('datasetFile').files[0].text());if(!Array.isArray(previewDataset)||!previewDataset.length)throw new Error('Dataset must be a nonempty JSON array.');
        $('datasetFileName').textContent=$('datasetFile').files[0].name;$('datasetInfo').textContent=`${previewDataset.length} conversations · ${($('datasetFile').files[0].size/1024/1024).toFixed(1)} MB`;
        updateConversationChoices();updateRunSummary();
    }catch(error){previewDataset=null;$('datasetFileName').textContent='Could not read dataset';$('datasetInfo').textContent=error.message;updateRunSummary();}
};
async function loadDefaultDataset(){
    try{const result=await jsonRequest('/api/benchmarks/dataset');previewDataset=result.dataset;$('datasetFileName').textContent=result.filename;$('datasetInfo').textContent=`${previewDataset.length} conversations · bundled dataset`;$('allConversations').checked=true;updateConversationChoices();updateRunSummary();}
    catch(error){$('datasetFileName').textContent='Bundled dataset unavailable';$('datasetInfo').textContent='Upload a LoCoMo JSON file to continue.';updateRunSummary();}
}
$('allConversations').onchange=()=>{updateConversationChoices();updateRunSummary();};
$('sampleIds').onchange=updateRunSummary;$('questionLimit').oninput=updateRunSummary;
document.querySelectorAll('[name=category],[name=benchmarkModule]').forEach(input=>input.onchange=updateRunSummary);
$('benchmarkForm').onsubmit=async event=>{
    event.preventDefault();if(!previewDataset)return;importedBenchmark=false;importedOriginal=null;$('exportReview').hidden=false;
    $('resultsFile').disabled=true;$('benchmarkSetup').hidden=true;$('benchmarkRunning').hidden=false;$('benchmarkReport').hidden=true;$('progressTitle').textContent='Starting benchmark';$('progressDetail').textContent='Preparing the selected memory architecture.';
    try{
        const options={module:document.querySelector('[name=benchmarkModule]:checked').value,sample_ids:$('allConversations').checked?previewDataset.map(s=>String(s.sample_id)):selectedSamples(),categories:selectedCategories(),no_memory_context:$('noMemoryContext').value,question_limit:Number($('questionLimit').value)};
        const result=await jsonRequest('/api/benchmarks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({dataset:previewDataset,options})});
        runId=result.run_id;localStorage.setItem('kai3-benchmark-run',runId);pollBenchmark();
    }catch(error){$('resultsFile').disabled=false;$('benchmarkSetup').hidden=false;$('benchmarkRunning').hidden=true;$('benchmarkStatus').textContent=error.message;}
};
function categoryName(value){return ({'1':'Multi-hop','2':'Temporal','3':'Open-domain','4':'Single-hop','5':'Adversarial',overall:'Overall'})[String(value)]||String(value);}
async function pollBenchmark(){
    clearTimeout(pollTimer);
    if(importedBenchmark)return;
    const requestedRun=runId;
    try{
        const result=await jsonRequest(`/api/benchmarks/${requestedRun}`);
        if(importedBenchmark||requestedRun!==runId)return;
        benchmark=result;const running=['queued','running'].includes(benchmark.status);$('resultsFile').disabled=running;
        $('benchmarkSetup').hidden=true;$('benchmarkRunning').hidden=!running;$('benchmarkReport').hidden=running;
        const progress=benchmark.progress||{completed:0,total:0},percent=progress.total?Math.round(100*progress.completed/progress.total):0;
        $('progressBar').style.width=`${percent}%`;$('progressCount').textContent=`${progress.completed} / ${progress.total} questions`;
        $('progressTitle').textContent=benchmark.status==='queued'?'Preparing your run':'Evaluating answers and judge scores';
        $('progressDetail').textContent=`${benchmark.config.modules[0].replaceAll('_',' ')} · ${percent}% complete`;
        $('reportTitle').textContent=benchmark.status==='completed'?'Run complete':benchmark.status==='cancelled'?'Run cancelled · partial results':'Run report';
        $('reportSubtitle').textContent=`${benchmark.status} · ${progress.completed} of ${progress.total} questions processed`;
        $('reportStatus').textContent=benchmark.error?displayFailure(benchmark.error):'';
        $('resumeBenchmark').disabled=running;
        $('resumeBenchmark').hidden=benchmark.status==='completed'&&benchmark.cases.every(c=>c.correct!=null||c.diagnostics?.status==='context_limit_exceeded');
        $('exportReview').disabled=!benchmark.cases.some(c=>c.prediction!=null);$('reviewFile').disabled=!benchmark.cases.some(c=>c.prediction!=null);
        if(running){pollTimer=setTimeout(pollBenchmark,1200);}else drawBenchmark();
    }catch(error){if(importedBenchmark||requestedRun!==runId)return;$('resultsFile').disabled=false;$('benchmarkRunning').hidden=true;$('benchmarkSetup').hidden=false;if(error.status===404){localStorage.removeItem('kai3-benchmark-run');runId=null;$('benchmarkStatus').textContent='That saved run is no longer available. Start a new benchmark; completed runs are now saved across server restarts.';}else{$('benchmarkStatus').textContent=error.message;}}
}
function metricCard(label,value,note){const card=document.createElement('article');card.className='metric-card';const name=document.createElement('span');name.textContent=label;const number=document.createElement('strong');number.textContent=typeof value==='number'?value.toFixed(3):String(value??'—');const hint=document.createElement('small');hint.textContent=note;card.append(name,number,hint);return card;}
function detailRow(label,value,parent){const row=document.createElement('div');row.className='case-detail-row';const name=document.createElement('strong');name.textContent=label;const content=document.createElement('div');content.textContent=value==null||value===''?'—':typeof value==='string'?value:JSON.stringify(value,null,2);row.append(name,content);parent.append(row);}
function displayFailure(error){const text=String(error||'');if(/(?:Error code:\s*402\b|insufficient balance)/i.test(text))return 'DeepSeek account balance is exhausted. Top up the account, then resume unfinished work. Saved answers are retained.';if(/(?:Error code:\s*401\b|authentication fails|authentication_error|invalid.*api key)/i.test(text))return 'DeepSeek rejected the configured API key. Check DEEPSEEK_API_KEY in src/.env, restart KAI3, then resume unfinished work.';if(/Error code:\s*429\b/i.test(text))return 'DeepSeek rate limit persisted after retries. Resume unfinished work later.';return text||'The answer request failed. See technical diagnostics for details.';}

function drawBenchmark(){
    const body=$('benchmarkResults');body.replaceChildren();const overall=(benchmark.scores||[]).find(s=>s.category==='overall')||{};
    const metrics=document.createElement('div');metrics.className='metric-grid';
    metrics.append(metricCard('LoCoMo score',overall.mean_qa_score,`${overall.answer_count||0} answers scored`),metricCard('Exact match',overall.mean_exact_match,'Normalized reference match'),metricCard('Token F1',overall.mean_token_f1,'Stemmed token overlap'),metricCard('Accuracy',overall.accuracy,overall.accuracy==null?'Unavailable in this export':`${overall.correct_count??0} / ${overall.scored_count??0} correct ? ${overall.unscored_count??0} unscored`),metricCard('Judge rubric',overall.mean_judge,'Saved 0?2 diagnostic rating'));body.append(metrics);
    const summary=document.createElement('section');summary.className='report-section';const title=document.createElement('h3');title.textContent='Scores by category';summary.append(title);
    const table=document.createElement('table');table.className='report-table';table.innerHTML='<thead><tr><th>Category</th><th>LoCoMo score</th><th>Exact match</th><th>Token F1</th><th>Accuracy</th><th>Judge rubric</th><th>Answered / judged</th></tr></thead>';
    const rows=document.createElement('tbody');(benchmark.scores||[]).filter(s=>s.category!=='overall').forEach(s=>{const tr=document.createElement('tr');[`${categoryName(s.category)} · ${s.category}`,s.mean_qa_score,s.mean_exact_match,s.mean_token_f1,s.accuracy,s.mean_judge,`${s.answer_count??'?'} / ${s.judge_count??'?'}`].forEach((v,i)=>{const td=document.createElement('td');td.textContent=typeof v==='number'?v.toFixed(3):String(v??'—');tr.append(td);});rows.append(tr);});table.append(rows);summary.append(table);body.append(summary);
    const efficiency=(benchmark.efficiency||[])[0];
    if(efficiency){const section=document.createElement('section');section.className='report-section';const title=document.createElement('h3');title.textContent='Memory efficiency and latency';section.append(title);[['Evidence recall',efficiency.mean_evidence_recall],['Evidence cases',efficiency.evidence_count],['Mean retrieved token budget (conservative)',efficiency.mean_retrieved_token_budget],['Mean retrieval seconds',efficiency.mean_retrieval_seconds],['Mean answer seconds',efficiency.mean_answer_seconds]].forEach(([k,v])=>addField(section,k,v??'Unavailable'));(benchmark.memories||[]).forEach(m=>{addField(section,`Conversation ${m.sample_id} ? final storage`,m.ingestion.final_storage);addField(section,`Conversation ${m.sample_id} ? ingestion seconds`,m.ingestion.total_seconds);});body.append(section);}
    const config=document.createElement('section');config.className='report-section report-config';const configTitle=document.createElement('h3');configTitle.textContent='Run configuration';config.append(configTitle);const configGrid=document.createElement('div');configGrid.className='config-grid';
    [['Architecture',benchmark.config.modules?.[0]],['Conversations',benchmark.config.sample_ids?.join(', ')],['Categories',(benchmark.config.categories||[]).map(categoryName).join(', ')],['Question limit',benchmark.config.question_limit===0?'All matching questions':benchmark.config.question_limit],['No-memory input',benchmark.config.no_memory_context],['Answer model',benchmark.answer_model],['Judge model',benchmark.judge_model]].forEach(([k,v])=>addField(configGrid,k,v??'—'));config.append(configGrid);body.append(config);
    const calibration=document.createElement('section');calibration.className='report-section calibration-panel';const calibrationTitle=document.createElement('h3');calibrationTitle.textContent='Human calibration';calibration.append(calibrationTitle);const calibrationText=document.createElement('p');calibrationText.textContent=benchmark.calibration?`${benchmark.calibration.status} · ${benchmark.calibration.reviewed_count} cases reviewed · agreement by rubric dimension`:'Uncalibrated · export a sample, add 0–2 rubric ratings, then import it.';calibration.append(calibrationText);if(benchmark.calibration)addField(calibration,'Agreement',benchmark.calibration.agreement);body.append(calibration);
    (benchmark.errors||[]).forEach(error=>addCard(body,'Run error',error));
    const cases=document.createElement('section');cases.className='report-section';const casesTitle=document.createElement('h3');casesTitle.textContent='Question results';cases.append(casesTitle);
    const filterBar=document.createElement('div');filterBar.className='case-filters';const categoryFilter=document.createElement('select');categoryFilter.id='caseCategoryFilter';categoryFilter.innerHTML='<option value="all">All categories</option>'+[1,2,3,4,5].map(c=>`<option value="${c}">${categoryName(c)}</option>`).join('');
    const statusFilter=document.createElement('select');statusFilter.id='caseStatusFilter';statusFilter.innerHTML='<option value="all">All statuses</option><option value="answered">Answered</option><option value="failed">Failed</option><option value="judge-error">Judge error</option><option value="uncertain">Judge uncertain</option>';
    filterBar.append(categoryFilter,statusFilter);cases.append(filterBar);const list=document.createElement('div');list.className='case-list';cases.append(list);body.append(cases);
    function renderCases(){list.replaceChildren();const selectedCategory=categoryFilter.value,selectedStatus=statusFilter.value;
        benchmark.cases.filter(c=>(selectedCategory==='all'||String(c.category)===selectedCategory)&&(selectedStatus==='all'||(selectedStatus==='answered'?!!c.prediction:selectedStatus==='failed'?!!c.error:selectedStatus==='judge-error'?!!c.judge_error:!!c.judge?.uncertain))).forEach(c=>{
            const item=document.createElement('details');item.className='question-item';const head=document.createElement('summary');const question=document.createElement('span');question.textContent=c.question;const badge=document.createElement('small');badge.textContent=`${categoryName(c.category)} · Q${c.question_index+1}`;const score=document.createElement('b');score.textContent=c.error?'Failed':`F1 ${c.token_f1==null?'Unavailable':c.token_f1.toFixed(2)} · Judge ${c.judge?.overall??'—'}`;head.append(badge,question,score);item.append(head);
            const detail=document.createElement('div');detail.className='question-detail';
            if(c.error){const failure=document.createElement('div');failure.className='case-error';failure.textContent=displayFailure(c.error);detail.append(failure);}
            detailRow('Reference answer',c.answer,detail);detailRow('Prediction',c.prediction,detail);detailRow('LoCoMo score',c.score,detail);detailRow('Exact match',c.exact_match,detail);detailRow('Token F1',c.token_f1,detail);
            if(c.judge)detailRow('Judge assessment',c.judge,detail);else detailRow('Judge assessment',c.error?'Not run because answer generation failed.':'Not available',detail);
            if(c.judge_error)detailRow('Judge error',displayFailure(c.judge_error),detail);
            if(c.human_review)detailRow('Human review',c.human_review,detail);
            detailRow('Evidence recall',c.evidence_recall,detail);
            const evidence=document.createElement('details');evidence.className='case-evidence';const evidenceTitle=document.createElement('summary');evidenceTitle.textContent=`Retrieved evidence · ${c.diagnostics?.retrieved?.length||0} records`;evidence.append(evidenceTitle);
            (c.diagnostics?.retrieved||[]).forEach((entry,i)=>{const record=document.createElement('article');record.className='evidence-record';const meta=entry.metadata||{};const h=document.createElement('strong');h.textContent=`${i+1}. ${meta.speaker||'Memory'} · ${meta.dialogue_id||meta.fact_id||''} · ${meta.timestamp||''}`;const p=document.createElement('p');p.textContent=entry.text||'';record.append(h,p);evidence.append(record);});detail.append(evidence);
            const timing={};for(const key of ['retrieval_seconds','answer_seconds','judge_seconds','total_seconds','answer_llm_calls','judge_llm_calls','answer_tokens','judge_tokens'])if(c.diagnostics?.[key]!==undefined)timing[key]=c.diagnostics[key];detailRow('Timing and tokens',timing,detail);
            const raw={...c.diagnostics};delete raw.retrieved;const technical=document.createElement('details');technical.className='technical-details';const technicalTitle=document.createElement('summary');technicalTitle.textContent='Technical diagnostics';const pre=document.createElement('pre');pre.textContent=JSON.stringify(raw,null,2);technical.append(technicalTitle,pre);detail.append(technical);
            item.append(detail);list.append(item);
        });if(!list.children.length)addCard(list,'No questions match these filters','Choose another category or status.');
    }
    categoryFilter.onchange=renderCases;statusFilter.onchange=renderCases;renderCases();
    const memories=benchmark.memories||[];if(memories.length){const inspectButton=document.createElement('button');inspectButton.className='secondary-action';inspectButton.type='button';inspectButton.textContent='Inspect ingested memory';inspectButton.onclick=()=>{inspectionSource='benchmark';$('inspector').hidden=false;document.body.classList.add('memory-open');inspectBenchmark();};body.append(inspectButton);const select=document.createElement('select');select.id='benchmarkMemory';select.className='memory-run-select';memories.forEach((m,i)=>{const option=document.createElement('option');option.value=i;option.textContent=`${m.module} · ${m.sample_id}`;select.append(option);});select.onchange=inspectBenchmark;body.append(select);}
}
function inspectBenchmark(){const index=Number($('benchmarkMemory')?.value||0),memory=benchmark?.memories?.[index];if(!memory)return;const turns=benchmark.cases.filter(c=>c.module===memory.module&&c.sample_id===memory.sample_id).map(c=>c.diagnostics);setInspection({memory:memory.memory,turns,totals:{ingestion:memory.ingestion},benchmarkIndex:index},`${memory.module} · ${memory.sample_id}`);}
if(page==='chat'){save();render();refreshInspection();}
else{runId=localStorage.getItem('kai3-benchmark-run');loadDefaultDataset();if(runId)pollBenchmark();}
