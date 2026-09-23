(()=>{
'use strict';

const scriptPromises=new Map();
const stylePromises=new Map();

function loadStyle(href,id){
  if(document.getElementById(id))return Promise.resolve(true);
  if(stylePromises.has(href))return stylePromises.get(href);
  const promise=new Promise((resolve,reject)=>{
    const link=document.createElement('link');
    link.id=id;link.rel='stylesheet';link.href=href;
    link.onload=()=>resolve(true);
    link.onerror=()=>reject(new Error(`Nu s-a putut încărca ${href}`));
    document.head.appendChild(link);
  });
  stylePromises.set(href,promise);
  return promise;
}

function loadScript(src){
  const key=src.split('?')[0];
  const existing=document.querySelector(`script[data-partener-heavy="${key}"]`);
  if(existing)return Promise.resolve(true);
  if(scriptPromises.has(key))return scriptPromises.get(key);
  const promise=new Promise((resolve,reject)=>{
    const script=document.createElement('script');
    script.src=src;script.defer=true;script.dataset.partenerHeavy=key;
    script.onload=()=>resolve(true);
    script.onerror=()=>reject(new Error(`Nu s-a putut încărca ${src}`));
    document.head.appendChild(script);
  });
  scriptPromises.set(key,promise);
  return promise;
}

let decisionDataPromise=null;
function loadDecisionData(){
  if(window.PARTENER_DECISION_PRODUCTS)return Promise.resolve(true);
  if(decisionDataPromise)return decisionDataPromise;
  decisionDataPromise=loadScript('decision-products.js?v=20260923-lazy-r1').catch(error=>{
    decisionDataPromise=null;throw error;
  });
  return decisionDataPromise;
}

let canonicalPromise=null;
function loadCanonicalCalls(){
  if(window.PARTENER_MIPE_CANONICAL_CALLS)return Promise.resolve(true);
  if(canonicalPromise)return canonicalPromise;
  canonicalPromise=loadScript('mipe-canonical-calls.js?v=20260923-lazy-r1').catch(error=>{
    canonicalPromise=null;throw error;
  });
  return canonicalPromise;
}

let decisionHubPromise=null;
function loadDecisionHub(){
  if(window.PARTENER_DECISION_UI)return Promise.resolve(true);
  if(decisionHubPromise)return decisionHubPromise;
  decisionHubPromise=(async()=>{
    await Promise.all([
      loadStyle('decision-intelligence-v2.css?v=20260923-lazy-r1','partener-decision-intelligence-css'),
      loadDecisionData(),
    ]);
    await loadScript('home-freshness-guard-v1.js?v=20260923-lazy-r1');
    await loadScript('step-lll-dossier-bridge-v2.js?v=20260923-lazy-r1');
    await loadScript('decision-intelligence-v2.js?v=20260923-lazy-r1');
    return true;
  })().catch(error=>{decisionHubPromise=null;throw error});
  return decisionHubPromise;
}

let askPromise=null;
function loadAskSuite(){
  if(window.PARTENER_ASK_V2_READY)return Promise.resolve(true);
  if(askPromise)return askPromise;
  askPromise=(async()=>{
    await Promise.all([
      loadStyle('ask-partener-v2.css?v=20260923-lazy-r1','partener-ask-v2-css'),
      loadDecisionData(),
      loadCanonicalCalls(),
    ]);
    await loadScript('ask-partener-v2.js?v=20260923-lazy-r1');
    window.PARTENER_ASK_V2_READY=true;
    return true;
  })().catch(error=>{askPromise=null;throw error});
  return askPromise;
}

let lifecyclePromise=null;
function loadLifecycleSuite(){
  if(window.PARTENER_CALL_LIFECYCLE&&document.querySelector('[data-call-lifecycle]'))return Promise.resolve(true);
  if(lifecyclePromise)return lifecyclePromise;
  lifecyclePromise=(async()=>{
    await loadStyle('call-lifecycle-ui.css?v=20260923-lazy-r1','partener-call-lifecycle-css');
    await loadScript('call-lifecycle.js?v=20260923-lazy-r1');
    await loadScript('call-lifecycle-ui.js?v=20260923-lazy-r1');
    return true;
  })().catch(error=>{lifecyclePromise=null;throw error});
  return lifecyclePromise;
}

let mipeNewsPromise=null;
function loadMipeNews(){
  if(Array.isArray(window.PARTENER_DATA?.mipeNews))return Promise.resolve(true);
  if(mipeNewsPromise)return mipeNewsPromise;
  mipeNewsPromise=loadScript('mipe-news.js?v=20260923-lazy-r1').catch(error=>{
    mipeNewsPromise=null;throw error;
  });
  return mipeNewsPromise;
}

function autoEnhance(){
  if(document.querySelector('.ask'))loadAskSuite().catch(()=>{});
  if(document.querySelector('.detailHeader'))loadLifecycleSuite().catch(()=>{});
}

document.addEventListener('click',event=>{
  const target=event.target instanceof Element?event.target:null;
  if(!target)return;
  if(target.closest('[data-r="ask"],#ago'))loadAskSuite().catch(()=>{});
  if(target.closest('[data-c]'))loadLifecycleSuite().catch(()=>{});
  if(target.closest('[data-decision-load]'))loadDecisionHub().catch(()=>{});
},true);

let syncTimer=null;
const app=document.getElementById('app');
if(app)new MutationObserver(()=>{
  clearTimeout(syncTimer);
  syncTimer=setTimeout(autoEnhance,40);
}).observe(app,{childList:true,subtree:true});

window.PARTENER_LOAD_DECISION_HUB=loadDecisionHub;
window.PARTENER_LOAD_ASK=loadAskSuite;
window.PARTENER_LOAD_LIFECYCLE=loadLifecycleSuite;
window.PARTENER_LOAD_MIPE_NEWS=loadMipeNews;
window.PARTENER_HEAVY_ASSETS=Object.freeze({
  decisionData:'lazy',
  canonicalCalls:'lazy',
  lifecycle:'lazy',
  mipeNews:'lazy',
});
autoEnhance();
})();
