#!/usr/bin/env python3
"""Fail-closed reconciliation for EEA/Norway Grants Romania 2021-2028 programming intelligence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

SNAPSHOT_SCHEMA = "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_EVIDENCE_V2"
RECONCILIATION_SCHEMA = "PARTENER_EU_EEA_ROMANIA_PROGRAMMING_RECONCILIATION_V1"
RECONCILER_VERSION = "EEA_ROMANIA_PROGRAMMING_RECONCILE_V1"
SOURCE_FAMILY = "EEA_NORWAY"
PROGRAMME_FAMILY = "EEA and Norway Grants Romania 2021-2028"
OBSERVATION_STATE = "PROGRAMMING_PIPELINE"
EXPECTED_SOURCE_ID = "SRC-EEA-FMO-ROMANIA-2021-2028-PROGRAMMES"
EXPECTED_AUTHORITY_URL = "https://eeagrants.org/en/fmo/news/renewed-cooperation-romania"
EXPECTED_PROGRAMME_COUNT = 9

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


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EEA programming timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _programme_identity(snapshot: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(row.get("programme_id") or "") for row in snapshot.get("records") or []))


def identity(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    source = snapshot.get("source") or {}
    return (
        snapshot.get("source_family"),
        snapshot.get("programme_family"),
        source.get("id"),
        source.get("url"),
    )


def _validate_material_boundary(value: Mapping[str, Any], *, label: str) -> None:
    if value.get("observation_state") not in {OBSERVATION_STATE, "PROGRAMMING_PIPELINE_RECONCILED_NON_AUTHORIZING"}:
        raise ValueError(f"{label} observation state drift")
    if value.get("publication_effect") != "NONE":
        raise ValueError(f"{label} publication boundary drift")
    for flag in MATERIAL_FLAGS:
        if value.get(flag, False) is not False:
            raise ValueError(f"{label} attempted material authorization: {flag}")


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError("EEA programming snapshot schema drift")
    if snapshot.get("source_family") != SOURCE_FAMILY or snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA programming family drift")
    _validate_material_boundary(snapshot, label="EEA programming snapshot")
    if snapshot.get("requires_reconciliation") is not True:
        raise ValueError("EEA programming snapshot lost reconciliation requirement")
    if snapshot.get("current_material_truth_available") is not False:
        raise ValueError("EEA programming snapshot became current material truth")
    if snapshot.get("fit_is_not_eligibility") is not True or snapshot.get("market_intelligence_only") is not True:
        raise ValueError("EEA programming market/fit boundary weakened")
    source = snapshot.get("source") or {}
    if source.get("id") != EXPECTED_SOURCE_ID or source.get("url") != EXPECTED_AUTHORITY_URL:
        raise ValueError("EEA programming authority identity drift")
    health = snapshot.get("source_health_state")
    if health == "HEALTHY":
        if snapshot.get("evidence_usable_for_reconciliation") is not True or snapshot.get("lkg_required") is not False:
            raise ValueError("healthy EEA programming snapshot has inconsistent health gates")
        records = list(snapshot.get("records") or [])
        if len(records) != EXPECTED_PROGRAMME_COUNT or len(set(_programme_identity(snapshot))) != EXPECTED_PROGRAMME_COUNT:
            raise ValueError("healthy EEA programming snapshot programme inventory drift")
        for row in records:
            if row.get("observation_state") != OBSERVATION_STATE or row.get("not_a_call") is not True:
                raise ValueError("EEA programme row crossed programming-only boundary")
            if row.get("requires_reconciliation") is not True or row.get("material_fact_use") is not False:
                raise ValueError("EEA programme row weakened reconciliation/material boundary")
            for flag in MATERIAL_FLAGS:
                if row.get(flag, False) is not False:
                    raise ValueError(f"EEA programme row attempted authorization: {flag}")
            if not re.fullmatch(r"[0-9a-f]{64}", str(row.get("semantic_fingerprint") or "")):
                raise ValueError("EEA programme row missing semantic fingerprint")
        if not re.fullmatch(r"[0-9a-f]{64}", str(snapshot.get("semantic_fingerprint") or "")):
            raise ValueError("healthy EEA programming snapshot missing semantic fingerprint")
        if source.get("http_status") != 200 or not re.fullmatch(r"[0-9a-f]{64}", str(source.get("raw_hash") or "")):
            raise ValueError("healthy EEA programming source receipt inconsistent")
    elif health == "DEGRADED":
        if snapshot.get("evidence_usable_for_reconciliation") is not False or snapshot.get("lkg_required") is not True:
            raise ValueError("degraded EEA programming snapshot weakened fail-closed state")
        if snapshot.get("records") not in ([], None) or snapshot.get("semantic_fingerprint") is not None:
            raise ValueError("degraded EEA programming snapshot fabricated semantic evidence")
        if source.get("raw_hash") is not None:
            raise ValueError("degraded EEA programming snapshot fabricated raw hash")
        if not str(snapshot.get("failure_class") or "").strip():
            raise ValueError("degraded EEA programming snapshot missing failure class")
    else:
        raise ValueError("EEA programming source health state drift")


def _semantic_view(snapshot: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "programme_id": row.get("programme_id"),
            "semantic_fingerprint": row.get("semantic_fingerprint"),
            "programme_operator": row.get("programme_operator"),
            "fund_operator": row.get("fund_operator"),
        }
        for row in sorted(snapshot.get("records") or [], key=lambda row: str(row.get("programme_id") or ""))
    ]


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(current)
    current_healthy = current.get("source_health_state") == "HEALTHY"
    previous_valid = False
    previous_healthy = False
    previous_sha = None
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous)
        if identity(previous) != identity(current):
            raise ValueError("EEA programming previous authority identity mismatch")
        if _parse_time(str(previous.get("fetched_at") or "")) >= _parse_time(str(current.get("fetched_at") or "")):
            raise ValueError("EEA programming previous snapshot is not strictly older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health_state") == "HEALTHY"
        previous_sha = _sha256_json(previous)
        if current_healthy and previous_healthy and _programme_identity(previous) != _programme_identity(current):
            raise ValueError("EEA programming previous programme identity mismatch")

    if not current_healthy:
        state = "CURRENT_PROGRAMMING_AUTHORITY_DEGRADED_LKG_REQUIRED"
        semantic_passed = False
        programming_watch_candidate = False
        source_health_watch_candidate = True
        lkg_required = True
        lkg_available = bool(previous_valid and previous_healthy)
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_passed = True
        programming_watch_candidate = False
        source_health_watch_candidate = False
        lkg_required = False
        lkg_available = False
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_passed = True
        programming_watch_candidate = False
        source_health_watch_candidate = True
        lkg_required = False
        lkg_available = False
    else:
        before = _semantic_view(previous)
        after = _semantic_view(current)
        if before != after:
            changes.append({"kind": "EEA_ROMANIA_PROGRAMMING_SEMANTICS_CHANGED", "before": before, "after": after})
            state = "EEA_ROMANIA_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            programming_watch_candidate = True
        else:
            state = "NO_CHANGE"
            programming_watch_candidate = False
        semantic_passed = True
        source_health_watch_candidate = False
        lkg_required = False
        lkg_available = True

    result: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": "EEA_FMO_ROMANIA_PROGRAMME_MAP",
        "observation_state": "PROGRAMMING_PIPELINE_RECONCILED_NON_AUTHORIZING",
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_snapshot_sha256": _sha256_json(current),
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "current_source_health_state": current.get("source_health_state"),
        "previous_snapshot_sha256": previous_sha,
        "previous_available": previous_valid,
        "previous_healthy": previous_healthy,
        "reconciliation_state": state,
        "semantic_reconciliation_passed": semantic_passed,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "programming_watch_candidate": programming_watch_candidate,
        "source_health_watch_candidate": source_health_watch_candidate,
        "lkg_reference_required": lkg_required,
        "lkg_reference_available": lkg_available,
        "lkg_reference_is_current_truth": False,
        "market_intelligence_only": True,
        "fit_is_not_eligibility": True,
        "exact_call_or_topic_identifier_required": True,
        "current_official_exact_call_endpoint_required": True,
        "field_scoped_material_admission_required": True,
        "material_admission_ready_for_downstream_review": False,
        "current_material_truth_available": False,
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        result[flag] = False
    result["reconciliation_fingerprint"] = _sha256_json({
        "identity": identity(current),
        "state": state,
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "previous_snapshot_sha256": previous_sha,
        "semantic_changes": changes,
        "current_source_health_state": current.get("source_health_state"),
    })
    validate_reconciliation(result, current=current)
    return result


def validate_reconciliation(result: Mapping[str, Any], *, current: Mapping[str, Any]) -> None:
    if result.get("schema") != RECONCILIATION_SCHEMA or result.get("reconciler_version") != RECONCILER_VERSION:
        raise ValueError("EEA programming reconciliation schema/version drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA programming reconciliation family drift")
    _validate_material_boundary(result, label="EEA programming reconciliation")
    if result.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("EEA programming LKG crossed current-truth boundary")
    if result.get("material_admission_ready_for_downstream_review") is not False or result.get("current_material_truth_available") is not False:
        raise ValueError("EEA programming reconciliation became material truth/admission ready")
    state = result.get("reconciliation_state")
    if current.get("source_health_state") == "DEGRADED":
        if state != "CURRENT_PROGRAMMING_AUTHORITY_DEGRADED_LKG_REQUIRED":
            raise ValueError("degraded EEA programming current did not fail closed")
        if result.get("semantic_reconciliation_passed") is not False or result.get("programming_watch_candidate") is not False:
            raise ValueError("degraded EEA programming current emitted semantic watch")
    else:
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "EEA_ROMANIA_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if state not in allowed or result.get("semantic_reconciliation_passed") is not True:
            raise ValueError("healthy EEA programming reconciliation state drift")
    if result.get("programming_watch_candidate") is not (state == "EEA_ROMANIA_PROGRAMMING_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"):
        raise ValueError("EEA programming watch signal disagrees with reconciliation state")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("current")
    ap.add_argument("--previous")
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    current = json.loads(Path(args.current).read_text(encoding="utf-8"))
    previous = json.loads(Path(args.previous).read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "programming_watch_candidate": result["programming_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
