const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor(tag='div'){this.tag=tag;this.children=[];this.value=tag==='select'?'all':'';this.hidden=false;this.disabled=false;this.style={};this.dataset={};this.classList={toggle(){},add(){},remove(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  querySelectorAll(){return [];}
  setAttribute(key,value){(this.attrs??={})[key]=value;}
  getAttribute(key){return this.attrs?.[key]??null;}
  removeAttribute(key){if(this.attrs)delete this.attrs[key];}
  click(){if(this.onclick)return this.onclick();}
  focus(){}
  select(){}
  showModal(){this.open=true;}
  close(){this.open=false;this.onclose?.();}
}
const nodes={};let requests=0;const downloaded=[];const storage={};
const context=vm.createContext({
  location:{pathname:'/benchmark'},
  document:{getElementById:id=>nodes[id]??=new Node(),createElement:tag=>new Node(tag),querySelectorAll:()=>[],body:new Node()},
  localStorage:{getItem:k=>storage[k]??null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]},
  crypto:{randomUUID:()=> 'test-id'},setTimeout:()=>1,clearTimeout(){},
  fetch(){requests++;throw new Error('Import must not use the network');},
  Blob:class {constructor(parts){this.parts=parts;downloaded.push(parts.join(''));}},
  FormData:class {constructor(){this.fields=new Map();}append(key,value,name){this.fields.set(key,value);if(key==='file')this.filename=name;}get(key){return this.fields.get(key);}},
  URL:{createObjectURL:()=> 'blob:test',revokeObjectURL(){}},
});
// Skip page startup to isolate import actions from the initial dataset request.
const source=fs.readFileSync('src/workspace.js','utf8');
vm.runInContext(source.slice(0,source.lastIndexOf("if(page==='chat'){save();")),context);
const run=code=>vm.runInContext(code,context);
const text=node=>[node.textContent??'',...node.children.map(text)].join(' ');
const fixture={schema_version:1,status:'completed',config:{modules:['no_memory']},scores:[
  {category:4,mean_qa_score:1,mean_judge:2,answer_count:1,judge_count:1},
  {category:'overall',mean_qa_score:1,mean_judge:2,answer_count:1,judge_count:1}],
  cases:[{question:'<script>untrusted question</script>',category:4,answer:'Rome',prediction:'Rome',
    score:1,token_f1:1,judge:{overall:2},diagnostics:{answer_seconds:1.5,answer_tokens:7,
      retrieved:[{text:'Alice lives in Rome.',metadata:{speaker:'Alice'}}]}}]};
context.fixture=fixture;
run("showImportedBenchmark(fixture,'legacy.json')");
assert.equal(requests,0);
assert.equal(nodes.benchmarkReport.hidden,false);
assert.equal(nodes.newChat.hidden,true);
assert.equal(nodes.benchmarkSidebar.hidden,false);
assert.equal(nodes.reportMode.hidden,false);
assert.equal(nodes.reviewLabelsControl.hidden,true);
assert.equal(nodes.reportStatus.textContent,'');
assert.equal(nodes.benchmarkSetup.hidden,true);
assert.equal(nodes.resumeBenchmark.hidden,true);
assert.equal(nodes.reviewFile.disabled,true);
assert.equal(run('runId'),null);
assert.equal(fixture.cases[0].question_index,undefined); // original unchanged
assert.equal(nodes.benchmarkResults.children[0].children.length,4);
const folds=nodes.benchmarkResults.children.filter(n=>n.tag==='details');
assert.equal(folds.length,6);
assert.ok(folds.every(n=>!n.open));
assert.equal(nodes.reportMoreActions.hidden,true);
assert.match(text(nodes.benchmarkResults.children[0]),/LoCoMo score/);
assert.match(text(nodes.benchmarkResults),/Single-hop/);
assert.match(text(nodes.benchmarkResults),/binary accuracy unavailable/);
assert.match(text(nodes.benchmarkResults),/Judge rubric/);
assert.match(text(nodes.benchmarkResults),/Alice lives in Rome/);
assert.match(text(nodes.benchmarkResults),/answer_seconds/);
assert.match(text(nodes.benchmarkResults),/<script>untrusted question<\/script>/);
run("$('exportBenchmark').onclick(); $('resumeBenchmark').onclick(); $('exportReview').onclick()");
assert.equal(requests,0);
assert.deepEqual(JSON.parse(downloaded[0]),fixture);
for(const value of [[],{}, {cases:'wrong'}, {schema_version:99,cases:[]}, {cases:[{question:'Q',category:9}]}, {cases:[{question:'Q',category:4,token_f1:'bad'}]}, {cases:[],scores:[{category:'overall',accuracy:'bad'}]}]){
  context.invalid=value;
  assert.throws(()=>run('showImportedBenchmark(invalid,"bad.json")'),/Cannot import results/);
  assert.equal(run('benchmark.cases.length'),1);
}
const modern=JSON.parse(JSON.stringify(fixture));modern.scores[1].accuracy=1;modern.scores[1].correct_count=1;modern.scores[1].scored_count=1;
context.modern=modern;run("showImportedBenchmark(modern,'modern.json')");
assert.match(text(nodes.benchmarkResults),/1 \/ 1 correct/);
// Module-specific controls omit unsupported settings and retain per-module drafts.
run("updateMemorySettings('sliding_window')");
assert.equal(nodes.retrievalKField.hidden,false);
assert.equal(nodes.summaryTokensField.hidden,true);
assert.equal(run("benchmarkMemoryOptions('sliding_window').max_stored_entries"),10);
run("$('retrievalK').value='8';$('storageCapacity').value='20';updateMemorySettings('summarization')");
assert.equal(nodes.retrievalKField.hidden,true);
assert.equal(nodes.storageCapacityField.hidden,true);
assert.equal(nodes.summaryTokensField.hidden,false);
assert.equal(nodes.retrievalK.disabled,true);
assert.equal(run("'retrieval_k' in benchmarkMemoryOptions('summarization')"),false);
assert.equal(run("'max_stored_entries' in benchmarkMemoryOptions('summarization')"),false);
run("updateMemorySettings('vector_store')");
assert.equal(run("benchmarkMemoryOptions('vector_store').max_stored_entries"),null);
run("updateMemorySettings('sliding_window')");
assert.equal(nodes.retrievalK.value,'8');
assert.equal(nodes.storageCapacity.value,'20');
run("$('retrievalK').value='0'");
assert.throws(()=>run("benchmarkMemoryOptions('sliding_window')"),/positive integer/);
run("updateMemorySettings('full_context')");
assert.equal(nodes.memorySettings.hidden,true);
assert.equal(run("Object.keys(benchmarkMemoryOptions('full_context')).length"),0);
context.controlled=JSON.parse(JSON.stringify(modern));
context.controlled.schema_version=2;
context.controlled.config.modules=['full_context'];
Object.assign(context.controlled.scores[1],{selected_count:2,judged_count:1,completion_rate:.5,end_to_end_success_rate:.5,failure_counts:{judge_failed:1}});
run("showImportedBenchmark(controlled,'controlled.json')");
assert.match(text(nodes.benchmarkResults),/End-to-end success/);
assert.match(text(nodes.benchmarkResults),/50\.0%/);
assert.match(text(nodes.benchmarkResults),/Judge completion/);
assert.equal(run("benchmarkConditionLabel({config:{modules:['no_memory'],no_memory_context:'full'}})"),'Full Context');
assert.match(run("benchmarkConditionLabel({config:{modules:['no_memory']}})"),/unknown/);
context.liveReport={status:'running',worker:{mode:'detached'},progress:{percent:25.5,total:10,answered:2,judged:1,phase:'ingestion',sample_id:'one',conversation_index:1,conversation_total:2,turn_completed:5,turn_total:20}};
run('renderRunProgress(liveReport)');
assert.equal(nodes.progressBar.style.width,'25.5%');
assert.match(nodes.progressActivity.textContent,/Writing turn 5 of 20/);
assert.match(nodes.progressCount.textContent,/2 answered/);
assert.equal(nodes.continueBenchmark.hidden,true);
context.liveReport.status='waiting_review';context.liveReport.progress.phase='review';
run('renderRunProgress(liveReport)');
assert.equal(nodes.continueBenchmark.hidden,false);
assert.equal(nodes.reviewMemoryButton.hidden,false);
assert.match(nodes.progressTitle.textContent,/Memory ready for review/);
context.usageFixture={cases:[
 {prediction:'A',judge:{overall:2},diagnostics:{total_seconds:10,answer_seconds:6,judge_seconds:3,retrieval_seconds:1,answer_tokens:100,judge_tokens:20}},
 {prediction:'B',judge:{overall:2},diagnostics:{total_seconds:20,answer_seconds:12,judge_seconds:6,retrieval_seconds:2,answer_tokens:200,judge_tokens:40}},
 {error:'failed',diagnostics:{answer_tokens:0,judge_tokens:0,total_seconds:0,retrieval_seconds:0,answer_seconds:0}}],memories:[{ingestion:{memory_tokens:30,total_seconds:5}}]};
assert.equal(run('benchmarkUsage(usageFixture).meanRuntime'),26/3);
assert.equal(run('benchmarkUsage(usageFixture).meanQuestionTokens'),110);
assert.equal(run('benchmarkUsage(usageFixture).totalMemoryAnswerTokens'),330);
assert.equal(run('benchmarkUsage(usageFixture).totalRuntime'),26);
assert.equal(run('benchmarkUsage(usageFixture).totalTokens'),390);
assert.equal(run('benchmarkUsage(usageFixture).recordedSeconds'),35);
assert.equal(run('benchmarkUsage(usageFixture).answerFailures'),1);
assert.equal(run('benchmarkUsage({cases:[]}).meanRuntime'),null);
assert.match(text(nodes.benchmarkResults),/Average question runtime/);
assert.match(text(nodes.benchmarkResults),/Memory \+ answering tokens\/question/);
assert.match(text(nodes.benchmarkResults),/Context tokens\/question/);
context.contextUsage={cases:[{diagnostics:{memory_context_tokens:100,answer_tokens:99999}},{diagnostics:{memory_context_tokens:300}}]};
assert.equal(run('benchmarkUsage(contextUsage).meanContextTokens'),200);
context.contextUsage.cases[1].diagnostics={supplied_context:''};
assert.equal(run('benchmarkUsage(contextUsage).meanContextTokens'),50);
context.contextUsage.cases[1].diagnostics={};
assert.equal(run('benchmarkUsage(contextUsage).meanContextTokens'),null);
context.contextUsage.comparison={version:5,rows:[{overall:{case_count:2,total_context_tokens:800,context_token_count:2}}]};
assert.equal(run('benchmarkUsage(contextUsage).meanContextTokens'),400,'Use backend offline counts when legacy records lack counts');
context.contextUsage.comparison={version:5,rows:{}};
assert.equal(run('benchmarkUsage(contextUsage).meanContextTokens'),null,'Malformed optional comparison metadata cannot break report imports');
const originalUsage=JSON.stringify(context.usageFixture);
context.retryUsage=JSON.parse(originalUsage);
context.retryUsage.previous_ingestions=[{ingestion:{ingestion_id:'retry',memory_tokens:60,preparation_seconds:10}}];
context.retryUsage.cases[0].diagnostics.provider_requests=[{phase:'answer',tokens:40},{phase:'answer',tokens:80},{phase:'judge',tokens:99999}];
context.retryUsage.cases[0].diagnostics.execution_retrieval_seconds=3;
context.retryUsage.cases[0].diagnostics.execution_answer_seconds=10;
assert.equal(run('benchmarkUsage(retryUsage).meanQuestionTokens'),410/3);
assert.equal(run('benchmarkUsage(retryUsage).meanRuntime'),14);
context.retryUsage.previous_ingestions.push(JSON.parse(JSON.stringify(context.retryUsage.previous_ingestions[0])));
assert.equal(run('benchmarkUsage(retryUsage).meanQuestionTokens'),410/3,'Duplicate rebuilds count once');
context.retryUsage.cases[0].diagnostics.provider_requests.unshift({phase:'answer',status:'error',tokens:null});
context.retryUsage.previous_ingestions[0].ingestion.provider_requests=[{phase:'memory',status:'error',tokens:null},{phase:'memory',status:'completed',tokens:60}];
assert.equal(run('benchmarkUsage(retryUsage).meanQuestionTokens'),410/3,'Unreported failed requests do not hide the average');
assert.equal(run("recordedPhaseTokens({provider_requests:[{phase:'memory',status:'error',tokens:5},{phase:'memory',status:'completed',tokens:30}]},'memory')"),35);
assert.equal(run("recordedPhaseTokens({provider_requests:[{phase:'memory',status:'completed',tokens:null}]},'memory')"),null);
assert.equal(run('benchmarkUsage(retryUsage).meanRuntime'),14);
context.retryUsage.cases[1].diagnostics.answer_tokens=null;
context.retryUsage.cases[1].diagnostics.execution_answer_seconds=null;
assert.equal(run('benchmarkUsage(retryUsage).meanQuestionTokens'),null);
assert.equal(run('benchmarkUsage(retryUsage).meanRuntime'),null);
assert.equal(JSON.stringify(context.usageFixture),originalUsage,'Computing costs preserves the input');
context.lifecycleFixture={cases:[{module:'vector_store',prediction:'A',judge:null,judge_error:'Invalid judge output',diagnostics:{answer_tokens:100,judge_tokens:20,total_seconds:10,execution_total_seconds:15}}],
 memories:[{module:'vector_store',ingestion:{ingestion_id:'build-a',memory_tokens:30,total_seconds:5}}]};
assert.equal(run('benchmarkUsage(lifecycleFixture).totalTokens'),150,'Known tokens from failed judging count even without a parsed judgment');
assert.equal(run('benchmarkUsage(lifecycleFixture).recordedSeconds'),20,'Prefer cumulative execution time to the earlier question timer');
context.lifecycleFixture.previous_ingestions=[{module:'vector_store',ingestion:{total_seconds:5,memory_tokens:30,ingestion_id:'build-a'}}];
assert.equal(run('benchmarkUsage(lifecycleFixture).totalTokens'),150,'Duplicate build identity is counted once, independent of object key order');
assert.equal(run('benchmarkUsage(lifecycleFixture).ingestionSeconds'),5);
context.lifecycleFixture.cases.push({module:'vector_store',prediction:null,error:'Answer failed',diagnostics:{answer_llm_calls:2,judge_llm_calls:0,provider_requests:[{phase:'answer',status:'error',tokens:5},{phase:'answer',status:'error',tokens:null}],total_seconds:2,execution_total_seconds:3}});
assert.equal(run('benchmarkUsage(lifecycleFixture).totalTokens'),155,'Reported tokens from failed answers count; unreported failures are ignored');
assert.equal(run('benchmarkUsage(lifecycleFixture).recordedSeconds'),23);
context.lifecycleFixture.cases[1].diagnostics.execution_total_seconds=null;
assert.equal(run('benchmarkUsage(lifecycleFixture).recordedSeconds'),null,'An explicitly unknown cumulative time is not replaced with a partial total');
context.lifecycleFixture.previous_ingestions[0].ingestion.total_seconds=6;
assert.equal(run('benchmarkUsage(lifecycleFixture).totalTokens'),null,'Conflicting duplicate ingestion records follow Compare lifecycle rules');
assert.equal(run('benchmarkUsage(lifecycleFixture).ingestionSeconds'),null);
// Exercise the file input handler and malformed JSON recovery.
(async()=>{
  nodes.resultsFile.files=[{name:'bad.json',text:async()=>'{broken'}];
  await run("$('resultsFile').onchange()");
  assert.match(nodes.reportStatus.textContent,/not valid JSON/);
  nodes.resultsFile.files=[{name:'legacy.json',text:async()=> '\uFEFF'+JSON.stringify(fixture)}];
  await run("$('resultsFile').onchange()");
  assert.equal(nodes.resultsFile.value,'');
  assert.match(nodes.reportSubtitle.textContent,/legacy.json/);
  assert.equal(requests,0);
  if(process.argv[2]){
    context.actual=JSON.parse(fs.readFileSync(process.argv[2],'utf8').replace(/^\uFEFF/,''));
    run("showImportedBenchmark(actual,'no_mem_locomo.json')");
    assert.equal(run('benchmark.cases.length'),100);
    assert.match(text(nodes.benchmarkResults),/Scores by category/);
    assert.equal(requests,0);
    console.log('Actual 100-question export rendered successfully.');
  }
  const exports=[],responses=[];
  context.fetch=async (url,options={})=>{
    exports.push({url,...options});
    if(url==='/api/results')return {ok:true,json:async()=>({files:['renamed (trial).json']})};
    const response=responses.shift();assert(response,'Unexpected export request: '+url);
    return {ok:response.status<400,status:response.status,json:async()=>response.data};
  };
  const save=()=>run("$('compareExportForm').onsubmit({preventDefault(){}})");
  const close=()=>run("$('compareExportCancel').onclick()");
  const before=JSON.stringify(fixture);
  run("$('exportToCompare').onclick()");
  assert.equal(nodes.compareExportDialog.open,true);
  assert.equal(nodes.compareExportName.value,'legacy.json');
  run("$('compareExportDialog').onclose()");
  assert.equal(run('compareExportSource!==null'),true,'A queued close from an earlier dialog must not clear a reopened export');
  nodes.compareExportName.value='renamed (trial).json';
  responses.push({status:201,data:{path:'renamed (trial).json',report:{comparison:{rows:[]}}}});
  await save();
  const firstExport=exports.find(r=>r.url==='/api/results/import');
  assert.equal(firstExport.body.filename,'renamed (trial).json');
  assert.deepEqual(JSON.parse(firstExport.body.get('file').parts.join('')),fixture,'Export preserves original imported fields');
  assert.equal(JSON.stringify(fixture),before);
  assert.equal(nodes.compareExportOpen.hidden,false);
  assert.match(nodes.compareExportStatus.textContent,/renamed \(trial\).json.*computed metrics/);
  assert.equal(exports.some(r=>r.url.includes('/api/benchmarks/')),false,'Imported reports need no benchmark API lookup');
  close();
  const conflict={status:409,data:{error:'Duplicate',conflicts:['old.json','uploads/old.json'],duplicate_name:'old (1).json'}};
  run("$('exportToCompare').onclick();$('compareExportName').value='old.json'");
  responses.push(conflict);await save();
  assert.equal(nodes.compareExportConflict.hidden,false);
  assert.equal(nodes.compareExportTarget.children.length,2);
  assert.equal(nodes.compareExportSubmit.hidden,true);
  nodes.compareExportTarget.value='uploads/old.json';responses.push({status:200,data:{path:'uploads/old.json',replaced:true}});
  await run("$('compareExportReplace').onclick()");
  let last=exports.filter(r=>r.url==='/api/results/import').at(-1);
  assert.equal(last.body.get('action'),'replace');assert.equal(last.body.get('replace_path'),'uploads/old.json');
  close();
  run("$('exportToCompare').onclick();$('compareExportName').value='old.json'");
  responses.push(conflict);await save();responses.push({status:201,data:{path:'old (1).json'}});
  await run("$('compareExportDuplicate').onclick()");
  last=exports.filter(r=>r.url==='/api/results/import').at(-1);assert.equal(last.body.get('action'),'duplicate');
  assert.match(nodes.compareExportStatus.textContent,/old \(1\).json/);close();
  run("$('exportToCompare').onclick()");responses.push(conflict);await save();
  const count=exports.length;run("$('compareExportSkip').onclick()");
  assert.equal(exports.length,count,'Skip makes no save request');assert.equal(nodes.compareExportDialog.open,false);
  run("$('exportToCompare').onclick();$('compareExportName').value='../outside.json'");
  responses.push({status:400,data:{error:'Use a JSON basename.'}});await save();
  assert.match(nodes.compareExportStatus.textContent,/basename/);assert.equal(nodes.compareExportOpen.hidden,true);
  assert.equal(nodes.compareExportDialog.open,true);assert.equal(nodes.compareExportName.disabled,false);close();
  run("importedBenchmark=false;runId='saved-run';benchmark={status:'completed',config:{modules:['vector_store']},cases:[]};$('exportToCompare').onclick();runId='another-run'");
  assert.match(nodes.compareExportName.value,/vector store.*saved-ru.*\.json/i);
  const fresh={...fixture,run_id:'saved-run',status:'fresh-snapshot'};
  responses.push({status:200,data:fresh},conflict);await save();
  responses.push({status:201,data:{path:'old (1).json'}});await run("$('compareExportDuplicate').onclick()");
  assert.equal(exports.filter(r=>r.url==='/api/benchmarks/saved-run/export').length,1,'Fresh snapshot is read once and retained for duplicate retries');
  assert.equal(exports.some(r=>r.url==='/api/benchmarks/another-run/export'),false);
  last=exports.filter(r=>r.url==='/api/results/import').at(-1);
  assert.equal(JSON.parse(last.body.get('file').parts.join('')).status,'fresh-snapshot');close();
  run("$('exportToCompare').onclick()");responses.push({status:404,data:{error:'Benchmark run is unavailable.'}});
  const beforeMissing=exports.filter(r=>r.url==='/api/results/import').length;await save();
  assert.equal(exports.filter(r=>r.url==='/api/results/import').length,beforeMissing);
  assert.match(nodes.compareExportStatus.textContent,/unavailable/);close();
  assert.equal(JSON.stringify(fixture),before);assert.equal(responses.length,0);
  context.fetch=async url=>({ok:true,status:200,json:async()=>url==='/api/benchmarks'?{runs:[]}:({...context.liveReport,config:{modules:['no_memory']},cases:[],review:{token:'token'}})});
  run("importedBenchmark=false;runId='test-run';");
  await run('pollBenchmark()');
  assert.equal(nodes.benchmarkRunning.hidden,false);
  assert.equal(nodes.reportMode.hidden,true);
  assert.equal(nodes.continueBenchmark.hidden,false);
  console.log('Result import/export tests passed: imported preservation, named Compare export, fresh saved snapshots, duplicate skip/keep/replace, and failures.');
})().catch(error=>{console.error(error);process.exitCode=1;});
