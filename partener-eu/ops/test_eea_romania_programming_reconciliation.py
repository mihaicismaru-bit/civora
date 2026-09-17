#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json

from eea_romania_programming_intelligence_reconcile import (
    EXPECTED_AUTHORITY_URL,
    EXPECTED_PROGRAMME_COUNT,
    EXPECTED_SOURCE_ID,
    MATERIAL_FLAGS,
    PROGRAMME_FAMILY,
    RECONCILIATION_SCHEMA,
    SNAPSHOT_SCHEMA,
    SOURCE_FAMILY,
    reconcile,
)


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def healthy(*, fetched_at: str = "2026-09-07T00:00:00+00:00", mutation: bool = False) -> dict:
    records = []
    for index in range(EXPECTED_PROGRAMME_COUNT):
        semantic = {
            "programme_id": f"EEA-RO-{index:02d}",
            "programme_name": f"Programme {index}",
            "programme_operator": f"Operator {index}" + (" changed" if mutation and index == 2 else ""),
            "fund_operator": None,
            "programme_grant_evidence": f"€ {index+1},000,000",
        }
        records.append({
            "schema": "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_OBSERVATION_V2",
            "source_family": SOURCE_FAMILY,
            "programme_family": PROGRAMME_FAMILY,
            "programme_id": semantic["programme_id"],
            "programme_name": semantic["programme_name"],
            "programme_operator": semantic["programme_operator"],
            "fund_operator": None,
            "authority_url": EXPECTED_AUTHORITY_URL,
            "semantic_fingerprint": sha(semantic),
            "observation_state": "PROGRAMMING_PIPELINE",
            "not_a_call": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "canonical_corpus_mutation": False,
            "requires_reconciliation": True,
            "publication_effect": "NONE",
        })
    return {
        "schema": SNAPSHOT_SCHEMA,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": "EEA_FMO_ROMANIA_PROGRAMME_MAP",
        "source": {
            "id": EXPECTED_SOURCE_ID,
            "url": EXPECTED_AUTHORITY_URL,
            "published_date": "2026-05-12",
            "http_status": 200,
            "content_type": "text/html",
            "raw_hash": "a" * 64,
            "bytes": 1000,
        },
        "fetched_at": fetched_at,
        "parser_version": "EEA_ROMANIA_PROGRAMMING_INTELLIGENCE_V2",
        "run_id": "test",
        "records": records,
        "stats": {"programme_records": 9, "open_calls_authorized": 0},
        "observation_state": "PROGRAMMING_PIPELINE",
        "source_health_state": "HEALTHY",
        "healthy_source_count": 1,
        "degraded_source_count": 0,
        "evidence_usable_for_reconciliation": True,
        "lkg_required": False,
        "semantic_fingerprint": sha([row["semantic_fingerprint"] for row in records]),
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "current_material_truth_available": False,
        "material_fact_use": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "requires_reconciliation": True,
        "publication_effect": "NONE",
    }


def degraded(*, fetched_at: str = "2026-09-07T00:01:00+00:00") -> dict:
    value = healthy(fetched_at=fetched_at)
    value["source_health_state"] = "DEGRADED"
    value["healthy_source_count"] = 0
    value["degraded_source_count"] = 1
    value["evidence_usable_for_reconciliation"] = False
    value["lkg_required"] = True
    value["semantic_fingerprint"] = None
    value["records"] = []
    value["source"]["raw_hash"] = None
    value["source"]["http_status"] = None
    value["failure_class"] = "TRANSPORT_ERROR"
    return value


def expect_raises(fn, contains: str) -> None:
    try:
        fn()
    except (ValueError, RuntimeError) as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected {contains!r}, got {exc!r}") from exc
    else:
        raise AssertionError(f"expected failure containing {contains!r}")


def assert_boundary(result: dict) -> None:
    assert result["schema"] == RECONCILIATION_SCHEMA
    assert result["publication_effect"] == "NONE"
    assert result["current_material_truth_available"] is False
    assert result["material_admission_ready_for_downstream_review"] is False
    assert result["lkg_reference_is_current_truth"] is False
    for flag in MATERIAL_FLAGS:
        assert result[flag] is False


def main() -> int:
    current = healthy(fetched_at="2026-09-07T00:02:00+00:00")
    baseline = reconcile(current)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert_boundary(baseline)

    previous = healthy(fetched_at="2026-09-07T00:01:00+00:00")
    same = reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["programming_watch_candidate"] is False
    assert_boundary(same)

    changed_current = healthy(fetched_at="2026-09-07T00:03:00+00:00", mutation=True)
    changed = reconcile(changed_current, previous)
    assert changed["reconciliation_state"] == "EEA_ROMANIA_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed["programming_watch_candidate"] is True
    assert changed["semantic_change_count"] == 1
    assert_boundary(changed)

    down = reconcile(degraded(fetched_at="2026-09-07T00:04:00+00:00"), previous)
    assert down["reconciliation_state"] == "CURRENT_PROGRAMMING_AUTHORITY_DEGRADED_LKG_REQUIRED"
    assert down["lkg_reference_required"] is True
    assert down["lkg_reference_available"] is True
    assert down["semantic_reconciliation_passed"] is False
    assert_boundary(down)

    recovered_previous = degraded(fetched_at="2026-09-07T00:01:00+00:00")
    recovered = reconcile(current, recovered_previous)
    assert recovered["reconciliation_state"] == "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    assert_boundary(recovered)

    newer = healthy(fetched_at="2026-09-07T00:05:00+00:00")
    expect_raises(lambda: reconcile(current, newer), "strictly older")

    drift = healthy(fetched_at="2026-09-07T00:01:00+00:00")
    drift["source"]["id"] = "OTHER"
    expect_raises(lambda: reconcile(current, drift), "authority identity")

    inventory_drift = healthy(fetched_at="2026-09-07T00:01:00+00:00")
    inventory_drift["records"][0]["programme_id"] = inventory_drift["records"][1]["programme_id"]
    expect_raises(lambda: reconcile(current, inventory_drift), "programme inventory")

    widened = healthy()
    widened["open_call_authorized"] = True
    expect_raises(lambda: reconcile(widened), "material authorization")

    lexical = healthy()
    lexical["records"][0]["programme_name"] = "OPEN deadline budget eligible"
    lexical["records"][0]["semantic_fingerprint"] = sha({"lexical": "OPEN deadline budget eligible"})
    lexical["semantic_fingerprint"] = sha([row["semantic_fingerprint"] for row in lexical["records"]])
    lexical_result = reconcile(lexical)
    assert lexical_result["open_call_authorized"] is False
    assert lexical_result["deadline_authorized"] is False
    assert lexical_result["budget_authorized"] is False
    assert lexical_result["eligibility_authorized"] is False

    print("PASS EEA Romania programming reconciliation fail-closed regressions (10 cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
