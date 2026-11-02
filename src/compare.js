'use strict';
const el = id => document.getElementById(id);
const loaded = new Map(), selected = new Set();
let filenames = [];
let busy = false, pendingDelete = null, pendingRename = null;
const categoryNames = {'1':'Multi-hop','2':'Temporal','3':'Open-domain','4':'Single-hop','5':'Adversarial'};
const colors = ['#d8ed79','#82c8ef','#c6a0f6','#f6b780','#80d6bf','#f295b0'];
const finite = value => typeof value === 'number' && Number.isFinite(value);
const fmt = value => finite(value) ? value.toLocaleString(undefined,{maximumFractionDigits:2}) : 'Unavailable';
function node(tag, text, className) { const n=document.createElement(tag); if(text!=null)n.textContent=text;if(className)n.className=className;return n; }
async function api(url, options) {
    const response=await fetch(url,options);const result=await response.json();
    if(!response.ok)throw Object.assign(new Error(result.error||'Request failed.'),{status:response.status,details:result});return result;
}
function status(message,error=false){el('status').textContent=message;el('status').setAttribute('data-tone',error?'error':'info');}
function displayName(name){return /^uploads\/[a-f0-9]{32}-[^/]+$/.test(name)?name.slice(8).replace(/^[a-f0-9]{32}-/,''):name.split('/').pop();}
function sortFiles(){filenames.sort((a,b)=>displayName(a).localeCompare(displayName(b),'en',{sensitivity:'base',numeric:true})||a.localeCompare(b));}
function visibleFiles(){const query=el('search').value.trim().toLowerCase();return filenames.filter(name=>displayName(name).toLowerCase().includes(query));}
function downloadUrl(name){return '/api/results/file?path='+encodeURIComponent(name)+'&download=1';}
function updateActions(){
    el('save').disabled=busy||!selected.size;
    el('downloadSelected').disabled=busy||!selected.size;
    el('downloadSelected').textContent=selected.size?`Download selected (${selected.size})`:'Download selected';
    el('clearSelection').disabled=busy||!selected.size;
    el('selectVisible').disabled=busy||!visibleFiles().some(name=>!selected.has(name));
    el('refresh').disabled=busy;el('uploads').disabled=busy;
    el('selectedTotal').textContent=`${selected.size} file${selected.size===1?'':'s'} selected`;
    el('selectionHint').textContent=selected.size>1?'Downloads separate JSON files. Allow multiple downloads if your browser asks.':selected.size?'Downloads the selected saved JSON file.':'Choose one or more files to start comparing.';
}
function setBusy(value){busy=value;el('library').setAttribute('aria-busy',String(value));for(const control of el('library').querySelectorAll('input,button'))control.disabled=value;updateActions();}
async function loadRun(name){if(!loaded.has(name)){const result=await api('/api/results/file?analysis=1&path='+encodeURIComponent(name));loaded.set(name,result.report);}selected.add(name);}
function renderLibrary(){
    const list=el('library');list.replaceChildren();const visible=visibleFiles();
    el('libraryCount').textContent=visible.length===filenames.length?String(filenames.length):`${visible.length} / ${filenames.length}`;
    for(const name of visible){
        const line=node('div',null,'file');line.setAttribute('data-path',name);const label=node('label');const check=node('input');check.type='checkbox';check.checked=selected.has(name);check.disabled=busy;check.setAttribute('aria-label','Compare '+displayName(name));
        check.onchange=async()=>{
            if(busy)return;
            if(!check.checked){selected.delete(name);render();return;}
            setBusy(true);status('Loading '+displayName(name)+'…');
            try{await loadRun(name);status('Selected '+displayName(name));}
            catch(error){status(displayName(name)+': '+error.message,true);}
            finally{check.checked=selected.has(name);setBusy(false);render();check.focus();}
        };
        const copy=node('span',null,'file-copy');copy.append(node('span',displayName(name),'file-name'),node('small','Saved JSON'));
        label.append(check,copy);const actions=node('div',null,'file-actions');
        const rename=node('button','Rename');rename.type='button';rename.disabled=busy;rename.setAttribute('aria-label','Rename '+displayName(name));rename.onclick=()=>{pendingRename=name;el('renameCurrent').textContent=displayName(name);el('renameName').value=displayName(name);el('renameError').textContent='';el('renameDialog').showModal();el('renameName').focus();el('renameName').select();};actions.append(rename);
        const remove=node('button','Delete','delete-file');remove.type='button';remove.disabled=busy;remove.setAttribute('aria-label','Delete '+displayName(name));remove.onclick=()=>{pendingDelete=name;el('deleteFilename').textContent=displayName(name);el('deleteDialog').returnValue='';el('deleteDialog').showModal();el('cancelDelete').focus();};actions.append(remove);
        line.append(label,actions);list.append(line);
    }
    if(!list.childElementCount){const empty=node('div',null,'empty-state');empty.append(node('h3',filenames.length?'No matching files':'Build your result library'),node('p',filenames.length?'Try another filename or clear your search.':'Upload benchmark JSON files to start your first comparison.'));list.append(empty);}
    updateActions();
}
async function refresh(){const result=await api('/api/results');filenames=result.files;sortFiles();for(const name of selected)if(!filenames.includes(name)){selected.delete(name);loaded.delete(name);}renderLibrary();render();}
function rows(){
    const data=[...selected].flatMap(name=>{
        const report=loaded.get(name);return (report?.comparison?.rows||[]).map(row=>({
            ...row,name,report,label:displayName(name).replace(/\.json$/i,'')+' · '+row.module,
            metrics:el('category').value==='overall'?row.overall:row.categories[el('category').value]||{}
        }));
    });
    return sortRows(data,'name','asc').map((row,index)=>({...row,runNumber:index+1,color:colors[index%colors.length]}));
}
function sortRows(data,field,direction){
    const sign=direction==='desc'?-1:1;
    const value=row=>field==='completion'?row.metrics.completion_percent:row.categories[field.slice(9)]?.accuracy_percent;
    return [...data].sort((a,b)=>{
        if(field==='name')return sign*(a.label.localeCompare(b.label,'en',{sensitivity:'base',numeric:true})||a.name.localeCompare(b.name));
        const av=value(a),bv=value(b);
        if(!finite(av)||!finite(bv))return finite(av)?-1:finite(bv)?1:0;
        return sign*(av-bv);
    });
}
function svgNode(tag, attrs={}, text){const n=document.createElementNS('http://www.w3.org/2000/svg',tag);for(const [key,value]of Object.entries(attrs))n.setAttribute(key,String(value));if(text!=null)n.textContent=text;return n;}
let activeChartPoint=null;
function hideChartTooltip(){el('chartTooltip').hidden=true;activeChartPoint=null;}
function positionChartTooltip(point,event){
    const tooltip=el('chartTooltip'),anchor=point.getBoundingClientRect();
    const x=event?.clientX??anchor.right,y=event?.clientY??anchor.top+anchor.height/2;
    const {width,height}=tooltip.getBoundingClientRect(),gap=14,edge=12;
    const left=x+gap+width>window.innerWidth-edge?x-width-gap:x+gap;
    const top=y+gap+height>window.innerHeight-edge?y-height-gap:y+gap;
    tooltip.style.left=Math.max(edge,Math.min(left,window.innerWidth-width-edge))+'px';
    tooltip.style.top=Math.max(edge,Math.min(top,window.innerHeight-height-edge))+'px';
}
function chartDetails(row,kind){
    const m=row.metrics,overall=row.overall;
    const details=[['Question type',kind==='storage'?'All question types (run total)':categoryNames[el('category').value]||'All question types']];
    if(kind==='accuracy')details.push(['Judged / selected',`${fmt(m.judged_count)} / ${fmt(m.selected_count)}`],['Judge completion',finite(m.completion_percent)?fmt(m.completion_percent)+'%':'Unavailable']);
    if(kind==='tokens')details.push(['Cases with token usage',`${fmt(m.token_count)} / ${fmt(m.case_count)}`],['Total question tokens',fmt(m.total_question_tokens)]);
    if(kind==='runtime')details.push(['Cases with runtime',`${fmt(m.runtime_count)} / ${fmt(m.case_count)}`],['Total question runtime',finite(m.total_question_seconds)?fmt(m.total_question_seconds)+' s':'Unavailable']);
    if(kind==='storage')details.push(['Stored text bytes',fmt(overall.stored_text_bytes)],['Measured snapshots',`${fmt(overall.storage_count)} / ${fmt(overall.memory_count)}`]);
    if((kind==='tokens'||kind==='runtime')&&overall.lifecycle){const l=overall.lifecycle;details.push(['Recorded lifecycle tokens (all types)',fmt(l.total_provider_tokens)],['Recorded lifecycle runtime (all types)',finite(l.total_seconds)?fmt(l.total_seconds)+' s':'Unavailable'],['Ingestion builds',fmt(l.ingestion_count)],['Request ledger',l.request_ledger_complete?'Complete for recorded attempts':'Partial / legacy']);}
    return details;
}
const chartMetrics={
    tokens:{label:'Tokens per question',unit:'tokens',value:r=>r.metrics.mean_question_tokens,note:'Mean answer + judge tokens per recorded question. Excludes ingestion.'},
    accuracy:{label:'Judged accuracy',unit:'%',value:r=>r.metrics.accuracy_percent,note:'Correct / judged questions. Unjudged questions are excluded.'},
    storage:{label:'Stored memory text',unit:'KiB',value:r=>finite(r.overall.stored_text_bytes)?r.overall.stored_text_bytes/1024:null,note:'Final UTF-8 memory text across the run. Excludes embeddings and runtime overhead.'},
    runtime:{label:'Runtime per question',unit:'s',value:r=>r.metrics.mean_question_seconds,note:'Mean recorded question time, including judging. Excludes ingestion.'}
};
function metricValue(row,key){const metric=chartMetrics[key],value=metric.value(row);return finite(value)?fmt(value)+' '+metric.unit:'Unavailable';}
function showChartTooltip(point,row,xKey,yKey,peers,event){
    const tooltip=el('chartTooltip');activeChartPoint=point;
    const details=node('dl');
    for(const [axis,key] of [['X',xKey],['Y',yKey]]){
        details.append(node('dt',axis+' · '+chartMetrics[key].label),node('dd',metricValue(row,key)));
        for(const [label,value] of chartDetails(row,key))details.append(node('dt',axis+' · '+label),node('dd',value));
    }
    tooltip.replaceChildren(node('span',`Run ${row.runNumber}`,'tooltip-kicker'),node('strong',displayName(row.name),'tooltip-name'),node('span',row.module,'tooltip-module'),details);
    for(const key of new Set([xKey,yKey]))tooltip.append(node('p',chartMetrics[key].note,'tooltip-note'));
    if(peers.length>1)tooltip.append(node('p','Also at these coordinates: '+peers.filter(peer=>peer!==row).map(peer=>`Run ${peer.runNumber}: ${peer.label}`).join('; '),'tooltip-note'));
    tooltip.hidden=false;positionChartTooltip(point,event);
}
document.addEventListener('keydown',event=>{if(event.key==='Escape')hideChartTooltip();});
document.addEventListener('pointerdown',event=>{if(activeChartPoint&&!activeChartPoint.contains(event.target)&&!el('chartTooltip').contains(event.target))hideChartTooltip();});
window.addEventListener('scroll',hideChartTooltip,true);
window.addEventListener('resize',hideChartTooltip);
function chart(data,xKey,yKey){
    const xMetric=chartMetrics[xKey],yMetric=chartMetrics[yKey];
    const card=node('article',null,'chart');
    card.append(node('h3',xMetric.label+' vs '+yMetric.label),node('p','Each point is a run. Hover, focus, or tap for both values and coverage.'));
    el('charts').replaceChildren(card);
    if(!data.length)return;
    const plotted=data.filter(row=>finite(xMetric.value(row))&&finite(yMetric.value(row)));
    const upper=(key,metric)=>{
        if(key==='accuracy')return 100;
        const target=Math.max(0,...plotted.map(metric.value))*(1+Number(el('headroom').value)/100);
        const step=target?10**Math.floor(Math.log10(target))/2:0.25;
        return Math.max(step,Math.ceil(target/step)*step);
    };
    const xMax=upper(xKey,xMetric),yMax=upper(yKey,yMetric),height=380;
    const svg=svgNode('svg',{height,role:'group','aria-label':`Scatter plot; X: ${xMetric.label}, axis from 0 to ${fmt(xMax)} ${xMetric.unit}; Y: ${yMetric.label}, axis from 0 to ${fmt(yMax)} ${yMetric.unit}`});
    card.append(svg);
    // No viewBox: SVG coordinates and font sizes stay in CSS pixels at every width.
    const width=svg.getBoundingClientRect().width,left=60,right=24,top=24,bottom=60;
    const plotWidth=width-left-right,plotHeight=height-top-bottom;
    const tick=value=>value.toLocaleString('en-US',{notation:'compact',maximumFractionDigits:1});
    for(let i=0;i<=4;i++){
        const x=left+plotWidth*i/4,y=top+plotHeight-plotHeight*i/4;
        svg.append(svgNode('line',{x1:x,y1:top,x2:x,y2:height-bottom,class:'grid'}),svgNode('text',{x,y:height-bottom+20,'text-anchor':'middle'},tick(xMax*i/4)),
                   svgNode('line',{x1:left,y1:y,x2:width-right,y2:y,class:'grid'}),svgNode('text',{x:left-10,y:y+4,'text-anchor':'end'},tick(yMax*i/4)));
    }
    const label=metric=>metric.label+(metric.unit==='tokens'?'':' ('+metric.unit+')');
    svg.append(svgNode('text',{x:left+plotWidth/2,y:height-12,'text-anchor':'middle',class:'axis-label'},label(xMetric)),
               svgNode('text',{x:14,y:top+plotHeight/2,transform:`rotate(-90 14 ${top+plotHeight/2})`,'text-anchor':'middle',class:'axis-label'},label(yMetric)));
    const coordinates=new Map();
    for(const row of plotted){const key=JSON.stringify([xMetric.value(row),yMetric.value(row)]);if(!coordinates.has(key))coordinates.set(key,[]);coordinates.get(key).push(row);}
    const unavailable=node('div',null,'chart-unavailable');
    for(const row of data){
        const x=xMetric.value(row),y=yMetric.value(row),measured=finite(x)&&finite(y);
        const point=measured?svgNode('g',{tabindex:0,role:'img'}):node('button',`Run ${row.runNumber}: ${row.label} · Unavailable`,'chart-missing');
        point.setAttribute('class',measured?'chart-point':'chart-point chart-missing');
        point.setAttribute('data-path',row.name);point.setAttribute('data-module',row.module);
        point.setAttribute('aria-label',`Run ${row.runNumber}: ${row.label}; X: ${xMetric.label}: ${metricValue(row,xKey)}; Y: ${yMetric.label}: ${metricValue(row,yKey)}`);
        point.setAttribute('aria-describedby','chartTooltip');
        const peers=measured?coordinates.get(JSON.stringify([x,y])):[];
        const show=event=>showChartTooltip(point,row,xKey,yKey,peers,event);
        point.onpointerenter=show;point.onpointermove=event=>{if(activeChartPoint===point)positionChartTooltip(point,event);};
        point.onpointerleave=()=>{if(document.activeElement===point){positionChartTooltip(point);return;}if(activeChartPoint===point)hideChartTooltip();};
        point.onfocus=()=>show();point.onblur=()=>{if(activeChartPoint===point)hideChartTooltip();};point.onclick=show;
        if(measured){
            const cx=left+plotWidth*x/xMax,cy=height-bottom-plotHeight*y/yMax;
            point.append(svgNode('circle',{cx,cy,r:12,fill:'transparent',class:'chart-hit-target'}),svgNode('circle',{cx,cy,r:5,fill:row.color,class:'chart-dot'}));svg.append(point);
        }else{point.type='button';unavailable.append(point);}
    }
    if(unavailable.childElementCount){card.append(node('p','Not plotted: a selected measurement is unavailable.'),unavailable);}
}
function tableCell(row,text,small){const td=node('td',text);if(small)td.append(node('small',small));row.append(td);}
function render(){
    hideChartTooltip();
    const data=rows(),category=el('category').value;
    const tableSort=el('tableSort').value||'name',tableOrder=el('tableOrder').value||'asc';
    const tableData=sortRows(data,tableSort,tableOrder);
    updateActions();
    el('selectionCount').textContent=`${selected.size} files selected · ${data.length} conditions · ${categoryNames[category]||'All question types'}`;
    el('comparisonEmpty').hidden=!!data.length;
    el('comparisonEmpty').children[1].textContent=selected.size?'No comparison conditions found':'Your comparison starts here';
    el('comparisonEmpty').children[2].textContent=selected.size?'The selected files contain no recorded conditions. Choose results with benchmark cases.':'Select results from your library above. Each condition gets a consistent color across axis choices.';
    el('charts').hidden=!data.length;
    el('chartHint').hidden=!data.length;
    const legend=el('runLegend');legend.replaceChildren();
    data.forEach(row=>{const item=node('span',null,'legend-item'),swatch=node('span',null,'swatch');swatch.style.backgroundColor=row.color;item.append(swatch,node('strong',`Run ${row.runNumber}`),node('span',row.label));legend.append(item);});
    chart(data,el('chartX').value||'tokens',el('chartY').value||'accuracy');
    const types=el('types');types.replaceChildren();const head=node('thead'),hr=node('tr');
    const headings=[['name','Run'],...Object.entries(categoryNames).map(([key,title])=>['category:'+key,title]),['completion','Judge completion (filter)']];
    for(const [key,title] of headings){const th=node('th',title);th.setAttribute('scope','col');if(key===tableSort)th.setAttribute('aria-sort',tableOrder==='desc'?'descending':'ascending');hr.append(th);}head.append(hr);types.append(head);const body=node('tbody');
    tableData.forEach(row=>{
        const tr=node('tr');tableCell(tr,`Run ${row.runNumber}: ${row.label}`,`${row.report.status||'Unknown status'} · ${row.report.protocol||'Unknown protocol'}`);
        for(const key of Object.keys(categoryNames)){const m=row.categories[key];tableCell(tr,m&&finite(m.accuracy_percent)?fmt(m.accuracy_percent)+'%':'Unavailable',m?`${m.judged_count} judged / ${m.selected_count} selected`:null);}
        tableCell(tr,finite(row.metrics.completion_percent)?fmt(row.metrics.completion_percent)+'%':'Unavailable',`${row.metrics.judged_count??0} judged / ${row.metrics.selected_count??0} selected`);body.append(tr);
    });if(!data.length){const tr=node('tr'),td=node('td','Select results to compare accuracy by question type.','empty-cell');td.colSpan=7;tr.append(td);body.append(tr);}types.append(body);
    const coverage=node('table'),ch=node('tr');for(const title of ['Run','Token coverage','Runtime coverage','Storage coverage'])ch.append(node('th',title));coverage.append(ch);
    data.forEach(row=>{const tr=node('tr');tableCell(tr,`Run ${row.runNumber}: ${row.label}`);tableCell(tr,`${row.metrics.token_count??0} / ${row.metrics.case_count??0} cases`);tableCell(tr,`${row.metrics.runtime_count??0} / ${row.metrics.case_count??0} cases`);tableCell(tr,`${row.overall.storage_count} / ${row.overall.memory_count} snapshots`);coverage.append(tr);});
    const lifecycle=node('table'),lh=node('tr');for(const title of ['Run (all question types)','Ingestion tokens','Answer tokens','Judge tokens','Lifecycle tokens','Lifecycle seconds','Request ledger'])lh.append(node('th',title));lifecycle.append(lh);
    data.forEach(row=>{const tr=node('tr'),l=row.overall.lifecycle;tableCell(tr,`Run ${row.runNumber}`);for(const phase of ['ingestion','answer','judge'])tableCell(tr,fmt(l?.[phase]?.tokens),l?`${l[phase].known_count} / ${l[phase].record_count} records with usage`:null);tableCell(tr,fmt(l?.total_provider_tokens));tableCell(tr,fmt(l?.total_seconds));tableCell(tr,l?.request_ledger_complete?'Complete for recorded attempts':'Partial / legacy');lifecycle.append(tr);});
    el('coverage').replaceChildren(coverage,lifecycle);
}
function chooseDuplicate(file,conflict,index,total){
    const dialog=el('duplicateDialog'),target=el('replaceTarget');
    el('duplicateProgress').textContent=`UPLOAD ${index} OF ${total} · FILENAME CONFLICT`;
    el('duplicateFilename').textContent=file.name;
    el('duplicateNewName').textContent='Save as '+conflict.duplicate_name;
    target.replaceChildren();for(const path of conflict.conflicts){const option=node('option',path);option.value=path;target.append(option);}target.value=conflict.conflicts[0];
    dialog.returnValue='';
    return new Promise(resolve=>{
        dialog.onclose=()=>resolve({action:['duplicate','replace'].includes(dialog.returnValue)?dialog.returnValue:'skip',path:target.value});
        dialog.showModal();el('skipDuplicate').focus();
    });
}
async function uploadResult(file,index,total){
    let choice={action:'ask'};
    while(true){
        const form=new FormData();form.append('file',file);form.append('action',choice.action);
        if(choice.action==='replace')form.append('replace_path',choice.path);
        try{return await api('/api/results/import',{method:'POST',body:form});}
        catch(error){
            if(error.status!==409||!Array.isArray(error.details?.conflicts))throw error;
            // A target removed by another tab no longer needs a conflict prompt.
            if(!error.details.conflicts.length){choice={action:'ask'};continue;}
            status('Waiting for your choice for '+file.name+'…');
            choice=await chooseDuplicate(file,error.details,index,total);
            if(choice.action==='skip')return null;
            status('Saving '+file.name+'…');
        }
    }
}
el('uploads').onchange=async()=>{
    if(busy)return;const input=el('uploads'),files=[...input.files];if(!files.length)return;setBusy(true);let successes=0,skipped=0,replaced=0;const errors=[];
    for(const [index,file] of files.entries()){
        status(`Saving ${file.name} (${index+1} of ${files.length})…`);
        try{const result=await uploadResult(file,index+1,files.length);if(!result){skipped++;continue;}loaded.set(result.path,result.report);selected.add(result.path);successes++;if(result.replaced)replaced++;}
        catch(error){errors.push(file.name+': '+error.message);}
    }
    try{await refresh();if(successes){el('search').value='';renderLibrary();}}catch(error){errors.push(error.message);}finally{input.value='';setBusy(false);render();}
    status(`${successes} file(s) saved and selected · ${replaced} replaced · ${skipped} skipped. ${errors.join(' ')}`,!!errors.length);
};
el('save').onclick=async()=>{
    if(busy)return;setBusy(true);const errors=[];let count=0;
    for(const name of [...selected]){try{const result=await api('/api/results/enrich',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:name})});loaded.set(name,result.report);count++;}catch(error){errors.push(name+': '+error.message);}}
    setBusy(false);render();status(`${count} JSON file(s) updated with computed metrics. ${errors.join(' ')}`,!!errors.length);
};
el('selectVisible').onclick=async()=>{
    if(busy)return;const names=visibleFiles().filter(name=>!selected.has(name));setBusy(true);const errors=[];
    for(const name of names){try{await loadRun(name);}catch(error){errors.push(displayName(name)+': '+error.message);}}
    setBusy(false);renderLibrary();render();status(errors.length?errors.join(' '):`${selected.size} files selected.`,!!errors.length);
};
el('clearSelection').onclick=()=>{if(busy)return;selected.clear();renderLibrary();render();status('Selection cleared.');};
el('downloadSelected').onclick=async()=>{
    if(busy||!selected.size)return;const names=[...selected];
    setBusy(true);let count=0;const errors=[];
    for(const name of names){
        status('Preparing '+displayName(name)+'…');
        try{
            const response=await fetch(downloadUrl(name));
            if(!response.ok){const error=await response.json();throw new Error(error.error||'Download failed.');}
            const url=URL.createObjectURL(await response.blob()),link=node('a');link.href=url;link.download=displayName(name);link.click();setTimeout(()=>URL.revokeObjectURL(url),60000);count++;
        }catch(error){errors.push(displayName(name)+': '+error.message);}
    }
    setBusy(false);status(`Requested ${count} separate JSON download(s). ${errors.join(' ')}`,!!errors.length);
};
el('renameForm').onsubmit=async event=>{
    event.preventDefault();if(busy||!pendingRename)return;const previous=pendingRename;
    setBusy(true);el('renameSubmit').disabled=true;el('renameCancel').disabled=true;el('renameError').textContent='';
    try{
        const result=await api('/api/results/rename',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({path:previous,name:el('renameName').value})});
        if(loaded.has(previous)){const report=loaded.get(previous);loaded.delete(previous);loaded.set(result.path,report);}
        const names=[...selected].map(name=>name===previous?result.path:name);selected.clear();for(const name of names)selected.add(name);
        filenames=filenames.map(name=>name===previous?result.path:name);sortFiles();renderLibrary();render();el('renameDialog').close();status('Renamed to '+displayName(result.path));
    }catch(error){el('renameError').textContent=error.message;el('renameName').focus();}
    finally{setBusy(false);el('renameSubmit').disabled=false;el('renameCancel').disabled=false;}
};
el('renameCancel').onclick=()=>el('renameDialog').close();
el('renameDialog').onclose=()=>{if(!el('renameDialog').open)pendingRename=null;};
el('deleteDialog').onclose=async()=>{
    const name=pendingDelete;pendingDelete=null;if(el('deleteDialog').returnValue!=='delete'||!name||busy)return;
    setBusy(true);
    try{await api('/api/results/file?path='+encodeURIComponent(name),{method:'DELETE'});selected.delete(name);loaded.delete(name);filenames=filenames.filter(file=>file!==name);renderLibrary();render();status('Deleted '+displayName(name));}
    catch(error){status(error.message,true);}finally{setBusy(false);el('search').focus();}
};
el('refresh').onclick=async()=>{if(busy)return;setBusy(true);try{await refresh();status('Library refreshed.');}catch(error){status(error.message,true);}finally{setBusy(false);}};
el('search').oninput=renderLibrary;el('category').onchange=render;el('headroom').onchange=render;
el('chartX').onchange=render;el('chartY').onchange=render;
el('tableSort').onchange=()=>{el('tableOrder').value=el('tableSort').value==='name'?'asc':'desc';render();};
el('tableOrder').onchange=render;
setBusy(true);refresh().then(()=>status('Select saved results or upload JSON files.')).catch(error=>status(error.message,true)).finally(()=>setBusy(false));

let chartContainerWidth=0;
new ResizeObserver(([entry])=>{
    const width=Math.round(entry.contentRect.width);
    if(width!==chartContainerWidth){chartContainerWidth=width;render();}
}).observe(el('charts'));
