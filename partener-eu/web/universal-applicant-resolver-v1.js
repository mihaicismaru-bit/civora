(()=>{
'use strict';
const REGISTRY={
  '2541894':{
    cui:'2541894',name:'Primăria Orașului Brezoi',legalName:'Orașul Brezoi',type:'municipality',entityClass:'UAT',county:'Vâlcea',region:'Sud-Vest Oltenia',locality:'Brezoi',address:'Str. Lotrului nr. 2, Brezoi, Vâlcea, 245500',phone:'0250778240',status:'ACTIVE',objectives:['urban_regeneration','green_infrastructure','mobility','tourism','digitalization','education','social_services','renewable_energy'],
    sourceFacts:[{label:'Primăria Orașului Brezoi — contact oficial',url:'https://primariabrezoi.ro/contact.html',tier:'A',checkedAt:'2026-08-12'}],confidence:0.99
  }
};
const clean=v=>String(v||'').replace(/\D/g,'');
const setValue=(id,value)=>{const el=document.getElementById(id);if(!el||value==null||value==='')return;el.value=value;el.dispatchEvent(new Event('change',{bubbles:true}));};
const setObjectives=(keys=[])=>document.querySelectorAll('[data-cw-obj]').forEach(el=>{el.checked=keys.includes(el.value)});
const status=(text,tone='info')=>{let el=document.getElementById('cwResolverStatus');if(!el){const cui=document.getElementById('cwCui');if(!cui)return;el=document.createElement('div');el.id='cwResolverStatus';el.style.cssText='margin-top:6px;font-size:12px;line-height:1.35';cui.parentElement.appendChild(el)}el.textContent=text;el.dataset.tone=tone;};
async function remoteResolve(cui){
  const endpoint=window.PARTENER_ENTITY_API_URL;
  if(!endpoint)return null;
  const r=await fetch(`${endpoint.replace(/\/$/,'')}/resolve/${encodeURIComponent(cui)}`,{headers:{Accept:'application/json'}});
  if(!r.ok)return null;
  return r.json();
}
async function resolve(raw){
  const cui=clean(raw);if(cui.length<2)throw new Error('CUI/CIF invalid.');
  if(REGISTRY[cui])return {...REGISTRY[cui],resolver:'verified-local-registry'};
  const remote=await remoteResolve(cui).catch(()=>null);
  if(remote)return {...remote,cui,resolver:'remote-provider-chain'};
  throw new Error('Entitatea nu este încă disponibilă în registrul local, iar providerul extern nu este configurat. CUI-ul rămâne salvat pentru rezolvare ulterioară.');
}
function applyEntity(e){
  setValue('cwCui',e.cui);setValue('cwName',e.name||e.legalName);setValue('cwType',e.type);setValue('cwCounty',e.county);setValue('cwRegion',e.region);setObjectives(e.objectives||[]);
  status(`${e.name||e.legalName} identificat automat · ${e.entityClass||e.type||'entitate'} · încredere ${Math.round((e.confidence||0)*100)}%`,'good');
  const form=document.getElementById('cwCui')?.closest('.cw2Form');if(form){form.dataset.resolvedCui=e.cui;form.dataset.entityClass=e.entityClass||'';form.dataset.resolver=e.resolver||'';}
  window.dispatchEvent(new CustomEvent('partener:entity-resolved',{detail:e}));
}
async function run(){const input=document.getElementById('cwCui');if(!input)return;status('Identificare în curs…');try{applyEntity(await resolve(input.value));}catch(err){status(err.message,'warn');}}
function mount(){
  const input=document.getElementById('cwCui');if(!input||input.dataset.resolverMounted)return;
  input.dataset.resolverMounted='1';input.placeholder='CUI/CIF — ex. 2541894';input.autocomplete='off';
  const btn=document.createElement('button');btn.type='button';btn.className='btn secondary small';btn.textContent='Identifică automat';btn.style.marginTop='8px';btn.addEventListener('click',run);input.parentElement.appendChild(btn);
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();run();}});
  input.addEventListener('blur',()=>{const cui=clean(input.value);if(REGISTRY[cui])run();});
}
new MutationObserver(mount).observe(document.documentElement,{childList:true,subtree:true});
mount();
window.PARTENER_ENTITY_RESOLVER={resolve,applyEntity,registry:REGISTRY,version:'1.0.0'};
})();
