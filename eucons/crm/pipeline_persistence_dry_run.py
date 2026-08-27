#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "crm" / "pipeline_persistence_dry_run_contract.json"
DEFAULT_PIPELINE_CONTRACT = EUCONS / "crm" / "pipeline_contract.json"

FORBIDDEN_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone",
    "home_address", "private_contact", "contact_name", "email", "phone", "cnp",
    "reviewer_name", "reviewer_email", "reviewer_phone",
}
WRITE_FLAGS = (
    "pipeline_write_enabled",
    "crm_write_enabled",
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
)


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


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("id") == "EUCONS-E11-R10-PIPELINE-PERSISTENCE-DRY-RUN-001",
            "dry-run persistence contract id drift")
    require(contract.get("status") == "CANONICAL", "dry-run persistence contract is not canonical")
    require(contract.get("source_ingest_contract") == "EUCONS-E11-R10-PIPELINE-INGEST-REQUEST-001",
            "source ingest contract drift")
    require(contract.get("required_source_state") == "HUMAN_APPROVED_PIPELINE_INGEST_REQUEST",
            "source state drift")
    require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "eligibility boundary drift")
    require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "research boundary drift")
    require(contract.get("pipeline_contract_id") == "R10-PIPELINE-001", "pipeline contract drift")
    require(contract.get("pipeline_engine_id") == "EUCONS_R10_UNIFIED_COMMERCIAL_PIPELINE",
            "pipeline engine drift")
    require(contract.get("mode") == "DRY_RUN_NON_WRITING", "dry-run mode drift")
    require(contract.get("operations") == [
        "VALIDATE_TARGET_ENTRY",
        "PLAN_PIPELINE_RECORD_CREATE",
        "PLAN_APPEND_AUDIT_EVENT",
    ], "dry-run operation sequence drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "PIPELINE_PERSISTENCE_DRY_RUN_VALIDATED", "output state drift")
    require(output.get("execution_mode") == "DRY_RUN", "execution mode drift")
    require(output.get("persistence_executed") is False, "persistence failed open")
    require(output.get("real_pipeline_record_created") is False, "real record creation failed open")
    require(output.get("audit_event_written") is False, "audit event write failed open")
    require(output.get("requires_separate_persistence_step") is True, "separate persistence step missing")
    for field in WRITE_FLAGS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for field, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"rule failed open: {field}")


def validate_pipeline(pipeline: dict[str, Any], contract: dict[str, Any]) -> None:
    require(pipeline.get("id") == contract["pipeline_contract_id"], "unexpected pipeline contract")
    require(pipeline.get("engine_id") == contract["pipeline_engine_id"], "unexpected pipeline engine")
    require(pipeline.get("production_persistence_enabled") is False,
            "pipeline production persistence failed open")
    outputs = pipeline.get("outputs") or {}
    require(outputs.get("eligibility_state") == "NOT_ASSESSED", "pipeline eligibility drift")
    for field in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled"):
        require(outputs.get(field) is False, f"pipeline {field} failed open")
    require((pipeline.get("contact_gate") or {}).get("automatic_send") is False,
            "pipeline automatic send failed open")
    require((pipeline.get("commercial_gate") or {}).get("automatic_offer") is False,
            "pipeline automatic offer failed open")
    privacy = pipeline.get("privacy") or {}
    require(privacy.get("pipeline_stores_raw_contact_data") is False, "raw contact storage failed open")
    require(privacy.get("pipeline_stores_only_contact_reference") is True,
            "contact reference boundary drift")
    audit = pipeline.get("audit") or {}
    require(audit.get("append_only") is True, "pipeline audit is not append-only")
    require(audit.get("receipt_idempotency") is True, "pipeline audit idempotency disabled")
    require(set(audit.get("required_fields") or []) == {"sequence", "event_type", "record_id", "at", "details"},
            "pipeline audit required fields drift")


def build_dry_run_persistence_plan(ingest_request: dict[str, Any],
                                   contract: dict[str, Any],
                                   pipeline: dict[str, Any]) -> dict[str, Any]:
    validate_contract(contract)
    validate_pipeline(pipeline, contract)
    require(isinstance(ingest_request, dict), "ingest request must be an object")
    if FORBIDDEN_KEYS & set(keys(ingest_request)):
        raise ValueError("person-level field entered dry-run persistence plan")

    require(ingest_request.get("contract_id") == contract["source_ingest_contract"],
            "source ingest contract mismatch")
    require(ingest_request.get("record_state") == contract["required_source_state"],
            "ingest request is not dry-run ready")
    require(ingest_request.get("eligibility_state") == contract["required_eligibility_state"],
            "eligibility was assessed")
    require(ingest_request.get("maximum_next_state") == contract["required_maximum_next_state"],
            "research boundary crossed")
    require(ingest_request.get("human_approval_recorded") is True, "human approval missing")
    require(ingest_request.get("persistence_executed") is False, "source persistence already executed")
    require(ingest_request.get("requires_separate_persistence_step") is True,
            "source separate persistence step missing")
    for field in WRITE_FLAGS:
        require(ingest_request.get(field) is False, f"source {field} failed open")

    request_id = safe_ref(ingest_request.get("request_id"), "request_id")
    review_id = safe_ref(ingest_request.get("source_review_id"), "source_review_id")
    evaluation_id = safe_ref(ingest_request.get("source_evaluation_id"), "source_evaluation_id")
    prospect_id = safe_ref(ingest_request.get("prospect_id"), "prospect_id")
    opportunity_id = safe_ref(ingest_request.get("selected_opportunity_id"), "selected_opportunity_id")
    service_id = safe_ref(ingest_request.get("selected_service_id"), "selected_service_id")
    approval = ingest_request.get("approval_receipt") or {}
    approval_id = safe_ref(approval.get("approval_id"), "approval_id")
    require(approval.get("decision") == "APPROVE_PIPELINE_ENTRY", "approval decision drift")
    require(approval.get("decision_source") == "HUMAN", "approval source drift")
    require(approval.get("scope") == "NON_WRITING_INGEST_REQUEST_ONLY", "approval scope drift")

    entry = ingest_request.get("requested_pipeline_entry") or {}
    lane = safe_ref(entry.get("lane"), "pipeline lane")
    stage = safe_ref(entry.get("stage"), "pipeline stage")
    source_ref = safe_ref(entry.get("source_ref"), "pipeline source_ref")
    organization_ref = safe_ref(entry.get("organization_key_ref"), "organization_key_ref")
    require(lane in (pipeline.get("entry_lanes") or []), "pipeline lane unavailable")
    require((pipeline.get("entry_stage_by_lane") or {}).get(lane) == stage, "pipeline stage drift")
    require(source_ref == evaluation_id, "source_ref mismatch")
    require(organization_ref == prospect_id, "organization reference mismatch")

    basis = "|".join((
        request_id,
        approval_id,
        contract["pipeline_contract_id"],
        contract["pipeline_engine_id"],
        lane,
        stage,
        source_ref,
        organization_ref,
        opportunity_id,
        service_id,
    ))
    digest = hashlib.sha256(basis.encode()).hexdigest()
    plan_id = "PDRY-" + digest[:24]
    planned_record_id = "PREC-" + hashlib.sha256(("record|" + basis).encode()).hexdigest()[:24]
    planned_audit_event_id = "PAUD-" + hashlib.sha256(("audit|" + basis).encode()).hexdigest()[:24]
    receipt_id = "PDRC-" + hashlib.sha256(("receipt|" + basis).encode()).hexdigest()[:24]

    target = {
        "lane": lane,
        "stage": stage,
        "source_ref": source_ref,
        "organization_key_ref": organization_ref,
    }
    operations = [
        {"order": 1, "operation": "VALIDATE_TARGET_ENTRY", "would_write": False},
        {"order": 2, "operation": "PLAN_PIPELINE_RECORD_CREATE", "target_ref": planned_record_id,
         "would_write": False},
        {"order": 3, "operation": "PLAN_APPEND_AUDIT_EVENT", "target_ref": planned_audit_event_id,
         "would_write": False},
    ]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "plan_id": plan_id,
        "record_state": contract["output"]["record_state"],
        "execution_mode": "DRY_RUN",
        "source_request_id": request_id,
        "source_review_id": review_id,
        "source_evaluation_id": evaluation_id,
        "source_approval_id": approval_id,
        "prospect_id": prospect_id,
        "selected_opportunity_id": opportunity_id,
        "selected_service_id": service_id,
        "match_semantics": ingest_request.get("match_semantics"),
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "target_pipeline_entry": target,
        "planned_record_id": planned_record_id,
        "planned_audit_event": {
            "event_id": planned_audit_event_id,
            "event_type": "PIPELINE_ENTRY_PLANNED_DRY_RUN",
            "record_id": planned_record_id,
            "details_ref": request_id,
            "would_write": False,
            "runtime_fields_required_for_real_write": ["sequence", "at"],
        },
        "planned_operations": operations,
        "dry_run_receipt": {
            "receipt_id": receipt_id,
            "outcome": "VALIDATED_NON_WRITING",
            "source_request_id": request_id,
            "source_approval_id": approval_id,
            "idempotency_fingerprint": digest,
        },
        "production_persistence_enabled": False,
        "persistence_executed": False,
        "real_pipeline_record_created": False,
        "audit_event_written": False,
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
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT))
    parser.add_argument("--pipeline-contract", default=str(DEFAULT_PIPELINE_CONTRACT))
    args = parser.parse_args()
    result = build_dry_run_persistence_plan(
        load_json(Path(args.input)),
        load_json(Path(args.contract)),
        load_json(Path(args.pipeline_contract)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
