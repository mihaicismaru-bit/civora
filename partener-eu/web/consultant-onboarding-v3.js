(()=>{
'use strict';
const KEY='partener_consultant_v3_onboarding_dismissed';
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]||c));
const get=()=>{try{return localStorage.getItem(KEY)==='1'}catch{return false}};
const set=v=>{try{v?localStorage.setItem(KEY,'1'):localStorage.removeItem(KEY)}catch{}};
let modal=null;
function isConsultant(){return !!document.querySelector('.cw3Root')}
function close(permanent=false){if(permanent)set(true);modal?.remove();modal=null}
function trigger(selector){const el=document.querySelector(selector);if(el){close(false);el.click()}}
function open(force=false){
 if(!isConsultant())return;
 if(modal)modal.remove();
 modal=document.createElement('div');
 modal.className='cw3OnboardingBackdrop';
 modal.innerHTML=`<section class="cw3Onboarding" role="dialog" aria-modal="true" aria-labelledby="cw3OnboardingTitle">
  <button class="cw3OnboardingClose" aria-label="Închide">×</button>
  <div class="eyebrow">Start rapid · Consultant Workspace</div>
  <h2 id="cw3OnboardingTitle">De la client la decizia GO / NO-GO, în patru pași</h2>
  <p class="cw3OnboardingLead">Modulul consultant nu este o listă separată de apeluri. El folosește același corpus canonic și îl proiectează asupra profilului fiecărui client.</p>
  <div class="cw3OnboardingSteps">
   <article><span>1</span><div><h3>Creează profilul clientului</h3><p>Completează tipul organizației, regiunea, CAEN-ul, dimensiunea, obiectivele și ideea de proiect. Cu cât profilul este mai complet, cu atât screeningul este mai util.</p><button data-onboard="client">Adaugă / completează clientul</button></div></article>
   <article><span>2</span><div><h3>Analizează Opportunity Radar</h3><p>Apelurile sunt ordonate explicabil după solicitant, teritoriu, obiective, status și completitudinea profilului. Scorul este relevanță operațională, nu probabilitate de aprobare.</p><button data-onboard="radar">Deschide oportunitățile</button></div></article>
   <article><span>3</span><div><h3>Deschide dosarul apelului</h3><p>Verifică hard-gates, condițiile necunoscute, sursele, riscurile și răspunde la întrebările consultantului. Rezultatul rămâne REVIEW până când datele critice sunt confirmate.</p><button data-onboard="dossier">Deschide un dosar</button></div></article>
   <article><span>4</span><div><h3>Transformă analiza în lucru</h3><p>Urmărește apelul, compară alternativele, atașează documentele clientului și generează taskuri din cerințe, riscuri și deadline.</p><button data-onboard="tasks">Deschide planul de lucru</button></div></article>
  </div>
  <div class="cw3OnboardingNote"><b>Confidențialitate:</b> profilurile și documentele sunt păstrate în browserul tău. Folosește periodic funcția Backup.</div>
  <div class="cw3OnboardingActions"><button class="cw3OnboardingPrimary" data-onboard="client">Începe cu un client</button><button class="cw3OnboardingSecondary" data-onboard="dismiss">Am înțeles, nu mai afișa automat</button></div>
 </section>`;
 document.body.appendChild(modal);
 modal.querySelector('.cw3OnboardingClose').onclick=()=>close(false);
 modal.onclick=e=>{if(e.target===modal)close(false)};
 modal.querySelectorAll('[data-onboard]').forEach(b=>b.onclick=()=>{
  const action=b.dataset.onboard;
  if(action==='dismiss'){close(true);return}
  if(action==='client')trigger('[data-cw3-new-client], [data-cw3-edit-client]');
  if(action==='radar')trigger('[data-cw3-tab="opportunities"]');
  if(action==='dossier')trigger('[data-cw3-tab="dossier"]');
  if(action==='tasks')trigger('[data-cw3-tab="tasks"]');
 });
}
function inject(){
 const root=document.querySelector('.cw3Root');if(!root)return;
 const actions=root.querySelector('.cw3TopActions');
 if(actions&&!actions.querySelector('[data-cw3-help]')){
  const b=document.createElement('button');b.className='cw3Btn ghost';b.dataset.cw3Help='1';b.textContent='Cum funcționează';b.onclick=()=>open(true);actions.insertBefore(b,actions.querySelector('[data-cw3-export-quick]'));
 }
 if(!get()&&!document.querySelector('.cw3OnboardingBackdrop'))setTimeout(()=>open(false),100);
}
const obs=new MutationObserver(inject);obs.observe(document.getElementById('app'),{childList:true,subtree:true});inject();
})();
