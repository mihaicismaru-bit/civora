const PAGINATION_KEYS = new Set([
  'tabel','PARTICIPANT','ENTITATE','docs-BUGET','docs-SOLICITANT','docs-PLAN_ACHIZITII',
  'docs-ANEXE','docs-INDICATOR_PRESTABILIT','CONTRACT_MUNCA','DOCUMENT_PLATA','DOVADA_PLATA',
  'ALTA_CHELTUIALA_COST_SIMPLIFICAT','STAT','cereri-rambursare','istoric-rambursare',
  'propuneri-reziliere','solicitari-reziliere','centralizator-pers-RESURSA_UMANA_IMPLICATA',
  'RESURSA_UMANA_IMPLICATA','clarificare'
]);

const PRESERVE_QUERY_KEYS = new Set(['raportProgresId','raportProgresSnapVersion']);

export function canonicalizeMySmisUrl(raw) {
  const u = new URL(raw);
  u.hash = '';
  const out = new URL(`${u.origin}${u.pathname}`);
  for (const [key, value] of u.searchParams.entries()) {
    if (PRESERVE_QUERY_KEYS.has(key)) out.searchParams.set(key, value);
    else if (!PAGINATION_KEYS.has(key) && !looksLikePaginationValue(value)) out.searchParams.set(key, value);
  }
  return out.href;
}

function looksLikePaginationValue(value = '') {
  try {
    const once = decodeURIComponent(value);
    const decoded = atobSafe(once);
    if (!decoded) return false;
    const jsonText = decodeURIComponent(decoded);
    const obj = JSON.parse(jsonText);
    return obj && Number.isFinite(Number(obj.page)) && Number.isFinite(Number(obj.size));
  } catch {
    return false;
  }
}

function atobSafe(value) {
  try {
    if (typeof atob === 'function') return atob(value);
    return Buffer.from(value, 'base64').toString('binary');
  } catch {
    return null;
  }
}

export function normalizeFilename(name = '') {
  return name.trim().replace(/\s+/g, ' ').toLowerCase();
}

export function isSafeDirectGetCandidate(candidate, pageUrl) {
  try {
    if (!candidate?.href) return false;
    const page = new URL(pageUrl);
    const target = new URL(candidate.href, pageUrl);
    if (target.protocol !== 'https:') return false;
    if (target.origin !== page.origin) return false;
    if (!/(^|\.)mysmis2021\.gov\.ro$/i.test(target.hostname)) return false;
    const hay = `${candidate.text || ''} ${candidate.download || ''} ${target.pathname}`.toLowerCase();
    return /descarc|download|\.pdf(?:$|\?)|\.docx?(?:$|\?)|\.xlsx?(?:$|\?)|document/.test(hay);
  } catch {
    return false;
  }
}

export function rankDirectGetCandidates(candidates, target, pageUrl) {
  const names = (target?.candidate_names || []).map(normalizeFilename);
  return (candidates || [])
    .filter((c) => isSafeDirectGetCandidate(c, pageUrl))
    .map((c) => {
      const hay = normalizeFilename(`${c.text || ''} ${c.download || ''} ${c.href || ''}`);
      const exactName = names.find((n) => n && hay.includes(n));
      let score = exactName ? 100 : 0;
      if (/\.pdf(?:$|\?)/i.test(c.href || '')) score += 10;
      if (/descarc|download/i.test(`${c.text || ''} ${c.download || ''}`)) score += 5;
      return { ...c, score, matched_name: exactName || null };
    })
    .sort((a, b) => b.score - a.score || String(a.href).localeCompare(String(b.href)));
}

export function dedupeCanonicalRoutes(urls) {
  const seen = new Set();
  const out = [];
  for (const raw of urls || []) {
    let key;
    try { key = canonicalizeMySmisUrl(raw); }
    catch { continue; }
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(key);
  }
  return out;
}

export function buildMirrorReceipt({ project, project_uuid, targets, started_at = new Date().toISOString() }) {
  return {
    artifact: `${project}_MYSMIS_DOCUMENT_MIRROR_RECEIPT_v0.4`,
    reader_version: '0.4.0',
    project,
    project_uuid,
    started_at,
    mode: 'READ_ONLY_DIRECT_GET_ONLY',
    targets: targets || [],
    security: {
      button_clicks: false,
      form_submits: false,
      server_writes: false,
      same_origin_get_only: true,
      ssot_promotion_before_hash_and_body_review: false
    }
  };
}

export function summarizeReceipt(receipt) {
  const targets = receipt?.targets || [];
  return {
    total: targets.length,
    downloaded_hashed: targets.filter((t) => t.final_status === 'DOWNLOADED_HASHED').length,
    blocked: targets.filter((t) => t.final_status !== 'DOWNLOADED_HASHED').length
  };
}
