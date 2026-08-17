(()=>{
'use strict';
const P=window.PARTENER_DECISION_PRODUCTS||{dossiers:[]};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const norm=s=>String(s||'').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g,'').replace(/[^a-z0-9]+/g,' ').trim();
const words=s=>new Set(norm(s).split(/\s+/).filter(x=>x.length>=3));
const fact=(d,label)=>(d.quickFacts||[]).find(x=>x.label===label);
const factText=(d,label)=>{const f=fact(d,label);return f&&f.value&&!['Neconfirmat','—'].includes(String(f.value))?String(f.value):'Neconfirmat'};
const eventLabels={CALL_OPENED:'Apel deschis',GUIDE_PUBLISHED:'Ghid publicat',GUIDE_MODIFIED:'Ghid modificat',GUIDE_UPDATED_AFTER_CONSULTATION:'Ghid final actualizat',CONSULTATION_OPENED:'Consultare publică deschisă',CONSULTATION_CLOSED:'Consultare încheiată',DEADLINE_EXTENDED:'Termen prelungit',CALL_CLOSED:'Depunere închisă',EVALUATION_UPDATE:'Evaluare în curs',RESULTS_PUBLISHED:'Rezultate publicate',CONTRACTING_UPDATE:'Contractare actualizată',CONTRACTS_PUBLISHED:'Contracte publicate',OFFICIAL_UPDATE:'Actualizare oficială'};
const clusters=[
 {id:'energie',label:'energie regenerabilă',terms:['energie','regenerabil','fotovoltaic','solar','autoconsum','baterii','stocare']},
 {id:'digital',label:'digitalizare',terms:['digital','digitalizare','tehnologii','software','cloud','automatizare','it']},
 {id:'agri',label:'agricultură',terms:['agricultura','agricol','ferma','fermieri','afir','procesare','alimentara','alimentar']},
 {id:'social',label:'servicii sociale',terms:['social','incluziune','vulnerabil','ong','asociatie','fundatie']},
 {id:'educatie',label:'educație / formare',terms:['educatie','scoala','universitate','formare','competente','ocupare','tineri','neet']},
 {id:'sanatate',label:'sănătate',terms:['sanatate','spital','medical','cabinet','medici']},
 {id:'turism',label:'turism',terms:['turism','turistic','hotel','cazare']},
 {id:'productie',label:'investiții productive',terms:['productie','productiva','utilaje','echipamente','capacitate','investitie']}
];
const actors=[
 {id:'firma',label:'firmă / IMM',query:['firma','imm','srl','companie','intreprindere'],target:['imm','intreprindere','societate','companie','microintreprindere']},
 {id:'ong',label:'ONG',query:['ong','asociatie','fundatie'],target:['ong','asociatie','fundatie']},
 {id:'uat',label:'UAT / instituție publică',query:['primarie','uat','consiliu','institutie','autoritate'],target:['uat','autoritate publica','institutie publica','primarie']},
 {id:'educatie',label:'școală / universitate',query:['scoala','universitate','liceu'],target:['unitate de invatamant','universitate','scoala']},
 {id:'fermier',label:'fermier',query:['fermier','ferma','agricultor'],target:['fermier','agricol','exploatatie agricola']}
];
function dossierText(d){return norm([d.title,d.programme,d.region,d.code,d.standfirst,(d.audience||[]).join(' '),(d.sections||[]).map(s=>`${s.title||''} ${(s.items||[]).join(' ')}`).join(' '),JSON.stringify(d.quickFacts||[])].join(' '))}
function score(d,q){const qt=words(q),text=dossierText(d),title=norm(d.title),aud=norm((d.audience||[]).join(' '));let points=0;const why=[];
 for(const w of qt){if(title.includes(w))points+=5;else if(text.includes(w))points+=1.4}
 for(const c of clusters){const asked=c.terms.some(t=>norm(q).includes(norm(t)));const hit=c.terms.some(t=>text.includes(norm(t)));if(asked&&hit){points+=12;why.push(c.label)}}
 for(const a of actors){const asked=a.query.some(t=>norm(q).includes(norm(t)));const hit=a.target.some(t=>aud.includes(norm(t))||text.includes(norm(t)));if(asked&&hit){points+=8;why.push(a.label)}}
 if(d.status==='OPEN')points+=1.5;if((d.quality?.completeness||0)>=70)points+=1;
 return {points,why:[...new Set(why)]};
}
function resultCard(row){const d=row.d;const src=(d.sources||[]).find(s=>s.url);const depth=d.quality?.dossierLevel||`${d.quality?.completeness||0}% structurat`;return `<article class="askV3Card"><div class="askV3Top"><span class="askV3Status">${esc(d.statusLabel||d.status||'În verificare')}</span><span>${esc(depth)}</span></div><h3>${esc(d.title)}</h3><p class="askV3Meta">${esc(d.programme||'')} · ${esc(d.region||'România')}</p><div class="askV3Why"><b>De ce apare:</b> ${esc(row.why.length?row.why.join(' · '):'termenii din întrebare apar în dosarul oficial')}</div><div class="askV3Facts"><span><small>Finanțare</small><b>${esc(factText(d,'Grant')!=='Neconfirmat'?factText(d,'Grant'):factText(d,'Finanțare'))}</b></span><span><small>Termen</small><b>${esc(factText(d,'Termen'))}</b></span></div><p>${esc(d.decisionAction||d.standfirst||'Verifică dosarul și sursa oficială înainte de decizie.')}</p><div class="askV3Actions"><button class="btn" data-ask-open="${esc(d.id)}" data-ask-title="${esc(d.title)}">Deschide dosarul</button>${src?`<a class="btn secondary" href="${esc(src.url)}" target="_blank" rel="noreferrer">Sursa oficială ↗</a>`:''}</div></article>`}
function analyze(root){const input=root.querySelector('#aq');const out=root.querySelector('#ans');const q=(input?.value||'').trim();if(!out)return;if(q.length<4){out.innerHTML='<div class="askV3Notice">Descrie pe scurt cine ești, unde implementezi și ce vrei să finanțezi.</div>';return}
 const rows=(P.dossiers||[]).map(d=>({d,...score(d,q)})).filter(x=>x.points>=6).sort((a,b)=>b.points-a.points||(b.d.quality?.completeness||0)-(a.d.quality?.completeness||0)).slice(0,6);
 if(!rows.length){out.innerHTML='<div class="askV3Notice"><b>Nu am găsit o potrivire suficient de sigură.</b><br>Încearcă să adaugi tipul organizației, județul și investiția dorită. Nu afișăm apeluri aleatoriu când nu avem potrivire.</div>';return}
 out.innerHTML=`<div class="askV3Summary"><b>${rows.length} oportunități relevante în corpusul actual</b><span>Potrivirea este informațională, nu verdict de eligibilitate. Dosarul și ghidul oficial decid.</span></div><div class="askV3Grid">${rows.map(resultCard).join('')}</div>`;bindAskResults(out)}
function bindAskResults(root){root.querySelectorAll('[data-ask-open]').forEach(btn=>btn.onclick=()=>{const id=btn.dataset.askOpen,title=btn.dataset.askTitle||'';const nav=document.querySelector('[data-decisionnav]');if(!nav)return;nav.click();setTimeout(()=>{const q=document.querySelector('#diQ');if(q){q.value=title;q.dispatchEvent(new Event('input',{bubbles:true}))}setTimeout(()=>document.querySelector(`[data-di-dossier="${CSS.escape(id)}"]`)?.click(),360)},60)})}
function enhanceAsk(){const ask=document.querySelector('.main .ask');if(!ask||ask.dataset.askV3==='1')return;ask.dataset.askV3='1';ask.innerHTML=`<div class="eyebrow">Caută în dosarele PARTENER.EU</div><h1>Spune ce vrei să finanțezi.</h1><p class="askV3Intro">Căutăm în dosarele canonice și îți arătăm numai oportunitățile care au o potrivire explicabilă cu întrebarea ta.</p><div class="searchBox"><input id="aq" autocomplete="off" placeholder="Ex.: Sunt IMM în Vâlcea și vreau panouri fotovoltaice și baterii"><button class="btn" id="ago">Caută finanțări</button></div><div class="askV3Hints">Include: <b>tipul organizației</b> · <b>județul/regiunea</b> · <b>investiția</b></div><div id="ans"></div>`;ask.querySelector('#ago').onclick=()=>analyze(ask);ask.querySelector('#aq').onkeydown=e=>{if(e.key==='Enter')analyze(ask)}}
function simplifyNav(){document.querySelectorAll('.navlinks [data-r="changes"]').forEach(x=>x.remove())}
function humanizeEvents(){document.querySelectorAll('.kind').forEach(node=>{const raw=String(node.textContent||'').trim().toUpperCase();if(eventLabels[raw])node.textContent=eventLabels[raw]});document.querySelectorAll('[data-t="changed"]').forEach(x=>{if(/modific/i.test(x.textContent||''))x.textContent='Istoric'})}
let timer=null;function sync(){clearTimeout(timer);timer=setTimeout(()=>{simplifyNav();enhanceAsk();humanizeEvents()},40)}
const app=document.querySelector('#app')||document.body;new MutationObserver(sync).observe(app,{childList:true,subtree:true});window.addEventListener('load',sync,{once:true});setTimeout(sync,140);
})();
