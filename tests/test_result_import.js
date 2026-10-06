const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
class Node {
  constructor(tag='div'){this.tag=tag;this.children=[];this.value=tag==='select'?'all':'';this.hidden=false;this.disabled=false;this.style={};this.dataset={};this.classList={toggle(){},add(){},remove(){}};}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  querySelectorAll(){return [];}
  setAttribute(){}
  click(){if(this.onclick)return this.onclick();}
}
const nodes={};let requests=0;const downloaded=[];const storage={};
const context=vm.createContext({
  location:{pathname:'/benchmark'},
  document:{getElementById:id=>nodes[id]??=new Node(),createElement:tag=>new Node(tag),querySelectorAll:()=>[],body:new Node()},
  localStorage:{getItem:k=>storage[k]??null,setItem:(k,v)=>storage[k]=v,removeItem:k=>delete storage[k]},
  crypto:{randomUUID:()=> 'test-id'},setTimeout:()=>1,clearTimeout(){},
  fetch(){requests++;throw new Error('Import must not use the network');},
  Blob:class {constructor(parts){downloaded.push(parts.join(''));}},
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
assert.equal(nodes.benchmarkResults.children[0].children.length,3);
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
 {error:'failed',diagnostics:{answer_tokens:0,judge_tokens:0}}],memories:[{ingestion:{memory_tokens:30,total_seconds:5}}]};
assert.equal(run('benchmarkUsage(usageFixture).meanRuntime'),15);
assert.equal(run('benchmarkUsage(usageFixture).meanQuestionTokens'),180);
assert.equal(run('benchmarkUsage(usageFixture).totalTokens'),390);
assert.equal(run('benchmarkUsage(usageFixture).recordedSeconds'),35);
assert.equal(run('benchmarkUsage(usageFixture).answerFailures'),1);
assert.equal(run('benchmarkUsage({cases:[]}).meanRuntime'),null);
assert.match(text(nodes.benchmarkResults),/Average question runtime/);
assert.match(text(nodes.benchmarkResults),/Average tokens per question/);
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
  context.fetch=async url=>({ok:true,status:200,json:async()=>url==='/api/benchmarks'?{runs:[]}:({...context.liveReport,config:{modules:['no_memory']},cases:[],review:{token:'token'}})});
  run("importedBenchmark=false;runId='test-run';");
  await run('pollBenchmark()');
  assert.equal(nodes.benchmarkRunning.hidden,false);
  assert.equal(nodes.reportMode.hidden,true);
  assert.equal(nodes.continueBenchmark.hidden,false);
  console.log('Result import tests passed: legacy/current reports, validation, rendering, local export, no network.');
})().catch(error=>{console.error(error);process.exitCode=1;});
