#!/usr/bin/env node
'use strict';
const fs=require('fs');
const path=require('path');
const vm=require('vm');

const ROOT=path.resolve(__dirname,'..');
const source=fs.readFileSync(path.join(ROOT,'web','ask-partener-v2.js'),'utf8');

const callA={id:'MIPE-A',code:'A',title:'Energie A',programme:'Program A',region:'Romania',activities:['energie'],materialFacts:{eligibility:{conditions:['IMM'],partners:[],geographic_scope:['Romania']}},verificationEvidence:[{sourceTier:'T1',sourceUrl:'https://official.example/a'}]};
const callB={id:'MIPE-B',code:'B',title:'Energie B',programme:'Program B',region:'Romania',activities:['energie'],materialFacts:{eligibility:{conditions:['IMM'],partners:[],geographic_scope:['Romania']}},verificationEvidence:[{sourceTier:'T1',sourceUrl:'https://official.example/b'}]};
const common={audience:['IMM'],status:'OPEN',region:'Romania',quality:{completeness:100},decisionAction:'Verifică dosarul.',quickFacts:[],sections:[]};
const conflict={...common,id:'MIPE-A',sourceType:'MIPE_CALL',sourceLinks:[{source:'MIPE'}],code:'B',title:'CONFLICT energie',programme:'Program conflict',sources:[{tier:'T1',url:'https://official.example/b',label:'Sursă conflict'}]};
const consistent={...common,id:'MIPE-B',sourceType:'MIPE_CALL',sourceLinks:[{source:'MIPE'}],code:'B',title:'CONSISTENT energie',programme:'Program B',sources:[{tier:'T1',url:'https://official.example/b',label:'Sursă B'}]};
const independent={...common,id:'AFIR-1',sourceType:'AFIR_CALL',sourceLinks:[{source:'AFIR'}],code:'AFIR-X',title:'INDEPENDENT energie',programme:'AFIR',sources:[{tier:'T1',url:'https://afir.example/x',label:'Sursă AFIR'}]};

const input={value:'energie',placeholder:'',autocomplete:'',addEventListener(){}};
const output={innerHTML:'',querySelector(){return null},querySelectorAll(){return []}};
const button={textContent:'',onclick:null};
const search={insertAdjacentHTML(){}};
const ask={dataset:{},querySelector(sel){return ({'.eyebrow':{textContent:''},'h1':{textContent:''},'#aq':input,'#ago':button,'.searchBox':search,'.askV2Hint':null})[sel]??null}};

global.window={
  PARTENER_DECISION_PRODUCTS:{dossiers:[conflict,consistent,independent]},
  PARTENER_MIPE_CANONICAL_CALLS:{calls:[callA,callB]},
  addEventListener(){}
};
global.document={
  querySelector(sel){if(sel==='.main .ask')return ask;if(sel==='#aq')return input;if(sel==='#ans')return output;return null},
  getElementById(){return null}
};
global.MutationObserver=class{observe(){}};
global.clearTimeout=()=>{};
global.setTimeout=fn=>{fn();return 1};

vm.runInThisContext(source,{filename:'ask-partener-v2.js'});
if(typeof button.onclick!=='function')throw new Error('Ask enhance did not bind submit action');
button.onclick({preventDefault(){}});

if(output.innerHTML.includes('CONFLICT energie'))throw new Error('MIPE dossier with conflicting canonical identity leaked into Ask results');
if(!output.innerHTML.includes('CONSISTENT energie'))throw new Error('Uniquely resolved MIPE dossier was incorrectly excluded');
if(!output.innerHTML.includes('INDEPENDENT energie'))throw new Error('Non-MIPE verified dossier was incorrectly forced through MIPE canonical registry');
if(!source.includes('canonicalConflict:true')||!source.includes('!x.canonicalConflict'))throw new Error('Explicit canonical fail-closed contract is missing');
console.log(JSON.stringify({status:'PASS',conflictingMipeExcluded:true,resolvedMipeIncluded:true,nonMipePreserved:true}));
