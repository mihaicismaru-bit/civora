#!/usr/bin/env python3
"""Semantic reconciliation for exact current Digital Europe Funding & Tenders evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_digital_ft_exact import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_DIGITAL_FT_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_DIGITAL_FT_RECONCILE_V1_1"
MATERIAL_FLAGS = (
    "material_fact_use",
    "open_call_authorized",
    "deadline_authorized",
    "budget_authorized",
    "eligibility_authorized",
    "publish_authorized",
    "distribution_authorized",
    "call_alert_authorized",
)
DEGRADED_STATE = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("reconciliation timestamps must be timezone-aware")
    return parsed


def _evidence_usable(evidence: Mapping[str, Any]) -> bool:
    value = evidence.get("evidence_usable_for_reconciliation")
    if value is None:
        return True
    if value not in {True, False}:
        raise ValueError("Digital Europe evidence usability state invalid")
    return bool(value)


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("exact Digital Europe semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("exact Digital Europe semantic fingerprint tampered")
    return dict(semantics)


def _validate_previous_identity_and_time(current: Mapping[str, Any], previous: Mapping[str, Any]) -> None:
    if previous.get("schema") != EXACT_SCHEMA:
        raise ValueError("previous evidence is not Digital Europe exact evidence")
    validate_evidence(previous)
    if previous.get("reference") != current.get("reference"):
        raise ValueError("Digital Europe reconciliation identity mismatch")
    if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
        raise ValueError("previous Digital Europe evidence is newer than current evidence")


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not Digital Europe exact evidence")
    current_semantics = _validated_semantics(current)
    current_usable = _evidence_usable(current)
    changes: list[dict[str, Any]] = []

    if previous is not None:
        _validate_previous_identity_and_time(current, previous)

    if not current_usable:
        state = DEGRADED_STATE
        semantic_reconciliation_passed = False
    elif previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
    else:
        previous_semantics = _validated_semantics(previous)
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "DIGITAL_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True

    ready = bool(
        current_usable
        and current.get("candidate_state") == "OPEN_CALL"
        and current.get("authority_url_verified") is True
        and current.get("status_label")
    )
    lkg_required = not current_usable
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "DIGITAL_EUROPE",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "reference": current.get("reference"),
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "current_source_health_state": current.get("source_health_state", "HEALTHY"),
        "current_evidence_usable_for_reconciliation": current_usable,
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "lkg_reference_required": lkg_required,
        "lkg_reference_available": previous is not None,
        "lkg_reference_is_current_truth": False,
        "material_admission_ready_for_downstream_review": ready,
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
        raise ValueError("Digital Europe reconciliation schema/parser drift")
    validate_evidence(current)
    current_usable = _evidence_usable(current)
    if receipt.get("reference") != current.get("reference"):
        raise ValueError("Digital Europe reconciliation current identity binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("Digital Europe reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("Digital Europe reconciliation current semantic binding failed")
    if receipt.get("current_evidence_usable_for_reconciliation") is not current_usable:
        raise ValueError("Digital Europe reconciliation current usability binding failed")
    if previous is not None:
        _validate_previous_identity_and_time(current, previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("Digital Europe reconciliation previous evidence hash mismatch")
    elif receipt.get("previous_evidence_sha256") is not None:
        raise ValueError("Digital Europe reconciliation unexpectedly bound previous evidence")

    if not current_usable:
        if receipt.get("reconciliation_state") != DEGRADED_STATE:
            raise ValueError("Digital Europe degraded current evidence reconciliation state invalid")
        if receipt.get("semantic_reconciliation_passed") is not False:
            raise ValueError("Digital Europe degraded current evidence pretended semantic reconciliation")
        if receipt.get("semantic_change_count") != 0 or receipt.get("semantic_changes") != []:
            raise ValueError("Digital Europe degraded current evidence invented semantic change")
        if receipt.get("lkg_reference_required") is not True:
            raise ValueError("Digital Europe degraded current evidence lost LKG requirement")
        if receipt.get("lkg_reference_available") is not (previous is not None):
            raise ValueError("Digital Europe degraded current evidence LKG availability drift")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("Digital Europe degraded current evidence became review-ready")
    else:
        if previous is None:
            expected = "BASELINE_CAPTURED_NON_AUTHORIZING"
        else:
            expected = (
                "NO_CHANGE"
                if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
                else "DIGITAL_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
            )
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("Digital Europe reconciliation state disagrees with semantic fingerprints")
        if receipt.get("semantic_reconciliation_passed") is not True:
            raise ValueError("Digital Europe healthy exact evidence failed semantic reconciliation")
        if receipt.get("lkg_reference_required") is not False:
            raise ValueError("Digital Europe healthy exact evidence unexpectedly requires LKG")
        ready = (
            current.get("candidate_state") == "OPEN_CALL"
            and current.get("authority_url_verified") is True
            and bool(current.get("status_label"))
        )
        if receipt.get("material_admission_ready_for_downstream_review") is not bool(ready):
            raise ValueError("Digital Europe reconciliation downstream-review gate drift")

    if receipt.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("Digital Europe reconciliation promoted LKG to current truth")
    if receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("Digital Europe reconciliation skipped mandatory admission gate")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"Digital Europe reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("Digital Europe reconciliation crossed publication boundary")


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
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "semantic_reconciliation_passed": receipt["semantic_reconciliation_passed"],
        "lkg_reference_required": receipt["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
