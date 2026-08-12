#!/usr/bin/env python3
import json
import re
import urllib.parse
from pathlib import Path
import mipe_ingest_ipv4 as base

PDDS_SEED = 'https://mfe.gov.ro/pdds/despre-program-programare/'
WEBINDEX_SEEDS = Path(__file__).resolve().parent / 'state' / 'pdds_webindex_seeds.json'

# Prioritize the explicit official PDDS programme tree supplied by the operator.
if PDDS_SEED not in base.ROOTS:
    base.ROOTS.insert(0, PDDS_SEED)

# When the main PDDS seed is unreachable from the runner, probe only canonical
# PDDS URLs previously discovered through a web index. Discovery is not
# verification: these roots still must be fetched successfully from mfe.gov.ro
# before any item can be published.
try:
    seed_data = json.loads(WEBINDEX_SEEDS.read_text(encoding='utf-8'))
    fallback_urls = []
    for item in seed_data.get('items', []):
        url = str(item.get('url') or '').strip()
        p = urllib.parse.urlparse(url)
        if p.scheme == 'https' and p.hostname == 'mfe.gov.ro' and p.path.startswith('/pdds/'):
            fallback_urls.append(url)
    insert_at = 1 if base.ROOTS and base.ROOTS[0] == PDDS_SEED else 0
    for url in reversed(fallback_urls):
        if url not in base.ROOTS:
            base.ROOTS.insert(insert_at, url)
except Exception:
    fallback_urls = []

for kw in ['pdds', 'dezvoltare durabilă', 'dezvoltare durabila', 'programare', 'prioritate', 'priorități', 'prioritati']:
    if kw not in base.KW:
        base.KW.append(kw)

_original_tag = base.tag

def pdds_tag(text):
    x = (text or '').lower()
    if 'pdds' in x or 'programul dezvoltare durabilă' in x or 'programul dezvoltare durabila' in x:
        return 'PDDS'
    return _original_tag(text)

base.tag = pdds_tag
_original_discover = base.discover

def scoped_pdds_discover(root):
    out, health = _original_discover(root)
    if '/pdds/' not in root or not health.get('ok'):
        return out, health

    # Second-hop discovery only inside the official PDDS path. This is bounded,
    # provenance-preserving and fail-closed: no external hosts or non-PDDS paths.
    seen = {c.get('url') for c in out if c.get('url')}
    second_hop = []
    for candidate in list(out)[:15]:
        url = candidate.get('url') or ''
        p = urllib.parse.urlparse(url)
        if p.hostname not in base.HOSTS or not p.path.startswith('/pdds/'):
            continue
        r = base.curl(url, 16)
        if not r.get('ok'):
            continue
        try:
            page, title, desc, body = base.page(r['data'])
        except Exception:
            continue
        for href, anchor in page.links:
            u = base.norm(href, r.get('url') or url)
            if not u or u in seen:
                continue
            up = urllib.parse.urlparse(u)
            if up.hostname not in base.HOSTS or not up.path.startswith('/pdds/'):
                continue
            if re.search(r'\.(pdf|docx?|xlsx?|zip|jpg|jpeg|png|gif|svg)(\?|$)', u, re.I):
                continue
            if base.score(anchor, '', '', u) > 0:
                seen.add(u)
                second_hop.append({'url': u, 'title': anchor, 'via': 'pdds-second-hop'})
                if len(second_hop) >= 30:
                    break
        if len(second_hop) >= 30:
            break
    out.extend(second_hop)
    health['pddsSeed'] = PDDS_SEED
    health['pddsWebIndexSeedCount'] = len(fallback_urls)
    health['pddsSecondHopCount'] = len(second_hop)
    return out, health

base.discover = scoped_pdds_discover

if __name__ == '__main__':
    base.main()
