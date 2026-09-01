#!/usr/bin/env python3
"""Status-only material admission for Creative Europe competitive/cascading calls.

This gate is deliberately narrower than publication. It may admit only the current
OPEN status of one exact Funding & Tenders competitive-call identity after exact
authority readback and semantic reconciliation. Deadline, budget, eligibility,
publication, distribution and alerts remain separately unauthorized.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
from typing import Any, Mapping

import creative_europe_ft_competitive_exact as exact
import creative_europe_ft_competitive_reconcile as reconcile_exact

ADMISSION_ID = "CREATIVE_EUROPE_FT_COMPETITIVE_MATERIAL_ADMISSION_V1"
SCHEMA = "PARTENER_EU_CREATIVE_EUROPE_FT_COMPETITIVE_MATERIAL_ADMISSION_V1"
OBSERVATION_STATE = "OPEN_STATUS_MATERIAL_ADMITTED_NON_PUBLISHING"
STATUS_SCOPE = "STATUS_ONLY"
WITHHELD_FIELDS = ("deadline", "budget", "eligibility", "participation", "publication", "distribution", "call_alert")


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_time(value: str, *, field: str) -> dt.datetime:
    text = str(value or "")
    if not text:
        raise ValueError(f"{field} is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed.astimezone(dt.timezone.utc)


def admit_status(
    exact_evidence: Mapping[str, Any],
    reconciliation: Mapping[str, Any],
    *,
    admitted_at: str | None = None,
) -> dict[str, Any]:
    """Admit only the OPEN status fact; keep every other material field gated."""
    exact.validate_exact_evidence(exact_evidence)
    reconcile_exact.validate_receipt(reconciliation)

    exact_sha = _sha(dict(exact_evidence))
    reconciliation_sha = _sha(dict(reconciliation))
    identity = str(exact_evidence.get("identity_key") or "")
    competitive_id = exact.validate_competitive_id(str(exact_evidence.get("competitive_call_id") or ""))
    parent = exact.validate_reference(str(exact_evidence.get("parent_reference") or ""))

    if reconciliation.get("identity_key") != identity:
        raise ValueError("competitive admission identity mismatch")
    if reconciliation.get("competitive_call_id") != competitive_id:
        raise ValueError("competitive admission id mismatch")
    if reconciliation.get("parent_reference") != parent:
        raise ValueError("competitive admission parent mismatch")
    if reconciliation.get("current_evidence_sha256") != exact_sha:
        raise ValueError("competitive admission reconciliation does not bind exact evidence")
    if reconciliation.get("current_semantic_fingerprint") != exact_evidence.get("semantic_fingerprint"):
        raise ValueError("competitive admission semantic fingerprint mismatch")
    if reconciliation.get("current_source_candidate_semantic_fingerprint") != exact_evidence.get("source_candidate_semantic_fingerprint"):
        raise ValueError("competitive admission source-candidate binding mismatch")

    if exact_evidence.get("authority_url_verified") is not True:
        raise ValueError("competitive admission requires verified exact authority URL")
    if exact_evidence.get("candidate_observation_state") != "OPEN_CALL":
        raise ValueError("competitive admission requires current exact OPEN_CALL evidence")
    if reconciliation.get("candidate_observation_state") != "OPEN_CALL":
        raise ValueError("competitive admission reconciliation is not OPEN_CALL")
    if reconciliation.get("candidate_status_label") != exact_evidence.get("status_label"):
        raise ValueError("competitive admission status label mismatch")
    if reconciliation.get("semantic_reconciliation_passed") is not True:
        raise ValueError("competitive admission requires passed semantic reconciliation")
    if reconciliation.get("material_admission_ready_for_downstream_review") is not True:
        raise ValueError("competitive admission downstream-review gate is not ready")
    if reconciliation.get("requires_material_admission") is not True:
        raise ValueError("competitive admission input skipped material-admission boundary")

    exact_time = _parse_time(str(exact_evidence.get("fetched_at") or ""), field="exact fetched_at")
    reconciled_time = _parse_time(str(reconciliation.get("reconciled_at") or ""), field="reconciled_at")
    admission_time = _parse_time(admitted_at, field="admitted_at") if admitted_at else dt.datetime.now(dt.timezone.utc)
    if reconciled_time < exact_time:
        raise ValueError("competitive admission reconciliation predates exact evidence")
    if admission_time < reconciled_time:
        raise ValueError("competitive admission predates reconciliation")

    semantic_change = bool(reconciliation.get("semantic_changed"))
    reconciliation_state = str(reconciliation.get("reconciliation_state") or "")
    distribution_change_candidate = (
        semantic_change
        and reconciliation_state == "EXACT_COMPETITIVE_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    )

    receipt: dict[str, Any] = {
        "schema": SCHEMA,
        "admission_id": ADMISSION_ID,
        "source_family": "EU_DIRECT",
        "programme_family": "CREATIVE_EUROPE",
        "opportunity_class": "COMPETITIVE_CASCADING_CALL",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS_COMPETITIVE_CALL",
        "observation_state": OBSERVATION_STATE,
        "identity_key": identity,
        "competitive_call_id": competitive_id,
        "parent_reference": parent,
        "authority_url": exact_evidence.get("authority_url"),
        "authority_url_verified": True,
        "status_scope": STATUS_SCOPE,
        "admitted_status": "OPEN_CALL",
        "admitted_status_label": exact_evidence.get("status_label"),
        "admitted_at": admission_time.isoformat().replace("+00:00", "Z"),
        "exact_fetched_at": exact_evidence.get("fetched_at"),
        "exact_run_id": exact_evidence.get("run_id"),
        "exact_evidence_sha256": exact_sha,
        "exact_semantic_fingerprint": exact_evidence.get("semantic_fingerprint"),
        "source_candidate_semantic_fingerprint": exact_evidence.get("source_candidate_semantic_fingerprint"),
        "reconciliation_sha256": reconciliation_sha,
        "reconciliation_fingerprint": reconciliation.get("reconciliation_fingerprint"),
        "reconciliation_state": reconciliation_state,
        "semantic_change_count": int(reconciliation.get("semantic_change_count") or 0),
        "semantic_changed": semantic_change,
        "admitted_material_fields": ["status"],
        "withheld_material_fields": list(WITHHELD_FIELDS),
        "withheld_material_candidates": {
            "deadline_candidate": exact_evidence.get("deadline_candidate"),
            "budget_candidate": exact_evidence.get("budget_candidate"),
        },
        "material_admission_scope": STATUS_SCOPE,
        "material_admission_complete_for_status": True,
        "material_admission_complete_for_call": False,
        "material_fact_use": True,
        "material_fact_use_scope": ["status"],
        "status_fact_authorized": True,
        "open_call_authorized": True,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "distribution_change_candidate": distribution_change_candidate,
        "requires_publication_review": True,
        "requires_distribution_change_gate": True,
        "requires_field_specific_admission": ["deadline", "budget", "eligibility", "participation"],
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
    }
    receipt["admission_fingerprint"] = _sha({
        "identity_key": identity,
        "exact_evidence_sha256": exact_sha,
        "reconciliation_sha256": reconciliation_sha,
        "admitted_status": receipt["admitted_status"],
        "admitted_status_label": receipt["admitted_status_label"],
        "material_admission_scope": STATUS_SCOPE,
        "distribution_change_candidate": distribution_change_candidate,
    })
    validate_admission(receipt)
    return receipt


def validate_admission(receipt: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA or receipt.get("admission_id") != ADMISSION_ID:
        raise ValueError("competitive material admission identity drift")
    if receipt.get("source_family") != "EU_DIRECT" or receipt.get("programme_family") != "CREATIVE_EUROPE":
        raise ValueError("competitive material admission programme boundary drift")
    if receipt.get("opportunity_class") != "COMPETITIVE_CASCADING_CALL":
        raise ValueError("competitive material admission opportunity-class drift")
    cid = exact.validate_competitive_id(str(receipt.get("competitive_call_id") or ""))
    parent = exact.validate_reference(str(receipt.get("parent_reference") or ""))
    if receipt.get("identity_key") != f"FUNDING_TENDERS_COMPETITIVE_CALL:{cid}":
        raise ValueError("competitive material admission identity-key drift")
    if parent != str(receipt.get("parent_reference") or "").upper():
        raise ValueError("competitive material admission parent drift")
    if receipt.get("authority_url") != exact.competitive_url(cid) or receipt.get("authority_url_verified") is not True:
        raise ValueError("competitive material admission authority drift")
    if receipt.get("observation_state") != OBSERVATION_STATE:
        raise ValueError("competitive material admission observation-state drift")
    if receipt.get("status_scope") != STATUS_SCOPE or receipt.get("material_admission_scope") != STATUS_SCOPE:
        raise ValueError("competitive material admission widened beyond status")
    if receipt.get("admitted_status") != "OPEN_CALL" or not receipt.get("admitted_status_label"):
        raise ValueError("competitive material admission status missing")
    if receipt.get("admitted_material_fields") != ["status"]:
        raise ValueError("competitive material admission fields widened")
    if set(receipt.get("withheld_material_fields") or []) != set(WITHHELD_FIELDS):
        raise ValueError("competitive material admission withheld-field contract drift")
    if receipt.get("material_admission_complete_for_status") is not True or receipt.get("material_admission_complete_for_call") is not False:
        raise ValueError("competitive material admission completeness drift")
    if receipt.get("material_fact_use") is not True or receipt.get("material_fact_use_scope") != ["status"]:
        raise ValueError("competitive material admission fact-use scope drift")
    if receipt.get("status_fact_authorized") is not True or receipt.get("open_call_authorized") is not True:
        raise ValueError("competitive material admission did not authorize status")
    for key in (
        "deadline_authorized", "budget_authorized", "eligibility_authorized",
        "publish_authorized", "distribution_authorized", "call_alert_authorized",
    ):
        if receipt.get(key) is not False:
            raise ValueError(f"competitive material admission over-authorized: {key}")
    if receipt.get("requires_publication_review") is not True or receipt.get("requires_distribution_change_gate") is not True:
        raise ValueError("competitive material admission skipped downstream gates")
    if receipt.get("publication_effect") != "NONE" or receipt.get("canonical_corpus_mutation") is not False:
        raise ValueError("competitive material admission crossed publication boundary")
    for key in (
        "exact_evidence_sha256", "exact_semantic_fingerprint", "reconciliation_sha256",
        "reconciliation_fingerprint", "admission_fingerprint",
    ):
        if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(key) or "")):
            raise ValueError(f"competitive material admission hash invalid: {key}")
    source_fp = receipt.get("source_candidate_semantic_fingerprint")
    if source_fp is not None and not re.fullmatch(r"[0-9a-f]{64}", str(source_fp)):
        raise ValueError("competitive material admission source-candidate fingerprint invalid")
    if receipt.get("reconciliation_state") not in {
        "BASELINE_CAPTURED_NON_AUTHORIZING",
        "NO_CHANGE",
        "EXACT_COMPETITIVE_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING",
    }:
        raise ValueError("competitive material admission reconciliation state invalid")
    if receipt.get("distribution_change_candidate") is True and receipt.get("semantic_changed") is not True:
        raise ValueError("competitive material admission invented distribution change")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exact", type=pathlib.Path, required=True)
    parser.add_argument("--reconciliation", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    exact_evidence = json.loads(args.exact.read_text(encoding="utf-8"))
    reconciliation = json.loads(args.reconciliation.read_text(encoding="utf-8"))
    receipt = admit_status(exact_evidence, reconciliation)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "identity_key": receipt["identity_key"],
        "material_admission_scope": receipt["material_admission_scope"],
        "open_call_authorized": receipt["open_call_authorized"],
        "deadline_authorized": receipt["deadline_authorized"],
        "budget_authorized": receipt["budget_authorized"],
        "eligibility_authorized": receipt["eligibility_authorized"],
        "publish_authorized": receipt["publish_authorized"],
        "distribution_authorized": receipt["distribution_authorized"],
        "call_alert_authorized": receipt["call_alert_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
