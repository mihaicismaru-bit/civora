#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import sys
import tempfile
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

PARENT = "CREA-CULT-2026-PERFORM-EU"
CID = "49521170"
URL = exact.competitive_url(CID)
STATUS = "31094502"

SEARCH = {
    "results": [{
        "metadata": {
            "identifier": [PARENT],
            "callIdentifier": [PARENT],
            "status": [STATUS],
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
FACET = {
    "facets": [{
        "name": "status",
        "values": [{"rawValue": STATUS, "value": "Open for submission"}],
    }]
}


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
with tempfile.TemporaryDirectory() as tmp:
    current = exact.collect_exact(
        PARENT,
        CID,
        run_id="competitive-current",
        fetched_at="2026-09-01T08:10:00+00:00",
        output_dir=Path(tmp),
        source_candidate=source_candidate,
        post_func=fake_post,
        readback_func=fake_readback,
    )
    assert current["identity_key"] == f"FUNDING_TENDERS_COMPETITIVE_CALL:{CID}"
    assert current["candidate_observation_state"] == "OPEN_CALL"
    assert current["status_label"] == "Open"
    assert current["authority_url_verified"] is True
    assert current["deadline_candidate"].startswith("2026-10-22")
    assert current["source_candidate_semantic_fingerprint"] == "c" * 64
    assert current["open_call_authorized"] is False
    assert current["call_alert_authorized"] is False
    assert (Path(tmp) / "ft-competitive-exact-evidence.json").is_file()

baseline = reconcile.reconcile(current, reconciled_at="2026-09-01T08:11:00Z")
assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
assert baseline["material_admission_ready_for_downstream_review"] is True
assert baseline["open_call_authorized"] is False
assert baseline["call_alert_authorized"] is False

previous = copy.deepcopy(current)
previous["run_id"] = "competitive-previous"
previous["fetched_at"] = "2026-09-01T07:10:00+00:00"
no_change = reconcile.reconcile(current, previous, reconciled_at="2026-09-01T08:12:00Z")
assert no_change["reconciliation_state"] == "NO_CHANGE"
assert no_change["semantic_change_count"] == 0

changed = copy.deepcopy(current)
changed["status_code"] = "31094503"
changed["status_label"] = "Closed"
changed["candidate_observation_state"] = "CLOSED_CALL"
semantic = {key: changed.get(key) for key in reconcile.SEMANTIC_FIELDS}
changed["semantic_fingerprint"] = exact.sha256_bytes(exact.canonical_json(semantic))
change_receipt = reconcile.reconcile(changed, current, reconciled_at="2026-09-01T09:10:00Z")
assert change_receipt["reconciliation_state"] == "EXACT_COMPETITIVE_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
assert change_receipt["semantic_change_count"] == 3
assert change_receipt["material_admission_ready_for_downstream_review"] is False
assert change_receipt["open_call_authorized"] is False

bad = copy.deepcopy(current)
bad["open_call_authorized"] = True
try:
    exact.validate_exact_evidence(bad)
except ValueError:
    pass
else:
    raise AssertionError("competitive exact evidence self-authorized OPEN")

try:
    exact.validate_competitive_id("../49521170")
except ValueError:
    pass
else:
    raise AssertionError("unsafe competitive id accepted")

# Materially conflicting exact type-8 records remain fail-closed.
def conflict_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = copy.deepcopy(SEARCH)
        second = copy.deepcopy(SEARCH["results"][0])
        second["metadata"]["deadlineDate"] = ["2026-11-01T23:59:00.000+0000"]
        payload["results"].append(second)
    else:
        payload = FACET
    raw = json.dumps(payload, sort_keys=True).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "d" * 64}

with tempfile.TemporaryDirectory() as tmp:
    try:
        exact.collect_exact(
            PARENT,
            CID,
            run_id="competitive-conflict",
            fetched_at="2026-09-01T08:20:00+00:00",
            output_dir=Path(tmp),
            post_func=conflict_post,
            readback_func=fake_readback,
        )
    except exact.CompetitiveRecordConflict as exc:
        diagnostic = exc.diagnostic
    else:
        raise AssertionError("competitive exact conflict did not fail closed")
    assert diagnostic["decision"] == "MATERIAL_CONFLICT_REJECTED"
    assert "deadline_candidate" in diagnostic["conflict_fields"]
    assert diagnostic["authority_url_verified"] is False
    assert diagnostic["open_call_authorized"] is False
    assert (Path(tmp) / "ft-competitive-exact-conflict.json").is_file()

print("PASS Creative Europe exact competitive-call + identity-keyed reconcile stays non-authorizing")
