#!/usr/bin/env node
/*
 * Build partener-eu/web/ask-index.js: a compact search index for "Întreabă PARTENER.EU".
 *
 * The Ask page used to lazy-load decision-products.js (~3 MB) and
 * mipe-canonical-calls.js (~2.6 MB) just to rank dossiers. This index keeps
 * exactly the fields ask-partener-v2.js reads, with long section/eligibility
 * text pre-folded and de-duplicated per word. Ranking is unchanged: every
 * query token is a single folded word, and a word-level substring match on the
 * de-duplicated text gives the same result as on the full text.
 *
 * It is a deployment artifact (generated in the Pages workflow), never a
 * second source of truth; ask-partener-v2.js falls back to the full data when
 * the index is missing.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const WEB = path.resolve(__dirname, '..', 'web');
const fold = s => String(s || '').toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, ' ').trim();
// Query tokens are always longer than 2 characters, so shorter words can never match.
const words = s => fold(s).split(' ').filter(w => w.length > 2);
const uniqueWords = s => [...new Set(words(s))].join(' ');
const UNKNOWN_SECTION = /nu este.*confirmat|nu sunt.*confirmat|neconfirmat/i;

function loadGlobal(file, name) {
  const sandbox = { window: {} };
  vm.runInNewContext(fs.readFileSync(path.join(WEB, file), 'utf8'), sandbox, { filename: file });
  return sandbox.window[name];
}

const P = loadGlobal('decision-products.js', 'PARTENER_DECISION_PRODUCTS');
const C = loadGlobal('mipe-canonical-calls.js', 'PARTENER_MIPE_CANONICAL_CALLS');
if (!P || !Array.isArray(P.dossiers)) throw new Error('decision-products.js has no dossiers');

const SHOWN_FACTS = new Set(['termen', 'grant', 'finantare', 'buget', 'contributie proprie', 'status'].map(fold));

// Per dossier: folded section titles + one vocabulary string "word:mask,..."
// where mask (base 36) marks the sections containing that word.
function sectionVocabulary(sections) {
  const masks = new Map();
  sections.forEach((s, i) => {
    for (const w of new Set(words((s.items || []).join(' ')))) {
      masks.set(w, (masks.get(w) || 0) | (1 << i));
    }
  });
  return [...masks].map(([w, m]) => `${w}:${m.toString(36)}`).join(',');
}

// Ask answers only with dossiers that pass the publication gate (the same set that gets static pages).
const dossiers = P.dossiers.filter(d => String(d.publicationState || '').toUpperCase() === 'PUBLISHABLE').map(d => ({
  id: d.id,
  publicationState: d.publicationState,
  title: d.title,
  programme: d.programme,
  region: d.region,
  code: d.code,
  status: d.status,
  sourceType: d.sourceType,
  sourceLinks: (d.sourceLinks || []).map(x => ({ source: x && x.source })),
  audience: d.audience,
  standfirst: d.standfirst,
  decisionAction: d.decisionAction,
  // only the facts the Ask card shows or checks
  quickFacts: (d.quickFacts || []).filter(q => SHOWN_FACTS.has(fold(q.label))).map(q => ({ label: q.label, value: q.value, confidence: q.confidence })),
  quality: { completeness: d.quality && d.quality.completeness },
  // all sources: official-tier URLs also link a dossier to its canonical call
  sources: (d.sources || []).map(x => ({ url: x.url, tier: x.tier, label: x.label })),
  // only "not confirmed" sections are displayed verbatim by the Ask card
  sections: (d.sections || []).filter(s => UNKNOWN_SECTION.test(s.title || '')).map(s => ({ title: s.title, items: s.items })),
  // ranking data for every section
  sectionTitles: (d.sections || []).map(s => fold(s.title)),
  sectionVocab: sectionVocabulary(d.sections || []),
}));

const calls = (Array.isArray(C && C.calls) ? C.calls : []).map(c => {
  const e = (c.materialFacts && c.materialFacts.eligibility) || {};
  return {
    id: c.id,
    code: c.code,
    title: c.title,
    programme: c.programme,
    region: c.region,
    status: c.status,
    verificationEvidence: (c.verificationEvidence || []).map(v => ({ sourceTier: v.sourceTier, sourceUrl: v.sourceUrl })),
    eligibilityText: uniqueWords([...(e.conditions || []), ...(e.partners || []), ...(e.geographic_scope || [])].slice(0, 16).join(' ')),
    activitiesText: uniqueWords((c.activities || []).slice(0, 16).join(' ')),
  };
});

const payload = { schemaVersion: 1, generatedAt: P.generatedAt || null, dossiers, calls };
const out = 'window.PARTENER_ASK_INDEX=' + JSON.stringify(payload) + ';\n';
fs.writeFileSync(path.join(WEB, 'ask-index.js'), out);
console.log(JSON.stringify({ dossiers: dossiers.length, calls: calls.length, bytes: out.length }));
