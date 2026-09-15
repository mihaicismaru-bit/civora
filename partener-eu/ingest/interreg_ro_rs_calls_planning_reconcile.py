#!/usr/bin/env python3
"""Semantic reconciliation for official RO-RS planned-calls calendar evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
from typing import Any

from interreg_ro_rs_calls_planning import (
    AUTHORITY_CLASS,
    INDEX_URL,
    MATERIAL_FLAGS,
    OBSERVATION_STATE,
    PARSER_VERSION,
    PROGRAMME_FAMILY,
    SCHEMA,
)

RECONCILIATION_SCHEMA = "PARTENER_EU_INTERREG_RO_RS_CALLS_PLANNING_RECONCILIATION_V1"
RECONCILER_VERSION = "INTERREG_RO_RS_CALLS_PLANNING_RECONCILE_V1"


def _parse_time(value: Any, *, field: str) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} missing")
    text = value.strip().replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _assert_non_authorizing(receipt: dict[str, Any], *, label: str) -> None:
    if receipt.get("schema") != SCHEMA:
        raise ValueError(f"{label} schema mismatch")
    if receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError(f"{label} parser version mismatch")
    if receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError(f"{label} programme identity mismatch")
    if receipt.get("authority_class") != AUTHORITY_CLASS or receipt.get("authority_url") != INDEX_URL:
        raise ValueError(f"{label} authority identity mismatch")
    if receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError(f"{label} must remain PLANNED")
    if receipt.get("market_intelligence_only") is not True or receipt.get("planning_evidence_non_authorizing") is not True:
        raise ValueError(f"{label} lost non-authorizing boundary")
    if receipt.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError(f"{label} widened downstream material admission")
    if any(bool(receipt.get(flag)) for flag in MATERIAL_FLAGS):
        raise ValueError(f"{label} widened material authorization")
    if receipt.get("publication_effect") != "NONE":
        raise ValueError(f"{label} widened publication effect")


def _valid_previous(current: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any] | None:
    if previous is None:
        return None
    _assert_non_authorizing(previous, label="previous")
    if previous.get("source_health_state") != "HEALTHY":
        raise ValueError("previous evidence must be HEALTHY before it can be comparison/LKG reference")
    if not previous.get("semantic_fingerprint"):
        raise ValueError("previous HEALTHY evidence lacks semantic fingerprint")
    previous_time = _parse_time(previous.get("fetched_at"), field="previous.fetched_at")
    current_time = _parse_time(current.get("fetched_at"), field="current.fetched_at")
    if previous_time >= current_time:
        raise ValueError("previous evidence must be strictly older than current evidence")
    return previous


def reconcile(current: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    _assert_non_authorizing(current, label="current")
    valid_previous = _valid_previous(current, previous)
    current_health = current.get("source_health_state")

    base: dict[str, Any] = {
        "schema": RECONCILIATION_SCHEMA,
        "reconciler_version": RECONCILER_VERSION,
        "source_schema": SCHEMA,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "authority_url": INDEX_URL,
        "observation_state": OBSERVATION_STATE,
        "run_id": current.get("run_id"),
        "fetched_at": current.get("fetched_at"),
        "current_source_health_state": current_health,
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "previous_present": valid_previous is not None,
        "previous_fetched_at": valid_previous.get("fetched_at") if valid_previous else None,
        "previous_semantic_fingerprint": valid_previous.get("semantic_fingerprint") if valid_previous else None,
        "previous_is_current_truth": False,
        "lkg_is_current_truth": False,
        "market_intelligence_only": True,
        "material_admission_ready_for_downstream_review": False,
        "publication_effect": "NONE",
    }
    base.update({flag: False for flag in MATERIAL_FLAGS})

    if current_health == "DEGRADED":
        if current.get("latest_calendar") is not None or current.get("semantic_fingerprint") is not None:
            raise ValueError("DEGRADED current evidence must not retain current calendar semantics")
        if current.get("lkg_required") is not True:
            raise ValueError("DEGRADED current evidence must require LKG")
        base.update({
            "reconciliation_state": "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING",
            "semantic_change_count": 0,
            "semantic_change_fields": [],
            "lkg_reference_available": valid_previous is not None,
            "history_state": "CURRENT_DEGRADED_REFERENCE_PREVIOUS_ONLY" if valid_previous else "CURRENT_DEGRADED_NO_PREVIOUS",
        })
        return base

    if current_health != "HEALTHY":
        raise ValueError(f"unexpected current source health: {current_health}")
    if current.get("lkg_required") is not False or not current.get("semantic_fingerprint"):
        raise ValueError("HEALTHY current evidence lacks stable semantic identity")

    if valid_previous is None:
        base.update({
            "reconciliation_state": "BASELINE_HEALTHY",
            "semantic_change_count": 0,
            "semantic_change_fields": [],
            "lkg_reference_available": False,
            "history_state": "CURRENT_HEALTHY_BASELINE",
        })
        return base

    changed = current["semantic_fingerprint"] != valid_previous["semantic_fingerprint"]
    fields = ["planned_calls_calendar"] if changed else []
    base.update({
        "reconciliation_state": "SEMANTIC_CHANGE_REVIEW_REQUIRED" if changed else "NO_CHANGE",
        "semantic_change_count": len(fields),
        "semantic_change_fields": fields,
        "lkg_reference_available": True,
        "history_state": "CURRENT_HEALTHY",
    })
    return base


def validate_reconciliation(receipt: dict[str, Any]) -> None:
    if receipt.get("schema") != RECONCILIATION_SCHEMA or receipt.get("reconciler_version") != RECONCILER_VERSION:
        raise ValueError("RO-RS planning reconciliation schema/version drift")
    if receipt.get("observation_state") != "PLANNED" or receipt.get("market_intelligence_only") is not True:
        raise ValueError("RO-RS planning reconciliation left PLANNED market-intelligence boundary")
    if receipt.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("RO-RS planning reconciliation widened material admission")
    if any(bool(receipt.get(flag)) for flag in MATERIAL_FLAGS):
        raise ValueError("RO-RS planning reconciliation widened material authorization")
    if receipt.get("publication_effect") != "NONE" or receipt.get("lkg_is_current_truth") is not False:
        raise ValueError("RO-RS planning reconciliation widened current/public truth")
    state = receipt.get("reconciliation_state")
    allowed = {"BASELINE_HEALTHY", "NO_CHANGE", "SEMANTIC_CHANGE_REVIEW_REQUIRED", "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"}
    if state not in allowed:
        raise ValueError(f"unexpected reconciliation state: {state}")
    if state == "NO_CHANGE" and receipt.get("semantic_change_count") != 0:
        raise ValueError("NO_CHANGE receipt has semantic changes")
    if state == "SEMANTIC_CHANGE_REVIEW_REQUIRED" and int(receipt.get("semantic_change_count") or 0) < 1:
        raise ValueError("semantic change receipt lacks change count")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = None
    if args.previous and args.previous.exists():
        previous = json.loads(args.previous.read_text(encoding="utf-8"))
    receipt = reconcile(current, previous)
    validate_reconciliation(receipt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "history_state": receipt["history_state"],
        "previous_fetched_at": receipt["previous_fetched_at"],
        "publication_effect": receipt["publication_effect"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
