// Hermetic replay of the *active* lightweight homepage gate. No DOM, network,
// source mutation or public publication is involved.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const source=fs.readFileSync(path.resolve(here,'../web/home-concierge-vnext.js'),'utf8');
assert.ok(source.endsWith('})();\n'),'active homepage must retain its expected IIFE closure');
assert.ok(source.includes('const canonicalOpenTotal=open.length;'),
 'homepage OPEN metric must follow the live gate rather than a stale projected total');
let fixedNow=Date.parse('2026-11-07T19:00:00Z');
class FixedDate extends Date{static now(){return fixedNow}}
const window={
 PARTENER_HOME_DATA:{dossiers:[],news:[]},
 addEventListener(){}
};
const document={body:{classList:{toggle(){}}},querySelector(){return null},getElementById(){return null}};
const sandbox={window,document,Date:FixedDate};
const testedSource=source.replace(/\}\)\(\);\s*$/,
 'globalThis.__gates={isUpcoming,isConsultation,isOpen};\n})();');
vm.runInNewContext(testedSource,sandbox,{filename:'home-concierge-vnext.js'});
const {isUpcoming,isConsultation,isOpen}=sandbox.__gates;
assert.equal(typeof isUpcoming,'function');
const record=(status,facts={},publicationState='PUBLISHABLE')=>({
 status,publicationState,title:'Oportunitate verificată',
 quickFacts:Object.entries(facts).map(([label,value])=>({label,value,confidence:'CONFIRMED'}))
});
assert.equal(isUpcoming(record('EXPECTED',{'Termen':'16 octombrie 2026, 12:00'})),false,
 'past deadline cannot remain URMEAZĂ just because its calendar year is current');
assert.equal(isUpcoming(record('EXPECTED',{'Termen':'20 noiembrie 2026, 12:00'})),true,
 'future dated expected call stays visible as PREPARE, never as OPEN');
assert.equal(isUpcoming(record('EXPECTED',{})),false,
 'undated plan cannot enter homepage as a current opportunity');
assert.equal(isUpcoming(record('EXPECTED',{'Calendar':'2028'})),false,
 'programme year is not a dated application window');
assert.equal(isUpcoming(record('EXPECTED',{
 'Termen':'30 octombrie 2026','Deschidere':'20 noiembrie 2026'
})),false,'contradictory old cutoff must fail closed despite a future opening clue');
assert.equal(isUpcoming(record('EXPECTED',{'Termen':'20 noiembrie 2026'},'PROVISIONAL_FAIL_CLOSED')),false,
 'review-only dossier must not enter public preparation surfaces');
assert.equal(isUpcoming(record('OPEN',{'Termen':'20 noiembrie 2026'})),false,
 'OPEN cannot be relabeled as upcoming');
assert.equal(isConsultation(record('PUBLIC_CONSULTATION',{'Termen consultare':'4 septembrie 2026'})),false,
 'expired consultation cannot be presented as current');
assert.equal(isConsultation(record('PUBLIC_CONSULTATION',{'Termen consultare':'18 noiembrie 2026'})),true,
 'future consultation end can remain in the distinct consultation surface');
assert.equal(isConsultation(record('PUBLIC_CONSULTATION',{})),false,
 'undated consultation remains queryable but does not assert currentness');
assert.equal(isConsultation(record('EXPECTED',{'Termen consultare':'18 noiembrie 2026'})),false,
 'planned call cannot silently become public consultation');
assert.equal(isOpen(record('EXPECTED',{'Termen':'20 noiembrie 2026'})),false,
 'future-programming evidence must never promote to OPEN');

// Romania has EET (UTC+2) in November and EEST (UTC+3) in October.
// Browser locale and its timezone must not change the call lifecycle.
// Exact official clock cutoffs: 16:00 Romania = 14:00Z winter / 13:00Z summer.
const timedOpen=(deadline)=>record('OPEN',{'Status':'OPEN','Termen':deadline});
fixedNow=Date.parse('2026-11-16T13:59:59Z');
assert.equal(isOpen(timedOpen('16 noiembrie 2026, 16:00')),true,
 'EET: official Romanian call remains open one second before real cutoff');
fixedNow=Date.parse('2026-11-16T14:00:01Z');
assert.equal(isOpen(timedOpen('16 noiembrie 2026, 16:00')),false,
 'EET: call cannot remain OPEN after Bucharest 16:00, even abroad');
fixedNow=Date.parse('2026-10-08T12:59:59Z');
assert.equal(isOpen(timedOpen('8 octombrie 2026, 16:00')),true,
 'EEST: correct summer UTC offset for Romanian official deadline');
fixedNow=Date.parse('2026-10-08T13:00:01Z');
assert.equal(isOpen(timedOpen('8 octombrie 2026, 16:00')),false,
 'EEST: expired official deadline cannot leak after 13:00Z');
assert.equal(isOpen(timedOpen('2026-10-08T16:00:00+03:00')),false,
 'offset-qualified ISO dates must remain exact, never reinterpret in browser TZ');
fixedNow=Date.parse('2026-03-01T12:00:00Z');
assert.equal(isUpcoming(record('EXPECTED',{'Termen':'29 martie 2026, 03:30'})),false,
 'nonexistent DST spring local hour cannot authorize future preparation, even before that date');
fixedNow=Date.parse('2026-10-25T00:29:59Z');
assert.equal(isOpen(timedOpen('25 octombrie 2026, 03:30')),true,
 'autumn DST: ambiguous Romanian cutoff uses earliest possible 03:30');
fixedNow=Date.parse('2026-10-25T00:30:01Z');
assert.equal(isOpen(timedOpen('25 octombrie 2026, 03:30')),false,
 'autumn DST: second 03:30 cannot extend an already elapsed cutoff');
fixedNow=Date.parse('2026-11-16T13:59:59Z');
assert.equal(isOpen(timedOpen('16 noiembrie 2026')),false,
 'date-only source cannot invent a deadline hour and authorize OPEN');
assert.equal(isOpen(record('OPEN',{'Status':'CLOSED','Termen':'16 noiembrie 2026, 16:00'})),false,
 'contradictory confirmed status fact never authorizes OPEN');
fixedNow=Date.parse('2026-11-07T19:00:00Z');


// Independent compact-home gate must remain fail-closed even if the
// separate decision-hub freshnessGuard is not loaded yet.
fixedNow=Date.parse('2026-11-10T10:00:00Z');
assert.equal(isOpen(timedOpen('2026-11-11T00:00:00')),false,
 'timezone-free ISO timestamp must never authorize OPEN');
assert.equal(isOpen(timedOpen('2026-11-11T00:00:00+02:00')),true,
 'equivalent offset-qualified exact timestamp remains valid before cutoff');
assert.equal(isOpen(timedOpen('2026-11-31T12:00:00+02:00')),false,
 'browser-normalized impossible ISO calendar date must never authorize OPEN');
assert.equal(isOpen(timedOpen('2026-11-11T25:00:00+02:00')),false,
 'invalid official hour must fail closed');
assert.equal(isOpen({...timedOpen('2026-11-11T00:00:00+02:00'),
  closesAt:'2026-11-06T12:00:00+02:00'}),false,
 'competing expired top-level cutoff must hold even with future confirmed fact');
assert.equal(isOpen({...timedOpen('2026-11-11T00:00:00+02:00'),
  deadline:'Neconfirmat'}),false,
 'unparseable competing cutoff must not be silently ignored');
assert.equal(isOpen({...timedOpen('2026-11-11T00:00:00+02:00'),
  closesAt:'2026-11-11T00:00:00+02:00'}),true,
 'matching independent exact cutoffs retain valid OPEN state');
fixedNow=Date.parse('2026-11-10T22:00:00Z');
assert.equal(isOpen(timedOpen('2026-11-11T00:00:00+02:00')),false,
 'at the precise official deadline, OPEN must already be held');
fixedNow=Date.parse('2026-11-07T19:00:00Z');

// The lazily loaded decision-hub freshness guard must not mistake an old
// successful ingestion timestamp for "now". This regression exercises its
// complete projection against November 10 while its LKG is from November 3.
const guardSource=fs.readFileSync(path.resolve(here,'../web/home-freshness-guard-v1.js'),'utf8');
let guardNow=Date.parse('2026-11-10T00:25:00Z');
class GuardDate extends Date{
 constructor(...args){super(...(args.length?args:[guardNow]))}
 static now(){return guardNow}
}
const guardRecord=(id,deadline,statusValue='OPEN')=>({
 id,title:'Sursă oficială '+id,status:'OPEN',publicationState:'PUBLISHABLE',
 quickFacts:[
  {label:'Status',value:statusValue,confidence:'CONFIRMED'},
  {label:'Termen',value:deadline,confidence:'CONFIRMED'}
 ]
});
function checkGuard(rows){
 const P={
  generatedAt:'2026-11-03T20:33:50Z',
  dossiers:rows,
  home:{openDossierIds:rows.map(d=>d.id),prepareDossierIds:[]},
  summary:{openCount:rows.length,prepareCount:0}
 };
 const guardWindow={
  PARTENER_DECISION_PRODUCTS:P,
  PARTENER_DATA:{mipeIngestion:{asOf:'2026-11-03T20:33:50Z'},
                mysmisRegistry:{observedAt:'2026-11-02T10:00:00Z'}}
 };
 vm.runInNewContext(guardSource,{window:guardWindow,Date:GuardDate},
   {filename:'home-freshness-guard-v1.js'});
 return P;
}
const expired='2026-11-06T12:00:00+02:00';
const future='2026-11-16T16:00:00+02:00';
let guard=checkGuard([
 guardRecord('expired',expired),
 guardRecord('live',future),
 guardRecord('contradictory',future,'CLOSED')
]);
assert.equal(Array.from(guard.home.openDossierIds).join(','),'live',
 'real-time gate must remove expired OPEN and contradictory official status');
assert.equal(Array.from(guard.freshnessGuard.removedOpenDossierIds).join(','),
 'expired,contradictory','removed OPEN IDs must remain auditable');
assert.equal(guard.summary.openCount,1,'homepage openCount cannot use historical LKG time');
assert.equal(guard.freshnessGuard.dossierStatusOverrides.expired,'REVIEW',
 'deadline expiry alone must not invent an official CLOSED status');
assert.equal(guard.freshnessGuard.dossierStatusOverrides.contradictory,'REVIEW');
assert.equal(guard.freshnessGuard.asOf,new Date(guardNow).toISOString(),
 'freshness audit clock must reflect wall clock, not source-generatedAt');
guardNow=Date.parse('2026-11-16T14:00:01Z');
guard=checkGuard([guardRecord('formerly-live',future)]);
assert.equal(guard.summary.openCount,0,
 'at exact end, an unchanged old LKG must fail closed without new ingestion');
assert.equal(guard.freshnessGuard.dossierStatusOverrides['formerly-live'],'REVIEW');

console.log('PASS active homepage: future-dated PREPARE/CONSULTATION only; expired/unknown/contradictory fail closed; OPEN metric is live; no promotion.');
