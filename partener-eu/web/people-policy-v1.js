(()=>{
'use strict';
const P=window.PARTENER_PEOPLE_POLICY;if(!P||!Array.isArray(P.items))return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const typeLabel=t=>({FUNDING_COMMITMENT:'FINANȚARE / BUGET',PROGRAMME_CHANGE_SIGNAL:'CALENDAR / PROGRAM',POLICY_SIGNAL:'POLITICĂ PUBLICĂ'}[t]||'SEMNAL PUBLIC');
const typeClass=t=>t==='FUNDING_COMMITMENT'?'commitment':t==='PROGRAMME_CHANGE_SIGNAL'?'change':'policy';
const dateText=v=>{try{return new Date(v).toLocaleDateString('ro-RO',{day:'numeric',month:'long',year:'numeric'})}catch{return String(v||'')}};
const byId=new Map(P.items.map(x=>[x.id,x]));
function isHome(){return !!document.querySelector('.main .hero')&&!document.querySelector('.main .ask')}
function photo(x){return x.photoUrl?`<img src="${esc(x.photoUrl)}" alt="${esc(x.person||x.institution||'Sursă oficială')}" loading="lazy" referrerpolicy="no-referrer">`:`<span>${esc(x.initials||'•')}</span>`}
function primarySource(x){return (x.sources||[]).find(s=>s?.url)||null}
function card(x){const src=primarySource(x);return `<article class="personCard commercial"><div class="personPhoto">${photo(x)}<span class="signalBadge ${typeClass(x.type)}">${esc(typeLabel(x.type))}</span></div><div class="personCardBody"><div class="personName">${esc(x.person||x.institution||'Sursă oficială')}</div><div class="personRole">${esc(x.role||'Decident / instituție publică')}</div><div class="personMeta">${esc(dateText(x.date))} · ${esc(x.topic||x.institution||'Fonduri europene')}</div><h3>${esc(x.headline)}</h3><p class="personTake"><b>De ce contează:</b> ${esc(x.whyItMatters||x.analysis||'Semnal relevant pentru finanțări.')}</p><div class="personCardFoot"><span>${esc(x.institution||'Sursă oficială')}</span>${src?`<a href="${esc(src.url)}" target="_blank" rel="noreferrer">Sursa oficială ↗</a>`:'<span>Sursă în verificare</span>'}</div></div></article>`}
function removePromo(){document.querySelectorAll('[data-peoplepromo]').forEach(x=>x.remove())}
function inject(){const main=document.querySelector('.main');if(!main)return;if(!isHome()){removePromo();return}if(document.querySelector('[data-peoplepromo]'))return;const chosen=(P.homeIds||[]).map(id=>byId.get(id)).filter(Boolean).slice(0,3);if(!chosen.length)return;const section=document.createElement('section');section.className='section peoplePromo';section.dataset.peoplepromo='1';section.innerHTML=`<div class="peopleHead"><div><div class="eyebrow">Semnale oficiale relevante</div><h2>Ce spun decidenții</h2><div class="peopleSub">Doar semnale recente din surse oficiale care pot schimba finanțarea, calendarul sau prioritățile. O declarație nu modifică singură un apel.</div></div></div><div class="peopleGrid">${chosen.map(card).join('')}</div>`;main.appendChild(section)}
let timer=null;function sync(){clearTimeout(timer);timer=setTimeout(()=>{removePromo();inject()},80)}
const app=document.querySelector('#app')||document.body;new MutationObserver(sync).observe(app,{childList:true,subtree:true});window.addEventListener('load',sync,{once:true});setTimeout(sync,220);
})();
