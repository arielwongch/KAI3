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
}
const nodes={};
const document={getElementById:id=>nodes[id]??=new Node(),createElement:tag=>new Node(tag),querySelectorAll:()=>[],body:new Node()};
const marked={parse:text=>text};
const DOMPurify={sanitize:text=>'SANITIZED:'+text};
const navigator={clipboard:{writeText:async()=>{}}};
const setTimeout=()=>1,clearTimeout=()=>{};
let requests=[];
let responseHandler=()=>({status:404,data:{error:'Server memory is unavailable.'}});
const fetch=async(url,options)=>{requests.push({url,options});const r=responseHandler(url,options);return {ok:r.status<400,status:r.status,json:async()=>r.data};};
function descendants(node){return [node,...node.children.flatMap(descendants)];}
function text(node){return [node.textContent??'',...node.children.map(text)].join(' ');}
function byClass(root,name){return descendants(root).filter(n=>(n.className||'').split(' ').includes(name));}
`;

async function harness(seed={}){
    const context=vm.createContext({});
    const run=code=>vm.runInContext(code,context);
    run(stub.replace('SEED',JSON.stringify(seed)));
    run(source);
    await new Promise(setImmediate);
    return {run,async act(code){await run(code);await new Promise(setImmediate);}};
}

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
