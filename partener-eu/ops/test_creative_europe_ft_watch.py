#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
MODULE = INGEST / "creative_europe_ft_watch.py"
spec = importlib.util.spec_from_file_location("creative_europe_ft_watch", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

RECONCILE_MODULE = INGEST / "creative_europe_ft_watch_reconcile.py"
reconcile_spec = importlib.util.spec_from_file_location("creative_europe_ft_watch_reconcile", RECONCILE_MODULE)
r = importlib.util.module_from_spec(reconcile_spec)
assert reconcile_spec and reconcile_spec.loader
reconcile_spec.loader.exec_module(r)

OPEN = "CREA-MEDIA-2026-DEVMINISLATE"
FORTHCOMING = "CREA-CULT-2027-COOP"
CONFLICT = "CREA-CROSS-2026-CONFLICT"

page1 = {
    "results": [
        {"metadata": {
            "identifier": [OPEN], "callIdentifier": ["CREA-MEDIA-2026"],
            "status": ["31094502"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"], "deadlineDate": ["2026-09-17"],
        }, "content": "European mini-slate development"},
        {"metadata": {
            "identifier": [CONFLICT], "callIdentifier": ["CREA-CROSS-2026"],
            "status": ["31094502"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Conflicting fixture"},
    ]
}
page2 = {
    "results": [
        {"metadata": {
            "identifier": [FORTHCOMING], "callIdentifier": ["CREA-CULT-2027"],
            "status": ["31094501"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"], "deadlineDate": ["2027-05-01"],
        }, "content": "Future cooperation projects"},
        {"metadata": {
            "identifier": [CONFLICT], "callIdentifier": ["CREA-CROSS-2026"],
            "status": ["99999999"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Conflicting fixture"},
        {"metadata": {
            "identifier": ["EAC/A03/2021"], "status": ["31094502"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Not Creative Europe structured topic"},
    ]
}
facet = {
    "facets": [{
        "name": "status",
        "values": [
            {"rawValue": "31094502", "value": "Open for submission"},
            {"rawValue": "31094501", "value": "Forthcoming"},
        ],
    }]
}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = page1 if page_number == 1 else page2 if page_number == 2 else {"results": []}
        raw = json.dumps(payload, sort_keys=True).encode()
        return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}
    raw = json.dumps(facet, sort_keys=True).encode()
    return facet, raw, {"url": endpoint, "http_status": 200, "sha256": "b" * 64}


e = m.collect_watch(
    run_id="fixture",
    fetched_at="2026-09-01T02:30:00+00:00",
    text="CREA-",
    page_size=2,
    max_pages=3,
    post_func=fake_post,
)
assert e["source_health"] == "HEALTHY"
assert e["open_call_authorized"] is False
assert e["stats"]["search_records"] == 5
assert e["stats"]["non_crea_records_excluded"] == 1
assert e["stats"]["explicit_crea_references_seen"] == 3
assert e["stats"]["exact_reference_candidates"] == 2
assert e["stats"]["conflicting_references_excluded"] == 1
assert [c["reference"] for c in e["candidates"]] == [OPEN, FORTHCOMING]
assert e["candidates"][0]["candidate_observation_state"] == "OPEN_CANDIDATE_NON_AUTHORIZING"
assert e["candidates"][1]["candidate_observation_state"] == "FORTHCOMING_CANDIDATE_NON_AUTHORIZING"
assert all(c["authority_url_verified"] is False for c in e["candidates"])
assert all(c["requires_exact_topic_readback"] is True for c in e["candidates"])

bad = dict(e)
bad["open_call_authorized"] = True
try:
    m.validate_watch_evidence(bad)
except ValueError:
    pass
else:
    raise AssertionError("programme watch self-authorized OPEN")

bad_candidate = json.loads(json.dumps(e))
bad_candidate["candidates"][0]["authority_url_verified"] = True
try:
    m.validate_watch_evidence(bad_candidate)
except ValueError:
    pass
else:
    raise AssertionError("programme watch claimed exact topic verification without readback")


def empty_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = {"results": []}
    else:
        payload = {"facets": []}
    raw = json.dumps(payload).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "c" * 64}


empty = m.collect_watch(
    run_id="empty",
    fetched_at="2026-09-01T02:30:00+00:00",
    post_func=empty_post,
)
assert empty["source_health"] == "DEGRADED_EMPTY_STRUCTURED_DISCOVERY"
assert empty["lkg_required"] is True
assert empty["stats"]["exact_reference_candidates"] == 0
assert empty["open_call_authorized"] is False

# Programme-watch semantic history + exact-verification prioritization.
CLOSED = "CREA-CULT-2026-CLOSED"
NEW = "CREA-CROSS-2027-NEW"
STATUS_LABELS = {
    "31094502": "Open for submission",
    "31094501": "Forthcoming",
    "31094503": "Closed",
}


def record(reference: str, status: str, *, deadline: str | None = None):
    metadata = {
        "identifier": [reference],
        "callIdentifier": ["-".join(reference.split("-")[:-1])],
        "status": [status],
        "programAbbreviation": ["CREA"],
        "programmePeriod": ["2021 - 2027"],
    }
    if deadline:
        metadata["deadlineDate"] = [deadline]
    return {"metadata": metadata, "content": reference}


def make_watch(run_id: str, fetched_at: str, rows: list[dict]):
    search = {"results": rows}
    facet_payload = {
        "facets": [{
            "name": "status",
            "values": [
                {"rawValue": code, "value": label}
                for code, label in STATUS_LABELS.items()
            ],
        }]
    }

    def post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
        payload = search if "search" in endpoint and "facet" not in endpoint else facet_payload
        raw = json.dumps(payload, sort_keys=True).encode()
        return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "d" * 64}

    return m.collect_watch(
        run_id=run_id,
        fetched_at=fetched_at,
        page_size=50,
        max_pages=1,
        post_func=post,
    )


previous = make_watch(
    "previous-watch",
    "2026-09-01T03:00:00+00:00",
    [
        record(OPEN, "31094502", deadline="2026-09-17"),
        record(CLOSED, "31094503", deadline="2026-01-15"),
    ],
)

baseline = r.reconcile_watch(previous, reconciled_at="2026-09-01T03:01:00Z")
assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
assert baseline["semantic_change_count"] == 0
assert [q["reference"] for q in baseline["exact_verification_queue"]] == [OPEN]
assert baseline["programme_watch_candidate"] is False
assert baseline["open_call_authorized"] is False

same = make_watch(
    "same-watch",
    "2026-09-01T04:00:00+00:00",
    [
        record(OPEN, "31094502", deadline="2026-09-17"),
        record(CLOSED, "31094503", deadline="2026-01-15"),
    ],
)
no_change = r.reconcile_watch(same, previous, reconciled_at="2026-09-01T04:01:00Z")
assert no_change["reconciliation_state"] == "NO_CHANGE"
assert no_change["semantic_change_count"] == 0
assert no_change["exact_verification_queue"] == []
assert no_change["programme_watch_candidate"] is False

changed = make_watch(
    "changed-watch",
    "2026-09-01T05:00:00+00:00",
    [
        record(OPEN, "31094503", deadline="2026-09-17"),
        record(CLOSED, "31094503", deadline="2026-01-15"),
        record(NEW, "31094501", deadline="2027-02-01"),
    ],
)
changed_receipt = r.reconcile_watch(changed, previous, reconciled_at="2026-09-01T05:01:00Z")
assert changed_receipt["reconciliation_state"] == "PROGRAMME_WATCH_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
assert changed_receipt["added_references"] == [NEW]
assert changed_receipt["changed_references"] == [OPEN]
assert changed_receipt["semantic_change_count"] == 2
assert changed_receipt["programme_watch_candidate"] is True
assert [q["reference"] for q in changed_receipt["exact_verification_queue"]] == [NEW, OPEN]
assert all(q["authority_url_verified"] is False for q in changed_receipt["exact_verification_queue"])
assert all(q["requires_exact_topic_readback"] is True for q in changed_receipt["exact_verification_queue"])

removed = make_watch(
    "removed-watch",
    "2026-09-01T06:00:00+00:00",
    [record(CLOSED, "31094503", deadline="2026-01-15")],
)
removed_receipt = r.reconcile_watch(removed, previous, reconciled_at="2026-09-01T06:01:00Z")
assert removed_receipt["removed_references"] == [OPEN]
assert [q["reference"] for q in removed_receipt["exact_verification_queue"]] == [OPEN]
assert removed_receipt["exact_verification_queue"][0]["reason"] == "PRIORITY_REFERENCE_DISAPPEARED"

current_degraded = m.collect_watch(
    run_id="current-degraded",
    fetched_at="2026-09-01T07:00:00+00:00",
    post_func=empty_post,
)
degraded_receipt = r.reconcile_watch(current_degraded, previous, reconciled_at="2026-09-01T07:01:00Z")
assert degraded_receipt["reconciliation_state"] == "CURRENT_SOURCE_DEGRADED_LKG_REFERENCED_NON_AUTHORIZING"
assert degraded_receipt["lkg_reference_available"] is True
assert degraded_receipt["lkg_material_fact_use"] is False
assert degraded_receipt["exact_verification_queue"] == []
assert degraded_receipt["programme_watch_candidate"] is False
assert degraded_receipt["source_health_watch_candidate"] is True

recovered = r.reconcile_watch(same, empty, reconciled_at="2026-09-01T04:01:00Z")
assert recovered["reconciliation_state"] == "SOURCE_RECOVERED_BASELINE_REESTABLISHED_NON_AUTHORIZING"
assert [q["reference"] for q in recovered["exact_verification_queue"]] == [OPEN]
assert recovered["programme_watch_candidate"] is False
assert recovered["source_health_watch_candidate"] is True

scope_drift = copy.deepcopy(previous)
scope_drift["search_text"] = "CREA-MEDIA"
try:
    r.reconcile_watch(same, scope_drift, reconciled_at="2026-09-01T04:01:00Z")
except ValueError:
    pass
else:
    raise AssertionError("programme-watch reconciliation accepted changed search scope")

tampered = copy.deepcopy(previous)
tampered["candidates"][0]["status_label_candidate"] = "Closed"
try:
    r.reconcile_watch(same, tampered, reconciled_at="2026-09-01T04:01:00Z")
except ValueError:
    pass
else:
    raise AssertionError("programme-watch reconciliation accepted tampered candidate semantics")

future_previous = copy.deepcopy(previous)
future_previous["fetched_at"] = "2026-09-01T08:00:00+00:00"
try:
    r.reconcile_watch(same, future_previous, reconciled_at="2026-09-01T08:01:00Z")
except ValueError:
    pass
else:
    raise AssertionError("programme-watch reconciliation accepted previous evidence newer than current")

bad_receipt = copy.deepcopy(changed_receipt)
bad_receipt["open_call_authorized"] = True
try:
    r.validate_watch_reconciliation(bad_receipt)
except ValueError:
    pass
else:
    raise AssertionError("programme-watch reconciliation self-authorized OPEN")

print("PASS Creative Europe programme-wide structured F&T watch + semantic history stay non-authorizing")
