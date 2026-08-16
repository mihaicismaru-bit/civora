(()=>{
'use strict';
const PROFILE_FILTERS=[
  ['Firmă / IMM','firmă'],
  ['ONG / asociație','ONG'],
  ['Școală / universitate','școală'],
  ['Primărie / instituție','autoritate publică'],
  ['Fermă / agricultură','fermieri'],
  ['Formare profesională','formare profesională']
];
const NEED_FILTERS=[
  ['Energie','energie'],
  ['Digitalizare','digitalizare'],
  ['Investiții productive','investiții'],
  ['Educație','educație'],
  ['Ocupare și formare','formare'],
  ['Servicii sociale','servicii sociale'],
  ['Turism','turism'],
  ['Agricultură','agricultură']
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
function openConsultant(){
  const mode=document.getElementById('mode');
  if(!mode)return;
  if(mode.textContent.trim()==='Spațiu consultant')mode.click();
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

function simplifySummary(home){
  const summary=home.querySelector('.diHomeSummary');
  if(!summary)return;
  const lead=summary.querySelector('.diHomeLead');
  if(lead){
    const small=lead.querySelector('small');
    const strong=lead.querySelector('strong');
    const span=lead.querySelector('span');
    if(small)small.textContent='Situația finanțărilor urmărite';
    if(strong)strong.textContent='Vezi ce este deschis, ce urmează și ce merită pregătit.';
    if(span)span.textContent='Pentru fiecare oportunitate separăm informația confirmată de ceea ce mai trebuie verificat.';
  }
  const metrics=[...summary.querySelectorAll('.diMetric')];
  const labels=[
    ['apeluri deschise','Poți analiza depunerea acum'],
    ['oportunități în pregătire','Poți începe pregătirea'],
    ['schimbări importante','Necesită atenție']
  ];
  const values=[window.PARTENER_DECISION_PRODUCTS?.summary?.openCount??'—',window.PARTENER_DECISION_PRODUCTS?.summary?.prepareCount??'—',window.PARTENER_DECISION_PRODUCTS?.summary?.newsCount??'—'];
  metrics.forEach((metric,i)=>{
    if(!labels[i]){metric.remove();return;}
    const b=metric.querySelector('b');
    const span=metric.querySelector('span');
    if(b)b.textContent=values[i];
    if(span){span.innerHTML=`${labels[i][0]}<small>${labels[i][1]}</small>`;}
  });
}

function injectBeginnerEntry(){
  const home=document.querySelector('.diHome');
  const hero=document.querySelector('.hero');
  if(!home||!hero)return;
  if(home.querySelector('[data-novice-entry]')){explainLabels(home);simplifySummary(home);return;}

  const eyebrow=hero.querySelector('.eyebrow');
  const title=hero.querySelector('h1');
  const heroP=hero.querySelector('p');
  if(eyebrow)eyebrow.textContent='Finanțări europene explicate pentru decizie';
  if(title)title.textContent='Găsește finanțarea potrivită fără să citești zeci de ghiduri.';
  if(heroP)heroP.textContent='Alegi cine ești și ce vrei să finanțezi. PARTENER.EU îți arată oportunitățile, cine poate aplica, câți bani sunt disponibili, termenele, documentele și ce trebuie făcut mai departe.';

  let heroActions=hero.querySelector('.noviceHeroActions');
  if(!heroActions){
    heroActions=document.createElement('div');
    heroActions.className='noviceHeroActions';
    heroActions.innerHTML='<button data-novice-profile>Găsește finanțări pentru mine</button><button class="secondary" data-novice-open>Vezi apelurile deschise</button><button class="secondary" data-novice-consultant>Sunt consultant</button>';
    const target=hero.querySelector('p')||hero.firstElementChild;
    target?.insertAdjacentElement('afterend',heroActions);
  }

  const proof=document.createElement('div');
  proof.className='noviceProof';
  proof.innerHTML='<span>✓ Surse oficiale</span><span>✓ Condiții explicate în română</span><span>✓ Documente și anexe într-un singur loc</span><span>✓ Necunoscutele sunt marcate, nu ghicite</span>';
  heroActions.insertAdjacentElement('afterend',proof);

  const entry=document.createElement('section');
  entry.className='noviceEntry';
  entry.dataset.noviceEntry='1';
  entry.innerHTML=`
    <div class="noviceEntryHead">
      <div><span class="noviceKicker">Pornește simplu</span><h2>Nu trebuie să știi numele programului.</h2><p>Alege profilul organizației sau domeniul investiției. Vei ajunge direct la oportunitățile relevante și la dosarul lor explicat.</p></div>
      <div class="noviceLegend"><b>Cum citim statusul</b><span><i class="open"></i><strong>Deschis</strong> — sesiunea primește proiecte</span><span><i class="prepare"></i><strong>În pregătire</strong> — poți începe documentele, dar nu depui încă</span><span><i class="verify"></i><strong>În verificare</strong> — există informație utilă, dar lipsesc confirmări materiale</span></div>
    </div>
    <div class="noviceChoiceBlock"><h3>1. Cine ești?</h3><div class="noviceProfiles">${PROFILE_FILTERS.map(([label,query])=>`<button data-novice-query="${query}"><span>${label}</span><b>Vezi oportunități →</b></button>`).join('')}</div></div>
    <div class="noviceChoiceBlock"><h3>2. Ce vrei să finanțezi?</h3><div class="noviceNeeds">${NEED_FILTERS.map(([label,query])=>`<button data-novice-query="${query}">${label}</button>`).join('')}</div></div>
    <div class="noviceHow"><div><span>1</span><b>Găsești oportunitatea</b><small>după profil sau domeniu</small></div><div><span>2</span><b>Deschizi dosarul</b><small>eligibilitate, bani, termen, documente</small></div><div><span>3</span><b>Știi ce ai de făcut</b><small>acțiuni, riscuri și ce mai trebuie verificat</small></div></div>`;
  home.insertBefore(entry,home.firstChild);

  document.querySelector('[data-novice-open]')?.addEventListener('click',()=>openHub('','open'));
  document.querySelector('[data-novice-profile]')?.addEventListener('click',()=>entry.scrollIntoView({behavior:'smooth',block:'start'}));
  document.querySelector('[data-novice-consultant]')?.addEventListener('click',openConsultant);
  entry.querySelectorAll('[data-novice-query]').forEach(btn=>btn.addEventListener('click',()=>openHub(btn.dataset.noviceQuery,'dossiers')));
  simplifySummary(home);
  explainLabels(home);
}

function polishMobileCards(){
  document.querySelectorAll('.diDossierCard').forEach(card=>{
    const paragraph=card.querySelector('p');
    if(paragraph&&paragraph.textContent.length>155){
      paragraph.title=paragraph.textContent;
      paragraph.textContent=paragraph.textContent.slice(0,152).trim()+'…';
    }
  });
}

function run(){injectBeginnerEntry();explainLabels();polishMobileCards();}
window.addEventListener('load',()=>setTimeout(run,80),{once:true});
document.addEventListener('click',()=>setTimeout(run,120),true);
setTimeout(run,180);
})();
