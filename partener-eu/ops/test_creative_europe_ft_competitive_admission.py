#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))


def load(name: str):
    path = INGEST / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


exact = load("creative_europe_ft_competitive_exact")
reconcile = load("creative_europe_ft_competitive_reconcile")
admission = load("creative_europe_ft_competitive_admission")

PARENT = "CREA-CULT-2026-PERFORM-EU"
CID = "49521170"
URL = exact.competitive_url(CID)
OPEN = "31094502"
CLOSED = "31094503"

SEARCH = {
    "results": [{
        "metadata": {
            "identifier": [PARENT],
            "callIdentifier": [PARENT],
            "status": [OPEN],
            "type": ["8"],
            "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
            "deadlineDate": ["2026-10-22T23:59:00.000+0000"],
            "budget": ["1400000"],
            "esST_URL": [URL],
        },
        "content": "Perform EU",
        "url": URL,
    }]
}
FACET = {"facets": [{"name": "status", "values": [
    {"rawValue": OPEN, "value": "Open for submission"},
    {"rawValue": CLOSED, "value": "Closed"},
]}]}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    payload = SEARCH if "search" in endpoint and "facet" not in endpoint else FACET
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}


def fake_readback(url, *, max_bytes=None, opener=None):
    assert url == URL
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 64,
        "body_sha256": "b" * 64,
        "verified": True,
    }


source_candidate = {
    "identity_key": f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}",
    "parent_reference": PARENT,
    "semantic_fingerprint": "c" * 64,
}
current = exact.collect_exact(
    PARENT,
    CID,
    run_id="competitive-admission-current",
    fetched_at="2026-09-01T09:00:00+00:00",
    source_candidate=source_candidate,
    post_func=fake_post,
    readback_func=fake_readback,
)
baseline = reconcile.reconcile(current, reconciled_at="2026-09-01T09:01:00Z")
receipt = admission.admit_status(current, baseline, admitted_at="2026-09-01T09:02:00Z")
assert receipt["material_admission_scope"] == "STATUS_ONLY"
assert receipt["material_fact_use"] is True
assert receipt["material_fact_use_scope"] == ["status"]
assert receipt["status_fact_authorized"] is True
assert receipt["open_call_authorized"] is True
assert receipt["deadline_authorized"] is False
assert receipt["budget_authorized"] is False
assert receipt["eligibility_authorized"] is False
assert receipt["publish_authorized"] is False
assert receipt["distribution_authorized"] is False
assert receipt["call_alert_authorized"] is False
assert receipt["distribution_change_candidate"] is False
assert receipt["publication_effect"] == "NONE"
assert receipt["canonical_corpus_mutation"] is False
assert receipt["withheld_material_candidates"]["deadline_candidate"].startswith("2026-10-22")
assert receipt["withheld_material_candidates"]["budget_candidate"] == "1400000"

previous_closed = copy.deepcopy(current)
previous_closed["run_id"] = "competitive-admission-previous"
previous_closed["fetched_at"] = "2026-09-01T08:00:00+00:00"
previous_closed["status_code"] = CLOSED
previous_closed["status_label"] = "Closed"
previous_closed["candidate_observation_state"] = "CLOSED_CALL"
previous_semantic = {key: previous_closed.get(key) for key in reconcile.SEMANTIC_FIELDS}
previous_closed["semantic_fingerprint"] = exact.sha256_bytes(exact.canonical_json(previous_semantic))
change = reconcile.reconcile(current, previous_closed, reconciled_at="2026-09-01T09:03:00Z")
changed_receipt = admission.admit_status(current, change, admitted_at="2026-09-01T09:04:00Z")
assert changed_receipt["distribution_change_candidate"] is True
assert changed_receipt["open_call_authorized"] is True
assert changed_receipt["call_alert_authorized"] is False
assert changed_receipt["distribution_authorized"] is False

tampered = copy.deepcopy(baseline)
tampered["current_evidence_sha256"] = "d" * 64
try:
    admission.admit_status(current, tampered, admitted_at="2026-09-01T09:05:00Z")
except ValueError:
    pass
else:
    raise AssertionError("competitive admission accepted unbound reconciliation")

closed_current = copy.deepcopy(current)
closed_current["run_id"] = "competitive-admission-closed"
closed_current["fetched_at"] = "2026-09-01T10:00:00+00:00"
closed_current["status_code"] = CLOSED
closed_current["status_label"] = "Closed"
closed_current["candidate_observation_state"] = "CLOSED_CALL"
closed_semantic = {key: closed_current.get(key) for key in reconcile.SEMANTIC_FIELDS}
closed_current["semantic_fingerprint"] = exact.sha256_bytes(exact.canonical_json(closed_semantic))
closed_receipt = reconcile.reconcile(closed_current, current, reconciled_at="2026-09-01T10:01:00Z")
assert closed_receipt["material_admission_ready_for_downstream_review"] is False
try:
    admission.admit_status(closed_current, closed_receipt, admitted_at="2026-09-01T10:02:00Z")
except ValueError:
    pass
else:
    raise AssertionError("competitive admission authorized non-OPEN current evidence")

broadened = copy.deepcopy(receipt)
broadened["deadline_authorized"] = True
try:
    admission.validate_admission(broadened)
except ValueError:
    pass
else:
    raise AssertionError("competitive admission allowed deadline authorization")

print("PASS Creative Europe competitive status-only material admission stays non-publishing and field-scoped")
