(()=>{
const D=window.PARTENER_DATA;
if(!D||!D.radarSV)return;
let audience='TOATE';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const badge=s=>`<span class="badge ${s}">${esc(String(s).replaceAll('_',' '))}</span>`;
const priority=p=>`<span class="svprio ${p}">${esc(p)}</span>`;
function radarCalls(){return D.radarSV.callIds.map(id=>D.calls.find(c=>c.id===id)).filter(Boolean).filter(c=>audience==='TOATE'||c.radarSV.audiences.includes(audience));}
function renderRadar(){
 const main=document.querySelector('.main'); if(!main)return;
 const list=radarCalls();
 main.innerHTML=`<section class="svhero"><div><div class="eyebrow">PEO + PoIDS · Sud-Vest Oltenia</div><h1>${esc(D.radarSV.title)}</h1><p>${esc(D.radarSV.description)}</p></div><div class="svsummary"><div><b>${D.radarSV.callIds.length}</b><span>oportunități urmărite</span></div><div><b>${D.radarSV.callIds.map(id=>D.calls.find(c=>c.id===id)).filter(c=>c&&c.status==='OPEN').length}</b><span>OPEN</span></div><div><b>${D.radarSV.callIds.map(id=>D.calls.find(c=>c.id===id)).filter(c=>c&&c.status!=='OPEN').length}</b><span>în pregătire / watch</span></div></div></section>
 <section class="section"><div class="svfilters">${D.radarSV.audiences.map(a=>`<button class="svfilter ${audience===a?'active':''}" data-sva="${esc(a)}">${esc(a)}</button>`).join('')}</div><div class="svnote">Rolurile marcate <b>VERIFY_GUIDE</b> nu sunt transformate în verdict de eligibilitate până la extragerea ghidului final.</div><div class="svgrid">${list.map(c=>`<article class="svcard"><div class="svtop"><div>${badge(c.status)} ${priority(c.radarSV.priority)}</div><div class="svrole">${esc(c.radarSV.role)}</div></div><h3>${esc(c.title)}</h3><div class="meta">${esc(c.programme)} · ${esc(c.region)}</div><div class="svaud">${c.radarSV.audiences.map(a=>`<span>${esc(a)}</span>`).join('')}</div><div class="svfacts"><div><small>Deadline / stare</small><b>${c.status==='OPEN'?esc(c.close):esc(c.consultation||'Monitorizare')}</b></div><div><small>Rol</small><b>${esc(c.radarSV.roleState)}</b></div></div><p>${esc(c.radarSV.note||c.summary)}</p><div class="svactions"><button class="btn small" data-svcall="${esc(c.id)}">Vezi în Explorer</button>${(c.sourceFacts||[])[0]?`<a class="svsource" href="${esc(c.sourceFacts[0].url)}" target="_blank" rel="noreferrer">Sursa oficială</a>`:''}</div></article>`).join('')}</div></section>`;
 main.querySelectorAll('[data-sva]').forEach(b=>b.onclick=()=>{audience=b.dataset.sva;renderRadar()});
 main.querySelectorAll('[data-svcall]').forEach(b=>b.onclick=()=>{
   const id=b.dataset.svcall;
   const row=[...document.querySelectorAll('[data-c]')].find(x=>x.dataset.c===id);
   const brand=document.querySelector('.brand');
   if(brand) brand.click();
   setTimeout(()=>{
     const target=[...document.querySelectorAll('[data-c]')].find(x=>x.dataset.c===id);
     if(target)target.click();
     else { const q=document.getElementById('homeQ'); if(q){q.value=id;} }
   },20);
 });
}
function inject(){
 const nav=document.querySelector('.navlinks');
 if(nav&&!nav.querySelector('[data-svradar]')){
  const b=document.createElement('button'); b.className='navlink svnav'; b.dataset.svradar='1'; b.textContent='Radar SV Oltenia'; b.onclick=renderRadar; nav.appendChild(b);
 }
 const hero=document.querySelector('.hero');
 if(hero&&!document.querySelector('[data-svpromo]')){
   const p=document.createElement('button'); p.className='svpromo'; p.dataset.svpromo='1'; p.innerHTML='<b>Radar Sud-Vest Oltenia</b><span>PEO + PoIDS pentru FPC, școli și ONG-uri →</span>'; p.onclick=renderRadar; hero.insertAdjacentElement('afterend',p);
 }
}
const obs=new MutationObserver(()=>inject()); obs.observe(document.getElementById('app'),{childList:true,subtree:true}); inject();
})();
