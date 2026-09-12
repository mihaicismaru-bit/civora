#!/usr/bin/env python3
"""Fail-closed same-identity reconciliation for MFF 2028-2034 programming."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from mff_2028_2034_programming_pipeline import (
    MATERIAL_FLAGS,
    PARSER_VERSION,
    PROGRAMME_FAMILY,
    PROGRAMME_PERIOD,
    SCHEMA as CURRENT_SCHEMA,
    SOURCE_FAMILY,
    identity,
    validate_snapshot,
)

SCHEMA = "PARTENER_EU_MFF_2028_2034_PROGRAMMING_RECONCILIATION_V2"
RECONCILER_VERSION = "MFF_2028_2034_PROGRAMMING_RECONCILE_V2"


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("MFF reconciliation timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def semantic_view(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "sources": {
            str(row.get("source_id") or ""): {
                "observation_state": row.get("observation_state"),
                "source_semantic_fingerprint": row.get("source_semantic_fingerprint"),
                "romania_relevance_score": row.get("romania_relevance_score"),
            }
            for row in snapshot.get("sources") or []
        },
        "market_signals": list(snapshot.get("market_signals") or []),
        "applicant_fit_tags": list(snapshot.get("applicant_fit_tags") or []),
        "geography_tags": list(snapshot.get("geography_tags") or []),
    }


def semantic_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = semantic_view(previous)
    after = semantic_view(current)
    changes: list[dict[str, Any]] = []
    for source_id in sorted(set(before["sources"]) | set(after["sources"])):
        old = before["sources"].get(source_id)
        new = after["sources"].get(source_id)
        if old != new:
            changes.append({"kind": "SOURCE_PROGRAMMING_SEMANTICS_CHANGED", "source_id": source_id, "before": old, "after": new})
    for field in ("market_signals", "applicant_fit_tags", "geography_tags"):
        if before[field] != after[field]:
            changes.append({"kind": "PROGRAMMING_INTELLIGENCE_CHANGED", "field": field, "before": before[field], "after": after[field]})
    return changes


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(current)
    current_identity = identity(current)
    current_healthy = current.get("source_health_state") == "HEALTHY" and int(current.get("degraded_source_count") or 0) == 0

    previous_valid = False
    previous_healthy = False
    previous_sha = None
    previous_identity_match = None
    parser_migration = False
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous)
        previous_identity_match = identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("MFF previous source/programme identity mismatch")
        if parse_time(str(previous.get("fetched_at") or "")) >= parse_time(str(current.get("fetched_at") or "")):
            raise ValueError("MFF previous snapshot is not strictly older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health_state") == "HEALTHY" and int(previous.get("degraded_source_count") or 0) == 0
        previous_sha = sha256_json(previous)
        parser_migration = str(previous.get("parser_version") or "") != str(current.get("parser_version") or "")

    if not current_healthy:
        state = "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        pipeline_watch_candidate = False
        source_health_watch_candidate = True
        lkg_reference_required = True
        lkg_reference_available = bool(previous_valid and previous_healthy)
        baseline_captured = False
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        pipeline_watch_candidate = False
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        pipeline_watch_candidate = False
        source_health_watch_candidate = True
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif parser_migration:
        state = "PARSER_VERSION_CHANGED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        pipeline_watch_candidate = False
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = True
    else:
        changes = semantic_changes(previous, current)
        if changes:
            state = "MFF_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            pipeline_watch_candidate = True
        else:
            state = "NO_CHANGE"
            pipeline_watch_candidate = False
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = False

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_period": PROGRAMME_PERIOD,
        "authority_class": "OFFICIAL_EU_PROGRAMMING_AUTHORITIES",
        "observation_state": "PROGRAMMING_PIPELINE_RECONCILED_NON_AUTHORIZING",
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_parser_version": current.get("parser_version"),
        "current_snapshot_sha256": sha256_json(current),
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "current_source_health_state": current.get("source_health_state"),
        "previous_snapshot_sha256": previous_sha,
        "previous_parser_version": previous.get("parser_version") if previous else None,
        "previous_identity_match": previous_identity_match,
        "parser_migration_baseline": parser_migration and current_healthy and previous_healthy,
        "reconciliation_state": state,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "pipeline_watch_candidate": pipeline_watch_candidate,
        "source_health_watch_candidate": source_health_watch_candidate,
        "baseline_captured": baseline_captured,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": lkg_reference_available,
        "lkg_reference_is_current_truth": False,
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_call_endpoint_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["reconciliation_fingerprint"] = sha256_json({
        "identity": current_identity,
        "state": state,
        "current_parser_version": current.get("parser_version"),
        "previous_parser_version": previous.get("parser_version") if previous else None,
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "previous_snapshot_sha256": previous_sha,
        "semantic_changes": changes,
        "current_source_health_state": current.get("source_health_state"),
    })
    validate_reconciliation(result, current=current, previous=previous)
    return result


def validate_reconciliation(result: Mapping[str, Any], *, current: Mapping[str, Any], previous: Mapping[str, Any] | None) -> None:
    if result.get("schema") != SCHEMA or result.get("reconciler_version") != RECONCILER_VERSION:
        raise ValueError("MFF reconciliation schema/version drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("MFF reconciliation family drift")
    if result.get("programme_period") != PROGRAMME_PERIOD:
        raise ValueError("MFF reconciliation period drift")
    current_healthy = current.get("source_health_state") == "HEALTHY" and int(current.get("degraded_source_count") or 0) == 0
    state = result.get("reconciliation_state")
    if not current_healthy:
        if state != "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED":
            raise ValueError("degraded MFF current did not fail closed")
        if result.get("semantic_reconciliation_passed") is not False or result.get("semantic_change_count") != 0:
            raise ValueError("degraded MFF current produced semantic change")
        if result.get("pipeline_watch_candidate") is not False or result.get("lkg_reference_required") is not True:
            raise ValueError("degraded MFF current weakened pipeline/LKG boundary")
    else:
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "MFF_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
            "PARSER_VERSION_CHANGED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if state not in allowed or result.get("semantic_reconciliation_passed") is not True:
            raise ValueError("healthy MFF reconciliation state drift")
    if result.get("pipeline_watch_candidate") is not (state == "MFF_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"):
        raise ValueError("MFF pipeline-watch signal disagrees with reconciliation state")
    if result.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("MFF LKG crossed current-truth boundary")
    if result.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("MFF programming evidence became material-admission ready")
    if result.get("market_intelligence_only") is not True or result.get("fit_is_not_eligibility") is not True:
        raise ValueError("MFF reconciliation market/fit boundary weakened")
    if result.get("publication_effect") != "NONE":
        raise ValueError("MFF reconciliation crossed publication boundary")
    for flag in MATERIAL_FLAGS:
        if result.get(flag) is not False:
            raise ValueError(f"MFF reconciliation attempted authorization: {flag}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("current")
    ap.add_argument("--previous")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "pipeline_watch_candidate": result["pipeline_watch_candidate"],
        "source_health_watch_candidate": result["source_health_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
