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
const fixedNow=Date.parse('2026-11-07T19:00:00Z');
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
console.log('PASS active homepage: future-dated PREPARE/CONSULTATION only; expired/unknown/contradictory fail closed; OPEN metric is live; no promotion.');
