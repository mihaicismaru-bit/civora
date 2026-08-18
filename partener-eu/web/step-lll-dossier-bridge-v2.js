(()=>{
'use strict';
const DP=window.PARTENER_DECISION_PRODUCTS;
const DATA=window.PARTENER_DATA;
if(!DP||!Array.isArray(DP.dossiers)||!DATA||!Array.isArray(DATA.calls))return;
const norm=v=>String(v??'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().replace(/[^a-z0-9]+/g,' ').trim();
const isStep=x=>{const s=norm(`${x?.id||''} ${x?.code||''} ${x?.title||''}`);return s.includes('step lll')&&s.includes('adulti')&&s.includes('competente pentru viitor')};
const call=DATA.calls.find(isStep);
const d=DP.dossiers.find(isStep);
if(!call||!d)return;

const official=[
 {label:'MIPE — Ghidul Solicitantului STEP-LLL Adulți / pagina oficială',url:'https://mfe.gov.ro/ghiduri_peos/step-lll-competente-pentru-viitor-formare-la-locul-de-munca-si-educatia-adultilor-in-tehnologiile-critice-adulti/',tier:'T1',supports:['status','opening','beneficiaries','eligibility','activities','budget','grant','cofinancing','documents','scoring','indicators']},
 {label:'MIPE — Corrigendum nr. 1 STEP-LLL Adulți',url:'https://mfe.gov.ro/wp-content/uploads/2026/07/1678d03c7e876e0c7d010e3242f14d86.pdf',tier:'T1',supports:['deadline']},
 {label:'MIPE — Q&A / Lista de răspunsuri STEP-LLL Adulți',url:'https://mfe.gov.ro/wp-content/uploads/2026/05/3bb3ae91feb38e345bc687add0f88687.pdf',tier:'T1',supports:['beneficiaries','eligibility','activities','grant','cofinancing','geography','scoring','indicators','implementation_period','risks']},
 {label:'OIR PECU Nord-Vest — anunț oficial STEP-LLL',url:'https://www.runv.ro/anunturi.html',tier:'T1B OFFICIAL OIR',supports:['opening','deadline']}
];
if(!official.every(s=>/^https:\/\//.test(s.url)))return;

const APPLICANTS=[
 'Furnizori publici sau privați de formare profesională a adulților (FPC), autorizați în condițiile aplicabile.',
 'Furnizori publici sau privați de servicii specializate pentru stimularea ocupării, în condițiile ghidului.',
 'Confederații sindicale și confederații patronale.',
 'Federații sindicale și federații patronale.',
 'Asociații profesionale sectoriale și alte structuri asociative sectoriale fără scop patrimonial care reprezintă/deservesc operatori economici sau profesioniști din sectoarele STEP ori din sectoare utilizatoare/integratoare ale tehnologiilor STEP.',
 'Institute și centre de formare profesională și cercetare eligibile conform ghidului.'
];
const ELIGIBILITY=[
 'Grupul țintă poate fi format din persoane angajate și/sau șomeri cu vârsta de peste 29 de ani; proiectul nu este obligat să includă simultan ambele categorii.',
 'Proiectul trebuie dimensionat pentru minimum 25 de participanți; numărul maxim rezultă din arhitectura proiectului și din plafonul de valoare eligibilă raportat la participanți.',
 'Proiectul poate acoperi toate regiunile de dezvoltare sau minimum două regiuni de dezvoltare, în funcție de intervențiile și nevoile demonstrate.',
 'Dacă proiectul are un singur solicitant, acesta trebuie să fie furnizor FPC public sau privat autorizat; într-un parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.',
 'Furnizorul care realizează formarea trebuie să demonstreze experiență efectivă relevantă în activități de formare/dezvoltare de competențe în domeniul tehnologic STEP propus; simpla participare formală într-un proiect anterior nu este suficientă.',
 'Persoanele din grupul țintă nu trebuie să provină exclusiv de la angajatori care produc tehnologii STEP, dar proiectul trebuie să demonstreze legătura competențelor dezvoltate cu tehnologiile critice STEP și obiectivele apelului.'
];
const ACTIVITIES=[
 'A1 — servicii de informare și consiliere profesională: activitate opțională și destinată exclusiv șomerilor.',
 'A2.1 — formare profesională care poate include atât angajați, cât și șomeri; sunt posibile forme autorizate de calificare/recalificare/specializare/perfecționare și, în condițiile ghidului, programe cu recunoaștere organizațională sau internațională.',
 'A2.2 — formare profesională la locul de muncă: destinată exclusiv persoanelor angajate.',
 'Conținutul formării trebuie legat substanțial și demonstrabil de domeniile/subdomeniile tehnologice STEP; denumirea generică a cursului nu este suficientă.',
 'Activitățile de mentorat, schimb aplicat de bune practici și transfer tehnic de know-how se tratează în condițiile ghidului; workshopurile/conferințele generale nu substituie automat activitatea eligibilă.'
];
const COSTS=[
 'Alocarea totală a apelului este de 92.000.000 EUR.',
 'Asistența financiară nerambursabilă este de 100% din cheltuielile eligibile, iar rata de cofinanțare proprie a beneficiarului și partenerilor este 0%, conform formei finale clarificate după consultare.',
 '7.974 EUR/participant este reperul pentru dimensionarea valorii eligibile maxime a proiectului în raport cu grupul țintă; nu este un cost unitar/standard decontat automat pentru fiecare participant.',
 'Bugetul proiectului trebuie justificat prin activitățile, rezultatele și costurile efectiv propuse.',
 'Dubla finanțare a acelorași costuri sau activități este interzisă.'
];
const DOCUMENTS=[
 'Ghidul Solicitantului – Condiții Specifice STEP-LLL – Adulți, în versiunea finală/consolidată aplicabilă.',
 'Corrigendum nr. 1 STEP-LLL – Adulți.',
 'Lista de răspunsuri / clarificările Autorității de Management publicate după consultarea ghidului.',
 'Schema de ajutor și anexele aplicabile apelului, în versiunea publicată împreună cu ghidul.',
 'Lista domeniilor, subdomeniilor tehnologice și/sau codurilor relevante pentru încadrarea intervenției STEP, conform anexelor ghidului.',
 'Documentele de eligibilitate ale solicitantului și partenerilor, inclusiv dovezile privind autorizarea FPC acolo unde este necesară.',
 'Dovezile privind experiența efectivă a furnizorului de formare în activități relevante pentru domeniul STEP propus.',
 'Documentele care probează eligibilitatea persoanelor din grupul țintă și încadrarea lor în categoria angajat/șomer și în condiția de vârstă.'
];
const SCORING=[
 'Apel competitiv: proiectele sunt evaluate și ierarhizate conform grilei din ghidul final/consolidat.',
 'În urma consultării a fost eliminat criteriul distinct care puncta depășirea procentuală a țintei EECO01; evaluarea trebuie simulată pe grila finală, nu pe draft.',
 'A fost eliminat și criteriul distinct referitor la „centrele de excelență”; nu îl trata ca pe un criteriu autonom dacă grila finală nu îl mai conține.',
 'Răspunsurile AM clarifică rezultatul consultării; dacă există diferențe, prevalează ghidul final/consolidat și actele ulterioare aplicabile.'
];
const INDICATORS=[
 'Indicatorul de realizare central urmărit este EECO01 — Total participanți.',
 'Ținta programatică indicată după consultare pentru apel este de 11.538 participanți.',
 'Valoarea asumată la nivel de proiect trebuie corelată cu numărul de participanți și cu reperul de maximum 7.974 EUR/participant pentru dimensionarea valorii eligibile maxime.'
];
const OBLIGATIONS=[
 'Eligibilitatea fiecărui participant trebuie documentată și verificată conform ghidului și metodologiei aplicabile.',
 'Persoanele din grupul țintă trebuie să aibă peste 29 de ani și să se încadreze în categoria eligibilă de angajat și/sau șomer relevantă activității în care sunt incluse.',
 'Pentru A1 pot fi incluși numai șomeri; pentru A2.2 pot fi incluși numai angajați.',
 'Trebuie demonstrată legătura conținutului formării cu tehnologiile critice STEP, inclusiv prin curricula/programe și alte dovezi adecvate.',
 'Furnizorul de formare trebuie să poată demonstra experiență efectivă relevantă, nu doar calitatea formală de partener în proiecte anterioare.',
 'Durata de implementare a proiectului este de maximum 36 de luni, în limitele temporale ale programului.'
];
const RISKS=[
 'Bugetarea ca și cum 7.974 EUR/participant ar fi un cost standard decontabil automat, în loc de reper pentru plafonul valorii eligibile maxime.',
 'Construirea proiectului pentru o singură regiune, deși clarificarea AM permite toate regiunile sau minimum două regiuni de dezvoltare.',
 'Includerea angajaților în A1 sau a șomerilor în A2.2, contrar delimitării grupului țintă pe activități.',
 'Solicitant unic care nu este furnizor FPC autorizat ori parteneriat fără cel puțin un furnizor de formare profesională eligibil.',
 'Experiență declarată doar formal, fără dovada implementării efective a activităților de formare/dezvoltare de competențe în domeniul STEP relevant.',
 'Legătură insuficient demonstrată între curricula/competențele propuse și tehnologiile critice STEP.',
 'Folosirea unui termen de depunere anterior în locul termenului prelungit prin Corrigendum nr. 1.'
];
const CORR=[
 'Corrigendum nr. 1 prelungește perioada de depunere a proiectelor până la 30 septembrie 2026, ora 16:00.',
 'Pentru planificarea depunerii se folosește termenul din corrigendum și din documentația consolidată aplicabilă, nu un termen rămas în versiuni anterioare ale paginii/ghidului.',
 'Corrigendumul trebuie citit împreună cu ghidul final/consolidat; această sinteză nu extinde modificarea dincolo de ceea ce este publicat oficial.'
];
const QA=[
 'Grupul țintă poate include angajați și/sau șomeri cu vârsta de peste 29 de ani; nu este obligatorie prezența ambelor categorii în același proiect.',
 'Proiectul trebuie să aibă minimum 25 participanți; suma de 7.974 EUR/participant este reper pentru valoarea eligibilă maximă, nu cost unitar.',
 'Aria proiectului poate acoperi toate regiunile de dezvoltare sau minimum două regiuni; nu este obligatorie implementarea în toate regiunile.',
 'Solicitantul unic trebuie să fie furnizor FPC autorizat; într-un parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.',
 'A1 este opțională și numai pentru șomeri; A2.1 poate include angajați și/sau șomeri; A2.2, formarea la locul de muncă, este numai pentru angajați.',
 'Formarea poate include programe formale și, în condițiile ghidului, forme nonformale/recunoscute organizațional sau internațional, dar legătura cu tehnologiile STEP trebuie demonstrată substanțial.',
 'Furnizorul de formare trebuie să dovedească experiență efectivă relevantă în domeniul STEP propus; simpla calitate formală de partener anterior nu este suficientă.',
 'Cofinanțarea proprie a beneficiarului și partenerilor este 0%, iar durata maximă de implementare este 36 de luni.',
 'Consultarea a condus și la eliminarea unor criterii de evaluare din draft; simularea punctajului trebuie făcută pe grila finală/consolidată.',
 'Clarificările AM sunt utile pentru interpretarea modificărilor rezultate din consultare, dar ghidul final/consolidat și corrigendumurile ulterioare prevalează.'
];
const SUMMARY=[
 'Stare apel: DESCHIS.',
 'Deschidere MySMIS: 29 mai 2026, ora 16:00.',
 'Închidere: 30 septembrie 2026, ora 16:00, după prelungirea prin Corrigendum nr. 1.',
 'Solicitanți: furnizori FPC și servicii pentru ocupare, structuri sindicale/patronale, asociații sectoriale și institute/centre eligibile, în condițiile ghidului.',
 'Parteneriat: solicitantul unic trebuie să fie furnizor FPC autorizat; în parteneriat trebuie să existe cel puțin un furnizor de formare profesională eligibil.',
 'Grup țintă: angajați și/sau șomeri peste 29 de ani; minimum 25 participanți/proiect.',
 'Geografie: toate regiunile de dezvoltare sau minimum două regiuni, conform nevoilor și intervențiilor proiectului.',
 'Activități: A1 opțională și doar pentru șomeri; A2.1 pentru angajați și/sau șomeri; A2.2, formarea la locul de muncă, doar pentru angajați.',
 'Buget apel: 92.000.000 EUR; cofinanțare proprie beneficiar/parteneri: 0%.',
 'Valoare proiect: 7.974 EUR/participant este reper pentru plafonul valorii eligibile maxime, nu cost unitar.',
 'Durată maximă de implementare: 36 luni.',
 'Evaluare: competitivă, pe grila din ghidul final/consolidat.'
];
const section=(title,items)=>({title,items,empty:false});
const upsertSection=(title,items,after)=>{d.sections=Array.isArray(d.sections)?d.sections:[];const i=d.sections.findIndex(s=>s?.title===title);const row=section(title,items);if(i>=0){d.sections[i]=row;return}if(after){const p=d.sections.findIndex(s=>s?.title===after);if(p>=0){d.sections.splice(p+1,0,row);return}}d.sections.push(row)};
const fact=(label,value)=>{d.quickFacts=Array.isArray(d.quickFacts)?d.quickFacts:[];const x=d.quickFacts.find(f=>f?.label===label);if(x)Object.assign(x,{value,confidence:'CONFIRMED'});else d.quickFacts.push({label,value,confidence:'CONFIRMED'})};
Object.assign(d,{status:'OPEN',statusLabel:'DESCHIS',region:'Național; minimum 2 regiuni de dezvoltare',decision:'ACȚIONEAZĂ',decisionLabel:'ACȚIONEAZĂ',decisionAction:'Depunerea este deschisă până la 30 septembrie 2026, ora 16:00. Verifică eligibilitatea solicitantului/parteneriatului, grupul țintă, activitățile STEP și bugetul pe documentația consolidată.',publicationState:'PUBLISHABLE',standfirst:'Apel PEO STEP-LLL pentru competențe în tehnologii critice: 92 milioane EUR, cofinanțare proprie 0%, minimum 25 participanți, minimum două regiuni și termen 30 septembrie 2026, ora 16:00. Dosarul integrează ghidul final, Corrigendum nr. 1 și Q&A-ul AM.'});
fact('Status','DESCHIS');fact('Deschidere','29 mai 2026, 16:00');fact('Termen','30 septembrie 2026, 16:00');fact('Grant','Valoare eligibilă maximă dimensionată cu reperul de 7.974 EUR/participant');fact('Buget','92.000.000 EUR');fact('Contribuție proprie','0%');fact('Durată maximă','36 luni');fact('Arie','Toate regiunile sau minimum 2 regiuni de dezvoltare');
upsertSection('Rezumat executiv',SUMMARY);upsertSection('Decizia rapidă',[d.decisionAction,'Nu folosi termenul vechi din pagina inițială a ghidului: Corrigendum nr. 1 prelungește depunerea până la 30 septembrie 2026, ora 16:00.','Verifică din start furnizorul FPC, arhitectura parteneriatului, minimum două regiuni și delimitarea grupului țintă pe A1/A2.1/A2.2.']);
upsertSection('Cine poate aplica',APPLICANTS);upsertSection('Condiții esențiale de eligibilitate',ELIGIBILITY,'Cine poate aplica');upsertSection('Ce finanțează și în ce condiții',ACTIVITIES);upsertSection('Costuri, cofinanțare și ajutor de stat',COSTS);upsertSection('Documente de pregătit',DOCUMENTS);upsertSection('Cum se punctează',SCORING);upsertSection('Indicatori și obligații',[...INDICATORS,...OBLIGATIONS]);upsertSection('Riscuri de respingere sau implementare',RISKS);upsertSection('Corrigendum nr. 1 — rezumat',CORR,'Riscuri de respingere sau implementare');upsertSection('Q&A AM — clarificări esențiale',QA,'Corrigendum nr. 1 — rezumat');upsertSection('Implementare',['Durata maximă a proiectului este de 36 de luni, cu respectarea limitelor temporale ale programului.','Dimensionează activitățile, grupul țintă și bugetul împreună; reperul de 7.974 EUR/participant nu înlocuiește justificarea costurilor.','Păstrează dovada legăturii dintre fiecare program de formare/competență și domeniul tehnologic STEP vizat.'],'Q&A AM — clarificări esențiale');upsertSection('Ce trebuie făcut acum',['Rulează screeningul de eligibilitate pe solicitant și parteneri; confirmă furnizorul FPC eligibil.','Alege aria proiectului — toate regiunile sau minimum două — și justifică nevoile/intervențiile pentru regiunile selectate.','Separă grupul țintă pe activități: A1 numai șomeri, A2.1 angajați și/sau șomeri, A2.2 numai angajați.','Dimensionează numărul de participanți (minimum 25) și bugetul, respectând reperul de 7.974 EUR/participant fără a-l trata ca pe un cost standard.','Construiește matricea de dovezi STEP: curricula, programe, experiență anterioară și legătura cu domeniile/subdomeniile tehnologice.','Simulează grila finală și planifică depunerea înainte de 30 septembrie 2026, ora 16:00.']);upsertSection('Ce nu este încă confirmat',['Situațiile individuale de autorizare, încadrare a unei organizații, program de formare sau participant se validează pe documentul aplicabil cazului concret.','Q&A-ul explică rezultatul consultării, dar nu înlocuiește ghidul final/consolidat sau corrigendumurile ulterioare.']);
const supported=['status','opening','deadline','beneficiaries','eligibility','activities','eligible_activities','budget','grant','cofinancing','geography','applicable_region','documents','scoring','indicators','obligations','risks','implementation_period'];
d.quality={...(d.quality||{}),completeness:100,depthCompleteness:100,evidenceCount:official.length,failClosed:true,stepLllAuthoritativeBundle:true,verifiedFactClasses:[...new Set([...(d.quality?.verifiedFactClasses||[]),...supported])],blockedFactClasses:(d.quality?.blockedFactClasses||[]).filter(x=>!supported.includes(x))};
d.sources=Array.isArray(d.sources)?d.sources:[];for(const s of official){const old=d.sources.find(x=>x?.url===s.url);if(old)Object.assign(old,s);else d.sources.push({...s})}
d.documentSummaries=[{kind:'CORRIGENDUM',title:'Corrigendum nr. 1',items:CORR,sourceUrl:official[1].url,tier:'T1'},{kind:'QA_AM',title:'Q&A Autoritatea de Management',items:QA,sourceUrl:official[2].url,tier:'T1'}];
d.executiveSummary={status:'OPEN',opens:'2026-05-29T16:00:00+03:00',closes:'2026-09-30T16:00:00+03:00',applicants:APPLICANTS,targetGroup:['Persoane angajate și/sau șomeri cu vârsta de peste 29 de ani.','Minimum 25 participanți/proiect.'],activities:ACTIVITIES,callBudget:'92.000.000 EUR',projectValue:'Valoare eligibilă maximă dimensionată cu reperul de 7.974 EUR × numărul participanților; reperul nu este cost unitar.',cofinancing:'0%',geography:'Toate regiunile de dezvoltare sau minimum 2 regiuni.',implementationPeriod:'Maximum 36 luni.',evaluation:'Competitivă, conform grilei din ghidul final/consolidat.',sourceBound:true};
DP.policy=DP.policy||{};DP.policy.stepLllSourceBoundDossier=true;DATA.decisionProducts=DP;
window.dispatchEvent(new CustomEvent('partener:step-lll-dossier-ready',{detail:{id:d.id,completeness:100}}));
})();
