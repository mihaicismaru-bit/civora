#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

SCHEMA = "PARTENER_EU_ESC_PROGRAMME_RECONCILIATION_V1"
CURRENT_SCHEMA = "PARTENER_EU_ESC_PROGRAMME_INTELLIGENCE_V1"
RECONCILER_VERSION = "EU_DIRECT_ESC_PROGRAMME_RECONCILE_V1"
PROGRAMME_ID = "EUROPEAN_SOLIDARITY_CORPS"
PROGRAMME_FAMILY = "European Solidarity Corps"
AUTHORITY_CLASS = "T1_OFFICIAL_EU_PROGRAMME"
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "closed_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
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


def expected_semantic_fingerprint(snapshot: Mapping[str, Any]) -> str:
    return sha256_json(
        {
            "programme_id": snapshot.get("programme_id"),
            "programme_context": snapshot.get("programme_context"),
            "source_inventory": [
                (row.get("source_id"), row.get("observation_state"), row.get("source_semantic_fingerprint"))
                for row in snapshot.get("evidence") or []
            ],
            "fit_tags": list(snapshot.get("applicant_fit_tags") or []),
            "route_tags": list(snapshot.get("application_route_tags") or []),
        }
    )


def validate_snapshot(snapshot: Mapping[str, Any], label: str) -> None:
    if snapshot.get("schema") != CURRENT_SCHEMA:
        raise ValueError(f"{label} ESC snapshot schema drift")
    if snapshot.get("source_family") != "EU_DIRECT" or snapshot.get("programme_id") != PROGRAMME_ID:
        raise ValueError(f"{label} ESC identity drift")
    if snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError(f"{label} ESC programme family drift")
    if snapshot.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError(f"{label} ESC authority drift")
    evidence = snapshot.get("evidence") or []
    if snapshot.get("source_count") != 3 or len(evidence) != 3:
        raise ValueError(f"{label} ESC source inventory drift")
    if int(snapshot.get("healthy_source_count") or 0) + int(snapshot.get("degraded_source_count") or 0) != 3:
        raise ValueError(f"{label} ESC health accounting drift")
    if snapshot.get("source_health_state") not in {"HEALTHY", "DEGRADED"}:
        raise ValueError(f"{label} ESC health state invalid")
    if snapshot.get("current_material_truth_available") is not False:
        raise ValueError(f"{label} ESC programme intelligence became material truth")
    for key in (
        "market_intelligence_only",
        "fit_score_is_not_eligibility",
        "route_intelligence_is_not_call_eligibility",
        "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required",
        "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if snapshot.get(key) is not True:
            raise ValueError(f"{label} ESC intelligence boundary weakened: {key}")
    for flag in MATERIAL_FLAGS:
        if snapshot.get(flag) is not False:
            raise ValueError(f"{label} ESC snapshot became authorizing: {flag}")
    if snapshot.get("publication_effect") != "NONE":
        raise ValueError(f"{label} ESC publication boundary drift")
    if not snapshot.get("fetched_at"):
        raise ValueError(f"{label} ESC fetched_at missing")
    if str(snapshot.get("semantic_fingerprint") or "") != expected_semantic_fingerprint(snapshot):
        raise ValueError(f"{label} ESC semantic fingerprint mismatch")

    allowed_states = {"PROGRAMME_INTELLIGENCE", "CALL_INDEX_DISCOVERY"}
    source_ids: set[str] = set()
    for row in evidence:
        source_id = str(row.get("source_id") or "")
        if not source_id or source_id in source_ids:
            raise ValueError(f"{label} ESC source identity drift")
        source_ids.add(source_id)
        if row.get("programme_id") != PROGRAMME_ID or row.get("source_family") != "EU_DIRECT":
            raise ValueError(f"{label} ESC evidence identity drift")
        if row.get("authority_class") != AUTHORITY_CLASS or row.get("observation_state") not in allowed_states:
            raise ValueError(f"{label} ESC evidence authority/state drift")
        if row.get("material_fact_use") is not False or row.get("current_material_truth_available") is not False:
            raise ValueError(f"{label} ESC evidence became material truth")
        if row.get("source_health") == "HEALTHY":
            if row.get("lkg_required") is not False or row.get("evidence_usable_for_reconciliation") is not True:
                raise ValueError(f"{label} ESC healthy receipt inconsistent")
            for key in ("raw_sha256", "normalized_visible_text_sha256", "source_semantic_fingerprint"):
                if len(str(row.get(key) or "")) != 64:
                    raise ValueError(f"{label} ESC healthy receipt missing {key}")
        elif row.get("source_health") == "DEGRADED":
            if row.get("lkg_required") is not True or row.get("evidence_usable_for_reconciliation") is not False:
                raise ValueError(f"{label} ESC degraded receipt inconsistent")
            if row.get("source_semantic_fingerprint") is not None:
                raise ValueError(f"{label} ESC degraded receipt retained semantic truth")
        else:
            raise ValueError(f"{label} ESC source health invalid")


def identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows = sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
        )
        for row in (snapshot.get("evidence") or [])
    )
    return {
        "source_family": snapshot.get("source_family"),
        "programme_id": snapshot.get("programme_id"),
        "programme_family": snapshot.get("programme_family"),
        "authority_class": snapshot.get("authority_class"),
        "source_inventory": rows,
    }


def semantic_view(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows: dict[str, dict[str, Any]] = {}
    for row in snapshot.get("evidence") or []:
        rows[str(row.get("source_id") or "")] = {
            "observation_state": row.get("observation_state"),
            "source_semantic_fingerprint": row.get("source_semantic_fingerprint"),
        }
    return {
        "programme_id": snapshot.get("programme_id"),
        "programme_context": snapshot.get("programme_context"),
        "evidence": rows,
        "applicant_fit_tags": list(snapshot.get("applicant_fit_tags") or []),
        "application_route_tags": list(snapshot.get("application_route_tags") or []),
    }


def semantic_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = semantic_view(previous)
    after = semantic_view(current)
    changes: list[dict[str, Any]] = []
    for source_id in sorted(set(before["evidence"]) | set(after["evidence"])):
        b = before["evidence"].get(source_id)
        a = after["evidence"].get(source_id)
        if b != a:
            changes.append({"kind": "SOURCE_SEMANTICS_CHANGED", "source_id": source_id, "before": b, "after": a})
    for field in ("programme_context", "applicant_fit_tags", "application_route_tags"):
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
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous, "previous")
        previous_identity_match = identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("ESC previous source/programme identity mismatch")
        if parse_time(str(previous["fetched_at"])) >= parse_time(str(current["fetched_at"])):
            raise ValueError("ESC previous snapshot is not older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health_state") == "HEALTHY" and int(previous.get("degraded_source_count") or 0) == 0
        previous_sha = sha256_json(previous)

    if not current_healthy:
        state = "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        source_health_watch_candidate = True
        market_watch_candidate = False
        discovery_watch_candidate = False
        lkg_reference_required = True
        lkg_reference_available = bool(previous_valid and previous_healthy)
        baseline_captured = False
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        market_watch_candidate = False
        discovery_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = True
        market_watch_candidate = False
        discovery_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    else:
        changes = semantic_changes(previous, current)
        if changes:
            state = "ESC_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            market_watch_candidate = True
            changed_sources = {str(change.get("source_id") or "") for change in changes if change.get("kind") == "SOURCE_SEMANTICS_CHANGED"}
            current_rows = {str(row.get("source_id") or ""): row for row in current.get("evidence") or []}
            discovery_watch_candidate = any(current_rows.get(source_id, {}).get("observation_state") == "CALL_INDEX_DISCOVERY" for source_id in changed_sources)
        else:
            state = "NO_CHANGE"
            market_watch_candidate = False
            discovery_watch_candidate = False
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = True
        baseline_captured = False

    result: dict[str, Any] = {
        "schema": SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": current["source_family"],
        "programme_family": current["programme_family"],
        "programme_id": current["programme_id"],
        "authority_class": current["authority_class"],
        "observation_state": "PROGRAMME_INTELLIGENCE_RECONCILED_NON_AUTHORIZING",
        "current_run_id": current["run_id"],
        "current_fetched_at": current["fetched_at"],
        "current_snapshot_sha256": sha256_json(current),
        "current_semantic_fingerprint": current["semantic_fingerprint"],
        "current_source_health_state": current["source_health_state"],
        "previous_snapshot_sha256": previous_sha,
        "previous_identity_match": previous_identity_match,
        "reconciliation_state": state,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "market_watch_candidate": market_watch_candidate,
        "call_index_discovery_watch_candidate": discovery_watch_candidate,
        "pipeline_watch_candidate": False,
        "source_health_watch_candidate": source_health_watch_candidate,
        "baseline_captured": baseline_captured,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": lkg_reference_available,
        "lkg_reference_is_current_truth": False,
        "market_intelligence_only": True,
        "fit_score_is_not_eligibility": True,
        "route_intelligence_is_not_call_eligibility": True,
        "call_index_discovery_is_not_open_call": True,
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_endpoint_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["reconciliation_fingerprint"] = sha256_json(
        {
            "identity": current_identity,
            "state": state,
            "current_semantic_fingerprint": current["semantic_fingerprint"],
            "previous_snapshot_sha256": previous_sha,
            "semantic_changes": changes,
            "current_source_health_state": current["source_health_state"],
        }
    )
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("current")
    ap.add_argument("--previous")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    current = json.loads(pathlib.Path(args.current).read_text(encoding="utf-8"))
    previous = json.loads(pathlib.Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    path = pathlib.Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "programme_id": result["programme_id"],
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "market_watch_candidate": result["market_watch_candidate"],
        "call_index_discovery_watch_candidate": result["call_index_discovery_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
