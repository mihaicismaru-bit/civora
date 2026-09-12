#!/usr/bin/env python3
"""Semantic reconciliation for exact current Innovation Fund F&T evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_innovation_fund_ft_exact import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_INNOVATION_FUND_FT_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_INNOVATION_FUND_FT_RECONCILE_V1"
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
)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("reconciliation timestamps must be timezone-aware")
    return parsed


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("exact Innovation Fund semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("exact Innovation Fund semantic fingerprint tampered")
    return dict(semantics)


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not Innovation Fund exact evidence")
    current_semantics = _validated_semantics(current)
    changes: list[dict[str, Any]] = []

    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not Innovation Fund exact evidence")
        previous_semantics = _validated_semantics(previous)
        if previous.get("reference") != current.get("reference"):
            raise ValueError("Innovation Fund reconciliation identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous Innovation Fund evidence is newer than current evidence")
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "INNOVATION_FUND_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    status = str(current.get("status_label") or "").casefold()
    candidate = current.get("candidate_state")
    exact_current_status_proven = bool(
        current.get("authority_url_verified") is True
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
    )
    missing = ["field_scoped_material_admission"]
    if not exact_current_status_proven:
        missing.insert(0, "exact_current_status_not_materially_proven")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "INNOVATION_FUND",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "reference": current.get("reference"),
        "call_identifier": current.get("call_identifier"),
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "candidate_state": candidate,
        "status_label": current.get("status_label"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": True,
        "material_admission_ready_for_downstream_review": exact_current_status_proven,
        "missing_for_material_admission": missing,
        "field_scoped_material_admission_required": True,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    for key in MATERIAL_FLAGS:
        receipt[key] = False
    validate_receipt(receipt, current=current, previous=previous)
    return receipt


def validate_receipt(
    receipt: Mapping[str, Any], *, current: Mapping[str, Any], previous: Mapping[str, Any] | None = None
) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("parser_version") != PARSER_VERSION:
        raise ValueError("Innovation Fund reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("reference") != current.get("reference") or receipt.get("call_identifier") != current.get("call_identifier"):
        raise ValueError("Innovation Fund reconciliation current identity binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("Innovation Fund reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("Innovation Fund reconciliation current semantic binding failed")
    if previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
            raise ValueError("Innovation Fund baseline reconciliation state invalid")
        if receipt.get("previous_evidence_sha256") is not None:
            raise ValueError("Innovation Fund baseline unexpectedly bound previous evidence")
    else:
        validate_evidence(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("Innovation Fund reconciliation previous evidence hash mismatch")
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "INNOVATION_FUND_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("Innovation Fund reconciliation state disagrees with semantic fingerprints")
    status = str(current.get("status_label") or "").casefold()
    candidate = current.get("candidate_state")
    expected_ready = bool(
        current.get("authority_url_verified") is True
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
    )
    if receipt.get("material_admission_ready_for_downstream_review") is not expected_ready:
        raise ValueError("Innovation Fund reconciliation downstream-review gate drift")
    if receipt.get("semantic_reconciliation_passed") is not True or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Innovation Fund reconciliation skipped mandatory gate")
    if "field_scoped_material_admission" not in set(receipt.get("missing_for_material_admission") or []):
        raise ValueError("Innovation Fund reconciliation omitted final material admission requirement")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"Innovation Fund reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("Innovation Fund reconciliation crossed publication boundary")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("current", type=pathlib.Path)
    parser.add_argument("--previous", type=pathlib.Path)
    parser.add_argument("--output", required=True, type=pathlib.Path)
    args = parser.parse_args()
    current = json.loads(args.current.read_text(encoding="utf-8"))
    previous = json.loads(args.previous.read_text(encoding="utf-8")) if args.previous else None
    receipt = reconcile(current, previous)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "reference": receipt["reference"],
        "call_identifier": receipt["call_identifier"],
        "candidate_state": receipt["candidate_state"],
        "status_label": receipt["status_label"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
        "closed_call_authorized": receipt["closed_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
