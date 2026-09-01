#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import runpy
import sys
import tempfile
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
MODULE = INGEST / "creative_europe_ft_exact.py"
spec = importlib.util.spec_from_file_location("creative_europe_ft_exact", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

REF = "CREA-MEDIA-2026-DEVMINISLATE"

search_payload = {
    "results": [{
        "metadata": {
            "identifier": [REF],
            "callIdentifier": ["CREA-MEDIA-2026"],
            "status": ["31094502"],
            "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
            "deadlineDate": ["2026-09-17"],
        },
        "content": "European mini-slate development",
    }]
}
facet_payload = {
    "facets": [{
        "name": "status",
        "values": [{"rawValue": "31094502", "value": "Open for submission"}],
    }]
}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        raw = json.dumps(search_payload).encode()
        return search_payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}
    raw = json.dumps(facet_payload).encode()
    return facet_payload, raw, {"url": endpoint, "http_status": 200, "sha256": "b" * 64}


def fake_topic(url, *, max_bytes=None, opener=None):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": "c" * 64,
        "verified": True,
    }


e = m.collect_exact(
    REF,
    run_id="fixture",
    fetched_at="2026-08-31T18:00:00+00:00",
    post_func=fake_post,
    topic_func=fake_topic,
)
assert e["reference"] == REF
assert e["status_label"] == "Open"
assert e["candidate_observation_state"] == "OPEN_CALL"
assert e["open_call_authorized"] is False
assert e["requires_reconcile"] is True
assert e["authority_url_verified"] is True
assert e["excluded_linked_competitive_record_count"] == 0
assert e["linked_competitive_evidence_sha256"] is None

bad = dict(e)
bad["open_call_authorized"] = True
try:
    m.validate_exact_evidence(bad)
except ValueError:
    pass
else:
    raise AssertionError("exact F&T evidence self-authorized OPEN")

try:
    m.validate_reference("EAC/A03/2021")
except ValueError:
    pass
else:
    raise AssertionError("non-CREA reference accepted")


def conflicting_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = {"results": [
            search_payload["results"][0],
            {"metadata": {**search_payload["results"][0]["metadata"], "status": ["99999999"]}},
        ]}
        return payload, json.dumps(payload).encode(), {"url": endpoint, "http_status": 200, "sha256": "d" * 64}
    return fake_post(endpoint, text=text, page_size=page_size, page_number=page_number, parts=parts)


with tempfile.TemporaryDirectory() as tmp:
    output = Path(tmp)
    try:
        m.collect_exact(
            REF,
            run_id="conflict",
            fetched_at="2026-08-31T19:00:00+00:00",
            output_dir=output,
            post_func=conflicting_post,
            topic_func=fake_topic,
        )
    except m.ExactRecordConflict as exc:
        diagnostic = exc.diagnostic
    else:
        raise AssertionError("conflicting primary exact records did not fail closed")

    assert diagnostic["schema"] == m.CONFLICT_SCHEMA
    assert diagnostic["observation_state"] == m.CONFLICT_STATE
    assert diagnostic["reference"] == REF
    assert diagnostic["candidate_count"] == 2
    assert diagnostic["unique_material_signature_count"] == 2
    assert diagnostic["semantic_equivalence_proven"] is False
    assert diagnostic["decision"] == "MATERIAL_CONFLICT_REJECTED"
    assert diagnostic["conflict_fields"] == ["status_code"]
    assert diagnostic["authority_url_verified"] is False
    assert diagnostic["open_call_authorized"] is False
    assert diagnostic["requires_exact_topic_recheck"] is True
    assert diagnostic["requires_semantic_reconcile"] is True
    assert diagnostic["requires_material_admission"] is True
    m.validate_conflict_diagnostic(diagnostic)

    conflict_path = output / "ft-exact-conflict.json"
    search_path = output / "ft-search-response.json"
    assert conflict_path.is_file()
    assert search_path.is_file()
    persisted = json.loads(conflict_path.read_text(encoding="utf-8"))
    m.validate_conflict_diagnostic(persisted)
    assert persisted["search_raw_sha256"] == m.sha256_bytes(search_path.read_bytes())

    tampered = dict(persisted)
    tampered["open_call_authorized"] = True
    try:
        m.validate_conflict_diagnostic(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("conflict diagnostic self-authorized OPEN")

# F&T may return a type-8 competitive/cascading call that intentionally reuses
# the parent topic identifier. It is distinct source intelligence, not a second
# primary-topic truth row, and must not create a false exact-topic conflict.
PERFORM = "CREA-CULT-2026-PERFORM-EU"
PRIMARY_URL = m.ft.topic_url(PERFORM)
competitive_search = {
    "results": [
        {
            "metadata": {
                "identifier": [PERFORM],
                "callIdentifier": [PERFORM],
                "status": ["31094503"],
                "type": ["1"],
                "programmePeriod": ["2021 - 2027"],
                "deadlineDate": ["2026-01-15T00:00:00.000+0000"],
                "budgetOverview": ["{\"budgetTopicActionMap\":{\"x\":[]}}"],
                "esST_URL": [PRIMARY_URL],
            },
            "url": PRIMARY_URL,
            "content": "Perform EU",
        },
        {
            "metadata": {
                "identifier": [PERFORM],
                "status": ["31094502"],
                "type": ["8"],
                "programmePeriod": ["2021 - 2027"],
                "deadlineDate": ["2026-10-22T23:59:00.000+0000"],
                "budget": ["1400000"],
                "esST_URL": ["https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/competitive-calls-cs/49521170"],
            },
            "url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/competitive-calls-cs/49521170",
            "content": "Open Call of Perform Europe 2026-2028",
        },
    ]
}
competitive_facet = {
    "facets": [{
        "name": "status",
        "values": [
            {"rawValue": "31094502", "value": "Open for submission"},
            {"rawValue": "31094503", "value": "Closed"},
        ],
    }]
}


def competitive_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    payload = competitive_search if "search" in endpoint and "facet" not in endpoint else competitive_facet
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "e" * 64}


with tempfile.TemporaryDirectory() as tmp:
    output = Path(tmp)
    separated = m.collect_exact(
        PERFORM,
        run_id="linked-competitive",
        fetched_at="2026-09-01T06:50:00+00:00",
        output_dir=output,
        post_func=competitive_post,
        topic_func=fake_topic,
    )
    assert separated["reference"] == PERFORM
    assert separated["candidate_observation_state"] == "CLOSED_CALL"
    assert separated["status_label"] == "Closed"
    assert separated["excluded_linked_competitive_record_count"] == 1
    assert separated["linked_competitive_evidence_sha256"]
    assert separated["open_call_authorized"] is False
    linked_path = output / "ft-linked-competitive-records.json"
    assert linked_path.is_file()
    linked = json.loads(linked_path.read_text(encoding="utf-8"))
    m.validate_linked_competitive_evidence(linked)
    assert linked["parent_reference"] == PERFORM
    assert linked["record_count"] == 1
    assert linked["records"][0]["material"]["structured_type"] == "8"
    assert linked["records"][0]["material"]["deadline_candidate"].startswith("2026-10-22")
    assert linked["requires_separate_competitive_call_adapter"] is True
    assert linked["open_call_authorized"] is False

# Reuse the existing exact-topic regression lane to exercise the dedicated
# competitive/cascading adapter and identity-keyed reconciler as one bounded gate.
runpy.run_path(str(Path(__file__).with_name("test_creative_europe_ft_competitive.py")), run_name="__main__")

print("PASS Creative Europe exact F&T topic/cascade separation + competitive exact boundary regression")
