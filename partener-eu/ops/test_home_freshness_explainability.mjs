import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync('partener-eu/web/home-freshness-explainability-v1.js','utf8');
const context={window:{},URL,Intl,Date,setTimeout,clearTimeout,console};
vm.createContext(context);
vm.runInContext(source,context,{filename:'home-freshness-explainability-v1.js'});
const api=context.window.PARTENER_HOME_FRESHNESS_EXPLAINABILITY;
assert.ok(api,'freshness explainability API missing');
assert.equal(api.version,'home-freshness-explainability-v1');

const products={
  generatedAt:'2026-09-07T10:00:00Z',
  freshnessGuard:{asOf:'2026-09-07T10:05:00Z',state:'PASS'},
  summary:{openCount:4,prepareCount:9},
};
const data={mff2028:{asOf:'2026-09-01T00:00:00Z',items:[{},{},{}]}};
const model=api.buildModel(products,data,Date.parse('2026-09-07T10:30:00Z'));
assert.equal(model.lanes.length,3);
assert.equal(model.lanes[0].id,'open');
assert.equal(model.lanes[0].count,4);
assert.equal(model.lanes[0].state,'OPEN_CONFIRMED_ONLY');
assert.equal(model.lanes[1].id,'prepare');
assert.match(model.lanes[1].missing,/Identificator exact/);
assert.equal(model.lanes[2].id,'pipeline');
assert.equal(model.lanes[2].state,'PROGRAMMING_NON_AUTHORIZING');
assert.match(model.lanes[2].missing,/nu devine apel/i);
assert.equal(model.homeFresh.state,'FRESH');

const openDossier={status:'OPEN',quickFacts:[{label:'Status',confidence:'CONFIRMED'},{label:'Termen',confidence:'CONFIRMED'}]};
assert.equal(api.dossierConfidence(openDossier).state,'HIGH');
assert.match(api.dossierMissing(openDossier),/Eligibilitatea/);
const planned={status:'PUBLIC_CONSULTATION',quickFacts:[]};
assert.equal(api.dossierConfidence(planned).state,'PIPELINE');
assert.match(api.dossierMissing(planned),/endpoint oficial curent/);
assert.equal(api.freshnessState(null).state,'UNKNOWN');
assert.equal(api.freshnessState('2026-08-01T00:00:00Z',Date.parse('2026-09-07T10:30:00Z')).state,'STALE');

for(const forbidden of ['open_call_authorized=true','publish_authorized=true','PROGRAMMING_OPEN_CALL']){
  assert.ok(!source.includes(forbidden),`unsafe public authorization marker: ${forbidden}`);
}
console.log(JSON.stringify({status:'PASS',lanes:model.lanes.map(x=>x.id),openCount:model.lanes[0].count,pipelineState:model.lanes[2].state,materialAuthorization:false}));
