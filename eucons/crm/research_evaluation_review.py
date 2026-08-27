#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "crm" / "research_evaluation_review_contract.json"
DEFAULT_PIPELINE_CONTRACT = EUCONS / "crm" / "pipeline_contract.json"

FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name",
    "personal_email",
    "personal_phone",
    "home_address",
    "personal_social_profile",
    "personal_identifier",
    "date_of_birth",
    "private_contact",
    "contact_name",
    "email",
    "phone",
    "cnp",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _iter_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _iter_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_keys(child)


def _safe_id(value: Any, field: str) -> str:
    _require(isinstance(value, str) and 0 < len(value.strip()) <= 240, f"invalid {field}")
    normalized = value.strip()
    _require("@" not in normalized and "\n" not in normalized and "\r" not in normalized, f"unsafe {field}")
    return normalized


def validate_contract(contract: dict[str, Any]) -> None:
    _require(contract.get("id") == "EUCONS-E11-R10-COMMERCIAL-REVIEW-001", "commercial review contract id drift")
    _require(contract.get("status") == "CANONICAL", "commercial review contract is not canonical")
    _require(contract.get("source_evaluation_contract") == "EUCONS-E11-R07-EVALUATION-HANDOFF-001", "source evaluation contract drift")
    _require(
        contract.get("source_match_semantics") == "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "source semantics failed open",
    )
    _require(contract.get("required_source_state") == "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW", "source state drift")
    _require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "eligibility boundary drift")
    _require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "research boundary drift")
    _require(contract.get("pipeline_contract_id") == "R10-PIPELINE-001", "pipeline contract drift")
    _require(contract.get("pipeline_engine_id") == "EUCONS_R10_UNIFIED_COMMERCIAL_PIPELINE", "pipeline engine drift")
    _require(contract.get("proposed_entry_lane") == "PROSPECT_DISCOVERY", "pipeline entry lane drift")
    _require(contract.get("proposed_entry_stage") == "PROSPECT", "pipeline entry stage drift")

    output = contract.get("output") or {}
    _require(output.get("record_state") == "COMMERCIAL_PIPELINE_REVIEW_PENDING_HUMAN_DECISION", "commercial review state drift")
    _require(output.get("human_review_required") is True, "human review boundary failed open")
    for field in (
        "pipeline_write_enabled",
        "crm_write_enabled",
        "external_contact_enabled",
        "automatic_offer_enabled",
        "automatic_send_enabled",
    ):
        _require(output.get(field) is False, f"{field} must remain disabled")

    rules = contract.get("rules") or {}
    for field in (
        "selected_opportunity_required",
        "selected_service_required",
        "source_human_review_must_still_be_required",
        "source_external_actions_must_be_disabled",
        "source_crm_write_must_be_disabled",
        "pipeline_production_persistence_must_be_disabled",
        "pipeline_contact_actions_must_be_disabled",
        "pipeline_offer_actions_must_be_disabled",
        "person_level_fields_forbidden",
        "never_claim_eligibility_award_probability_or_buying_intent",
    ):
        _require(rules.get(field) is True, f"missing fail-closed rule: {field}")


def validate_pipeline_boundary(pipeline_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    _require(pipeline_contract.get("id") == contract["pipeline_contract_id"], "unexpected pipeline contract")
    _require(pipeline_contract.get("engine_id") == contract["pipeline_engine_id"], "unexpected pipeline engine")
    _require(pipeline_contract.get("production_persistence_enabled") is False, "pipeline production persistence failed open")
    entry_lane = contract["proposed_entry_lane"]
    _require(entry_lane in (pipeline_contract.get("entry_lanes") or []), "proposed pipeline lane is unavailable")
    _require(
        (pipeline_contract.get("entry_stage_by_lane") or {}).get(entry_lane) == contract["proposed_entry_stage"],
        "proposed pipeline entry stage drift",
    )

    contact = pipeline_contract.get("contact_gate") or {}
    _require(contact.get("automatic_approval") is False, "pipeline automatic contact approval failed open")
    _require(contact.get("automatic_send") is False, "pipeline automatic send failed open")
    commercial = pipeline_contract.get("commercial_gate") or {}
    _require(commercial.get("automatic_offer") is False, "pipeline automatic offer failed open")
    _require(commercial.get("binding_price_generation") is False, "pipeline binding price generation failed open")
    outputs = pipeline_contract.get("outputs") or {}
    _require(outputs.get("eligibility_state") == "NOT_ASSESSED", "pipeline eligibility boundary drift")
    for field in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled"):
        _require(outputs.get(field) is False, f"pipeline {field} failed open")
    privacy = pipeline_contract.get("privacy") or {}
    _require(privacy.get("pipeline_stores_raw_contact_data") is False, "pipeline raw contact storage failed open")
    _require(privacy.get("pipeline_stores_only_contact_reference") is True, "pipeline contact-reference boundary drift")


def build_commercial_review(
    evaluation: dict[str, Any],
    contract: dict[str, Any],
    pipeline_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_contract(contract)
    validate_pipeline_boundary(pipeline_contract, contract)
    _require(isinstance(evaluation, dict), "evaluation must be an object")
    if FORBIDDEN_PERSON_LEVEL_KEYS & set(_iter_keys(evaluation)):
        raise ValueError("person-level field entered commercial pipeline review")

    _require(evaluation.get("contract_id") == contract["source_evaluation_contract"], "source evaluation contract mismatch")
    _require(evaluation.get("record_state") == contract["required_source_state"], "evaluation is not commercial-review ready")
    _require(evaluation.get("match_semantics") == contract["source_match_semantics"], "evaluation semantics drift")
    _require(evaluation.get("eligibility_state") == contract["required_eligibility_state"], "eligibility was assessed before review")
    _require(evaluation.get("maximum_next_state") == contract["required_maximum_next_state"], "evaluation crossed research boundary")
    _require(evaluation.get("human_review_required") is True, "source human review requirement disappeared")
    _require(evaluation.get("external_contact_enabled") is False, "source enabled external contact")
    _require(evaluation.get("automatic_offer_enabled") is False, "source enabled automatic offer")
    _require(evaluation.get("crm_write_enabled") is False, "source enabled CRM write")

    evaluation_id = _safe_id(evaluation.get("evaluation_id"), "evaluation_id")
    prospect_id = _safe_id(evaluation.get("prospect_id"), "prospect_id")
    opportunity_id = _safe_id(evaluation.get("selected_opportunity_id"), "selected_opportunity_id")
    service_id = _safe_id(evaluation.get("selected_service_id"), "selected_service_id")

    basis = "|".join((evaluation_id, prospect_id, opportunity_id, service_id))
    review_id = "CMREV-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "review_id": review_id,
        "record_state": output["record_state"],
        "source_evaluation_id": evaluation_id,
        "prospect_id": prospect_id,
        "selected_opportunity_id": opportunity_id,
        "selected_service_id": service_id,
        "match_semantics": contract["source_match_semantics"],
        "eligibility_state": contract["required_eligibility_state"],
        "maximum_next_state": contract["required_maximum_next_state"],
        "source_provenance": evaluation.get("source_provenance") or {},
        "proposed_pipeline_entry": {
            "lane": contract["proposed_entry_lane"],
            "stage": contract["proposed_entry_stage"],
            "source_ref": evaluation_id,
            "organization_key_ref": prospect_id,
        },
        "decision_required": "HUMAN_COMMERCIAL_PIPELINE_ENTRY_REVIEW",
        "human_review_required": True,
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
    result = build_commercial_review(
        load_json(Path(args.input)),
        load_json(Path(args.contract)),
        load_json(Path(args.pipeline_contract)),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
