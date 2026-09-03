#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
import mff_2028_2034_programming_pipeline as adapter
import mff_2028_2034_programming_pipeline_reconcile as reconciler

REGISTRY = pathlib.Path(__file__).resolve().parents[1] / "ingest" / "mff_2028_2034_programming_pipeline_registry.json"


def fake_fetch(url: str, *, suffix: str = ""):
    mapping = {
        "eu-budget-2028-2034_en": "2028-2034 Multiannual Financial Framework European Competitiveness Fund Erasmus+ Horizon Europe presented proposal",
        "european-competitiveness-fund_en": "European Competitiveness Fund Proposal for a Regulation COM_2025_555_1 17 July 2025",
        "horizon-europe_en": "Horizon Europe Proposal for a Regulation COM_2025_543_1 17 July 2025",
        "erasmus_en": "Erasmus+ Proposal for a Regulation COM_2025_549_1 18 July 2025",
        "connecting-europe-facility_en": "Connecting Europe Facility Proposal for a Regulation COM_2025_547_1 17 July 2025",
        "single-market-and-customs-programme_en": "Single Market and Customs Programme Proposal for a Regulation COM_2025_590_1 3 September 2025",
        "boost-eu-s-competitiveness": "MFF 2028-2034 European Competitiveness Fund partial negotiating position single application gateway",
        "key-eu-priorities": "MFF 2028-2034 national and regional partnership plans cohesion agriculture fisheries migration and security",
        "cohesion-funds": "MFF 2028-2034 cohesion European Territorial Cooperation Interreg European Social Fund ERDF",
    }
    text = None
    for needle, value in mapping.items():
        if needle in url:
            text = value
            break
    if text is None:
        raise AssertionError(url)
    body = f"<html><body>{text} {suffix}</body></html>".encode()
    return body, {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=UTF-8",
    }


def main() -> None:
    registry, _ = adapter.load_registry(REGISTRY)
    assert len(registry["sources"]) == 9
    current, raw = adapter.acquire(
        registry,
        run_id="mff-test-1",
        fetched_at="2026-09-03T18:00:00Z",
        fetcher=fake_fetch,
    )
    assert current["schema"] == adapter.SCHEMA
    assert current["parser_version"] == adapter.PARSER_VERSION
    assert current["source_family"] == "PROGRAMMING_PIPELINE"
    assert current["programme_family"] == "MFF_2028_2034"
    assert current["observation_state"] == "PROGRAMMING_PIPELINE"
    assert current["source_count"] == 9 and len(raw) == 9
    assert current["healthy_source_count"] == 9 and current["degraded_source_count"] == 0
    assert current["source_health_state"] == "HEALTHY" and current["lkg_required"] is False
    assert len(current["semantic_fingerprint"]) == 64
    assert {row["observation_state"] for row in current["sources"]} == {"PROPOSAL", "PROGRAMMING_PROCESS"}
    assert all(row["fit_is_not_eligibility"] is True for row in current["sources"])
    assert all(0.0 <= row["romania_relevance_score"] <= 1.0 for row in current["sources"])
    assert any(row["romania_relevance_score"] >= 0.9 for row in current["sources"])
    for row in current["sources"]:
        assert row["source_health"] == "HEALTHY" and row["http_status"] == 200
        assert len(row["raw_sha256"]) == 64
        assert len(row["normalized_visible_text_sha256"]) == 64
        assert len(row["source_semantic_fingerprint"]) == 64
        for flag in adapter.MATERIAL_FLAGS:
            assert row[flag] is False
    for flag in adapter.MATERIAL_FLAGS:
        assert current[flag] is False

    baseline = reconciler.reconcile(current, None)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_reconciliation_passed"] is True
    assert baseline["pipeline_watch_candidate"] is False
    assert baseline["material_admission_ready_for_downstream_review"] is False

    same = copy.deepcopy(current)
    same["run_id"] = "mff-test-2"
    same["fetched_at"] = "2026-09-03T19:00:00Z"
    no_change = reconciler.reconcile(same, current)
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0
    assert no_change["pipeline_watch_candidate"] is False

    changed, _ = adapter.acquire(
        registry,
        run_id="mff-test-3",
        fetched_at="2026-09-03T20:00:00Z",
        fetcher=lambda url: fake_fetch(url, suffix="new official programming detail" if "cohesion-funds" in url else ""),
    )
    assert changed["semantic_fingerprint"] != current["semantic_fingerprint"]
    before = {row["source_id"]: row for row in current["sources"]}
    after = {row["source_id"]: row for row in changed["sources"]}
    sid = "COHESION-INTERREG-ESF-COUNCIL-PARTIAL-MANDATE-2026-06-29"
    assert before[sid]["raw_sha256"] != after[sid]["raw_sha256"]
    assert before[sid]["normalized_visible_text_sha256"] != after[sid]["normalized_visible_text_sha256"]
    assert before[sid]["source_semantic_fingerprint"] != after[sid]["source_semantic_fingerprint"]
    diff = reconciler.reconcile(changed, current)
    assert diff["reconciliation_state"] == "MFF_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1
    assert diff["pipeline_watch_candidate"] is True
    assert diff["material_admission_ready_for_downstream_review"] is False
    for flag in adapter.MATERIAL_FLAGS:
        assert diff[flag] is False

    degraded, _ = adapter.acquire(
        registry,
        run_id="mff-test-4",
        fetched_at="2026-09-03T21:00:00Z",
        fetcher=lambda url: (_ for _ in ()).throw(TimeoutError("synthetic timeout")) if "cohesion-funds" in url else fake_fetch(url),
    )
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["degraded_source_count"] == 1
    assert degraded["semantic_fingerprint"] is None
    assert degraded["lkg_required"] is True
    degraded_rec = reconciler.reconcile(degraded, current)
    assert degraded_rec["reconciliation_state"] == "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
    assert degraded_rec["semantic_reconciliation_passed"] is False
    assert degraded_rec["semantic_change_count"] == 0
    assert degraded_rec["semantic_changes"] == []
    assert degraded_rec["pipeline_watch_candidate"] is False
    assert degraded_rec["source_health_watch_candidate"] is True
    assert degraded_rec["lkg_reference_required"] is True
    assert degraded_rec["lkg_reference_available"] is True
    assert degraded_rec["lkg_reference_is_current_truth"] is False

    recovered = copy.deepcopy(same)
    recovered["run_id"] = "mff-test-5"
    recovered["fetched_at"] = "2026-09-03T22:00:00Z"
    recovery = reconciler.reconcile(recovered, degraded)
    assert recovery["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert recovery["pipeline_watch_candidate"] is False
    assert recovery["semantic_change_count"] == 0

    equal_time = copy.deepcopy(same)
    equal_time["fetched_at"] = current["fetched_at"]
    try:
        reconciler.reconcile(equal_time, current)
    except ValueError:
        pass
    else:
        raise AssertionError("equal-time previous snapshot should be rejected")

    identity_drift = copy.deepcopy(current)
    identity_drift["sources"][0]["authority_url"] = "https://commission.europa.eu/identity-drift"
    try:
        reconciler.reconcile(same, identity_drift)
    except ValueError:
        pass
    else:
        raise AssertionError("MFF previous identity drift should fail closed")

    tampered = copy.deepcopy(current)
    tampered["open_call_authorized"] = True
    try:
        adapter.validate_snapshot(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("MFF programming snapshot must never authorize OPEN")

    print(json.dumps({
        "status": "PASS",
        "sources": 9,
        "commission_sources": 6,
        "council_programming_sources": 3,
        "content_sensitive_semantic_hash": True,
        "degraded_current_lkg_fail_closed": True,
        "fit_is_not_eligibility": True,
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))


if __name__ == "__main__":
    main()
