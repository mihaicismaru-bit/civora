(()=>{
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const data=()=>window.PARTENER_DATA&&window.PARTENER_DATA.peoCalendar;
  const past=x=>{if(!x.plannedLaunch)return false;const d=new Date(x.plannedLaunch);return !Number.isNaN(d.getTime())&&d<new Date()};
  function statusLabel(x){
    if(x.materialization==='LAUNCHED_VERIFIED') return '<span class="pc-badge ok">Lansat ✓</span>';
    if(x.materialization==='CONSULTATION_VERIFIED') return '<span class="pc-badge consult">Consultare</span>';
    if(x.materialization==='MISSED_PLANNED_DATE') return '<span class="pc-badge risk">Întârziere verificată</span>';
    if(past(x)) return '<span class="pc-badge verify">De verificat</span>';
    return '<span class="pc-badge plan">Planificat</span>';
  }
  function fmtDate(v){if(!v)return 'Nespecificată';const d=new Date(v);return Number.isNaN(d.getTime())?v:d.toLocaleDateString('ro-RO',{month:'short',year:'numeric'});}
  function fmtMoney(v){const n=Number(v);return Number.isFinite(n)?new Intl.NumberFormat('ro-RO',{maximumFractionDigits:0}).format(n)+' €':(v||'—');}
  function render(){
    const d=data(); if(!d) return;
    const main=document.querySelector('.main'); if(!main) return;
    const eyebrow=[...main.querySelectorAll('.eyebrow')].find(x=>x.textContent.includes('Funding Calendar'));
    if(!eyebrow||document.getElementById('peo-calendar-panel')) return;
    const host=document.createElement('section');host.id='peo-calendar-panel';host.className='pc-wrap';
    const provenance=d.directMipeVerified?'<span class="pc-source direct">MIPE verificat direct</span>':'<span class="pc-source institutional">Copie instituțională OIR · MIPE direct indisponibil</span>';
    const needsCheck=(d.items||[]).filter(x=>past(x)&&!['LAUNCHED_VERIFIED','CONSULTATION_VERIFIED'].includes(x.materialization)).length;
    const rows=(d.items||[]).map(x=>`<div class="pc-row"><div>${statusLabel(x)}</div><div><div class="pc-title">${esc(x.title)}</div><div class="pc-meta">${esc(x.priority||'PEO')}${x.region?' · '+esc(x.region):''}</div></div><div><div class="pc-k">Lansare estimată</div><b>${esc(fmtDate(x.plannedLaunch))}</b><div class="pc-meta">închidere: ${esc(fmtDate(x.plannedClose))}</div></div><div><div class="pc-k">Buget / alocare</div><b>${esc(fmtMoney(x.budget))}</b><div class="pc-meta">${esc(x.fund||'')}</div></div></div>`).join('');
    host.innerHTML=`<div class="pc-head"><div><div class="eyebrow">Calendar oficial PEO</div><h2>${esc(d.title||'Calendar lansări PEO')}</h2><div class="sectionDesc">Calendarul este o intenție oficială de lansare, nu dovada că apelul este OPEN. CIVORA verifică separat materializarea fiecărui rând.</div></div><div class="pc-prov">${provenance}<span class="pc-version">${d.itemCount||0} poziții · versiune ${esc((d.versionSha256||'').slice(0,10))}</span></div></div><div class="pc-kpis"><div><strong>${d.itemCount||0}</strong><span>poziții PEO</span></div><div><strong>${(d.items||[]).filter(x=>x.materialization==='LAUNCHED_VERIFIED').length}</strong><span>lansări verificate</span></div><div><strong>${needsCheck}</strong><span>date trecute de verificat</span></div><div><strong>${d.changeCount||0}</strong><span>schimbări de versiune</span></div></div><div class="pc-legend"><span>Planificat ≠ OPEN</span><span>„De verificat” ≠ întârziat</span><span>Materializarea cere evidență oficială</span><span>Workbook-ul este versionat prin SHA-256</span></div><div class="pc-list">${rows||'<div class="notice">Calendarul este monitorizat, dar nu există încă rânduri parsate.</div>'}</div>`;
    const existing=main.querySelector('.section.list');if(existing)existing.before(host);else main.appendChild(host);
  }
  const obs=new MutationObserver(render);obs.observe(document.documentElement,{subtree:true,childList:true});render();
})();
