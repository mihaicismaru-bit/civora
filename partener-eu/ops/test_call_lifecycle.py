#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DECISION = json.loads((ROOT / 'partener-eu/ingest/state/decision_products.json').read_text(encoding='utf-8'))
LIFECYCLE = json.loads((ROOT / 'partener-eu/ingest/state/call_lifecycle.json').read_text(encoding='utf-8'))

stages = ['DISCOVERED','CONSULTATION','FINAL_GUIDE','ANNOUNCED','OPEN','CLOSED','EVALUATION','RESULTS','CONTRACTING','COMPLETED']
rank = {s:i for i,s in enumerate(stages)}
assert LIFECYCLE.get('policy',{}).get('lifecycleFirst') is True
assert LIFECYCLE.get('policy',{}).get('consultantIsDownstreamConsumer') is True
assert LIFECYCLE.get('policy',{}).get('winnerListsRequireExplicitOfficialEvidence') is True
assert len(LIFECYCLE.get('calls') or []) == len(DECISION.get('dossiers') or []), 'every dossier must have lifecycle state'
ids = {d['id'] for d in DECISION['dossiers']}
assert {c['dossierId'] for c in LIFECYCLE['calls']} == ids
for call in LIFECYCLE['calls']:
    assert call['stage'] in rank
    assert call['maturityRank'] == rank[call['stage']]
    assert call.get('stageLabel')
    monitoring = call.get('monitoring') or {}
    assert monitoring.get('failClosed') is True
    assert isinstance(monitoring.get('nextExpectedEvents'), list) and monitoring['nextExpectedEvents']
    assert monitoring.get('active') is (call['stage'] != 'COMPLETED')
    results = call.get('results') or {}
    if results.get('winnerListConfirmed'):
        assert results.get('winnerSources'), 'winner list cannot be confirmed without official source'
    if results.get('mysmis'):
        assert float(results['mysmis'].get('matchConfidence') or 0) >= .72
        assert 'nu reprezintă o listă nominală' in results['mysmis'].get('note','')
    transitions = call.get('transitions') or []
    assert transitions
    for a,b in zip(transitions, transitions[1:]):
        if a.get('to') in rank and b.get('to') in rank:
            assert rank[b['to']] >= rank[a['to']], f"lifecycle regressed for {call['dossierId']}"
summary = LIFECYCLE.get('summary') or {}
assert summary.get('callCount') == len(LIFECYCLE['calls'])
print(json.dumps(summary, ensure_ascii=False, indent=2))
print('Call lifecycle regression: PASS')
