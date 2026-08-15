(()=>{
'use strict';
const PROFILE_FILTERS=[
  ['firmă / IMM','firmă'],
  ['ONG / asociație','ONG'],
  ['școală / universitate','școală'],
  ['primărie / instituție','autoritate publică'],
  ['fermă / agricultură','fermieri'],
  ['formare profesională','formare profesională']
];

function openHub(query='',tab='dossiers'){
  const nav=document.querySelector('[data-decisionnav]');
  if(nav)nav.click();
  setTimeout(()=>{
    const tabBtn=document.querySelector(`[data-di-tab="${tab}"]`);
    if(tabBtn)tabBtn.click();
    setTimeout(()=>{
      if(!query)return;
      const input=document.getElementById('diQ');
      if(!input)return;
      input.value=query;
      input.dispatchEvent(new Event('input',{bubbles:true}));
    },60);
  },60);
}

function explainLabels(root=document){
  root.querySelectorAll('.diConfidence').forEach(el=>{
    const raw=el.textContent.trim();
    if(/^\d+%$/.test(raw)){
      el.textContent=`Dosar ${raw}`;
      el.title='Gradul de completare al informațiilor din dosar, nu probabilitatea de finanțare.';
    }
  });
  root.querySelectorAll('.diDecision').forEach(el=>{
    el.title='Recomandare de lucru PARTENER.EU, bazată pe informațiile verificate disponibile.';
  });
  root.querySelectorAll('.diStatus').forEach(el=>{
    const value=el.textContent.trim().toUpperCase();
    const map={
      'DESCHIS':'Sesiunea este confirmată ca deschisă pentru depunere.',
      'ÎN PREGĂTIRE':'Poți pregăti proiectul, dar depunerea nu este încă deschisă.',
      'ÎN CONSULTARE':'Ghidul este în consultare; condițiile se pot modifica.',
      'ÎN VERIFICARE':'Există informații utile, dar unele condiții materiale nu sunt încă suficient confirmate.',
      'ÎNCHIS':'Sesiunea nu mai primește proiecte.'
    };
    if(map[value])el.title=map[value];
  });
}

function injectBeginnerEntry(){
  const home=document.querySelector('.diHome');
  const hero=document.querySelector('.hero');
  if(!home||!hero)return;
  if(home.querySelector('[data-novice-entry]')){explainLabels(home);return;}

  const heroP=hero.querySelector('p');
  if(heroP)heroP.textContent='Spune-ne cine ești sau pornește de la apelurile deschise. Noi traducem ghidurile în condiții, bani, termene, documente și pași concreți.';

  let heroActions=hero.querySelector('.noviceHeroActions');
  if(!heroActions){
    heroActions=document.createElement('div');
    heroActions.className='noviceHeroActions';
    heroActions.innerHTML='<button data-novice-open>Vezi finanțările deschise</button><button class="secondary" data-novice-profile>Găsește după profilul meu</button>';
    const target=hero.querySelector('p')||hero.firstElementChild;
    target?.insertAdjacentElement('afterend',heroActions);
  }

  const entry=document.createElement('section');
  entry.className='noviceEntry';
  entry.dataset.noviceEntry='1';
  entry.innerHTML=`
    <div class="noviceEntryHead">
      <div><span class="noviceKicker">Nu trebuie să știi numele programului</span><h2>Ce fel de organizație ai?</h2><p>Alege profilul și vezi direct oportunitățile care merită verificate pentru tine.</p></div>
      <div class="noviceLegend"><span><i class="open"></i><b>Deschis</b> — poți depune</span><span><i class="prepare"></i><b>În pregătire</b> — poți începe documentele</span></div>
    </div>
    <div class="noviceProfiles">${PROFILE_FILTERS.map(([label,query])=>`<button data-novice-query="${query}"><span>${label}</span><b>Vezi oportunități →</b></button>`).join('')}</div>
    <div class="noviceTrust"><b>Ce primești pentru fiecare apel:</b><span>cine poate aplica</span><span>câți bani</span><span>termen</span><span>documente</span><span>punctaj</span><span>riscuri</span><span>ce faci acum</span></div>`;
  home.insertBefore(entry,home.firstChild);

  document.querySelector('[data-novice-open]')?.addEventListener('click',()=>openHub('','open'));
  document.querySelector('[data-novice-profile]')?.addEventListener('click',()=>entry.scrollIntoView({behavior:'smooth',block:'start'}));
  entry.querySelectorAll('[data-novice-query]').forEach(btn=>btn.addEventListener('click',()=>openHub(btn.dataset.noviceQuery,'dossiers')));
  explainLabels(home);
}

function polishMobileCards(){
  document.querySelectorAll('.diDossierCard').forEach(card=>{
    const paragraph=card.querySelector('p');
    if(paragraph&&paragraph.textContent.length>180){
      paragraph.title=paragraph.textContent;
      paragraph.textContent=paragraph.textContent.slice(0,177).trim()+'…';
    }
  });
}

function run(){injectBeginnerEntry();explainLabels();polishMobileCards();}
window.addEventListener('load',()=>setTimeout(run,80),{once:true});
document.addEventListener('click',()=>setTimeout(run,120),true);
setTimeout(run,180);
})();
