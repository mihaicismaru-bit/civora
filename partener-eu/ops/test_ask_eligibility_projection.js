#!/usr/bin/env node
'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const scriptPath=process.argv[2]||path.resolve(__dirname,'../web/ask-partener-v2.js');
const source=fs.readFileSync(scriptPath,'utf8');

function render(audience,options={}){
  const input={value:options.query||'energie',autocomplete:'',addEventListener(){}};
  const output={innerHTML:'',querySelector(){return null},querySelectorAll(){return []}};
  const button={textContent:'',onclick:null};
  const eyebrow={textContent:''};
  const heading={textContent:''};
  const search={insertAdjacentHTML(){}};
  const ask={
    dataset:{},
    querySelector(sel){
      if(sel==='.eyebrow')return eyebrow;
      if(sel==='h1')return heading;
      if(sel==='#aq')return input;
      if(sel==='#ago')return button;
      if(sel==='.searchBox')return search;
      if(sel==='.askV2Hint')return null;
      return null;
    }
  };
  const dossier={
    id:options.id||'TEST-ENERGY',
    publicationState:'PUBLISHABLE',
    title:options.title||'Finanțare pentru energie regenerabilă',
    programme:'Program test',
    region:'România',
    status:Object.prototype.hasOwnProperty.call(options,'status')?options.status:'OPEN',
    audience,
    standfirst:'Investiții în energie',
    decisionAction:options.decisionAction||'Verifică dosarul înainte de depunere.',
    quickFacts:options.quickFacts||[],
    sections:[],
    sources:[],
    sourceLinks:[],
    quality:{completeness:100}
  };
  // The public Ask index must preserve competitors, not just a favorable Termen.
  for(const field of ['deadline','closesAt','closeAt','openFrom','opensAt','openAt']){
    if(Object.prototype.hasOwnProperty.call(options,field))dossier[field]=options[field];
  }
  const window={
    PARTENER_ASK_INDEX:options.compactIndex?{dossiers:[dossier],calls:options.canonicalCalls||[]}:undefined,
    PARTENER_DECISION_PRODUCTS:{dossiers:[dossier]},
    PARTENER_MIPE_CANONICAL_CALLS:{calls:options.canonicalCalls||[]},
    PARTENER_DECISION_UI:{openHub(){return true},openDossier(){return true}},
    addEventListener(){}
  };
  const document={
    querySelector(sel){
      if(sel==='.main .ask')return ask;
      if(sel==='#aq')return input;
      if(sel==='#ans')return output;
      return null;
    },
    getElementById(){return null}
  };
  class MutationObserver{observe(){}}
  class FixedDate extends Date{static now(){return Date.parse(options.now||'2026-11-17T20:30:00Z')}}
  const sandbox={window,document,MutationObserver,URL,console,Map,Set,Number,String,Array,Object,RegExp,Math,Date:FixedDate,
    setTimeout(fn){fn();return 1},clearTimeout(){}};
  vm.runInNewContext(source,sandbox,{filename:scriptPath});
  assert.equal(typeof button.onclick,'function','Ask enhancement did not bind the search action');
  button.onclick({preventDefault(){}});
  return output.innerHTML;
}

const weak=render(['Conform ghidului solicitantului']);
assert(weak.includes('<b>Eligibilitate</b>'),'weak audience must render the unknown eligibility block');
assert(weak.includes('Eligibilitatea solicitantului nu este încă confirmată'),'weak audience must stay explicitly unconfirmed');
assert(!weak.includes('<b>Cine poate aplica</b>'),'weak audience must not be promoted as known eligibility');
assert(!weak.includes('Conform ghidului solicitantului'),'weak audience placeholder must not be echoed as a beneficiary claim');

const structured=render(['IMM eligibile']);
assert(structured.includes('<b>Cine poate aplica</b>'),'structured audience must remain visible');
assert(structured.includes('IMM eligibile'),'structured audience content must be preserved');
assert(!structured.includes('Eligibilitatea solicitantului nu este încă confirmată'),'structured audience must not be mislabeled unknown');

const evidenceNow=[
  {label:'Status',value:'OPEN',confidence:'CONFIRMED'},
  {label:'Termen',value:'2026-11-20T16:00:00+02:00',confidence:'CONFIRMED'}
];
const canonicalStatus=render(['IMM eligibile'],{
  status:'OPEN',quickFacts:evidenceNow,
  canonicalCalls:[{id:'TEST-ENERGY',status:'OPEN',verificationEvidence:[]}]
});
assert(canonicalStatus.includes('askV2Status OPEN">DESCHIS'),'a current, exact and internally consistent canonical OPEN can be shown');
const canonicalConflict=render(['IMM eligibile'],{
  status:'CLOSED',quickFacts:evidenceNow,
  canonicalCalls:[{id:'TEST-ENERGY',status:'OPEN',verificationEvidence:[]}]
});
assert(canonicalConflict.includes('askV2Status REVIEW">ÎN VERIFICARE'),'contradicting canonical and dossier states cannot silently promote OPEN');
assert(!canonicalConflict.includes('askV2Status OPEN">DESCHIS'),'canonical conflict must fail closed, even with a future cutoff');

const unknownStatus=render(['IMM eligibile'],{status:''});
assert(unknownStatus.includes('askV2Status UNKNOWN">NECONFIRMAT'),'missing status must be projected explicitly as unconfirmed');
assert(unknownStatus.includes('Statutul apelului nu este încă confirmat.'),'missing status must remain in the unknown-facts block');
assert(!unknownStatus.includes('askV2Status REVIEW">ÎN VERIFICARE'),'missing status must not be fabricated as review');

const factStatus=render(['IMM eligibile'],{
  status:'',
  quickFacts:[{label:'Status',value:'Deschis pentru depunere',confidence:'VERIFIED'}]
});
assert(factStatus.includes('askV2Status REVIEW">ÎN VERIFICARE'),'unstructured Deschis text cannot authorize an OPEN status without an exact call window');
assert(!factStatus.includes('askV2Status VERIFIED_FACT">Deschis pentru depunere'),'unstructured present-tense OPEN claim must not be echoed as verified');


// P0 #1404 — Ask must not resurrect a 6 November expired OPEN call from
// old generatedAt / a compact index / a canonical OPEN status. Source remains
// unchanged; the rendered answer must say REVIEW and block submission advice.
const expiredFacts=[
  {label:'Status',value:'OPEN',confidence:'CONFIRMED'},
  {label:'Termen',value:'2026-11-06T12:00:00+02:00',confidence:'CONFIRMED'}
];
const staleCluster=render(['IMM eligibile'],{
  id:'pr-centru-clusters-122-clustere-inovative',title:'Clustere inovative — energie',
  status:'OPEN',quickFacts:expiredFacts,compactIndex:true,
  canonicalCalls:[{id:'pr-centru-clusters-122-clustere-inovative',status:'OPEN',verificationEvidence:[]}],
  decisionAction:'ACȚIONEAZĂ. Planifică depunerea acum.'
});
assert(staleCluster.includes('askV2Status REVIEW">ÎN VERIFICARE'),'Ask cannot announce expired 6 Nov call OPEN');
assert(!staleCluster.includes('askV2Status OPEN">DESCHIS'),'stale OPEN badge leaked into Ask');
assert(!staleCluster.includes('ACȚIONEAZĂ'),'stale submission action leaked into Ask');
assert(staleCluster.includes('Starea curentă a apelului necesită reverificare'),'expired Ask result must give safe action');
assert(staleCluster.includes('Ultimul termen raportat (de reverificat)'),'historical deadline must be labeled unverified');
const atCutoff=render(['IMM eligibile'],{
  quickFacts:expiredFacts,status:'OPEN',now:'2026-11-06T10:00:00Z'
});
assert(atCutoff.includes('askV2Status REVIEW">ÎN VERIFICARE'),'exact deadline instant must expire');
const beforeCutoff=render(['IMM eligibile'],{
  quickFacts:expiredFacts,status:'OPEN',now:'2026-11-06T09:59:59Z'
});
assert(beforeCutoff.includes('askV2Status OPEN">DESCHIS'),'a valid pre-cutoff call must remain discoverable');
const roTimed=render(['IMM eligibile'],{
  quickFacts:[expiredFacts[0],{...expiredFacts[1],value:'6 noiembrie 2026, ora 12:00'}],
  status:'OPEN',now:'2026-11-06T09:59:59Z'
});
assert(roTimed.includes('askV2Status OPEN">DESCHIS'),'Romanian official local hour must parse as 10:00 UTC');
const conflictingClock=render(['IMM eligibile'],{
  quickFacts:evidenceNow,status:'OPEN',closesAt:'2026-11-25T16:00:00+02:00',compactIndex:true
});
assert(conflictingClock.includes('askV2Status REVIEW">ÎN VERIFICARE'),'compact Ask must retain and reject competing closing times');
const unknownOpening=render(['IMM eligibile'],{
  quickFacts:[...evidenceNow,{label:'Deschidere',value:'20 noiembrie 2026, ora 09:00',confidence:'CONFIRMED'}],
  status:'OPEN'
});
assert(unknownOpening.includes('askV2Status REVIEW">ÎN VERIFICARE'),'future official opening must not count as current');
const dateOnly=render(['IMM eligibile'],{
  quickFacts:[evidenceNow[0],{...evidenceNow[1],value:'20 noiembrie 2026'}],
  status:'OPEN'
});
assert(dateOnly.includes('askV2Status REVIEW">ÎN VERIFICARE'),'date-only deadline cannot authorize OPEN');
const missingEvidence=render(['IMM eligibile'],{
  status:'OPEN',canonicalCalls:[{id:'TEST-ENERGY',status:'OPEN',verificationEvidence:[]}]
});
assert(missingEvidence.includes('askV2Status REVIEW">ÎN VERIFICARE'),'canonical status without exact observed window cannot authorize OPEN');
const closedControl=render(['IMM eligibile'],{status:'CLOSED'});
assert(closedControl.includes('askV2Status CLOSED">ÎNCHIS'),'unrelated historical CLOSED control must remain intact');

// P0 #1403 — a disputed Făgărașului record must never be recommended
// by Ask from a stale dynamic projection, even if marked PUBLISHABLE.
// The distinct Moții call and unaffected dossiers stay discoverable.
const itiTitle='Sprijin pentru familii monoparentale — ITI Microregiunea Țara Făgărașului';
const itiQuery='sprijin familii monoparentale';
const heldIti=render(['Școli din ITI Moții'],{
  id:'mipe-1b5d21384b66b4b559',
  title:itiTitle,query:itiQuery,status:'CLOSED',
  decisionAction:'Nu mai investi resurse de depunere',
  quickFacts:[{label:'Termen',value:'31 august 2026',confidence:'CONFIRMED'}]
});
assert(heldIti.includes('Nu am găsit încă o potrivire suficient de sigură'),'held ITI must not produce Ask results');
for(const leaked of [itiTitle,'Școli din ITI Moții','Nu mai investi resurse','31 august 2026']){
  assert(!heldIti.includes(leaked),'disputed ITI evidence leaked into Ask: '+leaked);
}
const heldAlias=render(['Școli din ITI Moții'],{
  id:'mipe-reingested-20261116',title:itiTitle,query:itiQuery,status:'CLOSED'
});
assert(heldAlias.includes('Nu am găsit încă o potrivire suficient de sigură'),'reingested ITI identity must remain held by territorial title');
const distinctMotii=render(['Organizații eligibile'],{
  id:'mipe-distinct-iti-motii',
  title:'Sprijin pentru familii monoparentale — ITI Moții, Țara de Piatră',
  query:itiQuery,status:'CLOSED'
});
assert(distinctMotii.includes('ITI Moții, Țara de Piatră'),'distinct ITI territory must remain visible');
assert(!distinctMotii.includes('Nu am găsit încă o potrivire suficient de sigură'),'other territory must not be swept into P0 hold');

console.log(JSON.stringify({status:'PASS',cases:8,contract:'Ask eligibility, status and P0 territorial containment are fail-closed'}));