#!/usr/bin/env python3
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
canon=json.loads((ROOT/'partener-eu/ingest/state/mipe_canonical_calls.json').read_text(encoding='utf-8'))
products=json.loads((ROOT/'partener-eu/ingest/state/decision_products.json').read_text(encoding='utf-8'))

assert canon.get('policy',{}).get('oneCanonicalObjectPerCall') is True
assert canon.get('policy',{}).get('groupPagesCorrigendaAndDocuments') is True
assert canon.get('precisionGate',{}).get('failClosed') is True
calls=canon.get('calls') or []
assert calls, 'no canonical MIPE calls generated'
ids=[c['id'] for c in calls]
assert len(ids)==len(set(ids)), 'duplicate canonical MIPE ids'
for c in calls:
    assert c.get('title') and c.get('programme')
    assert c.get('status') in {'REVIEW','EXPECTED','PUBLIC_CONSULTATION','OPEN','CLOSED'}
    assert c.get('canonicalGroup',{}).get('pageCount',0)>=1
    assert c.get('verificationEvidence')
    assert c.get('publicationDecision',{}).get('blockedFactClasses') is not None
    assert c.get('canonicalGate',{}).get('decision')=='KEEP'
    folded=c.get('title','').lower()
    assert not folded.startswith('instrucțiunea '), f'administrative instruction leaked as call: {c.get("title")}'
    assert not folded.startswith('lista plăților '), f'payment list leaked as call: {c.get("title")}'
    assert 'lista proiectelor contractate pe regiuni' not in folded, f'cross-call report leaked as call: {c.get("title")}'
    for e in c.get('verificationEvidence',[]):
        assert str(e.get('sourceUrl','')).startswith('https://mfe.gov.ro/')

coverage=products.get('coverage',{}).get('mipe',{})
assert coverage.get('canonical')==len(calls)
assert coverage.get('candidates')==len(calls)
assert coverage.get('matched',0)+coverage.get('provisional',0)==len(calls)
mipe_dossiers=[d for d in products.get('dossiers',[]) if d.get('sourceType')=='MIPE_CANONICAL_V1' or d.get('canonicalLinks')]
assert mipe_dossiers, 'canonical MIPE corpus did not reach public dossiers'
for d in mipe_dossiers:
    assert d.get('sections') and d.get('sources')
    assert d.get('quality',{}).get('failClosed') is True
print(json.dumps({'canonicalCalls':len(calls),'precisionRemoved':canon.get('summary',{}).get('precisionGateRemoved'),'mipeDossiersOrMatches':len(mipe_dossiers),'coverage':coverage},ensure_ascii=False,indent=2))
