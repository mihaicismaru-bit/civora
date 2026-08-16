#!/usr/bin/env python3
"""Remove administrative/program-level MIPE objects from the canonical call registry.

The crawler intentionally has high recall. Canonical publication must have high
precision: methodologies, programme-wide instructions, payment lists and broad
contracting reports may support real calls, but are not funding calls by
themselves.
"""
from __future__ import annotations
import json, re, unicodedata
from pathlib import Path
from typing import Any

ROOT=Path(__file__).resolve().parents[2]
PATH=ROOT/'partener-eu/ingest/state/mipe_canonical_calls.json'
JS=ROOT/'partener-eu/web/mipe-canonical-calls.js'


def clean(v:Any)->str:
    return re.sub(r'\s+',' ',str(v or '')).strip()

def fold(v:Any)->str:
    s=''.join(ch for ch in unicodedata.normalize('NFKD',clean(v)) if not unicodedata.combining(ch))
    return re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()

ADMIN_PREFIXES=(
    'instructiunea ', 'metodologia ', 'lista platilor ', 'datele cumulative ',
    'programul educatie si ocupare versiunea ', 'programul sanatate versiunea ',
    'minuta reuniunii ', 'documente aferente reuniunii ', 'sinteza deciziilor reuniunii ',
    'lista proiectelor contractate pe regiuni', 'lista proiectelor pe regiuni',
    'calendarul lansarilor', 'calendar lansari',
)
GENERIC_PHRASES=(
    'privind transmiterea calendarului pentru apelurile de proiecte',
    'situatiei lunare aferente apelurilor de proiecte si contractelor',
    'metodologia de verificare evaluare si selectie a proiectelor',
    'conditii generale aferent programului',
)
FUNDING_TERMS=('grant','finantare','investitii','investitie','sprijin pentru','masuri active','competente','infrastructura','intreprinderi','servicii','educatie','ocupare','neet','step','erasmus','antreprenorial')


def real_call(c:dict)->tuple[bool,str]:
    title=fold(c.get('title'))
    code=clean(c.get('code'))
    latest=str(c.get('canonicalGroup',{}).get('latestEvent') or '')
    if code and code!='—':
        return True,'EXPLICIT_CALL_CODE'
    if any(title.startswith(p) for p in ADMIN_PREFIXES):
        return False,'ADMINISTRATIVE_TITLE'
    if any(p in title for p in GENERIC_PHRASES):
        return False,'PROGRAMME_LEVEL_DOCUMENT'
    # Cross-call lifecycle reports are evidence sources, not a canonical call.
    if latest in {'CONTRACTING_UPDATE','EVALUATION_UPDATE','RESULTS_PUBLISHED'}:
        if not any(t in title for t in FUNDING_TERMS):
            return False,'CROSS_CALL_LIFECYCLE_REPORT'
    # Generic official updates need a clearly named financing object.
    if latest in {'OFFICIAL_UPDATE','CONTRACTING_UPDATE'} and len(title.split())<5:
        return False,'LOW_SPECIFICITY_UPDATE'
    if not any(t in title for t in FUNDING_TERMS) and latest not in {'CONSULTATION_OPENED','GUIDE_PUBLISHED','GUIDE_MODIFIED','CALL_OPENED','DEADLINE_EXTENDED','CALL_CLOSED'}:
        return False,'NO_FUNDING_IDENTITY'
    return True,'CALL_SPECIFIC'


def main()->int:
    data=json.loads(PATH.read_text(encoding='utf-8'))
    kept=[]; removed=[]
    for c in data.get('calls') or []:
        ok,reason=real_call(c)
        if ok:
            c.setdefault('canonicalGate',{})['decision']='KEEP'
            c['canonicalGate']['reason']=reason
            kept.append(c)
        else:
            removed.append({'id':c.get('id'),'title':c.get('title'),'reason':reason,'sourceUrls':c.get('canonicalGroup',{}).get('pageUrls',[])})
    data['calls']=kept
    s=data.setdefault('summary',{})
    s['prePrecisionGateCalls']=s.get('canonicalCalls',len(kept)+len(removed))
    s['canonicalCalls']=len(kept)
    s['precisionGateRemoved']=len(removed)
    s['withExplicitCode']=sum(1 for c in kept if c.get('code') not in {None,'—'})
    s['withDocuments']=sum(1 for c in kept if c.get('canonicalGroup',{}).get('documentCount'))
    s['publishable']=sum(1 for c in kept if c.get('publicationState')=='PUBLISHABLE')
    data['precisionGate']={'failClosed':True,'removed':removed}
    PATH.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    JS.write_text('window.PARTENER_MIPE_CANONICAL_CALLS='+json.dumps(data,ensure_ascii=False,separators=(',',':'))+';\n',encoding='utf-8')
    print(json.dumps({'kept':len(kept),'removed':len(removed),'removedSample':removed[:8]},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    raise SystemExit(main())
