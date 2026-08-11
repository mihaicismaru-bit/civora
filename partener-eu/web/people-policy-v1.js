(()=>{
const D=window.PARTENER_DATA=window.PARTENER_DATA||{};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const items=[
{
 id:'dragos-pislaru-pnrr-revision-2026-06-19',person:'Dragoș Pîslaru',initials:'DP',role:'Ministrul Investițiilor și Proiectelor Europene',date:'19 iunie 2026',type:'FUNDING_COMMITMENT',className:'commitment',topic:'PNRR',headline:'Pîslaru: ultima revizuire tehnică a PNRR păstrează integral componenta de grant',
 statement:'Ministrul a anunțat finalizarea pozitivă a negocierilor tehnice cu Comisia Europeană pentru ultima modificare a PNRR și menținerea integrală a componentei nerambursabile.',
 officialFact:'Rolul de ministru MIPE este confirmat printr-un act normativ publicat la 2 iulie 2026. Valoarea și forma finală a PNRR trebuie tratate ca fapt operațional numai după documentele oficiale de revizuire și deciziile aferente.',
 analysis:'Semnal puternic pentru beneficiarii PNRR: riscul principal nu este dispariția granturilor în ansamblu, ci reclasificarea sau scoaterea proiectelor care nu pot fi finalizate la termen. PARTENER.EU nu transformă declarația într-o modificare de apel fără documentul oficial.',
 watch:'Decizia formală de revizuire, lista finală a investițiilor, jaloanele reformulate și orice efect asupra proiectelor/contractelor individuale.',
 audiences:['UAT','IMM','ONG','Școli','Beneficiari PNRR'],
 sources:[
  {label:'Declarație publică relatată de AGERPRES — 19.06.2026',url:'https://agerpres.ro/economic/2026/06/19/pislaru-am-finalizat-pozitiv-negocierile-tehnice-cu-comisia-europeana-privind-ultima-modificare-de-p--1568296',tier:'PUBLIC_STATEMENT / T2-ATTRIBUTED'},
  {label:'Portal Legislativ — HG nr. 511/2026, rol ministru MIPE',url:'https://legislatie.just.ro/Public/FormaPrintabila/00000G3M21JSNSHWBQN3C3FV4DO59YLY',tier:'T1'}
 ]
},
{
 id:'cseke-attila-pnrr-deadline-2026-07-08',person:'Cseke Attila',initials:'CA',role:'Ministrul Dezvoltării, Lucrărilor Publice și Administrației',date:'8 iulie 2026',type:'PROGRAMME_CHANGE_SIGNAL',className:'commitment',topic:'PNRR / UAT',headline:'Cseke Attila: termenul pentru unele investiții PNRR ale Ministerului Dezvoltării a fost prelungit până la 30 august',
 statement:'Ministrul a cerut beneficiarilor să accelereze execuția și decontarea proiectelor și a anunțat prelungirea termenului pentru investițiile coordonate de minister.',
 officialFact:'Ordinul nr. 770/2026 stabilește juridic prelungirea până la 30 august 2026 pentru proiectele din componentele 5, 10 și 15 gestionate de Ministerul Dezvoltării.',
 analysis:'Aici avem exemplul ideal pentru motor: declarația este doar semnalul editorial, iar actul normativ este faptul canonic. Pentru UAT-uri, acțiunea este imediată: actualizarea calendarului, facturilor și traseului de decontare.',
 watch:'Eventuale instrucțiuni suplimentare de decontare, clarificări pentru proiectele aflate la limită și stadiul absorbției până la termenul final.',
 audiences:['UAT','Școli','Beneficiari PNRR'],
 sources:[
  {label:'Comunicat MDLPA republicat de AGERPRES — 08.07.2026',url:'https://agerpres.ro/comunicate/2026/07/08/comunicat-de-presa---ministerul-dezvoltarii-lucrarilor-publice-si-administratiei--1574219',tier:'T1B OFFICIAL COMMUNIQUE'},
  {label:'Portal Legislativ — Ordinul nr. 770/2026',url:'https://legislatie.just.ro/Public/DetaliiDocument/312129',tier:'T1'}
 ]
},
{
 id:'oana-toiu-eu-budget-cohesion-2026-07-03',person:'Oana Țoiu',initials:'OȚ',role:'Ministrul Afacerilor Externe',date:'3 iulie 2026',type:'POLICY_SIGNAL',className:'policy',topic:'Buget UE post-2027',headline:'Oana Țoiu: coeziunea și competitivitatea trebuie să rămână priorități în negocierile bugetului european',
 statement:'În contextul Președinției irlandeze a Consiliului UE, ministrul a indicat coeziunea, competitivitatea, securitatea și politicile europene tradiționale între prioritățile României.',
 officialFact:'Aceasta este o poziționare de politică publică, nu o alocare de finanțare și nu un apel. Rolul ministerial este confirmat prin acte publicate în Monitorul Oficial în 2026.',
 analysis:'Pentru consultanți și beneficiari, semnalul este relevant pentru cadrul financiar 2028–2034: România va încerca să apere ponderea politicii de coeziune în competiție cu noile priorități europene. Nu produce însă nicio eligibilitate sau finanțare curentă.',
 watch:'Poziția formală a României pentru CFM 2028–2034, propunerea Comisiei, negocierile privind Politica de Coeziune și eventualele noi instrumente de competitivitate.',
 audiences:['Consultanți','UAT','IMM','ONG','Universități'],
 sources:[
  {label:'Comunicat MAE republicat de AGERPRES — 04.07.2026',url:'https://agerpres.ro/comunicate/2026/07/04/comunicat-de-presa---ministerul-afacerilor-externe--1573083',tier:'T1B OFFICIAL COMMUNIQUE'},
  {label:'Portal Legislativ — Ordin MAE nr. 1284/2026',url:'https://legislatie.just.ro/Public/DetaliiDocument/312115',tier:'T1'}
 ]
}
];
D.peoplePolicy={items,asOf:'2026-08-11T21:17:00+03:00',mode:'TEST_V1',policy:'Statement ≠ operational fact. Facts require T1/T1B evidence; analysis is explicitly labeled.'};
let filter='TOATE';
function card(x){return `<article class="personCard" data-personid="${esc(x.id)}"><div class="personTop"><div class="personIdentity"><div class="personAvatar">${esc(x.initials)}</div><div><div class="personName">${esc(x.person)}</div><div class="personRole">${esc(x.role)}</div></div></div><span class="signalBadge ${esc(x.className)}">${esc(x.type.replaceAll('_',' '))}</span></div><h3>${esc(x.headline)}</h3><div class="personMeta">${esc(x.date)} · ${esc(x.topic)}</div><p class="personTake">${esc(x.analysis)}</p></article>`}
function renderPeople(){const main=document.querySelector('.main');if(!main)return;const list=items.filter(x=>filter==='TOATE'||x.type===filter);main.innerHTML=`<section class="peopleHero"><div class="eyebrow">People & Policy Intelligence · TEST v1</div><h1>Oameni & Politici</h1><p class="peopleSub">Declarațiile persoanelor-cheie sunt urmărite ca semnale. PARTENER.EU separă explicit declarația, faptul oficial și analiza proprie, astfel încât o promisiune politică să nu devină accidental „apel de finanțare”.</p><div class="peopleFilters">${['TOATE','FUNDING_COMMITMENT','PROGRAMME_CHANGE_SIGNAL','POLICY_SIGNAL'].map(x=>`<button class="peopleFilter ${filter===x?'active':''}" data-peoplefilter="${esc(x)}">${esc(x.replaceAll('_',' '))}</button>`).join('')}</div><div class="peopleNote">TEST: 3 exemple verificate, pentru a valida produsul și designul înainte de automatizarea ingestiei.</div></section><section class="peopleList">${list.map(card).join('')}</section>`;bind(main)}
function renderArticle(id){const x=items.find(i=>i.id===id);if(!x)return;const main=document.querySelector('.main');if(!main)return;main.innerHTML=`<article class="peopleArticle"><div class="peopleArticleHead"><button class="btn ghost" data-peopleback>← Înapoi</button><div class="personTop" style="margin-top:18px"><div class="personIdentity"><div class="personAvatar">${esc(x.initials)}</div><div><div class="personName">${esc(x.person)}</div><div class="personRole">${esc(x.role)}</div></div></div><span class="signalBadge ${esc(x.className)}">${esc(x.type.replaceAll('_',' '))}</span></div><h1>${esc(x.headline)}</h1><div class="peopleArticleMeta"><span>${esc(x.date)}</span><span>·</span><span>${esc(x.topic)}</span></div></div><div class="peopleArticleBody"><section class="peopleBlock"><div class="peopleEvidence"><div class="evidenceBox"><div class="evidenceLabel">DECLARAȚIE / SEMNAL</div><b>Ce a spus / anunțat</b><p>${esc(x.statement)}</p></div><div class="evidenceBox"><div class="evidenceLabel">FAPT OFICIAL</div><b>Ce putem afirma operațional</b><p>${esc(x.officialFact)}</p></div></div></section><section class="peopleBlock"><h2>Analiza PARTENER.EU</h2><p>${esc(x.analysis)}</p></section><section class="peopleBlock"><h2>Pe cine poate afecta</h2><p>${esc(x.audiences.join(' · '))}</p></section><section class="peopleBlock"><h2>Ce urmărim mai departe</h2><p>${esc(x.watch)}</p></section><section class="peopleBlock"><h2>Surse și proveniență</h2><div class="sourceLinks">${x.sources.map(s=>`<a class="sourceLink" href="${esc(s.url)}" target="_blank" rel="noreferrer"><span><b>${esc(s.label)}</b><small>${esc(s.tier)}</small></span><span>↗</span></a>`).join('')}</div></section></div></article>`;main.querySelector('[data-peopleback]').onclick=renderPeople}
function bind(root=document){root.querySelectorAll('[data-personid]').forEach(n=>n.onclick=()=>renderArticle(n.dataset.personid));root.querySelectorAll('[data-peoplefilter]').forEach(n=>n.onclick=()=>{filter=n.dataset.peoplefilter;renderPeople()})}
function inject(){const nav=document.querySelector('.navlinks');if(nav&&!nav.querySelector('[data-peoplenav]')){const b=document.createElement('button');b.className='navlink peopleNav';b.dataset.peoplenav='1';b.textContent='Oameni & Politici';b.onclick=renderPeople;nav.appendChild(b)}const hero=document.querySelector('.hero');if(hero&&!document.querySelector('[data-peoplepromo]')){const section=document.createElement('section');section.className='section peoplePromo';section.dataset.peoplepromo='1';section.innerHTML=`<div class="peopleHead"><div><div class="eyebrow">People & Policy Intelligence</div><h2>Ce spun oamenii care influențează fondurile</h2><div class="peopleSub">Semnale publice separate de faptele administrative. Test v1 cu 3 personalități.</div></div><button class="btn secondary" data-peopleall>Vezi toate</button></div><div class="peopleGrid">${items.map(card).join('')}</div>`;const news=document.querySelector('[data-newspromo]');(news||hero).insertAdjacentElement('afterend',section);section.querySelector('[data-peopleall]').onclick=renderPeople;bind(section)}}
const obs=new MutationObserver(()=>inject());obs.observe(document.getElementById('app'),{childList:true,subtree:true});inject();
})();
