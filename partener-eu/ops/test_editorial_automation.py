#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import importlib.util
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

spec = importlib.util.spec_from_file_location('partener_daily_brief', ROOT / 'partener-eu' / 'ingest' / 'build_daily_brief.py')
assert spec and spec.loader
brief = importlib.util.module_from_spec(spec)
spec.loader.exec_module(brief)

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

# Pure regression fixture: the homepage brief must replay deterministically and
# must not promote stale news or ambiguous/expired OPEN dossiers.
def qf(label: str, value: str, confidence: str = 'CONFIRMED') -> dict[str, str]:
    return {'label': label, 'value': value, 'confidence': confidence}

fixed_now = dt.datetime(2026, 8, 26, 12, 0, tzinfo=brief.TZ)
assert brief.human_date('30 septembrie 2026, 16:00') == '30 septembrie 2026, 16:00'
clock_probe = {
    'id': 'clock-probe', 'status': 'OPEN', 'publicationState': 'PUBLISHABLE',
    'quickFacts': [qf('Status', 'DESCHIS'), qf('Termen', '30 septembrie 2026, 16:00')],
}
assert brief.is_current_open(clock_probe, dt.datetime(2026, 9, 30, 15, 59, tzinfo=brief.TZ)) is True
assert brief.is_current_open(clock_probe, dt.datetime(2026, 9, 30, 16, 1, tzinfo=brief.TZ)) is False

fixture = {
    'news': [
        {
            'id': 'fresh-news', 'kind': 'GUIDE_MODIFIED', 'programme': 'TEST',
            'headline': 'Ghid modificat recent', 'standfirst': 'Actualizare oficială recentă pentru testul de freshness.',
            'meaning': 'Trebuie reverificată documentația.', 'actions': ['Compară versiunile.'],
            'date': '2026-08-25T12:00:00+03:00', 'utilityScore': 90,
        },
        {
            'id': 'stale-2023', 'kind': 'CONSULTATION_OPENED', 'programme': 'TEST OLD',
            'headline': 'Calendarul fondurilor europene 2023', 'standfirst': 'Eveniment istoric care nu are voie pe suprafața Ce este nou.',
            'meaning': 'Doar referință istorică.', 'actions': ['Nu promova pe homepage.'],
            'date': '2023-01-20', 'utilityScore': 100,
        },
    ],
    'dossiers': [
        {
            'id': 'open-valid', 'status': 'OPEN', 'publicationState': 'PUBLISHABLE', 'programme': 'VALID',
            'title': 'Apel deschis valid', 'quality': {'completeness': 100},
            'quickFacts': [qf('Status', 'DESCHIS'), qf('Termen', '2026-09-05')],
        },
        {
            'id': 'open-expired', 'status': 'OPEN', 'publicationState': 'PUBLISHABLE', 'programme': 'EXPIRED',
            'title': 'Apel expirat', 'quality': {'completeness': 100},
            'quickFacts': [qf('Status', 'DESCHIS'), qf('Termen', '2026-08-20')],
        },
        {
            'id': 'open-undated', 'status': 'OPEN', 'publicationState': 'PUBLISHABLE', 'programme': 'UNDATED',
            'title': 'Apel fără termen confirmat', 'quality': {'completeness': 100},
            'quickFacts': [qf('Status', 'DESCHIS'), qf('Termen', 'Neconfirmat', 'UNKNOWN')],
        },
        {
            'id': 'open-provisional', 'status': 'OPEN', 'publicationState': 'PROVISIONAL_FAIL_CLOSED', 'programme': 'PROVISIONAL',
            'title': 'Apel provizoriu', 'quality': {'completeness': 100},
            'quickFacts': [qf('Status', 'DESCHIS'), qf('Termen', '2026-09-10')],
        },
        {
            'id': 'consult-current', 'status': 'PUBLIC_CONSULTATION', 'publicationState': 'PUBLISHABLE', 'programme': 'CONSULT',
            'title': 'Consultare 2026', 'quality': {'completeness': 80},
            'quickFacts': [qf('Status', 'ÎN CONSULTARE'), qf('Termen', '2026-09-15')],
        },
    ],
}
replay_a = brief.build_brief(fixture, fixed_now)
replay_b = brief.build_brief(fixture, fixed_now)
assert replay_a == replay_b, 'daily brief replay must be deterministic for the same payload and clock'
selected = {item['id'] for item in replay_a['items']}
assert 'brief-news-fresh-news' in selected
assert 'brief-news-stale-2023' not in selected
assert 'brief-dossier-open-valid' in selected
assert 'brief-dossier-open-expired' not in selected
assert 'brief-dossier-open-undated' not in selected
assert 'brief-dossier-open-provisional' not in selected
assert replay_a['policy']['newsMaxAgeHours'] == brief.NEWS_MAX_AGE_HOURS
assert replay_a['policy']['undatedOpenExcluded'] is True
assert replay_a['policy']['provisionalOpenExcluded'] is True
assert replay_a['policy']['currentPrepareEvidenceRequired'] is True

assert official.get('policy', {}).get('directOfficialOnly') is True
assert official.get('policy', {}).get('signalsDoNotChangeCalls') is True
assert official.get('policy', {}).get('failClosed') is True
sources = official.get('sources') or []
assert len(sources) >= 6
source_ids = {x.get('id') for x in sources}
assert {'GOV_RO_NEWS','EC_RO_NEWS','MS_PRESS','ANC_COMMUNICATES','ADR_ARTICLES','FED_MAI'} <= source_ids
for source in sources:
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

print(json.dumps({
    'dailyCards':len(daily.get('items') or []),
    'dailyFreshnessReplay':'PASS',
    'explicitDeadlineClock':'PASS',
    'newsMaxAgeHours':brief.NEWS_MAX_AGE_HOURS,
    'peopleSignals':len(people.get('items') or []),
    'homePeople':len(people.get('homeIds') or []),
    'officialSources':len(sources),
},ensure_ascii=False,indent=2))
