#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'partener-eu' / 'web'
STATE = ROOT / 'partener-eu' / 'ingest' / 'state'

index = (WEB / 'index.html').read_text(encoding='utf-8')
daily = json.loads((STATE / 'daily_brief.json').read_text(encoding='utf-8'))
people = json.loads((STATE / 'people_policy.json').read_text(encoding='utf-8'))

assert 'daily-brief-data.js' in index and 'daily-brief.js' in index
assert index.index('daily-brief-data.js') < index.index('daily-brief.js')
assert 'people-policy-data.js' in index and 'people-policy-v1.js' in index
assert index.index('people-policy-data.js') < index.index('people-policy-v1.js')

assert daily.get('policy', {}).get('dailyGenerated') is True
assert daily.get('policy', {}).get('decisionProductsOnly') is True
assert daily.get('policy', {}).get('rawIngestionExcluded') is True
assert daily.get('policy', {}).get('expiredOpenExcluded') is True
assert len(daily.get('items') or []) <= 4
for item in daily.get('items') or []:
    assert item.get('title') and item.get('action') and item.get('label')
    public_text=' '.join(str(item.get(k) or '') for k in ('label','programme','title','summary','action'))
    assert "{'" not in public_text and 'FUNDING_COMMITMENT' not in public_text
    assert not public_text.lstrip().startswith('{')

assert people.get('mode') == 'AUTO'
assert people.get('policy', {}).get('statementIsNotAdministrativeFact') is True
assert len(people.get('homeIds') or []) <= 3
ids = {x.get('id') for x in people.get('items') or []}
assert all(x in ids for x in people.get('homeIds') or [])
home = [next(x for x in people['items'] if x['id'] == i) for i in people.get('homeIds') or []]
assert len({x.get('personId') for x in home}) == len(home)
for item in people.get('items') or []:
    assert item.get('person') and item.get('role')
    assert item.get('officialFact')

ui = (WEB / 'people-policy-v1.js').read_text(encoding='utf-8')
for forbidden in ('People & Policy Intelligence','FUNDING COMMITMENT','PROGRAMME CHANGE SIGNAL','POLICY SIGNAL'):
    assert forbidden not in ui

print(json.dumps({'dailyCards':len(daily.get('items') or []),'peopleSignals':len(people.get('items') or []),'homePeople':len(people.get('homeIds') or [])},ensure_ascii=False,indent=2))
