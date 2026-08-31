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
        'raw_status': '31094502' if status == 'Open' else '31094501',
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


def structured_readback(r):
    return {
        'identifier': r['identifier'],
        'query_text': f'"{r["identifier"]}"',
        'api_url': f'https://api.tech.ec.europa.eu/search-api/prod/rest/search?apiKey=SEDIA&text=%22{r["identifier"]}%22&pageSize=10&pageNumber=1',
        'http_status': 200,
        'content_type': 'application/json',
        'bytes': 321,
        'raw_sha256': 'c' * 64,
        'matched_identifiers': [r['identifier']],
        'exact_match_count': 1,
        'status_codes': [r['raw_status']],
        'call_identifiers': [r['call_identifier']],
        'raw_types': ['1'],
        'verified': True,
    }


def build_evidence(rows, raw_bytes, conflicts):
    readbacks = {}
    structured = {}
    for r in rows:
        readbacks[r['identifier']] = {
            'url': r['authority_url'],
            'final_url': r['authority_url'],
            'http_status': 200,
            'body_sha256': 'b' * 64,
            'verified': True,
        }
        structured[r['identifier']] = structured_readback(r)
    return {
        'schema': 'PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1',
        'source_family': 'EU_DIRECT',
        'authority_class': 'EU_COMMISSION_FUNDING_TENDERS',
        'fetched_at': FETCHED_AT,
        'run_id': RUN_ID,
        'search_receipt': {'http_status': 200, 'sha256': hashlib.sha256(raw_bytes).hexdigest()},
        'facet_receipts': {},
        'status_resolution': {'31094502': 'Open', '31094501': 'Forthcoming'},
        'authority_readbacks': readbacks,
        'structured_topic_readbacks': structured,
        'batch': {
            'schema': 'PARTENER_EU_FUNDING_TENDERS_BATCH_V1',
            'records': rows,
            'conflicts': conflicts,
            'publication_effect': 'NONE',
        },
        'stats': {'normalized_records': len(rows), 'conflicts': len(conflicts)},
        'material_fact_use': False,
        'publish_authorized': False,
        'publication_effect': 'NONE',
        'canonical_corpus_mutation': False,
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
            'status': [r['raw_status']],
        }})
    raw_payload['results'].append({'metadata': {
        'identifier': [cascade['identifier']],
        'type': ['8'],
        'status': ['31094502'],
        'deadlineDate': ['2026-11-01T00:00:00+00:00'],
    }})
    raw_bytes = json.dumps(raw_payload, ensure_ascii=False, separators=(',', ':')).encode()
    conflicts = [{'identifier': cascade['identifier'], 'fingerprints': ['1' * 64, '2' * 64]}]
    evidence = build_evidence(rows, raw_bytes, conflicts)

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
    assert receipt['stats']['structured_topic_mismatches'] == 0
    assert {r['identifier'] for r in receipt['records']} == {direct['identifier'], future['identifier']}
    assert all(r['evidence_basis'] == 'EC_SEARCH_FACET_PLUS_EXACT_STRUCTURED_TOPIC_AND_PAGE_READBACK' for r in receipt['records'])
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

    # HTML page reachability cannot rescue a structured status mismatch.
    mismatch = json.loads(json.dumps(evidence))
    mismatch['structured_topic_readbacks'][direct['identifier']]['status_codes'] = ['31094501']
    mismatch_receipt = mod.reconcile_live_evidence(
        mismatch,
        raw_payload,
        search_raw_bytes=raw_bytes,
        reconciled_at='2026-08-28T00:02:00+00:00',
    )
    mismatch_q = {r['identifier']: r for r in mismatch_receipt['quarantined_records']}
    assert direct['identifier'] in mismatch_q
    assert 'STRUCTURED_TOPIC_STATUS_MISMATCH' in mismatch_q[direct['identifier']]['reasons']
    assert mismatch_receipt['stats']['structured_topic_mismatches'] == 1

    missing_structured = json.loads(json.dumps(evidence))
    del missing_structured['structured_topic_readbacks'][future['identifier']]
    missing_receipt = mod.reconcile_live_evidence(
        missing_structured,
        raw_payload,
        search_raw_bytes=raw_bytes,
        reconciled_at='2026-08-28T00:03:00+00:00',
    )
    missing_q = {r['identifier']: r for r in missing_receipt['quarantined_records']}
    assert 'STRUCTURED_TOPIC_READBACK_NOT_VERIFIED' in missing_q[future['identifier']]['reasons']

    print('PASS Funding & Tenders reconcile: structured topic status + exact page required; direct calls staged; unsafe rows quarantined')


if __name__ == '__main__':
    main()
