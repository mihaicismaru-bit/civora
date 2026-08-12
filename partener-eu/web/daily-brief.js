(()=>{
'use strict';
const D=window.PARTENER_DATA;if(!D)return;
const items=[
 {tone:'soon',label:'URMEAZĂ · 17 AUG',programme:'PR NORD-EST',title:'Eficiență energetică pentru blocurile din orașe',summary:'Buget 8,4 mil. EUR. Depunerea este programată între 17 august, ora 12:00 și 16 octombrie, ora 12:00.',action:'Acum: verifică lista clădirilor și documentele tehnice.',url:'https://oportunitati-ue.gov.ro/apel/apel-pr-ne-2026-3-rso2-1-1-eficienta-energetica-cladiri-rezidentiale-orase-august-2026/'},
 {tone:'update',label:'NOU · 12 AUG',programme:'MIPE · PEO',title:'Programul Educație și Ocupare a ajuns la versiunea 9.0',summary:'MIPE a publicat programul actualizat și decizia de aprobare. Este o modificare programatică; efectele pe apeluri se verifică individual.',action:'Acum: compară versiunea 9.0 înainte de proiectare.',url:'https://mfe.gov.ro/programul-educatie-si-ocupare-versiunea-9-0-si-decizia-de-aprobare-versiunea-9-0/'},
 {tone:'update',label:'GHID ACTUALIZAT',programme:'PROGRAMUL SĂNĂTATE',title:'Cabinete medicale publice și stomatologice din școli',summary:'MIPE a publicat o actualizare a ghidului. PARTENER.EU nu deduce schimbările materiale până la extragerea documentelor anexate.',action:'Acum: descarcă versiunea curentă și fă diferențialul.',url:'https://mfe.gov.ro/programul-sanatate-actualizeaza-ghidul-solicitantului-investitii-in-infrastructura-cabinetelor-medicale-publice-inclusiv-a-cabinetelor-medicale-stomatologice-organizate-in-unitati-de-invatamant-dot/'},
 {tone:'update',label:'RADAR · AUGUST',programme:'ADR CENTRU',title:'Catalog nou: apeluri lansate și ghiduri în consultare',summary:'Catalogul din 11 august grupează apeluri pentru mobilitate urbană, regenerare și patrimoniu, plus consultări în sănătate și tranziție justă.',action:'Acum: folosește catalogul ca radar, apoi verifică fișa fiecărui apel.',url:'https://www.adrcentru.ro/comunicare/titlul-materialului-catalogul-surselor-de-finantare-august-2026/'}
];
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function card(i,n){return `<a class="dailyBriefCard ${n===0?'primary':''}" href="${esc(i.url)}" target="_blank" rel="noreferrer"><div class="dailyBriefMeta"><span class="dailyBriefTag ${esc(i.tone)}">${esc(i.label)}</span><span class="dailyBriefTag">${esc(i.programme)}</span></div><h3>${esc(i.title)}</h3><p>${esc(i.summary)}</p><div class="dailyBriefAction"><span>${esc(i.action)}</span><b>Sursa oficială ↗</b></div></a>`}
function inject(){
 const hero=document.querySelector('.hero');if(!hero||document.querySelector('[data-dailybrief]'))return;
 const section=document.createElement('section');section.className='dailyBrief';section.dataset.dailybrief='2026-08-12';
 section.innerHTML=`<div class="dailyBriefHead"><div><div class="eyebrow">Briefing verificat · 12 august 2026</div><h2>Ce este nou și ce trebuie făcut acum</h2><div class="dailyBriefLead">Patru semnale oficiale, separate după maturitate: apel care urmează, document programatic și ghiduri actualizate. Nicio consultare nu este afișată ca apel deschis.</div></div><div class="dailyBriefStamp"><span>Actualizat</span><b>14:50 · Europe/Bucharest</b><span>surse T1 / instituționale</span></div></div><div class="dailyBriefGrid">${items.map(card).join('')}</div><div class="dailyBriefFoot"><span><strong>În paralel:</strong> AFIR Energie rămâne verificat până la 14 august; STEP‑LLL este deschis până la 30 septembrie, ora 16:00.</span><button type="button" data-daily-all>Vezi toate știrile</button></div>`;
 hero.insertAdjacentElement('afterend',section);
 section.querySelector('[data-daily-all]').addEventListener('click',()=>{const b=document.querySelector('[data-newsnav]');if(b)b.click()});
}
const obs=new MutationObserver(inject);obs.observe(document.getElementById('app'),{childList:true,subtree:true});inject();
window.PARTENER_DAILY_BRIEF={asOf:'2026-08-12T14:50:00+03:00',items};
})();
