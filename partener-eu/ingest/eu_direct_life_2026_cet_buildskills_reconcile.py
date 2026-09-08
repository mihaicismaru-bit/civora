#!/usr/bin/env python3
"""Semantic reconciliation for exact LIFE 2026 CET BUILDUP Skills topic."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any, Mapping

from eu_direct_life_2026_cet_buildskills_exact import (
    CINEA_URL,
    FT_TOPIC_URL,
    MATERIAL_FLAGS,
    SCHEMA as EVIDENCE_SCHEMA,
    TOPIC_IDENTIFIER,
    validate_evidence,
)

SCHEMA = "PARTENER_EU_LIFE_2026_CET_BUILDSKILLS_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_LIFE_2026_CET_BUILDSKILLS_RECONCILE_V1"


def _parsed_at(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("LIFE BUILDUP Skills evidence timestamp must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _same_identity(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    return (
        previous.get("schema") == EVIDENCE_SCHEMA
        and current.get("schema") == EVIDENCE_SCHEMA
        and previous.get("topic_identifier") == TOPIC_IDENTIFIER
        and current.get("topic_identifier") == TOPIC_IDENTIFIER
        and previous.get("cinea_authority_url") == CINEA_URL
        and current.get("cinea_authority_url") == CINEA_URL
        and previous.get("funding_tenders_topic_url") == FT_TOPIC_URL
        and current.get("funding_tenders_topic_url") == FT_TOPIC_URL
    )


def _assert_previous_non_authorizing(previous: Mapping[str, Any]) -> None:
    for key in MATERIAL_FLAGS:
        if previous.get(key) is not False:
            raise ValueError(f"previous LIFE BUILDUP Skills evidence attempted authorization widening: {key}")
    if previous.get("publication_effect") != "NONE":
        raise ValueError("previous LIFE BUILDUP Skills evidence crossed publication boundary")


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    validate_evidence(current)
    previous_same_identity = False
    previous_strictly_older = False
    previous_usable = False
    if previous is not None:
        validate_evidence(previous)
        _assert_previous_non_authorizing(previous)
        if not _same_identity(previous, current):
            raise ValueError("previous LIFE BUILDUP Skills evidence identity/authority drift")
        previous_same_identity = True
        previous_strictly_older = _parsed_at(str(previous["fetched_at"])) < _parsed_at(str(current["fetched_at"]))
        if not previous_strictly_older:
            raise ValueError("previous LIFE BUILDUP Skills evidence is not strictly older than current")
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
        "topic_identifier": TOPIC_IDENTIFIER,
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
        raise ValueError("LIFE BUILDUP Skills reconciliation schema/parser drift")
    if result.get("topic_identifier") != TOPIC_IDENTIFIER:
        raise ValueError("LIFE BUILDUP Skills reconciliation identity drift")
    if result.get("lkg_is_current_truth") is not False:
        raise ValueError("LIFE BUILDUP Skills reconciliation promoted LKG to current truth")
    if result.get("field_scoped_material_admission_required") is not True:
        raise ValueError("LIFE BUILDUP Skills reconciliation skipped field-scoped admission")
    if result.get("market_intelligence_only") is not True:
        raise ValueError("LIFE BUILDUP Skills reconciliation left market-intelligence boundary")
    state = result.get("reconciliation_state")
    allowed = {
        "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING",
        "BASELINE_CURRENT_HEALTHY_NON_AUTHORIZING",
        "CURRENT_HEALTHY_PREVIOUS_UNUSABLE_BASELINE_RESET_NON_AUTHORIZING",
        "NO_CHANGE",
        "SEMANTIC_CHANGE_REVIEW_REQUIRED",
    }
    if state not in allowed:
        raise ValueError(f"unsupported LIFE BUILDUP Skills reconciliation state: {state}")
    ready = result.get("material_admission_ready_for_downstream_review")
    if ready is True and state != "NO_CHANGE":
        raise ValueError("LIFE BUILDUP Skills review readiness escaped stable NO_CHANGE state")
    if state == "NO_CHANGE":
        if result.get("semantic_change_count") != 0 or result.get("previous_same_identity_restored") is not True:
            raise ValueError("LIFE BUILDUP Skills NO_CHANGE lacks same-identity stable replay")
        if result.get("previous_strictly_older") is not True or result.get("current_evidence_usable") is not True:
            raise ValueError("LIFE BUILDUP Skills NO_CHANGE lacks strict history/current health")
    if state == "SEMANTIC_CHANGE_REVIEW_REQUIRED" and result.get("semantic_change_count") != 1:
        raise ValueError("LIFE BUILDUP Skills semantic change count drift")
    if state == "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING":
        if result.get("lkg_required") is not True or result.get("source_health_watch_candidate") is not True:
            raise ValueError("LIFE BUILDUP Skills degraded reconciliation lost source-health/LKG watch")
        if ready is not False:
            raise ValueError("LIFE BUILDUP Skills degraded reconciliation became review-ready")
    for key in MATERIAL_FLAGS:
        if result.get(key) is not False:
            raise ValueError(f"LIFE BUILDUP Skills reconciliation attempted authorization: {key}")
    if result.get("publication_effect") != "NONE":
        raise ValueError("LIFE BUILDUP Skills reconciliation crossed publication boundary")


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
        "topic_identifier": result["topic_identifier"],
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
