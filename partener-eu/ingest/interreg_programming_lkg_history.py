#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import interreg_programming_pipeline as pipeline

HISTORICAL_LKG_VERSION = "INTERREG_PROGRAMMING_HISTORICAL_LKG_V1"
DEFAULT_MAX_HISTORY_SNAPSHOTS = 8


def _snapshot_time(snapshot: dict[str, Any], *, label: str) -> datetime:
    value = snapshot.get("fetched_at")
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{label}: fetched_at must be RFC3339 UTC-Z")
    parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    if parsed.tzinfo is None:
        raise ValueError(f"{label}: fetched_at must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _lkg_identity_payload(row: dict[str, Any]) -> dict[str, Any]:
    """Stable source identity for LKG reuse; excludes time-derived lifecycle/priority."""
    return {
        "source_id": row.get("source_id"),
        "programme_ids": list(row.get("programme_ids") or []),
        "programme": row.get("programme"),
        "programme_family": row.get("programme_family"),
        "source_family": row.get("source_family"),
        "programme_period": row.get("programme_period"),
        "authority_class": row.get("authority_class"),
        "authority_url": row.get("authority_url"),
        "supporting_authority_url": row.get("supporting_authority_url"),
        "observation_state": row.get("observation_state"),
        "signal_basis": row.get("signal_basis"),
        "source_published_date": row.get("source_published_date"),
        "consultation_start_date": row.get("consultation_start_date"),
        "consultation_end_date": row.get("consultation_end_date"),
    }


def _lkg_identity_fingerprint(row: dict[str, Any]) -> str:
    return pipeline._fingerprint(_lkg_identity_payload(row))


def _validate_receipt(receipt: dict[str, Any], current: dict[str, Any]) -> None:
    if receipt.get("adapter_id") != pipeline.RECONCILIATION_VERSION:
        raise ValueError("receipt: unexpected reconciliation adapter id")
    if receipt.get("current_run_id") != current.get("run_id"):
        raise ValueError("receipt: current run binding mismatch")
    if receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("receipt: programming policy drift")
    for key in pipeline.MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"receipt became authorizing: {key}")
    if receipt.get("call_alert_authorized") is not False:
        raise ValueError("receipt became call-alert authorizing")
    changes = receipt.get("changes")
    if not isinstance(changes, list):
        raise ValueError("receipt: changes must be a list")
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("receipt: change must be an object")
        for key in ("material_fact_use", "open_call_authorized", "publish_authorized", "distribution_authorized"):
            if change.get(key) is not False:
                raise ValueError(f"receipt change became authorizing: {change.get('source_id')} {key}")


def _validated_history(
    current: dict[str, Any],
    history_snapshots: Iterable[dict[str, Any]],
    *,
    max_history_snapshots: int,
) -> list[tuple[dict[str, Any], dict[str, dict[str, Any]], datetime]]:
    if max_history_snapshots < 1 or max_history_snapshots > 32:
        raise ValueError("max_history_snapshots must be between 1 and 32")
    current_time = _snapshot_time(current, label="current")
    current_run_id = str(current.get("run_id") or "")
    seen_run_ids: set[str] = set()
    validated: list[tuple[dict[str, Any], dict[str, dict[str, Any]], datetime]] = []
    for index, snapshot in enumerate(history_snapshots):
        by_id = pipeline._validate_snapshot(snapshot, label=f"history[{index}]")
        run_id = str(snapshot.get("run_id") or "")
        if not run_id:
            raise ValueError(f"history[{index}]: missing run_id")
        if run_id == current_run_id or run_id in seen_run_ids:
            continue
        fetched_at = _snapshot_time(snapshot, label=f"history[{index}]")
        if fetched_at >= current_time:
            continue
        seen_run_ids.add(run_id)
        validated.append((snapshot, by_id, fetched_at))
    validated.sort(key=lambda item: (item[2], str(item[0].get("run_id") or "")), reverse=True)
    return validated[:max_history_snapshots]


def _historical_reference(
    current_row: dict[str, Any],
    history: list[tuple[dict[str, Any], dict[str, dict[str, Any]], datetime]],
) -> tuple[dict[str, Any] | None, int | None]:
    current_identity = _lkg_identity_fingerprint(current_row)
    for rank, (snapshot, by_id, _fetched_at) in enumerate(history, start=1):
        candidate = by_id.get(str(current_row.get("source_id") or ""))
        if candidate is None:
            continue
        candidate_health = candidate.get("source_health") or {}
        if candidate_health.get("health_state") != "HEALTHY":
            continue
        raw_sha256 = candidate_health.get("raw_sha256")
        if not pipeline._is_sha256(raw_sha256):
            continue
        stored_semantic = candidate.get("semantic_fingerprint")
        stored_transport = candidate.get("transport_fingerprint")
        if not pipeline._is_sha256(stored_semantic) or not pipeline._is_sha256(stored_transport):
            continue
        if stored_semantic != pipeline._fingerprint(pipeline._row_semantic_payload(candidate)):
            continue
        if stored_transport != pipeline._fingerprint(pipeline._row_transport_payload(candidate)):
            continue
        if _lkg_identity_fingerprint(candidate) != current_identity:
            continue
        return {
            "source_id": candidate.get("source_id"),
            "authority_url": candidate.get("authority_url"),
            "historical_run_id": snapshot.get("run_id"),
            "historical_fetched_at": snapshot.get("fetched_at"),
            "historical_snapshot_sha256": pipeline._fingerprint(snapshot),
            "raw_sha256": raw_sha256,
            "semantic_identity_fingerprint": current_identity,
            "history_rank": rank,
            "use_constraint": "LAST_KNOWN_GOOD_EVIDENCE_REFERENCE_ONLY_NO_CURRENT_MATERIAL_FACT",
        }, rank
    return None, None


def _immediate_reference_identity_matches(
    current_row: dict[str, Any],
    change: dict[str, Any],
    receipt: dict[str, Any],
    history: list[tuple[dict[str, Any], dict[str, dict[str, Any]], datetime]],
) -> bool:
    """Immediate LKG is valid only when the previous row has the same stable authority/programme identity."""
    if change.get("lkg_status") != "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT":
        return True
    previous_run_id = str(receipt.get("previous_run_id") or "")
    source_id = str(current_row.get("source_id") or "")
    if not previous_run_id or not source_id:
        return False
    current_identity = _lkg_identity_fingerprint(current_row)
    for snapshot, by_id, _fetched_at in history:
        if str(snapshot.get("run_id") or "") != previous_run_id:
            continue
        candidate = by_id.get(source_id)
        if candidate is None:
            return False
        candidate_health = candidate.get("source_health") or {}
        if candidate_health.get("health_state") != "HEALTHY":
            return False
        if not pipeline._is_sha256(candidate_health.get("raw_sha256")):
            return False
        return _lkg_identity_fingerprint(candidate) == current_identity
    return False


def enrich_reconciliation_with_history(
    current: dict[str, Any],
    receipt: dict[str, Any],
    history_snapshots: Iterable[dict[str, Any]],
    *,
    max_history_snapshots: int = DEFAULT_MAX_HISTORY_SNAPSHOTS,
) -> dict[str, Any]:
    current_by_id = pipeline._validate_snapshot(current, label="current")
    _validate_receipt(receipt, current)
    history = _validated_history(
        current,
        history_snapshots,
        max_history_snapshots=max_history_snapshots,
    )
    result = copy.deepcopy(receipt)
    invalidated_immediate_references = 0
    historical_resolutions = 0
    for change in result["changes"]:
        source_id = str(change.get("source_id") or "")
        current_row = current_by_id.get(source_id)
        if current_row is None:
            continue
        health = current_row.get("source_health") or {}
        if not str(health.get("health_state") or "").startswith("DEGRADED"):
            continue
        if change.get("lkg_status") == "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT":
            if not _immediate_reference_identity_matches(current_row, change, result, history):
                change["lkg_status"] = "REQUIRED_REFERENCE_UNAVAILABLE"
                change["lkg_reference"] = None
                invalidated_immediate_references += 1
        if change.get("lkg_status") != "REQUIRED_REFERENCE_UNAVAILABLE":
            continue
        reference, _rank = _historical_reference(current_row, history)
        if reference is None:
            continue
        change["lkg_status"] = "REFERENCE_AVAILABLE_FROM_HISTORICAL_HEALTHY_SNAPSHOT"
        change["lkg_reference"] = reference
        historical_resolutions += 1

    available_statuses = {
        "REFERENCE_AVAILABLE_FROM_PREVIOUS_HEALTHY_SNAPSHOT",
        "REFERENCE_AVAILABLE_FROM_HISTORICAL_HEALTHY_SNAPSHOT",
    }
    result["lkg_reference_available_count"] = sum(
        1 for change in result["changes"] if change.get("lkg_status") in available_statuses
    )
    result["lkg_reference_missing_count"] = sum(
        1 for change in result["changes"] if change.get("lkg_status") == "REQUIRED_REFERENCE_UNAVAILABLE"
    )
    result["historical_lkg_resolution_version"] = HISTORICAL_LKG_VERSION
    result["historical_lkg_search_bounded"] = True
    result["historical_lkg_max_snapshots"] = max_history_snapshots
    result["historical_lkg_snapshot_count_considered"] = len(history)
    result["historical_lkg_run_ids_considered"] = [snapshot.get("run_id") for snapshot, _by_id, _when in history]
    result["historical_lkg_reference_available_count"] = historical_resolutions
    result["historical_lkg_reference_missing_count"] = result["lkg_reference_missing_count"]
    result["immediate_lkg_identity_guard"] = "SAME_STABLE_SOURCE_AUTHORITY_PROGRAMME_IDENTITY_REQUIRED"
    result["immediate_lkg_identity_mismatch_invalidated_count"] = invalidated_immediate_references
    result["historical_lkg_policy"] = (
        "Only a prior HEALTHY row with valid raw SHA-256 and the same stable source/authority/programme semantic identity "
        "may be referenced. Immediate-previous references are revalidated against the same identity rule before use. "
        "LKG is evidence-only and never becomes current material call evidence."
    )
    result["call_alert_authorized"] = False
    for key in pipeline.MATERIAL_FLAGS:
        result[key] = False
    result["publication_effect"] = "NONE"
    result["market_intelligence_only"] = True
    _validate_receipt(result, current)
    return result


def _load_history(directory: Path) -> list[dict[str, Any]]:
    if not directory.exists():
        return []
    snapshots: list[dict[str, Any]] = []
    for path in sorted(directory.rglob("interreg-programming-pipeline.json")):
        snapshots.append(json.loads(path.read_text(encoding="utf-8")))
    return snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve bounded historical LKG references for Interreg programming evidence.")
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--history-dir", type=Path, required=True)
    parser.add_argument("--max-history-snapshots", type=int, default=DEFAULT_MAX_HISTORY_SNAPSHOTS)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
    result = enrich_reconciliation_with_history(
        current,
        receipt,
        _load_history(args.history_dir),
        max_history_snapshots=args.max_history_snapshots,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "historical_lkg_snapshot_count_considered": result["historical_lkg_snapshot_count_considered"],
        "historical_lkg_reference_available_count": result["historical_lkg_reference_available_count"],
        "immediate_lkg_identity_mismatch_invalidated_count": result["immediate_lkg_identity_mismatch_invalidated_count"],
        "lkg_reference_available_count": result["lkg_reference_available_count"],
        "lkg_reference_missing_count": result["lkg_reference_missing_count"],
        "open_call_authorized": result["open_call_authorized"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
