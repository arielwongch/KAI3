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
const localStorage = {getItem: k => storage[k] ?? null, setItem: (k,v) => storage[k]=v};
let serial = 0;
const crypto = {randomUUID: () => 'uuid-' + (++serial)};
class Node {
    constructor(tag='div') {this.tag=tag; this.children=[]; this.value=''; this.disabled=false; this.hidden=false; this.style={}; this.dataset={}; this.classList={toggle(){},add(){},remove(){}};}
    append(...nodes) {this.children.push(...nodes);}
    replaceChildren(...nodes) {this.children=nodes;}
    querySelectorAll() {return [];}
    focus() {}
    click() {if(this.onclick) return this.onclick();}
    remove() {}
}
const nodes = {};
const document = {getElementById: id => nodes[id] ||= new Node(), createElement: tag => new Node(tag), querySelectorAll: () => [], body: new Node()};
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
        self.assertEqual(ctx.eval("$('inspectionBody').children[1].children[1].textContent"), '<script>x</script>')
        ctx.eval("inspectionTab='retrieved'; drawInspection()")
        self.assertEqual(ctx.eval("$('inspectionBody').children[2].children[1].textContent"), 'No context retrieved.')
        ctx.eval("inspectionTab='metrics'; drawInspection()")
        self.assertIn('7', ctx.eval("$('inspectionBody').children[0].children[1].textContent"))
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

if __name__ == '__main__':
    unittest.main()
