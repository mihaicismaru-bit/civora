(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roDate=v=>{try{return new Date(v).toLocaleString('ro-RO',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})}catch{return String(v||'')}};
const MONTHS={ianuarie:0,februarie:1,martie:2,aprilie:3,mai:4,iunie:5,iulie:6,august:7,septembrie:8,octombrie:9,noiembrie:10,decembrie:11};
function parseDecisionDate(value){
 if(!value)return null;
 const raw=String(value).trim();
 const direct=new Date(raw);
 if(!Number.isNaN(direct.getTime()))return direct;
 const normalized=raw.toLocaleLowerCase('ro-RO').replace(/[,.]/g,' ');
 const match=normalized.match(/(\d{1,2})\s+(ianuarie|februarie|martie|aprilie|mai|iunie|iulie|august|septembrie|octombrie|noiembrie|decembrie)\s+(20\d{2})(?:\D+(\d{1,2}):(\d{2}))?/i);
 if(!match)return null;
 return new Date(Number(match[3]),MONTHS[match[2]],Number(match[1]),Number(match[4]||23),Number(match[5]||59),0,0);
}
function factRow(d,...labels){
 const wanted=new Set(labels.map(x=>String(x).toLocaleLowerCase('ro-RO')));
 return (d.quickFacts||[]).find(row=>wanted.has(String(row?.label||'').toLocaleLowerCase('ro-RO')))||null;
}
function fact(d,...labels){const row=factRow(d,...labels);const value=String(row?.value||'').trim();return value&&!['Neconfirmat','—'].includes(value)?value:''}
function confirmedFact(d,label){const row=factRow(d,label);return String(row?.confidence||'').toUpperCase()==='CONFIRMED'?row:null}
function lifecycleDates(d){
 const values=[];
 ['openFrom','opensAt','openAt','deadline','closesAt','closeAt','consultationDeadline','publishedAt','publicationDate'].forEach(k=>{if(d[k])values.push(d[k])});
 (d.quickFacts||[]).forEach(row=>{if(/termen|deschidere|depunere|consult|publicare|calendar/i.test(String(row?.label||'')))values.push(row?.value)});
 return values.map(parseDecisionDate).filter(Boolean);
}
function currentEvidence(d,now){return lifecycleDates(d).some(x=>x.getFullYear()>=now.getFullYear()&&x>=new Date(now.getFullYear(),0,1))}
function currentOpen(d,now){
 if(String(d.status||'').toUpperCase()!=='OPEN'||String(d.publicationState||'').toUpperCase()!=='PUBLISHABLE')return false;
 const status=confirmedFact(d,'Status'),term=confirmedFact(d,'Termen');
 if(!status||!term)return false;
 const deadline=parseDecisionDate(term.value);
 return !!deadline&&deadline>=now;
}
function currentUpcoming(d,now){return String(d.status||'').toUpperCase()==='EXPECTED'&&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'&&currentEvidence(d,now)}
function currentConsultation(d,now){return String(d.status||'').toUpperCase()==='PUBLIC_CONSULTATION'&&String(d.publicationState||'').toUpperCase()==='PUBLISHABLE'&&currentEvidence(d,now)}
function dossierDeadline(d){return parseDecisionDate(fact(d,'Termen','Deschidere','Depunere','Termen consultare'))}
function sortDossiers(items){return [...items].sort((a,b)=>{const ad=dossierDeadline(a)?.getTime()??Number.MAX_SAFE_INTEGER;const bd=dossierDeadline(b)?.getTime()??Number.MAX_SAFE_INTEGER;return ad-bd||String(a.title||'').localeCompare(String(b.title||''),'ro')})}
function openInternal(item){
 if(item.dossierId){
  const open=()=>window.PARTENER_DECISION_UI?.openDossier?.(item.dossierId)===true;
  if(open())return;
  document.querySelector('[data-decisionnav]')?.click();
  let attempts=0;const retry=setInterval(()=>{attempts+=1;if(open()||attempts>=10)clearInterval(retry)},80);
  return
 }
 if(item.newsId){const nav=document.querySelector('[data-decisionnav]');nav?.click();setTimeout(()=>{document.querySelector('[data-di-tab="news"]')?.click();setTimeout(()=>document.querySelector(`[data-di-news="${CSS.escape(item.newsId)}"]`)?.click(),60)},60);return}
}
function card(i,n){const internal=!!(i.dossierId||i.newsId);return `<article class="dailyBriefCard ${n===0?'primary':''}" data-brief-id="${esc(i.id)}" tabindex="0"><div class="dailyBriefMeta"><span class="dailyBriefTag ${esc(i.tone||'update')}">${esc(i.label||'ACTUALIZARE')}</span><span class="dailyBriefTag">${esc(i.programme||'')}</span></div><h3>${esc(i.title)}</h3><p>${esc(i.summary)}</p><div class="dailyBriefAction"><span>${esc(i.action)}</span><b>${internal?'Deschide dosarul →':'Sursa oficială ↗'}</b></div></article>`}
function injectBrief(){
 const data=window.PARTENER_DAILY_BRIEF;
 const hero=document.querySelector('.hero');
 if(!hero||!data||!Array.isArray(data.items)||!data.items.length)return;
 document.querySelector('[data-dailybrief]')?.remove();
 const section=document.createElement('section');section.className='dailyBrief';section.dataset.dailybrief=data.asOf||'generated';
 section.innerHTML=`<div class="dailyBriefHead"><div><div class="eyebrow">Briefing verificat · ${esc(data.dateLabel||'astăzi')}</div><h2>${esc(data.title||'Ce este nou și ce trebuie făcut acum')}</h2><div class="dailyBriefLead">${esc(data.lead||'Selecție zilnică din informații verificate.')}</div></div><div class="dailyBriefStamp"><span>Actualizat</span><b>${esc(roDate(data.asOf))}</b><span>surse oficiale · selecție automată</span></div></div><div class="dailyBriefGrid">${data.items.map(card).join('')}</div><div class="dailyBriefFoot"><span>${data.parallel?`<strong>În paralel:</strong> ${esc(data.parallel.replace(/^În paralel:\s*/i,''))}`:'Briefingul se regenerează automat din dosarele și schimbările verificate.'}</span><button type="button" data-daily-all>Vezi toate dosarele</button></div>`;
 hero.insertAdjacentElement('afterend',section);
 section.querySelectorAll('[data-brief-id]').forEach((el,idx)=>{const item=data.items[idx];const go=()=>{if(item.dossierId||item.newsId)openInternal(item);else if(item.url&&/^https?:/i.test(item.url))window.open(item.url,'_blank','noopener,noreferrer')};el.onclick=go;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}}});
 section.querySelector('[data-daily-all]')?.addEventListener('click',()=>document.querySelector('[data-decisionnav]')?.click());
}
function compactSummary(d,kind){
 const grant=fact(d,'Grant','Valoare proiect','Finanțare','Buget');
 const term=fact(d,'Termen','Deschidere','Depunere','Termen consultare');
 const parts=[];
 if(grant)parts.push(grant);
 if(term)parts.push(`${kind==='upcoming'?'Calendar':'Termen'}: ${term}`);
 return parts.join(' · ')||String(d.standfirst||d.decisionAction||'Deschide dosarul pentru detaliile confirmate.').slice(0,220);
}
function catalogRow(d,kind){
 const label=kind==='open'?'DESCHIS':kind==='upcoming'?'URMEAZĂ':'ÎN CONSULTARE';
 return `<article class="openCallsRow" data-catalog-dossier="${esc(d.id)}" tabindex="0"><div class="openCallsRowMain"><div class="openCallsRowMeta"><span class="openCallsPill ${kind}">${label}</span><span>${esc(d.programme||'Program')}</span></div><h3>${esc(d.title||'Oportunitate de finanțare')}</h3><p>${esc(compactSummary(d,kind))}</p></div><span class="openCallsArrow" aria-hidden="true">→</span></article>`;
}
function bindCatalogRows(scope){scope.querySelectorAll('[data-catalog-dossier]').forEach(el=>{const go=()=>openInternal({dossierId:el.dataset.catalogDossier});el.addEventListener('click',go);el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();go()}})})}
function injectCatalog(){
 const products=window.PARTENER_DECISION_PRODUCTS;
 const hero=document.querySelector('.hero');
 if(!hero||!products||!Array.isArray(products.dossiers))return;
 const now=new Date();
 const groups={open:sortDossiers(products.dossiers.filter(d=>currentOpen(d,now))),upcoming:sortDossiers(products.dossiers.filter(d=>currentUpcoming(d,now))),consultation:sortDossiers(products.dossiers.filter(d=>currentConsultation(d,now)))};
 if(!groups.open.length&&!groups.upcoming.length&&!groups.consultation.length)return;
 document.querySelector('[data-open-calls-catalog]')?.remove();
 const anchor=document.querySelector('[data-dailybrief]')||hero;
 const section=document.createElement('section');section.className='openCallsCatalog';section.dataset.openCallsCatalog='verified';
 const tabs=[['open','Apeluri deschise acum'],['upcoming','Se deschid în curând'],['consultation','În consultare']];
 section.innerHTML=`<div class="openCallsHead"><div><div class="eyebrow">Catalog live verificat</div><h2>Toate oportunitățile curente, fără să ascundem restul pieței</h2><p>Briefingul de mai sus rămâne selecția de priorități. Aici vezi catalogul curent rezultat numai din dosare publicabile și dovezi oficiale; elementele fail-closed sau fără termen verificat nu intră la „deschis”.</p></div><button type="button" class="openCallsAllDossiers" data-catalog-all>Deschide catalogul complet</button></div><div class="openCallsTabs" role="tablist">${tabs.map(([key,label],idx)=>`<button type="button" role="tab" aria-selected="${idx===0?'true':'false'}" data-catalog-tab="${key}">${label}<b>${groups[key].length}</b></button>`).join('')}</div><div class="openCallsPanels">${tabs.map(([key,label],idx)=>`<div class="openCallsPanel" data-catalog-panel="${key}" ${idx?'hidden':''}><div class="openCallsList">${groups[key].slice(0,12).map(d=>catalogRow(d,key)).join('')}</div>${groups[key].length>12?`<button type="button" class="openCallsMore" data-catalog-more="${key}">Arată toate cele ${groups[key].length}</button>`:''}${groups[key].length===0?`<div class="openCallsEmpty">Nu există elemente care trec acum gate-ul verificat pentru această categorie.</div>`:''}</div>`).join('')}</div><div class="openCallsFoot">OPEN este afișat numai când statusul și termenul sunt confirmate, apelul este publicabil și termenul nu a expirat.</div>`;
 anchor.insertAdjacentElement('afterend',section);
 bindCatalogRows(section);
 section.querySelectorAll('[data-catalog-tab]').forEach(btn=>btn.addEventListener('click',()=>{const key=btn.dataset.catalogTab;section.querySelectorAll('[data-catalog-tab]').forEach(x=>x.setAttribute('aria-selected',String(x===btn)));section.querySelectorAll('[data-catalog-panel]').forEach(panel=>panel.hidden=panel.dataset.catalogPanel!==key)}));
 section.querySelectorAll('[data-catalog-more]').forEach(btn=>btn.addEventListener('click',()=>{const key=btn.dataset.catalogMore;const list=section.querySelector(`[data-catalog-panel="${key}"] .openCallsList`);if(!list)return;list.innerHTML=groups[key].map(d=>catalogRow(d,key)).join('');bindCatalogRows(list);btn.remove()}));
 section.querySelector('[data-catalog-all]')?.addEventListener('click',()=>document.querySelector('[data-decisionnav]')?.click());
}
function inject(){if(!document.querySelector('[data-dailybrief]'))injectBrief();if(!document.querySelector('[data-open-calls-catalog]'))setTimeout(injectCatalog,20)}
window.addEventListener('load',()=>setTimeout(inject,120),{once:true});
document.addEventListener('click',()=>setTimeout(inject,100),true);
setTimeout(inject,180);
})();
