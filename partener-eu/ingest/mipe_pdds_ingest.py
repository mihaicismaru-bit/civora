#!/usr/bin/env python3
import re
import urllib.parse
import mipe_ingest_ipv4 as base

PDDS_SEED = 'https://mfe.gov.ro/pdds/despre-program-programare/'

# Prioritize the explicit official PDDS programme tree supplied by the operator.
if PDDS_SEED not in base.ROOTS:
    base.ROOTS.insert(0, PDDS_SEED)
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
    health['pddsSecondHopCount'] = len(second_hop)
    return out, health

base.discover = scoped_pdds_discover

if __name__ == '__main__':
    base.main()
