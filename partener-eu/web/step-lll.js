(function(){
  const D=window.PARTENER_DATA;
  if(!D||!Array.isArray(D.calls)) return;
  D.asOf='2026-08-12T08:35:00+03:00';
  if(D.calls.some(c=>c.id==='peo-step-lll-adulti')) return;
  D.calls.unshift({
    id:'peo-step-lll-adulti',
    programme:'PEO / STEP',
    code:'P11 STEP — STEP-LLL',
    title:'STEP-LLL — Competențe pentru viitor: formare la locul de muncă și educația adulților în tehnologiile critice — Adulți',
    status:'PUBLIC_CONSULTATION',
    category:'Formare / tehnologii critice',
    region:'România',
    applicant:['De confirmat din ghidul final / documentele autoritative complete'],
    applicantKeys:[],
    objectiveKeys:['critical_technologies','adult_training','workplace_training'],
    open:'Neconfirmat — apelul nu este tratat ca lansat',
    close:'Neconfirmat',
    consultation:'2 aprilie – 27 aprilie 2026 (închisă)',
    budget:'Neconfirmat autoritativ în corpusul curent',
    grant:'Neconfirmat autoritativ în corpusul curent',
    cofinancing:'Neconfirmat autoritativ în corpusul curent',
    summary:'Ghidul Solicitantului Condiții Specifice STEP-LLL a fost lansat în consultare publică la 2 aprilie 2026 în Programul Educație și Ocupare, Prioritatea P11 STEP — Tehnologii strategice pentru Europa. Termenul oficial pentru observații a fost 27 aprilie 2026. PARTENER.EU nu promovează apelul la OPEN până la identificarea unei evidențe autoritative de lansare și a ghidului final.',
    eligibility:[
      'Eligibilitatea solicitantului nu este promovată ca fapt material până la verificarea ghidului final / anexelor autoritative.',
      'Obiectul confirmat este formarea la locul de muncă și educația adulților în tehnologii critice.',
      'Încadrarea exactă a solicitanților, partenerilor și grupului țintă rămâne de rezolvat din documentația oficială completă.'
    ],
    activities:[
      'Formare la locul de muncă în tehnologii critice — confirmat la nivelul titlului oficial al ghidului.',
      'Educația adulților în tehnologii critice — confirmat la nivelul titlului oficial al ghidului.',
      'Activitățile și limitele detaliate rămân nepromovate până la parsarea documentației autoritative.'
    ],
    costs:['Categorii de cost: neconfirmate autoritativ în corpusul curent.'],
    documents:[
      'Ghidul Solicitantului Condiții Specifice — versiunea lansată în consultare publică la 02.04.2026.',
      'Anexele ghidului — referite de sursa oficială OIR către MIPE; ingestia directă MIPE este încă blocată de transport.',
      'Ghid final / ordin de aprobare / eventuale corrigenda — de identificat și verificat înainte de actualizarea faptelor materiale.'
    ],
    scoring:['Praguri, criterii și grilă de evaluare: neconfirmate autoritativ în corpusul curent.'],
    indicators:['Indicatorii specifici: neconfirmați autoritativ în corpusul curent.'],
    risks:[
      'Consultarea publică nu înseamnă apel lansat.',
      'Nu trebuie transferate automat în versiunea finală condițiile dintr-un draft de ghid.',
      'Orice buget, deadline, eligibilitate sau scoring trebuie reconciliate cu ghidul final / MySMIS / MIPE înainte de publicare ca fapt.'
    ],
    dossierUrl:'step-lll-dossier.html',
    sourceFacts:[
      {label:'OIR PECU Regiunea Vest — anunț oficial STEP-LLL, 02.04.2026',url:'https://oirvest.ro/ghidul-solicitantului-conditii-specifice-step-lll-competente-pentru-viitor-formare-la-locul-de-munca-si-educatia-adultilor-in-tehnologiile-critice-adulti-lansa/',tier:'T1B'},
      {label:'MIPE — pagina ghidului STEP-LLL (referită de OIR; fetch direct pending)',url:'https://mfe.gov.ro/ghiduri_peos/step-lll-competente-pentru-viitor-formare-la-locul-de-munca-si-educatia-adultilor-in-tehnologiile-critice-adulti/',tier:'T1-pending-direct-verification'}
    ],
    changes:[
      {date:'2 apr 2026',kind:'CONSULTATION_OPENED',before:'—',after:'Ghid STEP-LLL lansat în consultare publică'},
      {date:'27 apr 2026',kind:'CONSULTATION_CLOSED',before:'Consultare deschisă',after:'Termenul pentru observații a expirat; lansarea apelului rămâne neconfirmată'}
    ]
  });
})();
