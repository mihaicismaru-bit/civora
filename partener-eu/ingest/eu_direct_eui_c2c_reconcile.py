#!/usr/bin/env python3
"""Semantic reconciliation for exact EUI City-to-City Exchanges evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_eui_c2c_exact import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_EUI_C2C_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_EUI_C2C_RECONCILE_V1"
MATERIAL_FLAGS = (
    "material_fact_use", "open_call_authorized", "closed_call_authorized",
    "deadline_authorized", "budget_authorized", "eligibility_authorized",
    "publish_authorized", "distribution_authorized", "call_alert_authorized",
)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def parse_time(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("EUI C2C reconciliation timestamps must be timezone-aware")
    return parsed


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("EUI C2C exact semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("EUI C2C semantic fingerprint tampered")
    return dict(semantics)


def _healthy(evidence: Mapping[str, Any]) -> bool:
    return evidence.get("source_health_state") == "HEALTHY" and evidence.get("lkg_required") is False


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not EUI C2C exact evidence")
    current_semantics = _validated_semantics(current)
    previous_semantics = None
    previous_healthy = False
    if previous is not None:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not EUI C2C exact evidence")
        previous_semantics = _validated_semantics(previous)
        if previous.get("identity_key") != current.get("identity_key"):
            raise ValueError("EUI C2C reconciliation identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous EUI C2C evidence is not strictly older than current")
        previous_healthy = _healthy(previous)

    current_healthy = _healthy(current)
    changes: list[dict[str, Any]] = []
    if not current_healthy:
        state = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
        passed = False
        lkg_required = True
    elif previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
        passed = True
        lkg_required = False
    elif not previous_healthy:
        state = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
        passed = True
        lkg_required = False
    else:
        assert previous_semantics is not None
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "EUI_C2C_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        passed = True
        lkg_required = False

    missing = ["official_call_or_topic_identifier", "field_scoped_material_admission"]
    if not current_healthy:
        missing.insert(0, "current_exact_authority_unresolved")
    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "EUROPEAN_URBAN_INITIATIVE",
        "opportunity_family": "CITY_TO_CITY_EXCHANGES",
        "authority_class": "EUI_EXACT_C2C_PAGE_AND_CURRENT_GUIDANCE",
        "identity_key": current.get("identity_key"),
        "identity_slug": current.get("identity_slug"),
        "official_call_identifier": None,
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_source_health_state": current.get("source_health_state"),
        "previous_source_health_state": previous.get("source_health_state") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "candidate_state": current.get("candidate_state"),
        "status_label": current.get("status_label"),
        "deadline_candidate": None,
        "authority_discrepancy": current.get("authority_discrepancy"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": passed,
        "lkg_reference_required": lkg_required,
        "lkg_reference_available": bool(previous is not None and previous_healthy),
        "lkg_reference_is_current_truth": False,
        "material_admission_ready_for_downstream_review": False,
        "missing_for_material_admission": missing,
        "field_scoped_material_admission_required": True,
        "market_intelligence_only": True,
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
        raise ValueError("EUI C2C reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("identity_key") != current.get("identity_key") or receipt.get("identity_slug") != current.get("identity_slug"):
        raise ValueError("EUI C2C reconciliation lost exact identity")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("EUI C2C reconciliation current evidence hash mismatch")
    if receipt.get("official_call_identifier") is not None or receipt.get("deadline_candidate") is not None:
        raise ValueError("EUI C2C reconciliation fabricated identifier/deadline")
    if receipt.get("material_admission_ready_for_downstream_review") is not False:
        raise ValueError("EUI C2C without formal ID reached material review")
    if receipt.get("lkg_reference_is_current_truth") is not False:
        raise ValueError("EUI C2C reconciliation promoted LKG to current truth")
    current_healthy = _healthy(current)
    previous_healthy = False
    if previous is not None:
        validate_evidence(previous)
        if previous.get("identity_key") != current.get("identity_key"):
            raise ValueError("EUI C2C previous identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) >= parse_time(str(current.get("fetched_at"))):
            raise ValueError("EUI C2C previous evidence not strictly older")
        previous_healthy = _healthy(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("EUI C2C previous evidence hash mismatch")
    else:
        if receipt.get("previous_evidence_sha256") is not None:
            raise ValueError("EUI C2C baseline unexpectedly bound previous evidence")

    if not current_healthy:
        expected = "CURRENT_EXACT_AUTHORITY_UNRESOLVED_LKG_REQUIRED"
        if receipt.get("semantic_reconciliation_passed") is not False:
            raise ValueError("degraded EUI C2C passed semantic reconciliation")
        if receipt.get("semantic_changes") != [] or receipt.get("semantic_change_count") != 0:
            raise ValueError("degraded EUI C2C fabricated semantic change")
        if receipt.get("lkg_reference_required") is not True:
            raise ValueError("degraded EUI C2C failed to require LKG/reference")
    elif previous is None:
        expected = "BASELINE_CAPTURED_NON_AUTHORIZING"
    elif not previous_healthy:
        expected = "SOURCE_HEALTH_RECOVERED_BASELINE_REFRESH_NON_AUTHORIZING"
    else:
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "EUI_C2C_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
    if receipt.get("reconciliation_state") != expected:
        raise ValueError("EUI C2C reconciliation state drift")
    if current_healthy and receipt.get("semantic_reconciliation_passed") is not True:
        raise ValueError("healthy EUI C2C skipped semantic reconciliation")
    if current_healthy and receipt.get("lkg_reference_required") is not False:
        raise ValueError("healthy EUI C2C incorrectly requires LKG")
    if receipt.get("lkg_reference_available") is not bool(previous is not None and previous_healthy):
        raise ValueError("EUI C2C LKG availability drift")
    missing = set(receipt.get("missing_for_material_admission") or [])
    if "official_call_or_topic_identifier" not in missing or "field_scoped_material_admission" not in missing:
        raise ValueError("EUI C2C missing hard material-admission blockers")
    if receipt.get("market_intelligence_only") is not True:
        raise ValueError("EUI C2C reconciliation stopped being non-authorizing")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EUI C2C reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("EUI C2C reconciliation crossed publication boundary")


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
        "identity_slug": receipt["identity_slug"],
        "candidate_state": receipt["candidate_state"],
        "status_label": receipt["status_label"],
        "reconciliation_state": receipt["reconciliation_state"],
        "semantic_change_count": receipt["semantic_change_count"],
        "lkg_reference_required": receipt["lkg_reference_required"],
        "material_admission_ready_for_downstream_review": False,
        "open_call_authorized": False,
        "publication_effect": "NONE",
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
