const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');

const source = fs.readFileSync('src/workspace.js', 'utf8');
const stub = `
const storage = SEED;
const localStorage = {getItem:k=>storage[k]??null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]};
let serial=0;
const crypto={randomUUID:()=> 'uuid-'+(++serial)};
class Node {
    constructor(tag='div'){this.tag=tag;this.children=[];this.value='';this.disabled=false;this.hidden=false;this.style={};this.dataset={};this.classList={toggle(){},add(){},remove(){}};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=nodes;}
    querySelectorAll(){return [];}
    focus(){}
    click(){if(this.onclick)return this.onclick();}
    remove(){}
    showModal(){this.open=true;}
    close(){this.open=false;this.onclose?.();}
}
const nodes={};
const document={getElementById:id=>nodes[id]??=new Node(),createElement:tag=>new Node(tag),querySelector:()=>null,querySelectorAll:()=>[],body:new Node()};
const marked={parse:text=>text};
const DOMPurify={sanitize:text=>'SANITIZED:'+text};
const navigator={clipboard:{writeText:async()=>{}}};
const setTimeout=()=>1,clearTimeout=()=>{};
let requests=[];
let responseHandler=()=>({status:404,data:{error:'Server memory is unavailable.'}});
let fetch=async(url,options)=>{requests.push({url,options});const r=responseHandler(url,options);return {ok:r.status<400,status:r.status,json:async()=>r.data};};
function descendants(node){return [node,...node.children.flatMap(descendants)];}
function text(node){return [node.textContent??'',...node.children.map(text)].join(' ');}
function byClass(root,name){return descendants(root).filter(n=>(n.className||'').split(' ').includes(name));}
`;

async function harness(seed={},pathname='/chat'){
    const context=vm.createContext({location:{pathname}});
    const run=code=>vm.runInContext(code,context);
    run(stub.replace('SEED',JSON.stringify(seed)));
    run(source);
    await new Promise(setImmediate);
    return {run,async act(code){await run(code);await new Promise(setImmediate);}};
}

test('reranker benchmark settings keep shortlist separate and preserve drafts',async()=>{
    const {run}=await harness();
    run("updateMemorySettings('vector_store_reranker')");
    assert.equal(run("$('candidateKField').hidden"),false);
    assert.equal(run("benchmarkMemoryOptions('vector_store_reranker').candidate_k"),50);
    assert.equal(run("benchmarkMemoryOptions('vector_store_reranker').retrieval_k"),null);
    run("$('candidateK').value='all';$('retrievalK').value='7';updateMemorySettings('vector_store')");
    assert.equal(run("$('candidateKField').hidden"),true);
    assert.equal(run("'candidate_k' in benchmarkMemoryOptions('vector_store')"),false);
    run("updateMemorySettings('vector_store_reranker')");
    assert.equal(run("benchmarkMemoryOptions('vector_store_reranker').candidate_k"),null);
    assert.equal(run("benchmarkMemoryOptions('vector_store_reranker').retrieval_k"),7);
    run("$('candidateK').value='0'");
    assert.throws(()=>run("benchmarkMemoryOptions('vector_store_reranker')"));
    assert.equal(run("benchmarkConditionLabel({config:{modules:['vector_store_reranker']}})"),'Vector Store + Reranker');
});

test('reranker chat validates settings, sends them, and locks after first message',async()=>{
    const {run,act}=await harness();
    run("active().module='vector_store_reranker';render();$('userInput').value='Rome';$('chatCandidateK').value='0'");
    assert.equal(run("$('chatRerankerSettings').hidden"),false);
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("requests.filter(r=>r.url==='/get').length"),0);
    assert.match(run("$('chatRerankerError').textContent"),/positive integer/);
    run("$('chatCandidateK').value='all';$('chatRerankerCapacity').value='12';responseHandler=url=>({status:200,data:url==='/get'?{reply:'Remembered',turn_id:'t1'}:{memory:{entries:[]},turns:[],totals:{}}})");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("JSON.parse(requests.find(r=>r.url==='/get').options.body).memory_options.candidate_k"),null);
    assert.equal(run('active().memory_options.max_stored_entries'),12);
    assert.equal(run("$('chatRerankerSettings').hidden"),true);
});

test('hybrid settings retain drafts and validate component controls',async()=>{
    const {run}=await harness();
    run("updateMemorySettings('delta')");
    assert.equal(run("$('hybridSettings').hidden"),false);
    assert.equal(run("$('summaryTokensField').hidden"),false);
    run(`$('hybridShare').value='30';$('componentOptions').value='{"vector_store":{"retrieval_k":8,"max_stored_entries":null}}'`);
    assert.equal(run("benchmarkMemoryOptions('delta').hybrid_shares.summarization"),.3);
    assert.equal(run("benchmarkMemoryOptions('delta').component_options.vector_store.retrieval_k"),8);
    run("updateMemorySettings('zeta')");
    assert.equal(run("$('summaryTokensField').hidden"),true);
    assert.equal(run("'max_summary_tokens' in benchmarkMemoryOptions('zeta')"),false);
    run("updateMemorySettings('delta')");
    assert.equal(run("$('hybridShare').value"),'30');
    assert.equal(run("benchmarkMemoryOptions('delta').component_options.vector_store.retrieval_k"),8);
    assert.throws(()=>run("hybridFormOptions('delta','100','{}')"));
    assert.throws(()=>run(`hybridFormOptions('delta','50','{"fact_store":{}}')`));
    assert.throws(()=>run(`hybridFormOptions('delta','50','{"vector_store":{"retrieval_k":true}}')`));
    run("updateMemorySettings('full_context')");
    assert.equal(run("$('hybridSettings').hidden"),true);
});

test('hybrid chat sends its fixed share and record settings',async()=>{
    const {run,act}=await harness();
    run("active().module='epsilon';render()");
    assert.equal(run("$('chatHybridSettings').hidden"),false);
    run(`$('chatHybridShare').value='40';$('chatHybridBudget').value='500';$('chatComponentOptions').value='{"fact_store":{"retrieval_k":3}}';$('userInput').value='Remember Rome';responseHandler=url=>({status:200,data:url==='/get'?{reply:'Remembered',turn_id:'t1'}:{memory:{entries:[]},turns:[],totals:{}}})`);
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("JSON.parse(requests.find(r=>r.url==='/get').options.body).memory_options.hybrid_shares.summarization"),.4);
    assert.equal(run("active().memory_options.component_options.fact_store.retrieval_k"),3);
    assert.equal(run("$('chatHybridSettings').hidden"),true);
});

test('history migration, restart blocking, and safe user text',async()=>{
    const {run,act}=await harness({'kai3-chat-history':JSON.stringify([{role:'user',content:'<script>bad</script>'}]),'kai3-chat-id':'legacy','kai3-memory-module':'sliding_window'});
    assert.equal(run('workspace.version'),1);
    assert.equal(run('active().id'),'legacy');
    assert.equal(run('unavailable'),true);
    assert.equal(run("$('sendButton').disabled"),true);
    assert.equal(run("byClass($('chatMessages'),'message-body')[0].textContent"),'<script>bad</script>');
    assert.equal(run("byClass($('chatMessages'),'message-body')[0].innerHTML"),undefined);
    await act("$('newChat').onclick()");
    assert.equal(run('workspace.sessions.length'),2);
    assert.equal(run('unavailable'),false);
    await act("workspace.active='legacy';render();refreshInspection()");
    assert.equal(run('unavailable'),true);
});

test('current inspector displays records, retrieval, and metrics safely',async()=>{
    const {run,act}=await harness();
    assert.equal(run('unavailable'),false);
    run("active().module='sliding_window';render()");
    assert.equal(run("$('sendButton').disabled"),false);
    await act(`responseHandler=()=>({status:200,data:{memory:{config:{max_items:10},entries:[{text:'<script>x</script>',metadata:{}}]},turns:[{query:'Q',status:'completed',retrieved:[],agent_tokens:7}],totals:{agent_tokens:7}}});refreshInspection()`);
    assert.equal(run("$('recordCount').textContent"),1);
    assert.match(run("text(byClass($('inspectionBody'),'record-detail')[0])"),/<script>x<\/script>/);
    assert.equal(run("descendants($('inspectionBody')).some(n=>n.innerHTML?.includes('<script>x</script>'))"),false);
    run("inspectionTab='retrieved';drawInspection()");
    assert.match(run("text($('inspectionBody'))"),/No context retrieved/);
    assert.match(run("text(byClass($('inspectionBody'),'retrieved-header')[0])"),/Q.*completed/);
    run("inspectionTab='metrics';drawInspection()");
    assert.match(run("text(byClass($('inspectionBody'),'metrics-section')[0])"),/Session totals.*agent tokens.*7/);
});

test('invalid saved JSON is recoverable',async()=>{
    const {run}=await harness({'kai3-workspace-v1':'invalid JSON','kai3-chat-history':'broken'});
    assert.equal(run('workspace.sessions.length'),1);
    assert.equal(run('active().messages.length'),0);
});

test('failed turns refresh diagnostics and require existing memory',async()=>{
    const {run,act}=await harness({'kai3-workspace-v1':JSON.stringify({version:1,active:'old',sessions:[{id:'old',title:'old',module:'sliding_window',messages:[],started:true}]})});
    await act("unavailable=false;checking=false;controlState();$('userInput').value='test';$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run('unavailable'),true);
    assert.match(run('active().messages[1].content'),/Request failed/);
    assert.equal(run("JSON.parse(requests.find(r=>r.url==='/get').options.body).requires_existing"),true);
    assert.match(run('requests.at(-1).url'),/diagnostics$/);
});

test('resume uses server input for both thread and detached runs',async()=>{
    for(const worker of [null,{mode:'detached'}]){
        const {run,act}=await harness();
        run(`runId='saved';benchmark={worker:${JSON.stringify(worker)}};previewDataset=[{sample_id:'unrelated bundled dataset'}];requests=[];responseHandler=()=>({status:503,data:{error:'test stop'}})`);
        await act("$('resumeBenchmark').onclick()");
        assert.equal(run('requests[0].url'),'/api/benchmarks/saved/resume');
        assert.equal(run('requests[0].options.body'),'{}');
    }
});

test('resume requests an upload only when the server needs the original',async()=>{
    const {run,act}=await harness();
    run("runId='saved';benchmark={};$('resumeDatasetControl').hidden=true;responseHandler=()=>({status:503,data:{error:'temporary failure'}})");
    await act("$('resumeBenchmark').onclick()");
    assert.equal(run("$('resumeDatasetControl').hidden"),true);
    run("responseHandler=()=>({status:409,data:{code:'dataset_required',error:'Upload the original dataset.'}})");
    await act("$('resumeBenchmark').onclick()");
    assert.equal(run("$('resumeDatasetControl').hidden"),false);
    assert.match(run("$('reportStatus').textContent"),/Upload the original/);
    run(`$('resumeDatasetFile').files=[{text:async()=>JSON.stringify([{sample_id:'original'}])}];requests=[];responseHandler=url=>url.endsWith('/resume')?{status:202,data:{run_id:'saved'}}:{status:404,data:{error:'poll stopped'}}`);
    await act("$('resumeDatasetFile').onchange()");
    assert.equal(run('requests[0].options.body'),'{"dataset":[{"sample_id":"original"}]}');
    assert.equal(run("$('resumeDatasetControl').hidden"),true);
});

test('invalid upload preserves the report and does not submit a resume',async()=>{
    const {run,act}=await harness();
    run("runId='saved';benchmark={};requests=[];$('resumeDatasetFile').files=[{text:async()=>'{invalid'}]");
    await act("$('resumeDatasetFile').onchange()");
    assert.equal(run('requests.length'),0);
    assert.equal(run('runId'),'saved');
    assert.match(run("$('reportStatus').textContent"),/Could not read the original dataset/);
});

test('an upload finishing after switching runs cannot resume the wrong run',async()=>{
    const {run,act}=await harness();
    run("runId='old';benchmark={};requests=[];let finishRead;$('resumeDatasetFile').files=[{text:()=>new Promise(resolve=>finishRead=resolve)}];let upload=$('resumeDatasetFile').onchange();runId='new';finishRead('[]')");
    await act('upload');
    assert.equal(run('requests.length'),0);
});


test('window hybrid chat validates, persists, sends and locks its recent window',async()=>{
    const {run,act}=await harness();
    run("active().module='alpha';render();$('chatWindowSize').value='';$('chatWindowSize').oninput()");
    assert.equal(run("$('sendButton').disabled"),true);
    run("$('chatWindowSize').value='3';$('chatWindowSize').oninput()");
    assert.equal(run("$('sendButton').disabled"),false);
    assert.equal(run("JSON.parse(storage[key]).sessions[0].window_size"),3);
    run("responseHandler=url=>({status:200,data:url==='/get'?{reply:'ok'}:{window_size:3,memory:{entries:[]},turns:[]}});$('userInput').value='hello'");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("JSON.parse(requests.find(r=>r.url==='/get').options.body).window_size"),3);
    assert.equal(run("$('chatWindowSize').disabled"),true);
    run("$('chatWindowSize').value='9';$('chatWindowSize').oninput()");
    assert.equal(run('active().window_size'),3);
});

test('window hybrid benchmark settings coexist with the existing hybrid controls',async()=>{
    const {run}=await harness();
    run("updateMemorySettings('beta');$('benchmarkWindowSize').value='7'");
    assert.equal(run("$('benchmarkWindowControl').hidden"),false);
    assert.equal(run("$('hybridSettings').hidden"),true);
    assert.equal(run("benchmarkMemoryOptions('beta').window_size"),7);
    assert.equal(run("benchmarkMemoryOptions('beta').retrieval_k"),null);
    assert.equal(run("benchmarkMemoryOptions('beta').max_stored_entries"),null);
    run("updateMemorySettings('alpha')");
    assert.equal(run("'max_stored_entries' in benchmarkMemoryOptions('alpha')"),false);
    assert.equal(run("benchmarkMemoryOptions('alpha').max_summary_tokens"),2000);
    run("updateMemorySettings('delta')");
    assert.equal(run("$('benchmarkWindowControl').hidden"),true);
    assert.equal(run("'window_size' in benchmarkMemoryOptions('delta')"),false);
    assert.equal(run("$('hybridSettings').hidden"),false);
});


test('periodic modes share one window and interval setting and expose only applicable controls',async()=>{
    const {run}=await harness();
    for(const mode of ['windowed_summarization','windowed_fact_store']){
        run(`updateMemorySettings('${mode}');$('benchmarkWindowSize').value='13'`);
        assert.equal(run("$('benchmarkWindowControl').hidden"),false);
        assert.equal(run(`benchmarkMemoryOptions('${mode}').window_size`),13);
        assert.equal(run("$('summaryTokensField').hidden"),mode!=='windowed_summarization');
        assert.equal(run("$('candidateKField').hidden"),mode!=='windowed_fact_store');
        assert.equal(run("$('retrievalKField').hidden"),mode!=='windowed_fact_store');
        run(`active().module='${mode}';render()`);
        assert.equal(run("$('chatWindowControl').hidden"),false);
        assert.match(run("$('chatWindowDescription').textContent"),/every k completed entries/);
    }
});

test('all embedded retrieval modes expose candidate limits; standalone vector remains cosine only',async()=>{
    const {run}=await harness();
    run("$('benchmarkWindowSize').value='100'");
    for(const mode of ['fact_store','beta','gamma','delta','epsilon','zeta','windowed_fact_store']){
        run(`updateMemorySettings('${mode}')`);
        assert.equal(run("$('candidateKField').hidden"),false);
        assert.equal(run(`benchmarkMemoryOptions('${mode}').candidate_k`),50);
    }
    run("updateMemorySettings('zeta');$('componentOptions').value=JSON.stringify({fact_store:{candidate_k:9}})");
    assert.equal(run("benchmarkMemoryOptions('zeta').component_options.fact_store.candidate_k"),9);
    run("updateMemorySettings('vector_store')");
    assert.equal(run("$('candidateKField').hidden"),true);
});


test('saved-run delete requires confirmation and protects active runs',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("requests=[];responseHandler=()=>({status:200,data:{runs:[{run_id:'done',module:'fact_store',status:'completed',deletable:true},{run_id:'active',module:'vector_store',status:'running',deletable:false}]}})");
    await act('refreshSavedRuns()');
    assert.equal(run("byClass($('savedRuns'),'delete-run').length"),2);
    assert.equal(run("byClass($('savedRuns'),'delete-run')[1].disabled"),true);
    run("byClass($('savedRuns'),'delete-run')[0].onclick()");
    assert.equal(run("$('benchmarkDeleteDialog').open"),true);
    assert.match(run("$('benchmarkDeleteName').textContent"),/done/);
    assert.equal(run("requests.filter(r=>r.options?.method==='DELETE').length"),0);
    run("$('benchmarkDeleteCancel').onclick()");
    await act("$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run("requests.filter(r=>r.options?.method==='DELETE').length"),0);
});

test('deleting the open saved run resets report, storage, inspector and list',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("runId='done';storage['kai3-benchmark-run']='done';benchmark={status:'completed'};inspectionSource='benchmark';inspection={memory:{entries:[]}};responseHandler=(url,options)=>({status:200,data:options?.method==='DELETE'?{deleted:'done'}:{runs:[]}});benchmarkDeleteTarget='done';$('benchmarkDeleteDialog').showModal();requests=[]");
    await act("$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run('requests[0].url'),'/api/benchmarks/done');
    assert.equal(run('requests[0].options.method'),'DELETE');
    assert.equal(run('runId'),null);
    assert.equal(run('benchmark'),null);
    assert.equal(run("storage['kai3-benchmark-run']"),undefined);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
    assert.equal(run("$('resultsFile').disabled"),false);
    assert.equal(run("$('inspector').hidden"),true);
    assert.equal(run("$('benchmarkDeleteDialog').open"),false);
    assert.match(run("$('savedRunStatus').textContent"),/deleted/);
});

test('deleting another run preserves the current report; failed deletion is retryable',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("runId='current';benchmark={status:'completed',marker:'keep'};benchmarkDeleteTarget='other';$('benchmarkDeleteDialog').showModal();responseHandler=()=>({status:409,data:{error:'Worker is still finishing'}})");
    await act("$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run('runId'),'current');
    assert.equal(run('benchmark.marker'),'keep');
    assert.equal(run("$('benchmarkDeleteDialog').open"),true);
    assert.match(run("$('benchmarkDeleteError').textContent"),/still finishing/);
    assert.equal(run("$('benchmarkDeleteConfirm').disabled"),false);
    run("responseHandler=()=>({status:200,data:{runs:[]}})");
    await act("$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run('runId'),'current');
    assert.equal(run('benchmark.marker'),'keep');
});

test('pending deletion blocks duplicate submission and dialog dismissal',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("benchmarkDeleteTarget='done';$('benchmarkDeleteDialog').showModal();let releaseDelete,deleteCalls=0;const normalFetch=fetch;fetch=(url,options)=>{if(options?.method==='DELETE'){deleteCalls++;return new Promise(resolve=>releaseDelete=()=>resolve({ok:true,status:200,json:async()=>({deleted:'done'})}));}return normalFetch(url,options);};responseHandler=()=>({status:200,data:{runs:[]}});let deleting=$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run('benchmarkDeleteBusy'),true);
    run("let prevented=false;$('benchmarkDeleteDialog').oncancel({preventDefault(){prevented=true}})");
    assert.equal(run('prevented'),true);
    run("$('benchmarkDeleteCancel').onclick()");
    assert.equal(run("$('benchmarkDeleteDialog').open"),true);
    await act("$('benchmarkDeleteForm').onsubmit({preventDefault(){}})");
    assert.equal(run('deleteCalls'),1);
    run('releaseDelete()');await act('deleting');
    assert.equal(run('benchmarkDeleteBusy'),false);
});
