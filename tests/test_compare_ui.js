const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Element {
    constructor(tag) { this.tag=tag;this.children=[];this.attrs={};this.style={};this.value='';this.textContent=''; }
    append(...items) { this.children.push(...items); }
    replaceChildren(...items) { this.children=items; }
    setAttribute(k,v) { this.attrs[k]=v; }
    getBoundingClientRect() { return {left:0,top:40,right:330,bottom:320,width:330,height:280}; }
    contains(target) { return this===target||this.children.some(c=>typeof c!=='string'&&c.contains(target)); }
    querySelectorAll(selector) { return this.children.filter(c=>typeof c!=='string').flatMap(c=>[...(selector.split(',').includes(c.tag)?[c]:[]),...c.querySelectorAll(selector)]); }
    click() { clicks.push(this); }
    focus() { this.focused=true; }
    select() { this.selectedText=true; }
    close() { this.open=false;this.onclose?.(); }
    showModal() { this.open=true; }
    get childElementCount() { return this.children.length; }
}
const elements = {};
const get = id => elements[id] ||= new Element('div');
const clicks=[],requests=[];
const documentEvents={},windowEvents={};
get('comparisonEmpty').append(new Element('span'),new Element('h3'),new Element('p'));
get('category').value='overall';get('headroom').value='10';
get('chartX').value='tokens';get('chartY').value='accuracy';get('tableSort').value='name';get('tableOrder').value='asc';
const overall = {accuracy_percent:80,mean_question_tokens:200,total_question_tokens:null,mean_question_seconds:2,total_question_seconds:null,stored_text_bytes:2048,judged_count:4,selected_count:5,token_count:4,runtime_count:3,case_count:5,storage_count:1,memory_count:1,completion_percent:80};
const temporal = {...overall,accuracy_percent:100,mean_question_tokens:100,mean_question_seconds:null,judged_count:1,selected_count:2,completion_percent:50};
const report = {comparison:{rows:[{module:'vector_store',overall,categories:{2:temporal}}]}};
const upload='uploads/0123456789abcdef0123456789abcdef/Trial (vector_k=10) 測試.json';
let library=['run.json',upload],failDelete=false,failDownload=false,failLoad=false,failRename=false;
const uploadResponses=[];
class FormData { constructor(){this.data=new Map();}append(key,value){this.data.set(key,value);}get(key){return this.data.get(key);} }
const resizeObservers=[];
class ResizeObserver {constructor(callback){this.callback=callback;resizeObservers.push(this);}observe(element){this.element=element;}}
const context = vm.createContext({ResizeObserver,document:{getElementById:get,createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag),createTextNode:text=>text,addEventListener:(name,handler)=>documentEvents[name]=handler},
    window:{innerWidth:1024,innerHeight:768,addEventListener:(name,handler)=>windowEvents[name]=handler},
    URL:{createObjectURL:()=> 'blob:selected',revokeObjectURL:()=>{}},setTimeout:fn=>fn(),FormData,
    fetch:async (url,options={})=>{requests.push({url,...options});if(url==='/api/results/import'){const response=uploadResponses.shift();assert(response,'Unexpected upload request');if(response.path&&!library.includes(response.path))library.push(response.path);return {ok:!response.error,status:response.error?409:response.replaced?200:201,json:async()=>response};}if(url==='/api/results/rename'){if(failRename)return {ok:false,status:409,json:async()=>({error:'Name already exists'})};const payload=JSON.parse(options.body),path=payload.path.slice(0,payload.path.lastIndexOf('/')+1)+payload.name;library=library.map(name=>name===payload.path?path:name);return {ok:true,json:async()=>({path})};}const failed=(options.method==='DELETE'&&failDelete)||(url.includes('&download=1')&&failDownload)||(url.includes('analysis=1')&&failLoad);return {ok:!failed,blob:async()=>({}),json:async()=>failed?{error:'Test failure'}:url==='/api/results'?{files:library}:{report}};}});
vm.runInContext(fs.readFileSync('src/compare.js','utf8'),context);
const evaluate = code => vm.runInContext(code,context);
(async()=>{
    await new Promise(setImmediate);
    assert.equal(get('library').children.length,2);
    assert.equal(get('downloadSelected').disabled,true);
    assert.equal(get('comparisonEmpty').hidden,false);
    assert.equal(get('library').children[0].children[1].children.length,2,'File cards contain only Rename and Delete');
    assert.equal(get('library').querySelectorAll('a').length,0,'Downloads are available only through Download selected');
    assert.equal(evaluate(`displayName(${JSON.stringify(upload)})`),'Trial (vector_k=10) 測試.json');
    assert.equal(evaluate("displayName('uploads/0123456789abcdef0123456789abcdef-old.json')"),'old.json');
    const checkbox=get('library').children[0].children[0].children[0];
    checkbox.checked=true;await checkbox.onchange();
    assert.equal(get('downloadSelected').disabled,false);
    assert.equal(get('comparisonEmpty').hidden,true);
    await get('downloadSelected').onclick();
    assert.equal(clicks.at(-1).download,'run.json');
    assert(requests.some(r=>r.url.includes('path=run.json&download=1')));
    assert.equal(get('charts').children.length,1);
    const svg=chart=>chart.children.find(c=>c.tag==='svg');
    const point=chart=>svg(chart).children.find(c=>c.tag==='g');
    const textContent=element=>[element.textContent,...element.children.map(c=>typeof c==='string'?c:textContent(c))].join(' ');
    const chooseAxes=(x,y)=>{get('chartX').value=x;get('chartY').value=y;get('chartX').onchange();assert.equal(get('charts').children.length,1);return get('charts').children[0];};
    let current=get('charts').children[0];
    assert.match(svg(current).attrs['aria-label'],/X: Tokens per question, axis from 0 to 250 tokens; Y: Judged accuracy, axis from 0 to 100 %/);
    assert.equal(svg(current).attrs.viewBox,undefined,'Text is not enlarged or shrunk by an SVG viewBox');
    const dots=chart=>svg(chart).querySelectorAll('circle').filter(c=>c.attrs.class==='chart-dot');
    assert.equal(dots(current).length,1);
    point(current).onpointerenter({clientX:1000,clientY:750});
    assert.equal(get('chartTooltip').hidden,false);
    assert.match(textContent(get('chartTooltip')),/Run 1.*run.json.*vector_store.*X · Tokens per question.*200 tokens.*Y · Judged accuracy.*80 %/);
    assert.match(textContent(get('chartTooltip')),/Cases with token usage.*4 \/ 5.*Total question tokens.*Unavailable.*Judged \/ selected.*4 \/ 5/);
    assert(Number.parseFloat(get('chartTooltip').style.left)+330<=1012);
    assert(Number.parseFloat(get('chartTooltip').style.top)+280<=756);
    point(current).onpointerleave();assert.equal(get('chartTooltip').hidden,true);
    context.document.activeElement=point(current);point(current).onfocus();point(current).onpointerleave();
    assert.equal(get('chartTooltip').hidden,false);
    point(current).onblur();assert.equal(get('chartTooltip').hidden,true);
    context.document.activeElement=null;point(current).onfocus();
    documentEvents.keydown({key:'Escape'});assert.equal(get('chartTooltip').hidden,true);
    overall.accuracy_percent=60;current=chooseAxes('tokens','accuracy');
    const originalX=Number(dots(current)[0].attrs.cx),originalY=Number(dots(current)[0].attrs.cy);
    current=chooseAxes('accuracy','tokens');
    assert(Number(dots(current)[0].attrs.cx)<originalX,'Changing X changes the horizontal coordinate');
    assert(Number(dots(current)[0].attrs.cy)<originalY,'Changing Y changes the vertical coordinate');
    overall.accuracy_percent=80;
    for(const x of ['accuracy','tokens','storage','runtime'])for(const y of ['accuracy','tokens','storage','runtime']){
        current=chooseAxes(x,y);assert.equal(dots(current).length,1);
        point(current).onfocus();assert.equal(get('chartTooltip').hidden,false);
    }
    current=chooseAxes('tokens','accuracy');
    get('headroom').value='30';get('headroom').onchange();
    assert.equal(get('chartTooltip').hidden,true);
    assert.match(svg(get('charts').children[0]).attrs['aria-label'],/axis from 0 to 300 tokens.*axis from 0 to 100 %/);
    resizeObservers[0].callback([{contentRect:{width:500}}]);
    assert.equal(get('charts').children.length,1,'Container resizes redraw the same scatter plot');
    get('category').value='2';get('category').onchange();
    assert.equal(evaluate('rows()[0].metrics.mean_question_tokens'),100);
    assert.equal(evaluate('rows()[0].overall.stored_text_bytes'),2048);
    current=chooseAxes('runtime','accuracy');
    assert.equal(dots(current).length,0,'Either missing axis value omits the dot');
    const missing=current.querySelectorAll('button')[0];assert(missing);
    missing.onfocus();assert.match(textContent(get('chartTooltip')),/Runtime per question.*Unavailable.*Judged accuracy.*100 %/);
    current=chooseAxes('storage','accuracy');point(current).onfocus();
    assert.match(textContent(get('chartTooltip')),/2 KiB.*All question types \(run total\).*Stored text bytes.*2,048.*Measured snapshots.*1 \/ 1/);
    assert.match(textContent(get('chartTooltip')),/Y · Question type.*Temporal/);
    windowEvents.scroll();assert.equal(get('chartTooltip').hidden,true);
    overall.stored_text_bytes=0;get('category').onchange();
    assert.equal(Number(dots(get('charts').children[0])[0].attrs.cx),60,'Zero is plotted at the horizontal origin');
    overall.stored_text_bytes=2048;
    current=chooseAxes('accuracy','tokens');
    point(current).onclick({clientX:40,clientY:60});assert.equal(get('chartTooltip').hidden,false);
    documentEvents.pointerdown({target:new Element('div')});assert.equal(get('chartTooltip').hidden,true);
    get('category').value='5';get('category').onchange();
    assert.equal(evaluate('rows()[0].metrics.accuracy_percent'),undefined);
    checkbox.checked=false;await checkbox.onchange();
    assert.equal(evaluate('rows().length'),0);
    assert.equal(get('save').disabled,true);
    get('search').value='(vector_k=10)';get('search').oninput();
    assert.equal(get('library').children.length,1);
    await get('selectVisible').onclick();
    assert.equal(evaluate('selected.size'),1,'Select visible respects search');
    get('search').value='';get('search').oninput();
    await get('selectVisible').onclick();
    assert.equal(evaluate('selected.size'),2);
    await get('downloadSelected').onclick();
    assert.deepEqual(clicks.slice(-2).map(link=>link.download).sort(),['Trial (vector_k=10) 測試.json','run.json'].sort());
    assert.equal(requests.some(r=>r.url==='/api/results/download'),false,'No ZIP request is made');
    failDownload=true;await get('downloadSelected').onclick();
    assert.match(get('status').textContent,/Requested 0 separate JSON.*Test failure/);
    assert.equal(get('downloadSelected').disabled,false);
    failDownload=false;
    const cardFor=path=>get('library').children.find(c=>c.attrs['data-path']===path);
    const remove=()=>cardFor(upload).children[1].children[1];
    remove().onclick();
    assert.equal(get('deleteDialog').open,true);
    assert.equal(get('cancelDelete').focused,true);
    get('deleteDialog').returnValue='cancel';await get('deleteDialog').onclose();
    assert.equal(evaluate('selected.size'),2,'Cancelling delete keeps selection');
    assert.equal(requests.filter(r=>r.method==='DELETE').length,0);
    failDelete=true;remove().onclick();get('deleteDialog').returnValue='delete';await get('deleteDialog').onclose();
    assert.equal(evaluate('selected.size'),2,'Failed deletion keeps selection');
    assert.equal(get('status').attrs['data-tone'],'error');
    remove().onclick();assert.equal(get('deleteDialog').returnValue,'','Reopening resets prior confirmation so Escape cannot delete');await get('deleteDialog').onclose();
    assert.equal(evaluate('selected.size'),2);
    failDelete=false;remove().onclick();get('deleteDialog').returnValue='delete';await get('deleteDialog').onclose();
    assert.equal(evaluate('selected.size'),1);
    assert.equal(get('library').children.length,1);
    assert.equal(evaluate(`loaded.has(${JSON.stringify(upload)})`),false);
    get('clearSelection').onclick();
    assert.equal(get('downloadSelected').disabled,true);
    library=['missing.json'];await get('refresh').onclick();failLoad=true;
    await get('selectVisible').onclick();
    assert.equal(evaluate('selected.size'),0);
    assert.equal(get('status').attrs['data-tone'],'error');
    assert.equal(get('selectVisible').disabled,false);
    failLoad=false;library=[upload];
    const conflict={error:'Duplicate filename',conflicts:[upload],duplicate_name:'Trial (vector_k=10) 測試 (1).json'};
    const numbered='uploads/new/Trial (vector_k=10) 測試 (1).json';
    const tick=()=>new Promise(setImmediate);
    const imports=()=>requests.filter(r=>r.url==='/api/results/import');
    // Each duplicate in one batch must receive its own prompt; skipping never
    // sends a second write request, and new imports continue after a conflict.
    uploadResponses.push(conflict,conflict,{path:numbered,report},{path:'uploads/new/fresh.json',report});
    get('uploads').files=[{name:'Trial (vector_k=10) 測試.json'},{name:'Trial (vector_k=10) 測試.json'},{name:'fresh.json'}];
    let uploading=get('uploads').onchange();await tick();
    assert.equal(get('duplicateDialog').open,true);
    assert.equal(get('duplicateDialog').returnValue,'');
    assert.equal(get('skipDuplicate').focused,true);
    assert.match(get('duplicateProgress').textContent,/UPLOAD 1 OF 3/);
    get('duplicateDialog').returnValue='skip';get('duplicateDialog').onclose();await tick();
    assert.match(get('duplicateProgress').textContent,/UPLOAD 2 OF 3/);
    assert.match(get('duplicateNewName').textContent,/\(1\)\.json/);
    assert.equal(imports().at(-1).body.get('action'),'ask','Second conflict needs an independent choice');
    get('duplicateDialog').returnValue='duplicate';get('duplicateDialog').onclose();await uploading;
    assert.equal(imports().at(-2).body.get('action'),'duplicate');
    assert.equal(imports().at(-1).body.get('action'),'ask','Choice does not carry over to next file');
    assert.equal(evaluate(`selected.has(${JSON.stringify(numbered)})`),true);
    assert.equal(evaluate(`selected.has(${JSON.stringify(upload)})`),false);
    assert.match(get('status').textContent,/2 file\(s\) saved.*1 skipped/);
    assert.equal(get('uploads').disabled,false);
    // Replacement targets are explicit when older files share a basename.
    const other='uploads/another/Trial (vector_k=10) 測試.json';library.push(other);
    const replacement={...report,status:'new replacement'};
    uploadResponses.push({...conflict,conflicts:[upload,other]},{path:other,report:replacement,replaced:true});
    get('uploads').files=[{name:'Trial (vector_k=10) 測試.json'}];
    uploading=get('uploads').onchange();await tick();
    assert.equal(get('replaceTarget').children.length,2);
    get('replaceTarget').value=other;get('duplicateDialog').returnValue='replace';get('duplicateDialog').onclose();await uploading;
    assert.equal(imports().at(-1).body.get('action'),'replace');
    assert.equal(imports().at(-1).body.get('replace_path'),other);
    assert.equal(evaluate(`loaded.get(${JSON.stringify(other)}).status`),'new replacement');
    assert.match(get('status').textContent,/1 replaced/);
    // Escape resets any prior confirmation and means skip for this file only.
    uploadResponses.push(conflict);get('uploads').files=[{name:'Trial (vector_k=10) 測試.json'}];
    uploading=get('uploads').onchange();await tick();
    assert.equal(get('duplicateDialog').returnValue,'');get('duplicateDialog').onclose();await uploading;
    assert.match(get('status').textContent,/1 skipped/);
    assert.equal(uploadResponses.length,0);
    cardFor(other).children[1].children[0].onclick();
    assert.equal(get('renameDialog').open,true);
    get('renameDialog').onclose();
    assert.equal(evaluate('pendingRename!==null'),true,'A queued close must not clear a reopened rename dialog');
    assert.equal(get('renameName').value,'Trial (vector_k=10) 測試.json');
    get('renameName').value='A renamed (2).json';failRename=true;
    await get('renameForm').onsubmit({preventDefault(){}});
    assert.equal(get('renameError').textContent,'Name already exists');
    assert.equal(get('renameDialog').open,true,'Failed rename keeps the editor open');
    assert.equal(evaluate(`selected.has(${JSON.stringify(other)})`),true);
    failRename=false;await get('renameForm').onsubmit({preventDefault(){}});
    const renamed='uploads/another/A renamed (2).json';
    assert.equal(evaluate(`selected.has(${JSON.stringify(other)})`),false);
    assert.equal(evaluate(`selected.has(${JSON.stringify(renamed)})`),true);
    assert.equal(evaluate(`loaded.get(${JSON.stringify(renamed)}).status`),'new replacement');
    assert.equal(get('renameDialog').open,false);
    assert.equal(get('library').children[0].children[0].children[1].children[0].textContent,'A renamed (2).json');
    const renameCalls=requests.filter(r=>r.url==='/api/results/rename').length;
    cardFor(renamed).children[1].children[0].onclick();get('renameCancel').onclick();
    assert.equal(requests.filter(r=>r.url==='/api/results/rename').length,renameCalls);
    library=['z.json','uploads/old/b.json','Alpha.json','run10.json','uploads/old/run2.json'];await get('refresh').onclick();
    assert.deepEqual(get('library').children.map(c=>c.children[0].children[1].children[0].textContent),['Alpha.json','b.json','run2.json','run10.json','z.json']);
    context.sortFixtures=[
        ['Zeta.json',{accuracy_percent:90,mean_question_tokens:0,mean_question_seconds:5,stored_text_bytes:1024,completion_percent:100},90,10],
        ['Alpha.json',{accuracy_percent:80,mean_question_tokens:200,mean_question_seconds:2,stored_text_bytes:2048,completion_percent:80},10,90],
        ['Missing.json',{accuracy_percent:null,mean_question_tokens:null,mean_question_seconds:null,stored_text_bytes:null,completion_percent:null},null,null],
        ['Tied.json',{accuracy_percent:90,mean_question_tokens:100,mean_question_seconds:1,stored_text_bytes:1024,completion_percent:90},90,50]
    ];
    evaluate(`selected.clear();loaded.clear();for(const [name,overall,a,b] of sortFixtures){loaded.set(name,{comparison:{rows:[{module:'vector_store',overall,categories:{1:{...overall,accuracy_percent:a},2:{...overall,accuracy_percent:b}}}]}});selected.add(name);}el('category').value='overall';render();`);
    const chartNames=()=>svg(get('charts').children[0]).children.filter(c=>c.tag==='g').map(c=>c.attrs['data-path']);
    const tableNames=()=>get('types').children[1].children.map(row=>row.children[0].textContent.split(': ')[1].split(' ·')[0]+'.json');
    const identity=name=>svg(get('charts').children[0]).children.find(c=>c.attrs?.['data-path']===name).attrs['aria-label'].split(';')[0];
    const tiedIdentity=identity('Tied.json');
    assert.deepEqual(chartNames(),['Alpha.json','Tied.json','Zeta.json']);
    assert.deepEqual(tableNames(),['Alpha.json','Missing.json','Tied.json','Zeta.json'],'Table keeps missing runs in name order');
    for(const metric of ['accuracy','tokens','runtime','storage']){
        chooseAxes(metric,'accuracy');
        assert.deepEqual(chartNames(),['Alpha.json','Tied.json','Zeta.json']);
        assert.equal(identity('Tied.json'),tiedIdentity,'Run identity stays stable across axes');
    }
    chooseAxes('storage','accuracy');point(get('charts').children[0]).onfocus();
    assert.match(textContent(get('chartTooltip')),/Run 1.*Alpha.json.*2 KiB.*80 %/);
    const points=svg(get('charts').children[0]).children.filter(c=>c.tag==='g');
    points[1].onfocus();assert.match(textContent(get('chartTooltip')),/Also at these coordinates: Run 4: Zeta/);
    assert.equal(dots(get('charts').children[0]).length,3,'Overlapping measured runs each retain a point');
    get('category').value='2';get('category').onchange();
    assert.deepEqual(chartNames(),['Alpha.json','Tied.json','Zeta.json']);
    const chooseTable=field=>{get('tableSort').value=field;get('tableSort').onchange();};
    chooseTable('category:1');assert.deepEqual(tableNames(),['Tied.json','Zeta.json','Alpha.json','Missing.json']);
    chooseTable('category:2');assert.deepEqual(tableNames(),['Alpha.json','Tied.json','Zeta.json','Missing.json'],'Choosing a new metric replaces the previous table sort');
    let headers=get('types').children[0].children[0].children;
    assert.equal(headers.filter(th=>th.attrs['aria-sort']).length,1,'Only one header carries an active sort');
    assert.equal(headers[2].attrs['aria-sort'],'descending');
    get('tableOrder').value='asc';get('tableOrder').onchange();assert.deepEqual(tableNames(),['Zeta.json','Tied.json','Alpha.json','Missing.json']);
    chooseTable('completion');assert.deepEqual(tableNames(),['Zeta.json','Tied.json','Alpha.json','Missing.json']);
    chooseTable('name');assert.equal(get('tableOrder').value,'asc');assert.deepEqual(tableNames(),['Alpha.json','Missing.json','Tied.json','Zeta.json']);
    console.log('Comparison UI: configurable scatter plot and independent table sorting, stable identities, filters/zero/missing/ties, selected-only downloads, tooltips, rename, deletion, and duplicates passed.');
})().catch(error=>{console.error(error);process.exitCode=1;});
