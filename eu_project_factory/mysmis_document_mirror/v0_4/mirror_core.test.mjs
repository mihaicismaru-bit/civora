import test from 'node:test';
import assert from 'node:assert/strict';
import {
  canonicalizeMySmisUrl,
  dedupeCanonicalRoutes,
  isSafeDirectGetCandidate,
  rankDirectGetCandidates,
  buildMirrorReceipt,
  summarizeReceipt
} from './mirror_core.mjs';

const BASE = 'https://mysmis2021.gov.ro/proiect/370bf40f-8283-4537-9377-6ac31bbdcf93';

test('canonicalization removes MySMIS pagination variants', () => {
  const a = `${BASE}/GRUP_TINTA_FORMULAR_PARTICIPANT_STANDARD/abc?doc-GRUP_TINTA=JTdCJTIyc2l6ZSUyMiUzQTEwJTJDJTIycGFnZSUyMiUzQTAlN0Q`;
  const b = `${BASE}/GRUP_TINTA_FORMULAR_PARTICIPANT_STANDARD/abc?doc-GRUP_TINTA=JTdCJTIyc2l6ZSUyMiUzQTUwJTJDJTIycGFnZSUyMiUzQTAlN0Q`;
  assert.equal(canonicalizeMySmisUrl(a), canonicalizeMySmisUrl(b));
});

test('canonicalization preserves report snapshot identity', () => {
  const u = `${BASE}/GRUP_TINTA_FORMULAR_PARTICIPANT_STANDARD/abc?raportProgresSnapVersion=1&raportProgresId=r1&doc-GRUP_TINTA=x`;
  const c = canonicalizeMySmisUrl(u);
  assert.match(c, /raportProgresSnapVersion=1/);
  assert.match(c, /raportProgresId=r1/);
});

test('dedupe collapses repeated canonical routes', () => {
  const urls = [
    `${BASE}/BUGET_STRATEGII?tabel=a`,
    `${BASE}/BUGET_STRATEGII?tabel=b`,
    `${BASE}/BUGET_STRATEGII`
  ];
  assert.equal(dedupeCanonicalRoutes(urls).length, 1);
});

test('direct GET safety rejects cross-origin and non-download links', () => {
  assert.equal(isSafeDirectGetCandidate({href:'https://evil.example/a.pdf', text:'download'}, BASE), false);
  assert.equal(isSafeDirectGetCandidate({href:`${BASE}/OBIECTIVE`, text:'Obiective'}, BASE), false);
  assert.equal(isSafeDirectGetCandidate({href:`${BASE}/document/abc.pdf`, text:'Descarcă'}, BASE), true);
});

test('ranking prefers explicit target filename', () => {
  const target = {candidate_names:['Notificare 4 310224 SI ANEXA v4.pdf']};
  const items = [
    {href:`${BASE}/document/generic.pdf`, text:'Descarcă generic'},
    {href:`${BASE}/document/notif.pdf`, text:'Notificare 4 310224 SI ANEXA v4.pdf'}
  ];
  const ranked = rankDirectGetCandidates(items, target, BASE);
  assert.equal(ranked[0].matched_name, 'notificare 4 310224 si anexa v4.pdf');
});

test('receipt remains fail-closed until body/hash review', () => {
  const r = buildMirrorReceipt({project:'310224', project_uuid:'u', targets:[{final_status:'DOWNLOADED_HASHED'},{final_status:'BLOCKED_NO_DIRECT_GET'}]});
  assert.equal(r.security.server_writes, false);
  assert.equal(r.security.ssot_promotion_before_hash_and_body_review, false);
  assert.deepEqual(summarizeReceipt(r), {total:2, downloaded_hashed:1, blocked:1});
});
