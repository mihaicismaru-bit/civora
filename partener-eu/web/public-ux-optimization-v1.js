(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot}',"'":'&#39;'}[c]));
function openConsultant(){const b=document.querySelector('.modebtn');if(b){b.click();return true}return false}
function addTrust(){
 const hero=document.querySelector('.hero');if(!hero||document.querySelector('.peTrust'))return;
 const box=document.createElement('section');box.className='peTrust';
 box.innerHTML='<div><b>Surse oficiale</b><span>Termenele și condițiile importante sunt legate de sursa din care provin.</span></div><div><b>Eligibilitate explicată</b><span>Vezi de ce o oportunitate se potrivește și ce trebuie verificat înainte de depunere.</span></div><div><b>Actualizări urmărite</b><span>Modificările de ghid, calendar și status sunt reunite în aceeași fișă de finanțare.</span></div>';
 hero.insertAdjacentElement('afterend',box);
}
function addEntry(){
 const stats=document.querySelector('.stats');if(!stats||document.querySelector('.peEntry'))return;
 const sec=document.createElement('section');sec.className='peEntry';
 sec.innerHTML='<div class="peEntryHead"><div><h2>Pornește de la profilul beneficiarului</h2><p>Introdu CUI/CIF-ul și filtrează oportunitățile pentru organizația ta.</p></div><button class="btn" data-pe-consultant>Deschide Consultant</button></div><div class="peEntryGrid"><button class="peEntryCard" data-pe-type="enterprise"><strong>Companie</strong><span>Finanțări pentru investiții, digitalizare, energie, inovare, formare și dezvoltare.</span><em>Verifică după CUI →</em></button><button class="peEntryCard" data-pe-type="municipality"><strong>Primărie / instituție publică</strong><span>Apeluri pentru UAT, servicii publice, infrastructură, regenerare, educație și energie.</span><em>Verifică după CIF →</em></button><button class="peEntryCard" data-pe-type="ngo"><strong>ONG / organizație</strong><span>Oportunități pentru servicii sociale, educație, ocupare, incluziune și parteneriate.</span><em>Vezi oportunitățile →</em></button></div>';
 stats.insertAdjacentElement('afterend',sec);
 sec.querySelectorAll('[data-pe-consultant],[data-pe-type]').forEach(b=>b.addEventListener('click',()=>{openConsultant();setTimeout(()=>{const add=document.querySelector('[data-cw-add]');if(add)add.click()},50)}));
}
function enhanceResolver(){
 const cui=document.getElementById('cwCui');if(!cui||document.querySelector('.peEntitySummary'))return;
 const info=document.createElement('div');info.className='peEntitySummary';info.innerHTML='<b>Identificare automată</b> · completează CUI/CIF-ul pentru a prelua datele publice disponibile și a construi profilul de eligibilitate.';
 cui.parentElement.appendChild(info);
}
function resolved(e){
 const d=e.detail||{};const info=document.querySelector('.peEntitySummary');if(!info)return;
 const facts=[['Tip',d.entityClass||d.type],['Județ',d.county],['Regiune',d.region]].filter(x=>x[1]);
 info.innerHTML=`<b>${esc(d.name||d.legalName||'Beneficiar identificat')}</b><div class="peResolvedFacts">${facts.map(([k,v])=>`<span><small>${esc(k)}</small><b>${esc(v)}</b></span>`).join('')}</div>`;
}
function modeLabel(){const b=document.querySelector('.modebtn');if(!b)return;if(b.textContent.trim()==='Public site')b.dataset.pePublic='1';else delete b.dataset.pePublic}
function polish(){addTrust();addEntry();enhanceResolver();modeLabel()}
window.addEventListener('partener:entity-resolved',resolved);
let pending=false;new MutationObserver(()=>{if(pending)return;pending=true;queueMicrotask(()=>{pending=false;polish()})}).observe(document.documentElement,{childList:true,subtree:true,characterData:true});
polish();
window.PARTENER_PUBLIC_UX={version:'1.0.1',polish,openConsultant};
})();
