#!/usr/bin/env node
'use strict';
const assert=require('assert');
const fs=require('fs');
const path=require('path');
const vm=require('vm');
const scriptPath=process.argv[2]||path.resolve(__dirname,'../web/ask-partener-v2.js');
const source=fs.readFileSync(scriptPath,'utf8');

function render(audience,options={}){
  const input={value:'energie',autocomplete:'',addEventListener(){}};
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
    id:'TEST-ENERGY',
    title:'Finanțare pentru energie regenerabilă',
    programme:'Program test',
    region:'România',
    status:Object.prototype.hasOwnProperty.call(options,'status')?options.status:'OPEN',
    audience,
    standfirst:'Investiții în energie',
    decisionAction:'Verifică dosarul înainte de depunere.',
    quickFacts:options.quickFacts||[],
    sections:[],
    sources:[],
    sourceLinks:[],
    quality:{completeness:100}
  };
  const window={
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
  const sandbox={window,document,MutationObserver,URL,console,Map,Set,Number,String,Array,Object,RegExp,Math,Date,
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

const canonicalStatus=render(['IMM eligibile'],{
  status:'CLOSED',
  canonicalCalls:[{id:'TEST-ENERGY',status:'OPEN',verificationEvidence:[]}]
});
assert(canonicalStatus.includes('askV2Status OPEN">DESCHIS'),'deterministic canonical status must take precedence over a conflicting dossier status');
assert(!canonicalStatus.includes('askV2Status CLOSED">ÎNCHIS'),'stale dossier status must not override the deterministic canonical status');

const unknownStatus=render(['IMM eligibile'],{status:''});
assert(unknownStatus.includes('askV2Status UNKNOWN">NECONFIRMAT'),'missing status must be projected explicitly as unconfirmed');
assert(unknownStatus.includes('Statutul apelului nu este încă confirmat.'),'missing status must remain in the unknown-facts block');
assert(!unknownStatus.includes('askV2Status REVIEW">ÎN VERIFICARE'),'missing status must not be fabricated as review');

const factStatus=render(['IMM eligibile'],{
  status:'',
  quickFacts:[{label:'Status',value:'Deschis pentru depunere',confidence:'VERIFIED'}]
});
assert(factStatus.includes('askV2Status VERIFIED_FACT">Deschis pentru depunere'),'a verified status fact may be displayed when no structured status exists');
assert(!factStatus.includes('Statutul apelului nu este încă confirmat.'),'verified status fact must not be mislabeled unknown');

console.log(JSON.stringify({status:'PASS',cases:5,contract:'Ask eligibility and status projection are fail-closed'}));