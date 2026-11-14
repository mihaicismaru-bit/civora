import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';

const source = readFileSync('partener-eu/web/consultant-mysmis-v1.js', 'utf8');
const now = Date.parse('2026-11-14T16:30:00Z');
class FrozenDate extends Date { static now() { return now; } }
const exactUrl = 'https://reporting.mysmis2021.gov.ro/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027';
const otherOfficialUrl = exactUrl.replace('reporting.', 'resurse.');
const current = {
  status: 'OK_DIRECT',
  observedAt: '2026-11-14T15:00:00Z',
  directOnly: true,
  source: { retrieval: 'CANONICAL_OFFICIAL_FETCH', canonicalUrl: exactUrl },
  validatedCallCount: 993,
  visibleRowCount: 1,
  explicitStatuses: ['FINALIZAT'],
  notice: 'Snapshot direct oficial.',
  calls: [{ programme: 'PEO', call: 'Stagii de practică pentru elevi',
    officialStatus: 'FINALIZAT', entities: '5', submitted: '6', contracts: '2',
    callBudgetRon: '1000000' }],
};

function render(data) {
  let snapshot = '', dossier = '';
  const hero = {
    querySelector(selector) {
      return selector === 'h1' ? { textContent: 'Stagii de practică pentru elevi' }
        : { textContent: 'PEO' };
    },
    insertAdjacentHTML(_where, html) { dossier = html; },
  };
  const dashboard = { insertAdjacentHTML(_where, html) { snapshot = html; } };
  const root = {
    querySelector(selector) {
      if (selector === '.cw3DashboardGrid') return dashboard;
      if (selector === '.cw3DossierHero') return hero;
      return null;
    },
  };
  const document = {
    querySelector(selector) { return selector === '.cw3Root' ? root : null; },
    getElementById() { return {}; },
  };
  class MutationObserver { observe() {} }
  runInNewContext(source, {
    window: { PARTENER_DATA: { mysmisRegistry: data } },
    document, MutationObserver, Date: FrozenDate, URL,
  });
  return { snapshot, dossier };
}

const accepted = render(current);
assert.match(accepted.snapshot, /993/);
assert.match(accepted.dossier, /Posibilă corespondență textuală MySMIS/);
assert.match(accepted.dossier, /Stagii de practică pentru elevi/);
assert.match(accepted.dossier, /codului exact de apel/);
assert.doesNotMatch(accepted.dossier, /FINALIZAT|1000000|cw3MySMISStatus|cw3MySMISFacts/,
  'Title-only match is discovery; no status/budget/counters, even for an exact title.');
// Two different official call rows can have identical titles and programme,
// so their status and budget must not be projected onto a consultant dossier.
const ambiguous = render({...current, calls: [
  {...current.calls[0], officialStatus:'DESCHIS', callBudgetRon:'999999999', entities:'888'},
  {...current.calls[0], officialStatus:'FINALIZAT', callBudgetRon:'1000000', entities:'5'}
]});
assert.match(ambiguous.dossier, /Posibilă corespondență textuală MySMIS/);
assert.doesNotMatch(ambiguous.dossier, /DESCHIS|FINALIZAT|999999999|1000000|888|cw3MySMISFacts/,
  'Ambiguous candidate row must never leak or attribute material official facts.');
assert.match(render({ ...current, source: { ...current.source, canonicalUrl: otherOfficialUrl } }).dossier, /FINALIZAT/);

for (const [name, variant] of Object.entries({
  legacy_august: { ...current, observedAt: '2026-08-17T21:43:22Z' },
  sla_expired: { ...current, observedAt: '2026-11-14T08:00:00Z' },
  future: { ...current, observedAt: '2026-11-14T17:00:00Z' },
  timezone_missing: { ...current, observedAt: '2026-11-14T15:00:00' },
  failed_corpus: { ...current, status: 'DEGRADED_LAST_KNOWN_GOOD_PRESERVED' },
  indirect: { ...current, directOnly: false },
  unverified: { ...current, source: { ...current.source, retrieval: 'SEARCH_DISCOVERY' } },
  spoofed_host: { ...current, source: { ...current.source, canonicalUrl: 'https://reporting.mysmis2021.gov.ro.attacker.example/ords/repo_bo/r/mysmis-2021/finantari-programe-2021-2027' } },
  injected_query: { ...current, source: { ...current.source, canonicalUrl: exactUrl + '?page=2' } },
})) {
  const rendered = render(variant);
  assert.match(rendered.snapshot, /verificare expirată/, name);
  assert.match(rendered.dossier, /verificare expirată/, name);
  assert.doesNotMatch(rendered.snapshot, /993|1000000|FINALIZAT/, name);
  assert.doesNotMatch(rendered.dossier, /1000000|FINALIZAT/, name);
  assert.match(rendered.dossier, /registrul oficial/, name);
}
console.log('PASS MySMIS consultant freshness: 2 valid endpoints + 9 negative cases');
