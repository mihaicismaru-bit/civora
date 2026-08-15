(()=>{
'use strict';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const roDate=v=>{try{return new Date(v).toLocaleString('ro-RO',{day:'numeric',month:'long',year:'numeric',hour:'2-digit',minute:'2-digit'})}catch{return String(v||'')}};
function openInternal(item){
 if(item.dossierId){const nav=document.querySelector('[data-decisionnav]');nav?.click();setTimeout(()=>document.querySelector(`[data-di-dossier="${CSS.escape(item.dossierId)}"]`)?.click(),80);return}
 if(item.newsId){const nav=document.querySelector('[data-decisionnav]');nav?.click();setTimeout(()=>{document.querySelector('[data-di-tab="news"]')?.click();setTimeout(()=>document.querySelector(`[data-di-news="${CSS.escape(item.newsId)}"]`)?.click(),60)},60);return}
}
function card(i,n){const internal=!!(i.dossierId||i.newsId);return `<article class="dailyBriefCard ${n===0?'primary':''}" data-brief-id="${esc(i.id)}" tabindex="0"><div class="dailyBriefMeta"><span class="dailyBriefTag ${esc(i.tone||'update')}">${esc(i.label||'ACTUALIZARE')}</span><span class="dailyBriefTag">${esc(i.programme||'')}</span></div><h3>${esc(i.title)}</h3><p>${esc(i.summary)}</p><div class="dailyBriefAction"><span>${esc(i.action)}</span><b>${internal?'Deschide dosarul →':'Sursa oficială ↗'}</b></div></article>`}
function inject(){
 const data=window.PARTENER_DAILY_BRIEF;
 const hero=document.querySelector('.hero');
 if(!hero||!data||!Array.isArray(data.items)||!data.items.length)return;
 document.querySelector('[data-dailybrief]')?.remove();
 const section=document.createElement('section');section.className='dailyBrief';section.dataset.dailybrief=data.asOf||'generated';
 section.innerHTML=`<div class="dailyBriefHead"><div><div class="eyebrow">Briefing verificat · ${esc(data.dateLabel||'astăzi')}</div><h2>${esc(data.title||'Ce este nou și ce trebuie făcut acum')}</h2><div class="dailyBriefLead">${esc(data.lead||'Selecție zilnică din informații verificate.')}</div></div><div class="dailyBriefStamp"><span>Actualizat</span><b>${esc(roDate(data.asOf))}</b><span>surse oficiale · selecție automată</span></div></div><div class="dailyBriefGrid">${data.items.map(card).join('')}</div><div class="dailyBriefFoot"><span>${data.parallel?`<strong>În paralel:</strong> ${esc(data.parallel.replace(/^În paralel:\s*/i,''))}`:'Briefingul se regenerează automat din dosarele și schimbările verificate.'}</span><button type="button" data-daily-all>Vezi toate dosarele</button></div>`;
 hero.insertAdjacentElement('afterend',section);
 section.querySelectorAll('[data-brief-id]').forEach((el,idx)=>{const item=data.items[idx];const go=()=>{if(item.dossierId||item.newsId)openInternal(item);else if(item.url&&/^https?:/i.test(item.url))window.open(item.url,'_blank','noopener,noreferrer')};el.onclick=go;el.onkeydown=e=>{if(e.key==='Enter'||e.key===' ')go()}});
 section.querySelector('[data-daily-all]')?.addEventListener('click',()=>document.querySelector('[data-decisionnav]')?.click());
}
window.addEventListener('load',()=>setTimeout(inject,120),{once:true});
document.addEventListener('click',()=>setTimeout(inject,100),true);
setTimeout(inject,180);
})();
