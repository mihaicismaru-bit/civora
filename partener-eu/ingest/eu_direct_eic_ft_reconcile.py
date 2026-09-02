#!/usr/bin/env python3
"""Semantic reconciliation for exact current Horizon Europe / EIC F&T evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_eic_ft_exact import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_EIC_FT_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_EIC_FT_RECONCILE_V1"
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
        raise ValueError("exact EIC semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("exact EIC semantic fingerprint tampered")
    return dict(semantics)


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not EIC exact evidence")
    current_semantics = _validated_semantics(current)
    changes: list[dict[str, Any]] = []

    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not EIC exact evidence")
        previous_semantics = _validated_semantics(previous)
        if previous.get("reference") != current.get("reference"):
            raise ValueError("EIC reconciliation identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous EIC evidence is newer than current evidence")
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "EIC_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    ready = bool(
        current.get("candidate_state") == "OPEN_CALL"
        and current.get("authority_url_verified") is True
        and str(current.get("status_label") or "").casefold() == "open"
    )
    missing = ["field_scoped_material_admission"]
    if current.get("candidate_state") != "OPEN_CALL" or str(current.get("status_label") or "").casefold() != "open":
        missing.insert(0, "current_funding_tenders_status_is_not_open")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "HORIZON_EUROPE_EIC",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "reference": current.get("reference"),
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "candidate_state": current.get("candidate_state"),
        "status_label": current.get("status_label"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": True,
        "material_admission_ready_for_downstream_review": ready,
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
        raise ValueError("EIC reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("reference") != current.get("reference"):
        raise ValueError("EIC reconciliation current identity binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("EIC reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("EIC reconciliation current semantic binding failed")
    if previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
            raise ValueError("EIC baseline reconciliation state invalid")
        if receipt.get("previous_evidence_sha256") is not None:
            raise ValueError("EIC baseline unexpectedly bound previous evidence")
    else:
        validate_evidence(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("EIC reconciliation previous evidence hash mismatch")
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "EIC_EXACT_TOPIC_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("EIC reconciliation state disagrees with semantic fingerprints")
    ready = bool(
        current.get("candidate_state") == "OPEN_CALL"
        and current.get("authority_url_verified") is True
        and str(current.get("status_label") or "").casefold() == "open"
    )
    if receipt.get("material_admission_ready_for_downstream_review") is not ready:
        raise ValueError("EIC reconciliation downstream-review gate drift")
    if receipt.get("semantic_reconciliation_passed") is not True or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("EIC reconciliation skipped mandatory gate")
    if "field_scoped_material_admission" not in set(receipt.get("missing_for_material_admission") or []):
        raise ValueError("EIC reconciliation omitted final material admission requirement")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EIC reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("EIC reconciliation crossed publication boundary")


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
        "candidate_state": receipt["candidate_state"],
        "status_label": receipt["status_label"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
