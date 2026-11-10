import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const here=path.dirname(fileURLToPath(import.meta.url));
const guardPath=path.resolve(here,'../web/home-freshness-guard-v1.js');
const guardSource=fs.readFileSync(guardPath,'utf8');

// Hermetic clock: the source must be replayable at both its original snapshot
// date and a later date without mistaking generatedAt for current time.
let fakeNow=Date.parse('2026-08-26T04:00:00Z');
class TestDate extends Date{
  constructor(...args){super(...(args.length?args:[fakeNow]))}
  static now(){return fakeNow}
}
function run(payload,data={}){
  const window={PARTENER_DECISION_PRODUCTS:structuredClone(payload),PARTENER_DATA:structuredClone(data)};
  vm.runInNewContext(guardSource,{window,Date:TestDate});
  return window.PARTENER_DECISION_PRODUCTS;
}

const payload={
  generatedAt:'2026-08-22T17:45:00Z',
  dossiers:[
    {id:'open-valid',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel deschis',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'2026-09-05T16:00:00+03:00',confidence:'CONFIRMED'}]},
    {id:'open-date-only',status:'OPEN',publicationState:'PUBLISHABLE',title:'Fără oră oficială',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'2026-09-05',confidence:'CONFIRMED'}]},
    {id:'open-expired-ro',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel expirat',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'14 august 2026',confidence:'CONFIRMED'}]},
    {id:'open-no-deadline',status:'OPEN',publicationState:'PUBLISHABLE',title:'Apel fără termen',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'Neconfirmat',confidence:'UNKNOWN'}]},
    {id:'open-provisional',status:'OPEN',publicationState:'PROVISIONAL_FAIL_CLOSED',title:'Apel provizoriu',quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},{label:'Termen',value:'2026-10-01',confidence:'CONFIRMED'}]},
    {id:'stale-2023',status:'PUBLIC_CONSULTATION',title:'Calendarul fondurilor europene 2023',quickFacts:[{label:'Termen',value:'2023-03-01'}]},
    {id:'current-2026',status:'PUBLIC_CONSULTATION',title:'Ghid în consultare',quickFacts:[{label:'Termen',value:'2026-09-05'}]},
    {id:'future-2027',status:'EXPECTED',title:'Apel estimat 2027',quickFacts:[]},
    {id:'ambiguous-review',status:'REVIEW',title:'Apel fără calendar confirmat',quickFacts:[{label:'Termen',value:'Neconfirmat'}]},
    {id:'closed-history',status:'CLOSED',title:'Referință istorică 2023',quickFacts:[{label:'Termen',value:'2023-05-01'}]}
  ],
  home:{openDossierIds:['open-valid','open-date-only','open-expired-ro','open-no-deadline','open-provisional'],prepareDossierIds:['stale-2023','current-2026','future-2027','ambiguous-review']},
  summary:{openCount:99,prepareCount:99}
};

const sourceData={mipeIngestion:{asOf:'2026-08-26T03:42:03Z'}};
const out=run(payload,sourceData);
assert.deepEqual(Array.from(out.home.openDossierIds),['open-valid']);
assert.equal(out.summary.openCount,1);
assert.deepEqual(Array.from(out.freshnessGuard.removedOpenDossierIds),['open-date-only','open-expired-ro','open-no-deadline','open-provisional']);
assert.deepEqual({...out.freshnessGuard.dossierStatusOverrides},{'open-date-only':'REVIEW','open-expired-ro':'REVIEW','open-no-deadline':'REVIEW','open-provisional':'REVIEW'});
assert.deepEqual(Array.from(out.home.prepareDossierIds),['current-2026','future-2027']);
assert.equal(out.summary.prepareCount,2);
assert.equal(out.freshnessGuard.state,'DEGRADED');
assert.deepEqual(Array.from(out.freshnessGuard.removedPrepareDossierIds),['stale-2023','ambiguous-review']);
assert.equal(out.dossiers.length,10,'Historical dossiers remain queryable; the guard only changes currentness surfaces.');

const replay=run(payload,sourceData);
assert.deepEqual(JSON.parse(JSON.stringify(replay)),JSON.parse(JSON.stringify(out)),'Same artifact timestamp must replay deterministically.');

// A stale LKG from August cannot preserve its originally valid September
// opening in November. No official CLOSED assertion is inferred from expiry.
fakeNow=Date.parse('2026-11-10T00:25:00Z');
const atPresent=run(payload,sourceData);
assert.deepEqual(Array.from(atPresent.home.openDossierIds),[]);
assert.equal(atPresent.summary.openCount,0);
assert.equal(atPresent.freshnessGuard.asOf,'2026-11-10T00:25:00.000Z');
assert.equal(atPresent.freshnessGuard.dossierStatusOverrides['open-valid'],'REVIEW');
fakeNow=Date.parse('2026-08-26T04:00:00Z');

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
assert.equal(clusters.status,'REVIEW','Expired 6 Nov cluster cannot remain OPEN even when the detail page lags the ADR index.');
assert.equal(clusters.close,'6 noiembrie 2026, 12:00','Keep the historical official deadline instead of asserting a new closure date.');

// A Romanian-language exact time must expire at the official local hour,
// not at 23:59 UTC. November is EET (UTC+2), July is EEST (UTC+3).
const timedOpen=(id,deadline,extra={})=>({
  id,status:'OPEN',publicationState:'PUBLISHABLE',title:id,
  quickFacts:[{label:'Status',value:'OPEN',confidence:'CONFIRMED'},
              {label:'Termen',value:deadline,confidence:'CONFIRMED'}],
  ...extra
});
const timedPayload=(dossiers)=>({generatedAt:'2026-10-01T00:00:00Z',dossiers,
  home:{openDossierIds:dossiers.map(d=>d.id),prepareDossierIds:[]},summary:{openCount:dossiers.length,prepareCount:0}});
const roNoon=timedOpen('ro-noon','6 noiembrie 2026, ora 12:00');
fakeNow=Date.parse('2026-11-06T09:59:59Z');
assert.deepEqual(Array.from(run(timedPayload([roNoon])).home.openDossierIds),['ro-noon']);
fakeNow=Date.parse('2026-11-06T10:00:01Z');
const expiredNoon=run(timedPayload([roNoon]));
assert.deepEqual(Array.from(expiredNoon.home.openDossierIds),[]);
assert.equal(expiredNoon.freshnessGuard.dossierStatusOverrides['ro-noon'],'REVIEW');
const julyNoon=timedOpen('summer-noon','1 iulie 2026, ora 12:00');
fakeNow=Date.parse('2026-07-01T08:59:59Z');
assert.deepEqual(Array.from(run(timedPayload([julyNoon])).home.openDossierIds),['summer-noon']);
fakeNow=Date.parse('2026-07-01T09:00:01Z');
assert.deepEqual(Array.from(run(timedPayload([julyNoon])).home.openDossierIds),[]);

// Competing deadlines cannot be resolved by taking the latest timestamp:
// e.g. stale top-level Nov 30 vs confirmed call cutoff Nov 6.
const contradictory=timedOpen('conflict','2026-11-06T12:00:00+02:00',
  {closesAt:'2026-11-30T16:00:00+02:00'});
fakeNow=Date.parse('2026-11-05T10:00:00Z');
const held=run(timedPayload([contradictory]));
assert.deepEqual(Array.from(held.home.openDossierIds),[]);
assert.equal(held.freshnessGuard.dossierStatusOverrides.conflict,'REVIEW');
// Date-only cutoff dates cannot be interpreted as \"end of day\" for OPEN.
// Even with a precise competing deadline, ambiguity must hold the record.
const dateOnly=timedOpen('date-only','16 noiembrie 2026');
const dmyDateOnly=timedOpen('dmy-date-only','16.11.2026');
const mixedPrecision=timedOpen('mixed-precision','16 noiembrie 2026, 16:00',
  {closesAt:'16 noiembrie 2026'});
fakeNow=Date.parse('2026-11-10T10:00:00Z');
const precisionHold=run(timedPayload([dateOnly,dmyDateOnly,mixedPrecision]));
assert.deepEqual(Array.from(precisionHold.home.openDossierIds),[]);
for(const id of ['date-only','dmy-date-only','mixed-precision']){
  assert.equal(precisionHold.freshnessGuard.dossierStatusOverrides[id],'REVIEW');
}
const preciseDmy=timedOpen('precise-dmy','16.11.2026 16:00:00');
assert.deepEqual(Array.from(run(timedPayload([preciseDmy])).home.openDossierIds),['precise-dmy'],
  'exact Romanian official clock continues to authorize only within verified scope');
// Compact-home and lazy decision-hub must never disagree on date-only OPEN.

// Zoneless ISO datetimes are unsafe: Date.parse uses the browser's
// timezone, which could keep an already expired call OPEN. Explicitly
// offset-bearing ISO remains actionable up to the exact instant.
const unzonedIso=timedOpen('unzoned-iso','2026-11-11T00:00:00');
const zonedIso=timedOpen('zoned-iso','2026-11-11T00:00:00+02:00');
const impossibleIso=timedOpen('impossible-iso','2026-02-31T00:00:00+02:00');
fakeNow=Date.parse('2026-11-10T21:59:59Z');
const isoBefore=run(timedPayload([unzonedIso,zonedIso,impossibleIso]));
assert.deepEqual(Array.from(isoBefore.home.openDossierIds),['zoned-iso']);
assert.equal(isoBefore.freshnessGuard.dossierStatusOverrides['unzoned-iso'],'REVIEW');
assert.equal(isoBefore.freshnessGuard.dossierStatusOverrides['impossible-iso'],'REVIEW');
fakeNow=Date.parse('2026-11-10T22:00:01Z');
assert.deepEqual(Array.from(run(timedPayload([unzonedIso,zonedIso])).home.openDossierIds),[]);
// Date.parse normalizes 2026-02-31 to March 3 on common JS engines.
// An impossible date-only cutoff must never keep an OPEN badge alive.
const validIsoDay=timedOpen('valid-iso-day','2026-03-31');
const impossibleIsoDay=timedOpen('impossible-iso-day','2026-02-31');
fakeNow=Date.parse('2026-02-28T12:00:00Z');
const isoDayResult=run(timedPayload([validIsoDay,impossibleIsoDay]));
assert.deepEqual(Array.from(isoDayResult.home.openDossierIds),[],
  'valid ISO date-only is archival context, never a precise OPEN cutoff');
assert.equal(isoDayResult.freshnessGuard.dossierStatusOverrides['valid-iso-day'],'REVIEW');
assert.equal(isoDayResult.freshnessGuard.dossierStatusOverrides['impossible-iso-day'],'REVIEW');
// AFIR DR-12's component counter includes a DD.MM.YYYY HH:mm:ss local
// clock, not an inferred date-only EOD. It must not survive until UTC midnight.
const afirMidnight=timedOpen('afir-dr12-other','11.11.2026 00:00:00');
const afirSlash=timedOpen('afir-dr12-slash','11/11/2026 00:00:00');
fakeNow=Date.parse('2026-11-10T21:59:59Z');
assert.deepEqual(Array.from(run(timedPayload([afirMidnight,afirSlash])).home.openDossierIds),['afir-dr12-other','afir-dr12-slash']);
fakeNow=Date.parse('2026-11-10T22:00:00Z');
const midnightHeld=run(timedPayload([afirMidnight,afirSlash]));
assert.deepEqual(Array.from(midnightHeld.home.openDossierIds),[]);
assert.equal(midnightHeld.freshnessGuard.dossierStatusOverrides['afir-dr12-other'],'REVIEW');
assert.equal(midnightHeld.freshnessGuard.dossierStatusOverrides['afir-dr12-slash'],'REVIEW');
// An unparseable competitor cannot be ignored while a confirmed cutoff
// is otherwise valid, and malformed official clocks cannot authorize OPEN.
fakeNow=Date.parse('2026-11-10T08:00:00Z');
const malformedClock=timedOpen('malformed-clock','11.11.2026 24:99');
const malformedCompeting=timedOpen('malformed-competing','11.11.2026 00:00:00',{closesAt:'Neconfirmat'});
const wrongSlashOrder=timedOpen('wrong-us-order','13/11/2026 00:00:00');
const heldNumeric=run(timedPayload([malformedClock,malformedCompeting,wrongSlashOrder]));
assert.deepEqual(Array.from(heldNumeric.home.openDossierIds),['wrong-us-order']);
assert.equal(heldNumeric.freshnessGuard.dossierStatusOverrides['malformed-competing'],'REVIEW');

// Unsupported/ambiguous time around the Bucharest DST transition also holds.
const ambiguous=timedOpen('ambiguous','25 octombrie 2026, ora 03:30');
fakeNow=Date.parse('2026-10-24T08:00:00Z');
assert.deepEqual(Array.from(run(timedPayload([ambiguous])).home.openDossierIds),[]);
// Embedded prose is not an official clock format: never strip a stated
// hour and turn an ambiguous zoneless timestamp into a future date-only
// cutoff. Reject impossible calendar dates even if Date.parse normalizes them.
fakeNow=Date.parse('2026-11-10T08:00:00Z');
const embeddedClocks=timedPayload([
  timedOpen('embedded-zoneless','Termen: 2026-11-11T00:00:00'),
  timedOpen('embedded-dmy-hour','Termen: 13/11/2026 00:00'),
  timedOpen('embedded-invalid-ymd','Termen: 2026-11-31'),
  timedOpen('embedded-invalid-dmy','Termen 11/31/2026'),
  timedOpen('embedded-valid-ymd','Termen: 2026-11-20'),
  timedOpen('exact-official-dmy','11.11.2026 00:00:00')
]);
const embeddedResult=run(embeddedClocks);
assert.deepEqual(Array.from(embeddedResult.home.openDossierIds),
  ['exact-official-dmy']);
assert.equal(embeddedResult.freshnessGuard.dossierStatusOverrides['embedded-valid-ymd'],'REVIEW',
  'embedded date-only prose must not authorize an OPEN cutoff');
for(const id of ['embedded-zoneless','embedded-dmy-hour','embedded-invalid-ymd','embedded-invalid-dmy']){
  assert.equal(embeddedResult.freshnessGuard.dossierStatusOverrides[id],'REVIEW',id);
}
fakeNow=Date.parse('2026-08-26T04:00:00Z');

fakeNow=Date.parse('2026-08-26T04:00:00Z');

console.log('PASS home-freshness-guard-v1.3: wall clock vs historic LKG, expired/provisional/undated OPEN held REVIEW; static boot remains guarded; replay deterministic.');
