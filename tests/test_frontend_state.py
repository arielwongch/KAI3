"""DOM-free state tests; install requirements-test.txt to enable QuickJS."""
import json
from pathlib import Path
import unittest
try:
    import quickjs
except ImportError:
    quickjs = None

STUB = r'''
const storage = SEED;
const localStorage = {getItem: k => storage[k] ?? null, setItem: (k,v) => storage[k]=v, removeItem: k => delete storage[k]};
let serial = 0;
const crypto = {randomUUID: () => 'uuid-' + (++serial)};
class Node {
    constructor(tag='div') {this.tag=tag; this.children=[]; this.selectedOptions=[]; this.options=[]; this.value=''; this.disabled=false; this.hidden=false; this.style={}; this.dataset={}; this.classList={toggle(){},add(){},remove(){}};}
    append(...nodes) {this.children.push(...nodes);}
    replaceChildren(...nodes) {this.children=nodes;}
    querySelectorAll() {return [];}
    focus() {}
    click() {if(this.onclick) return this.onclick();}
    remove() {}
    setAttribute() {}
}
const nodeText = node => [node.textContent ?? '', ...node.children.map(nodeText)].join(' ');
const nodes = {};
let selectedMode='sliding_window';
const document = {getElementById: id => nodes[id] ||= new Node(), createElement: tag => new Node(tag), querySelector: () => ({value:selectedMode}), querySelectorAll: () => [], body: new Node()};
const marked = {parse: text => text};
const DOMPurify = {sanitize: text => 'SANITIZED:' + text};
const navigator = {clipboard: {writeText: async () => {}}};
const setTimeout = () => 1, clearTimeout = () => {};
let requests=[];
let responseStatus=404, responseData={error:'Server memory is unavailable.'};
const fetch = async (url,options) => {requests.push({url,options}); return {ok:responseStatus<400,status:responseStatus,json:async()=>responseData};};
'''

@unittest.skipIf(quickjs is None, 'Install requirements-test.txt for frontend state tests')
class FrontendStateTests(unittest.TestCase):
    def context(self, seed=None):
        ctx = quickjs.Context()
        ctx.eval(STUB.replace('SEED', json.dumps(seed or {})))
        ctx.eval(Path('src/workspace.js').read_text())
        self.drain(ctx)
        return ctx
    def drain(self, ctx):
        for _ in range(100):
            if not ctx.execute_pending_job():
                return
        self.fail('Unsettled frontend promise queue')
    def test_migration_and_restart(self):
        ctx = self.context({'kai3-chat-history': json.dumps([{'role':'user','content':'<script>bad</script>'}]),'kai3-chat-id':'legacy','kai3-memory-module':'sliding_window'})
        self.assertEqual(ctx.eval('workspace.version'), 1)
        self.assertEqual(ctx.eval('active().id'), 'legacy')
        self.assertTrue(ctx.eval('unavailable'))
        self.assertTrue(ctx.eval("$('sendButton').disabled"))
        self.assertEqual(ctx.eval("$('chatMessages').children[0].children[1].children[1].textContent"), '<script>bad</script>')
        ctx.eval("$('newChat').onclick()")
        self.drain(ctx)
        self.assertEqual(ctx.eval('workspace.sessions.length'), 2)
        self.assertFalse(ctx.eval('unavailable'))
        ctx.eval("workspace.active='legacy'; render(); refreshInspection()")
        self.drain(ctx)
        self.assertTrue(ctx.eval('unavailable'))
    def test_empty_session_and_live_inspection(self):
        ctx = self.context()
        self.assertFalse(ctx.eval('unavailable'))
        ctx.eval("active().module='sliding_window'; render()")
        self.assertFalse(ctx.eval("$('sendButton').disabled"))
        ctx.eval("responseStatus=200; responseData={memory:{config:{max_items:10},entries:[{text:'<script>x</script>',metadata:{}}]},turns:[{query:'Q',status:'completed',retrieved:[],agent_tokens:7}],totals:{agent_tokens:7}}; refreshInspection()")
        self.drain(ctx)
        self.assertIn('<script>x</script>', ctx.eval("nodeText($('inspectionBody'))"))
        ctx.eval("inspectionTab='retrieved'; drawInspection()")
        self.assertIn('No context retrieved', ctx.eval("nodeText($('inspectionBody'))"))
        ctx.eval("inspectionTab='metrics'; drawInspection()")
        self.assertIn('7', ctx.eval("nodeText($('inspectionBody'))"))
    def test_invalid_saved_json_is_recoverable(self):
        ctx = self.context({'kai3-workspace-v1':'invalid JSON','kai3-chat-history':'broken'})
        self.assertEqual(ctx.eval('workspace.sessions.length'), 1)
        self.assertEqual(ctx.eval('active().messages.length'), 0)
    def test_failed_turn_refresh_and_existing_flag(self):
        seed={'kai3-workspace-v1':json.dumps({'version':1,'active':'old','sessions':[{'id':'old','title':'old','module':'sliding_window','messages':[],'started':True}]})}
        ctx=self.context(seed)
        ctx.eval("unavailable=false; checking=false; controlState(); $('userInput').value='test'; $('chatForm').onsubmit({preventDefault(){}})")
        self.drain(ctx)
        self.assertTrue(ctx.eval('unavailable'))
        self.assertIn('Request failed', ctx.eval('active().messages[1].content'))
        self.assertTrue(ctx.eval("JSON.parse(requests.find(r=>r.url==='/get').options.body).requires_existing"))

    def test_hybrid_window_validation_persistence_request_and_lock(self):
        ctx = self.context()
        ctx.eval("active().module='alpha'; render(); $('chatWindowSize').value=''; $('chatWindowSize').oninput()")
        self.assertTrue(ctx.eval("$('sendButton').disabled"))
        self.assertEqual(ctx.eval("$('chatWindowSize').value"), '')
        ctx.eval("$('chatWindowSize').value='3'; $('chatWindowSize').oninput()")
        self.assertFalse(ctx.eval("$('sendButton').disabled"))
        self.assertEqual(ctx.eval("JSON.parse(storage[key]).sessions[0].window_size"), 3)
        ctx.eval("responseStatus=200; responseData={reply:'done',window_size:3,memory:{entries:[]},turns:[]}; $('userInput').value='hello'; $('chatForm').onsubmit({preventDefault(){}})")
        self.drain(ctx)
        self.assertEqual(ctx.eval("JSON.parse(requests.find(r=>r.url==='/get').options.body).window_size"), 3)
        self.assertTrue(ctx.eval("$('chatWindowSize').disabled"))
        ctx.eval("$('chatWindowSize').value='9'; $('chatWindowSize').oninput()")
        self.assertEqual(ctx.eval('active().window_size'), 3)

    def test_old_session_defaults_and_server_settings(self):
        seed = {'kai3-workspace-v1': json.dumps({'version':1,'active':'old','sessions':[
            {'id':'old','module':'sliding_window','messages':[],'started':True}]})}
        ctx = self.context(seed)
        self.assertEqual(ctx.eval("$('chatWindowSize').value"), '10')
        ctx.eval("responseStatus=200;responseData={window_size:12,memory:{entries:[]},turns:[]}; refreshInspection()")
        self.drain(ctx)
        self.assertEqual(ctx.eval('active().window_size'), 12)
        self.assertTrue(ctx.eval("$('chatWindowSize').disabled"))

    def test_benchmark_window_visibility_description_and_payload(self):
        ctx = self.context()
        ctx.eval("$('benchmarkWindowSize').value='7'; selectedMode='beta'; updateRunSummary()")
        self.assertFalse(ctx.eval("$('benchmarkWindowControl').hidden"))
        self.assertIn('7 recent entries + up to 5 archived turns', ctx.eval("$('retrievalDescription').textContent"))
        ctx.eval("selectedMode='fact_store'; updateRunSummary()")
        self.assertTrue(ctx.eval("$('benchmarkWindowSize').disabled"))
        self.assertTrue(ctx.eval("$('benchmarkWindowControl').hidden"))
        for mode in ('alpha', 'fact_store'):
            ctx.eval(f"selectedMode='{mode}'; previewDataset=[{{sample_id:'one',qa:[]}}]; $('allConversations').checked=true; responseStatus=200;responseData={{run_id:'run'}};pollBenchmark=()=>{{}}; $('benchmarkForm').onsubmit({{preventDefault(){{}}}})")
            self.drain(ctx)
            payload = json.loads(ctx.eval("requests.filter(r=>r.url==='/api/benchmarks').slice(-1)[0].options.body"))
            if mode == 'alpha':
                self.assertEqual(payload['options']['window_size'], 7)
            else:
                self.assertNotIn('window_size', payload['options'])

    def test_hybrid_import_and_tier_inspection_preserve_additive_fields(self):
        ctx = self.context()
        report = {'schema_version':1, 'config':{'modules':['beta'], 'window_size':2},
                  'retrieval_policy':{'strategy':'window_plus_recall', 'window_size':2, 'long_term_k':5},
                  'memories':[{'memory':{'config':{'max_items':2}, 'entries':[
                      {'text':'archived text', 'metadata':{'memory_tier':'long_term','memory_component':'vector_store'}, 'chunk_count':1},
                      {'text':'recent text', 'metadata':{'memory_tier':'recent','memory_component':'sliding_window'}}]}}], 'cases':[]}
        ctx.eval('const hybridReport=' + json.dumps(report))
        normalized = json.loads(ctx.eval('JSON.stringify(normalizeBenchmarkImport(hybridReport))'))
        self.assertEqual(normalized['config']['window_size'], 2)
        self.assertEqual(normalized['retrieval_policy'], report['retrieval_policy'])
        self.assertEqual(normalized['memories'][0]['memory'], report['memories'][0]['memory'])
        ctx.eval("setInspection({memory:hybridReport.memories[0].memory,turns:[]}, 'beta')")
        text = ctx.eval("nodeText($('inspectionBody'))")
        self.assertIn('long term', text)
        self.assertIn('recent', text)
        self.assertIn('archived text', text)

if __name__ == '__main__':
    unittest.main()
