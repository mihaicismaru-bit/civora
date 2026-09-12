#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

SCHEMA = "PARTENER_EU_I3_PROGRAMME_RECONCILIATION_V1"
CURRENT_SCHEMA = "PARTENER_EU_I3_PROGRAMME_INTELLIGENCE_V1"
RECONCILER_VERSION = "EU_DIRECT_I3_PROGRAMME_RECONCILE_V1"
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


def validate_snapshot(snapshot: Mapping[str, Any], label: str) -> None:
    if snapshot.get("schema") != CURRENT_SCHEMA:
        raise ValueError(f"{label} I3 snapshot schema drift")
    if snapshot.get("source_family") != "EU_DIRECT" or snapshot.get("programme_id") != "I3":
        raise ValueError(f"{label} I3 identity drift")
    if snapshot.get("programme_family") != "Interregional Innovation Investments (I3) Instrument":
        raise ValueError(f"{label} I3 programme family drift")
    if snapshot.get("authority_class") != "T1_EISMEA_OFFICIAL":
        raise ValueError(f"{label} I3 authority drift")
    if snapshot.get("source_count") != 5 or len(snapshot.get("evidence") or []) != 5:
        raise ValueError(f"{label} I3 source inventory drift")
    if int(snapshot.get("healthy_source_count") or 0) + int(snapshot.get("degraded_source_count") or 0) != 5:
        raise ValueError(f"{label} I3 health accounting drift")
    if snapshot.get("source_health_state") not in {"HEALTHY", "DEGRADED"}:
        raise ValueError(f"{label} I3 health state invalid")
    for key in (
        "market_intelligence_only",
        "fit_score_is_not_eligibility",
        "geography_fit_is_not_eligibility",
        "partner_intelligence_is_not_call_eligibility",
        "exact_call_or_topic_identifier_required",
        "current_official_exact_endpoint_required",
        "structured_funding_tenders_reconciliation_required",
        "semantic_reconciliation_required",
        "field_scoped_material_admission_required",
    ):
        if snapshot.get(key) is not True:
            raise ValueError(f"{label} I3 intelligence boundary weakened: {key}")
    for flag in MATERIAL_FLAGS:
        if snapshot.get(flag) is not False:
            raise ValueError(f"{label} I3 snapshot became authorizing: {flag}")
    if snapshot.get("publication_effect") != "NONE":
        raise ValueError(f"{label} I3 publication boundary drift")
    if len(str(snapshot.get("semantic_fingerprint") or "")) != 64:
        raise ValueError(f"{label} I3 semantic fingerprint missing")
    if not snapshot.get("fetched_at"):
        raise ValueError(f"{label} I3 fetched_at missing")


def identity(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    rows = sorted(
        (
            str(row.get("source_id") or ""),
            str(row.get("authority_url") or ""),
            str(row.get("observation_state") or ""),
            str(row.get("call_reference_hint") or ""),
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
            "call_reference_hint": row.get("call_reference_hint"),
            "source_semantic_fingerprint": row.get("source_semantic_fingerprint"),
        }
    return {
        "programme_id": snapshot.get("programme_id"),
        "evidence": rows,
        "applicant_fit_tags": list(snapshot.get("applicant_fit_tags") or []),
        "geography_fit_tags": list(snapshot.get("geography_fit_tags") or []),
        "partner_intelligence_tags": list(snapshot.get("partner_intelligence_tags") or []),
    }


def semantic_changes(previous: Mapping[str, Any], current: Mapping[str, Any]) -> list[dict[str, Any]]:
    before = semantic_view(previous)
    after = semantic_view(current)
    changes: list[dict[str, Any]] = []
    for source_id in sorted(set(before["evidence"]) | set(after["evidence"])):
        b = before["evidence"].get(source_id)
        a = after["evidence"].get(source_id)
        if b != a:
            changes.append({
                "kind": "SOURCE_SEMANTICS_CHANGED",
                "source_id": source_id,
                "before": b,
                "after": a,
            })
    for field in ("applicant_fit_tags", "geography_fit_tags", "partner_intelligence_tags"):
        if before[field] != after[field]:
            changes.append({
                "kind": "PROGRAMME_INTELLIGENCE_CHANGED",
                "field": field,
                "before": before[field],
                "after": after[field],
            })
    return changes


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(current, "current")
    current_identity = identity(current)
    current_healthy = (
        current.get("source_health_state") == "HEALTHY"
        and int(current.get("degraded_source_count") or 0) == 0
    )

    previous_valid = False
    previous_healthy = False
    previous_sha = None
    previous_identity_match = None
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous, "previous")
        previous_identity_match = identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("I3 previous source/programme identity mismatch")
        if parse_time(str(previous["fetched_at"])) >= parse_time(str(current["fetched_at"])):
            raise ValueError("I3 previous snapshot is not older than current")
        previous_valid = True
        previous_healthy = (
            previous.get("source_health_state") == "HEALTHY"
            and int(previous.get("degraded_source_count") or 0) == 0
        )
        previous_sha = sha256_json(previous)

    if not current_healthy:
        state = "CURRENT_SOURCE_HEALTH_DEGRADED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        source_health_watch_candidate = True
        market_watch_candidate = False
        pipeline_watch_candidate = False
        lkg_reference_required = True
        lkg_reference_available = bool(previous_valid and previous_healthy)
        baseline_captured = False
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = False
        market_watch_candidate = False
        pipeline_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
        source_health_watch_candidate = True
        market_watch_candidate = False
        pipeline_watch_candidate = False
        lkg_reference_required = False
        lkg_reference_available = False
        baseline_captured = True
    else:
        changes = semantic_changes(previous, current)
        if changes:
            state = "I3_PROGRAMME_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            market_watch_candidate = True
            changed_sources = {
                str(change.get("source_id") or "")
                for change in changes
                if change.get("kind") == "SOURCE_SEMANTICS_CHANGED"
            }
            current_rows = {
                str(row.get("source_id") or ""): row
                for row in current.get("evidence") or []
            }
            pipeline_watch_candidate = any(
                current_rows.get(source_id, {}).get("observation_state") == "PROGRAMMING_PIPELINE"
                for source_id in changed_sources
            )
        else:
            state = "NO_CHANGE"
            market_watch_candidate = False
            pipeline_watch_candidate = False
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
        "pipeline_watch_candidate": pipeline_watch_candidate,
        "source_health_watch_candidate": source_health_watch_candidate,
        "baseline_captured": baseline_captured,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": lkg_reference_available,
        "lkg_reference_is_current_truth": False,
        "market_intelligence_only": True,
        "fit_score_is_not_eligibility": True,
        "geography_fit_is_not_eligibility": True,
        "partner_intelligence_is_not_call_eligibility": True,
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_endpoint_required": True,
        "structured_funding_tenders_reconciliation_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["reconciliation_fingerprint"] = sha256_json({
        "identity": current_identity,
        "state": state,
        "current_semantic_fingerprint": current["semantic_fingerprint"],
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
        "pipeline_watch_candidate": result["pipeline_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
