#!/usr/bin/env python3
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'partener-eu' / 'ingest' / 'funding_tenders_reconcile.py'
spec = importlib.util.spec_from_file_location('funding_tenders_reconcile', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

FETCHED_AT = '2026-08-28T00:00:00+00:00'
RUN_ID = 'fixture-ft-reconcile-001'


def hjson(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def sem(identifier, call_identifier, title, programme, status, url, deadline, budget=None):
    return {
        'identifier': identifier,
        'call_identifier': call_identifier,
        'title': title,
        'programme': programme,
        'programme_period': '2021 - 2027',
        'status_label': status,
        'authority_url': url,
        'deadline': deadline,
        'budget': budget,
    }


def row(identifier, *, status='Open', deadline='2026-09-22T00:00:00+00:00', budget=None, conflict=False):
    url = mod._expected_topic_url(identifier)
    call_id = identifier.rsplit('-', 1)[0]
    semantic = sem(identifier, call_id, f'Title {identifier}', '43108390', status, url, deadline, budget)
    return {
        'schema': 'PARTENER_EU_FUNDING_TENDERS_EVIDENCE_V1',
        'source_family': 'EU_DIRECT',
        'programme_family': 'BRUSSELS',
        'authority_class': 'EU_COMMISSION_FUNDING_TENDERS',
        'identifier': identifier,
        'call_identifier': call_id,
        'title': semantic['title'],
        'programme': semantic['programme'],
        'programme_period': semantic['programme_period'],
        'raw_status': '31094502',
        'status_label': status,
        'observation_state': 'OPEN_CALL' if status == 'Open' else 'FORTHCOMING_CALL',
        'authority_url': url,
        'authority_url_verified': True,
        'deadline_candidate': deadline,
        'budget_candidate': budget,
        'material_fact_use': False,
        'publish_authorized': False,
        'requires_reconcile': conflict,
        'fetched_at': FETCHED_AT,
        'raw_hash': 'a' * 64,
        'semantic_fingerprint': hjson(semantic),
        'parser_version': 'FUNDING_TENDERS_STRUCTURED_V1',
        'run_id': RUN_ID,
    }


def main():
    direct = row('HORIZON-TEST-2026-01')
    future = row('DIGITAL-TEST-2026-02', status='Forthcoming', deadline='2026-12-15T00:00:00+00:00')
    cascade = row('DIGITAL-CASCADE-2026-03', conflict=True, deadline='2026-10-31T00:00:00+00:00', budget='100000')
    stale = row('ERASMUS-STALE-2026-04', deadline='2025-09-01T00:00:00+00:00')
    rows = [direct, future, cascade, stale]
    types = {
        direct['identifier']: '1',
        future['identifier']: '2',
        cascade['identifier']: '8',
        stale['identifier']: '1',
    }
    raw_payload = {'results': []}
    for r in rows:
        raw_payload['results'].append({'metadata': {
            'identifier': [r['identifier']],
            'callIdentifier': [r['call_identifier']],
            'type': [types[r['identifier']]],
            'status': ['31094502'],
        }})
    raw_payload['results'].append({'metadata': {
        'identifier': [cascade['identifier']],
        'type': ['8'],
        'status': ['31094502'],
        'deadlineDate': ['2026-11-01T00:00:00+00:00'],
    }})
    raw_bytes = json.dumps(raw_payload, ensure_ascii=False, separators=(',', ':')).encode()
    readbacks = {}
    for r in rows:
        readbacks[r['identifier']] = {
            'url': r['authority_url'],
            'final_url': r['authority_url'],
            'http_status': 200,
            'body_sha256': 'b' * 64,
            'verified': True,
        }
    evidence = {
        'schema': 'PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1',
        'source_family': 'EU_DIRECT',
        'authority_class': 'EU_COMMISSION_FUNDING_TENDERS',
        'fetched_at': FETCHED_AT,
        'run_id': RUN_ID,
        'search_receipt': {'http_status': 200, 'sha256': hashlib.sha256(raw_bytes).hexdigest()},
        'facet_receipts': {},
        'status_resolution': {'31094502': 'Open'},
        'authority_readbacks': readbacks,
        'batch': {
            'schema': 'PARTENER_EU_FUNDING_TENDERS_BATCH_V1',
            'records': rows,
            'conflicts': [{'identifier': cascade['identifier'], 'fingerprints': ['1' * 64, '2' * 64]}],
            'publication_effect': 'NONE',
        },
        'stats': {'normalized_records': 4, 'conflicts': 1},
        'material_fact_use': False,
        'publish_authorized': False,
        'publication_effect': 'NONE',
        'canonical_corpus_mutation': False,
    }
    receipt = mod.reconcile_live_evidence(
        evidence,
        raw_payload,
        search_raw_bytes=raw_bytes,
        reconciled_at='2026-08-28T00:01:00+00:00',
    )
    assert receipt['publish_authorized'] is False
    assert receipt['publication_effect'] == 'NONE'
    assert receipt['canonical_corpus_mutation'] is False
    assert receipt['stats']['ready_for_staging'] == 2
    assert {r['identifier'] for r in receipt['records']} == {direct['identifier'], future['identifier']}
    q = {r['identifier']: r for r in receipt['quarantined_records']}
    assert 'NON_DIRECT_OR_PORTAL_ONLY_CALL_TYPE' in q[cascade['identifier']]['reasons']
    assert 'SEMANTIC_CONFLICT' in q[cascade['identifier']]['reasons']
    assert 'STALE_DEADLINE_CONTRADICTS_OPEN' in q[stale['identifier']]['reasons']
    assert all(r['missing_proofs'] == ['CANONICAL_STAGING_ADMISSION', 'PUBLIC_PROJECTION_QUALITY_GATE'] for r in receipt['records'])

    bad = json.loads(json.dumps(evidence))
    bad['search_receipt']['sha256'] = '0' * 64
    try:
        mod.reconcile_live_evidence(bad, raw_payload, search_raw_bytes=raw_bytes)
    except ValueError as exc:
        assert 'hash' in str(exc).lower()
    else:
        raise AssertionError('Search response hash mismatch must fail closed')

    print('PASS Funding & Tenders reconcile: direct calls staged, type-8/conflicts/stale OPEN quarantined, zero publication')


if __name__ == '__main__':
    main()
