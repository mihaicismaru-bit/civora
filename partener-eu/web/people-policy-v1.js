(()=>{
'use strict';
const P=window.PARTENER_PEOPLE_POLICY;if(!P||!Array.isArray(P.items))return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const compact=s=>String(s??'').replace(/\s+/g,' ').trim();
const typeLabel=t=>({FUNDING_COMMITMENT:'FINANȚARE / BUGET',PROGRAMME_CHANGE_SIGNAL:'CALENDAR / PROGRAM',POLICY_SIGNAL:'POLITICĂ PUBLICĂ'}[t]||'SEMNAL OFICIAL');
const typeClass=t=>t==='FUNDING_COMMITMENT'?'commitment':t==='PROGRAMME_CHANGE_SIGNAL'?'change':'policy';
const dateText=v=>{try{return new Date(v).toLocaleDateString('ro-RO',{day:'numeric',month:'long',year:'numeric'})}catch{return String(v||'')}};
const byId=new Map(P.items.map(x=>[x.id,x]));
const rawUrl=/^https?:\/\/\S+\/?$/i;
const materialTerms=/(apel|ghid|termen|calendar|buget|alocar|realoc|finanț|finant|depun|eligibil|consultare|prelung|contract|rezultat|selec|lansar|deschider|închider|inchider|corrigend|ordin)/i;
const noisyChrome=/(Despre instituție.*Transparență|Media Articole Descoper|Transparență instituțională.*Informații de interes public)/i;
function isHome(){return !!document.querySelector('.main [data-decision-home="1"]')}
function safeUrl(v){try{const u=new URL(String(v||''),location.href);return /^https?:$/.test(u.protocol)?u.href:''}catch{return ''}}
function sourceTier(s){return String(s?.tier||s?.sourceTier||'').trim()}
function isOfficialSource(s){return /^T1(?:B)?\b/i.test(sourceTier(s))}
function primarySource(x){return (x.sources||[]).find(s=>safeUrl(s?.url)&&isOfficialSource(s))||null}
function cleanStatement(x){const s=compact(x.statement||x.officialFact||'');if(!s||rawUrl.test(s)||noisyChrome.test(s))return '';return s.length>230?s.slice(0,227).trim()+'…':s}
function freshnessDays(){const n=Number(P.policy?.homeFreshnessDays);return Number.isFinite(n)&&n>0?n:60}
function isFresh(x){const t=new Date(x?.date||'').getTime();if(!Number.isFinite(t))return false;const age=(Date.now()-t)/86400000;return age>=-1&&age<=freshnessDays()}
function isMaterial(x){
  if(!x?.officialIngested||!isFresh(x))return false;
  const src=primarySource(x),head=compact(x.headline),statement=compact(x.statement);
  if(!src||head.length<12||rawUrl.test(head)||rawUrl.test(statement)||noisyChrome.test(statement))return false;
  if(x.type==='POLICY_SIGNAL')return false;
  if(!materialTerms.test(`${head} ${statement}`))return false;
  return !!cleanStatement(x);
}
function affectedText(x){
  const topic=compact(x.topic);
  if(topic&&topic.toLowerCase()!=='fonduri europene / decizie publică')return topic;
  const audiences=(x.audiences||[]).map(compact).filter(Boolean);
  return audiences.length?audiences.join(' · '):'beneficiarii și proiectele din aria semnalului';
}
function watchText(x){const w=compact(x.watch);if(w&&!rawUrl.test(w))return w;return 'Ghidul, ordinul, corrigendumul, calendarul sau alt act oficial care transformă semnalul într-o regulă aplicabilă.'}
function card(x){
  const src=primarySource(x),href=safeUrl(src?.url),statement=cleanStatement(x),tier=sourceTier(src);
  return `<a class="personSignalCard" href="${esc(href)}" target="_blank" rel="noreferrer" aria-label="${esc(x.headline)} — deschide sursa oficială"><div class="personSignalTop"><span class="signalBadge ${typeClass(x.type)}">${esc(typeLabel(x.type))}</span><span>${esc(x.institution||src?.label||'Sursă oficială')} · ${esc(dateText(x.date))}</span></div><div class="personName">${esc(x.person||x.institution||'Sursă oficială')}</div>${x.role?`<div class="personRole">${esc(x.role)}</div>`:''}<h3>${esc(x.headline)}</h3><p class="personSignalText"><b>Ce s-a anunțat:</b> ${esc(statement)}</p><p class="personImpact"><b>Poate afecta:</b> ${esc(affectedText(x))}</p><p class="personWatch"><b>Ce fapt oficial lipsește:</b> ${esc(watchText(x))}</p><div class="personCardFoot"><span>${esc(tier||'T1/T1B')} · Analiză PARTENER.EU</span><strong>Vezi semnalul și sursa oficială ↗</strong></div></a>`;
}
function removePromo(){document.querySelectorAll('[data-peoplepromo]').forEach(x=>x.remove())}
function inject(){
  const main=document.querySelector('.main');if(!main)return;
  if(!isHome()){removePromo();return}
  if(document.querySelector('[data-peoplepromo]'))return;
  const chosen=(P.homeIds||[]).map(id=>byId.get(id)).filter(Boolean).filter(isMaterial).slice(0,3);
  if(!chosen.length&&P.policy?.hideWhenNoFreshOfficialSignals!==false){removePromo();return}
  const section=document.createElement('section');section.className='section peoplePromo';section.dataset.peoplepromo='1';
  section.innerHTML=`<div class="peopleHead"><div><div class="eyebrow">Monitorizare decizională</div><h2>Semnale care pot schimba finanțările</h2><div class="peopleSub">Afișăm numai informații oficiale, proaspete și suficient de concrete încât să poată schimba apeluri, bugete, termene, eligibilitatea sau calendarul.</div></div></div>${chosen.length?`<div class="peopleGrid">${chosen.map(card).join('')}</div>`:'<div class="peopleEmpty"><strong>Niciun semnal material confirmat acum.</strong><p>Nu există un semnal oficial proaspăt și suficient de concret pentru afișare.</p></div>'}`;
  main.appendChild(section);
}
let timer=null;function sync(){clearTimeout(timer);timer=setTimeout(()=>{if(isHome())inject();else removePromo()},80)}
const app=document.querySelector('#app')||document.body;new MutationObserver(sync).observe(app,{childList:true,subtree:true});window.addEventListener('load',sync,{once:true});setTimeout(sync,220);
})();
