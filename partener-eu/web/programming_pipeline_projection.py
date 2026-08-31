#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROJECTION_ID = "PROGRAMMING_PIPELINE_PUBLIC_PROJECTION_V1"
SNAPSHOT_ADAPTER = "INTERREG_PROGRAMMING_PIPELINE_V1"
RECONCILIATION_ADAPTER = "INTERREG_PROGRAMMING_RECONCILIATION_V1"
ALLOWED_STATES = {"PROPOSAL", "CONSULTATION", "PROGRAMMING_PROCESS"}
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
)
STATE_LABELS = {
    "PROPOSAL": "Propunere",
    "CONSULTATION": "Consultare",
    "PROGRAMMING_PROCESS": "Programare în pregătire",
}
MISSING_FOR_OPEN = [
    "exact_call_or_topic_identifier",
    "current_official_exact_call_endpoint",
    "explicit_current_official_call_status",
    "call_specific_deadline_budget_eligibility_and_geography",
    "semantic_reconciliation",
]


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _require_non_authorizing(obj: dict[str, Any], label: str) -> None:
    if obj.get("market_intelligence_only") is not True:
        raise ValueError(f"{label}: market_intelligence_only must be true")
    if obj.get("publication_effect") != "NONE":
        raise ValueError(f"{label}: publication_effect must remain NONE")
    for key in MATERIAL_FLAGS:
        if obj.get(key) is not False:
            raise ValueError(f"{label}: authorizing drift: {key}")


def _validate_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    if snapshot.get("adapter_id") != SNAPSHOT_ADAPTER:
        raise ValueError("snapshot adapter mismatch")
    if snapshot.get("source_family") != "INTERREG":
        raise ValueError("snapshot source_family mismatch")
    if snapshot.get("programme_period") != "2028-2034":
        raise ValueError("snapshot programme_period mismatch")
    if snapshot.get("observation_state") != "PROGRAMMING_PIPELINE":
        raise ValueError("snapshot observation_state mismatch")
    _require_non_authorizing(snapshot, "snapshot")
    rows = snapshot.get("watchlist")
    if not isinstance(rows, list) or len(rows) != snapshot.get("source_count"):
        raise ValueError("snapshot source inventory mismatch")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("snapshot watch row must be an object")
        source_id = row.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("snapshot source_id missing/duplicate")
        seen.add(source_id)
        if row.get("observation_state") not in ALLOWED_STATES:
            raise ValueError(f"{source_id}: forbidden programming state")
        _require_non_authorizing(row, f"row {source_id}")
        health = row.get("source_health")
        if not isinstance(health, dict):
            raise ValueError(f"{source_id}: source_health missing")
        health_state = str(health.get("health_state") or "")
        if health_state == "HEALTHY":
            if health.get("lkg_required") is not False:
                raise ValueError(f"{source_id}: healthy source cannot require LKG")
            raw_sha = str(health.get("raw_sha256") or "")
            if len(raw_sha) != 64:
                raise ValueError(f"{source_id}: healthy source missing raw SHA-256")
        elif health_state.startswith("DEGRADED"):
            if health.get("lkg_required") is not True:
                raise ValueError(f"{source_id}: degraded source must require LKG")
        else:
            raise ValueError(f"{source_id}: unexpected live source health {health_state!r}")
    return rows


def _validate_reconciliation(snapshot: dict[str, Any], reconciliation: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if reconciliation.get("adapter_id") != RECONCILIATION_ADAPTER:
        raise ValueError("reconciliation adapter mismatch")
    if reconciliation.get("source_family") != "INTERREG":
        raise ValueError("reconciliation source_family mismatch")
    if reconciliation.get("programme_period") != "2028-2034":
        raise ValueError("reconciliation programme_period mismatch")
    _require_non_authorizing(reconciliation, "reconciliation")
    if reconciliation.get("call_alert_authorized") is not False:
        raise ValueError("reconciliation call_alert_authorized drift")
    if reconciliation.get("current_run_id") != snapshot.get("run_id"):
        raise ValueError("reconciliation current_run_id does not bind snapshot")
    if reconciliation.get("current_fetched_at") != snapshot.get("fetched_at"):
        raise ValueError("reconciliation current_fetched_at does not bind snapshot")
    if reconciliation.get("current_snapshot_sha256") != _fingerprint(snapshot):
        raise ValueError("reconciliation snapshot fingerprint mismatch")
    if reconciliation.get("pipeline_semantic_reconciliation_status") != "PASS":
        raise ValueError("reconciliation semantic status is not PASS")
    if reconciliation.get("pipeline_watch_candidate") is True:
        if reconciliation.get("pipeline_watch_label_required") != "PROGRAMARE_VIITOARE_PIPELINE":
            raise ValueError("pipeline watch candidate missing mandatory pipeline label")
    changes = reconciliation.get("changes")
    if not isinstance(changes, list):
        raise ValueError("reconciliation changes missing")
    by_id: dict[str, dict[str, Any]] = {}
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError("reconciliation change must be object")
        source_id = change.get("source_id")
        if not isinstance(source_id, str) or not source_id or source_id in by_id:
            raise ValueError("reconciliation change source_id missing/duplicate")
        for key in ("material_fact_use", "open_call_authorized", "publish_authorized", "distribution_authorized"):
            if change.get(key) is not False:
                raise ValueError(f"reconciliation change became authorizing: {source_id} {key}")
        by_id[source_id] = change
    return by_id


def _confidence(row: dict[str, Any], change: dict[str, Any] | None) -> tuple[str, str]:
    health = row["source_health"]
    health_state = str(health.get("health_state") or "")
    if health_state == "HEALTHY":
        if change and change.get("semantic_changed") is True:
            return "HIGH", "CURRENT_OFFICIAL_EVIDENCE_RECONCILED_CHANGE"
        return "HIGH", "CURRENT_OFFICIAL_EVIDENCE_VERIFIED"
    lkg_status = str((change or {}).get("lkg_status") or "")
    if "REFERENCE_AVAILABLE" in lkg_status:
        return "LOW", "CURRENT_TRANSPORT_DEGRADED_HISTORICAL_EVIDENCE_REFERENCE_ONLY"
    return "LOW", "CURRENT_TRANSPORT_DEGRADED_CURRENT_PROOF_MISSING"


def project(snapshot: dict[str, Any], reconciliation: dict[str, Any]) -> dict[str, Any]:
    rows = _validate_snapshot(snapshot)
    changes_by_id = _validate_reconciliation(snapshot, reconciliation)
    cards: list[dict[str, Any]] = []

    for row in rows:
        source_id = row["source_id"]
        change = changes_by_id.get(source_id)
        confidence, confidence_reason = _confidence(row, change)
        health = row["source_health"]
        missing = list(row.get("missing_for_open_confirmation") or MISSING_FOR_OPEN)
        required_missing = set(MISSING_FOR_OPEN)
        if not required_missing.issubset(set(missing)):
            raise ValueError(f"{source_id}: missing-for-open contract weakened")
        cards.append({
            "source_id": source_id,
            "programme_ids": list(row.get("programme_ids") or []),
            "programme": row.get("programme"),
            "programme_family": row.get("programme_family"),
            "programme_period": row.get("programme_period"),
            "observation_state": row.get("observation_state"),
            "observation_label_ro": STATE_LABELS[row["observation_state"]],
            "authority_class": row.get("authority_class"),
            "authority_url": row.get("authority_url"),
            "supporting_authority_url": row.get("supporting_authority_url"),
            "observed_at": snapshot.get("fetched_at"),
            "source_published_date": row.get("source_published_date"),
            "consultation_start_date": row.get("consultation_start_date"),
            "consultation_end_date": row.get("consultation_end_date"),
            "consultation_lifecycle": row.get("consultation_lifecycle"),
            "freshness_state": row.get("freshness_state"),
            "watch_priority": row.get("watch_priority"),
            "source_health": {
                "health_state": health.get("health_state"),
                "lkg_required": health.get("lkg_required"),
                "http_status": health.get("http_status"),
                "raw_sha256": health.get("raw_sha256"),
            },
            "reconciliation": {
                "change_kind": (change or {}).get("change_kind"),
                "semantic_changed": (change or {}).get("semantic_changed"),
                "transport_or_content_changed": (change or {}).get("transport_or_content_changed"),
                "lkg_status": (change or {}).get("lkg_status"),
            },
            "confidence": confidence,
            "confidence_reason": confidence_reason,
            "open_confirmation_state": "NOT_CONFIRMED_MISSING_EXACT_CALL_EVIDENCE",
            "missing_for_open_confirmation": missing,
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "publication_effect": "NONE",
        })

    cards.sort(key=lambda item: (-(int(item.get("watch_priority") or 0)), str(item["source_id"])))
    return {
        "schema_version": "1.0",
        "projection_id": PROJECTION_ID,
        "surface": "PROGRAMARE_VIITOARE_PIPELINE",
        "surface_state": "PREVIEW_READ_ONLY_NOT_PUBLISHED",
        "generated_from_run_id": snapshot.get("run_id"),
        "observed_at": snapshot.get("fetched_at"),
        "source_family": "INTERREG",
        "programme_period": "2028-2034",
        "card_count": len(cards),
        "healthy_source_count": snapshot.get("healthy_source_count"),
        "degraded_source_count": snapshot.get("degraded_source_count"),
        "reconciliation_state": reconciliation.get("reconciliation_state"),
        "semantic_change_count": reconciliation.get("semantic_change_count"),
        "transport_or_content_change_count": reconciliation.get("transport_or_content_change_count"),
        "pipeline_watch_candidate": reconciliation.get("pipeline_watch_candidate") is True,
        "pipeline_watch_label": (
            "PROGRAMARE_VIITOARE_PIPELINE"
            if reconciliation.get("pipeline_watch_candidate") is True
            else None
        ),
        "source_health_watch_candidate": reconciliation.get("source_health_watch_candidate") is True,
        "cards": cards,
        "reader_copy_generated": False,
        "seo_indexing_state": "NOINDEX_PREVIEW_ONLY",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "publication_effect": "NONE",
        "note": (
            "This is a read-only PROGRAMARE VIITOARE preview. "
            "PROPOSAL/CONSULTATION/PROGRAMMING_PROCESS cards never represent OPEN calls."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a fail-closed read-only Interreg programming-pipeline product projection.")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--reconciliation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    result = project(snapshot, reconciliation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
