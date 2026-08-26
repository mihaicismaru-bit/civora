(()=>{
'use strict';

const STYLE_ASSETS=[
  ['consultant-workspace-v3.css?v=20260816-0931','partener-consultant-workspace-v3-css'],
  ['consultant-onboarding-v3.css?v=20260815-2033','partener-consultant-onboarding-v3-css'],
  ['consultant-mysmis-v1.css?v=20260815-1100','partener-consultant-mysmis-v1-css'],
];
const SCRIPT_ASSETS=[
  'consultant-workspace-v3.js?v=20260816-0931',
  'consultant-onboarding-v3.js?v=20260815-2145',
  'consultant-mysmis-v1.js?v=20260815-2145',
];
let loadPromise=null;

function loadStyle([href,id]){
  const existing=document.getElementById(id);
  if(existing)return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const link=document.createElement('link');
    link.id=id;
    link.rel='stylesheet';
    link.href=href;
    link.onload=()=>resolve();
    link.onerror=()=>reject(new Error(`Nu s-a putut încărca ${href}`));
    document.head.appendChild(link);
  });
}

function loadScript(src){
  const key=src.split('?')[0];
  if(document.querySelector(`script[data-partener-lazy="${key}"]`))return Promise.resolve();
  return new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    script.src=src;
    script.defer=true;
    script.dataset.partenerLazy=key;
    script.onload=()=>resolve();
    script.onerror=()=>reject(new Error(`Nu s-a putut încărca ${src}`));
    document.head.appendChild(script);
  });
}

function loadConsultantSuite(){
  if(loadPromise)return loadPromise;
  loadPromise=(async()=>{
    await Promise.all(STYLE_ASSETS.map(loadStyle));
    for(const src of SCRIPT_ASSETS)await loadScript(src);
    return true;
  })().catch(error=>{
    loadPromise=null;
    console.error('PARTENER consultant suite load failed',error);
    throw error;
  });
  return loadPromise;
}

function isEntryClick(target){
  const button=target?.closest?.('#mode');
  if(!button)return false;
  const label=String(button.textContent||'').trim().toLowerCase();
  return label.includes('spațiu consultant')||label.includes('consultant workspace');
}

document.addEventListener('click',event=>{
  if(isEntryClick(event.target))loadConsultantSuite().catch(()=>{});
},true);

window.PARTENER_LOAD_CONSULTANT=loadConsultantSuite;
})();
