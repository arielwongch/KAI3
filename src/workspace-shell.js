/* Shared sidebar behavior for Chat, Test Benchmark, and Compare Runs. */
(()=>{
    const sidebar=document.getElementById('sidebar'),collapse=document.getElementById('collapseSidebar');
    if(!sidebar||!collapse)return;
    const triggers=[...document.querySelectorAll('[data-open-sidebar]')];
    let lastTrigger=null;
    function setOpen(open,restoreFocus=false){
        document.body.classList.toggle('sidebar-open',open);
        sidebar.inert=window.matchMedia('(max-width:720px)').matches&&!open;
        if(open){document.body.classList.remove('sidebar-collapsed');collapse.textContent='‹';collapse.setAttribute('aria-label','Collapse sidebar');collapse.setAttribute('aria-expanded','true');}
        document.querySelectorAll('.app-shell > main,.app-shell > section').forEach(content=>content.inert=open&&window.matchMedia('(max-width:720px)').matches);
        triggers.forEach(button=>button.setAttribute('aria-expanded',String(open)));
        if(open)sidebar.querySelector('[aria-current="page"]')?.focus();
        else if(restoreFocus)lastTrigger?.focus();
    }
    collapse.onclick=()=>{
        if(window.matchMedia('(max-width:720px)').matches){setOpen(false,true);return;}
        const collapsed=document.body.classList.toggle('sidebar-collapsed');
        collapse.textContent=collapsed?'›':'‹';collapse.setAttribute('aria-label',collapsed?'Expand sidebar':'Collapse sidebar');collapse.setAttribute('aria-expanded',String(!collapsed));
    };
    triggers.forEach(button=>{button.setAttribute('aria-controls','sidebar');button.setAttribute('aria-expanded','false');button.onclick=()=>{lastTrigger=button;setOpen(!document.body.classList.contains('sidebar-open'));};});
    document.getElementById('sidebarBackdrop').onclick=()=>setOpen(false,true);
    document.addEventListener('keydown',event=>{if(event.key==='Escape'&&document.body.classList.contains('sidebar-open')&&!document.querySelector('dialog[open]'))setOpen(false,true);});
    sidebar.querySelectorAll('a').forEach(link=>link.addEventListener('click',()=>setOpen(false)));
    window.addEventListener('resize',()=>{if(!window.matchMedia('(max-width:720px)').matches)setOpen(false);else sidebar.inert=!document.body.classList.contains('sidebar-open');});
    setOpen(false);
})();
