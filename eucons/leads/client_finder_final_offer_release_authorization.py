#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_authorization_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_readiness_contract.json"

RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
DISABLED_ACTION_FLAGS = (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
)
FALSE_BOUNDARY_FIELDS = (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
)
SOURCE_FALSE_BOUNDARY_FIELDS = tuple(field for field in FALSE_BOUNDARY_FIELDS if field != "release_package_generated")
FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone", "home_address",
    "personal_social_profile", "personal_identifier", "date_of_birth", "private_contact",
    "contact_name", "email", "phone", "cnp", "reviewer_name", "reviewer_email", "reviewer_phone",
}
FORBIDDEN_AUTHORIZATION_PAYLOAD_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability", "buying_intent",
    "purchase_intent", "legal_conclusion", "financial_conclusion", "price", "amount_minor",
    "pricing_rule", "discount", "fee", "quote", "payment_terms", "terms", "offer_id",
    "proposal_id", "crm_state", "pipeline_state", "lead_id", "message_body", "email_body",
    "proposal_body", "offer_body", "proposal_text", "offer_text", "subject", "headline", "cta",
    "freeform_content", "material_claim", "claim_text", "edit_text", "final_offer",
    "final_offer_body", "final_offer_text", "attachment", "recipient", "channel",
}
SOURCE_READINESS_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_readiness_id", "record_state",
    "source_candidate_review_contract_id", "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id", "organization_key",
    "prospect_id", "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "release_readiness_outcome", "release_readiness_state", "authorization_scope", "next_gate_hint",
    "next_gate_authorized", "release_readiness_semantics", "decision_receipt", "eligibility_state",
    "maximum_next_state", "public_offer_content_included", "final_offer_generated",
    "offer_approval_granted", "final_offer_approval_granted", "final_offer_release_authorization_granted",
    "release_executed", "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "candidate_persistence_allowed",
    "draft_persistence_allowed", "offer_persistence_allowed", "production_offer_generation_allowed",
    "final_offer_generation_allowed", "offer_engine_invocation_allowed", "pricing_decision_allowed",
    "crm_context_materialization_allowed", "human_review_required", "external_contact_enabled",
    "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}
DECISION_FIELDS = {
    "source_final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id", "organization_key", "prospect_id",
    "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_verification_ref", "source_as_of", "release_authorization_outcome",
    "decision_source", "reviewer_ref", "decided_at",
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
    forbidden = FORBIDDEN_AUTHORIZATION_PAYLOAD_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "release-authorization schema drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-AUTHORIZATION-001", "release-authorization contract id drift")
    require(contract.get("status") == "CANONICAL", "release-authorization contract is not canonical")
    source = contract.get("source_readiness") or {}
    require(source == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-READINESS-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_READINESS_ENVELOPE",
        "required_release_readiness_outcome": "RELEASE_READY_INTERNAL_ONLY",
        "required_release_readiness_state": "FINAL_OFFER_RELEASE_READY_INTERNAL_ONLY",
        "required_authorization_scope": "NEXT_GATE_ONLY",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_AUTHORIZATION_GATE_REQUIRED",
        "required_next_gate_authorized": True,
        "required_official_source_reverified": True,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source release-readiness policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True, "external_contact_enabled": False,
        "automatic_offer_enabled": False, "automatic_send_enabled": False,
        "crm_write_enabled": False, "pipeline_write_enabled": False,
    }, "release-authorization boundary drift")
    policy = contract.get("authorization") or {}
    outcomes = ["MORE_AUTHORIZATION_REVIEW_REQUIRED", "RELEASE_PREPARATION_NOT_AUTHORIZED", "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY"]
    require(policy.get("decision_source") == "HUMAN", "release-authorization decision source failed open")
    require(policy.get("authorization_scope") == "NEXT_GATE_ONLY", "release-authorization scope drift")
    require(policy.get("allowed_authorization_outcomes") == outcomes, "release-authorization outcome allowlist drift")
    require(policy.get("outcome_state_map") == {
        "MORE_AUTHORIZATION_REVIEW_REQUIRED": "FINAL_OFFER_RELEASE_AUTHORIZATION_REVIEW_REQUIRED",
        "RELEASE_PREPARATION_NOT_AUTHORIZED": "FINAL_OFFER_RELEASE_PREPARATION_NOT_AUTHORIZED",
        "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY": "FINAL_OFFER_RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
    }, "release-authorization state map drift")
    require(policy.get("outcome_next_gate_map") == {
        "MORE_AUTHORIZATION_REVIEW_REQUIRED": None,
        "RELEASE_PREPARATION_NOT_AUTHORIZED": None,
        "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_GATE_REQUIRED",
    }, "release-authorization next-gate map drift")
    require(policy.get("outcome_next_gate_authorization_map") == {
        "MORE_AUTHORIZATION_REVIEW_REQUIRED": False,
        "RELEASE_PREPARATION_NOT_AUTHORIZED": False,
        "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY": True,
    }, "release-authorization next-gate authorization drift")
    require(policy.get("decided_at_format") == "RFC3339_UTC_Z", "release-authorization timestamp policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_AUTHORIZATION_ENVELOPE", "release-authorization output-state drift")
    require(output.get("human_review_required") is True, "release-authorization human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-authorization safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_readiness"]
    require(source_contract.get("id") == source["contract_id"], "source release-readiness contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source release-readiness contract is not canonical")
    readiness = source_contract.get("readiness") or {}
    outcome = source["required_release_readiness_outcome"]
    require(outcome in readiness.get("allowed_release_readiness_outcomes", []), "source release-readiness outcome no longer allowed")
    require(readiness.get("outcome_state_map", {}).get(outcome) == source["required_release_readiness_state"], "source release-readiness state policy drift")
    require(readiness.get("outcome_next_gate_map", {}).get(outcome) == source["required_next_gate_hint"], "source release-readiness next-gate policy drift")
    require(readiness.get("outcome_next_gate_authorization_map", {}).get(outcome) is True, "source release-readiness next-gate authorization drift")
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source release-readiness output-state drift")
    require(source_output.get("human_review_required") is True, "source release-readiness human-review failed open")
    for field in SOURCE_FALSE_BOUNDARY_FIELDS:
        require(source_output.get(field) is False, f"source release-readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source release-readiness {flag} failed open")


def validate_source_readiness(readiness: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(readiness, dict), "final-offer release-readiness envelope must be an object")
    assert_safe_payload(readiness, "source release-readiness envelope")
    require(set(readiness) == SOURCE_READINESS_FIELDS, "source release-readiness envelope fields drift")
    source = contract["source_readiness"]
    boundaries = contract["required_boundaries"]
    require(readiness.get("schema_version") == 1, "source release-readiness schema drift")
    require(readiness.get("contract_id") == source["contract_id"], "source release-readiness contract id mismatch")
    require(readiness.get("record_state") == source["record_state"], "source release-readiness record state mismatch")
    require(readiness.get("release_readiness_outcome") == source["required_release_readiness_outcome"], "source is not release ready internal-only")
    require(readiness.get("release_readiness_state") == source["required_release_readiness_state"], "source release-readiness state mismatch")
    require(readiness.get("authorization_scope") == source["required_authorization_scope"], "source authorization scope drift")
    require(readiness.get("next_gate_hint") == source["required_next_gate_hint"], "source authorization gate hint mismatch")
    require(readiness.get("next_gate_authorized") is source["required_next_gate_authorized"], "source authorization gate not authorized")
    require(readiness.get("official_source_reverified") is source["required_official_source_reverified"], "source official source not reverified")
    require(readiness.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(readiness.get("release_readiness_semantics") == "INTERNAL_RELEASE_READINESS_ONLY_NOT_RELEASE_AUTHORIZATION_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH", "source release-readiness semantics drift")
    require(readiness.get("eligibility_state") == boundaries["eligibility_state"], "source eligibility drift")
    require(readiness.get("maximum_next_state") == boundaries["maximum_next_state"], "source research boundary drift")
    require(readiness.get("human_review_required") is True, "source human review failed open")
    for field in SOURCE_FALSE_BOUNDARY_FIELDS:
        require(readiness.get(field) is False, f"source release-readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(readiness.get(flag) is False, f"source release-readiness {flag} failed open")
    receipt = readiness.get("decision_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source decision receipt fields drift")
    require(receipt.get("decision_source") == "HUMAN", "source decision receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "source decided_at must be RFC3339 UTC-Z")
    identity = tuple(safe_ref(readiness.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    lineage_fields = (
        "final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
        "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
        "source_offer_content_review_id", "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(readiness.get(field), field) for field in lineage_fields)
    verification_ref = safe_ref(readiness.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = readiness.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source_as_of must be RFC3339 UTC-Z")
    return identity, lineage, readiness["commercial_scope_area"], verification_ref, source_as_of


def validate_decision(decision: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(decision, dict), "release-authorization decision must be an object")
    assert_safe_payload(decision, "release-authorization decision")
    require(set(decision) == DECISION_FIELDS, "release-authorization decision fields drift")
    policy = contract["authorization"]
    require(decision.get("decision_source") == policy["decision_source"], "release-authorization decision source must be HUMAN")
    identity = tuple(safe_ref(decision.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    lineage_fields = (
        "source_final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
        "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
        "source_offer_content_review_id", "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(decision.get(field), field) for field in lineage_fields)
    scope = decision.get("commercial_scope_area")
    require(scope == contract["source_readiness"]["required_commercial_scope_area"], "release-authorization commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "release-authorization source_as_of must be RFC3339 UTC-Z")
    outcome = decision.get("release_authorization_outcome")
    require(outcome in policy["allowed_authorization_outcomes"], "release-authorization outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "decided_at must be RFC3339 UTC-Z")
    return identity, lineage, scope, verification_ref, source_as_of, outcome, reviewer_ref, decided_at


def build_final_offer_release_authorization(
    source_readiness: dict[str, Any], decision: dict[str, Any], contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_lineage, source_scope, source_verification_ref, source_as_of = validate_source_readiness(source_readiness, contract)
    decision_identity, decision_lineage, decision_scope, decision_verification_ref, decision_source_as_of, outcome, reviewer_ref, decided_at = validate_decision(decision, contract)
    require(decision_identity == source_identity, "release-authorization identity mismatch")
    require(decision_lineage == source_lineage, "release-authorization lineage mismatch")
    require(decision_scope == source_scope, "release-authorization scope mismatch")
    require(decision_verification_ref == source_verification_ref, "release-authorization source verification mismatch")
    require(decision_source_as_of == source_as_of, "release-authorization source_as_of mismatch")

    policy = contract["authorization"]
    state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    next_gate_authorized = policy["outcome_next_gate_authorization_map"][outcome]
    readiness_id, candidate_review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id = source_lineage
    org, prospect, opportunity, service = source_identity
    basis = "|".join((readiness_id, candidate_review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id, org, prospect, opportunity, service, source_scope, source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at))
    authorization_id = "OFFRELAUTH-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    result = {
        "schema_version": 1, "contract_id": contract["id"], "final_offer_release_authorization_id": authorization_id,
        "record_state": contract["output"]["record_state"], "source_release_readiness_contract_id": contract["source_readiness"]["contract_id"],
        "source_final_offer_release_readiness_id": readiness_id, "source_final_offer_candidate_review_id": candidate_review_id,
        "source_internal_final_offer_candidate_id": candidate_id, "source_offer_finalization_readiness_id": finalization_readiness_id,
        "source_offer_content_review_id": content_review_id, "source_internal_offer_draft_id": draft_id,
        "organization_key": org, "prospect_id": prospect, "selected_opportunity_id": opportunity, "selected_service_id": service,
        "commercial_scope_area": source_scope, "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref, "source_as_of": source_as_of,
        "release_authorization_outcome": outcome, "release_authorization_state": state,
        "authorization_scope": policy["authorization_scope"], "next_gate_hint": next_gate,
        "next_gate_authorized": next_gate_authorized,
        "release_authorization_semantics": "INTERNAL_NEXT_GATE_AUTHORIZATION_ONLY_NOT_FINAL_RELEASE_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {"decision_source": "HUMAN", "reviewer_ref": reviewer_ref, "decided_at": decided_at},
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "human_review_required": True,
    }
    for field in FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in DISABLED_ACTION_FLAGS:
        result[flag] = False
    require((next_gate is None and next_gate_authorized is False) or (next_gate == "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_GATE_REQUIRED" and next_gate_authorized is True and outcome == "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY"), "release-authorization next-gate authorization failed open")
    require(result["final_offer_release_authorization_granted"] is False and result["release_executed"] is False, "release-authorization external boundary failed open")
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release authorization gate")
    parser.add_argument("--source-readiness", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_authorization(load_json(args.source_readiness), load_json(args.decision), load_json(args.contract), load_json(args.source_contract))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
