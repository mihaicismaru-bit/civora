import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';

const source=fs.readFileSync('partener-eu/web/search-ask-explainability-v1.js','utf8');
const homeApi={
  freshnessState(value,now){
    if(!value)return {state:'UNKNOWN',label:'Dată neconfirmată'};
    const hours=(now-Date.parse(value))/36e5;
    if(hours<=24)return {state:'FRESH',label:'Observație recentă'};
    if(hours<=168)return {state:'CURRENT',label:'Verificat în ultimele 7 zile'};
    return {state:'STALE',label:'Necesită revalidare'};
  },
  dossierConfidence(d){
    if(d.status==='OPEN')return {state:'HIGH',label:'Ridicată · status și termen confirmate'};
    return {state:'PIPELINE',label:'În pregătire · non-OPEN'};
  },
  dossierMissing(d){return d.status==='OPEN'?'Eligibilitatea aplicantului trebuie verificată în dosarul concret.':'Identificator exact + endpoint oficial curent + status OPEN explicit + reconciliere semantică';},
};
const context={window:{PARTENER_HOME_FRESHNESS_EXPLAINABILITY:homeApi},URL,Intl,Date,setTimeout,clearTimeout,console};
vm.createContext(context);
vm.runInContext(source,context,{filename:'search-ask-explainability-v1.js'});
const api=context.window.PARTENER_SEARCH_ASK_EXPLAINABILITY;
assert.ok(api,'search/Ask explainability API missing');
assert.equal(api.version,'search-ask-explainability-v1');

const now=Date.parse('2026-09-07T14:00:00Z');
const openCall={
  id:'open-1',status:'OPEN',p11VerifiedFactClasses:['status','deadline'],
  sourceFacts:[{label:'Autoritate oficială',url:'https://example.eu/call/1',tier:'T1'}],
};
const openModel=api.callModel(openCall,{asOf:'2026-09-07T13:30:00Z'},now);
assert.equal(openModel.lane,'OPEN_CONFIRMED_ONLY');
assert.equal(openModel.confidence.state,'HIGH');
assert.equal(openModel.freshness.state,'FRESH');
assert.match(openModel.missing,/Eligibilitatea concretă/);
assert.equal(openModel.materialAuthorization,false);

const expected={id:'expected-1',status:'EXPECTED',sourceFacts:[{url:'https://example.eu/notice',tier:'T1'}]};
const expectedModel=api.callModel(expected,{asOf:'2026-09-07T13:30:00Z'},now);
assert.equal(expectedModel.lane,'UPCOMING_OR_REVIEW');
assert.equal(expectedModel.confidence.state,'PIPELINE');
assert.match(expectedModel.missing,/endpoint oficial curent/);

const programming={id:'pipeline-1',status:'PROGRAMMING',sourceFacts:[]};
const programmingModel=api.callModel(programming,{asOf:'2026-09-01T00:00:00Z'},now);
assert.equal(programmingModel.lane,'PROGRAMMING_NON_AUTHORIZING');
assert.notEqual(programmingModel.confidence.state,'HIGH');
assert.equal(programmingModel.materialAuthorization,false);

const dossier={
  id:'dossier-1',status:'OPEN',
  sources:[{label:'Sursă oficială',url:'https://authority.example/dossier',tier:'T1',fetched_at:'2026-09-07T13:00:00Z'}],
};
const dossierModel=api.dossierModel(dossier,{generatedAt:'2026-09-07T12:00:00Z'},now);
assert.equal(dossierModel.confidence.state,'HIGH');
assert.equal(dossierModel.freshness.state,'FRESH');
assert.equal(dossierModel.source.label,'Sursă oficială');
assert.match(dossierModel.missing,/Eligibilitatea/);
assert.equal(dossierModel.materialAuthorization,false);

for(const forbidden of ['open_call_authorized=true','publish_authorized=true','distribution_authorized=true','PROGRAMMING_OPEN_CALL']){
  assert.ok(!source.includes(forbidden),`unsafe authorization marker: ${forbidden}`);
}
console.log(JSON.stringify({status:'PASS',openLane:openModel.lane,expectedLane:expectedModel.lane,pipelineLane:programmingModel.lane,materialAuthorization:false}));
