#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / 'partener-eu' / 'web'
STATE = ROOT / 'partener-eu' / 'ingest' / 'state'

index = (WEB / 'index.html').read_text(encoding='utf-8')
daily = json.loads((STATE / 'daily_brief.json').read_text(encoding='utf-8'))
people = json.loads((STATE / 'people_policy.json').read_text(encoding='utf-8'))
official = json.loads((STATE / 'people_policy_official_sources.json').read_text(encoding='utf-8'))

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

assert official.get('policy', {}).get('directOfficialOnly') is True
assert official.get('policy', {}).get('signalsDoNotChangeCalls') is True
assert official.get('policy', {}).get('failClosed') is True
assert len(official.get('sources') or []) >= 3
for source in official.get('sources') or []:
    assert source.get('url','').startswith('https://')
    assert source.get('failClosed') is True

assert people.get('mode') == 'AUTO'
policy=people.get('policy', {})
assert policy.get('statementIsNotAdministrativeFact') is True
assert policy.get('homepageOnly') is True
assert policy.get('officialSourceIngestion') is True
assert policy.get('directOfficialHomepageOnly') is True
assert policy.get('hideWhenNoFreshOfficialSignals') is True
assert len(people.get('homeIds') or []) <= 3
ids = {x.get('id') for x in people.get('items') or []}
assert all(x in ids for x in people.get('homeIds') or [])
home = [next(x for x in people['items'] if x['id'] == i) for i in people.get('homeIds') or []]
assert len({x.get('personId') for x in home}) == len(home)
for item in people.get('items') or []:
    assert item.get('person') and item.get('role')
    assert item.get('officialFact')
for item in home:
    hosts={(urlparse(str(s.get('url') or '')).hostname or '').lower() for s in item.get('sources') or []}
    assert hosts, item.get('id')

ui = (WEB / 'people-policy-v1.js').read_text(encoding='utf-8')
for forbidden in ('People & Policy Intelligence','FUNDING COMMITMENT','PROGRAMME CHANGE SIGNAL','POLICY SIGNAL'):
    assert forbidden not in ui
assert 'isHome()' in ui
assert 'data-peopleall' not in ui
assert "document.addEventListener('click'" not in ui

print(json.dumps({'dailyCards':len(daily.get('items') or []),'peopleSignals':len(people.get('items') or []),'homePeople':len(people.get('homeIds') or []),'officialSources':len(official.get('sources') or [])},ensure_ascii=False,indent=2))
