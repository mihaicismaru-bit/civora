(()=>{
'use strict';
const L=window.PARTENER_CALL_LIFECYCLE;
if(!L||!Array.isArray(L.calls))return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const norm=s=>String(s||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const stages=[['DISCOVERED','Identificat'],['CONSULTATION','Consultare'],['FINAL_GUIDE','Ghid final'],['ANNOUNCED','Anunțat'],['OPEN','Depunere'],['CLOSED','Închis'],['EVALUATION','Evaluare'],['RESULTS','Rezultate'],['CONTRACTING','Contractare'],['COMPLETED','Finalizat']];
function findCall(){const h=document.querySelector('.diDossierHero h1');if(!h)return null;const title=norm(h.textContent);return L.calls.find(x=>norm(x.title)===title)||null}
function metric(label,value){return `<div><small>${esc(label)}</small><b>${esc(value??'Neconfirmat')}</b></div>`}
function render(){
 const hero=document.querySelector('.diDossierHero');if(!hero||document.querySelector('[data-call-lifecycle]'))return;
 const call=findCall();if(!call)return;
 const panel=document.createElement('section');panel.className='clPanel';panel.dataset.callLifecycle='1';
 const current=call.maturityRank??0;
 const m=call.results?.mysmis;
 const winners=call.results?.winnerSources||[];
 panel.innerHTML=`<div class="clHead"><div><span>Parcursul apelului</span><h2>${esc(call.stageLabel)}</h2><p>Urmărire de la prima identificare până la rezultate și contractare. Etapele avansează numai pe evidență oficială.</p></div><div class="clPriority">Monitorizare ${esc(call.monitoring?.priority==='HIGH'?'ridicată':call.monitoring?.priority==='MEDIUM'?'medie':'redusă')}</div></div><div class="clRail">${stages.map(([id,label],i)=>`<div class="${i<current?'done':i===current?'current':'future'}"><i>${i<current?'✓':i+1}</i><span>${esc(label)}</span></div>`).join('')}</div><div class="clGrid"><div class="clBlock"><h3>Ce urmărim în continuare</h3><ul>${(call.monitoring?.nextExpectedEvents||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div><div class="clBlock"><h3>Rezultate și contractare</h3>${m?`<div class="clMetrics">${metric('Proiecte depuse',m.submitted)}${metric('Contracte',m.contracts)}${metric('Retrase',m.withdrawn)}</div><small class="clNote">Date agregate din registrul public MySMIS. Nu reprezintă lista nominală de câștigători.</small>`:'<p>Nu există încă o asociere suficient de sigură cu registrul public MySMIS.</p>'}${winners.length?`<div class="clWinnerSources"><b>Surse oficiale pentru rezultate / beneficiari</b>${winners.map(s=>`<a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.label||'Sursă oficială')} ↗</a>`).join('')}</div>`:'<div class="clUnknown">Lista nominală de câștigători nu este încă confirmată.</div>'}</div></div><details class="clHistory"><summary>Istoricul etapelor</summary>${(call.transitions||[]).map(t=>`<div><span>${esc(t.observedAt||'')}</span><b>${esc(t.from?`${t.from} → ${t.to}`:t.to)}</b></div>`).join('')}</details>`;
 hero.insertAdjacentElement('afterend',panel);
}
const obs=new MutationObserver(()=>setTimeout(render,0));obs.observe(document.getElementById('app'),{childList:true,subtree:true});
window.addEventListener('load',render,{once:true});setTimeout(render,200);
})();
