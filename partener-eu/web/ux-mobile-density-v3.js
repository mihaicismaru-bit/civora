(()=>{
'use strict';

const MOBILE=window.matchMedia('(max-width: 720px)');
const LIMIT=3;
const expanded=new Set();
const SPECS=[
  {key:'open',heading:/Apeluri deschise/i,grid:'.diDossierGrid',card:'.diDossierCard',noun:'oportunități'},
  {key:'prepare',heading:/Apeluri și ghiduri în pregătire/i,grid:'.diDossierGrid',card:'.diDossierCard',noun:'oportunități'},
  {key:'changes',heading:/Ce s-a întâmplat și ce trebuie făcut/i,grid:'.diNewsGrid',card:'.diNewsCard',noun:'schimbări'}
];
let scheduled=false;

function reducedMotion(){return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches}
function findSection(pattern){
  return [...document.querySelectorAll('.diHome .diSection')].find(section=>pattern.test(section.querySelector('h2')?.textContent||''))||null;
}
function buttonText(spec,extra,isExpanded){
  return isExpanded?'Arată mai puține':`Arată încă ${extra}`;
}
function applySection(spec){
  const section=findSection(spec.heading);
  if(!section)return;
  const grid=section.querySelector(spec.grid);
  if(!grid)return;
  const cards=[...grid.querySelectorAll(`:scope > ${spec.card}`)];
  if(!grid.id)grid.id=`ux-v3-grid-${spec.key}`;
  let wrap=section.querySelector(`.uxV3MoreWrap[data-ux-v3-section="${spec.key}"]`);

  if(!MOBILE.matches||cards.length<=LIMIT){
    cards.forEach(card=>{card.hidden=false;delete card.dataset.uxV3Collapsed});
    wrap?.remove();
    return;
  }

  const isExpanded=expanded.has(spec.key);
  const extra=Math.max(0,cards.length-LIMIT);
  cards.forEach((card,index)=>{
    const collapse=!isExpanded&&index>=LIMIT;
    card.hidden=collapse;
    if(collapse)card.dataset.uxV3Collapsed='1';else delete card.dataset.uxV3Collapsed;
  });

  if(!wrap){
    wrap=document.createElement('div');
    wrap.className='uxV3MoreWrap';
    wrap.dataset.uxV3Section=spec.key;
    wrap.innerHTML='<button type="button" class="uxV3More"></button>';
    grid.insertAdjacentElement('afterend',wrap);
    wrap.querySelector('button').addEventListener('click',()=>{
      const opening=!expanded.has(spec.key);
      if(opening)expanded.add(spec.key);else expanded.delete(spec.key);
      applySection(spec);
      if(!opening)section.scrollIntoView({behavior:reducedMotion()?'auto':'smooth',block:'start'});
    });
  }

  const button=wrap.querySelector('.uxV3More');
  button.textContent=buttonText(spec,extra,isExpanded);
  button.setAttribute('aria-expanded',String(isExpanded));
  button.setAttribute('aria-controls',grid.id);
  button.setAttribute('aria-label',isExpanded
    ?`Arată mai puține ${spec.noun} în această secțiune`
    :`Afișează încă ${extra} ${spec.noun} în această secțiune`);
  wrap.dataset.extra=String(extra);
}
function apply(){
  scheduled=false;
  document.documentElement.classList.toggle('uxMobileDensityV3',MOBILE.matches);
  SPECS.forEach(applySection);
}
function schedule(){
  if(scheduled)return;
  scheduled=true;
  requestAnimationFrame(apply);
}

const app=document.getElementById('app');
if(app)new MutationObserver(schedule).observe(app,{subtree:true,childList:true});
MOBILE.addEventListener?.('change',schedule);
window.addEventListener('load',schedule,{once:true});
document.addEventListener('click',schedule,true);
setTimeout(schedule,220);
})();
