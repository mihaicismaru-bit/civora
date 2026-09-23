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

// Defense-in-depth regression for the critical static boot dataset. The raw
// snapshot must never expose a historical OPEN badge after its own deadline
// has passed. Runtime adapters remain a second guard, not the only guard.
const dataPath=path.resolve(here,'../web/data.js');
const dataSource=fs.readFileSync(dataPath,'utf8');
const staticWindow={};
vm.runInNewContext(dataSource,{window:staticWindow});
const calls=staticWindow.PARTENER_DATA?.calls||[];
const byId=new Map(calls.map(call=>[call.id,call]));
const afir=byId.get('afir-energy-2026');
const pids=byId.get('pids-supported-decision');
const clusters=byId.get('pr-centru-clusters-122');
assert.ok(afir,'AFIR static record must remain queryable for history.');
assert.ok(pids,'PIDS static record must remain queryable for history.');
assert.ok(clusters,'Current cluster record must remain available.');
assert.notEqual(afir.status,'OPEN','Expired AFIR static snapshot must fail closed before runtime adaptation.');
assert.equal(afir.close,'14 august 2026','Historical AFIR deadline must be preserved.');
assert.notEqual(pids.status,'OPEN','Expired PIDS static snapshot must fail closed before runtime adaptation.');
assert.equal(pids.close,'28 august 2026, 16:00','Historical PIDS deadline must be preserved.');
assert.equal(clusters.status,'OPEN','Fail-closed sanitation must not blanket-demote unrelated current OPEN records.');

console.log('PASS home-freshness-guard-v1.2: expired/provisional/undated OPEN suppressed; raw static boot OPEN leak blocked; history preserved; replay deterministic.');
