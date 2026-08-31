#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "web"))

from programming_pipeline_projection import MISSING_FOR_OPEN, _fingerprint, project


def row(source_id: str, state: str, health_state: str, priority: int) -> dict:
    healthy = health_state == "HEALTHY"
    return {
        "source_id": source_id,
        "programme_ids": [source_id.replace("SRC-", "")],
        "programme": f"{source_id} programme",
        "programme_family": "INTERREG_TEST",
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "authority_class": "T1_OFFICIAL_PROGRAMME",
        "authority_url": f"https://official.example/{source_id.lower()}",
        "supporting_authority_url": None,
        "observation_state": state,
        "signal_basis": "Official programming evidence.",
        "source_published_date": "2026-08-11",
        "consultation_start_date": "2026-08-11" if state == "CONSULTATION" else None,
        "consultation_end_date": None,
        "consultation_lifecycle": "WINDOW_END_NOT_STATED" if state == "CONSULTATION" else "NOT_A_CONSULTATION",
        "freshness_state": "CURRENT_60D",
        "watch_priority": priority,
        "source_health": {
            "health_state": health_state,
            "lkg_required": not healthy,
            "requested_url": f"https://official.example/{source_id.lower()}",
            "final_url": f"https://official.example/{source_id.lower()}" if healthy else None,
            "http_status": 200 if healthy else None,
            "content_type": "text/html" if healthy else None,
            "raw_sha256": "a" * 64 if healthy else None,
            "raw_size_bytes": 128 if healthy else 0,
            "missing_marker_groups": [],
        },
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
        "missing_for_open_confirmation": list(MISSING_FOR_OPEN),
    }


def fixture() -> tuple[dict, dict]:
    snapshot = {
        "schema_version": "1.0",
        "adapter_id": "INTERREG_PROGRAMMING_PIPELINE_V1",
        "run_id": "projection-test-run",
        "fetched_at": "2026-08-31T19:30:00Z",
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "observation_state": "PROGRAMMING_PIPELINE",
        "source_count": 2,
        "healthy_source_count": 1,
        "degraded_source_count": 1,
        "health_state": "DEGRADED",
        "watchlist": [
            row("SRC-RO-MD", "CONSULTATION", "DEGRADED_CERTIFICATE_VERIFY_FAILED", 90),
            row("SRC-HUSKROUA", "PROGRAMMING_PROCESS", "HEALTHY", 70),
        ],
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
    }
    changes = [
        {
            "source_id": "SRC-RO-MD",
            "change_kind": "TRANSPORT_OR_CONTENT_CHANGE",
            "semantic_changed": False,
            "transport_or_content_changed": True,
            "lkg_status": "REQUIRED_REFERENCE_UNAVAILABLE",
            "material_fact_use": False,
            "open_call_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
        },
        {
            "source_id": "SRC-HUSKROUA",
            "change_kind": "SEMANTIC_CHANGE",
            "semantic_changed": True,
            "transport_or_content_changed": False,
            "lkg_status": "NOT_REQUIRED_CURRENT_SOURCE_USABLE",
            "material_fact_use": False,
            "open_call_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
        },
    ]
    reconciliation = {
        "schema_version": "1.0",
        "adapter_id": "INTERREG_PROGRAMMING_RECONCILIATION_V1",
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "current_run_id": snapshot["run_id"],
        "current_fetched_at": snapshot["fetched_at"],
        "current_snapshot_sha256": _fingerprint(snapshot),
        "pipeline_semantic_reconciliation_status": "PASS",
        "reconciliation_state": "PIPELINE_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
        "semantic_change_count": 1,
        "transport_or_content_change_count": 1,
        "pipeline_watch_candidate": True,
        "pipeline_watch_label_required": "PROGRAMARE_VIITOARE_PIPELINE",
        "source_health_watch_candidate": True,
        "changes": changes,
        "call_alert_authorized": False,
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "publication_effect": "NONE",
    }
    return snapshot, reconciliation


def expect_fail(snapshot: dict, reconciliation: dict, label: str) -> None:
    try:
        project(snapshot, reconciliation)
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def main() -> None:
    snapshot, reconciliation = fixture()
    output = project(snapshot, reconciliation)
    assert output["projection_id"] == "PROGRAMMING_PIPELINE_PUBLIC_PROJECTION_V1"
    assert output["surface"] == "PROGRAMARE_VIITOARE_PIPELINE"
    assert output["surface_state"] == "PREVIEW_READ_ONLY_NOT_PUBLISHED"
    assert output["pipeline_watch_label"] == "PROGRAMARE_VIITOARE_PIPELINE"
    assert output["card_count"] == 2
    assert output["cards"][0]["source_id"] == "SRC-RO-MD"
    assert output["cards"][0]["observation_label_ro"] == "Consultare"
    assert output["cards"][0]["confidence"] == "LOW"
    assert output["cards"][0]["open_confirmation_state"] == "NOT_CONFIRMED_MISSING_EXACT_CALL_EVIDENCE"
    assert output["cards"][1]["confidence_reason"] == "CURRENT_OFFICIAL_EVIDENCE_RECONCILED_CHANGE"
    for key in (
        "material_fact_use",
        "open_call_authorized",
        "deadline_authorized",
        "budget_authorized",
        "eligibility_authorized",
        "publish_authorized",
        "distribution_authorized",
        "call_alert_authorized",
    ):
        assert output[key] is False
    assert output["publication_effect"] == "NONE"
    assert output["reader_copy_generated"] is False
    assert output["seo_indexing_state"] == "NOINDEX_PREVIEW_ONLY"

    bad = copy.deepcopy(snapshot)
    bad["watchlist"][0]["open_call_authorized"] = True
    expect_fail(bad, reconciliation, "row self-authorizes OPEN")

    bad = copy.deepcopy(snapshot)
    bad["watchlist"][1]["observation_state"] = "OPEN_CALL"
    expect_fail(bad, reconciliation, "pipeline row becomes OPEN_CALL")

    bad = copy.deepcopy(snapshot)
    bad["watchlist"][0]["missing_for_open_confirmation"] = ["semantic_reconciliation"]
    expect_fail(bad, reconciliation, "missing-for-open contract weakens")

    bad_reconcile = copy.deepcopy(reconciliation)
    bad_reconcile["current_run_id"] = "other-run"
    expect_fail(snapshot, bad_reconcile, "reconciliation does not bind current run")

    bad_reconcile = copy.deepcopy(reconciliation)
    bad_reconcile["pipeline_watch_label_required"] = "OPEN_CALL"
    expect_fail(snapshot, bad_reconcile, "pipeline watch loses mandatory label")

    bad_reconcile = copy.deepcopy(reconciliation)
    bad_reconcile["distribution_authorized"] = True
    expect_fail(snapshot, bad_reconcile, "reconciliation authorizes distribution")

    print("PASS programming pipeline projection stays read-only, pipeline-only and fail-closed")


if __name__ == "__main__":
    main()
