#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "crm" / "pipeline_ingest_request_contract.json"
DEFAULT_PIPELINE_CONTRACT = EUCONS / "crm" / "pipeline_contract.json"

FORBIDDEN_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone",
    "home_address", "private_contact", "contact_name", "email", "phone", "cnp",
    "reviewer_name", "reviewer_email", "reviewer_phone",
}
DECISION_FIELDS = {"decision", "decision_source", "scope", "reviewer_ref", "decided_at"}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from keys(child)


def safe_ref(value: Any, field: str) -> str:
    require(isinstance(value, str) and 0 < len(value.strip()) <= 240, f"invalid {field}")
    value = value.strip()
    require("@" not in value and "\n" not in value and "\r" not in value, f"unsafe {field}")
    return value


def aware_timestamp(value: Any) -> str:
    require(isinstance(value, str) and value.strip(), "invalid decided_at")
    value = value.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid decided_at") from exc
    require(parsed.tzinfo is not None and parsed.utcoffset() is not None, "decided_at timezone required")
    return value


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("id") == "EUCONS-E11-R10-PIPELINE-INGEST-REQUEST-001", "ingest request contract id drift")
    require(contract.get("status") == "CANONICAL", "ingest request contract is not canonical")
    require(contract.get("source_review_contract") == "EUCONS-E11-R10-COMMERCIAL-REVIEW-001", "source review contract drift")
    require(contract.get("required_source_state") == "COMMERCIAL_PIPELINE_REVIEW_PENDING_HUMAN_DECISION", "source state drift")
    require(contract.get("required_source_decision") == "HUMAN_COMMERCIAL_PIPELINE_ENTRY_REVIEW", "source decision drift")
    require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "eligibility boundary drift")
    require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "research boundary drift")
    require(contract.get("pipeline_contract_id") == "R10-PIPELINE-001", "pipeline contract drift")
    require(contract.get("pipeline_engine_id") == "EUCONS_R10_UNIFIED_COMMERCIAL_PIPELINE", "pipeline engine drift")
    approval = contract.get("approval") or {}
    require(approval == {
        "decision": "APPROVE_PIPELINE_ENTRY",
        "decision_source": "HUMAN",
        "scope": "NON_WRITING_INGEST_REQUEST_ONLY",
        "reviewer_ref_required": True,
        "decided_at_timezone_required": True,
    }, "approval contract drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "HUMAN_APPROVED_PIPELINE_INGEST_REQUEST", "output state drift")
    require(output.get("human_approval_recorded") is True, "human approval boundary drift")
    require(output.get("persistence_executed") is False, "persistence failed open")
    require(output.get("requires_separate_persistence_step") is True, "separate persistence step missing")
    for field in ("pipeline_write_enabled", "crm_write_enabled", "external_contact_enabled",
                  "automatic_offer_enabled", "automatic_send_enabled"):
        require(output.get(field) is False, f"{field} must remain disabled")
    for field, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"rule failed open: {field}")


def validate_pipeline(pipeline: dict[str, Any], contract: dict[str, Any]) -> None:
    require(pipeline.get("id") == contract["pipeline_contract_id"], "unexpected pipeline contract")
    require(pipeline.get("engine_id") == contract["pipeline_engine_id"], "unexpected pipeline engine")
    require(pipeline.get("production_persistence_enabled") is False, "pipeline production persistence failed open")
    outputs = pipeline.get("outputs") or {}
    require(outputs.get("eligibility_state") == "NOT_ASSESSED", "pipeline eligibility drift")
    for field in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled"):
        require(outputs.get(field) is False, f"pipeline {field} failed open")
    require((pipeline.get("contact_gate") or {}).get("automatic_send") is False, "pipeline automatic send failed open")
    require((pipeline.get("commercial_gate") or {}).get("automatic_offer") is False, "pipeline automatic offer failed open")
    privacy = pipeline.get("privacy") or {}
    require(privacy.get("pipeline_stores_raw_contact_data") is False, "raw contact storage failed open")
    require(privacy.get("pipeline_stores_only_contact_reference") is True, "contact reference boundary drift")


def build_pipeline_ingest_request(review: dict[str, Any], decision: dict[str, Any],
                                  contract: dict[str, Any], pipeline: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    validate_pipeline(pipeline, contract)
    require(isinstance(review, dict), "review must be an object")
    require(isinstance(decision, dict), "decision must be an object")
    if FORBIDDEN_KEYS & set(keys(review)):
        raise ValueError("person-level field entered ingest request")
    if FORBIDDEN_KEYS & set(keys(decision)):
        raise ValueError("person-level field entered human decision")

    require(review.get("contract_id") == contract["source_review_contract"], "source review contract mismatch")
    require(review.get("record_state") == contract["required_source_state"], "review is not ingest-request ready")
    require(review.get("decision_required") == contract["required_source_decision"], "source decision mismatch")
    require(review.get("eligibility_state") == "NOT_ASSESSED", "eligibility was assessed")
    require(review.get("maximum_next_state") == "RESEARCH_READY", "research boundary crossed")
    require(review.get("human_review_required") is True, "source human review disappeared")
    for field in ("pipeline_write_enabled", "crm_write_enabled", "external_contact_enabled",
                  "automatic_offer_enabled", "automatic_send_enabled"):
        require(review.get(field) is False, f"source {field} failed open")

    require(set(decision) == DECISION_FIELDS, "human decision fields drift")
    approval = contract["approval"]
    require(decision.get("decision") == approval["decision"], "human decision is not approval")
    require(decision.get("decision_source") == "HUMAN", "decision source must be HUMAN")
    require(decision.get("scope") == approval["scope"], "approval scope must remain non-writing")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = aware_timestamp(decision.get("decided_at"))

    review_id = safe_ref(review.get("review_id"), "review_id")
    evaluation_id = safe_ref(review.get("source_evaluation_id"), "source_evaluation_id")
    prospect_id = safe_ref(review.get("prospect_id"), "prospect_id")
    opportunity_id = safe_ref(review.get("selected_opportunity_id"), "selected_opportunity_id")
    service_id = safe_ref(review.get("selected_service_id"), "selected_service_id")
    entry = review.get("proposed_pipeline_entry") or {}
    lane = safe_ref(entry.get("lane"), "pipeline lane")
    stage = safe_ref(entry.get("stage"), "pipeline stage")
    source_ref = safe_ref(entry.get("source_ref"), "pipeline source_ref")
    organization_ref = safe_ref(entry.get("organization_key_ref"), "organization_key_ref")
    require(lane in (pipeline.get("entry_lanes") or []), "pipeline lane unavailable")
    require((pipeline.get("entry_stage_by_lane") or {}).get(lane) == stage, "pipeline stage drift")
    require(source_ref == evaluation_id, "source_ref mismatch")
    require(organization_ref == prospect_id, "organization reference mismatch")

    approval_basis = "|".join((review_id, reviewer_ref, decided_at, approval["decision"], approval["scope"]))
    approval_id = "HAPR-" + hashlib.sha256(approval_basis.encode()).hexdigest()[:24]
    request_basis = "|".join((approval_id, lane, stage, source_ref, organization_ref, opportunity_id, service_id))
    request_id = "PING-" + hashlib.sha256(request_basis.encode()).hexdigest()[:24]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "request_id": request_id,
        "record_state": contract["output"]["record_state"],
        "source_review_id": review_id,
        "source_evaluation_id": evaluation_id,
        "prospect_id": prospect_id,
        "selected_opportunity_id": opportunity_id,
        "selected_service_id": service_id,
        "match_semantics": review.get("match_semantics"),
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "requested_pipeline_entry": {"lane": lane, "stage": stage, "source_ref": source_ref,
                                     "organization_key_ref": organization_ref},
        "approval_receipt": {"approval_id": approval_id, "decision": approval["decision"],
                             "decision_source": "HUMAN", "scope": approval["scope"],
                             "reviewer_ref": reviewer_ref, "decided_at": decided_at},
        "human_approval_recorded": True,
        "persistence_executed": False,
        "requires_separate_persistence_step": True,
        "pipeline_write_enabled": False,
        "crm_write_enabled": False,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--decision", required=True)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--pipeline-contract", default=str(DEFAULT_PIPELINE_CONTRACT))
    args = parser.parse_args()
    result = build_pipeline_ingest_request(
        load_json(Path(args.input)), load_json(Path(args.decision)),
        load_json(Path(args.contract)), load_json(Path(args.pipeline_contract)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
