#!/usr/bin/env python3
"""Canonical sidecar staging for Interreg IPA Romania-Serbia planned-calls evidence.

The RO-RS planning calendar remains PLANNED / market-intelligence-only. This helper
lets the existing Official Programme / Interreg future-programming artifact become
the sole bounded history owner after migration, without inserting workbook rows into
OPEN/UPCOMING call truth.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import interreg_ro_rs_calls_planning as planning
import interreg_ro_rs_calls_planning_reconcile as planning_reconcile

CANONICAL_SIDECAR_SCHEMA = "PARTENER_EU_INTERREG_RO_RS_CALLS_PLANNING_CANONICAL_SIDECAR_V1"
HISTORY_FILENAME = "interreg-ro-rs-calls-planning.json"
RECONCILIATION_FILENAME = "interreg-ro-rs-calls-planning-reconciliation.json"
RESTORE_SOURCE_KIND = "INTERREG_FUTURE_CANONICAL"


def _parse_time(value: Any) -> dt.datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("fetched_at missing")
    parsed = dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("fetched_at must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _same_identity(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(
        left.get(key) == right.get(key)
        for key in ("schema", "parser_version", "programme_family", "authority_class", "authority_url", "observation_state")
    )


def select_previous(history_root: Path, current: Mapping[str, Any]) -> tuple[dict[str, Any] | None, Path | None]:
    """Return newest HEALTHY same-identity receipt strictly older than current."""
    planning.validate(dict(current))
    current_time = _parse_time(current.get("fetched_at"))
    if not history_root.exists():
        return None, None

    candidates: list[tuple[dt.datetime, Path, dict[str, Any]]] = []
    for path in history_root.rglob(HISTORY_FILENAME):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            planning.validate(value)
            if value.get("source_health_state") != "HEALTHY":
                continue
            if not value.get("semantic_fingerprint"):
                continue
            if not _same_identity(current, value):
                continue
            observed = _parse_time(value.get("fetched_at"))
            if observed >= current_time:
                continue
            candidates.append((observed, path, value))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue

    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, path, value = candidates[0]
    return value, path


def stage(*, run_id: str, future_output: Path) -> dict[str, Any]:
    """Acquire, reconcile, and stage compact canonical RO-RS planning history."""
    canonical_root = future_output.parent.parent
    lane_root = canonical_root / "interreg-ro-rs-calls-planning"
    current_dir = lane_root / "current"
    previous_dir = lane_root / "previous"
    for path in (current_dir, previous_dir):
        if path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)

    current, raws = planning.collect(run_id=f"{run_id}-ro-rs-planning")
    planning.validate(current)
    planning.write_output(current_dir, current, raws)

    history_root = future_output.parent / "history-scan" / "unpacked"
    previous, previous_path = select_previous(history_root, current)
    if previous is not None and previous_path is not None:
        shutil.copy2(previous_path, previous_dir / HISTORY_FILENAME)

    reconciliation = planning_reconcile.reconcile(current, previous)
    planning_reconcile.validate_reconciliation(reconciliation)
    reconciliation_path = current_dir / RECONCILIATION_FILENAME
    reconciliation_path.write_text(
        json.dumps(reconciliation, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for obj in (current, reconciliation):
        if obj.get("observation_state") != "PLANNED":
            raise ValueError("canonical RO-RS planning sidecar left PLANNED state")
        if obj.get("market_intelligence_only") is not True:
            raise ValueError("canonical RO-RS planning sidecar lost market-intelligence boundary")
        for flag in planning.MATERIAL_FLAGS:
            if obj.get(flag) is not False:
                raise ValueError(f"canonical RO-RS planning sidecar crossed material boundary: {flag}")
        if obj.get("publication_effect") != "NONE":
            raise ValueError("canonical RO-RS planning sidecar crossed publication boundary")
    if reconciliation.get("previous_is_current_truth") is not False or reconciliation.get("lkg_is_current_truth") is not False:
        raise ValueError("canonical RO-RS planning sidecar promoted history/LKG to current truth")

    history_publish = canonical_root / "history-publish"
    history_publish.mkdir(parents=True, exist_ok=True)
    shutil.copy2(current_dir / HISTORY_FILENAME, history_publish / HISTORY_FILENAME)
    shutil.copy2(reconciliation_path, history_publish / RECONCILIATION_FILENAME)

    latest = current.get("latest_calendar") or {}
    return {
        "schema": CANONICAL_SIDECAR_SCHEMA,
        "source_health_state": current.get("source_health_state"),
        "observation_state": current.get("observation_state"),
        "calendar_date": latest.get("calendar_date"),
        "calendar_url": latest.get("calendar_url"),
        "previous_same_identity_restored": previous is not None,
        "restore_source_kind": RESTORE_SOURCE_KIND if previous is not None else None,
        "previous_source_path": str(previous_path) if previous_path else None,
        "reconciliation_state": reconciliation.get("reconciliation_state"),
        "semantic_change_count": reconciliation.get("semantic_change_count"),
        "history_state": reconciliation.get("history_state"),
        "market_intelligence_only": True,
        "material_admission_ready_for_downstream_review": False,
        "open_call_authorized": False,
        "closed_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
    }
