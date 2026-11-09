(()=>{
'use strict';
const P=window.PARTENER_HOME_DATA||{};
if(!Array.isArray(P.dossiers)||!Array.isArray(P.news))return;
const TZ='Europe/Bucharest';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'');
const isTypingTarget=target=>target instanceof Element&&!!target.closest('input,textarea,select,[contenteditable="true"],.conciergeSearch');
const statusOverrides=P.freshnessGuard?.dossierStatusOverrides||{};
const currentStatus=d=>statusOverrides[d?.id]||d?.status||'REVIEW';
const fact=(d,label)=>d?.quickFacts?.find(x=>norm(x?.label)===norm(label));
const confirmed=(d,label)=>{const x=fact(d,label);return x&&String(x.confidence||'').toUpperCase()==='CONFIRMED'?x:null};
const fundingFact=d=>['Grant','Finanțare','Valoare proiect','Buget'].map(x=>confirmed(d,x)).find(Boolean)||null;
function displayValue(v){
 if(v==null)return '';
 if(typeof v==='object'){
   const amount=v.amount;
   if(amount!=null&&Number.isFinite(Number(amount))){
     const currency=String(v.currency||'').trim().toUpperCase();
     return `${new Intl.NumberFormat('ro-RO').format(Number(amount))}${currency?` ${currency}`:''}`;
   }
   const max=v.maximum_total_project_value_eur??v.maximum_eur??v.max_eur;
   if(max!=null&&Number.isFinite(Number(max)))return `max. ${new Intl.NumberFormat('ro-RO').format(Number(max))} EUR`;
   const min=v.minimum_eur??v.min_eur;
   if(min!=null&&Number.isFinite(Number(min)))return `de la ${new Intl.NumberFormat('ro-RO').format(Number(min))} EUR`;
   return '';
 }
 const text=String(v).replace(/\s+/g,' ').trim();
 return /^\s*[\[{]/.test(text)?'':text;
}
// Convert official Romanian wall-clock deadlines to exact UTC instants.
// Device timezone must not shift an OPEN/CONSULTATION cutoff. The round-trip
// also rejects impossible local instants at the spring DST transition and
// selects the earlier instant on an ambiguous autumn clock change (fail closed).
function romaniaTime(year,month,day,hour,minute){
 const fmt=new Intl.DateTimeFormat('en-GB',{timeZone:TZ,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'});
 for(const offset of [3,2]){
  const candidate=new Date(Date.UTC(year,month-1,day,hour-offset,minute));
  const fields=Object.fromEntries(fmt.formatToParts(candidate).filter(p=>p.type!=='literal').map(p=>[p.type,Number(p.value)]));
  if(fields.year===year&&fields.month===month&&fields.day===day&&fields.hour===hour&&fields.minute===minute)return candidate;
 }
 return null;
}
function parseDate(v){
 if(!v)return null;
 const raw=String(v).trim();
 // Explicit UTC/offset timestamps are already exact. Otherwise source dates
 // without a timezone are Romanian local dates, NOT browser-local dates.
 const iso=raw.match(/^(20\d{2})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(Z|[+-]\d{2}:\d{2})?)?$/i);
 if(iso){
  if(iso[6]){const exact=new Date(raw);return Number.isNaN(exact.getTime())?null:exact;}
  return romaniaTime(Number(iso[1]),Number(iso[2]),Number(iso[3]),Number(iso[4]??23),Number(iso[5]??59));
 }
 const ro=raw.toLocaleLowerCase('ro-RO');
 const months={ianuarie:1,februarie:2,martie:3,aprilie:4,mai:5,iunie:6,iulie:7,august:8,septembrie:9,octombrie:10,noiembrie:11,decembrie:12};
 const m=ro.match(/(\d{1,2})\s+([a-zăâîșț]+)\s+(20\d{2})(?:[^0-9]+(\d{1,2}):(\d{2}))?/i);
 if(!m||!months[m[2]])return null;
 return romaniaTime(Number(m[3]),months[m[2]],Number(m[1]),Number(m[4]??23),Number(m[5]??59));
}
function dateText(v){
 const d=parseDate(v);if(!d)return '';
 return new Intl.DateTimeFormat('ro-RO',{day:'numeric',month:'long',year:'numeric',timeZone:TZ}).format(d);
}
function openDossier(id){
 const d=(P.dossiers||[]).find(x=>String(x?.id)===String(id));
 if(d?.canonicalPath){location.assign(d.canonicalPath);return}
 window.PARTENER_LOAD_DECISION_HUB?.().then(()=>window.PARTENER_DECISION_UI?.openDossier?.(id)).catch(()=>{});
}
// Free-text descriptions go to the Ask engine (intent + word ranking); profile shortcuts open the filterable explorer.
function openAsk(query){location.assign('/?view=ask&q='+encodeURIComponent(query))}
function openHub(query='',tab='dossiers'){
 if(query){location.assign('/?q='+encodeURIComponent(query));return}
 const routes={open:'/finantari/deschise/',prepare:'/finantari/in-pregatire/',news:'/schimbari/',dossiers:'/dosare/'};
 location.assign(routes[tab]||'/finantari/');
}
function isOpen(d){
 if(currentStatus(d)!=='OPEN'||String(d.publicationState||'').toUpperCase()!=='PUBLISHABLE')return false;
 if(!confirmed(d,'Status'))return false;
 const deadline=confirmed(d,'Termen');if(!deadline)return false;
 const parsed=parseDate(deadline.value);return !!(parsed&&parsed.getTime()>=Date.now());
}
// A current-year reference or a PUBLISHABLE flag alone cannot establish that
// a planned/consultation dossier is actionable *now*. An expired explicit
// submission/consultation deadline wins over a later, unrelated calendar clue.
// Unknown/unparseable calendars remain queryable in the dossier, not on home.
function hasFreshPrepareEvidence(d){
 const now=Date.now(),dated=[];
 let expiredCutoff=false;
 const add=(raw,cutoff=false)=>{
   // A year is programme context, not a verifiable date/window.
   if(/^20\d{2}$/.test(String(raw??'').trim()))return;
   const value=parseDate(raw);
   if(!value)return;
   const ts=value.getTime();
   dated.push(ts);
   if(cutoff&&ts<=now)expiredCutoff=true;
 };
 for(const key of ['deadline','closesAt','closeAt','consultationDeadline'])add(d?.[key],true);
 for(const key of ['openFrom','opensAt','openAt'])add(d?.[key]);
 for(const row of d?.quickFacts||[]){
   const label=norm(row?.label);
   if(/termen|inchidere|depunere/.test(label))add(row?.value,true);
   else if(/deschidere|calendar/.test(label))add(row?.value);
 }
 return !expiredCutoff&&dated.some(ts=>ts>now);
}
function isUpcoming(d){
 const s=currentStatus(d);
 return ['EXPECTED','ANNOUNCED','UPCOMING','PREPARE_NOW'].includes(s)
   &&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'
   &&hasFreshPrepareEvidence(d);
}
function isConsultation(d){
 return currentStatus(d)==='PUBLIC_CONSULTATION'
   &&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'
   &&hasFreshPrepareEvidence(d);
}
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
 const n=(P.news||[]).find(x=>String(x?.id)===String(id));
 location.assign(n?.canonicalPath||'/schimbari/');
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
 let search=hero.querySelector('.conciergeSearch');
 if(!search){
   search=document.createElement('form');search.className='conciergeSearch';
   search.innerHTML='<label for="conciergeQ">Descrie investiția ta</label><div><input id="conciergeQ" type="search" inputmode="search" enterkeyhint="search" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="ex. hală de producție și utilaje pentru o firmă din Vâlcea"><button type="submit">Găsește finanțări</button></div>';
   p?.insertAdjacentElement('afterend',search);
   search.onsubmit=e=>{e.preventDefault();const q=search.querySelector('input')?.value.trim();if(q)openAsk(q)};
 }
 let profiles=hero.querySelector('.conciergeProfiles');
 if(!profiles){
   profiles=document.createElement('div');profiles.className='conciergeProfiles';profiles.innerHTML=PROFILES.map(([l,q])=>`<button type="button" data-concierge-query="${esc(q)}">${esc(l)}</button>`).join('');
   search.insertAdjacentElement('afterend',profiles);
   profiles.querySelectorAll('[data-concierge-query]').forEach(b=>b.onclick=()=>openHub(b.dataset.conciergeQuery,'dossiers'));
 }
 let proof=hero.querySelector('.conciergeProof');
 if(!proof){
   proof=document.createElement('div');proof.className='conciergeProof';
   proof.innerHTML='<span>Surse oficiale</span><span>Actualizare continuă</span><span>Necunoscutele rămân necunoscute</span>';
   profiles.insertAdjacentElement('afterend',proof);
 }

 document.querySelector('[data-concierge-surface]')?.remove();
 const open=P.dossiers.filter(isOpen).sort((a,b)=>score(b)-score(a));
 // Count only records still passing the live gate, never a stale snapshot total.
 const canonicalOpenTotal=open.length;
 const legacyOpenMetric=hero.querySelector('.heroCard .big');
 if(legacyOpenMetric)legacyOpenMetric.textContent=String(canonicalOpenTotal);
 const upcoming=P.dossiers.filter(isUpcoming).sort((a,b)=>score(b)-score(a));
 const consultation=P.dossiers.filter(isConsultation).sort((a,b)=>score(b)-score(a));
 const changes=recentNews();
 const surface=document.createElement('div');surface.className='conciergeSurface';surface.dataset.conciergeSurface='1';
 surface.innerHTML=`
   <section class="conciergeSection conciergeOpen">
     <div class="conciergeSectionHead"><div><span>Deschise acum</span><h2>Finanțări la care poți lucra acum</h2><p>Doar apeluri cu stare și termen confirmate din surse oficiale.</p></div><button data-concierge-hub="open">Vezi toate ${canonicalOpenTotal?`(${canonicalOpenTotal})`:''} →</button></div>
     <div class="conciergeGrid">${open.slice(0,6).map(d=>card(d,'open')).join('')||'<div class="conciergeEmpty">Nu există acum apeluri deschise care trec toate verificările noastre.</div>'}</div>
   </section>
   <section class="conciergeService" data-rpm-promo="1" aria-label="Română pentru Muncă">
     <div class="conciergeServiceIcon" aria-hidden="true">RO</div>
     <div class="conciergeServiceCopy"><span>Serviciu pentru angajatori</span><h2>Ai angajați străini? Română pentru Muncă.</h2><p>Curs de limba română organizat pentru echipe: program, participare și documentele necesare, într-un singur flux.</p></div>
     <a href="/romana-pentru-munca/">Vezi oferta <b>→</b></a>
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
 surface.querySelector('[data-concierge-consultation]')?.addEventListener('click',()=>location.assign('/consultari/'));
}
const needsRender=()=>{const hero=document.querySelector('.main .hero');return !!hero&&!document.querySelector('[data-concierge-surface]')};
render();
const appRoot=document.getElementById('app');
if(appRoot)new MutationObserver(()=>{if(needsRender())render()}).observe(appRoot,{childList:true});
window.addEventListener('popstate',()=>setTimeout(()=>{if(needsRender())render()},0));
})();
