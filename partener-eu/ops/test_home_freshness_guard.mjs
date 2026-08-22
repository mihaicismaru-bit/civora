import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const guardPath=path.resolve(here,'../web/home-freshness-guard-v1.js');
const guardSource=fs.readFileSync(guardPath,'utf8');

function run(payload){
  const window={PARTENER_DECISION_PRODUCTS:structuredClone(payload)};
  vm.runInNewContext(guardSource,{window,Date});
  return window.PARTENER_DECISION_PRODUCTS;
}

const payload={
  generatedAt:'2026-08-22T17:45:00Z',
  dossiers:[
    {id:'stale-2023',status:'PUBLIC_CONSULTATION',title:'Calendarul fondurilor europene 2023',quickFacts:[{label:'Termen',value:'2023-03-01'}]},
    {id:'current-2026',status:'PUBLIC_CONSULTATION',title:'Ghid în consultare',quickFacts:[{label:'Termen',value:'2026-09-05'}]},
    {id:'future-2027',status:'EXPECTED',title:'Apel estimat 2027',quickFacts:[]},
    {id:'ambiguous-review',status:'REVIEW',title:'Apel fără calendar confirmat',quickFacts:[{label:'Termen',value:'Neconfirmat'}]},
    {id:'closed-history',status:'CLOSED',title:'Referință istorică 2023',quickFacts:[{label:'Termen',value:'2023-05-01'}]}
  ],
  home:{prepareDossierIds:['stale-2023','current-2026','future-2027','ambiguous-review']},
  summary:{prepareCount:99}
};

const out=run(payload);
assert.deepEqual(Array.from(out.home.prepareDossierIds),['current-2026','future-2027']);
assert.equal(out.summary.prepareCount,2);
assert.equal(out.freshnessGuard.state,'DEGRADED');
assert.deepEqual(Array.from(out.freshnessGuard.removedPrepareDossierIds),['stale-2023','ambiguous-review']);
assert.equal(out.dossiers.length,5,'Historical dossiers remain queryable; the guard only changes currentness surfaces.');

const replay=run(payload);
assert.deepEqual(JSON.parse(JSON.stringify(replay)),JSON.parse(JSON.stringify(out)),'Same artifact timestamp must replay deterministically.');

console.log('PASS home-freshness-guard-v1: stale 2023 suppressed, 2026/2027 retained, ambiguous REVIEW fail-closed, history preserved, replay deterministic.');
