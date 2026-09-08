#!/usr/bin/env python3
"""Semantic reconciliation for exact Horizon Europe call HORIZON-CL5-2026-09.

Previous/LKG evidence is comparison/reference only. Reconciliation may mark a
stable exact-current unit ready for downstream *review*, but never authorizes
material facts; field-scoped admission remains mandatory.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any, Mapping

from eu_direct_horizon_cl5_2026_09_exact import (
    CALL_IDENTIFIER,
    MATERIAL_FLAGS,
    SCHEMA as EVIDENCE_SCHEMA,
    validate_evidence,
)

SCHEMA = "PARTENER_EU_HORIZON_CL5_2026_09_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_HORIZON_CL5_2026_09_RECONCILE_V1"


def _parsed_at(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Horizon CL5 evidence timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _same_identity(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return (
        previous.get("schema") == EVIDENCE_SCHEMA
        and current.get("schema") == EVIDENCE_SCHEMA
        and previous.get("call_identifier") == CALL_IDENTIFIER
        and current.get("call_identifier") == CALL_IDENTIFIER
        and previous.get("cinea_authority_url") == current.get("cinea_authority_url")
        and previous.get("funding_tenders_call_url") == current.get("funding_tenders_call_url")
    )


def _assert_previous_non_authorizing(previous: Mapping[str, Any]) -> None:
    for key in MATERIAL_FLAGS:
        if previous.get(key) is not False:
            raise ValueError(f"previous Horizon CL5 evidence attempted authorization widening: {key}")
    if previous.get("publication_effect") != "NONE":
        raise ValueError("previous Horizon CL5 evidence crossed publication boundary")


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_evidence(current)
    previous_same_identity = False
    previous_strictly_older = False
    previous_usable = False
    if previous is not None:
        validate_evidence(previous)
        _assert_previous_non_authorizing(previous)
        if not _same_identity(previous, current):
            raise ValueError("previous Horizon CL5 evidence identity/authority drift")
        previous_same_identity = True
        previous_strictly_older = _parsed_at(str(previous["fetched_at"])) < _parsed_at(str(current["fetched_at"]))
        if not previous_strictly_older:
            raise ValueError("previous Horizon CL5 evidence is not strictly older than current")
        previous_usable = previous.get("evidence_usable_for_reconciliation") is True

    current_usable = current.get("evidence_usable_for_reconciliation") is True
    semantic_change_count = 0
    changed_fields: list[str] = []
    if not current_usable:
        state = "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"
        history_state = "CURRENT_DEGRADED_LKG_REQUIRED"
        ready = False
        source_health_watch_candidate = True
    elif previous is None:
        state = "BASELINE_CURRENT_HEALTHY_NON_AUTHORIZING"
        history_state = "CURRENT_HEALTHY"
        ready = False
        source_health_watch_candidate = False
    elif not previous_usable:
        state = "CURRENT_HEALTHY_PREVIOUS_UNUSABLE_BASELINE_RESET_NON_AUTHORIZING"
        history_state = "CURRENT_HEALTHY"
        ready = False
        source_health_watch_candidate = False
    elif previous.get("exact_semantic_fingerprint") == current.get("exact_semantic_fingerprint"):
        state = "NO_CHANGE"
        history_state = "CURRENT_HEALTHY"
        ready = True
        source_health_watch_candidate = False
    else:
        state = "SEMANTIC_CHANGE_REVIEW_REQUIRED"
        history_state = "CURRENT_HEALTHY"
        ready = False
        source_health_watch_candidate = False
        semantic_change_count = 1
        prev_sem = dict(previous.get("exact_semantics") or {})
        curr_sem = dict(current.get("exact_semantics") or {})
        changed_fields = sorted(
            key for key in set(prev_sem) | set(curr_sem) if prev_sem.get(key) != curr_sem.get(key)
        )

    flags = {key: False for key in MATERIAL_FLAGS}
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "call_identifier": CALL_IDENTIFIER,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous else None,
        "previous_same_identity_restored": previous_same_identity,
        "previous_strictly_older": previous_strictly_older,
        "previous_evidence_usable": previous_usable,
        "current_evidence_usable": current_usable,
        "current_source_health_state": current.get("source_health_state"),
        "reconciliation_state": state,
        "semantic_change_count": semantic_change_count,
        "changed_fields": changed_fields,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous else None,
        "history_state": history_state,
        "lkg_required": current.get("lkg_required") is True,
        "lkg_is_current_truth": False,
        "source_health_watch_candidate": source_health_watch_candidate,
        "material_admission_ready_for_downstream_review": ready,
        "field_scoped_material_admission_required": True,
        "market_intelligence_only": True,
        **flags,
        "publication_effect": "NONE",
    }
    validate_reconciliation(result)
    return result


def validate_reconciliation(result: Mapping[str, Any]) -> None:
    if result.get("schema") != SCHEMA or result.get("parser_version") != PARSER_VERSION:
        raise ValueError("Horizon CL5 reconciliation schema/parser drift")
    if result.get("call_identifier") != CALL_IDENTIFIER:
        raise ValueError("Horizon CL5 reconciliation identity drift")
    if result.get("lkg_is_current_truth") is not False:
        raise ValueError("Horizon CL5 reconciliation promoted LKG to current truth")
    if result.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Horizon CL5 reconciliation skipped field-scoped admission")
    if result.get("market_intelligence_only") is not True:
        raise ValueError("Horizon CL5 reconciliation left market-intelligence boundary")
    state = result.get("reconciliation_state")
    allowed = {
        "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING",
        "BASELINE_CURRENT_HEALTHY_NON_AUTHORIZING",
        "CURRENT_HEALTHY_PREVIOUS_UNUSABLE_BASELINE_RESET_NON_AUTHORIZING",
        "NO_CHANGE",
        "SEMANTIC_CHANGE_REVIEW_REQUIRED",
    }
    if state not in allowed:
        raise ValueError(f"unsupported Horizon CL5 reconciliation state: {state}")
    ready = result.get("material_admission_ready_for_downstream_review")
    if ready is True and state != "NO_CHANGE":
        raise ValueError("Horizon CL5 review readiness escaped stable NO_CHANGE state")
    if state == "NO_CHANGE":
        if result.get("semantic_change_count") != 0 or result.get("previous_same_identity_restored") is not True:
            raise ValueError("Horizon CL5 NO_CHANGE lacks same-identity stable replay")
        if result.get("previous_strictly_older") is not True or result.get("current_evidence_usable") is not True:
            raise ValueError("Horizon CL5 NO_CHANGE lacks strict history/current health")
    if state == "SEMANTIC_CHANGE_REVIEW_REQUIRED" and result.get("semantic_change_count") != 1:
        raise ValueError("Horizon CL5 semantic change count drift")
    if state == "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING":
        if result.get("lkg_required") is not True or result.get("source_health_watch_candidate") is not True:
            raise ValueError("Horizon CL5 degraded reconciliation lost source-health/LKG watch")
        if ready is not False:
            raise ValueError("Horizon CL5 degraded reconciliation became review-ready")
    for key in MATERIAL_FLAGS:
        if result.get(key) is not False:
            raise ValueError(f"Horizon CL5 reconciliation attempted authorization: {key}")
    if result.get("publication_effect") != "NONE":
        raise ValueError("Horizon CL5 reconciliation crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", required=True, type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    result = reconcile(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "call_identifier": result["call_identifier"],
        "reconciliation_state": result["reconciliation_state"],
        "semantic_change_count": result["semantic_change_count"],
        "history_state": result["history_state"],
        "material_admission_ready_for_downstream_review": result["material_admission_ready_for_downstream_review"],
        "open_call_authorized": result["open_call_authorized"],
        "publication_effect": result["publication_effect"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
