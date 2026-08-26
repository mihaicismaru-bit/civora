import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const guardPath=path.resolve(here,'../web/home-freshness-guard-v1.js');
const guardSource=fs.readFileSync(guardPath,'utf8');

function run(payload,data={}){
  const window={PARTENER_DECISION_PRODUCTS:structuredClone(payload),PARTENER_DATA:structuredClone(data)};
  vm.runInNewContext(guardSource,{window,Date});
  return window.PARTENER_DECISION_PRODUCTS;
}

const payload={
  generatedAt:'2026-08-22T17:45:00Z',
  dossiers:[
    {id:'open-valid',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel deschis',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'2026-09-05',confidence:'CONFIRMED'}]},
    {id:'open-expired-ro',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel expirat',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'14 august 2026',confidence:'CONFIRMED'}]},
    {id:'open-no-deadline',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel fără termen',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'Neconfirmat',confidence:'UNKNOWN'}]},
    {id:'open-provisional',status:'OPEN',publicationState:'PROVISIONAL_FAIL_CLOSED',title:'Apel provizoriu',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'2026-10-01',confidence:'CONFIRMED'}]},
    {id:'stale-2023',status:'PUBLIC_CONSULTATION',title:'Calendarul fondurilor europene 2023',quickFacts:[{label:'Termen',value:'2023-03-01'}]},
    {id:'current-2026',status:'PUBLIC_CONSULTATION',title:'Ghid în consultare',quickFacts:[{label:'Termen',value:'2026-09-05'}]},
    {id:'future-2027',status:'EXPECTED',title:'Apel estimat 2027',quickFacts:[]},
    {id:'ambiguous-review',status:'REVIEW',title:'Apel fără calendar confirmat',quickFacts:[{label:'Termen',value:'Neconfirmat'}]},
    {id:'closed-history',status:'CLOSED',title:'Referință istorică 2023',quickFacts:[{label:'Termen',value:'2023-05-01'}]}
  ],
  home:{openDossierIds:['open-valid','open-expired-ro','open-no-deadline','open-provisional'],prepareDossierIds:['stale-2023','current-2026','future-2027','ambiguous-review']},
  summary:{openCount:99,prepareCount:99}
};

const sourceData={mipeIngestion:{asOf:'2026-08-26T03:42:03Z'}};
const out=run(payload,sourceData);
assert.deepEqual(Array.from(out.home.openDossierIds),['open-valid']);
assert.equal(out.summary.openCount,1);
assert.deepEqual(Array.from(out.freshnessGuard.removedOpenDossierIds),['open-expired-ro','open-no-deadline','open-provisional']);
assert.deepEqual({...out.freshnessGuard.dossierStatusOverrides},{'open-expired-ro':'CLOSED','open-no-deadline':'REVIEW','open-provisional':'REVIEW'});
assert.deepEqual(Array.from(out.home.prepareDossierIds),['current-2026','future-2027']);
assert.equal(out.summary.prepareCount,2);
assert.equal(out.freshnessGuard.state,'DEGRADED');
assert.deepEqual(Array.from(out.freshnessGuard.removedPrepareDossierIds),['stale-2023','ambiguous-review']);
assert.equal(out.dossiers.length,9,'Historical dossiers remain queryable; the guard only changes currentness surfaces.');

const replay=run(payload,sourceData);
assert.deepEqual(JSON.parse(JSON.stringify(replay)),JSON.parse(JSON.stringify(out)),'Same artifact timestamp must replay deterministically.');

console.log('PASS home-freshness-guard-v1.1: expired/provisional/undated OPEN suppressed, stale PREPARE suppressed, history preserved, replay deterministic.');
