#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_future_programming_watch as mod  # noqa: E402


def healthy_fetch(row, timeout):
    raw = f"official:{row['id']}".encode()
    return {
        "health_state": "HEALTHY",
        "requested_url": row["authority_url"],
        "final_url": row["authority_url"],
        "http_status": 200,
        "content_type": "text/html",
        "raw_sha256": mod._sha(raw),
        "raw_size_bytes": len(raw),
        "missing_marker_groups": [],
        "error_type": None,
        "error": None,
    }


def expect_failure(fn, label):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def rehash(snapshot):
    for row in snapshot["watchlist"]:
        row["semantic_fingerprint"] = mod._fingerprint(mod._semantic_payload(row))
        row["transport_fingerprint"] = mod._fingerprint(mod._transport_payload(row))
    snapshot["semantic_fingerprint"] = mod._fingerprint([[r["source_id"], r["semantic_fingerprint"]] for r in snapshot["watchlist"]])
    snapshot["transport_fingerprint"] = mod._fingerprint([[r["source_id"], r["transport_fingerprint"]] for r in snapshot["watchlist"]])


def main():
    original_fetch = mod._fetch
    mod._fetch = healthy_fetch
    try:
        baseline = mod.build_snapshot(run_id="test-1", observed_at="2026-09-02T07:00:00Z")
    finally:
        mod._fetch = original_fetch

    assert baseline["source_count"] == 9
    assert baseline["healthy_source_count"] == 9
    assert baseline["coverage_complete"] is True
    assert all(row["observation_state"] in {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"} for row in baseline["watchlist"])
    assert all("OPEN" not in row["observation_state"] and "CALL" not in row["observation_state"] for row in baseline["watchlist"])
    assert all(row["open_call_authorized"] is False for row in baseline["watchlist"])
    assert all(row["call_alert_authorized"] is False for row in baseline["watchlist"])
    assert next(row for row in baseline["watchlist"] if row["source_id"] == "INT-FUTURE-ROHU-2028-2034")["consultation_lifecycle"] == "AFTER_WINDOW"
    assert next(row for row in baseline["watchlist"] if row["source_id"] == "INT-FUTURE-BSB-2028-2034")["consultation_lifecycle"] in {"END_KNOWN_START_NOT_STATED", "IN_WINDOW"}

    eu_framework = next(row for row in baseline["watchlist"] if row["source_id"] == "INT-FUTURE-EU-COM-2025-552")
    assert eu_framework["authority_class"] == "T1_EU_OFFICIAL_PROGRAMMING_ANALYSIS"
    assert eu_framework["authority_url"].startswith("https://futurium.ec.europa.eu/en/border-focal-point-network/news/")
    assert eu_framework["supporting_authority_url"] == "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:52025PC0552"
    assert eu_framework["observation_state"] == "PROPOSAL"
    assert eu_framework["open_call_authorized"] is False

    base_reconcile = mod.reconcile(baseline, None, reconciled_at="2026-09-02T07:01:00Z")
    assert base_reconcile["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert base_reconcile["pipeline_watch_candidate"] is False
    assert base_reconcile["call_alert_authorized"] is False

    no_change = mod.reconcile(copy.deepcopy(baseline), baseline, reconciled_at="2026-09-02T07:02:00Z")
    assert no_change["reconciliation_state"] == "NO_CHANGE"
    assert no_change["semantic_change_count"] == 0

    degraded = copy.deepcopy(baseline)
    degraded["run_id"] = "test-2"
    row = degraded["watchlist"][0]
    row["source_health"] = {
        "health_state": "DEGRADED",
        "requested_url": row["authority_url"],
        "final_url": None,
        "http_status": None,
        "content_type": None,
        "raw_sha256": None,
        "raw_size_bytes": 0,
        "missing_marker_groups": [],
        "error_type": "TLS_CERTIFICATE_VERIFY_FAILED",
        "error": "synthetic",
    }
    degraded["healthy_source_count"] = 8
    degraded["degraded_source_count"] = 1
    degraded["source_health"] = "DEGRADED"
    degraded["coverage_complete"] = False
    rehash(degraded)
    rec = mod.reconcile(degraded, baseline, reconciled_at="2026-09-02T07:03:00Z")
    change = next(item for item in rec["changes"] if item["source_id"] == row["source_id"])
    assert change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SAME_IDENTITY"
    assert change["lkg_reference"]["use_constraint"] == "EVIDENCE_REFERENCE_ONLY_NEVER_CURRENT_CALL_OR_PROGRAMMING_TRUTH"
    assert rec["source_health_watch_candidate"] is True
    assert rec["pipeline_watch_candidate"] is False
    assert rec["call_alert_authorized"] is False

    degraded_semantic = copy.deepcopy(baseline)
    degraded_semantic["run_id"] = "test-3"
    semantic_row = degraded_semantic["watchlist"][0]
    semantic_row["signal_basis"] = str(semantic_row["signal_basis"]) + " synthetic registry refresh"
    semantic_row["source_health"] = {
        "health_state": "DEGRADED",
        "requested_url": semantic_row["authority_url"],
        "final_url": None,
        "http_status": None,
        "content_type": None,
        "raw_sha256": None,
        "raw_size_bytes": 0,
        "missing_marker_groups": [],
        "error_type": "TLS_CERTIFICATE_VERIFY_FAILED",
        "error": "synthetic",
    }
    degraded_semantic["healthy_source_count"] = 8
    degraded_semantic["degraded_source_count"] = 1
    degraded_semantic["source_health"] = "DEGRADED"
    degraded_semantic["coverage_complete"] = False
    rehash(degraded_semantic)
    rec = mod.reconcile(degraded_semantic, baseline, reconciled_at="2026-09-02T07:03:30Z")
    change = next(item for item in rec["changes"] if item["source_id"] == semantic_row["source_id"])
    assert rec["semantic_change_count"] == 1
    assert rec["pipeline_evidence_change_count"] == 0
    assert rec["pipeline_watch_candidate"] is False
    assert rec["source_health_watch_candidate"] is True
    assert rec["reconciliation_state"] == "PIPELINE_SEMANTIC_CHANGE_CURRENT_SOURCE_UNUSABLE_NON_AUTHORIZING"
    assert change["semantic_changed"] is True
    assert change["pipeline_watch_evidence_usable"] is False
    assert change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SAME_IDENTITY"
    assert rec["call_alert_authorized"] is False

    tampered = copy.deepcopy(baseline)
    tampered["watchlist"][0]["open_call_authorized"] = True
    expect_failure(lambda: mod.validate_snapshot(tampered), "row OPEN authorization")

    tampered = copy.deepcopy(baseline)
    tampered["watchlist"][0]["observation_state"] = "OPEN_CALL"
    expect_failure(lambda: mod.validate_snapshot(tampered), "pipeline to OPEN_CALL")

    tampered = copy.deepcopy(baseline)
    tampered["watchlist"][0]["authority_url"] = "https://example.com/fake"
    expect_failure(lambda: mod.validate_snapshot(tampered), "authority/fingerprint tamper")

    registry = json.loads(mod.DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    registry["sources"][0]["observation_state"] = "OPEN_CALL"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "registry.json"
        path.write_text(json.dumps(registry), encoding="utf-8")
        expect_failure(lambda: mod.load_registry(path), "registry OPEN_CALL")

    wrong_identity_previous = copy.deepcopy(baseline)
    wrong_identity_previous["watchlist"][0]["authority_url"] = "https://futurium.ec.europa.eu/en/border-focal-point-network/news/fake"
    rehash(wrong_identity_previous)
    rec = mod.reconcile(degraded, wrong_identity_previous, reconciled_at="2026-09-02T07:04:00Z")
    change = next(item for item in rec["changes"] if item["source_id"] == row["source_id"])
    assert change["lkg_status"] == "REQUIRED_REFERENCE_UNAVAILABLE"
    assert change["lkg_reference"] is None

    print({
        "status": "PASS",
        "schema": baseline["schema"],
        "sources": baseline["source_count"],
        "eu_framework_primary_authority": "FUTURIUM_EC",
        "eu_framework_supporting_legal_authority": "EUR_LEX_COM_2025_552",
        "baseline_reconciliation": base_reconcile["reconciliation_state"],
        "same_identity_lkg_guard": "PASS",
        "degraded_semantic_pipeline_watch_suppression": "PASS",
        "open_call_widening_guard": "PASS",
        "programming_state_never_encodes_open_or_call": "PASS",
    })


if __name__ == "__main__":
    main()
