(()=>{
'use strict';
const eventLabels={CALL_OPENED:'Apel deschis',GUIDE_PUBLISHED:'Ghid publicat',GUIDE_MODIFIED:'Ghid modificat',GUIDE_UPDATED_AFTER_CONSULTATION:'Ghid final actualizat',CONSULTATION_OPENED:'Consultare publică deschisă',CONSULTATION_CLOSED:'Consultare încheiată',DEADLINE_EXTENDED:'Termen prelungit',CALL_CLOSED:'Depunere închisă',EVALUATION_UPDATE:'Evaluare în curs',RESULTS_PUBLISHED:'Rezultate publicate',CONTRACTING_UPDATE:'Contractare actualizată',CONTRACTS_PUBLISHED:'Contracte publicate',OFFICIAL_UPDATE:'Actualizare oficială'};
function simplifyNav(){document.querySelectorAll('.navlinks [data-r="changes"]').forEach(x=>x.remove())}
function humanizeEvents(){document.querySelectorAll('.kind').forEach(node=>{const raw=String(node.textContent||'').trim().toUpperCase();if(eventLabels[raw])node.textContent=eventLabels[raw]});document.querySelectorAll('[data-t="changed"]').forEach(x=>{if(/modific/i.test(x.textContent||''))x.textContent='Istoric'})}
let timer=null;function sync(){clearTimeout(timer);timer=setTimeout(()=>{simplifyNav();humanizeEvents()},40)}
const app=document.querySelector('#app')||document.body;new MutationObserver(sync).observe(app,{childList:true,subtree:true});window.addEventListener('load',sync,{once:true});setTimeout(sync,140);
})();
