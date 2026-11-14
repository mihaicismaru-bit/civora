(()=>{
'use strict';
const D=window.PARTENER_DATA;
if(!D)return;
const MYSMIS_FRESHNESS_MS=8*60*60*1000;
const MYSMIS_REPORT_PATH='/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027';
function officialRegistryUrl(value){
 try{
  const u=new URL(value);
  return u.protocol==='https:'&&['reporting.mysmis2021.gov.ro','resurse.mysmis2021.gov.ro'].includes(u.hostname)
   &&(u.port===''||u.port==='443')&&u.pathname.replace(/\/$/,'')===MYSMIS_REPORT_PATH
   &&!u.search&&!u.hash&&!u.username&&!u.password;
 }catch{return false}
}
function registryCurrent(r){
 if(r?.status!=='OK_DIRECT'||r.directOnly!==true||r.source?.retrieval!=='CANONICAL_OFFICIAL_FETCH'||!officialRegistryUrl(r.source?.canonicalUrl))return false;
 const stamp=String(r.observedAt||'');
 if(!/(Z|[+-]\d{2}:\d{2})$/.test(stamp))return false;
 const observed=Date.parse(stamp),age=Date.now()-observed;
 return Number.isFinite(observed)&&age>=0&&age<=MYSMIS_FRESHNESS_MS;
}
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
const tokens=s=>new Set(norm(s).split(/\s+/).filter(w=>w.length>=3&&!['apel','program','proiecte','pentru','regiuni','romania','actiunea','prioritatea'].includes(w)));
const family=s=>{const x=norm(s);if(/\bpeo\b|educatie si ocupare/.test(x))return'PEO';if(/poids|\bpids\b|incluziune si demnitate/.test(x))return'PoIDS';if(/pdds|dezvoltare durabila/.test(x))return'PDDS';if(/tranzitie justa|\bptj\b/.test(x))return'PTJ';if(/regional|regiunea/.test(x))return'REGIONAL';return''};
function similarity(a,b){const A=tokens(a),B=tokens(b);if(!A.size||!B.size)return 0;let common=0;for(const t of A)if(B.has(t))common++;return common/Math.max(A.size,B.size)}
function matchCall(title,programme=''){
 const registry=D.mysmisRegistry;if(!registryCurrent(registry)||!registry.calls?.length)return null;
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
function stalePanel(r,evidence){
 const link=officialRegistryUrl(r.source?.canonicalUrl)?r.source.canonicalUrl:'https://resurse.mysmis2021.gov.ro'+MYSMIS_REPORT_PATH;
 const cls=evidence?'cw3MySMISEvidence empty':'cw3MySMISSnapshot';
 const heading=evidence?'Nu putem confirma situația acestui apel':'Nu există un snapshot oficial recent';
 const detail=evidence?'Statutul, bugetul și indicatorii MySMIS nu pot fi utilizați fără dovezi oficiale recente.':'Indicatorii și statusurile vechi sunt ascunse.';
 return '<section class="'+cls+'" data-cw3-mysmis-'+(evidence?'evidence':'snapshot')+'><div><div class="eyebrow">MySMIS — verificare expirată</div><h3>'+heading+'</h3><p>'+detail+' Ultima observație: '+esc(r.observedAt||'necunoscută')+'. Verifică starea actuală la sursa oficială.</p></div><a href="'+esc(link)+'" target="_blank" rel="noopener noreferrer">Deschide registrul oficial ↗</a></section>';
}
function snapshotPanel(){const r=D.mysmisRegistry;if(!r)return'';if(!registryCurrent(r))return stalePanel(r,false);return `<section class="cw3MySMISSnapshot" data-cw3-mysmis-snapshot><div><div class="eyebrow">Evidență directă MySMIS</div><h3>Registrul oficial verificat</h3><p>${esc(r.notice||'')}</p></div><div class="cw3MySMISMetrics"><span><b>${esc(r.validatedCallCount??'—')}</b><small>apeluri validate raportate</small></span><span><b>${esc(r.visibleRowCount??0)}</b><small>linii în snapshotul direct</small></span><span><b>${esc((r.explicitStatuses||[]).join(' · ')||'—')}</b><small>statusuri publicate literal</small></span></div><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noreferrer">Deschide registrul oficial ↗</a></section>`}
function evidencePanel(title,programme){const r=D.mysmisRegistry;if(!r)return'';if(!registryCurrent(r))return stalePanel(r,true);const found=matchCall(title,programme);if(!found)return `<section class="cw3MySMISEvidence empty" data-cw3-mysmis-evidence><div class="eyebrow">Verificare directă MySMIS</div><h3>Nicio legătură exactă în snapshotul vizibil</h3><p>Apelul nu a putut fi legat cu suficientă încredere de una dintre liniile vizibile în snapshotul direct MySMIS. <b>Absența nu este dovadă că apelul nu există.</b> Verificarea ghidului și a înregistrării MySMIS rămâne necesară.</p><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noreferrer">Caută în registrul oficial ↗</a></section>`;
 const x=found.row;
 // A programme/title similarity score is discovery, never an exact MySMIS
 // call identifier. Even EXACT_TITLE can collide across programmes/years.
 // Do not render a matched row's status, budget or operational counters until
 // the dossier and official snapshot carry the SAME exact verified call code.
 return `<section class="cw3MySMISEvidence empty" data-cw3-mysmis-evidence data-cw3-mysmis-match="candidate"><div class="eyebrow">Posibilă corespondență textuală MySMIS</div><h3>${esc(x.call)}</h3><p>${esc(x.programme)} · potrivire ${esc(found.mode)} · scor ${(found.score*100).toFixed(0)}%</p><p>Legătura este doar un indiciu de căutare: statusul literal nu înlocuiește automat statusul canonic PARTENER.EU. Fără reconcilierea codului exact de apel și a sursei oficiale actuale, statusul, bugetul și indicatorii operaționali ai acestei linii nu sunt afișați.</p><a href="${esc(r.source?.canonicalUrl)}" target="_blank" rel="noopener noreferrer">Verifică apelul exact în registrul oficial ↗</a></section>`;
}
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
