(()=>{
const D=window.PARTENER_DATA;
const find=id=>D.calls.find(c=>c.id===id);
const mk=x=>Object.assign({applicant:[],applicantKeys:[],objectiveKeys:[],eligibility:['Necesită verificarea ghidului specific'],activities:['Conform ghidului specific'],costs:['Conform ghidului specific'],documents:['Conform ghidului specific'],scoring:['Conform ghidului specific'],indicators:['Conform ghidului specific'],risks:[],sourceFacts:[],changes:[],budget:'Vezi ghid',grant:'Vezi ghid',cofinancing:'Vezi ghid'},x);

const radarMeta=(c,m)=>Object.assign(c,{radarSV:Object.assign({territory:'Sud-Vest Oltenia',audiences:[],role:'VERIFY_GUIDE',roleState:'VERIFY_GUIDE',priority:'MEDIUM',note:''},m)});

let c=find('peo-step-lll');
if(!c){
 c=mk({id:'peo-step-lll',programme:'PEO / STEP',code:'P11 / ESO4.7 / 11.g.1',title:'STEP-LLL — Competențe pentru viitor: formare la locul de muncă și educația adulților în tehnologiile critice',status:'OPEN',category:'Formare',region:'România / inclusiv Sud-Vest Oltenia',applicant:['Clasele exacte de solicitanți se validează din ghidul final'],applicantKeys:['training_provider'],objectiveKeys:['critical_technologies','adult_training','vocational_training'],open:'29 mai 2026, 16:00',close:'30 septembrie 2026, 16:00',summary:'Apel competitiv PEO pentru dezvoltarea competențelor adulților în sectoarele tehnologice STEP. Termenul a fost prelungit oficial până la 30 septembrie 2026.',eligibility:['Statusul și termenul sunt confirmate oficial','Pentru verdictul de eligibilitate al unui furnizor FPC, PARTENER.EU cere verificarea clasei exacte de solicitant din ghidul final'],activities:['Formare la locul de muncă și educația adulților în tehnologii critice','Actualizare de competențe și recalificare pentru sectoarele STEP'],risks:['Nu confunda relevanța pentru FPC cu eligibilitatea confirmată până la extragerea completă a ghidului'],sourceFacts:[{label:'OIR PECU Nord-Vest — Ghid STEP-LLL și fereastra MySMIS 29.05–28.08.2026',url:'https://www.runv.ro/anunturi.html',tier:'T1B'},{label:'OIR PECU Nord-Vest — Corrigendum 27.07.2026: prelungire până la 30.09.2026, 16:00',url:'https://www.runv.ro/anunturi.html',tier:'T1B'}],changes:[{date:'27 iul 2026',kind:'DEADLINE_EXTENDED',before:'28 aug 2026, 16:00',after:'30 sept 2026, 16:00'},{date:'29 mai 2026',kind:'CALL_OPENED',before:'Consultare',after:'OPEN'}]});
 D.calls.push(c);
}
radarMeta(c,{audiences:['FPC'],role:'CANDIDAT SOLICITANT DIRECT',roleState:'VERIFY_GUIDE_ELIGIBILITY_CLASS',priority:'CRITICAL',note:'Cel mai puternic lead pentru furnizori FPC. Status/deadline confirmate; clasa exactă de solicitant trebuie extrasă din ghid înainte de verdictul final.'});

c=find('poids-formare-specialisti-vulnerabili');
if(!c){
 c=mk({id:'poids-formare-specialisti-vulnerabili',programme:'PoIDS',code:'P08 / ESO4.11 / Acțiunea 8.3',title:'Formarea profesională a specialiștilor care lucrează cu grupuri vulnerabile',status:'OPEN',category:'Formare / Social',region:'România / inclusiv Sud-Vest Oltenia',applicant:['Clasele exacte de solicitanți se validează din ghidul final'],applicantKeys:['training_provider','ngo'],objectiveKeys:['vocational_training','social_services','vulnerable_groups'],open:'30 iulie 2026, 16:00',close:'30 septembrie 2026, 16:00',summary:'Apel competitiv PoIDS, Acțiunea 8.3, pentru formarea profesională a specialiștilor care lucrează cu grupuri vulnerabile.',eligibility:['Apelul este OPEN conform comunicării oficiale AM/OIR','Rolul exact al furnizorilor FPC și ONG-urilor trebuie validat din ghid înainte de eligibilitate'],activities:['Formare profesională pentru specialiști care lucrează cu grupuri vulnerabile'],risks:['Titlul apelului indică o potrivire tematică puternică, dar nu substituie lista oficială a solicitanților eligibili'],sourceFacts:[{label:'OIR PECU Nord-Vest — Ghid final și fereastra MySMIS 30.07–30.09.2026',url:'https://www.runv.ro/anunturi.html',tier:'T1B'}],changes:[{date:'30 iul 2026',kind:'CALL_OPENED',before:'Consultare',after:'OPEN până la 30 sept 2026'}]});
 D.calls.push(c);
}
radarMeta(c,{audiences:['FPC','ONG'],role:'SOLICITANT / PARTENER DE VERIFICAT',roleState:'VERIFY_GUIDE',priority:'HIGH',note:'Foarte relevant tematic pentru furnizori FPC și ONG-uri active cu grupuri vulnerabile; lista de solicitanți trebuie extrasă din ghid.'});

c=find('pids-monoparentale');
if(!c){
 c=mk({id:'pids-monoparentale',programme:'PoIDS',code:'P05 / ESO4.3 / Acțiunea 5.5',title:'Măsuri integrate de sprijin pentru familiile monoparentale vulnerabile din România',status:'OPEN',category:'Social / Ocupare / Formare',region:'România / inclusiv Sud-Vest Oltenia',applicant:['Apel necompetitiv — structura solicitant/partener se validează din ghid'],applicantKeys:['public_authority'],objectiveKeys:['social_services','employment','vocational_training','education'],open:'30 iunie 2026, 16:00',close:'28 august 2026, 16:00',summary:'Apel PoIDS necompetitiv pentru măsuri integrate destinate familiilor monoparentale vulnerabile.',eligibility:['Statusul și fereastra MySMIS sunt confirmate oficial','Pentru FPC, școli și ONG-uri trebuie verificată calitatea de partener și condițiile exacte din ghid'],activities:['Măsuri integrate de sprijin pentru familii monoparentale','Intervenții legate de acces la piața muncii și servicii de sprijin'],risks:['Apel necompetitiv: existența apelului nu înseamnă posibilitate de depunere directă pentru orice organizație','Termen apropiat: 28 august 2026'],sourceFacts:[{label:'OIR PECU Nord-Vest — Ghid final PoIDS și fereastra MySMIS 30.06–28.08.2026',url:'https://www.runv.ro/anunturi.html',tier:'T1B'}],changes:[{date:'30 iun 2026',kind:'CALL_OPENED',before:'Consultare',after:'OPEN până la 28 aug 2026'}]});
 D.calls.push(c);
}
radarMeta(c,{audiences:['FPC','ȘCOALĂ','ONG'],role:'PARTENER POTENȚIAL',roleState:'VERIFY_GUIDE_PARTNER_LIST',priority:'HIGH',note:'Apel necompetitiv. Pentru FPC/școli/ONG valoarea este în primul rând de parteneriat; verificăm lista finală de parteneri înainte de acțiune.'});

c=find('peo-step-vet');
if(c){
 c.region='România / inclusiv Sud-Vest Oltenia';
 c.status='EXPECTED';
 c.consultation='13 iulie – 3 august 2026';
 c.sourceFacts=[{label:'OIR PECU Vest — consultare STEP-VET 13.07–03.08.2026',url:'https://oirvest.ro/peo-consultare-publica-ghidul-solicitantului-conditii-specifice-step-vet-formare-profesionala-la-locul-de-munca-pentru-elevii-din-invatamantul-profesional-si-tehnic-in-tehnologii-crit/',tier:'T1B'}];
 c.risks=['Consultarea s-a încheiat; lansarea MySMIS nu este încă confirmată în sursa oficială observată','Rolurile exacte pentru școli/FPC/ONG trebuie extrase din ghidul final'];
 radarMeta(c,{audiences:['ȘCOALĂ','FPC','ONG'],role:'SOLICITANT / PARTENER DE VERIFICAT',roleState:'WAIT_FINAL_LAUNCH_AND_GUIDE',priority:'HIGH',note:'Pregătire acum; nu este OPEN până la evidența oficială de lansare.'});
}

c=find('pids-trafic-persoane');
if(c){
 c.region='România / inclusiv Sud-Vest Oltenia';
 c.status='EXPECTED';
 c.consultation='13 iulie – 3 august 2026';
 c.sourceFacts=[{label:'OIR PECU Vest — consultare PoIDS Servicii integrate pentru victimele traficului de persoane',url:'https://oirvest.ro/poids-lansare-ghiduri-in-consultare-publica-in-data-de-13-07-2026/',tier:'T1B'}];
 c.risks=['Consultarea s-a încheiat; nu există în sursa observată confirmarea deschiderii MySMIS','Pentru ONG trebuie validată lista oficială a solicitanților/partenerilor'];
 radarMeta(c,{audiences:['ONG'],role:'SOLICITANT / PARTENER DE VERIFICAT',roleState:'WAIT_FINAL_LAUNCH_AND_GUIDE',priority:'HIGH',note:'Foarte relevant pentru ONG-uri specializate; se pregătește dosarul de eligibilitate, dar nu se prezintă drept OPEN.'});
}

c=find('poids-formare-profesionisti-copii-familii');
if(!c){
 c=mk({id:'poids-formare-profesionisti-copii-familii',programme:'PoIDS',code:'P05 / ESO4.11 / Acțiunea 5.6',title:'Creșterea accesului profesioniștilor din domeniul serviciilor sociale pentru copii și familii la programe de formare continuă',status:'EXPECTED',category:'Formare / Social',region:'România / inclusiv Sud-Vest Oltenia',applicant:['Apel non-competitiv — rolurile exacte se verifică în ghid'],applicantKeys:[],objectiveKeys:['continuous_training','social_services','children_families'],open:'Neconfirmat',close:'Neconfirmat',consultation:'13 iulie – 3 august 2026',summary:'Ghid PoIDS pentru creșterea accesului profesioniștilor din servicii sociale pentru copii și familii la formare continuă. Consultarea s-a încheiat; lansarea finală nu este confirmată.',eligibility:['Apelul este non-competitiv','Rolul FPC/ONG trebuie verificat din ghidul final'],activities:['Programe de formare continuă pentru profesioniști din servicii sociale pentru copii și familii'],risks:['Nu este OPEN în evidența oficială observată'],sourceFacts:[{label:'OIR PECU Vest — consultare PoIDS 13.07–03.08.2026',url:'https://oirvest.ro/poids-lansare-ghiduri-in-consultare-publica-in-data-de-13-07-2026/',tier:'T1B'}],changes:[{date:'13 iul 2026',kind:'CONSULTATION_OPENED',before:'—',after:'Consultare până la 3 aug 2026'}]});
 D.calls.push(c);
}
radarMeta(c,{audiences:['FPC','ONG'],role:'PARTENER / FURNIZOR DE VERIFICAT',roleState:'WAIT_FINAL_LAUNCH_AND_GUIDE',priority:'MEDIUM',note:'Watchlist foarte relevantă pentru ecosistemul social/formare; momentan nu este apel deschis.'});

D.radarSV={
 title:'Sud-Vest Oltenia · FPC / Școli / ONG',
 description:'Radar PEO + PoIDS pentru organizații de formare profesională, unități de învățământ și ONG-uri. Rolurile de eligibilitate sunt fail-closed: dacă ghidul final nu este încă extras, afișăm VERIFY_GUIDE.',
 callIds:D.calls.filter(x=>x.radarSV).sort((a,b)=>({CRITICAL:0,HIGH:1,MEDIUM:2}[a.radarSV.priority]??9)-({CRITICAL:0,HIGH:1,MEDIUM:2}[b.radarSV.priority]??9)).map(x=>x.id),
 audiences:['TOATE','FPC','ȘCOALĂ','ONG'],
 asOf:'2026-08-11T19:04:00+03:00'
};
D.asOf='2026-08-11T19:04:00+03:00';
})();
