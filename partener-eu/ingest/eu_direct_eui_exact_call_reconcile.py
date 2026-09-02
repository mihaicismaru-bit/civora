#!/usr/bin/env python3
"""Semantic reconciliation for exact European Urban Initiative call evidence."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
from typing import Any, Mapping

from eu_direct_eui_exact_call import SCHEMA as EXACT_SCHEMA, canonical_json, validate_evidence

SCHEMA = "PARTENER_EU_EUI_EXACT_CALL_RECONCILIATION_V1"
PARSER_VERSION = "EU_DIRECT_EUI_EXACT_CALL_RECONCILE_V1"
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
        raise ValueError("EUI reconciliation timestamps must be timezone-aware")
    return parsed


def _validated_semantics(evidence: Mapping[str, Any]) -> dict[str, Any]:
    validate_evidence(evidence)
    semantics = evidence.get("exact_semantics")
    if not isinstance(semantics, dict):
        raise ValueError("EUI exact semantics missing")
    if sha256_json(semantics) != evidence.get("exact_semantic_fingerprint"):
        raise ValueError("EUI exact semantic fingerprint tampered")
    return dict(semantics)


def reconcile(current: Mapping[str, Any], previous: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if current.get("schema") != EXACT_SCHEMA:
        raise ValueError("current evidence is not EUI exact-call evidence")
    current_semantics = _validated_semantics(current)
    changes: list[dict[str, Any]] = []

    if previous is None:
        state = "BASELINE_CAPTURED_NON_AUTHORIZING"
    else:
        if previous.get("schema") != EXACT_SCHEMA:
            raise ValueError("previous evidence is not EUI exact-call evidence")
        previous_semantics = _validated_semantics(previous)
        if previous.get("identity_key") != current.get("identity_key"):
            raise ValueError("EUI exact-call reconciliation identity mismatch")
        if parse_time(str(previous.get("fetched_at"))) > parse_time(str(current.get("fetched_at"))):
            raise ValueError("previous EUI exact-call evidence is newer than current evidence")
        for key in sorted(set(previous_semantics) | set(current_semantics)):
            before = previous_semantics.get(key)
            after = current_semantics.get(key)
            if before != after:
                changes.append({"field": key, "before": before, "after": after})
        state = "NO_CHANGE" if not changes else "EUI_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    exact_current_status_proven = bool(
        current.get("source_health_state") == "HEALTHY"
        and current.get("discovery_link_verified") is True
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
    )
    official_identifier_present = bool(str(current.get("official_call_identifier") or "").strip())
    open_gate_identity_ok = candidate != "OPEN_CALL" or official_identifier_present
    review_ready = exact_current_status_proven and open_gate_identity_ok

    missing = ["field_scoped_material_admission"]
    if not exact_current_status_proven:
        missing.insert(0, "exact_current_status_not_materially_proven")
    if candidate == "OPEN_CALL" and not official_identifier_present:
        missing.insert(0, "official_call_or_topic_identifier")

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": "EU_DIRECT",
        "programme_family": "EUROPEAN_URBAN_INITIATIVE",
        "authority_class": "EUI_EXACT_CALL_DETAIL_AND_TOR",
        "identity_key": current.get("identity_key"),
        "identity_slug": current.get("identity_slug"),
        "official_call_identifier": current.get("official_call_identifier"),
        "current_fetched_at": current.get("fetched_at"),
        "previous_fetched_at": previous.get("fetched_at") if previous is not None else None,
        "current_evidence_sha256": sha256_json(current),
        "previous_evidence_sha256": sha256_json(previous) if previous is not None else None,
        "current_exact_semantic_fingerprint": current.get("exact_semantic_fingerprint"),
        "previous_exact_semantic_fingerprint": previous.get("exact_semantic_fingerprint") if previous is not None else None,
        "candidate_state": candidate,
        "status_label": current.get("status_label"),
        "deadline_candidate": current.get("deadline_candidate"),
        "reconciliation_state": state,
        "semantic_change_count": len(changes),
        "semantic_changes": changes,
        "semantic_reconciliation_passed": True,
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
        raise ValueError("EUI reconciliation schema/parser drift")
    validate_evidence(current)
    if receipt.get("identity_key") != current.get("identity_key") or receipt.get("identity_slug") != current.get("identity_slug"):
        raise ValueError("EUI reconciliation current identity binding failed")
    if receipt.get("current_evidence_sha256") != sha256_json(current):
        raise ValueError("EUI reconciliation current evidence hash mismatch")
    if receipt.get("current_exact_semantic_fingerprint") != current.get("exact_semantic_fingerprint"):
        raise ValueError("EUI reconciliation current semantic binding failed")
    if previous is None:
        if receipt.get("reconciliation_state") != "BASELINE_CAPTURED_NON_AUTHORIZING":
            raise ValueError("EUI baseline reconciliation state invalid")
        if receipt.get("previous_evidence_sha256") is not None:
            raise ValueError("EUI baseline unexpectedly bound previous evidence")
    else:
        validate_evidence(previous)
        if receipt.get("previous_evidence_sha256") != sha256_json(previous):
            raise ValueError("EUI reconciliation previous evidence hash mismatch")
        expected = (
            "NO_CHANGE"
            if current.get("exact_semantic_fingerprint") == previous.get("exact_semantic_fingerprint")
            else "EUI_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
        )
        if receipt.get("reconciliation_state") != expected:
            raise ValueError("EUI reconciliation state disagrees with semantic fingerprints")

    candidate = current.get("candidate_state")
    status = str(current.get("status_label") or "").casefold()
    exact_current_status_proven = bool(
        current.get("source_health_state") == "HEALTHY"
        and current.get("discovery_link_verified") is True
        and candidate in {"OPEN_CALL", "FORTHCOMING_CALL", "CLOSED_CALL"}
        and status in {"open", "forthcoming", "closed"}
    )
    official_identifier_present = bool(str(current.get("official_call_identifier") or "").strip())
    expected_ready = exact_current_status_proven and (candidate != "OPEN_CALL" or official_identifier_present)
    if receipt.get("material_admission_ready_for_downstream_review") is not expected_ready:
        raise ValueError("EUI reconciliation downstream-review gate drift")
    missing = set(receipt.get("missing_for_material_admission") or [])
    if "field_scoped_material_admission" not in missing:
        raise ValueError("EUI reconciliation omitted final material admission requirement")
    if candidate == "OPEN_CALL" and not official_identifier_present and "official_call_or_topic_identifier" not in missing:
        raise ValueError("EUI reconciliation relaxed the hard OPEN identifier gate")
    if receipt.get("semantic_reconciliation_passed") is not True or receipt.get("field_scoped_material_admission_required") is not True:
        raise ValueError("EUI reconciliation skipped mandatory gate")
    for key in MATERIAL_FLAGS:
        if receipt.get(key) is not False:
            raise ValueError(f"EUI reconciliation attempted authorization: {key}")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("EUI reconciliation crossed publication boundary")


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
        "material_admission_ready_for_downstream_review": receipt["material_admission_ready_for_downstream_review"],
        "open_call_authorized": receipt["open_call_authorized"],
        "closed_call_authorized": receipt["closed_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
