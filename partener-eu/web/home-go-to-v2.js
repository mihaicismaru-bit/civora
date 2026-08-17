(()=>{
'use strict';
const qs=(s,r=document)=>r.querySelector(s);
const P=window.PARTENER_DECISION_PRODUCTS||{};
function openHub(query='',tab='dossiers'){
  const nav=qs('[data-decisionnav]'); if(nav)nav.click();
  setTimeout(()=>{const tabBtn=qs(`[data-di-tab="${tab}"]`);if(tabBtn)tabBtn.click();setTimeout(()=>{if(!query)return;const input=qs('#diQ');if(!input)return;input.value=query;input.dispatchEvent(new Event('input',{bubbles:true}));},80);},80);
}
function localGeneratedAt(){if(!P.generatedAt)return 'actualizare automată';try{return new Intl.DateTimeFormat('ro-RO',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}).format(new Date(P.generatedAt));}catch{return 'actualizare recentă'}}
function enhanceHero(){
  const hero=qs('.hero'); if(!hero)return;
  const eyebrow=qs('.eyebrow',hero),title=qs('h1',hero),p=qs('p',hero);
  if(eyebrow)eyebrow.textContent='Finanțări europene, explicate pentru decizie';
  if(title)title.textContent='Ai o investiție în minte? Află ce finanțări merită urmărite acum.';
  if(p)p.textContent='Nu trebuie să știi programul sau numărul apelului. Spune ce vrei să faci, iar PARTENER.EU organizează informația oficială în eligibilitate, bani, termene, documente și următorul pas.';
  const primary=qs('[data-novice-profile]');if(primary)primary.textContent='Începe — durează 30 secunde';
  const secondary=qs('[data-novice-open]');if(secondary)secondary.textContent='Vezi apelurile deschise';
  const actions=qs('.noviceHeroActions',hero);
  if(actions&&!qs('[data-goto-search]',hero)){
    const search=document.createElement('form');search.className='gotoSearch';search.dataset.gotoSearch='1';
    search.innerHTML='<label for="gotoQ">Sau caută direct după ideea ta</label><div><input id="gotoQ" autocomplete="off" placeholder="ex. panouri fotovoltaice, digitalizare IMM, centru social"><button type="submit">Caută finanțări</button></div><small>Poți scrie în limbaj normal. Căutăm în dosare, beneficiari, activități și programe.</small>';
    actions.insertAdjacentElement('afterend',search);search.addEventListener('submit',e=>{e.preventDefault();const q=qs('#gotoQ',search)?.value.trim();if(q)openHub(q,'dossiers')});
  }
  const proof=qs('.noviceProof',hero);
  if(proof)proof.innerHTML='<span>✓ Surse oficiale urmărite continuu</span><span>✓ Fără jargon administrativ inutil</span><span>✓ Necunoscutele sunt marcate, nu inventate</span><span>✓ Schimbările sunt urmărite</span>';
  if(proof&&!qs('[data-goto-pulse]',hero)){const pulse=document.createElement('div');pulse.className='gotoPulse';pulse.dataset.gotoPulse='1';const summary=P.summary||{};pulse.innerHTML=`<span><b>${summary.openCount??'—'}</b> apeluri confirmate deschise</span><span><b>${summary.prepareCount??'—'}</b> oportunități de pregătit</span><span><b>${summary.dossierCount??'—'}</b> dosare urmărite</span><small>Actualizat ${localGeneratedAt()}</small>`;proof.insertAdjacentElement('afterend',pulse);}
}
function addOrientation(){const entry=qs('.noviceEntry');if(!entry||qs('[data-goto-orientation]'))return;const box=document.createElement('div');box.className='gotoOrientation';box.dataset.gotoOrientation='1';box.innerHTML='<div><b>Prima dată aici?</b><span>Nu căuta după numele programului. Pornește de la tine.</span></div><div class="gotoSteps"><span><strong>1</strong>Cine ești?</span><span><strong>2</strong>Ce vrei să finanțezi?</span><span><strong>3</strong>Vezi doar oportunitățile relevante</span></div>';entry.insertAdjacentElement('beforebegin',box);}
function clarifyEntry(){const entry=qs('.noviceEntry');if(!entry)return;const h2=qs('h2',entry),p=qs('.noviceEntryHead p',entry);if(h2)h2.textContent='Începe cu două răspunsuri simple.';if(p)p.textContent='Nu ai nevoie de experiență cu fonduri europene. Alege profilul și investiția; fiecare rezultat îți spune clar ce știm, ce nu știm încă și ce merită făcut.';}
function addReturnPath(){const home=qs('.diHome');if(!home||qs('[data-goto-return]'))return;const summary=qs('.diHomeSummary',home);if(!summary)return;const strip=document.createElement('section');strip.className='gotoReturn';strip.dataset.gotoReturn='1';const count=P.summary?.newsCount??0;strip.innerHTML=`<div><span class="gotoKicker">Revii pe PARTENER.EU?</span><b>Vezi ce s-a schimbat de la ultima verificare.</b><small>${count?`${count} schimbări cu utilitate sunt în fluxul curent.`:'Dacă nu există schimbări materiale, nu umplem pagina cu zgomot.'}</small></div><button data-goto-news>Vezi schimbările importante →</button>`;summary.insertAdjacentElement('beforebegin',strip);qs('[data-goto-news]',strip)?.addEventListener('click',()=>openHub('','news'));}
function addPromise(){const home=qs('.diHome');if(!home||qs('[data-goto-promise]'))return;const summary=qs('.diHomeSummary',home);if(!summary)return;const section=document.createElement('section');section.className='gotoPromise';section.dataset.gotoPromise='1';section.innerHTML='<div><span class="gotoKicker">De ce PARTENER.EU</span><h2>De la „am auzit că sunt niște fonduri” la o decizie clară.</h2></div><div class="gotoPromiseGrid"><article><b>Găsești</b><p>oportunități după profilul tău, nu după jargonul instituției.</p></article><article><b>Înțelegi</b><p>cine poate aplica, pentru ce, cu ce buget și până când.</p></article><article><b>Verifici</b><p>sursa oficială și vezi separat informația încă neconfirmată.</p></article><article><b>Acționezi</b><p>cu documente, pași următori și schimbări importante într-un singur loc.</p></article></div>';summary.insertAdjacentElement('afterend',section);}
function addPopularSearches(){const entry=qs('.noviceEntry');if(!entry||qs('[data-goto-popular]',entry))return;const block=document.createElement('div');block.className='gotoPopular';block.dataset.gotoPopular='1';const items=['panouri fotovoltaice','digitalizare IMM','utilaje și producție','turism','agricultură','școală și educație'];block.innerHTML='<span>Căutări utile:</span>'+items.map(x=>`<button data-goto-query="${x}">${x}</button>`).join('');entry.appendChild(block);block.querySelectorAll('[data-goto-query]').forEach(btn=>btn.addEventListener('click',()=>openHub(btn.dataset.gotoQuery,'dossiers')));}
function run(){enhanceHero();addOrientation();clarifyEntry();addPopularSearches();addReturnPath();addPromise();}
window.addEventListener('load',()=>setTimeout(run,240),{once:true});setTimeout(run,420);
})();
