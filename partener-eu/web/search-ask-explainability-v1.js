(()=>{
'use strict';

const api={version:'search-ask-explainability-v1'};
const OPEN_PROOF_MISSING='Identificator exact + endpoint oficial curent + status OPEN explicit + reconciliere semantică';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const asArray=v=>Array.isArray(v)?v:[];
const upper=v=>String(v||'').toUpperCase();
const officialTier=v=>/^T1(?:B)?(?:\b|_)/i.test(String(v||'').trim());

function asTime(value){
  if(value==null||value==='')return null;
  const t=new Date(value).getTime();
  return Number.isFinite(t)?t:null;
}
function freshnessState(value,now=Date.now()){
  const home=window.PARTENER_HOME_FRESHNESS_EXPLAINABILITY;
  if(home&&typeof home.freshnessState==='function')return home.freshnessState(value,now);
  const t=asTime(value);if(t==null)return {state:'UNKNOWN',label:'Dată neconfirmată'};
  const hours=Math.max(0,(now-t)/36e5);
  if(hours<=24)return {state:'FRESH',label:'Observație recentă'};
  if(hours<=168)return {state:'CURRENT',label:'Verificat în ultimele 7 zile'};
  return {state:'STALE',label:'Necesită revalidare'};
}
function formatObserved(value){
  const t=asTime(value);if(t==null)return 'dată neconfirmată';
  try{return new Intl.DateTimeFormat('ro-RO',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(t));}
  catch{return String(value)}
}
function hostLabel(url){try{return new URL(String(url||'')).hostname.replace(/^www\./,'')}catch{return ''}}
function normalizedSource(raw){
  if(typeof raw==='string')return {url:raw,label:hostLabel(raw)||'Sursă atașată',observedAt:null,tier:''};
  if(!raw||typeof raw!=='object')return {url:'',label:'Sursă atașată',observedAt:null,tier:''};
  const url=raw.url||raw.href||raw.source_url||raw.authority_url||'';
  return {
    url,
    label:raw.label||raw.name||raw.authority||raw.publisher||raw.source_name||hostLabel(url)||'Sursă atașată',
    observedAt:raw.fetched_at||raw.fetchedAt||raw.observed_at||raw.observedAt||raw.date||null,
    tier:raw.tier||raw.sourceTier||raw.authority_class||'',
  };
}
function callSource(c){return normalizedSource(asArray(c?.sourceFacts)[0]||c?.source||null)}
function dossierSource(d){
  const sources=asArray(d?.sources).filter(Boolean);
  const official=sources.find(s=>officialTier(s?.tier||s?.sourceTier));
  return normalizedSource(official||sources[0]||d?.source||null);
}
function callObservation(c,data){
  const src=callSource(c);
  return c?.observedAt||c?.observed_at||c?.updatedAt||c?.updated_at||src.observedAt||data?.asOf||null;
}
function dossierObservation(d,products){
  const src=dossierSource(d);
  return d?.observedAt||d?.observed_at||d?.updatedAt||d?.updated_at||d?.publishedAt||d?.published_at||src.observedAt||products?.freshnessGuard?.asOf||products?.generatedAt||null;
}
function verifiedClasses(c){return new Set(asArray(c?.p11VerifiedFactClasses).map(x=>String(x||'').toLowerCase()))}
function callConfidence(c){
  const status=upper(c?.status),verified=verifiedClasses(c);
  if(status==='OPEN'&&verified.has('status')&&verified.has('deadline'))return {state:'HIGH',label:'Ridicată · status și termen confirmate'};
  if(['EXPECTED','PUBLIC_CONSULTATION','REVIEW','UPCOMING','ANNOUNCED','PLANNED','DISCOVERED'].includes(status))return {state:'PIPELINE',label:'Non-OPEN · în pregătire sau monitorizare'};
  return {state:'REVIEW',label:'În verificare'};
}
function callMissing(c){
  const status=upper(c?.status),verified=verifiedClasses(c);
  if(status==='OPEN'&&verified.has('status')&&verified.has('deadline'))return 'Eligibilitatea concretă a solicitantului trebuie verificată în dosarul oficial.';
  if(status==='OPEN')return 'Confirmarea materială a statusului și termenului în proiecția verificată.';
  return OPEN_PROOF_MISSING;
}
function callLane(c){
  const status=upper(c?.status),verified=verifiedClasses(c);
  if(status==='OPEN'&&verified.has('status')&&verified.has('deadline'))return 'OPEN_CONFIRMED_ONLY';
  if(['PROGRAMMING','PROGRAMMING_PROCESS','PROPOSAL','CONSULTATION','PLANNED'].includes(status))return 'PROGRAMMING_NON_AUTHORIZING';
  return 'UPCOMING_OR_REVIEW';
}
function dossierConfidence(d){
  const home=window.PARTENER_HOME_FRESHNESS_EXPLAINABILITY;
  if(home&&typeof home.dossierConfidence==='function')return home.dossierConfidence(d);
  const status=upper(d?.status);
  if(['EXPECTED','PUBLIC_CONSULTATION','REVIEW','UPCOMING','ANNOUNCED','PLANNED'].includes(status))return {state:'PIPELINE',label:'Non-OPEN · în pregătire'};
  return {state:'REVIEW',label:'În verificare'};
}
function dossierMissing(d){
  const home=window.PARTENER_HOME_FRESHNESS_EXPLAINABILITY;
  if(home&&typeof home.dossierMissing==='function')return home.dossierMissing(d);
  return upper(d?.status)==='OPEN'?'Eligibilitatea concretă trebuie verificată în dosarul oficial.':OPEN_PROOF_MISSING;
}
function callModel(c,data,now=Date.now()){
  const source=callSource(c),observedAt=callObservation(c,data),freshness=freshnessState(observedAt,now),confidence=callConfidence(c);
  return {id:String(c?.id||''),lane:callLane(c),source,observedAt,freshness,confidence,missing:callMissing(c),materialAuthorization:false};
}
function dossierModel(d,products,now=Date.now()){
  const source=dossierSource(d),observedAt=dossierObservation(d,products),freshness=freshnessState(observedAt,now),confidence=dossierConfidence(d);
  return {id:String(d?.id||''),source,observedAt,freshness,confidence,missing:dossierMissing(d),materialAuthorization:false};
}
api.callModel=callModel;
api.dossierModel=dossierModel;
api.freshnessState=freshnessState;
api.openProofMissing=OPEN_PROOF_MISSING;
window.PARTENER_SEARCH_ASK_EXPLAINABILITY=api;

function sourceHtml(source){
  if(source.url&&/^https:\/\//i.test(source.url))return `<a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.label||hostLabel(source.url)||'Sursa oficială')} ↗</a>`;
  return `<span>${esc(source.label||'Sursă atașată')}</span>`;
}
function metaHtml(model){return `<div class="saxMeta" data-sax-meta="1">
  <div><small>Sursă</small>${sourceHtml(model.source)}</div>
  <div><small>Observat</small><span>${esc(formatObserved(model.observedAt))} · ${esc(model.freshness.label)}</span></div>
  <div><small>Încredere</small><span>${esc(model.confidence.label)}</span></div>
  <div><small>Ce lipsește</small><span>${esc(model.missing)}</span></div>
</div>`}
function explorerGuide(root){
  if(!root||root.querySelector('[data-sax-explorer-guide]'))return;
  const resultbar=root.querySelector('.resultbar');if(!resultbar)return;
  const guide=document.createElement('div');guide.className='saxGuide';guide.dataset.saxExplorerGuide='1';
  guide.innerHTML='<b>Cum citești rezultatele</b><span><strong>OPEN confirmat</strong> = numai cu dovada verificată pentru status și termen.</span><span><strong>În pregătire / consultare</strong> = non-OPEN.</span><span><strong>Pipeline</strong> = market/programming intelligence, niciodată apel deschis.</span>';
  resultbar.insertAdjacentElement('beforebegin',guide);
}
function decorateExplorer(){
  const q=document.querySelector('#fq'),status=document.querySelector('#fs');if(!q||!status)return;
  q.setAttribute('aria-label','Caută în oportunitățile monitorizate');
  status.setAttribute('aria-label','Filtrează după starea oportunității');
  const main=q.closest('main')||document.querySelector('.main');explorerGuide(main);
  const data=window.PARTENER_DATA||{};const byId=new Map(asArray(data.calls).map(c=>[String(c?.id||''),c]));
  main?.querySelectorAll('.callrow[data-c]').forEach(row=>{
    if(row.querySelector('[data-sax-meta]'))return;
    const c=byId.get(String(row.dataset.c||''));if(!c)return;
    row.classList.add('saxCallRow');
    row.insertAdjacentHTML('beforeend',metaHtml(callModel(c,data)));
  });
}
function askGuide(ask){
  if(!ask||ask.querySelector('[data-sax-ask-guide]'))return;
  const hint=ask.querySelector('.askV2Hint')||ask.querySelector('.searchBox');if(!hint)return;
  const guide=document.createElement('div');guide.className='saxGuide saxAskGuide';guide.dataset.saxAskGuide='1';
  guide.innerHTML='<b>Fiecare potrivire arată și calitatea dovezii</b><span>Prospețimea, sursa, nivelul de încredere și informația care încă lipsește rămân vizibile lângă rezultat.</span>';
  hint.insertAdjacentElement('afterend',guide);
}
function decorateAsk(){
  const ask=document.querySelector('.main .ask');if(!ask)return;askGuide(ask);
  const products=window.PARTENER_DECISION_PRODUCTS||{};const byId=new Map(asArray(products.dossiers).map(d=>[String(d?.id||''),d]));
  ask.querySelectorAll('.askV2Card').forEach(card=>{
    if(card.querySelector('[data-sax-meta]'))return;
    const open=card.querySelector('[data-ask-open]');const d=byId.get(String(open?.dataset?.askOpen||''));if(!d)return;
    const html=metaHtml(dossierModel(d,products));
    if(open)open.insertAdjacentHTML('beforebegin',html);else card.insertAdjacentHTML('beforeend',html);
  });
}
function render(){decorateExplorer();decorateAsk()}
if(typeof document!=='undefined'){
  const root=document.getElementById('app')||document.documentElement;
  let timer;const sync=()=>{clearTimeout(timer);timer=setTimeout(render,50)};
  if(root)new MutationObserver(sync).observe(root,{childList:true,subtree:true});
  window.addEventListener('load',()=>setTimeout(render,260),{once:true});
  setTimeout(render,420);
}
})();
