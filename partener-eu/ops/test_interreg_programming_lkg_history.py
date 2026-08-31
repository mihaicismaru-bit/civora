#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "partener-eu" / "ingest"))

import interreg_programming_lkg_history as history
import interreg_programming_pipeline as pipeline

SOURCE_ID = "INT-PIPE-ROMD-2028-2034"


def _row(snapshot: dict, source_id: str = SOURCE_ID) -> dict:
    return next(row for row in snapshot["watchlist"] if row["source_id"] == source_id)


def _refresh(row: dict) -> None:
    pipeline._attach_row_fingerprints(row)


def _healthy(row: dict, raw_hash: str) -> None:
    health = row["source_health"]
    health.update({
        "health_state": "HEALTHY",
        "lkg_required": False,
        "final_url": row["authority_url"],
        "http_status": 200,
        "content_type": "text/html",
        "raw_sha256": raw_hash,
        "raw_size_bytes": 321,
        "missing_marker_groups": [],
        "attempt_count": 1,
        "max_attempts": 3,
        "retryable_failure_count": 0,
        "retry_exhausted": False,
        "attempt_history": [],
        "error": None,
    })
    _refresh(row)


def _degraded(row: dict) -> None:
    health = row["source_health"]
    health.update({
        "health_state": "DEGRADED",
        "lkg_required": True,
        "final_url": None,
        "http_status": None,
        "content_type": None,
        "raw_sha256": None,
        "raw_size_bytes": 0,
        "missing_marker_groups": [],
        "attempt_count": 1,
        "max_attempts": 3,
        "retryable_failure_count": 0,
        "retry_exhausted": False,
        "attempt_history": [],
        "error": "URLError: synthetic certificate failure",
    })
    _refresh(row)


def _snapshot(base: dict, run_id: str, fetched_at: str) -> dict:
    value = copy.deepcopy(base)
    value["run_id"] = run_id
    value["fetched_at"] = fetched_at
    return value


def _base() -> dict:
    return pipeline.resolve(
        run_id="BASE",
        observed_at="2026-08-31T12:00:00Z",
        live=False,
    )


def main() -> None:
    base = _base()

    current = _snapshot(base, "CURRENT", "2026-08-31T12:00:00Z")
    previous = _snapshot(base, "PREVIOUS", "2026-08-31T11:00:00Z")
    older_healthy = _snapshot(base, "OLDER-HEALTHY", "2026-08-31T10:00:00Z")
    _degraded(_row(current))
    _degraded(_row(previous))
    _healthy(_row(older_healthy), "a" * 64)

    receipt = pipeline.reconcile_snapshots(
        current,
        previous,
        reconciled_at="2026-08-31T12:01:00Z",
    )
    initial_change = next(row for row in receipt["changes"] if row["source_id"] == SOURCE_ID)
    assert initial_change["lkg_status"] == "REQUIRED_REFERENCE_UNAVAILABLE"

    enriched = history.enrich_reconciliation_with_history(
        current,
        receipt,
        [previous, older_healthy],
    )
    change = next(row for row in enriched["changes"] if row["source_id"] == SOURCE_ID)
    assert change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_HISTORICAL_HEALTHY_SNAPSHOT"
    assert change["lkg_reference"]["historical_run_id"] == "OLDER-HEALTHY"
    assert change["lkg_reference"]["raw_sha256"] == "a" * 64
    assert change["lkg_reference"]["history_rank"] == 2
    assert enriched["historical_lkg_snapshot_count_considered"] == 2
    assert enriched["historical_lkg_reference_available_count"] == 1
    assert enriched["lkg_reference_available_count"] == 1
    assert enriched["lkg_reference_missing_count"] == 0
    assert enriched["immediate_lkg_identity_mismatch_invalidated_count"] == 0
    assert enriched["call_alert_authorized"] is False
    assert enriched["open_call_authorized"] is False
    assert enriched["distribution_authorized"] is False
    assert enriched["publication_effect"] == "NONE"

    wrong_identity = _snapshot(base, "WRONG-IDENTITY", "2026-08-31T10:30:00Z")
    wrong_row = _row(wrong_identity)
    _healthy(wrong_row, "b" * 64)
    wrong_row["authority_url"] = wrong_row["authority_url"] + "?changed-identity=1"
    _refresh(wrong_row)
    wrong_only = history.enrich_reconciliation_with_history(
        current,
        receipt,
        [previous, wrong_identity],
    )
    wrong_change = next(row for row in wrong_only["changes"] if row["source_id"] == SOURCE_ID)
    assert wrong_change["lkg_status"] == "REQUIRED_REFERENCE_UNAVAILABLE"
    assert wrong_only["historical_lkg_reference_available_count"] == 0
    assert wrong_only["lkg_reference_missing_count"] == 1

    recent_degraded = _snapshot(base, "RECENT-DEGRADED", "2026-08-31T11:30:00Z")
    middle_degraded = _snapshot(base, "MIDDLE-DEGRADED", "2026-08-31T11:15:00Z")
    oldest_healthy = _snapshot(base, "OLDEST-HEALTHY", "2026-08-31T09:00:00Z")
    _degraded(_row(recent_degraded))
    _degraded(_row(middle_degraded))
    _healthy(_row(oldest_healthy), "c" * 64)
    bounded = history.enrich_reconciliation_with_history(
        current,
        receipt,
        [oldest_healthy, middle_degraded, recent_degraded],
        max_history_snapshots=2,
    )
    bounded_change = next(row for row in bounded["changes"] if row["source_id"] == SOURCE_ID)
    assert bounded["historical_lkg_snapshot_count_considered"] == 2
    assert bounded_change["lkg_status"] == "REQUIRED_REFERENCE_UNAVAILABLE"

    immediate_healthy = _snapshot(base, "IMMEDIATE-HEALTHY", "2026-08-31T11:00:00Z")
    _healthy(_row(immediate_healthy), "d" * 64)
    immediate_receipt = pipeline.reconcile_snapshots(
        current,
        immediate_healthy,
        reconciled_at="2026-08-31T12:02:00Z",
    )
    immediate = history.enrich_reconciliation_with_history(
        current,
        immediate_receipt,
        [immediate_healthy, older_healthy],
    )
    immediate_change = next(row for row in immediate["changes"] if row["source_id"] == SOURCE_ID)
    assert immediate_change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT"
    assert immediate_change["lkg_reference"]["previous_run_id"] == "IMMEDIATE-HEALTHY"
    assert immediate["historical_lkg_reference_available_count"] == 0
    assert immediate["immediate_lkg_identity_mismatch_invalidated_count"] == 0
    assert immediate["lkg_reference_available_count"] == 1

    immediate_wrong = _snapshot(base, "IMMEDIATE-WRONG", "2026-08-31T11:00:00Z")
    immediate_wrong_row = _row(immediate_wrong)
    _healthy(immediate_wrong_row, "e" * 64)
    immediate_wrong_row["authority_url"] = immediate_wrong_row["authority_url"] + "?authority-generation=old"
    _refresh(immediate_wrong_row)
    immediate_wrong_receipt = pipeline.reconcile_snapshots(
        current,
        immediate_wrong,
        reconciled_at="2026-08-31T12:03:00Z",
    )
    pre_guard_change = next(row for row in immediate_wrong_receipt["changes"] if row["source_id"] == SOURCE_ID)
    assert pre_guard_change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT"

    guarded_missing = history.enrich_reconciliation_with_history(
        current,
        immediate_wrong_receipt,
        [immediate_wrong],
    )
    guarded_missing_change = next(row for row in guarded_missing["changes"] if row["source_id"] == SOURCE_ID)
    assert guarded_missing_change["lkg_status"] == "REQUIRED_REFERENCE_UNAVAILABLE"
    assert guarded_missing_change["lkg_reference"] is None
    assert guarded_missing["immediate_lkg_identity_mismatch_invalidated_count"] == 1
    assert guarded_missing["lkg_reference_available_count"] == 0
    assert guarded_missing["lkg_reference_missing_count"] == 1

    guarded_fallback = history.enrich_reconciliation_with_history(
        current,
        immediate_wrong_receipt,
        [immediate_wrong, older_healthy],
    )
    guarded_fallback_change = next(row for row in guarded_fallback["changes"] if row["source_id"] == SOURCE_ID)
    assert guarded_fallback_change["lkg_status"] == "REFERENCE_AVAILABLE_FROM_HISTORICAL_HEALTHY_SNAPSHOT"
    assert guarded_fallback_change["lkg_reference"]["historical_run_id"] == "OLDER-HEALTHY"
    assert guarded_fallback["immediate_lkg_identity_mismatch_invalidated_count"] == 1
    assert guarded_fallback["historical_lkg_reference_available_count"] == 1
    assert guarded_fallback["lkg_reference_available_count"] == 1

    tampered_history = copy.deepcopy(older_healthy)
    tampered_history["open_call_authorized"] = True
    try:
        history.enrich_reconciliation_with_history(current, receipt, [tampered_history])
    except ValueError as exc:
        assert "became authorizing" in str(exc)
    else:
        raise AssertionError("authorizing historical snapshot must fail closed")

    future = _snapshot(older_healthy, "FUTURE", "2026-08-31T13:00:00Z")
    future_only = history.enrich_reconciliation_with_history(current, receipt, [future])
    assert future_only["historical_lkg_snapshot_count_considered"] == 0
    assert future_only["lkg_reference_missing_count"] == 1

    try:
        history.enrich_reconciliation_with_history(current, receipt, [older_healthy], max_history_snapshots=0)
    except ValueError as exc:
        assert "max_history_snapshots" in str(exc)
    else:
        raise AssertionError("zero history bound must fail closed")

    print(json.dumps({
        "status": "PASS",
        "historical_lkg_resolution_version": enriched["historical_lkg_resolution_version"],
        "historical_lkg_snapshot_count_considered": enriched["historical_lkg_snapshot_count_considered"],
        "historical_lkg_reference_available_count": enriched["historical_lkg_reference_available_count"],
        "resolved_historical_run_id": change["lkg_reference"]["historical_run_id"],
        "bounded_history_excludes_older_good": bounded_change["lkg_status"],
        "immediate_previous_preserved": immediate_change["lkg_status"],
        "authority_identity_mismatch_invalidated": guarded_missing["immediate_lkg_identity_mismatch_invalidated_count"],
        "identity_safe_historical_fallback": guarded_fallback_change["lkg_status"],
        "open_call_authorized": enriched["open_call_authorized"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
