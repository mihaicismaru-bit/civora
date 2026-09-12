#!/usr/bin/env python3
"""Semantic reconciliation for exact EEA Civil Society Fund Romania Call #6 evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eea_civil_society_fund_call6_exact import (
    AUTHORITY_CLASS,
    OFFICIAL_CALL_IDENTIFIER,
    PROGRAMME_FAMILY,
    PROGRAMME_ID,
    SCHEMA as EXACT_SCHEMA,
    SOURCE_FAMILY,
    canonical_json,
    validate_evidence,
)

SCHEMA = "PARTENER_EU_EEA_CSF_RO_CALL6_RECONCILIATION_V1"
PARSER_VERSION = "EEA_CSF_RO_CALL6_RECONCILE_V1"
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
        raise ValueError("EEA CSF reconciliation timestamps must be timezone-aware")
    return parsed


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, Mapping):
        raise ValueError("EEA CSF exact semantics missing")
    row = dict(semantics)
    if sha256_json(row) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("EEA CSF exact semantic fingerprint tampered")
    return row


def _healthy(evidence: Mapping[str, Any] | None) -> bool:
    return bool(
        evidence is not None
        and evidence.get("source_health_state") == "HEALTHY"
        and evidence.get("lkg_required") is False
    )


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not EEA CSF Call #6 exact evidence")
    current_semantics = _validated_semantics(current)
    previous_semantics: dict[str, Any] | None = None

    if previous is not None:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not EEA CSF Call #6 exact evidence")
        previous_semantics = _validated_semantics(previous)
        if previous.get("identity_key") != current.get("identity_key"):
            raise ValueError("EEA CSF exact reconciliation identity mismatch")
        if previous.get("official_call_identifier") != OFFICIAL_CALL_IDENTIFIER:
            raise ValueError("EEA CSF previous evidence lost Call #6 identifier")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous EEA CSF exact evidence is not strictly older than current evidence")

    changes: list[dict[str, Any]] = []
    current_healthy = _healthy(current)
    previous_healthy = _healthy(previous)
    semantic_reconciliation_passed = current_healthy
    lkg_reference_required = not current_healthy
    lkg_reference_available = bool(lkg_reference_required and previous_healthy)

    if not current_healthy:
        state = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
    elif previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    else:
        assert previous_semantics is not None
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "EEA_CSF_CALL6_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    exact_current_status_proven = bool(
        current_healthy
        and current.get("discovery_link_verified") is True
        and current.get("official_call_identifier") == OFFICIAL_CALL_IDENTIFIER
        and candidate in {"OPEN_CALL", "CLOSED_CALL"}
        and status in {"open", "closed"}
    )
    previous_same_identity_healthy = bool(previous is not None and previous_healthy)
    review_ready = exact_current_status_proven and previous_same_identity_healthy

    missing = ["field_scoped_material_admission"]
    if not previous_same_identity_healthy:
        missing.insert(0, "previous_same_identity_healthy_exact_receipt_or_reviewed_baseline_exception")
    if not exact_current_status_proven:
        missing.insert(0, "exact_current_status_not_materially_proven")
    if lkg_reference_required:
        missing.insert(0, "fresh_exact_current_authority")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "programme_id": PROGRAMME_ID,
        "authority_class": AUTHORITY_CLASS,
        "official_call_identifier": OFFICIAL_CALL_IDENTIFIER,
        "identity_key": current.get("identity_key"),
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "candidate_state": candidate,
        "status_label": current.get("status_label"),
        "deadline_candidate": current.get("deadline_candidate"),
        "budget_candidate": current.get("budget_candidate"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": lkg_reference_available,
        "lkg_reference_is_current_truth": False,
        "material_admission_ready_for_downstream_review": review_ready,
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
        raise ValueError("EEA CSF Call #6 reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("EEA CSF reconciliation family drift")
    if receipt.get("programme_id") != PROGRAMME_ID or receipt.get("official_call_identifier") != OFFICIAL_CALL_IDENTIFIER:
        raise ValueError("EEA CSF reconciliation call identity drift")
    if receipt.get("identity_key") != current.get("identity_key"):
        raise ValueError("EEA CSF reconciliation current identity binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("EEA CSF reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("EEA CSF reconciliation current semantic binding failed")
    if receipt.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("EEA CSF reconciliation promoted LKG to current truth")

    current_healthy = _healthy(current)
    previous_healthy = _healthy(previous)
    if previous is not None:
        validate_evidence(previous)
        if previous.get("identity_key") != current.get("identity_key"):
            raise ValueError("EEA CSF reconciliation previous identity drift")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("EEA CSF reconciliation accepted non-older previous evidence")
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("EEA CSF reconciliation previous evidence hash mismatch")

    if not current_healthy:
        if receipt.get("reconciliation_state") != "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED":
            raise ValueError("degraded EEA CSF current did not fail closed")
        if receipt.get("semantic_reconciliation_passed") is not False:
            raise ValueError("degraded EEA CSF current fabricated semantic reconciliation")
        if receipt.get("semantic_change_count") != 0 or receipt.get("semantic_changes") != []:
            raise ValueError("degraded EEA CSF current fabricated semantic changes")
        if receipt.get("lkg_reference_required") is not True:
            raise ValueError("degraded EEA CSF current did not require LKG/reference handling")
        if receipt.get("lkg_reference_available") is not previous_healthy:
            raise ValueError("EEA CSF LKG availability drift")
    elif previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
            raise ValueError("EEA CSF baseline reconciliation state invalid")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("EEA CSF baseline unexpectedly became review-ready")
        if receipt.get("lkg_reference_required") is not False:
            raise ValueError("healthy EEA CSF baseline incorrectly required LKG")
    elif not previous_healthy:
        if receipt.get("reconciliation_state") != "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING":
            raise ValueError("EEA CSF source recovery state invalid")
    else:
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "EEA_CSF_CALL6_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("EEA CSF reconciliation state disagrees with semantic fingerprints")

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    exact_current_status_proven = bool(
        current_healthy
        and current.get("discovery_link_verified") is True
        and current.get("official_call_identifier") == OFFICIAL_CALL_IDENTIFIER
        and candidate in {"OPEN_CALL", "CLOSED_CALL"}
        and status in {"open", "closed"}
    )
    expected_ready = exact_current_status_proven and previous_healthy
    if receipt.get("material_admission_ready_for_downstream_review") is not expected_ready:
        raise ValueError("EEA CSF downstream-review gate drift")
    missing = set(receipt.get("missing_for_material_admission") or [])
    if "field_scoped_material_admission" not in missing:
        raise ValueError("EEA CSF reconciliation omitted final material admission requirement")
    if receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("EEA CSF reconciliation skipped mandatory material gate")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EEA CSF reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("EEA CSF reconciliation crossed publication boundary")


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
        "official_call_identifier": receipt["official_call_identifier"],
        "candidate_state": receipt["candidate_state"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "lkg_reference_required": receipt["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": False,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
