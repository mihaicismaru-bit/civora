#!/usr/bin/env python3
"""Fail-closed semantic reconciliation for exact Creative Europe F&T evidence.

This layer compares two immutable exact-topic observations for the same CREA-*
reference. It can prove that a candidate material observation is unchanged or
that a semantic change has been observed and reconciled, but it never authorizes
OPEN, deadline, budget, eligibility, publication, distribution, or alerts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping

from creative_europe_ft_exact import MATERIAL_FLAGS, canonical_json, validate_exact_evidence

RECONCILER_ID = "CREATIVE_EUROPE_FT_RECONCILE_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_RECONCILIATION_V1"
SEMANTIC_FIELDS = (
    "reference",
    "status_code",
    "status_label",
    "candidate_observation_state",
    "authority_url",
    "authority_url_verified",
    "programme",
    "deadline_candidate",
    "budget_candidate",
)


def _sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _parse_utc(value: str) -> dt.datetime:
    text = str(value or "")
    if not text:
        raise ValueError("fetched_at is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _semantic_payload(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {key: evidence.get(key) for key in SEMANTIC_FIELDS}


def _validate_immutable_exact(evidence: Mapping[str, Any], *, label: str) -> None:
    validate_exact_evidence(evidence)
    expected = _sha256(_semantic_payload(evidence))
    if evidence.get("semantic_fingerprint") != expected:
        raise ValueError(f"{label}: semantic fingerprint does not bind exact evidence")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("search_raw_sha256") or "")):
        raise ValueError(f"{label}: search raw hash invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", str(evidence.get("facet_raw_sha256") or "")):
        raise ValueError(f"{label}: facet raw hash invalid")


def reconcile(
    current: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    *,
    reconciled_at: str | None = None,
) -> dict[str, Any]:
    _validate_immutable_exact(current, label="current")
    current_time = _parse_utc(str(current.get("fetched_at") or ""))
    if previous is not None:
        _validate_immutable_exact(previous, label="previous")
        if previous.get("reference") != current.get("reference"):
            raise ValueError("previous/current Creative Europe reference mismatch")
        previous_time = _parse_utc(str(previous.get("fetched_at") or ""))
        if previous_time > current_time:
            raise ValueError("previous Creative Europe evidence is newer than current evidence")

    if reconciled_at:
        reconciled_time = _parse_utc(reconciled_at)
    else:
        reconciled_time = dt.datetime.now(dt.timezone.utc)
    if reconciled_time < current_time:
        raise ValueError("reconciled_at predates current exact evidence")

    current_semantic = _semantic_payload(current)
    current_sha = _sha256(dict(current))
    previous_sha = _sha256(dict(previous)) if previous is not None else None
    changes: list[dict[str, Any]] = []
    if previous is not None:
        previous_semantic = _semantic_payload(previous)
        for field in SEMANTIC_FIELDS:
            if previous_semantic.get(field) != current_semantic.get(field):
                changes.append({
                    "field": field,
                    "previous_value": previous_semantic.get(field),
                    "current_value": current_semantic.get(field),
                })

    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif changes:
        state = "EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    else:
        state = "NO_CHANGE"

    current_is_open = current.get("candidate_observation_state") == "OPEN_CALL"
    missing = [
        "call-specific material admission for deadline/budget/eligibility/participation",
    ]
    if not current_is_open:
        missing.insert(0, "current Funding & Tenders status is not verified OPEN")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "adapter_id": RECONCILER_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "observation_state": "EXACT_TOPIC_SEMANTIC_RECONCILIATION_NON_AUTHORIZING",
        "reference": current.get("reference"),
        "current_run_id": current.get("run_id"),
        "current_fetched_at": current.get("fetched_at"),
        "current_evidence_sha256": current_sha,
        "current_semantic_fingerprint": current.get("semantic_fingerprint"),
        "previous_run_id": previous.get("run_id") if previous is not None else None,
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "previous_evidence_sha256": previous_sha,
        "previous_semantic_fingerprint": previous.get("semantic_fingerprint") if previous is not None else None,
        "reconciled_at": reconciled_time.isoformat().replace("+00:00", "Z"),
        "reconciliation_state": state,
        "semantic_reconciliation_passed": True,
        "semantic_change_count": len(changes),
        "semantic_changed": bool(changes),
        "changes": changes,
        "candidate_observation_state": current.get("candidate_observation_state"),
        "candidate_status_label": current.get("status_label"),
        "material_admission_ready_for_downstream_review": current_is_open,
        "market_intelligence_only": True,
        "requires_material_admission": True,
        "missing_for_material_admission": missing,
        "call_alert_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    receipt["reconciliation_fingerprint"] = _sha256({
        "reference": receipt["reference"],
        "current_evidence_sha256": current_sha,
        "previous_evidence_sha256": previous_sha,
        "reconciliation_state": state,
        "changes": changes,
    })
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("adapter_id") != RECONCILER_ID:
        raise ValueError("Creative Europe reconciliation identity drift")
    if receipt.get("source_family") != "EU_DIRECT" or receipt.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("Creative Europe reconciliation programme boundary drift")
    if receipt.get("observation_state") != "EXACT_TOPIC_SEMANTIC_RECONCILIATION_NON_AUTHORIZING":
        raise ValueError("Creative Europe reconciliation observation state drift")
    if receipt.get("semantic_reconciliation_passed") is not True or receipt.get("requires_material_admission") is not True:
        raise ValueError("Creative Europe reconciliation gate weakened")
    if receipt.get("market_intelligence_only") is not True:
        raise ValueError("Creative Europe reconciliation lost market-intelligence boundary")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"Creative Europe reconciliation became authorizing: {key}")
    if receipt.get("call_alert_authorized") is not False:
        raise ValueError("Creative Europe reconciliation authorized call alert")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("Creative Europe reconciliation crossed publication boundary")
    for key in ("current_evidence_sha256", "current_semantic_fingerprint", "reconciliation_fingerprint"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(key) or "")):
            raise ValueError(f"Creative Europe reconciliation hash invalid: {key}")
    if receipt.get("previous_run_id") is not None:
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("previous_evidence_sha256") or "")):
            raise ValueError("Creative Europe previous evidence hash invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("previous_semantic_fingerprint") or "")):
            raise ValueError("Creative Europe previous semantic fingerprint invalid")
    if int(receipt.get("semantic_change_count") or 0) != len(receipt.get("changes") or []):
        raise ValueError("Creative Europe reconciliation change count drift")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", type=pathlib.Path, required=True)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    receipt = reconcile(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "reference": receipt["reference"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
