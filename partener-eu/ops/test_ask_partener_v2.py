#!/usr/bin/env python3
import json
import re
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
assert 'function resolveCanonical(' in js
assert 'function canonicalUrls(' in js
assert 'function dossierUrls(' in js
assert 'canonicalByCode=uniqueIndex' in js
assert 'canonicalByUrl=uniqueIndex' in js
assert 'candidates.size===1' in js
assert 'ambiguous=new Set' in js
assert 'canonicalById.get(d.id)' not in js
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
assert 'window.PARTENER_DATA.calls' not in js
assert 'D.calls.slice(0,2)' not in js
assert 'C.calls=' not in js and 'C.calls.push' not in js
assert 'P.dossiers=' not in js and 'P.dossiers.push' not in js
assert 'fetch(' not in js and 'XMLHttpRequest' not in js
assert '.askV2Grid' in css and '@media(max-width:760px)' in css

decisions = json.loads((STATE / 'decision_products.json').read_text(encoding='utf-8'))
canonical = json.loads((STATE / 'mipe_canonical_calls.json').read_text(encoding='utf-8'))
calls = canonical.get('calls') or []

def fold(value):
    import unicodedata
    text = unicodedata.normalize('NFD', str(value or '').lower())
    text = ''.join(ch for ch in text if unicodedata.category(ch) != 'Mn')
    return re.sub(r'[^a-z0-9]+', ' ', text).strip()

def norm_code(value):
    value = fold(value)
    return None if value in {'', 'n a', 'neconfirmat', 'necunoscut'} else value

def norm_url(value):
    try:
        p = urlsplit(str(value or ''))
    except ValueError:
        return None
    if p.scheme not in {'http', 'https'} or not p.netloc:
        return None
    path = re.sub(r'/+', '/', p.path or '/')
    if path != '/':
        path = path.rstrip('/')
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), path, '', ''))

def unique_index(items, keys):
    index = {}
    ambiguous = set()
    for item in items:
        for key in keys(item):
            if not key or key in ambiguous:
                continue
            if key in index and index[key] is not item:
                del index[key]
                ambiguous.add(key)
            else:
                index.setdefault(key, item)
    return index

def call_urls(call):
    values = [x.get('sourceUrl') for x in call.get('verificationEvidence') or []]
    values += list((call.get('canonicalGroup') or {}).get('pageUrls') or [])
    values += [x.get('url') for x in call.get('timeline') or []]
    return {norm_url(x) for x in values if norm_url(x)}

def dossier_urls(dossier):
    values = [x.get('url') for x in dossier.get('sources') or []]
    if isinstance(dossier.get('source'), dict):
        values.append(dossier['source'].get('url'))
    return {norm_url(x) for x in values if norm_url(x)}

by_id = unique_index(calls, lambda c: [str(c.get('id') or '').strip()])
by_code = unique_index(calls, lambda c: [norm_code(c.get('code'))])
by_url = unique_index(calls, call_urls)

resolved = 0
resolved_by_url = 0
for dossier in decisions.get('dossiers') or []:
    candidates = set()
    did = str(dossier.get('id') or '').strip()
    code = norm_code(dossier.get('code'))
    if did in by_id:
        candidates.add(id(by_id[did]))
    if code in by_code:
        candidates.add(id(by_code[code]))
    url_hits = {id(by_url[url]) for url in dossier_urls(dossier) if url in by_url}
    candidates.update(url_hits)
    if len(candidates) == 1:
        resolved += 1
        if url_hits:
            resolved_by_url += 1

assert resolved_by_url > 0, 'real corpus has no deterministic dossier↔canonical URL overlap'
print(json.dumps({
    'status': 'PASS',
    'resolvedCanonicalDossiers': resolved,
    'resolvedByOfficialUrl': resolved_by_url,
    'policy': 'unique id/code/official URL; ambiguity fails closed',
}, ensure_ascii=False, indent=2))
