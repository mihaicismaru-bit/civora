#!/usr/bin/env python3
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'partener-eu' / 'web'
STATE = ROOT / 'partener-eu' / 'ingest' / 'state'
index = (WEB / 'index.html').read_text(encoding='utf-8')
js = (WEB / 'ask-partener-v2.js').read_text(encoding='utf-8')
css = (WEB / 'ask-partener-v2.css').read_text(encoding='utf-8')

assert 'ask-partener-v2.css' in index
assert 'ask-partener-v2.js' in index
assert index.index('decision-products.js') < index.index('ask-partener-v2.js')
assert index.index('mipe-canonical-calls.js') < index.index('ask-partener-v2.js')
assert 'window.PARTENER_DECISION_PRODUCTS' in js
assert 'window.PARTENER_MIPE_CANONICAL_CALLS' in js
assert 'const canonicalById=new Map' in js
assert 'const canonicalByCode=uniqueIndex' in js
assert 'const canonicalByOfficialUrl=uniqueIndex' in js
assert 'function canonicalCall(' in js
assert 'canonicalCall(d)' in js
assert 'const candidates=new Set()' in js
assert 'candidates.size===1' in js
assert 'if(direct)return direct' not in js
assert 'return canonicalByCode.get(code)' not in js
assert 'return canonicalByOfficialUrl.get(key)' not in js
assert 'function uniqueIndex(' in js
assert 'function isMipeLinked(' in js
assert 'function urlKey(' in js and 'function canonicalOfficialUrls(' in js
assert "String(x?.source||'').toUpperCase()==='MIPE'" in js
assert 'verificationEvidence' in js and 'sourceUrl' in js and 'sourceTier' in js
assert 'function canonicalParts(' in js
assert 'function interpretQuestion(' in js
assert 'function detectedLocation(' in js
assert 'COUNTY_REGION' in js
assert 'Am înțeles întrebarea astfel:' in js
assert 'Beneficiar:' in js and 'Investiție:' in js and 'Zonă:' in js
assert 'P.dossiers.map(d=>rank(d,ts,interpretation))' in js
assert 'eligibilitatea din datele verificate' in js
assert 'activitățile din datele verificate' in js
assert 'quality?.completeness' in js
assert 'function knownValue(' in js
assert 'function unknownFacts(' in js
assert 'Termenul de depunere nu este încă confirmat.' in js
assert 'Valoarea finanțării nu este încă confirmată.' in js
assert 'Eligibilitatea solicitantului nu este încă confirmată' in js
assert 'Nu am găsit încă o potrivire suficient de sigură' in js
assert 'Nu îți afișăm apeluri aleatorii' in js
assert 'Încă neconfirmat' in js
assert 'Deschide dosarul verificat' in js
assert 'T1/T1B' not in js
assert 'tier neprecizat' not in js
assert 'sursă oficială primară' in js
assert 'window.PARTENER_DATA.calls' not in js
assert 'D.calls.slice(0,2)' not in js
assert 'dossier_similarity' not in js and 'best_match' not in js
assert 'C.calls=' not in js and 'C.calls.push' not in js
assert 'P.dossiers=' not in js and 'P.dossiers.push' not in js
assert 'fetch(' not in js and 'XMLHttpRequest' not in js
assert '.askV2Grid' in css and '@media(max-width:760px)' in css

# The checked-in Source Intelligence products are read-only fixtures for proving that
# the conservative correlation keys have real overlap. No fuzzy/title matching is allowed.
def fold(value: object) -> str:
    text = unicodedata.normalize('NFD', str(value or '').lower())
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()


def official_tier(value: object) -> bool:
    return bool(re.match(r'^T1(?:B)?(?:\b|_)', str(value or '').strip(), re.I))


def code_key(value: object) -> str:
    raw = str(value or '').strip()
    if re.match(r'^(?:-|—|n/?a|unknown|necunoscut|neconfirmat)$', raw, re.I):
        return ''
    return re.sub(r'\s+', '', fold(raw))


def url_key(value: object) -> str:
    try:
        parsed = urlsplit(str(value or ''))
    except ValueError:
        return ''
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        return ''
    path = parsed.path.rstrip('/') or '/'
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ''))


def unique_index(rows: list[dict], keys_for) -> dict[str, dict]:
    buckets: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        for key in set(k for k in keys_for(row) if k):
            buckets[key].append(row)
    return {key: values[0] for key, values in buckets.items() if len(values) == 1}


def is_mipe_linked(dossier: dict) -> bool:
    if re.match(r'^MIPE(?:_|$)', str(dossier.get('sourceType') or ''), re.I):
        return True
    return any(str(link.get('source') or '').upper() == 'MIPE' for link in dossier.get('sourceLinks') or [])


decision_payload = json.loads((STATE / 'decision_products.json').read_text(encoding='utf-8'))
canonical_payload = json.loads((STATE / 'mipe_canonical_calls.json').read_text(encoding='utf-8'))
dossiers = decision_payload.get('dossiers') or []
canonical = canonical_payload.get('calls') or []
by_id = {row.get('id'): row for row in canonical if row.get('id')}
by_code = unique_index(canonical, lambda row: [code_key(row.get('code'))])
by_url = unique_index(
    canonical,
    lambda row: [
        url_key(ev.get('sourceUrl'))
        for ev in row.get('verificationEvidence') or []
        if official_tier(ev.get('sourceTier'))
    ],
)

resolved = {'id': 0, 'code': 0, 'url': 0}
for dossier in dossiers:
    if dossier.get('id') in by_id:
        resolved['id'] += 1
        continue
    if not is_mipe_linked(dossier):
        continue
    code = code_key(dossier.get('code'))
    if code and code in by_code:
        resolved['code'] += 1
        continue
    urls = {
        url_key(source.get('url'))
        for source in dossier.get('sources') or []
        if official_tier(source.get('tier'))
    }
    if any(url and url in by_url for url in urls):
        resolved['url'] += 1

assert sum(resolved.values()) > 0, 'No deterministic Ask↔MIPE correlation exists in the checked-in corpus'
assert resolved['code'] + resolved['url'] > 0, f'Only exact IDs correlate; stable cross-product join is still unproven: {resolved}'
print(json.dumps({
    'status': 'PASS',
    'dossiers': len(dossiers),
    'canonicalCalls': len(canonical),
    'resolved': resolved,
}, ensure_ascii=False))
