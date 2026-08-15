(()=>{
'use strict';
const qs=(s,r=document)=>r.querySelector(s);

function enhanceHero(){
  const hero=qs('.hero'); if(!hero)return;
  const eyebrow=qs('.eyebrow',hero), title=qs('h1',hero), p=qs('p',hero);
  if(eyebrow)eyebrow.textContent='Finanțări europene, explicate pentru oameni care au altceva de făcut';
  if(title)title.textContent='Spune-ne ce vrei să faci. Îți arătăm ce finanțări merită verificate acum.';
  if(p)p.textContent='Nu trebuie să știi programul, prioritatea sau numărul apelului. Alegi cine ești și ce vrei să finanțezi; noi organizăm informația oficială în eligibilitate, bani, termene, documente și următorul pas.';
  const primary=qs('[data-novice-profile]'); if(primary)primary.textContent='Începe — durează 30 secunde';
  const secondary=qs('[data-novice-open]'); if(secondary)secondary.textContent='Vezi ce este deschis acum';
  const proof=qs('.noviceProof');
  if(proof)proof.innerHTML='<span>✓ Surse oficiale urmărite continuu</span><span>✓ Fără jargon administrativ inutil</span><span>✓ Necunoscutele sunt marcate, nu inventate</span><span>✓ Actualizări și schimbări urmărite</span>';
}

function addOrientation(){
  const entry=qs('.noviceEntry'); if(!entry||qs('[data-goto-orientation]'))return;
  const box=document.createElement('div'); box.className='gotoOrientation'; box.dataset.gotoOrientation='1';
  box.innerHTML='<div><b>Prima dată aici?</b><span>Nu căuta după numele programului. Pornește de la tine.</span></div><div class="gotoSteps"><span><strong>1</strong>Cine ești?</span><span><strong>2</strong>Ce vrei să finanțezi?</span><span><strong>3</strong>Vezi doar oportunitățile relevante</span></div>';
  entry.insertAdjacentElement('beforebegin',box);
}

function clarifyEntry(){
  const entry=qs('.noviceEntry'); if(!entry)return;
  const h2=qs('h2',entry), p=qs('.noviceEntryHead p',entry);
  if(h2)h2.textContent='Începe cu două răspunsuri simple.';
  if(p)p.textContent='Nu ai nevoie de experiență cu fonduri europene. Alege profilul și investiția; fiecare rezultat îți spune clar ce știm, ce nu știm încă și ce merită făcut.';
}

function addPromise(){
  const home=qs('.diHome'); if(!home||qs('[data-goto-promise]'))return;
  const summary=qs('.diHomeSummary',home); if(!summary)return;
  const section=document.createElement('section'); section.className='gotoPromise'; section.dataset.gotoPromise='1';
  section.innerHTML='<div><span class="gotoKicker">PARTENER.EU, pe scurt</span><h2>De la „am auzit că sunt niște fonduri” la o decizie clară.</h2></div><div class="gotoPromiseGrid"><article><b>Găsești</b><p>oportunități după profilul tău, nu după jargonul instituției.</p></article><article><b>Înțelegi</b><p>cine poate aplica, pentru ce, cu ce buget și până când.</p></article><article><b>Verifici</b><p>sursa oficială și vezi separat informația încă neconfirmată.</p></article><article><b>Acționezi</b><p>cu documente, pași următori și schimbări importante într-un singur loc.</p></article></div>';
  summary.insertAdjacentElement('afterend',section);
}

function run(){enhanceHero();addOrientation();clarifyEntry();addPromise();}
window.addEventListener('load',()=>setTimeout(run,240),{once:true});
setTimeout(run,420);
})();
