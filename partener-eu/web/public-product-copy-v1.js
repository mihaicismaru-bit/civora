(()=>{
'use strict';
const exact=new Map([
 ['What Changed','Actualizări'],
 ['Ask PARTENER.EU','Întreabă PARTENER.EU'],
 ['Consultant mode','Consultant'],
 ['Public site','Site public'],
 ['Apeluri deschise în pilot','Apeluri deschise'],
 ['watch / consultare','în monitorizare'],
 ['facts demo cu provenance','date cu surse verificate'],
 ['Funding Explorer','Oportunități de finanțare'],
 ['Version & Change Intelligence','Actualizări și modificări'],
 ['Funding Calendar','Calendar finanțări'],
 ['Calendar canonic','Calendar apeluri'],
 ['Consultant Workspace','Consultant'],
 ['Opportunity radar','Oportunități recomandate'],
 ['Actions & deadlines','Acțiuni și termene'],
 ['Sources','Surse'],
 ['Track','Urmărește'],
 ['Tracked ✓','Urmărit ✓']
]);
const replacements=[
 [/PARTENER\.EU · CIVORA Pilot 01 · Faptele critice au proveniență; estimările nu sunt prezentate ca termene oficiale\./g,'PARTENER.EU · Informații despre finanțări europene din surse oficiale și verificabile.'],
 [/Fail-closed: consultarea nu devine OPEN fără evidență oficială\./g,'Un apel este marcat deschis numai după confirmarea dintr-o sursă oficială.'],
 [/Funding intelligence pentru beneficiari și consultanți, cu sursa fiecărui fapt important\./g,'Informații clare despre finanțări pentru companii, instituții publice, ONG-uri și consultanți — cu sursa fiecărei informații esențiale.'],
 [/Prioritizate după utilitate decizională\./g,'Selectate pentru relevanță, termen și utilitate practică.'],
 [/Un rezultat = un obiect canonic, nu un articol separat\./g,'Fiecare oportunitate reunește într-un singur loc condițiile, termenele, documentele și sursele relevante.'],
 [/Date oficiale separate de consultări și estimări\./g,'Termenele oficiale sunt diferențiate clar de perioadele de consultare și de lansările estimate.'],
 [/Răspuns grounded în corpusul canonic demo\./g,'Răspuns bazat pe informațiile și sursele disponibile în PARTENER.EU.'],
 [/Date private client · canonical calls read-only/g,'Profil beneficiar și oportunități relevante'],
 [/Matcher explicabil; scorul nu este probabilitate de aprobare\./g,'Verificare orientativă pe baza criteriilor cunoscute ale apelului.'],
 [/Scorul este relevanță operațională, nu probabilitate de aprobare\./g,'Scorul indică relevanța oportunității pentru profilul beneficiarului.'],
 [/Ranking explicabil după tip organizație, obiective, teritoriu și status\./g,'Oportunități ordonate după profilul organizației, obiective, teritoriu și stadiul apelului.'],
 [/Datele de lucru sunt salvate local în browser\. Corpusul apelurilor rămâne read-only\./g,'Datele de lucru ale beneficiarului sunt păstrate separat de informațiile oficiale despre apeluri.'],
 [/Lista structurată a solicitanților nu este completă în corpus; necesită verificarea ghidului\./g,'Lista solicitanților trebuie confirmată în ghidul oficial al apelului.'],
 [/Apel OPEN în corpusul curent\./g,'Apel deschis conform informațiilor oficiale disponibile.'],
 [/Apel în pregătire \/ consultare; util pentru pregătire, nu pentru depunere acum\./g,'Apel în pregătire sau consultare; poate fi urmărit pentru pregătirea din timp a proiectului.'],
 [/Nu investi timp de depunere; păstrează doar ca referință\./g,'Apel închis; poate fi păstrat ca referință pentru lansări viitoare.']
];
function cleanNode(node){
 if(node.nodeType!==Node.TEXT_NODE)return;
 let s=node.nodeValue||'';
 const trimmed=s.trim();
 if(exact.has(trimmed))s=s.replace(trimmed,exact.get(trimmed));
 for(const [rx,to] of replacements)s=s.replace(rx,to);
 if(s!==node.nodeValue)node.nodeValue=s;
}
function polish(){
 document.querySelectorAll('.footer').forEach(el=>el.textContent='PARTENER.EU · Informații despre finanțări europene din surse oficiale și verificabile.');
 const hero=document.querySelector('.hero');
 if(hero){
   const eyebrow=hero.querySelector('.eyebrow'); if(eyebrow)eyebrow.textContent='Finanțări europene · România';
   const p=hero.querySelector('p'); if(p)p.textContent='Descoperă oportunități de finanțare, verifică eligibilitatea și urmărește termenele importante într-un singur loc.';
   const label=hero.querySelector('.heroCard .label'); if(label)label.textContent='Apeluri deschise';
   const notice=hero.querySelector('.notice'); if(notice)notice.textContent='Statusurile și termenele sunt afișate pe baza surselor oficiale disponibile.';
 }
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
 const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);nodes.forEach(cleanNode);
 document.querySelectorAll('.navlink').forEach(b=>{if(b.textContent.trim()==='What Changed')b.textContent='Actualizări';if(b.textContent.trim()==='Ask PARTENER.EU')b.textContent='Întreabă PARTENER.EU';});
 document.querySelectorAll('.modebtn').forEach(b=>{if(b.textContent.trim()==='Consultant mode')b.textContent='Consultant';if(b.textContent.trim()==='Public site')b.textContent='Site public';});
}
let scheduled=false;
const schedule=()=>{if(scheduled)return;scheduled=true;queueMicrotask(()=>{scheduled=false;polish();});};
new MutationObserver(schedule).observe(document.documentElement,{childList:true,subtree:true,characterData:true});
polish();
window.PARTENER_PUBLIC_COPY={version:'1.0.0',polish};
})();
