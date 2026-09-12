#!/usr/bin/env python3
"""Semantic reconciliation for exact I3 Funding & Tenders evidence.

Previous/LKG receipts are comparison/reference only.  Even a healthy, exact,
current OPEN candidate remains non-authorizing until a separate field-scoped
material-admission step accepts the relevant fields.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_i3_ft_exact import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_I3_FT_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_I3_FT_RECONCILE_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "I3"
AUTHORITY_CLASS = "EISMEA_PLUS_EU_COMMISSION_FUNDING_TENDERS"
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
    parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("I3 reconciliation timestamps must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def _identity(evidence: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source_family": evidence.get("source_family"),
        "programme_family": evidence.get("programme_family"),
        "reference": evidence.get("reference"),
        "funding_tenders_authority_url": evidence.get("funding_tenders_authority_url"),
        "eismea_authority_url": evidence.get("eismea_authority_url"),
    }


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("I3 exact semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("I3 exact semantic fingerprint tampered")
    return dict(semantics)


def _is_healthy(evidence: Mapping[str, Any]) -> bool:
    return bool(
        evidence.get("source_health_state") == "HEALTHY"
        and evidence.get("lkg_required") is False
        and evidence.get("evidence_usable_for_reconciliation") is True
        and evidence.get("funding_tenders_authority_verified") is True
        and (evidence.get("eismea_receipt") or {}).get("health_state") == "HEALTHY"
        and evidence.get("cross_authority_status_consistent") is True
    )


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not I3 exact-call evidence")
    current_semantics = _validated_semantics(current)
    current_identity = _identity(current)
    current_healthy = _is_healthy(current)

    previous_semantics: dict[str, Any] | None = None
    previous_healthy = False
    previous_identity_match: bool | None = None
    if previous is not None:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not I3 exact-call evidence")
        previous_semantics = _validated_semantics(previous)
        previous_identity_match = _identity(previous) == current_identity
        if not previous_identity_match:
            raise ValueError("I3 exact-call reconciliation identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous I3 exact-call evidence is not strictly older than current evidence")
        previous_healthy = _is_healthy(previous)

    changes: list[dict[str, Any]] = []
    lkg_reference_required = False
    if not current_healthy:
        state = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
        semantic_reconciliation_passed = False
        lkg_reference_required = True
    elif previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        semantic_reconciliation_passed = True
    else:
        assert previous_semantics is not None
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "I3_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        semantic_reconciliation_passed = True

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    identifier_present = bool(str(current.get("reference") or "").strip() and str(current.get("call_identifier") or "").strip())
    exact_current_status_proven = bool(
        current_healthy
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
        and identifier_present
    )
    review_ready = exact_current_status_proven and semantic_reconciliation_passed

    missing = ["field_scoped_material_admission"]
    if not current_healthy:
        missing.insert(0, "current_exact_authority_unresolved")
    elif not exact_current_status_proven:
        missing.insert(0, "exact_current_status_not_materially_proven")
    if candidate == "OPEN_CALL" and not identifier_present:
        missing.insert(0, "official_call_or_topic_identifier")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "reference": current.get("reference"),
        "call_identifier": current.get("call_identifier"),
        "identity": current_identity,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_source_health_state": current.get("source_health_state"),
        "previous_source_health_state": previous.get("source_health_state") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "previous_identity_match": previous_identity_match,
        "candidate_state": candidate,
        "status_label": current.get("status_label"),
        "deadline_candidate": current.get("deadline_candidate"),
        "budget_candidate": current.get("budget_candidate"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": semantic_reconciliation_passed,
        "lkg_reference_required": lkg_reference_required,
        "lkg_reference_available": bool(previous is not None and previous_healthy),
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
        raise ValueError("I3 reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("source_family") != SOURCE_FAMILY or receipt.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("I3 reconciliation family drift")
    if receipt.get("authority_class") != AUTHORITY_CLASS:
        raise ValueError("I3 reconciliation authority-class drift")
    if receipt.get("identity") != _identity(current):
        raise ValueError("I3 reconciliation current identity binding failed")
    if receipt.get("reference") != current.get("reference") or receipt.get("call_identifier") != current.get("call_identifier"):
        raise ValueError("I3 reconciliation exact identifier binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("I3 reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("I3 reconciliation current semantic binding failed")

    current_healthy = _is_healthy(current)
    previous_healthy = False
    if previous is None:
        if receipt.get("previous_evidence_sha256") is not None or receipt.get("previous_source_health_state") is not None:
            raise ValueError("I3 baseline unexpectedly bound previous evidence")
        if receipt.get("previous_identity_match") is not None:
            raise ValueError("I3 baseline invented previous identity result")
    else:
        validate_evidence(previous)
        if _identity(previous) != _identity(current):
            raise ValueError("I3 reconciliation previous identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous I3 exact-call evidence is not strictly older than current evidence")
        if receipt.get("previous_identity_match") is not True:
            raise ValueError("I3 reconciliation lost previous same-identity binding")
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("I3 reconciliation previous evidence hash mismatch")
        if receipt.get("previous_source_health_state") != previous.get("source_health_state"):
            raise ValueError("I3 reconciliation previous source-health binding failed")
        previous_healthy = _is_healthy(previous)

    if not current_healthy:
        expected = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
        if receipt.get("semantic_reconciliation_passed") is not False:
            raise ValueError("degraded I3 current incorrectly passed semantic reconciliation")
        if receipt.get("semantic_change_count") != 0 or receipt.get("semantic_changes") != []:
            raise ValueError("degraded I3 current fabricated semantic changes")
        if receipt.get("lkg_reference_required") is not True:
            raise ValueError("degraded I3 current did not require LKG/reference handling")
        if receipt.get("lkg_reference_available") is not bool(previous is not None and previous_healthy):
            raise ValueError("degraded I3 current LKG availability drift")
        if receipt.get("material_admission_ready_for_downstream_review") is not False:
            raise ValueError("degraded I3 current reached material review gate")
        if "current_exact_authority_unresolved" not in set(receipt.get("missing_for_material_admission") or []):
            raise ValueError("degraded I3 current omitted unresolved-authority blocker")
    elif previous is None:
        expected = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif not previous_healthy:
        expected = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        if receipt.get("semantic_change_count") != 0 or receipt.get("semantic_changes") != []:
            raise ValueError("I3 source-health recovery fabricated semantic changes")
    else:
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "I3_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
    if receipt.get("reconciliation_state") != expected:
        raise ValueError("I3 reconciliation state disagrees with source-health/semantic evidence")

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    identifier_present = bool(str(current.get("reference") or "").strip() and str(current.get("call_identifier") or "").strip())
    expected_ready = bool(
        current_healthy
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
        and identifier_present
    )
    if receipt.get("material_admission_ready_for_downstream_review") is not expected_ready:
        raise ValueError("I3 reconciliation downstream-review gate drift")
    missing = set(receipt.get("missing_for_material_admission") or [])
    if "field_scoped_material_admission" not in missing:
        raise ValueError("I3 reconciliation omitted final material admission requirement")
    if candidate == "OPEN_CALL" and not identifier_present and "official_call_or_topic_identifier" not in missing:
        raise ValueError("I3 reconciliation relaxed hard OPEN identifier gate")
    if current_healthy and receipt.get("semantic_reconciliation_passed") is not True:
        raise ValueError("healthy I3 reconciliation skipped mandatory semantic gate")
    if receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("I3 reconciliation skipped final material gate")
    if receipt.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("I3 reconciliation promoted LKG to current truth")
    if current_healthy and receipt.get("lkg_reference_required") is not False:
        raise ValueError("healthy I3 current incorrectly required LKG")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"I3 reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("I3 reconciliation crossed publication boundary")


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
        "source_health_state": receipt["current_source_health_state"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "lkg_reference_required": receipt["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
        "closed_call_authorized": receipt["closed_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
