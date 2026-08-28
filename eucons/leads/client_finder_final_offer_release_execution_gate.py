#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_gate_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_authorization_contract.json"

RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)
FALSE_BOUNDARY_FIELDS = (
    "public_offer_content_included",
    "final_offer_generated",
    "offer_approval_granted",
    "final_offer_approval_granted",
    "final_offer_release_authorization_granted",
    "release_executed",
    "release_package_generated",
    "release_package_approved",
    "pricing_included",
    "new_legal_claims_included",
    "new_financial_claims_included",
    "target_state_committed",
    "persistence_executed",
    "candidate_persistence_allowed",
    "draft_persistence_allowed",
    "offer_persistence_allowed",
    "production_offer_generation_allowed",
    "final_offer_generation_allowed",
    "offer_engine_invocation_allowed",
    "pricing_decision_allowed",
    "crm_context_materialization_allowed",
)
FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone", "home_address",
    "personal_social_profile", "personal_identifier", "date_of_birth", "private_contact",
    "contact_name", "email", "phone", "cnp", "reviewer_name", "reviewer_email", "reviewer_phone",
}
FORBIDDEN_PAYLOAD_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability", "buying_intent",
    "purchase_intent", "legal_conclusion", "financial_conclusion", "price", "amount_minor",
    "pricing_rule", "discount", "fee", "quote", "payment_terms", "terms", "offer_id",
    "proposal_id", "crm_state", "pipeline_state", "lead_id", "message_body", "email_body",
    "proposal_body", "offer_body", "proposal_text", "offer_text", "subject", "headline", "cta",
    "freeform_content", "material_claim", "claim_text", "edit_text", "final_offer",
    "final_offer_body", "final_offer_text", "attachment", "recipient", "channel", "send_to",
    "release_channel", "publication_target", "destination", "provider_message_id",
}
SOURCE_AUTHORIZATION_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_execution_authorization_id", "record_state",
    "source_release_package_review_contract_id", "source_final_offer_release_package_review_id",
    "source_final_offer_release_package_preparation_id", "source_final_offer_release_authorization_id",
    "source_final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id", "organization_key", "prospect_id",
    "selected_opportunity_id", "selected_service_id", "commercial_scope_area", "official_source_reverified",
    "official_source_verification_ref", "source_as_of", "release_execution_authorization_outcome",
    "release_execution_authorization_state", "authorization_scope", "next_gate_hint", "next_gate_authorized",
    "authorization_semantics", "decision_receipt", "eligibility_state", "maximum_next_state", "source_bound",
    "human_review_required", "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "release_package_approved", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed", "offer_engine_invocation_allowed",
    "pricing_decision_allowed", "crm_context_materialization_allowed", "external_contact_enabled",
    "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def recursive_keys(value: Any):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from recursive_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from recursive_keys(child)


def safe_ref(value: Any, field: str) -> str:
    require(isinstance(value, str) and 0 < len(value.strip()) <= 240, f"invalid {field}")
    normalized = value.strip()
    require("@" not in normalized and "\n" not in normalized and "\r" not in normalized, f"unsafe {field}")
    return normalized


def assert_safe_payload(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    forbidden = FORBIDDEN_PAYLOAD_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "release-execution gate schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-GATE-001",
        "release-execution gate contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "release-execution gate contract is not canonical")
    require(contract.get("source_authorization") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-AUTHORIZATION-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_AUTHORIZATION_ENVELOPE",
        "required_authorization_outcome": "RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY",
        "required_authorization_state": "FINAL_OFFER_RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY",
        "required_authorization_scope": "NEXT_GATE_ONLY",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_GATE_REQUIRED",
        "required_next_gate_authorized": True,
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_final_offer_release_authorization_granted": False,
        "required_release_executed": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source execution-authorization policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "release-execution gate boundary drift")
    require(contract.get("execution_preparation") == {
        "mode": "DETERMINISTIC_INTERNAL_RELEASE_COMMAND_ONLY",
        "command_type": "INTERNAL_RELEASE_EXECUTION_REVIEW_ENVELOPE_ONLY",
        "external_action": "NO_EXTERNAL_ACTION",
        "release_action": "NOT_EXECUTED",
        "send_action": "NOT_EXECUTED",
        "publication_action": "NOT_EXECUTED",
        "prepared_state": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_PREPARED_REVIEW_REQUIRED",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_REVIEW_GATE_REQUIRED",
    }, "release-execution preparation policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_PREPARATION_ENVELOPE", "release-execution output-state drift")
    require(output.get("source_bound") is True, "release-execution source binding failed open")
    require(output.get("human_review_required") is True, "release-execution human review failed open")
    require(output.get("internal_execution_envelope_prepared") is True, "internal execution envelope preparation disabled")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-execution safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_authorization"]
    require(source_contract.get("id") == source["contract_id"], "source execution-authorization contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source execution-authorization contract is not canonical")
    policy = source_contract.get("authorization") or {}
    outcome = source["required_authorization_outcome"]
    require(outcome in policy.get("allowed_authorization_outcomes", []), "source execution-authorization outcome no longer allowed")
    require(policy.get("outcome_state_map", {}).get(outcome) == source["required_authorization_state"], "source execution-authorization state policy drift")
    require(policy.get("authorization_scope") == source["required_authorization_scope"], "source execution-authorization scope policy drift")
    require(policy.get("outcome_next_gate_map", {}).get(outcome) == source["required_next_gate_hint"], "source execution-authorization next-gate policy drift")
    require(policy.get("outcome_next_gate_authorization_map", {}).get(outcome) is source["required_next_gate_authorized"], "source next-gate authorization policy drift")
    output = source_contract.get("output") or {}
    require(output.get("record_state") == source["record_state"], "source execution-authorization output-state drift")
    require(output.get("source_bound") is True, "source execution-authorization source binding failed open")
    require(output.get("human_review_required") is True, "source execution-authorization human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"source execution-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source execution-authorization {flag} failed open")


def validate_source_authorization(authorization: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(authorization, dict), "release-execution authorization envelope must be an object")
    assert_safe_payload(authorization, "source release-execution authorization envelope")
    require(set(authorization) == SOURCE_AUTHORIZATION_FIELDS, "source release-execution authorization envelope fields drift")
    source = contract["source_authorization"]
    boundaries = contract["required_boundaries"]
    require(authorization.get("schema_version") == 1, "source execution-authorization schema drift")
    require(authorization.get("contract_id") == source["contract_id"], "source execution-authorization contract id mismatch")
    require(authorization.get("record_state") == source["record_state"], "source execution-authorization record state mismatch")
    require(authorization.get("release_execution_authorization_outcome") == source["required_authorization_outcome"], "source execution gate was not positively authorized")
    require(authorization.get("release_execution_authorization_state") == source["required_authorization_state"], "source execution-authorization state mismatch")
    require(authorization.get("authorization_scope") == source["required_authorization_scope"], "source execution-authorization scope mismatch")
    require(authorization.get("next_gate_hint") == source["required_next_gate_hint"], "source execution gate hint mismatch")
    require(authorization.get("next_gate_authorized") is source["required_next_gate_authorized"], "source execution gate was not authorized")
    require(authorization.get("official_source_reverified") is source["required_official_source_reverified"], "source official source not reverified")
    require(authorization.get("source_bound") is source["required_source_bound"], "source execution authorization is not source-bound")
    require(authorization.get("release_package_generated") is source["required_release_package_generated"], "source release-package generation boundary drift")
    require(authorization.get("release_package_approved") is source["required_release_package_approved"], "source release-package approval boundary drift")
    require(authorization.get("final_offer_release_authorization_granted") is source["required_final_offer_release_authorization_granted"], "source final release authority boundary drift")
    require(authorization.get("release_executed") is source["required_release_executed"], "source release execution boundary drift")
    require(authorization.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(
        authorization.get("authorization_semantics") == "NEXT_GATE_ENTRY_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "source execution-authorization semantics drift",
    )
    require(authorization.get("eligibility_state") == boundaries["eligibility_state"], "source execution-authorization eligibility drift")
    require(authorization.get("maximum_next_state") == boundaries["maximum_next_state"], "source execution-authorization research boundary drift")
    require(authorization.get("human_review_required") is True, "source execution-authorization human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(authorization.get(field) is False, f"source execution-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(authorization.get(flag) is False, f"source execution-authorization {flag} failed open")

    receipt = authorization.get("decision_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source execution-authorization decision receipt fields drift")
    require(receipt.get("decision_source") == "HUMAN", "source execution-authorization decision is not human")
    reviewer_ref = safe_ref(receipt.get("reviewer_ref"), "source execution-authorization reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "source execution-authorization decided_at must be RFC3339 UTC-Z")

    authorization_id = safe_ref(authorization.get("final_offer_release_execution_authorization_id"), "final_offer_release_execution_authorization_id")
    lineage_fields = (
        "source_final_offer_release_package_review_id",
        "source_final_offer_release_package_preparation_id",
        "source_final_offer_release_authorization_id",
        "source_final_offer_release_readiness_id",
        "source_final_offer_candidate_review_id",
        "source_internal_final_offer_candidate_id",
        "source_offer_finalization_readiness_id",
        "source_offer_content_review_id",
        "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(authorization.get(field), field) for field in lineage_fields)
    identity = tuple(safe_ref(authorization.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    verification_ref = safe_ref(authorization.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = authorization.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source execution-authorization source_as_of must be RFC3339 UTC-Z")
    return authorization_id, lineage, identity, authorization["commercial_scope_area"], verification_ref, source_as_of, reviewer_ref, decided_at


def build_final_offer_release_execution_gate(
    authorization: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    authorization_id, lineage, identity, scope, verification_ref, source_as_of, reviewer_ref, decided_at = validate_source_authorization(authorization, contract)

    org, prospect, opportunity, service = identity
    basis = "|".join((authorization_id, *lineage, org, prospect, opportunity, service, scope, verification_ref, source_as_of, reviewer_ref, decided_at))
    preparation_id = "OFFRELEXECPREP-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    policy = contract["execution_preparation"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_execution_preparation_id": preparation_id,
        "record_state": contract["output"]["record_state"],
        "source_execution_authorization_contract_id": contract["source_authorization"]["contract_id"],
        "source_final_offer_release_execution_authorization_id": authorization_id,
        "source_final_offer_release_package_review_id": lineage[0],
        "source_final_offer_release_package_preparation_id": lineage[1],
        "source_final_offer_release_authorization_id": lineage[2],
        "source_final_offer_release_readiness_id": lineage[3],
        "source_final_offer_candidate_review_id": lineage[4],
        "source_internal_final_offer_candidate_id": lineage[5],
        "source_offer_finalization_readiness_id": lineage[6],
        "source_offer_content_review_id": lineage[7],
        "source_internal_offer_draft_id": lineage[8],
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": scope,
        "official_source_reverified": True,
        "official_source_verification_ref": verification_ref,
        "source_as_of": source_as_of,
        "execution_preparation_mode": policy["mode"],
        "execution_command": {
            "command_type": policy["command_type"],
            "external_action": policy["external_action"],
            "release_action": policy["release_action"],
            "send_action": policy["send_action"],
            "publication_action": policy["publication_action"],
        },
        "execution_preparation_state": policy["prepared_state"],
        "next_gate_hint": policy["next_gate_hint"],
        "execution_semantics": "INTERNAL_REVIEW_ENVELOPE_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "source_authorization_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "source_bound": True,
        "human_review_required": True,
        "internal_execution_envelope_prepared": True,
    }
    for field in FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in DISABLED_ACTION_FLAGS:
        result[flag] = False
    require(result["execution_command"]["external_action"] == "NO_EXTERNAL_ACTION", "release-execution gate prepared an external action")
    require(result["release_executed"] is False, "release-execution gate executed release")
    require(result["automatic_send_enabled"] is False, "release-execution gate enabled automatic send")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder deterministic internal final-offer release execution gate")
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_execution_gate(
        load_json(args.authorization),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
