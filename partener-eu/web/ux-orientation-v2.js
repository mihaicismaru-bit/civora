(()=>{
'use strict';

const SECTION_SPECS=[
  {key:'profile',label:'Profil',match:()=>document.querySelector('.diHome .noviceEntry')},
  {key:'open',label:'Deschise',match:()=>findSection(/Apeluri deschise/i)},
  {key:'prepare',label:'Pregătește',match:()=>findSection(/Apeluri și ghiduri în pregătire/i)},
  {key:'changes',label:'Schimbări',match:()=>findSection(/Ce s-a întâmplat și ce trebuie făcut/i)}
];
const EXTRA_KEYBOARD='.diNewsCard,.diNewsRow,.diResultDossier';
let scheduled=false;
let sectionObserver=null;

function findSection(pattern){
  return [...document.querySelectorAll('.diHome .diSection')].find(section=>pattern.test(section.querySelector('h2')?.textContent||''))||null;
}
function prefersReduced(){return window.matchMedia?.('(prefers-reduced-motion: reduce)').matches}
function itemCount(key,target){
  if(key==='open'||key==='prepare')return target.querySelectorAll('.diDossierCard').length;
  if(key==='changes')return target.querySelectorAll('.diNewsCard').length;
  return null;
}
function setHeaderHeight(){
  const bar=document.querySelector('.topbar');
  if(!bar)return;
  document.documentElement.style.setProperty('--ux-v2-header-height',`${Math.ceil(bar.getBoundingClientRect().height)}px`);
}
function targets(){
  return SECTION_SPECS.map(spec=>{
    const target=spec.match();
    if(!target)return null;
    const id=`ux-v2-${spec.key}`;
    target.id=id;
    target.classList.add('uxV2Target');
    target.setAttribute('aria-label',spec.key==='profile'?'Alege profilul și investiția':target.querySelector('h2')?.textContent?.trim()||spec.label);
    return {...spec,target,id,count:itemCount(spec.key,target)};
  }).filter(Boolean);
}
function markCurrent(key){
  document.querySelectorAll('.uxV2Rail a[data-ux-v2-key]').forEach(link=>{
    const active=link.dataset.uxV2Key===key;
    link.classList.toggle('active',active);
    if(active)link.setAttribute('aria-current','location'); else link.removeAttribute('aria-current');
  });
}
function observeSections(rows){
  sectionObserver?.disconnect();
  if(!('IntersectionObserver' in window))return;
  sectionObserver=new IntersectionObserver(entries=>{
    const visible=entries.filter(e=>e.isIntersecting).sort((a,b)=>Math.abs(a.boundingClientRect.top)-Math.abs(b.boundingClientRect.top));
    if(!visible.length)return;
    markCurrent(visible[0].target.dataset.uxV2Key||'');
  },{rootMargin:'-28% 0px -58% 0px',threshold:[0,.01]});
  rows.forEach(row=>{row.target.dataset.uxV2Key=row.key;sectionObserver.observe(row.target)});
}
function buildRail(home,rows){
  let rail=home.querySelector('.uxV2Rail');
  const signature=rows.map(r=>`${r.key}:${r.count??''}`).join('|');
  if(!rail){
    rail=document.createElement('nav');
    rail.className='uxV2Rail';
    rail.dataset.uxV2Rail='1';
    rail.setAttribute('aria-label','Navigare rapidă în pagina de finanțări');
    const summary=home.querySelector('.diHomeSummary');
    if(summary)home.insertBefore(rail,summary);else home.insertBefore(rail,home.firstChild);
  }
  if(rail.dataset.signature!==signature){
    rail.dataset.signature=signature;
    rail.innerHTML=`<span class="uxV2RailLabel">Mergi direct la</span><div class="uxV2RailLinks">${rows.map(row=>`<a href="#${row.id}" data-ux-v2-key="${row.key}"><span>${row.label}</span>${row.count==null?'':`<b>${row.count}</b>`}</a>`).join('')}</div>`;
    rail.querySelectorAll('a[data-ux-v2-key]').forEach(link=>link.addEventListener('click',event=>{
      const key=link.dataset.uxV2Key;
      const row=rows.find(x=>x.key===key);
      if(!row)return;
      event.preventDefault();
      markCurrent(key);
      row.target.scrollIntoView({behavior:prefersReduced()?'auto':'smooth',block:'start'});
      history.replaceState(null,'',`#${row.id}`);
    }));
  }
  observeSections(rows);
}
function extendKeyboardCoverage(){
  document.querySelectorAll(EXTRA_KEYBOARD).forEach(el=>{
    if(el.matches('button,a,input,select,textarea'))return;
    el.setAttribute('role','button');
    if(!el.hasAttribute('tabindex'))el.setAttribute('tabindex','0');
    el.dataset.uxKeyboard='1';
    if(!el.getAttribute('aria-label')){
      const title=el.querySelector('h3,.title')?.textContent?.trim();
      if(title)el.setAttribute('aria-label',title.slice(0,180));
    }
  });
  document.querySelectorAll('.diNewsCard').forEach(card=>{
    if(card.querySelector('.uxV2OpenHint'))return;
    const hint=document.createElement('span');
    hint.className='uxV2OpenHint';
    hint.setAttribute('aria-hidden','true');
    hint.textContent='Deschide analiza →';
    card.appendChild(hint);
  });
}
function apply(){
  scheduled=false;
  document.documentElement.classList.add('uxOrientationV2');
  setHeaderHeight();
  extendKeyboardCoverage();
  const home=document.querySelector('.diHome');
  if(!home)return;
  const rows=targets();
  if(rows.length>=3)buildRail(home,rows);
}
function schedule(){
  if(scheduled)return;
  scheduled=true;
  requestAnimationFrame(apply);
}

const app=document.getElementById('app');
if(app)new MutationObserver(schedule).observe(app,{subtree:true,childList:true});
window.addEventListener('resize',schedule,{passive:true});
window.addEventListener('load',schedule,{once:true});
document.addEventListener('click',schedule,true);
setTimeout(schedule,180);
})();
