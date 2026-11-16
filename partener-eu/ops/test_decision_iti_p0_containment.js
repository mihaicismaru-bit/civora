#!/usr/bin/env node
'use strict';
// Runtime replay for issue #1403. Do not change canonical dossiers/news.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const src=fs.readFileSync(path.resolve(__dirname,'../web/decision-intelligence-v2.js'),'utf8');
const title='Sprijin pentru familii monoparentale — ITI Microregiunea Țara Făgărașului';
const dossier=(id,label)=>({
  id,title:label,programme:'PoIDS',publicationState:'PUBLISHABLE',
  region:'România',status:'CLOSED',decision:'DO_NOT_APPLY',
  decisionAction:'Nu mai investi resurse de depunere',
  standfirst:'Text de consultare',sourceType:'MIPE',sourceLinks:[],
  quickFacts:[{label:'Termen',value:'31 august 2026',confidence:'CONFIRMED'}],
  audience:['Școli din ITI Moții'],sections:[],sources:[],quality:{completeness:86}
});
const held=dossier('mipe-1b5d21384b66b4b559',title);
const alias=dossier('mipe-reissued-iti',title);
const motii=dossier('mipe-distinct-motii','Sprijin pentru familii monoparentale — ITI Moții, Țara de Piatră');
const unrelated=dossier('other-call','Finanțare energie verde');
const news=(id,dossierId,headline)=>({
  id,dossierId,headline,programme:'PoIDS',kind:'CALL_CLOSED',
  standfirst:'Test',meaning:'Verifică actele',actions:['Verifică'],utilityScore:90,
  date:'2026-11-16T00:00:00Z'
});
const P={
  generatedAt:'2026-11-16T00:00:00Z',
  summary:{dossierCount:4,openCount:0,prepareCount:0,highCompletenessCount:4,newsCount:3},
  dossiers:[held,alias,motii,unrelated],
  news:[news('held-news',held.id,'Termen Făgărașului contaminat'),news('alias-news',alias.id,'Alias contaminat'),news('safe-news',unrelated.id,'Știre independentă')],
  home:{openDossierIds:[held.id],prepareDossierIds:[alias.id,motii.id],changeNewsIds:['held-news','safe-news']}
};
const untouched=JSON.stringify(P);
const main={innerHTML:'',querySelectorAll(){return []},querySelector(){return null}};
const document={
  querySelector(selector){return selector==='.main'?main:null},
  getElementById(){return {}},
  createElement(){return {dataset:{},classList:{add(){}},querySelectorAll(){return []}}}
};
class MutationObserver{observe(){}}
const window={PARTENER_DECISION_PRODUCTS:P,PARTENER_DATA:{}};
vm.runInNewContext(src,{window,document,MutationObserver,console},{filename:'decision-intelligence-v2.js'});
const ui=window.PARTENER_DECISION_UI;
assert(ui,'decision UI failed to start');
assert.equal(ui.openDossier(held.id),false,'held exact-ID dossier must not open');
assert.equal(ui.openDossier(alias.id),false,'renamed-ID same-territory dossier must not open');
assert.equal(ui.openNews('held-news'),false,'held dossier news must not open');
assert.equal(ui.openNews('alias-news'),false,'held alias news must not open');
assert.equal(ui.openDossier(motii.id),true,'unrelated ITI territory must remain accessible');
assert.equal(ui.openDossier(unrelated.id),true,'unrelated dossier must remain accessible');
assert.equal(ui.openNews('safe-news'),true,'independent news must remain accessible');
ui.openHub('dossiers');
assert(!main.innerHTML.includes(title),'disputed title leaked into search');
assert(!main.innerHTML.includes('mipe-1b5d21384b66b4b559'),'disputed ID leaked into search');
assert(main.innerHTML.includes('ITI Moții, Țara de Piatră'),'distinct ITI territory lost');
assert(main.innerHTML.includes('Finanțare energie verde'),'unrelated dossier lost');
ui.openHub('news');
assert(!main.innerHTML.includes('Termen Făgărașului contaminat'),'held news leaked into news hub');
assert(!main.innerHTML.includes('Alias contaminat'),'held alias news leaked into news hub');
assert(main.innerHTML.includes('Știre independentă'),'independent news lost');
assert.equal(JSON.stringify(P),untouched,'canonical data was mutated');
console.log('PASS P0 #1403 dynamic search/dossier/news hold and immutable corpus replay');
