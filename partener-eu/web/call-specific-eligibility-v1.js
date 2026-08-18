(()=>{
'use strict';
const D=window.PARTENER_DATA;
if(!D||!Array.isArray(D.calls))return;
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function currentCall(){
  const head=document.querySelector('.detailHeader');
  if(!head)return null;
  const title=head.querySelector('h1')?.textContent?.trim()||'';
  const sub=head.querySelector('.sub')?.textContent?.trim()||'';
  return D.calls.find(c=>String(c.title||'').trim()===title)
    ||D.calls.find(c=>c.code&&sub.includes(String(c.code)))
    ||null;
}
function applicantOptions(c){
  const labels=Array.isArray(c?.applicant)?c.applicant:[];
  const keys=Array.isArray(c?.applicantKeys)?c.applicantKeys:[];
  if(!labels.length||labels.length!==keys.length)return [];
  return keys.map((key,i)=>({key:String(key),label:String(labels[i])})).filter(x=>x.key&&x.label);
}
function sync(){
  const box=document.querySelector('.eligibilityBox');
  const select=document.getElementById('org');
  if(!box||!select)return;
  const c=currentCall();
  if(!c)return;
  const options=applicantOptions(c);
  const signature=`${c.id||c.title}|${options.map(x=>x.key).join('|')}`;
  if(select.dataset.callEligibility===signature)return;
  select.dataset.callEligibility=signature;
  const title=box.querySelector('h3');
  const desc=box.querySelector('.sectionDesc');
  const button=box.querySelector('#match');
  if(title)title.textContent='Pot aplica în acest apel?';
  let note=box.querySelector('[data-call-eligibility-note]');
  if(!note){
    note=document.createElement('div');
    note.dataset.callEligibilityNote='1';
    note.className='meta';
    note.style.marginTop='8px';
    select.insertAdjacentElement('afterend',note);
  }
  if(options.length){
    select.disabled=false;
    if(button)button.disabled=false;
    select.innerHTML='<option value="">Alege categoria de solicitant din ghid</option>'+options.map(x=>`<option value="${esc(x.key)}">${esc(x.label)}</option>`).join('');
    if(desc)desc.textContent='Lista de mai jos este specifică ghidului apelului deschis. Selectează categoria juridică în care te încadrezi.';
    note.textContent=`${options.length} categorii de solicitanți eligibili sunt definite pentru acest apel. Verificarea finală depinde și de condițiile specifice din ghid.`;
  }else{
    select.innerHTML='<option value="">Categoriile de solicitanți sunt în verificare documentară</option>';
    select.disabled=true;
    if(button)button.disabled=true;
    if(desc)desc.textContent='Nu afișăm categorii generice din alte apeluri. Eligibilitatea solicitantului pentru acest apel este încă în verificare documentară.';
    note.textContent='Revenim cu selectorul imediat ce categoriile din ghid sunt confirmate în dosarul canonic.';
  }
}
let timer=null;
function schedule(){clearTimeout(timer);timer=setTimeout(sync,35)}
const app=document.getElementById('app')||document.body;
new MutationObserver(schedule).observe(app,{childList:true,subtree:true});
window.addEventListener('load',schedule,{once:true});
document.addEventListener('click',schedule,true);
setTimeout(sync,120);
})();
