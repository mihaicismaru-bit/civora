(()=>{
'use strict';
const exact=new Map([
 ['What Changed','Actualizări'],['Ask PARTENER.EU','Întreabă PARTENER.EU'],['Consultant mode','Consultant'],['Public site','Site public'],['Apeluri deschise în pilot','Apeluri deschise'],['watch / consultare','în monitorizare'],['facts demo cu provenance','date cu surse verificate'],['Funding Explorer','Oportunități de finanțare'],['Version & Change Intelligence','Actualizări și modificări'],['Funding Calendar','Calendar finanțări'],['Calendar canonic','Calendar apeluri'],['Consultant Workspace','Consultant'],['Opportunity radar','Oportunități recomandate'],['Actions & deadlines','Acțiuni și termene'],['Sources','Surse'],['Track','Urmărește'],['Tracked ✓','Urmărit ✓']
]);
const replacements=[
 [/PARTENER\.EU · CIVORA Pilot 01 · Faptele critice au proveniență; estimările nu sunt prezentate ca termene oficiale\./g,'PARTENER.EU · Informații despre finanțări europene din surse oficiale și verificabile.'],
 [/Fail-closed: consultarea nu devine OPEN fără evidență oficială\./g,'Un apel este marcat deschis numai după confirmarea dintr-o sursă oficială.'],
 [/Funding intelligence pentru beneficiari și consultanți, cu sursa fiecărui fapt important\./g,'Informații clare despre finanțări pentru companii, instituții publice, ONG-uri și consultanți — cu sursa fiecărei informații esențiale.']
];
function cleanNode(node){if(node.nodeType!==Node.TEXT_NODE)return;let s=node.nodeValue||'';const t=s.trim();if(exact.has(t))s=s.replace(t,exact.get(t));for(const [rx,to] of replacements)s=s.replace(rx,to);if(s!==node.nodeValue)node.nodeValue=s;}
function polish(){
 document.querySelectorAll('.footer').forEach(el=>{const v='PARTENER.EU · Informații despre finanțări europene din surse oficiale și verificabile.';if(el.textContent!==v)el.textContent=v;});
 const hero=document.querySelector('.hero');if(hero){const eyebrow=hero.querySelector('.eyebrow');if(eyebrow&&eyebrow.textContent!=='Finanțări europene · România')eyebrow.textContent='Finanțări europene · România';const p=hero.querySelector('p');const pv='Descoperă oportunități de finanțare, verifică eligibilitatea și urmărește termenele importante într-un singur loc.';if(p&&p.textContent!==pv)p.textContent=pv;const label=hero.querySelector('.heroCard .label');if(label&&label.textContent!=='Apeluri deschise')label.textContent='Apeluri deschise';const notice=hero.querySelector('.notice');const nv='Statusurile și termenele sunt afișate pe baza surselor oficiale disponibile.';if(notice&&notice.textContent!==nv)notice.textContent=nv;}
 const walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);const nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);nodes.forEach(cleanNode);
}
// Deliberately no global MutationObserver: dynamic modules own their rendering.
// A bounded second pass catches synchronous modules loaded immediately after this script without creating a feedback loop.
polish();
setTimeout(polish,250);
window.PARTENER_PUBLIC_COPY={version:'1.0.2',polish};
})();
