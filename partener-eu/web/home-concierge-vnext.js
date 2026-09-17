(()=>{
'use strict';
const P=window.PARTENER_DECISION_PRODUCTS||{};
if(!Array.isArray(P.dossiers)||!Array.isArray(P.news))return;
const TZ='Europe/Bucharest';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const statusOverrides=P.freshnessGuard?.dossierStatusOverrides||{};
const currentStatus=d=>statusOverrides[d?.id]||d?.status||'REVIEW';
const fact=(d,label)=>d?.quickFacts?.find(x=>norm(x?.label)===norm(label));
const confirmed=(d,label)=>{const x=fact(d,label);return x&&String(x.confidence||'').toUpperCase()==='CONFIRMED'?x:null};
const fundingFact=d=>['Grant','Finanțare','Valoare proiect'].map(x=>confirmed(d,x)).find(Boolean)||null;
function displayValue(v){
 if(v==null)return '';
 if(typeof v==='object'){
   const max=v.maximum_total_project_value_eur??v.maximum_eur??v.max_eur;
   if(max!=null&&Number.isFinite(Number(max)))return `max. ${new Intl.NumberFormat('ro-RO').format(Number(max))} EUR`;
   const min=v.minimum_eur??v.min_eur;
   if(min!=null&&Number.isFinite(Number(min)))return `de la ${new Intl.NumberFormat('ro-RO').format(Number(min))} EUR`;
   return '';
 }
 const text=String(v).replace(/\s+/g,' ').trim();
 return /^\s*[\[{]/.test(text)?'':text;
}
function parseDate(v){
 if(!v)return null;
 const d=new Date(v);if(!Number.isNaN(d.getTime()))return d;
 const ro=String(v).toLowerCase();
 const months={ianuarie:0,februarie:1,martie:2,aprilie:3,mai:4,iunie:5,iulie:6,august:7,septembrie:8,octombrie:9,noiembrie:10,decembrie:11};
 const m=ro.match(/(\d{1,2})\s+([a-zăâîșț]+)\s+(20\d{2})(?:[^0-9]+(\d{1,2}):(\d{2}))?/i);
 if(!m||months[m[2]]===undefined)return null;
 return new Date(Number(m[3]),months[m[2]],Number(m[1]),Number(m[4]||23),Number(m[5]||59));
}
function dateText(v){
 const d=parseDate(v);if(!d)return '';
 return new Intl.DateTimeFormat('ro-RO',{day:'numeric',month:'long',year:'numeric',timeZone:TZ}).format(d);
}
function openDossier(id){
 if(window.PARTENER_DECISION_UI?.openDossier?.(id)===true)return;
 document.querySelector('[data-decisionnav]')?.click();
 let tries=0;const timer=setInterval(()=>{tries++;if(window.PARTENER_DECISION_UI?.openDossier?.(id)===true||tries>12)clearInterval(timer)},80);
}
function openHub(query='',tab='dossiers'){
 document.querySelector('[data-decisionnav]')?.click();
 setTimeout(()=>{
   document.querySelector(`[data-di-tab="${tab}"]`)?.click();
   setTimeout(()=>{
     if(!query)return;
     const input=document.getElementById('diQ');if(!input)return;
     input.value=query;input.dispatchEvent(new Event('input',{bubbles:true}));
   },80);
 },80);
}
function isOpen(d){
 if(currentStatus(d)!=='OPEN'||String(d.publicationState||'').toUpperCase()!=='PUBLISHABLE')return false;
 if(!confirmed(d,'Status'))return false;
 const deadline=confirmed(d,'Termen');if(!deadline)return false;
 const parsed=parseDate(deadline.value);return !!(parsed&&parsed.getTime()>=Date.now());
}
function isUpcoming(d){
 const s=currentStatus(d);
 return ['EXPECTED','ANNOUNCED','UPCOMING','PREPARE_NOW'].includes(s)&&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE';
}
function isConsultation(d){return currentStatus(d)==='PUBLIC_CONSULTATION'&&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'};
function score(d){
 const c=Number(d?.quality?.completeness||0);const dl=parseDate(confirmed(d,'Termen')?.value);let urgency=0;
 if(dl){const days=Math.max(0,(dl-Date.now())/86400000);urgency=days<=7?30:days<=21?20:days<=45?10:0;}
 return c+urgency;
}
function card(d,mode='open'){
 const deadline=confirmed(d,'Termen');const funding=fundingFact(d);const audience=(d.audience||[]).filter(Boolean).slice(0,2);
 const meta=[];const fundingText=displayValue(funding?.value);const deadlineText=dateText(deadline?.value);
 if(fundingText)meta.push(fundingText);
 if(deadlineText)meta.push(mode==='open'?`până la ${deadlineText}`:`termen anunțat: ${deadlineText}`);
 const action=mode==='open'?'Vezi dacă poți aplica':mode==='consultation'?'Vezi condițiile în consultare':'Vezi ce merită pregătit';
 return `<article class="conciergeCard" data-concierge-dossier="${esc(d.id)}" tabindex="0">
   <div class="conciergeCardMeta"><span>${esc(d.programme||'Program')}</span>${d.region?`<span>${esc(d.region)}</span>`:''}</div>
   <h3>${esc(d.title||'Oportunitate de finanțare')}</h3>
   ${meta.length?`<div class="conciergeFacts">${meta.map(x=>`<strong>${esc(x)}</strong>`).join('<i>·</i>')}</div>`:''}
   ${audience.length?`<p>${esc(audience.join(' · '))}</p>`:''}
   <button type="button">${action} →</button>
 </article>`;
}
function recentNews(){
 const now=Date.now();
 return (P.news||[]).filter(n=>{
   const d=parseDate(n.date);if(!d||d.getTime()>now)return false;
   return (now-d.getTime())<=72*3600000&&Number(n.utilityScore||0)>=60;
 }).sort((a,b)=>Number(b.utilityScore||0)-Number(a.utilityScore||0)).slice(0,3);
}
const NEWS_LABELS={DEADLINE_EXTENDED:'TERMEN PRELUNGIT',CALL_OPENED:'APEL DESCHIS',GUIDE_MODIFIED:'GHID MODIFICAT',GUIDE_UPDATED_AFTER_CONSULTATION:'GHID ACTUALIZAT',GUIDE_PUBLISHED:'GHID PUBLICAT',CONSULTATION_OPENED:'CONSULTARE DESCHISĂ',CALL_CLOSED:'APEL ÎNCHIS',RESULTS_PUBLISHED:'REZULTATE',OFFICIAL_UPDATE:'ACTUALIZARE OFICIALĂ'};
function newsRow(n){
 const label=NEWS_LABELS[String(n.kind||'').toUpperCase()]||'ACTUALIZARE';
 return `<article class="conciergeNews" data-concierge-news="${esc(n.id)}" tabindex="0">
   <div><span>${esc(dateText(n.date))}</span><b>${esc(label)}</b></div>
   <h3>${esc(n.headline||'Actualizare importantă')}</h3>
   <p>${esc(n.standfirst||n.meaning||'')}</p>
   <button type="button">Vezi ce înseamnă →</button>
 </article>`;
}
function openNews(id){
 document.querySelector('[data-decisionnav]')?.click();
 setTimeout(()=>{document.querySelector('[data-di-tab="news"]')?.click();setTimeout(()=>document.querySelector(`[data-di-news="${CSS.escape(id)}"]`)?.click(),80)},80);
}
const PROFILES=[['Firmă / IMM','firmă IMM'],['ONG','ONG'],['Primărie','primărie'],['Agricultură','agricultură'],['Educație','educație']];
function render(){
 const main=document.querySelector('.main'),hero=document.querySelector('.hero');
 const home=!!(main&&hero);
 document.body.classList.toggle('conciergeHome',home);
 if(!home)return;
 hero.classList.add('conciergeHero');
 const eyebrow=hero.querySelector('.eyebrow'),h1=hero.querySelector('h1'),p=hero.querySelector('p');
 if(eyebrow)eyebrow.textContent='PARTENER.EU · finanțări explicate simplu';
 if(h1)h1.textContent='Ce vrei să finanțezi?';
 if(p)p.textContent='Descrie investiția în câteva cuvinte. Îți arătăm apelurile care merită verificate, ce știm sigur și ce trebuie să faci mai departe.';
 hero.querySelectorAll('.conciergeSearch,.conciergeProfiles').forEach(x=>x.remove());
 const search=document.createElement('form');search.className='conciergeSearch';
 search.innerHTML='<label for="conciergeQ">Descrie investiția ta</label><div><input id="conciergeQ" autocomplete="off" placeholder="ex. hală de producție și utilaje pentru o firmă din Vâlcea"><button type="submit">Găsește finanțări</button></div>';
 p?.insertAdjacentElement('afterend',search);
 const profiles=document.createElement('div');profiles.className='conciergeProfiles';profiles.innerHTML=PROFILES.map(([l,q])=>`<button type="button" data-concierge-query="${esc(q)}">${esc(l)}</button>`).join('');search.insertAdjacentElement('afterend',profiles);
 search.onsubmit=e=>{e.preventDefault();const q=search.querySelector('input')?.value.trim();if(q)openHub(q,'dossiers')};
 profiles.querySelectorAll('[data-concierge-query]').forEach(b=>b.onclick=()=>openHub(b.dataset.conciergeQuery,'dossiers'));

 document.querySelector('[data-concierge-surface]')?.remove();
 const open=P.dossiers.filter(isOpen).sort((a,b)=>score(b)-score(a));
 const upcoming=P.dossiers.filter(isUpcoming).sort((a,b)=>score(b)-score(a));
 const consultation=P.dossiers.filter(isConsultation).sort((a,b)=>score(b)-score(a));
 const changes=recentNews();
 const surface=document.createElement('div');surface.className='conciergeSurface';surface.dataset.conciergeSurface='1';
 surface.innerHTML=`
   <section class="conciergeSection conciergeOpen">
     <div class="conciergeSectionHead"><div><span>Deschise acum</span><h2>Finanțări la care poți lucra acum</h2><p>Doar apeluri cu stare și termen confirmate din surse oficiale.</p></div><button data-concierge-hub="open">Vezi toate ${open.length?`(${open.length})`:''} →</button></div>
     <div class="conciergeGrid">${open.slice(0,6).map(d=>card(d,'open')).join('')||'<div class="conciergeEmpty">Nu există acum apeluri deschise care trec toate verificările noastre.</div>'}</div>
   </section>
   <section class="conciergeSection conciergeUpcoming">
     <div class="conciergeSectionHead"><div><span>Se pregătesc</span><h2>Merită să începi pregătirea</h2><p>Nu sunt încă sesiuni deschise. Le separăm clar ca să nu confunzi pregătirea cu depunerea.</p></div><button data-concierge-hub="prepare">Vezi toate →</button></div>
     <div class="conciergeGrid compact">${upcoming.slice(0,4).map(d=>card(d,'upcoming')).join('')||'<div class="conciergeEmpty">Nu avem acum oportunități viitoare suficient de clare pentru homepage.</div>'}</div>
     ${consultation.length?`<div class="conciergeConsultation"><div><span>În consultare</span><b>${consultation.length} ${consultation.length===1?'oportunitate':'oportunități'}</b><small>Condițiile se pot modifica înainte de lansare.</small></div><button data-concierge-consultation>Vezi consultările →</button></div>`:''}
   </section>
   <section class="conciergeSection conciergeChanges">
     <div class="conciergeSectionHead"><div><span>Ce s-a schimbat</span><h2>Doar schimbările care pot influența o decizie</h2><p>Dacă nu există o modificare materială, nu umplem pagina cu zgomot.</p></div><button data-concierge-hub="news">Vezi istoricul →</button></div>
     <div class="conciergeNewsList">${changes.map(newsRow).join('')||'<div class="conciergeEmpty">Nu există schimbări materiale noi în ultimele 72 de ore.</div>'}</div>
   </section>
   <section class="conciergeTrust">
     <div><span>De ce poți avea încredere în PARTENER.EU</span><h2>Mai puțin jargon. Mai multă dovadă.</h2></div>
     <div class="conciergeTrustGrid"><p><b>Surse oficiale</b><br>Informația materială vine din autoritatea competentă.</p><p><b>Actualizare continuă</b><br>Schimbările sunt urmărite și reconciliate automat.</p><p><b>Necunoscutele rămân necunoscute</b><br>Nu completăm termene, bugete sau eligibilități prin presupuneri.</p><p><b>Poți verifica tot</b><br>Dosarul păstrează sursa, schimbările și contextul deciziei.</p></div>
   </section>`;
 hero.insertAdjacentElement('afterend',surface);
 surface.querySelectorAll('[data-concierge-dossier]').forEach(el=>{const go=()=>openDossier(el.dataset.conciergeDossier);el.onclick=go;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}}});
 surface.querySelectorAll('[data-concierge-news]').forEach(el=>{const go=()=>openNews(el.dataset.conciergeNews);el.onclick=go;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}}});
 surface.querySelectorAll('[data-concierge-hub]').forEach(b=>b.onclick=()=>openHub('',b.dataset.conciergeHub));
 surface.querySelector('[data-concierge-consultation]')?.addEventListener('click',()=>{openHub('','dossiers');setTimeout(()=>{const s=document.getElementById('diStatus');if(s){s.value='PUBLIC_CONSULTATION';s.dispatchEvent(new Event('change',{bubbles:true}))}},200)});
}
window.addEventListener('load',()=>setTimeout(render,560),{once:true});
document.addEventListener('click',()=>setTimeout(render,360),true);
setTimeout(render,760);
})();
