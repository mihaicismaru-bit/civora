#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for the Romania EEA/Norway multi-source programme/discovery watch."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from eea_norway_romania_programme_watch import (
    AUTHORITY_CLASS,
    CIVIL_SOCIETY_CALLS_URL,
    EEA_MOU_URL,
    MATERIAL_FLAGS,
    NFP_DIRECTORY_URL,
    NORWAY_MOU_URL,
    OBSERVATION_STATE,
    PARSER_VERSION,
    PROGRAMME_FAMILY,
    ROMANIA_COOPERATION_URL,
    SCHEMA as SNAPSHOT_SCHEMA,
    SOURCE_FAMILY,
    validate_receipt,
)

RECONCILIATION_SCHEMA = "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_RECONCILIATION_V1"
RECONCILER_VERSION = "EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_RECONCILE_V1"
RECONCILED_OBSERVATION_STATE = "PROGRAMME_AND_CALL_DISCOVERY_RECONCILED_NON_AUTHORIZING"
EXPECTED_AUTHORITY_URLS = tuple(sorted((
    ROMANIA_COOPERATION_URL,
    EEA_MOU_URL,
    NORWAY_MOU_URL,
    NFP_DIRECTORY_URL,
    CIVIL_SOCIETY_CALLS_URL,
)))


def _sha256_json(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EEA/Norway Romania watch timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def prepare_healthy_snapshot(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Add canonical health/reconciliation gates without altering source semantics."""
    validate_receipt(receipt)
    value = dict(receipt)
    value.update({
        "authority_urls": list(EXPECTED_AUTHORITY_URLS),
        "evidence_usable_for_reconciliation": True,
        "lkg_required": False,
        "requires_reconciliation": True,
        "current_material_truth_available": False,
        "fit_is_not_eligibility": True,
    })
    for flag in MATERIAL_FLAGS:
        value[flag] = False
    return value


def build_degraded_snapshot(*, run_id: str, fetched_at: str, failure_class: str, failure_detail: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema": SNAPSHOT_SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "source_health": "DEGRADED",
        "market_intelligence_only": True,
        "authority_urls": list(EXPECTED_AUTHORITY_URLS),
        "sources": [],
        "programme_fit_evidence": None,
        "programmes": [],
        "programming_observations": [],
        "national_focal_point_observation": None,
        "call_discovery": [],
        "semantic_fingerprint": None,
        "failure_class": failure_class,
        "failure_detail": str(failure_detail)[:1000],
        "evidence_usable_for_reconciliation": False,
        "lkg_required": True,
        "requires_reconciliation": True,
        "current_material_truth_available": False,
        "fit_is_not_eligibility": True,
        "missing_for_open_call_confirmation": [
            "selected exact call identifier",
            "fresh call-specific official endpoint readback",
            "semantic reconciliation against same-identity previous exact evidence",
            "field-scoped material admission",
        ],
        "publication_effect": "NONE",
    }
    for flag in MATERIAL_FLAGS:
        value[flag] = False
    return value


def _validate_boundary(value: Mapping[str, Any], *, label: str) -> None:
    if value.get("publication_effect") != "NONE":
        raise ValueError(f"{label} publication boundary drift")
    for flag in MATERIAL_FLAGS:
        if value.get(flag, False) is not False:
            raise ValueError(f"{label} attempted material authorization: {flag}")
    if value.get("current_material_truth_available") is not False:
        raise ValueError(f"{label} became current material truth")
    if value.get("fit_is_not_eligibility") is not True or value.get("market_intelligence_only") is not True:
        raise ValueError(f"{label} weakened market/fit boundary")


def validate_snapshot(snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("schema") != SNAPSHOT_SCHEMA or snapshot.get("parser_version") != PARSER_VERSION:
        raise ValueError("EEA/Norway Romania watch snapshot schema/parser drift")
    if snapshot.get("source_family") != SOURCE_FAMILY or snapshot.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA/Norway Romania watch family drift")
    if snapshot.get("authority_class") != AUTHORITY_CLASS or snapshot.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("EEA/Norway Romania watch authority/observation drift")
    if tuple(sorted(snapshot.get("authority_urls") or ())) != EXPECTED_AUTHORITY_URLS:
        raise ValueError("EEA/Norway Romania watch bounded authority identity drift")
    if snapshot.get("requires_reconciliation") is not True:
        raise ValueError("EEA/Norway Romania watch lost reconciliation requirement")
    _validate_boundary(snapshot, label="EEA/Norway Romania watch snapshot")

    health = snapshot.get("source_health")
    if health == "HEALTHY":
        validate_receipt(snapshot)
        if snapshot.get("evidence_usable_for_reconciliation") is not True or snapshot.get("lkg_required") is not False:
            raise ValueError("healthy EEA/Norway Romania watch has inconsistent health gates")
        if len(snapshot.get("sources") or []) != len(EXPECTED_AUTHORITY_URLS):
            raise ValueError("healthy EEA/Norway Romania watch lost bounded source inventory")
        if not str(snapshot.get("semantic_fingerprint") or ""):
            raise ValueError("healthy EEA/Norway Romania watch missing semantic fingerprint")
    elif health == "DEGRADED":
        if snapshot.get("evidence_usable_for_reconciliation") is not False or snapshot.get("lkg_required") is not True:
            raise ValueError("degraded EEA/Norway Romania watch weakened fail-closed state")
        if snapshot.get("semantic_fingerprint") is not None:
            raise ValueError("degraded EEA/Norway Romania watch fabricated semantic fingerprint")
        if snapshot.get("sources") not in ([], None) or snapshot.get("programmes") not in ([], None) or snapshot.get("call_discovery") not in ([], None):
            raise ValueError("degraded EEA/Norway Romania watch fabricated current evidence")
        if not str(snapshot.get("failure_class") or "").strip():
            raise ValueError("degraded EEA/Norway Romania watch missing failure class")
    else:
        raise ValueError("EEA/Norway Romania watch source health drift")


def identity(snapshot: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        snapshot.get("source_family"),
        snapshot.get("programme_family"),
        snapshot.get("authority_class"),
        tuple(sorted(snapshot.get("authority_urls") or ())),
    )


def _semantic_view(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    if snapshot.get("source_health") != "HEALTHY":
        return {}
    programmes = sorted(
        ({"programme": row.get("programme"), "operator": row.get("operator")} for row in snapshot.get("programmes") or []),
        key=lambda row: (str(row.get("programme") or ""), str(row.get("operator") or "")),
    )
    programming = sorted(
        ({"title": row.get("title"), "source_url": row.get("source_url")} for row in snapshot.get("programming_observations") or []),
        key=lambda row: (str(row.get("title") or ""), str(row.get("source_url") or "")),
    )
    calls = sorted(
        ({"label": row.get("label"), "url": row.get("url")} for row in snapshot.get("call_discovery") or []),
        key=lambda row: str(row.get("url") or ""),
    )
    fit = snapshot.get("programme_fit_evidence") or {}
    nfp = snapshot.get("national_focal_point_observation") or {}
    return {
        "programmes": programmes,
        "programming_observations": programming,
        "national_focal_point_state": nfp.get("state"),
        "call_discovery": calls,
        "programme_fit_facts": fit.get("facts") or {},
    }


def _change_set(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    kinds = {
        "programmes": "PROGRAMME_OPERATOR_MAP_CHANGED",
        "programming_observations": "PROGRAMMING_DOCUMENT_SET_CHANGED",
        "national_focal_point_state": "NFP_DIRECTORY_STATE_CHANGED",
        "call_discovery": "CALL_DISCOVERY_SET_CHANGED",
        "programme_fit_facts": "PROGRAMME_FIT_FACTS_CHANGED",
    }
    for key, kind in kinds.items():
        if before.get(key) != after.get(key):
            changes.append({"kind": kind, "before": before.get(key), "after": after.get(key)})
    return changes


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(current)
    current_healthy = current.get("source_health") == "HEALTHY"
    previous_valid = False
    previous_healthy = False
    previous_sha = None
    changes: list[dict[str, Any]] = []

    if previous is not None:
        validate_snapshot(previous)
        if identity(previous) != identity(current):
            raise ValueError("EEA/Norway Romania watch previous authority identity mismatch")
        if _parse_time(str(previous.get("fetched_at") or "")) >= _parse_time(str(current.get("fetched_at") or "")):
            raise ValueError("EEA/Norway Romania watch previous snapshot is not strictly older than current")
        previous_valid = True
        previous_healthy = previous.get("source_health") == "HEALTHY"
        previous_sha = _sha256_json(previous)

    call_index_watch = False
    programming_watch = False
    source_health_watch = False
    if not current_healthy:
        state = "CURRENT_EEA_NORWAY_ROMANIA_WATCH_DEGRADED_LKG_REQUIRED"
        semantic_passed = False
        source_health_watch = True
        lkg_required = True
        lkg_available = bool(previous_valid and previous_healthy)
    elif not previous_valid:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_passed = True
        lkg_required = False
        lkg_available = False
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_passed = True
        source_health_watch = True
        lkg_required = False
        lkg_available = False
    else:
        changes = _change_set(_semantic_view(previous), _semantic_view(current))
        if changes:
            state = "EEA_NORWAY_ROMANIA_DISCOVERY_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            call_index_watch = any(row.get("kind") == "CALL_DISCOVERY_SET_CHANGED" for row in changes)
            programming_watch = any(row.get("kind") != "CALL_DISCOVERY_SET_CHANGED" for row in changes)
        else:
            state = "NO_CHANGE"
        semantic_passed = True
        lkg_required = False
        lkg_available = True

    result: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": RECONCILED_OBSERVATION_STATE,
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_snapshot_sha256": _sha256_json(current),
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "current_source_health": current.get("source_health"),
        "previous_snapshot_sha256": previous_sha,
        "previous_available": previous_valid,
        "previous_healthy": previous_healthy,
        "reconciliation_state": state,
        "semantic_reconciliation_passed": semantic_passed,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "programming_watch_candidate": programming_watch,
        "call_index_discovery_watch_candidate": call_index_watch,
        "source_health_watch_candidate": source_health_watch,
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
        "semantic_changes": changes,
        "current_source_health": current.get("source_health"),
        "previous_snapshot_sha256": previous_sha,
    })
    validate_reconciliation(result, current=current)
    return result


def validate_reconciliation(result: Mapping[str, Any], *, current: Mapping[str, Any]) -> None:
    if result.get("schema") != RECONCILIATION_SCHEMA or result.get("reconciler_version") != RECONCILER_VERSION:
        raise ValueError("EEA/Norway Romania watch reconciliation schema/version drift")
    if result.get("source_family") != SOURCE_FAMILY or result.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA/Norway Romania watch reconciliation family drift")
    if result.get("observation_state") != RECONCILED_OBSERVATION_STATE:
        raise ValueError("EEA/Norway Romania watch reconciliation observation drift")
    _validate_boundary(result, label="EEA/Norway Romania watch reconciliation")
    if result.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("EEA/Norway Romania watch LKG became current truth")
    if result.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("EEA/Norway Romania discovery watch became material-admission ready")
    state = result.get("reconciliation_state")
    if current.get("source_health") == "DEGRADED":
        if state != "CURRENT_EEA_NORWAY_ROMANIA_WATCH_DEGRADED_LKG_REQUIRED":
            raise ValueError("degraded EEA/Norway Romania watch did not fail closed")
        if result.get("semantic_reconciliation_passed") is not False:
            raise ValueError("degraded EEA/Norway Romania watch claimed semantic reconciliation")
        if result.get("programming_watch_candidate") is not False or result.get("call_index_discovery_watch_candidate") is not False:
            raise ValueError("degraded EEA/Norway Romania watch emitted semantic watch")
    else:
        allowed = {
            "BASELINE_CAPTURED_NON_AUTHORIZING",
            "NO_CHANGE",
            "EEA_NORWAY_ROMANIA_DISCOVERY_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
            "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING",
        }
        if state not in allowed or result.get("semantic_reconciliation_passed") is not True:
            raise ValueError("healthy EEA/Norway Romania watch reconciliation state drift")
    if result.get("call_index_discovery_watch_candidate") is True:
        if not any(row.get("kind") == "CALL_DISCOVERY_SET_CHANGED" for row in result.get("semantic_changes") or []):
            raise ValueError("EEA/Norway Romania call-index watch lacks reconciled call-discovery change")


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
        "call_index_discovery_watch_candidate": result["call_index_discovery_watch_candidate"],
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
