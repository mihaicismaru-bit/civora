(()=>{
'use strict';

const api={version:'home-freshness-explainability-v1'};
const OPEN_PROOF_MISSING='Identificator exact + endpoint oficial curent + status OPEN explicit + reconciliere semantică';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const asArray=v=>Array.isArray(v)?v:[];
const upper=v=>String(v||'').toUpperCase();

function asTime(value){
  if(value==null||value==='')return null;
  const d=new Date(value);
  const t=d.getTime();
  return Number.isFinite(t)?t:null;
}
function formatObserved(value){
  const t=asTime(value);if(t==null)return 'dată neconfirmată';
  try{return new Intl.DateTimeFormat('ro-RO',{day:'2-digit',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(t));}
  catch{return String(value)}
}
function freshnessState(value,now=Date.now()){
  const t=asTime(value);if(t==null)return {state:'UNKNOWN',label:'Dată neconfirmată'};
  const hours=Math.max(0,(now-t)/36e5);
  if(hours<=24)return {state:'FRESH',label:'Observație recentă'};
  if(hours<=168)return {state:'CURRENT',label:'Verificat în ultimele 7 zile'};
  return {state:'STALE',label:'Necesită revalidare'};
}
function sourceFromDossier(d){
  const raw=asArray(d?.sources)[0]??d?.source??null;
  if(typeof raw==='string')return {url:raw,label:hostLabel(raw)};
  if(raw&&typeof raw==='object'){
    const url=raw.url||raw.href||raw.source_url||raw.authority_url||'';
    const label=raw.label||raw.name||raw.authority||raw.publisher||raw.source_name||hostLabel(url)||'Sursă atașată';
    const observedAt=raw.fetched_at||raw.fetchedAt||raw.observed_at||raw.observedAt||raw.date||null;
    return {url,label,observedAt};
  }
  return {url:'',label:'Sursă atașată'};
}
function hostLabel(url){
  try{return new URL(String(url||'')).hostname.replace(/^www\./,'');}catch{return ''}
}
function fact(d,label){return asArray(d?.quickFacts).find(x=>String(x?.label||'').toLowerCase()===String(label).toLowerCase())||null}
function dossierObservation(d,products){
  const s=sourceFromDossier(d);
  return d?.observedAt||d?.observed_at||d?.updatedAt||d?.updated_at||d?.publishedAt||d?.published_at||s.observedAt||products?.freshnessGuard?.asOf||products?.generatedAt||null;
}
function dossierConfidence(d){
  const status=upper(fact(d,'Status')?.confidence);
  const deadline=upper(fact(d,'Termen')?.confidence);
  const current=upper(d?.status);
  if(current==='OPEN'&&status==='CONFIRMED'&&deadline==='CONFIRMED')return {state:'HIGH',label:'Ridicată · status și termen confirmate'};
  if(['EXPECTED','PUBLIC_CONSULTATION','REVIEW','UPCOMING','ANNOUNCED','PLANNED'].includes(current))return {state:'PIPELINE',label:'În pregătire · non-OPEN'};
  return {state:'REVIEW',label:'În verificare'};
}
function dossierMissing(d){
  const current=upper(d?.status);
  const unknowns=[...asArray(d?.unknowns),...asArray(d?.missing),...asArray(d?.quality?.missing)].map(String).filter(Boolean);
  if(unknowns.length)return unknowns.slice(0,2).join(' · ');
  if(current==='OPEN')return 'Eligibilitatea aplicantului trebuie verificată în dosarul concret.';
  return OPEN_PROOF_MISSING;
}
function buildModel(products,data,now=Date.now()){
  const generatedAt=products?.freshnessGuard?.asOf||products?.generatedAt||null;
  const homeFresh=freshnessState(generatedAt,now);
  const pipelineAt=data?.mff2028?.asOf||null;
  const pipelineFresh=freshnessState(pipelineAt,now);
  return {
    generatedAt,
    homeFresh,
    lanes:[
      {
        id:'open',
        eyebrow:'ACUM',
        title:'Apeluri deschise confirmate',
        count:Number(products?.summary?.openCount||0),
        state:'OPEN_CONFIRMED_ONLY',
        confidence:'Ridicată numai unde statusul și termenul sunt confirmate',
        observedAt:generatedAt,
        source:'Dosare cu surse și proveniență atașate',
        missing:'Pentru fiecare beneficiar, eligibilitatea concretă rămâne de verificat.',
      },
      {
        id:'prepare',
        eyebrow:'PREGĂTEȘTE',
        title:'Oportunități în pregătire',
        count:Number(products?.summary?.prepareCount||0),
        state:'UPCOMING_OR_REVIEW',
        confidence:'Non-OPEN până la dovada exactă de deschidere',
        observedAt:generatedAt,
        source:'Ghiduri, consultări și surse oficiale urmărite',
        missing:OPEN_PROOF_MISSING,
      },
      {
        id:'pipeline',
        eyebrow:'MAI DEVREME',
        title:'Programare viitoare / Pipeline',
        count:Array.isArray(data?.mff2028?.items)?data.mff2028.items.length:null,
        state:'PROGRAMMING_NON_AUTHORIZING',
        confidence:pipelineFresh.state==='STALE'?'Snapshot vechi · revalidare necesară':'Market/programming intelligence · non-authorizing',
        observedAt:pipelineAt,
        source:'Surse oficiale de programare și negociere',
        missing:'Un element de programare nu devine apel fără '+OPEN_PROOF_MISSING.toLowerCase()+'.',
      }
    ]
  };
}
api.buildModel=buildModel;
api.dossierConfidence=dossierConfidence;
api.dossierMissing=dossierMissing;
api.freshnessState=freshnessState;
window.PARTENER_HOME_FRESHNESS_EXPLAINABILITY=api;

function openDecision(tab){
  const nav=document.querySelector('[data-decisionnav]');if(nav)nav.click();
  setTimeout(()=>document.querySelector(`[data-di-tab="${tab}"]`)?.click(),90);
}
function openPipeline(){
  const direct=document.querySelector('[data-mff2028open]');
  if(direct){direct.click();return;}
  const section=document.querySelector('[data-mff2028]');
  if(section)section.scrollIntoView({behavior:'smooth',block:'start'});
}
function laneCard(lane,model){
  const fresh=freshnessState(lane.observedAt);
  const count=lane.count==null?'—':String(lane.count);
  const action=lane.id==='pipeline'?'Programare viitoare →':lane.id==='open'?'Vezi deschise →':'Vezi de pregătit →';
  return `<article class="hfxLane hfx-${esc(lane.id)}" data-hfx-lane="${esc(lane.id)}">
    <div class="hfxLaneTop"><span class="hfxEyebrow">${esc(lane.eyebrow)}</span><span class="hfxFresh hfxFresh-${esc(fresh.state)}">${esc(fresh.label)}</span></div>
    <div class="hfxCount">${esc(count)}</div><h3>${esc(lane.title)}</h3>
    <dl class="hfxMeta">
      <div><dt>Observat</dt><dd>${esc(formatObserved(lane.observedAt))}</dd></div>
      <div><dt>Sursă</dt><dd>${esc(lane.source)}</dd></div>
      <div><dt>Încredere</dt><dd>${esc(lane.confidence)}</dd></div>
      <div><dt>Ce lipsește</dt><dd>${esc(lane.missing)}</dd></div>
    </dl>
    <button type="button" class="hfxAction" data-hfx-action="${esc(lane.id)}">${esc(action)}</button>
  </article>`;
}
function decorateDossierCards(products){
  const byId=new Map(asArray(products?.dossiers).map(d=>[String(d?.id||''),d]));
  document.querySelectorAll('.diDossierCard[data-di-dossier]').forEach(card=>{
    if(card.querySelector('[data-hfx-cardmeta]'))return;
    const d=byId.get(String(card.dataset.diDossier||''));if(!d)return;
    const source=sourceFromDossier(d),observed=dossierObservation(d,products),confidence=dossierConfidence(d),missing=dossierMissing(d),fresh=freshnessState(observed);
    const meta=document.createElement('div');meta.className='hfxCardMeta';meta.dataset.hfxCardmeta='1';
    const sourceHtml=source.url&&/^https:\/\//i.test(source.url)?`<a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.label||hostLabel(source.url)||'Sursa oficială')} ↗</a>`:`<span>${esc(source.label||'Sursă atașată')}</span>`;
    meta.innerHTML=`<div><small>Sursă</small>${sourceHtml}</div><div><small>Observat</small><span>${esc(formatObserved(observed))} · ${esc(fresh.label)}</span></div><div><small>Încredere</small><span>${esc(confidence.label)}</span></div><div><small>Ce lipsește</small><span>${esc(missing)}</span></div>`;
    const foot=card.querySelector('.diCardFoot');if(foot)foot.insertAdjacentElement('beforebegin',meta);else card.appendChild(meta);
  });
}
function render(){
  const products=window.PARTENER_DECISION_PRODUCTS||{};
  if(!Array.isArray(products.dossiers))return;
  const home=document.querySelector('.diHome');if(!home)return;
  const model=buildModel(products,window.PARTENER_DATA||{});
  let surface=home.querySelector('[data-hfx-surface]');
  if(!surface){
    surface=document.createElement('section');surface.className='hfxSurface';surface.dataset.hfxSurface='1';
    const target=home.querySelector('.diHomeSummary');
    if(target)target.insertAdjacentElement('afterend',surface);else home.prepend(surface);
  }
  surface.innerHTML=`<div class="hfxHead"><div><span class="hfxKicker">Prospețime înainte de volum</span><h2>Ce este confirmat acum, ce merită pregătit și ce este încă doar pipeline.</h2><p>PARTENER.EU separă dovada de apel curent de programare, consultări și semnale de piață. O sursă veche sau incompletă nu este prezentată ca fapt actual.</p></div><div class="hfxGuard"><b>${esc(model.homeFresh.label)}</b><span>Proiecție: ${esc(formatObserved(model.generatedAt))}</span></div></div><div class="hfxGrid">${model.lanes.map(l=>laneCard(l,model)).join('')}</div>`;
  surface.querySelector('[data-hfx-action="open"]')?.addEventListener('click',()=>openDecision('open'));
  surface.querySelector('[data-hfx-action="prepare"]')?.addEventListener('click',()=>openDecision('prepare'));
  surface.querySelector('[data-hfx-action="pipeline"]')?.addEventListener('click',openPipeline);
  decorateDossierCards(products);
}

if(typeof document!=='undefined'){
  const root=document.getElementById('app')||document.documentElement;
  const observer=new MutationObserver(()=>{if(document.querySelector('.diHome'))render()});
  if(root)observer.observe(root,{childList:true,subtree:true});
  window.addEventListener('load',()=>setTimeout(render,300),{once:true});
  setTimeout(render,500);
}
})();
