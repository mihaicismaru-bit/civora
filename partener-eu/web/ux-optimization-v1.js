(()=>{
'use strict';

const STATUS_LABELS={
  OPEN:'Deschis',
  EXPECTED:'În pregătire',
  PUBLIC_CONSULTATION:'În consultare',
  DISCOVERED:'În verificare',
  CLOSED:'Închis'
};
const INPUT_LABELS={
  homeQ:'Caută oportunități după domeniu sau program',
  fq:'Caută în oportunitățile de finanțare',
  fs:'Filtrează oportunitățile după status',
  aq:'Descrie organizația, zona și investiția dorită',
  gotoQ:'Caută după ideea de investiție',
  diQ:'Caută în dosarele și oportunitățile verificate',
  org:'Alege tipul organizației pentru verificarea eligibilității'
};
const KEYBOARD_TARGETS='.brand,.card.clickable,.callrow,.diDossierCard';
let scheduled=false;

function ensureSkipLink(){
  if(document.querySelector('.uxSkip'))return;
  const link=document.createElement('a');
  link.className='uxSkip';
  link.href='#ux-main';
  link.textContent='Sari la conținut';
  document.body.insertBefore(link,document.body.firstChild);
}

function enhanceMain(){
  const main=document.querySelector('main.main');
  if(!main)return;
  main.id='ux-main';
  main.setAttribute('tabindex','-1');
}

function enhanceNavigation(){
  const nav=document.querySelector('.nav');
  if(nav){
    nav.setAttribute('role','navigation');
    nav.setAttribute('aria-label','Navigație principală');
  }
  const navlinks=document.querySelector('.navlinks');
  if(navlinks)navlinks.setAttribute('aria-label','Secțiuni PARTENER.EU');
  const brand=document.querySelector('.brand');
  if(brand){
    brand.setAttribute('role','button');
    brand.setAttribute('tabindex','0');
    brand.setAttribute('aria-label','PARTENER.EU — Acasă');
    brand.dataset.uxKeyboard='1';
  }
  const mode=document.getElementById('mode');
  if(mode)mode.setAttribute('aria-label',mode.textContent.trim()==='Spațiu consultant'?'Deschide spațiul consultant':'Revino la site-ul public');
}

function enhanceForms(){
  Object.entries(INPUT_LABELS).forEach(([id,label])=>{
    const el=document.getElementById(id);
    if(el&&!el.getAttribute('aria-label'))el.setAttribute('aria-label',label);
  });
  const ans=document.getElementById('ans');
  if(ans){ans.setAttribute('aria-live','polite');ans.setAttribute('aria-atomic','false');}
  const match=document.getElementById('matchout');
  if(match){match.setAttribute('aria-live','polite');match.setAttribute('aria-atomic','true');}
  const resultbar=document.querySelector('.resultbar');
  if(resultbar)resultbar.setAttribute('aria-live','polite');
}

function translateStatuses(){
  document.querySelectorAll('.badge').forEach(el=>{
    if(el.dataset.uxStatusTranslated==='1')return;
    const key=el.textContent.trim().replace(/\s+/g,'_').toUpperCase();
    if(!STATUS_LABELS[key])return;
    el.textContent=STATUS_LABELS[key];
    el.dataset.uxStatusTranslated='1';
    el.setAttribute('aria-label',`Status: ${STATUS_LABELS[key]}`);
  });
}

function enhanceClickableCards(){
  document.querySelectorAll(KEYBOARD_TARGETS).forEach(el=>{
    if(el.matches('button,a,input,select,textarea'))return;
    el.setAttribute('role','button');
    if(!el.hasAttribute('tabindex'))el.setAttribute('tabindex','0');
    el.dataset.uxKeyboard='1';
    if(!el.getAttribute('aria-label')){
      const title=el.querySelector?.('h1,h2,h3,.title')?.textContent?.trim();
      if(title)el.setAttribute('aria-label',title.slice(0,180));
    }
  });
}

function apply(){
  scheduled=false;
  document.documentElement.classList.add('uxOptimizedV1');
  ensureSkipLink();
  enhanceMain();
  enhanceNavigation();
  enhanceForms();
  translateStatuses();
  enhanceClickableCards();
}

function schedule(){
  if(scheduled)return;
  scheduled=true;
  requestAnimationFrame(apply);
}

document.addEventListener('keydown',event=>{
  if(event.key!=='Enter'&&event.key!==' ')return;
  const target=event.target.closest?.('[data-ux-keyboard="1"]');
  if(!target)return;
  if(target.matches('button,a,input,select,textarea'))return;
  event.preventDefault();
  target.click();
});

const app=document.getElementById('app');
if(app)new MutationObserver(schedule).observe(app,{subtree:true,childList:true});
window.addEventListener('load',schedule,{once:true});
document.addEventListener('click',schedule,true);
setTimeout(schedule,120);
})();
