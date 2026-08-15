(()=>{
'use strict';
const D=window.PARTENER_DATA;
if(!D)return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
const tokens=s=>new Set(norm(s).split(/\s+/).filter(w=>w.length>=3&&!['apel','program','proiecte','pentru','regiuni','romania','actiunea','prioritatea'].includes(w)));
const family=s=>{const x=norm(s);if(/\bpeo\b|educatie si ocupare/.test(x))return'PEO';if(/poids|\bpids\b|incluziune si demnitate/.test(x))return'PoIDS';if(/pdds|dezvoltare durabila/.test(x))return'PDDS';if(/tranzitie justa|\bptj\b/.test(x))return'PTJ';if(/regional|regiunea/.test(x))return'REGIONAL';return''};
function similarity(a,b){const A=tokens(a),B=tokens(b);if(!A.size||!B.size)return 0;let common=0;for(const t of A)if(B.has(t))common++;return common/Math.max(A.size,B.size)}
function matchCall(title,programme=''){
 const registry=D.mysmisRegistry;if(!registry?.calls?.length)return null;
 const nt=norm(title),pf=family(programme);
 let best=null;
 for(const row of registry.calls){
  const nr=norm(row.call),rf=family(row.programme);
  if(pf&&rf&&pf!==rf)continue;
  let score=similarity(title,row.call);
  let mode='TOKEN_MATCH';
  if(nt===nr){score=1;mode='EXACT_TITLE'}
  else if(Math.min(nt.length,nr.length)>=45&&(nt.includes(nr)||nr.includes(nt))){score=Math.max(score,.92);mode='TITLE_CONTAINMENT'}
  if(!best||score>best.score)best={row,score,mode};
 }
 return best&&best.score>=.74?best:null;
}
function snapshotPanel(){const r=D.mysmisRegistry;if(!r)return'';return `<section class="cw3MySMISSnapshot" data-cw3-mysmis-snapshot><div><div class="eyebrow">Evidență directă MySMIS</div><h3>Registrul oficial verificat</h3><p>${esc(r.notice||'')}</p></div><div class="cw3MySMISMetrics"><span><b>${esc(r.validatedCallCount??'—')}</b><small>apeluri validate raportate</small></span><span><b>${esc(r.visibleRowCount??0)}</b><small>linii în snapshotul direct</small></span><span><b>${esc((r.explicitStatuses||[]).join(' · ')||'—')}</b><small>statusuri publicate literal</small></span></div><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noreferrer">Deschide registrul oficial ↗</a></section>`}
function evidencePanel(title,programme){const r=D.mysmisRegistry;if(!r)return'';const found=matchCall(title,programme);if(!found)return `<section class="cw3MySMISEvidence empty" data-cw3-mysmis-evidence><div class="eyebrow">Verificare directă MySMIS</div><h3>Nicio legătură exactă în snapshotul vizibil</h3><p>Apelul nu a putut fi legat cu suficientă încredere de una dintre liniile vizibile în snapshotul direct MySMIS. <b>Absența nu este dovadă că apelul nu există.</b> Verificarea ghidului și a înregistrării MySMIS rămâne necesară.</p><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noreferrer">Caută în registrul oficial ↗</a></section>`;
 const x=found.row;return `<section class="cw3MySMISEvidence" data-cw3-mysmis-evidence><div class="cw3MySMISTop"><div><div class="eyebrow">Verificare directă MySMIS</div><h3>${esc(x.call)}</h3><p>${esc(x.programme)} · legătură ${esc(found.mode)} · scor ${(found.score*100).toFixed(0)}%</p></div><span class="cw3MySMISStatus">${esc(x.officialStatus||'NEPRECIZAT')}</span></div><div class="cw3MySMISFacts"><span><small>Entități</small><b>${esc(x.entities||'—')}</b></span><span><small>Depuse</small><b>${esc(x.submitted||'—')}</b></span><span><small>Contracte</small><b>${esc(x.contracts||'—')}</b></span><span><small>Buget apel (lei)</small><b>${esc(x.callBudgetRon||'—')}</b></span></div><p class="cw3MySMISWarning">Statusul este redat literal din MySMIS și nu înlocuiește automat statusul canonic PARTENER.EU fără reconciliere editorială.</p><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noreferrer">Sursa oficială directă ↗</a></section>`}
function inject(){
 const root=document.querySelector('.cw3Root');if(!root)return;
 const dash=root.querySelector('.cw3DashboardGrid');if(dash&&!root.querySelector('[data-cw3-mysmis-snapshot]'))dash.insertAdjacentHTML('beforebegin',snapshotPanel());
 const hero=root.querySelector('.cw3DossierHero');if(hero&&!root.querySelector('[data-cw3-mysmis-evidence]')){
  const title=hero.querySelector('h1')?.textContent||'';
  const programme=hero.querySelector('p')?.textContent||'';
  hero.insertAdjacentHTML('afterend',evidencePanel(title,programme));
 }
}
const obs=new MutationObserver(inject);obs.observe(document.getElementById('app'),{childList:true,subtree:true});inject();
})();
