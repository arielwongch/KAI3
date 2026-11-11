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
    constructor(tag='div'){this.tag=tag;this.children=[];this.attrs={};this.value='';this.disabled=false;this.hidden=false;this.style={};this.dataset={};this.classList={toggle:(name,on)=>{const names=new Set((this.className||'').split(' ').filter(Boolean));if(on??!names.has(name))names.add(name);else names.delete(name);this.className=[...names].join(' ');},add:name=>this.classList.toggle(name,true),remove:name=>this.classList.toggle(name,false)};}
    setAttribute(key,value){this.attrs[key]=value;}
    getAttribute(key){return this.attrs[key]??null;}
    removeAttribute(key){delete this.attrs[key];}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=nodes;}
    querySelectorAll(){return [];}
    querySelector(selector){return descendants(this).find(n=>(n.className||'').split(' ').includes(selector.slice(1)))||null;}
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
const timeoutCalls=[];
const setTimeout=(fn,delay)=>{timeoutCalls.push({fn,delay});return 1;},clearTimeout=()=>{};
let requests=[];
let responseHandler=()=>({status:404,data:{error:'Server memory is unavailable.'}});
let fetch=async(url,options)=>{requests.push({url,options});const r=await responseHandler(url,options);return {ok:r.status<400,status:r.status,json:async()=>r.data};};
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

test('saved-run sidebar identifies configurations without opening reports',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run('requests=[]');
    run(`responseHandler=()=>({status:200,data:{runs:[
        {run_id:'first',module:'delta',status:'completed',config:{modules:['delta'],retrieval_k:20,candidate_k:null,memory_context_tokens:4096,question_limit:0,component_options:{vector_store:{retrieval_k:7}}}},
        {run_id:'second',module:'compaction',status:'completed',config:{modules:['compaction'],retain_percent:33.3,compaction_mode:'one_shot'}},
        {run_id:'legacy',module:'vector_store',status:'completed'}
    ]}})`);
    await act('refreshSavedRuns()');
    assert.match(run("text(byClass($('savedRuns'),'saved-run-open')[0])"),/k: 20 · Candidates: All · Context: 4096/);
    assert.match(run("text(byClass($('savedRuns'),'saved-run-config')[0])"),/question limit 0/);
    assert.match(run("text(byClass($('savedRuns'),'saved-run-config')[0])"),/"retrieval_k":7/);
    assert.match(run("text(byClass($('savedRuns'),'saved-run-open')[1])"),/Compaction \| 33.3% \| one_shot/);
    assert.match(run("text(byClass($('savedRuns'),'saved-run-config')[2])"),/Configuration unavailable/);
    assert.equal(run("requests.filter(r=>r.url.startsWith('/api/benchmarks/')).length"),0);
    run("byClass($('savedRuns'),'saved-run-config')[0].open=true");
    await act('refreshSavedRuns(false)');
    assert.equal(run("byClass($('savedRuns'),'saved-run-config')[0].open"),true);
});

test('legacy history indexing shows loading and clears it when summaries arrive',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("responseHandler=()=>({status:200,data:{runs:[],loading:true}})");
    await act('refreshSavedRuns()');
    assert.match(run("text($('savedRuns'))"),/Loading saved benchmark history/);
    assert.match(run("$('savedRunStatus').textContent"),/Loading saved benchmark history/);
    assert.equal(run('savedRunsTimer'),1);
    run("responseHandler=()=>({status:200,data:{runs:[],loading:false}})");
    await act('refreshSavedRuns(false)');
    assert.equal(run("$('savedRunStatus').textContent"),'');
    assert.match(run("text($('savedRuns'))"),/Your benchmark runs will appear here/);
});

test('compaction benchmark accepts variable ratios and separates source, trigger and reader budgets',async()=>{
    const {run}=await harness();
    run("$('compactMode').value='one_shot';$('compactPercent').value='33.3';$('compactTrigger').value='1000';$('compactSourceEntries').value='50';updateMemorySettings('compaction')");
    assert.equal(run("$('compactionSettings').hidden"),false);
    assert.equal(run("$('summaryTokensField').hidden"),true);
    assert.equal(run("$('retrievalKField').hidden"),true);
    assert.equal(run("benchmarkMemoryOptions('compaction').retain_percent"),33.3);
    assert.equal(run("benchmarkMemoryOptions('compaction').compaction_source_entries"),50);
    run("$('compactMode').value='repeated';updateMemorySettings('compaction')");
    assert.equal(run("'compaction_source_entries' in benchmarkMemoryOptions('compaction')"),false);
    assert.equal(run("benchmarkMemoryOptions('compaction').compaction_trigger_tokens"),1000);
    run("$('compactPercent').value='0'");
    assert.throws(()=>run("benchmarkMemoryOptions('compaction')"));
});

test('compaction chat sends fixed settings and manual action uses an independent percentage',async()=>{
    const {run,act}=await harness();
    run("active().module='compaction';render();$('chatCompactPercent').value='35';$('chatCompactTrigger').value='500';$('chatCompactBudget').value='800';$('userInput').value='remember this';responseHandler=()=>({status:200,data:{reply:'ok'}})");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("JSON.parse(requests.find(r=>r.url==='/get').options.body).memory_options.retain_percent"),35);
    assert.equal(run("$('chatCompactPercent').disabled"),true);
    run("unavailable=false;$('chatManualPercent').value='12.5';responseHandler=url=>url.endsWith('/compact')?{status:200,data:{event:{before_tokens:100,after_tokens:10,actual_retain_percent:10}}}:{status:200,data:{memory:{entries:[]},turns:[]}}");
    await act("$('compactChat').onclick()");
    assert.equal(run("JSON.parse(requests.find(r=>r.url.endsWith('/compact')).options.body).retain_percent"),12.5);
    assert.equal(run("active().memory_options.retain_percent"),35);
    assert.match(run("$('chatCompactionStatus').textContent"),/100.*10 tokens/);
});

test('compaction run stays on progress through temporary polling failures and recovers',async()=>{
    const {run,act}=await harness();
    run(`runId='compaction-run';$('benchmarkSetup').hidden=true;$('benchmarkRunning').hidden=false;
        responseHandler=()=>({status:503,data:{error:'Checkpoint temporarily locked'}})`);
    await act('pollBenchmark()');
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.equal(run('runId'),'compaction-run');
    assert.equal(run('pollTimer'),1);
    assert.match(run("$('progressActivity').textContent"),/Retrying/);
    run(`responseHandler=url=>({status:200,data:url==='/api/benchmarks'?{runs:[]}:
        {run_id:'compaction-run',status:'running',config:{modules:['compaction']},
         progress:{completed:13,total:100,phase:'ingestion'},cases:[]}})`);
    await act('pollBenchmark()');
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.doesNotMatch(run("$('progressActivity').textContent"),/Retrying/);
    run("responseHandler=async()=>{throw new TypeError('Failed to fetch')}");
    await act('pollBenchmark()');
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.equal(run('benchmark.progress.completed'),13);
    assert.match(run("$('progressActivity').textContent"),/Failed to fetch.*Retrying/);
    await act("$('newBenchmarkRun').onclick()");
    assert.equal(run('runId'),null);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
});

test('each workspace bundles the shared helper without relying on a template script tag',()=>{
    const helper=fs.readFileSync('src/loading.js','utf8').replace(/\r\n/g,'\n').trim();
    for(const name of ['workspace.js','compare.js']){
        assert(fs.readFileSync('src/'+name,'utf8').replace(/\r\n/g,'\n').includes(helper),name+' must include the current shared helper');
    }
    const context=vm.createContext({});
    vm.runInContext(helper,context);
    const original=vm.runInContext('KAI3Loading',context);
    vm.runInContext(helper,context);
    assert.equal(vm.runInContext('KAI3Loading',context),original,'Cached pages may also load the standalone helper');
});

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

test('a rejected first request leaves memory settings and retry available',async()=>{
    const {run,act}=await harness();
    run("active().module='vector_store_reranker';render();$('userInput').value='hello';responseHandler=url=>url==='/get'?{status:400,data:{error:'Invalid settings'}}:{status:404,data:{error:'No memory'}}");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run('active().started'),false);
    assert.equal(run('unavailable'),false);
    assert.equal(run("$('sendButton').disabled"),false);
    assert.equal(run("$('chatRerankerSettings').hidden"),false);
    assert.equal(run('active().pending_request'),undefined);
});

test('uncertain first request retries the same ID without duplicating the user turn',async()=>{
    const {run,act}=await harness();
    run("active().module='sliding_window';render();$('userInput').value='hello';responseHandler=url=>{if(url==='/get')throw new Error('connection lost');return {status:404,data:{error:'No memory'}}}");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    const requestId=run('active().pending_request.payload.request_id');
    assert.equal(run('active().started'),false);
    assert.equal(run("$('sendButton').disabled"),false);
    run("$('userInput').value='hello';responseHandler=url=>url==='/get'?{status:200,data:{reply:'Tea',turn_id:'turn'}}:{status:200,data:{memory:{entries:[],config:{}},turns:[]}}");
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run("JSON.parse(requests.filter(r=>r.url==='/get').at(-1).options.body).request_id"),requestId);
    assert.equal(run("active().messages.filter(m=>m.role==='user').length"),1);
    assert.equal(run('active().pending_request'),undefined);
});

test('lost reply is recovered from turn diagnostics and failed memory has a write-only retry',async()=>{
    const {run,act}=await harness();
    run(`active().module='sliding_window';render();$('userInput').value='hello';
        responseHandler=url=>{if(url==='/get')throw new Error('reply lost');return {status:200,data:{memory:{entries:[],config:{}},turns:[{request_id:active().pending_request.payload.request_id,turn_id:'paid',final_answer:'Tea',memory_write_status:'failed',warning:'Memory offline'}]}}}`);
    await act("$('chatForm').onsubmit({preventDefault(){}})");
    assert.equal(run('active().started'),true);
    assert.equal(run('active().pending_request'),undefined);
    assert.equal(run('active().messages.at(-1).content'),'Tea');
    assert.equal(run("$('sendButton').disabled"),true);
    run("responseHandler=url=>url.endsWith('/retry-memory')?{status:200,data:{memory_write_status:'completed'}}:{status:200,data:{memory:{entries:[],config:{}},turns:[{turn_id:'paid',memory_write_status:'completed'}]}}");
    await act("descendants($('chatMessages')).find(n=>n.textContent==='Retry memory update').onclick()");
    assert.equal(run("requests.filter(r=>r.url==='/get').length"),1);
    assert.equal(run("requests.some(r=>r.url==='/api/chats/uuid-1/turns/paid/retry-memory')"),true);
    assert.equal(run("$('sendButton').disabled"),false);
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

test('resume blocks duplicate submissions and stays on progress through a polling failure',async()=>{
    const {run,act}=await harness();
    run(`runId='saved';benchmark={status:'failed'};requests=[];let finishResume;
        responseHandler=url=>url.endsWith('/resume')?new Promise(resolve=>finishResume=resolve):
            {status:503,data:{error:'Temporary status failure'}};
        let resuming=resumeSavedBenchmark()`);
    assert.equal(run("$('resumeBenchmark').disabled"),true);
    await act('resumeSavedBenchmark()');
    assert.equal(run("requests.filter(r=>r.url.endsWith('/resume')).length"),1);
    run("finishResume({status:202,data:{run_id:'saved'}})");
    await act('resuming');
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.match(run("$('progressActivity').textContent"),/Retrying/);
    assert.equal(run("$('resumeBenchmark').disabled"),true);
    await act('resumeSavedBenchmark()');
    assert.equal(run("requests.filter(r=>r.url.endsWith('/resume')).length"),1);
});

test('parallel limit is server-owned and progress shows active question count',async()=>{
    const {run,act}=await harness();
    run("runId='saved';benchmark={status:'failed'};requests=[];responseHandler=()=>({status:503,data:{error:'Test stop'}})");
    await act('resumeSavedBenchmark()');
    assert.equal(run('requests[0].options.body'),'{}');
    assert(!source.includes('questionWorkerCount'));
    const html=fs.readFileSync('src/index.html','utf8');
    assert(!html.includes('id="questionWorkers"'));
    assert(!html.includes('id="resumeQuestionWorkers"'));
    run("renderRunProgress({status:'running',config:{question_workers:8},progress:{phase:'questions',active_questions:[0,2],question_workers:8}})");
    assert.match(run("$('progressActivity').textContent"),/2 questions running.*8 in parallel/);
});

test('late resume response cannot reopen a run after switching away and back',async()=>{
    const {run,act}=await harness();
    run(`runId='saved';requests=[];let finishResume;responseHandler=()=>new Promise(resolve=>finishResume=resolve);
        let resuming=resumeSavedBenchmark();$('newBenchmarkRun').onclick();runId='saved';
        finishResume({status:202,data:{run_id:'saved'}})`);
    await act('resuming');
    assert.equal(run('requests.length'),1);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
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
    assert.equal(run("benchmarkMemoryOptions('alpha').max_summary_tokens"),8000);
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

test('overlapping requests retain their spinner until the last request finishes, including errors',async()=>{
    const {run,act}=await harness();
    run("let replies=[];responseHandler=()=>new Promise(resolve=>replies.push(resolve));let first=jsonRequest('/api/results'),second=jsonRequest('/api/results').catch(e=>e.message)");
    assert.equal(run("$('refreshResultLibrary').getAttribute('data-loading')"),'true');
    run("replies[0]({status:200,data:{files:[]}})");await act('first');
    assert.equal(run("$('refreshResultLibrary').getAttribute('data-loading')"),'true');
    run("replies[1]({status:503,data:{error:'Unavailable'}})");await act('second');
    assert.equal(run("$('refreshResultLibrary').getAttribute('data-loading')"),null);
    assert.equal(run("$('refreshResultLibrary').getAttribute('aria-busy')"),null);
});

const savedRunSetup = `
const savedList=[{run_id:'run-a',module:'vector_store',status:'running',deletable:false},{run_id:'run-b',module:'fact_store',status:'completed',deletable:true,resumable:true}];
let replies=[];
const snapshot=(id,phase='answer')=>({run_id:id,status:'running',config:{modules:['vector_store']},progress:{phase,completed:0,total:10},cases:[]});
responseHandler=url=>url==='/api/benchmarks'?{status:200,data:{runs:savedList}}:new Promise(resolve=>replies.push(resolve));
`;

test('saved run shows immediate loading then a persistent sidebar selection without poll flicker',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);await act('refreshSavedRuns()');
    run("let opening=openSavedRun('run-a')");
    assert.equal(run("byClass($('savedRuns'),'saved-run-state')[0].textContent"),'Loading…');
    assert.equal(run("byClass($('savedRuns'),'saved-run-state')[0].getAttribute('data-loading')"),'true');
    assert.equal(run("$('benchmarkLoadStatus').hidden"),false);
    assert.equal(run("$('benchmarkReport').hidden"),true);
    run("replies.shift()({status:200,data:snapshot('run-a')})");await act('opening');
    assert.equal(run("byClass($('savedRuns'),'selected')[0].dataset.runId"),'run-a');
    assert.equal(run("byClass($('savedRuns'),'saved-run-open')[0].getAttribute('aria-current')"),'true');
    assert.equal(run("byClass($('savedRuns'),'saved-run-state')[0].hidden"),true);
    assert.equal(run("$('benchmarkLoadStatus').hidden"),true);
    assert.equal(run("$('refreshRuns').getAttribute('data-loading')"),null);
    run('let poll=pollBenchmark()');
    assert.equal(run("byClass($('savedRuns'),'saved-run-state')[0].hidden"),true);
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),null);
    run("replies.shift()({status:200,data:snapshot('run-a','judge')})");await act('poll');
    await act('refreshSavedRuns()');
    assert.equal(run("byClass($('savedRuns'),'selected')[0].dataset.runId"),'run-a');
    run("$('newBenchmarkRun').onclick()");
    assert.equal(run("byClass($('savedRuns'),'selected').length"),0);
});

test('rapid A/B/A switching ignores stale responses even when the run ID matches again',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);await act('refreshSavedRuns()');
    run("let oldA=openSavedRun('run-a'),oldB=openSavedRun('run-b'),newA=openSavedRun('run-a')");
    run("replies[0]({status:200,data:snapshot('run-a','ingestion')})");await act('oldA');
    assert.equal(run('benchmark'),null);
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),'true');
    run("replies[2]({status:200,data:snapshot('run-a','judge')})");await act('newA');
    run("replies[1]({status:404,data:{error:'Old error'}})");await act('oldB');
    assert.equal(run('benchmark.progress.phase'),'judge');
    assert.equal(run('selectedRunId'),'run-a');
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),null);
    assert.equal(run("$('benchmarkSetup').hidden"),true);
});

test('reset during a saved-run load prevents the late response restoring the report',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);await act('refreshSavedRuns()');
    run("let opening=openSavedRun('run-a');$('newBenchmarkRun').onclick();replies.shift()({status:200,data:snapshot('run-a')})");
    await act('opening');
    assert.equal(run('runId'),null);
    assert.equal(run('benchmark'),null);
    assert.equal(run("$('benchmarkLoadStatus').hidden"),true);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
    assert.equal(run("byClass($('savedRuns'),'selected').length"),0);
});

test('failed saved-run loading keeps the selected run pending and never resumes another run',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);await act('refreshSavedRuns()');
    run("let resumes=0;$('resumeBenchmark').onclick=()=>resumes++;let opening=byClass($('savedRuns'),'saved-run-actions')[1].children[1].onclick();replies.shift()({status:503,data:{error:'Temporarily unavailable'}})");
    await act('opening');
    assert.equal(run('resumes'),0);
    assert.equal(run('selectedRunId'),null);
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),null);
    assert.equal(run("byClass($('savedRuns'),'saved-run-state')[1].hidden"),false);
    assert.match(run("$('benchmarkLoadStatus').textContent"),/Temporarily unavailable.*Retrying/);
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run('runId'),'run-b');
    assert.equal(run("storage['kai3-benchmark-run']"),'run-b');
});

test('transient legacy 404 during first load preserves run selection and recovers without setup',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);await act('refreshSavedRuns()');
    run("let opening=openSavedRun('run-a');replies.shift()({status:404,data:{error:'Benchmark run is unavailable.'}})");
    await act('opening');
    assert.equal(run('runId'),'run-a');
    assert.equal(run("storage['kai3-benchmark-run']"),'run-a');
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run("$('benchmarkLoadStatus').hidden"),false);
    assert.match(run("$('benchmarkLoadStatus').textContent"),/Retrying/);
    assert.equal(run('pollTimer'),1);
    run("let recovery=pollBenchmark();replies.shift()({status:200,data:snapshot('run-a')})");
    await act('recovery');
    assert.equal(run('selectedRunId'),'run-a');
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.equal(run('pollFailures'),0);
});

test('live-run 404s back off without losing progress and explicit reset stops late timers',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);
    run("let opening=openSavedRun('run-a');replies.shift()({status:200,data:snapshot('run-a','ingestion')})");
    await act('opening');
    run("responseHandler=()=>({status:404,data:{error:'Transient checkpoint miss'}})");
    const delays=[];
    for(let i=0;i<5;i++){
        await act('pollBenchmark()');
        delays.push(run('timeoutCalls.at(-1).delay'));
    }
    assert.deepEqual(delays,[2000,4000,8000,10000,10000]);
    assert.equal(run('benchmark.progress.phase'),'ingestion');
    assert.equal(run('selectedRunId'),'run-a');
    assert.equal(run("$('benchmarkRunning').hidden"),false);
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    run("$('newBenchmarkRun').onclick();requests=[]");
    await act('pollBenchmark()');
    assert.equal(run('requests.length'),0);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
});

test('confirmed missing run stops retrying but does not discard last report or navigate',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run(savedRunSetup);
    run("let opening=openSavedRun('run-a');replies.shift()({status:200,data:snapshot('run-a')})");
    await act('opening');
    run("$('benchmarkRunning').hidden=true;$('benchmarkReport').hidden=false;responseHandler=()=>({status:404,data:{code:'benchmark_not_found',retryable:false,error:'Choose another saved run or New benchmark.'}})");
    await act('pollBenchmark()');
    assert.equal(run('pollTimer'),null);
    assert.equal(run('runId'),'run-a');
    assert.equal(run("storage['kai3-benchmark-run']"),'run-a');
    assert.equal(run("$('benchmarkReport').hidden"),false);
    assert.equal(run("$('benchmarkSetup').hidden"),true);
    assert.match(run("$('reportStatus').textContent"),/Choose another/);
});

test('local file reads show an indicator and cannot reopen an import after reset',async()=>{
    const {run,act}=await harness({},'/benchmark');
    run("let finishRead;$('resultsFile').files=[{name:'report.json',text:()=>new Promise(resolve=>finishRead=resolve)}];let reading=$('resultsFile').onchange()");
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),'true');
    assert.equal(run("$('benchmarkLoadStatus').hidden"),false);
    run("$('newBenchmarkRun').onclick();finishRead(JSON.stringify({schema_version:1,cases:[]}))");await act('reading');
    assert.equal(run('importedBenchmark'),false);
    assert.equal(run("$('benchmarkSetup').hidden"),false);
    assert.equal(run("$('benchmarkLoadStatus').getAttribute('data-loading')"),null);
});

test('memory availability checks show a spinner and clean up after failure',async()=>{
    const {run,act}=await harness();
    run("let finishMemory;responseHandler=()=>new Promise(resolve=>finishMemory=resolve);let inspecting=refreshInspection()");
    assert.equal(run("$('moduleStatus').getAttribute('data-loading')"),'true');
    assert.equal(run("$('inspectionStatus').getAttribute('data-loading')"),'true');
    run("finishMemory({status:503,data:{error:'Memory unavailable'}})");await act('inspecting');
    assert.equal(run("$('moduleStatus').getAttribute('data-loading')"),null);
    assert.equal(run("$('inspectionStatus').getAttribute('data-loading')"),null);
});


test('completed reports distinguish failed ingestion including older saved runs',async()=>{
    const {run}=await harness({},'/benchmark');
    assert.equal(run("benchmarkStatusLabel({status:'completed',ingestion_outcome:{failed_conversations:2}})"),'Completed with ingestion errors');
    assert.equal(run("ingestionFailureCount({memories:[{module:'windowed_fact_store',sample_id:'conv-1',error:'bad batch'},{module:'windowed_fact_store',sample_id:'conv-1',error:'bad batch'}]})"),1);
    assert.equal(run("benchmarkStatusLabel({status:'completed',memories:[]})"),'completed');
});


test('live report does not turn unknown failed request usage into zero',async()=>{
    const {run}=await harness({},'/benchmark');
    assert.equal(run("recordedPhaseTokens({provider_requests:[{phase:'memory',status:'error',tokens:null},{phase:'memory',status:'completed',tokens:30}]},'memory')"),null);
    assert.equal(run("recordedPhaseTokens({provider_requests:[{phase:'memory',status:'error',tokens:5},{phase:'memory',status:'completed',tokens:30}]},'memory')"),35);
});

test('headline and lifecycle usage agree on duplicate ingestion provenance and ownership',async()=>{
    const {run}=await harness({},'/benchmark');
    run(`let accountingReport={config:{modules:['windowed_summarization']},
        cases:[{module:'windowed_summarization',sample_id:'a',diagnostics:{answer_tokens:10,judge_tokens:5}}],
        memories:[{module:'windowed_summarization',sample_id:'a',ingestion:{ingestion_id:'one',
            provider_requests:[{phase:'memory',status:'completed',tokens:20,response_id:'first'}]}}]};
        accountingReport.previous_ingestions=JSON.parse(JSON.stringify(accountingReport.memories));`);
    assert.equal(run('benchmarkTokenUsage(accountingReport).total'),30);
    assert.equal(run('benchmarkLifecycleUsage(accountingReport).totalTokens'),35);
    assert.equal(run('benchmarkLifecycleUsage(accountingReport).buildCount'),1);
    // Property order is irrelevant to duplicate identity.
    run("accountingReport.previous_ingestions[0].ingestion={provider_requests:accountingReport.previous_ingestions[0].ingestion.provider_requests,ingestion_id:'one'}");
    assert.equal(run('benchmarkTokenUsage(accountingReport).total'),30);
    run("accountingReport.previous_ingestions[0].ingestion.provider_requests[0].response_id='other'");
    assert.equal(run('benchmarkTokenUsage(accountingReport).total'),null);
    assert.equal(run('benchmarkLifecycleUsage(accountingReport).knownMemoryAnswerTokens'),null);
    run("accountingReport.previous_ingestions[0].ingestion.provider_requests[0].response_id='first';accountingReport.previous_ingestions[0].sample_id='b'");
    assert.equal(run('benchmarkTokenUsage(accountingReport).total'),null);
    assert.equal(run('benchmarkLifecycleUsage(accountingReport).knownTotalTokens'),null);
});
