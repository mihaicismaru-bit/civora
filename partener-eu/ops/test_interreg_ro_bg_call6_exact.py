#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import tempfile

from interreg_ro_bg_call6_exact import MATERIAL_FLAGS, collect, load_registry, reconcile, validate_registry

REGISTRY = pathlib.Path(__file__).resolve().parents[1] / "ingest" / "interreg_ro_bg_call6_exact_registry.json"

EXACT = b"""<html><body><h1>Call 6</h1><p>Launching date - 23rd of June 2025</p><p>The deadline for uploading applications in the Jems system is 22nd of December 2025, at 13:00 (EET).</p><p>Priority 1 - A well connected region, Specific Objective 3.2</p></body></html>"""
CLOSED = b"""<html><body><h1>Closed calls for proposals</h1><p>Call 6 - Call dedicated to the operations of strategic importance under Priority 1, Specific Objective 3.2</p></body></html>"""


def fake_fetch(url: str):
    raw = EXACT if "open-calls-for-proposals-call-6" in url else CLOSED
    return raw, {"requested_url": url, "final_url": url, "http_status": 200, "content_type": "text/html; charset=UTF-8"}


def run() -> None:
    registry = load_registry(REGISTRY)
    evidence1, _ = collect(registry=registry, run_id="test-1", fetched_at="2026-09-03T07:00:00+00:00", fetcher=fake_fetch)
    assert evidence1["source_health_state"] == "HEALTHY"
    assert evidence1["official_call_identifier"] == "6"
    assert evidence1["candidate_state"] == "CLOSED_CALL_CANDIDATE"
    assert evidence1["candidate_deadline_text"] == "22 December 2025, 13:00 EET"
    assert evidence1["territorial_relevance"]["programme_area_relevance_only"] is True
    assert evidence1["territorial_relevance"]["call_eligibility_authorized"] is False
    assert all(evidence1[key] is False for key in MATERIAL_FLAGS)
    baseline = reconcile(evidence1)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is False

    evidence2, _ = collect(registry=registry, run_id="test-2", fetched_at="2026-09-03T07:00:01+00:00", fetcher=fake_fetch)
    same = reconcile(evidence2, evidence1)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["material_admission_ready_for_downstream_review"] is True
    assert all(same[key] is False for key in MATERIAL_FLAGS)

    changed = copy.deepcopy(evidence2)
    changed["exact_semantics"]["candidate_deadline_text"] = "23 December 2025, 13:00 EET"
    from interreg_ro_bg_call6_exact import sha256_json
    changed["candidate_deadline_text"] = "23 December 2025, 13:00 EET"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    rec_changed = reconcile(changed, evidence1)
    assert rec_changed["reconciliation_state"] == "RO_BG_CALL6_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert rec_changed["semantic_change_count"] == 1
    assert rec_changed["publish_authorized"] is False

    try:
        reconcile(evidence1, evidence2)
    except ValueError as exc:
        assert "history inversion" in str(exc)
    else:
        raise AssertionError("history inversion must fail closed")

    bad_registry = copy.deepcopy(registry)
    bad_registry["policy"]["closed_call_authorized"] = True
    try:
        validate_registry(bad_registry)
    except ValueError as exc:
        assert "fail-closed" in str(exc)
    else:
        raise AssertionError("authorizing registry must be rejected")

    def missing_closed_call(url: str):
        raw = EXACT if "open-calls-for-proposals-call-6" in url else b"<html><body><h1>Closed calls for proposals</h1><p>Call 5</p></body></html>"
        return raw, {"requested_url": url, "final_url": url, "http_status": 200, "content_type": "text/html"}

    degraded, _ = collect(registry=registry, run_id="test-degraded", fetched_at="2026-09-03T07:00:02+00:00", fetcher=missing_closed_call)
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["lkg_required"] is True
    assert degraded["exact_semantic_fingerprint"] is None
    degraded_rec = reconcile(degraded, evidence2)
    assert degraded_rec["reconciliation_state"] == "CURRENT_SOURCE_DEGRADED_FAIL_CLOSED"
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_is_current_truth"] is False

    print(json.dumps({
        "unit": "INTERREG_RO_BG_CALL6_EXACT",
        "healthy_candidate": evidence2["candidate_state"],
        "same_identity_replay": same["reconciliation_state"],
        "degraded_missing_closed_index": degraded_rec["reconciliation_state"],
        "material_authorization": False,
    }, sort_keys=True))


if __name__ == "__main__":
    run()
