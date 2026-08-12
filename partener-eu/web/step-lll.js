(function(){
  const D=window.PARTENER_DATA;
  if(!D||!Array.isArray(D.calls)) return;
  D.asOf='2026-08-12T08:50:00+03:00';
  const existing=D.calls.find(c=>c.id==='peo-step-lll-adulti');
  const call={
    id:'peo-step-lll-adulti', programme:'PEO / STEP', code:'P11 STEP / Acțiunea 11.g.1',
    title:'STEP-LLL — Competențe pentru viitor: formare la locul de muncă și educația adulților în tehnologiile critice — Adulți',
    status:'OPEN', category:'Formare / tehnologii critice', region:'România',
    applicant:['Furnizori FPC publici și privați autorizați','Furnizori acreditați de servicii specializate pentru ocupare','Confederații sindicale și patronale','Federații sindicale/patronale','Asociații profesionale sectoriale și structuri asociative sectoriale eligibile','Institute/centre de formare și cercetare'],
    applicantKeys:['training_provider','employment_service_provider','trade_union_confederation','employer_confederation','sectoral_association','training_research_institute'],
    objectiveKeys:['critical_technologies','adult_training','workplace_training'],
    open:'29 mai 2026, 16:00', close:'30 septembrie 2026, 16:00', consultation:'2–27 aprilie 2026',
    budget:'92 mil. EUR', grant:'100% din cheltuielile eligibile', cofinancing:'0%',
    summary:'Apel competitiv PEO pentru dezvoltarea competențelor adulților în tehnologiile critice STEP. Ghidul final și lansarea MySMIS sunt confirmate prin OIR PECU Nord-Vest; consultarea a produs modificări importante privind cofinanțarea, aria geografică, grupul țintă și grila de evaluare.',
    eligibility:['Grup țintă: persoane angajate și/sau șomeri cu vârsta peste 29 de ani','Proiectele pot viza toate regiunile sau minimum două regiuni, în funcție de intervenții și nevoi','Legătura directă dintre competențele dezvoltate și tehnologiile critice STEP trebuie demonstrată','În cazul solicitantului unic, acesta trebuie să fie furnizor FPC autorizat; parteneriatele trebuie să includă cel puțin un furnizor de formare profesională'],
    activities:['A1 — informare și consiliere profesională pentru șomeri, activitate relevantă/opțională','A2.1 — formare profesională pentru angajați și șomeri în tehnologii critice STEP','A2.2 — formare profesională la locul de muncă exclusiv pentru angajați','A3 — schimb de bune practici, mentorat profesional, colaborări și transfer de know-how'],
    costs:['Bugetul trebuie fundamentat în raport cu activitățile și rezultatele','7.974 EUR/participant este reper de dimensionare, nu cost standard','Subvenția pentru anumite programe de instruire este reglementată distinct în ghid'],
    documents:['Ghidul Solicitantului Condiții Specifice — forma finală','Anexele finale STEP-LLL','Lista de răspunsuri la consultarea publică — 69 poziții / 52 pagini'],
    scoring:['Criteriul privind depășirea țintei EECO01 a fost eliminat','Criteriul distinct privind centrele de excelență a fost eliminat/reformulat','Experiența furnizorului de formare trebuie demonstrată prin activități și documente concrete, nu prin simpla calitate formală de partener'],
    indicators:['EECO01 — participanți adulți; ținta apelului actualizată la 11.538 persoane','Reper financiar pentru dimensionare: 7.974 EUR/participant'],
    risks:['Corelarea insuficientă cu Anexa 7 — tehnologii critice STEP','Experiență STEP insuficient documentată a furnizorului de formare','Confuzia dintre programe de formare și activități generale de diseminare/workshop','Buget necorelat realist cu grupul țintă și rezultatele'],
    dossierUrl:'step-lll-dossier.html',
    sourceFacts:[
      {label:'OIR PECU Nord-Vest — ghid final și fereastră MySMIS',url:'https://www.runv.ro/anunturi.html',tier:'T1B'},
      {label:'MIPE — pagina oficială STEP-LLL',url:'https://mfe.gov.ro/ghiduri_peos/step-lll-competente-pentru-viitor-formare-la-locul-de-munca-si-educatia-adultilor-in-tehnologiile-critice-adulti/',tier:'T1'},
      {label:'Lista de răspunsuri STEP-LLL — copie accesibilă a documentului MIPE',url:'https://fonduri-structurale-media.s3.eu-central-1.amazonaws.com/PEO_Lista_de_raspunsuri_formare_adulti_6490fe2e68.pdf',tier:'T2-mirror-of-official-document'}
    ],
    changes:[
      {date:'2 apr 2026',kind:'CONSULTATION_OPENED',before:'—',after:'Ghid lansat în consultare'},
      {date:'27 apr 2026',kind:'CONSULTATION_CLOSED',before:'Consultare deschisă',after:'Perioada de observații închisă'},
      {date:'29 mai 2026',kind:'CALL_OPENED',before:'Consultare',after:'Ghid final publicat; MySMIS deschis la 16:00'},
      {date:'29 mai 2026',kind:'GUIDE_UPDATED_AFTER_CONSULTATION',before:'Draft',after:'Cofinanțare 0%; reguli geografice și de grup țintă clarificate; grilă revizuită'},
      {date:'27 iul 2026',kind:'DEADLINE_EXTENDED',before:'28 aug 2026, 16:00',after:'30 sept 2026, 16:00'}
    ]
  };
  if(existing) Object.assign(existing,call); else D.calls.unshift(call);
})();
