/* Real Chromium focus/scroll regression. No npm packages or provider requests.
 * PYTHON=venv/Scripts/python.exe CHROME_BIN=<chrome> node tests/test_benchmark_scroll_browser.js
 * Optional BROWSER_ARTIFACT_DIR saves screenshots and geometric measurements.
 */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
const chromeBin = process.env.CHROME_BIN || (process.platform === 'win32'
    ? 'C:/Program Files/Google/Chrome/Application/chrome.exe' : 'google-chrome');
const python = process.env.PYTHON || (process.platform === 'win32'
    ? path.join(root, 'venv/Scripts/python.exe') : 'python3');
const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'kai3-scroll-browser-'));
const artifacts = process.env.BROWSER_ARTIFACT_DIR;
if (artifacts) fs.mkdirSync(artifacts, {recursive:true});
let server, chrome, ws, serial = 0;
const pending = new Map(), errors = [], measurements = [];
function endpoint(child, regex) {
    return new Promise((resolve, reject) => {
        const timer = setTimeout(() => reject(new Error('Browser fixture startup timed out')), 30000);
        const fail = error => {clearTimeout(timer);reject(error);};
        child.once('error', fail);
        child.once('exit', code => fail(new Error('Browser fixture exited early: '+code)));
        for (const stream of [child.stdout, child.stderr]) stream.on('data', chunk => {
            const match = chunk.toString().match(regex);
            if (match) {clearTimeout(timer);resolve(match[1]);}
        });
    });
}
function call(method, params={}, sessionId) {
    return new Promise((resolve, reject) => {
        const id = ++serial;
        const timer = setTimeout(() => {pending.delete(id);reject(new Error('CDP timed out: '+method));}, 10000);
        pending.set(id, {resolve:value=>{clearTimeout(timer);resolve(value);},reject:error=>{clearTimeout(timer);reject(error);}});
        ws.send(JSON.stringify({id,method,params,...(sessionId?{sessionId}:{})}));
    });
}
(async()=>{
    server = spawn(python, ['tests/fixtures/benchmark_browser.py'], {cwd:root,windowsHide:true,stdio:['ignore','pipe','pipe']});
    const port = await endpoint(server, /PREVIEW_PORT=(\d+)/);
    chrome = spawn(chromeBin, ['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check',
        '--remote-debugging-port=0','--user-data-dir='+profile], {windowsHide:true,stdio:['ignore','pipe','pipe']});
    const address = await endpoint(chrome, /DevTools listening on (ws:\/\/[^\s]+)/);
    ws = new WebSocket(address);
    await new Promise((resolve,reject)=>{ws.onopen=resolve;ws.onerror=reject;});
    ws.onmessage = event => {
        const data=JSON.parse(event.data);
        if(data.method==='Runtime.exceptionThrown')errors.push(data.params.exceptionDetails.text);
        if(data.id && pending.has(data.id)){
            const request=pending.get(data.id);pending.delete(data.id);
            data.error?request.reject(new Error(data.error.message)):request.resolve(data.result);
        }
    };
    const {targetId}=await call('Target.createTarget',{url:'about:blank'});
    const {sessionId}=await call('Target.attachToTarget',{targetId,flatten:true});
    await call('Runtime.enable',{},sessionId);await call('Page.enable',{},sessionId);
    const evaluate=async expression=>{
        const result=await call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true},sessionId);
        assert(!result.exceptionDetails,JSON.stringify(result.exceptionDetails));return result.result.value;
    };
    const geometry=()=>evaluate(`(()=>{const rect=e=>{const r=e.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,left:r.left,width:r.width}};return {
        rootScroll:document.scrollingElement.scrollTop,rootHeight:document.scrollingElement.scrollHeight,
        viewport:innerHeight,shell:rect(document.querySelector('.app-shell')),
        header:rect(document.querySelector('.benchmark-topbar')),sidebar:rect(document.getElementById('sidebar')),
        innerScroll:document.querySelector('.benchmark-scroll').scrollTop,
        selected:document.querySelector('[name=benchmarkModule]:checked')?.value,
        focused:document.activeElement?.value,
        compactionVisible:!document.getElementById('compactionSettings').hidden,
        hybridVisible:!document.getElementById('hybridSettings').hidden};})()`);
    const anchored=async context=>{
        const g=await geometry();measurements.push({context,...g});
        assert.equal(g.rootScroll,0,context+': outer document scrolled');
        assert.equal(g.shell.top,0,context+': app shell moved');
        assert.equal(g.header.top,0,context+': header moved');
        assert.equal(g.sidebar.top,0,context+': sidebar moved');
        assert(Math.abs(g.rootHeight-g.viewport)<=1,context+': outer document exceeds viewport');
        return g;
    };
    const click=async selector=>{
        const point=await evaluate(`(()=>{const r=document.querySelector(${JSON.stringify(selector)}).getBoundingClientRect();return {x:r.left+r.width*.6,y:r.top+Math.min(30,r.height/2)}})()`);
        for(const type of ['mousePressed','mouseReleased'])await call('Input.dispatchMouseEvent',{type,...point,button:'left',clickCount:1},sessionId);
        await delay(30);
    };
    const key=async key=>{
        for(const type of ['keyDown','keyUp'])await call('Input.dispatchKeyEvent',{type,key,code:key,windowsVirtualKeyCode:{Tab:9,ArrowRight:39,ArrowLeft:37}[key]},sessionId);
        await delay(20);
    };
    let clicks=0,keyboardSelections=0;
    for(const [width,height] of [[1440,700],[1440,1000],[2048,950],[390,844]]){
        await call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false},sessionId);
        for(const collapsed of (width>720?[false,true]:[false])){
            await call('Page.navigate',{url:`http://127.0.0.1:${port}/benchmark`},sessionId);
            let ready=false;
            for(let i=0;i<100;i++){
                ready=await evaluate(`document.readyState==='complete'&&typeof updateRunSummary==='function'&&!!document.querySelector('[name=benchmarkModule][value="compaction"]')`);
                if(ready)break;await delay(50);
            }
            assert(ready,'Workspace did not initialize');
            if(collapsed)await click('#collapseSidebar');
            const modes=await evaluate(`[...document.querySelectorAll('[name=benchmarkModule]')].map(e=>e.value)`);
            for(const mode of [...modes,'compaction','epsilon','sliding_window','compaction']){
                const selector=`[name=benchmarkModule][value="${mode}"]`;
                // Scroll only the intended pane; scrollIntoView could mask the old bug.
                await evaluate(`(()=>{const label=document.querySelector(${JSON.stringify(selector)}).closest('label');document.querySelector('.benchmark-scroll').scrollTop+=label.getBoundingClientRect().top-${Math.round(height*.55)};return true;})()`);
                const before=await geometry();await click(selector+' ~ span:last-child');
                const after=await anchored(`${width}x${height} collapsed=${collapsed} click=${mode}`);
                assert.equal(after.selected,mode);assert.equal(after.focused,mode);
                assert.equal(after.innerScroll,before.innerScroll,'Selection moved the inner pane unexpectedly');
                assert.equal(after.compactionVisible,mode==='compaction');
                assert.equal(after.hybridVisible,['delta','epsilon','zeta'].includes(mode));clicks++;
            }
            if(artifacts){
                const shot=await call('Page.captureScreenshot',{format:'png'},sessionId);
                fs.writeFileSync(path.join(artifacts,`benchmark-selection-${width}-${height}-${collapsed}.png`),Buffer.from(shot.data,'base64'));
            }
            // A real Tab enters the group; native arrow keys cycle every architecture.
            await evaluate(`(()=>{const before=document.createElement('button');before.id='keyboardEntry';before.textContent='keyboard test';document.querySelector('.architecture-grid').before(before);before.focus({preventScroll:true});return true;})()`);
            await key('Tab');assert.equal((await geometry()).focused,'compaction');
            for(let i=0;i<modes.length;i++){
                await key('ArrowRight');
                const state=await anchored(`${width}x${height} collapsed=${collapsed} keyboard=${i}`);
                assert.equal(state.selected,state.focused);keyboardSelections++;
            }
            await evaluate(`document.getElementById('keyboardEntry').remove();true`);
            for(const deltaY of [20000,-20000]){
                const bounds=await evaluate(`(()=>{const r=document.querySelector('.benchmark-scroll').getBoundingClientRect();return {x:r.left+r.width/2,y:r.top+r.height/2};})()`);
                await call('Input.dispatchMouseEvent',{type:'mouseWheel',...bounds,deltaX:0,deltaY},sessionId);
                await delay(100);await anchored(`${width}x${height} wheel=${deltaY}`);
                assert(await evaluate(deltaY<0?`document.querySelector('.benchmark-scroll').scrollTop===0`:`(()=>{const s=document.querySelector('.benchmark-scroll');return s.scrollTop+s.clientHeight>=s.scrollHeight-1;})()`),'Cannot reach pane edge');
            }
            if(artifacts){
                const shot=await call('Page.captureScreenshot',{format:'png'},sessionId);
                fs.writeFileSync(path.join(artifacts,`benchmark-scroll-${width}-${height}-${collapsed}.png`),Buffer.from(shot.data,'base64'));
            }
        }
    }
    assert.deepEqual(errors,[],'Browser JavaScript errors');
    if(artifacts)fs.writeFileSync(path.join(artifacts,'geometry.json'),JSON.stringify(measurements,null,2));
    console.log(JSON.stringify({clicks,keyboardSelections,geometryChecks:measurements.length,exceptions:errors}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{
    try{if(ws)await call('Browser.close');}catch{}
    ws?.close();chrome?.kill();server?.kill();
    // Leave the unique temporary profile for OS cleanup; never remove a user profile.
});
