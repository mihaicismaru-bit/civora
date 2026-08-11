(()=>{
const D=window.PARTENER_DATA=window.PARTENER_DATA||{};
const SOURCE='https://www.afir.ro/domenii-de-interventie/detalii-si-anexe-dr-14/';
const RELEASE='https://www.afir.ro/comunicate/afir-a-publicat-conditiile-accesarii-fondurilor-pentru-investitii-in-ferme-mici/';
const DOCS=[
['Ghidul Solicitantului DR 14','1,54 MB'],
['Anexa 2 - C1.1 Model Contract de Finanțare','152,34 KB'],
['Anexa 3 - Anexa I la Tratatul de instituire al Comunității Europene','231,33 KB'],
['Anexa 4 - Fișa intervenției DR 14','37,29 KB'],
['Anexa 5 - Lista Actelor Normative Utile','129,02 KB'],
['Anexa 6 – Lista UAT care se regăsesc în Zonele Montane (ZM), utilizată pentru justificarea încadrării exploatației','9,22 MB'],
['Anexa 7 - Lista UAT din zona unde se implementează Instrumentul Teritorial Integrat (ITI)','269,35 KB'],
['Anexa 8 - Instrucțiuni evitare creare condiții artificiale PS 2023 - 2027','44,49 KB'],
['Anexa 9 - Instrucțiuni Proiecții Financiare (Anexa C)','20,12 KB'],
['Anexa 10 - Anexa C DR 14 pentru toți solicitanții','186,36 KB'],
['Anexa 11 - Model adeverință emisă de forma asociativă pentru dovedirea calității de membru a beneficiarului','22,83 KB'],
['Anexa 12 - Programul de Acțiune și Codul de Bune Practici Agricole – Ordin ANPM și MADR','12,37 MB'],
['Anexa 13 - Lista pentru verificarea conformității platformelor individuale','28,58 KB'],
['Anexa 14 - Lista Rase Autohtone','21,9 KB'],
['Anexa 15 - Lista UAT din Zonele cu Constrângeri Semnificative, Zonele cu Constrângeri Specifice și Zonele Normale','9,22 MB'],
['Anexa 16 - Corelarea puterii mașinii cu suprafața fermei pentru achiziționarea de mașini agricole','398,92 KB'],
['E 1.2 - Fișa de evaluare a proiectului DR 14','410,6 KB']
].map((x,i)=>({no:i+1,name:x[0],size:x[1],date:'06.08.2026',source:SOURCE}));
D.dr14Story={
 id:'afir-dr14-final-guide-2026-08-06',
 tag:'AFIR · DR-14',
 kind:'GHID FINAL PUBLICAT',
 status:'SESIUNE ÎN PREGĂTIRE',
 date:'6 august 2026',
 headline:'DR-14: AFIR a publicat ghidul final pentru investiții în ferme mici. 50.000 € / proiect, până la 85% nerambursabil',
 deck:'Pachetul final are 17 documente. Sesiunea nu este încă deschisă; AFIR spune că depunerea va începe după cel puțin 15 zile de la publicarea ghidului.',
 source:SOURCE,
 release:RELEASE,
 documents:DOCS
};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
function render(){
 const main=document.querySelector('.main');if(!main)return;
 const s=D.dr14Story;
 main.innerHTML=`<article class="dr14Article">
 <header class="dr14Hero"><button class="btn ghost dr14Back">← Înapoi</button><div class="dr14Tags"><span>AFIR</span><span>DR-14</span><span>GHID FINAL</span><span class="wait">SESIUNE ÎN PREGĂTIRE</span></div><h1>${esc(s.headline)}</h1><p>${esc(s.deck)}</p><div class="dr14Meta">Publicat de AFIR: 6 august 2026 · analiză PARTENER.EU: 11 august 2026</div></header>
 <section class="dr14Facts"><div><small>Grant maxim</small><b>50.000 €</b></div><div><small>Intensitate</small><b>max. 85%</b></div><div><small>Contribuție proprie</small><b>min. 15%</b></div><div><small>Documente oficiale</small><b>17</b></div></section>
 <section class="dr14Block important"><h2>Status acum</h2><p><b>Ghidul final este publicat, dar sesiunea nu este încă deschisă.</b> AFIR precizează că depunerea online va începe în perioada sesiunii de primire a proiectelor, care va fi deschisă după cel puțin 15 zile de la publicarea ghidului. Din 6 august rezultă că 21 august 2026 este doar <em>cea mai devreme dată posibilă</em>, nu data oficială de lansare. Data, alocarea sesiunii și pragurile de calitate trebuie preluate exclusiv din anunțul de lansare AFIR.</p></section>
 <section class="dr14Block"><h2>Cine poate aplica</h2><p>Beneficiarii sunt <b>fermierii, cu excepția persoanelor fizice</b>. AFIR precizează că statutul de mic fermier va fi verificat în baza IACS – APIA, inclusiv codul exploatației înregistrat pentru entitatea economică solicitantă.</p><p class="dr14Caution">PARTENER.EU nu fixează aici pragurile SO/SOC din versiunile consultative. Pentru verdictul de eligibilitate trebuie folosit Ghidul final din 06.08.2026 și datele reale ale exploatației.</p></section>
 <section class="dr14Block"><h2>Ce finanțează</h2><div class="dr14Bullets"><div>Construirea sau modernizarea construcțiilor cu destinație agricolă ori necesare în fermă.</div><div>Facilități pentru gestionarea adecvată a gunoiului de grajd.</div><div>Unități de condiționare, depozitare și procesare la nivelul fermei, inclusiv comercializarea și marketingul produselor agricole proprii.</div><div>Mașini agricole specializate și echipamente noi.</div><div>Acces la utilități în exploatația agricolă.</div><div>Înființarea și modernizarea echipamentelor pentru irigații și facilități de stocare a apei, ca parte secundară a proiectului.</div></div><p>AFIR precizează că lista integrală a investițiilor finanțabile este în Ghidul solicitantului; lista de mai sus reprezintă categoriile confirmate explicit în comunicatul final din 6 august.</p></section>
 <section class="dr14Block"><h2>Ce trebuie pregătit acum</h2><ol class="dr14Steps"><li><b>Verificarea fermei în IACS/APIA</b> și corelarea codului exploatației cu forma juridică ce va depune proiectul.</li><li><b>Încadrarea economică exactă</b> după regulile Ghidului final, nu după informații din perioada consultativă.</li><li><b>Lista investiției</b> și justificarea legăturii fiecărei cheltuieli cu producția agricolă primară și modernizarea exploatației.</li><li><b>Cofinanțarea</b>: proiectul trebuie construit ținând cont de contribuția proprie de minimum 15% plus eventualele costuri neeligibile.</li><li><b>Localizarea</b>: verificarea anexelor UAT pentru zonă montană, ITI și zone cu constrângeri, dacă sunt relevante.</li><li><b>Proiecțiile financiare</b>: Anexa C și instrucțiunile aferente trebuie lucrate înainte de depunere, nu în ultima zi.</li><li><b>Punctajul</b>: se simulează pe Fișa E1.2 înainte de decizia GO/NO-GO.</li><li><b>Condiții artificiale</b>: structura exploatației, relațiile între entități și investiția nu trebuie create sau fragmentate artificial pentru accesarea sprijinului.</li></ol></section>
 <section class="dr14Block"><h2>Ce NU știm încă</h2><p>Pagina și comunicatul AFIR din 6 august nu stabilesc în textul public afișat <b>data exactă de deschidere și închidere a sesiunii, alocarea sesiunii sau pragurile lunare de calitate</b>. Acestea trebuie confirmate prin anunțul oficial de lansare. Până atunci, DR-14 trebuie tratat ca <b>READY TO PREPARE</b>, nu ca apel OPEN.</p></section>
 <section class="dr14Block"><h2>Documentele oficiale găsite</h2><p class="dr14DocLead">AFIR afișează pe pagina DR-14 următoarele 17 documente, toate datate 06.08.2026. Portalul AFIR generează linkurile de fișier prin endpoint-uri de descărcare/redirect, astfel că PARTENER.EU păstrează proveniența și trimite la pagina oficială, fără a crea copii necontrolate ale anexelor.</p><div class="dr14Docs">${DOCS.map(d=>`<div class="dr14Doc"><div class="dr14DocNo">${d.no}</div><div class="dr14DocBody"><b>${esc(d.name)}</b><span>${esc(d.size)} · ${esc(d.date)}</span></div><a href="${SOURCE}" target="_blank" rel="noreferrer">Deschide în AFIR ↗</a></div>`).join('')}</div></section>
 <section class="dr14Block source"><h2>Surse</h2><div class="dr14Sources"><a href="${SOURCE}" target="_blank" rel="noreferrer"><b>AFIR — Detalii și Anexe DR 14</b><span>Ghid final + 16 anexe / fișe afișate la 06.08.2026</span></a><a href="${RELEASE}" target="_blank" rel="noreferrer"><b>AFIR — Comunicat 06.08.2026</b><span>Condiții, finanțare, beneficiari și regula de minimum 15 zile până la deschiderea sesiunii</span></a></div></section>
 </article>`;
 main.querySelector('.dr14Back').onclick=()=>{const brand=document.querySelector('.brand');if(brand)brand.click();else location.reload()};
}
function card(){return `<article class="dr14NewsCard" data-dr14open><div class="dr14CardTop"><span>AFIR · DR-14</span><span class="wait">GHID FINAL · NU E OPEN</span></div><h3>50.000 € pentru ferme mici: ghidul final DR-14 și toate documentele publicate de AFIR</h3><p>17 documente oficiale · max. 85% nerambursabil · pregătirea dosarului poate începe acum.</p><div class="dr14CardFoot">6 august 2026 <b>Analiză completă →</b></div></article>`}
function inject(){
 const hero=document.querySelector('.hero');
 if(hero&&!document.querySelector('[data-dr14promo]')){const wrap=document.createElement('section');wrap.className='section dr14Promo';wrap.dataset.dr14promo='1';wrap.innerHTML=`<div class="eyebrow">Dosar de finanțare</div><h2>Nou pe AFIR: DR-14 pentru ferme mici</h2>${card()}`;const news=document.querySelector('[data-newspromo]');(news||hero).insertAdjacentElement('afterend',wrap);wrap.querySelector('[data-dr14open]').onclick=render;}
 const list=document.querySelector('.newsList');
 if(list&&!list.querySelector('[data-dr14open]')){const w=document.createElement('div');w.innerHTML=card();const c=w.firstElementChild;list.insertAdjacentElement('afterbegin',c);c.onclick=render;}
}
const obs=new MutationObserver(inject);obs.observe(document.getElementById('app'),{childList:true,subtree:true});inject();
})();
