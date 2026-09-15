#!/usr/bin/env python3
"""Fail-closed same-identity reconciliation for LIFE programme intelligence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "PARTENER_EU_LIFE_PROGRAMME_RECONCILIATION_V1"
CURRENT_SCHEMA = "PARTENER_EU_LIFE_PROGRAMME_INTELLIGENCE_V1"
RECONCILER_VERSION = "EU_DIRECT_LIFE_PROGRAMME_RECONCILE_V1"
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
    "canonical_corpus_mutation",
)


def sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _programme_row(snapshot: Mapping[str, Any]) -> Mapping[str, Any]:
    rows = snapshot.get("programme_intelligence") or []
    if len(rows) != 1 or rows[0].get("programme_family") != "LIFE":
        raise ValueError("LIFE programme intelligence row missing")
    return rows[0]


def validate_snapshot(snapshot: Mapping[str, Any], label: str) -> None:
    if snapshot.get("schema") != CURRENT_SCHEMA:
        raise ValueError(f"{label} LIFE snapshot schema drift")
    if snapshot.get("source_family") != "EU_DIRECT" or snapshot.get("programme_families") != ["LIFE"]:
        raise ValueError(f"{label} LIFE identity drift")
    if snapshot.get("programme_id", "LIFE") != "LIFE" or snapshot.get("programme_family", "LIFE") != "LIFE":
        raise ValueError(f"{label} LIFE programme identity drift")
    if snapshot.get("source_count") != 4 or len(snapshot.get("sources") or []) != 4:
        raise ValueError(f"{label} LIFE source inventory drift")
    if int(snapshot.get("healthy_source_count") or 0) + int(snapshot.get("degraded_source_count") or 0) != 4:
        raise ValueError(f"{label} LIFE health accounting drift")
    if snapshot.get("source_health_state") not in {"HEALTHY", "DEGRADED"}:
        raise ValueError(f"{label} LIFE health state invalid")
    if snapshot.get("market_intelligence_only") is not True or snapshot.get("fit_scores_are_not_eligibility") is not True:
        raise ValueError(f"{label} LIFE intelligence boundary weakened")
    for flag in MATERIAL_FLAGS:
        if snapshot.get(flag) is not False:
            raise ValueError(f"{label} LIFE snapshot became authorizing: {flag}")
    if snapshot.get("publication_effect") != "NONE":
        raise ValueError(f"{label} LIFE publication boundary drift")
    if not snapshot.get("fetched_at"):
        raise ValueError(f"{label} LIFE fetched_at missing")
    healthy = snapshot.get("source_health_state") == "HEALTHY" and int(snapshot.get("degraded_source_count") or 0) == 0
    if healthy and len(str(snapshot.get("semantic_fingerprint") or "")) != 64:
        raise ValueError(f"{label} healthy LIFE semantic fingerprint missing")
    if not healthy and snapshot.get("semantic_fingerprint") is not None:
        if str(snapshot.get("parser_version") or "") != "LIFE_PROGRAMME_INTELLIGENCE_V1":
            raise ValueError(f"{label} degraded LIFE semantic fingerprint must be null")
    _programme_row(snapshot)


def identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    inventory = sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
        )
        for row in snapshot.get("sources") or []
    )
    return {
        "source_family": snapshot.get("source_family"),
        "programme_id": snapshot.get("programme_id", "LIFE"),
        "programme_family": snapshot.get("programme_family", "LIFE"),
        "source_inventory": inventory,
    }


def semantic_view(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    programme = _programme_row(snapshot)
    sources = {
        str(row.get("source_id") or ""): {
            "observation_state": row.get("observation_state"),
            "source_semantic_fingerprint": row.get("source_semantic_fingerprint"),
        }
        for row in snapshot.get("sources") or []
    }
    return {
        "sources": sources,
        "market_signals": list(programme.get("market_signals") or []),
        "applicant_fit_tags": list(programme.get("applicant_fit_tags") or []),
        "pipeline_signals": list(programme.get("pipeline_signals") or []),
    }


def semantic_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = semantic_view(previous)
    after = semantic_view(current)
    changes: list[dict[str, Any]] = []
    for source_id in sorted(set(before["sources"]) | set(after["sources"])):
        old = before["sources"].get(source_id)
        new = after["sources"].get(source_id)
        if old != new:
            changes.append({"kind": "SOURCE_SEMANTICS_CHANGED", "source_id": source_id, "before": old, "after": new})
    for field in ("market_signals", "applicant_fit_tags", "pipeline_signals"):
        if before[field] != after[field]:
            changes.append({"kind": "PROGRAMME_INTELLIGENCE_CHANGED", "field": field, "before": before[field], "after": after[field]})
    return changes


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(current, "current")
    current_identity = identity(current)
    current_healthy = current.get("source_health_state") == "HEALTHY" and int(current.get("degraded_source_count") or 0) == 0

    previous_valid = False
    previous_healthy = False
    previous_sha = None
    previous_identity_match = None
    parser_migration = False
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous, "previous")
        previous_identity_match = identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("LIFE previous source/programme identity mismatch")
        if parse_time(str(previous["fetched_at"])) >= parse_time(str(current["fetched_at"])):
            raise ValueError("LIFE previous snapshot is not older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health_state") == "HEALTHY" and int(previous.get("degraded_source_count") or 0) == 0
        previous_sha = sha256_json(previous)
        parser_migration = str(previous.get("parser_version") or "") != str(current.get("parser_version") or "")

    if not current_healthy:
        state = "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        source_health_watch_candidate = True
        pipeline_watch_candidate = False
        lkg_reference_required = True
        lkg_reference_available = bool(previous_valid and previous_healthy)
        baseline_captured = False
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        pipeline_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = True
        pipeline_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif parser_migration:
        state = "PARSER_VERSION_CHANGED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        pipeline_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = True
    else:
        changes = semantic_changes(previous, current)
        if changes:
            state = "LIFE_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            pipeline_watch_candidate = True
        else:
            state = "NO_CHANGE"
            pipeline_watch_candidate = False
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = False

    result = {
        "schema": SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "LIFE",
        "programme_id": "LIFE",
        "authority_class": current["authority_class"],
        "observation_state": "PROGRAMME_INTELLIGENCE_RECONCILED_NON_AUTHORIZING",
        "current_run_id": current["run_id"],
        "current_fetched_at": current["fetched_at"],
        "current_parser_version": current.get("parser_version"),
        "previous_parser_version": previous.get("parser_version") if previous else None,
        "parser_migration_baseline": parser_migration and current_healthy and previous_healthy,
        "current_snapshot_sha256": sha256_json(current),
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "current_source_health_state": current["source_health_state"],
        "previous_snapshot_sha256": previous_sha,
        "previous_identity_match": previous_identity_match,
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
        "fit_score_is_not_eligibility": True,
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_endpoint_required": True,
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
        "current_source_health_state": current["source_health_state"],
    })
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("current")
    ap.add_argument("--previous")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_id": "LIFE",
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "pipeline_watch_candidate": result["pipeline_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
