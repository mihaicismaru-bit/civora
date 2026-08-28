#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_offer_finalization_readiness_contract.json"
DEFAULT_SOURCE_REVIEW_CONTRACT = EUCONS / "leads" / "client_finder_offer_content_review_contract.json"

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)
FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone", "home_address",
    "personal_social_profile", "personal_identifier", "date_of_birth", "private_contact",
    "contact_name", "email", "phone", "cnp", "reviewer_name", "reviewer_email", "reviewer_phone",
}
FORBIDDEN_FINALIZATION_PAYLOAD_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "price", "amount_minor", "pricing_rule", "discount", "fee", "quote",
    "payment_terms", "terms", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body", "offer_body", "proposal_text", "offer_text",
    "subject", "headline", "cta", "freeform_content", "material_claim", "claim_text", "edit_text",
    "draft_sections", "final_offer", "final_offer_body", "final_offer_text", "attachment",
}
SOURCE_REVIEW_FIELDS = {
    "schema_version", "contract_id", "offer_content_review_id", "record_state",
    "source_draft_contract_id", "source_internal_offer_draft_id", "organization_key", "prospect_id",
    "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "content_review_outcome", "content_review_state", "internal_content_review_approved",
    "next_gate_hint", "offer_finalization_gate_required", "content_review_semantics", "decision_receipt",
    "eligibility_state", "maximum_next_state", "offer_approval_granted", "draft_approval_granted",
    "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "human_review_required", "external_contact_enabled", "automatic_offer_enabled",
    "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}
DECISION_FIELDS = {
    "offer_content_review_id",
    "source_internal_offer_draft_id",
    "organization_key",
    "prospect_id",
    "selected_opportunity_id",
    "selected_service_id",
    "commercial_scope_area",
    "official_source_verification_ref",
    "source_as_of",
    "authorization_scope",
    "finalization_readiness_outcome",
    "decision_source",
    "reviewer_ref",
    "decided_at",
}
RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")


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


def assert_no_person_level_fields(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")


def assert_no_forbidden_finalization_payload(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    forbidden = FORBIDDEN_FINALIZATION_PAYLOAD_KEYS & keys
    require(not forbidden, f"forbidden material/finalization field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "offer finalization readiness schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-OFFER-FINALIZATION-READINESS-001",
        "offer finalization readiness contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "offer finalization readiness contract is not canonical")
    require(contract.get("source_review") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-CONTENT-REVIEW-001",
        "record_state": "CLIENT_FINDER_OFFER_CONTENT_REVIEW_ENVELOPE",
        "required_content_review_outcome": "APPROVED_INTERNAL_ONLY",
        "required_content_review_state": "INTERNAL_DRAFT_CONTENT_APPROVED_INTERNAL_ONLY",
        "required_internal_content_review_approved": True,
        "required_next_gate_hint": "SEPARATE_OFFER_FINALIZATION_GATE_REQUIRED",
        "required_offer_finalization_gate_required": True,
        "required_official_source_reverified": True,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source content review policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "offer finalization readiness boundary drift")

    readiness = contract.get("readiness") or {}
    outcomes = [
        "MORE_FINALIZATION_REVIEW_REQUIRED",
        "FINALIZATION_NOT_READY",
        "FINALIZATION_READY_INTERNAL_ONLY",
    ]
    require(readiness.get("decision_source") == "HUMAN", "finalization readiness decision source failed open")
    require(readiness.get("authorization_scope") == "NEXT_GATE_ONLY", "finalization authorization scope drift")
    require(
        readiness.get("allowed_finalization_readiness_outcomes") == outcomes,
        "finalization readiness outcome allowlist drift",
    )
    require(readiness.get("outcome_state_map") == {
        "MORE_FINALIZATION_REVIEW_REQUIRED": "FINALIZATION_REVIEW_REQUIRED",
        "FINALIZATION_NOT_READY": "FINALIZATION_NOT_READY",
        "FINALIZATION_READY_INTERNAL_ONLY": "FINALIZATION_READY_INTERNAL_ONLY",
    }, "finalization readiness state mapping drift")
    require(readiness.get("outcome_next_gate_map") == {
        "MORE_FINALIZATION_REVIEW_REQUIRED": None,
        "FINALIZATION_NOT_READY": None,
        "FINALIZATION_READY_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_GENERATION_GATE_REQUIRED",
    }, "finalization readiness next-gate mapping drift")
    require(readiness.get("outcome_next_gate_authorization_map") == {
        "MORE_FINALIZATION_REVIEW_REQUIRED": False,
        "FINALIZATION_NOT_READY": False,
        "FINALIZATION_READY_INTERNAL_ONLY": True,
    }, "finalization readiness authorization mapping drift")
    require(readiness.get("decided_at_format") == "RFC3339_UTC_Z", "finalization readiness timestamp policy drift")

    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_OFFER_FINALIZATION_READINESS_ENVELOPE",
        "finalization readiness output-state drift",
    )
    require(output.get("human_review_required") is True, "finalization readiness human-review boundary failed open")
    for field in (
        "offer_approval_granted", "final_offer_approval_granted",
        "final_offer_generation_authorization_granted", "content_mutation_allowed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"offer finalization readiness safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_review"]
    require(source_contract.get("id") == source["contract_id"], "source content review contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source content review contract is not canonical")
    source_review = source_contract.get("review") or {}
    require(
        source_review.get("outcome_state_map", {}).get(source["required_content_review_outcome"])
        == source["required_content_review_state"],
        "source content review outcome-state drift",
    )
    require(
        source_review.get("outcome_next_gate_map", {}).get(source["required_content_review_outcome"])
        == source["required_next_gate_hint"],
        "source content review next-gate drift",
    )
    source_draft = source_contract.get("source_draft") or {}
    require(source_draft.get("required_official_source_reverified") is True, "source review official-source prerequisite failed open")
    require(source_draft.get("required_source_bound") is True, "source review source-binding prerequisite failed open")
    output = source_contract.get("output") or {}
    require(output.get("record_state") == source["record_state"], "source content review output-state drift")
    require(output.get("human_review_required") is True, "source content review human-review boundary failed open")
    for field in (
        "offer_approval_granted", "draft_approval_granted", "pricing_included",
        "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
        "persistence_executed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"source content review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source content review {flag} failed open")


def validate_source_review(
    review: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str]:
    require(isinstance(review, dict), "offer content review envelope must be an object")
    assert_no_person_level_fields(review, "source content review envelope")
    assert_no_forbidden_finalization_payload(review, "source content review envelope")
    require(set(review) == SOURCE_REVIEW_FIELDS, "source content review envelope fields drift")
    source = contract["source_review"]
    boundaries = contract["required_boundaries"]
    require(review.get("schema_version") == 1, "source content review schema drift")
    require(review.get("contract_id") == source["contract_id"], "source content review contract id mismatch")
    require(review.get("record_state") == source["record_state"], "source content review record state mismatch")
    require(
        review.get("content_review_outcome") == source["required_content_review_outcome"],
        "source content review is not approved internal only",
    )
    require(
        review.get("content_review_state") == source["required_content_review_state"],
        "source content review state mismatch",
    )
    require(
        review.get("internal_content_review_approved") is source["required_internal_content_review_approved"],
        "source internal content review approval mismatch",
    )
    require(review.get("next_gate_hint") == source["required_next_gate_hint"], "source finalization gate hint mismatch")
    require(
        review.get("offer_finalization_gate_required") is source["required_offer_finalization_gate_required"],
        "source finalization gate requirement mismatch",
    )
    require(
        review.get("official_source_reverified") is source["required_official_source_reverified"],
        "source official source is not reverified",
    )
    require(
        review.get("commercial_scope_area") == source["required_commercial_scope_area"],
        "source commercial scope drift",
    )
    require(
        review.get("content_review_semantics")
        == "INTERNAL_CONTENT_REVIEW_ONLY_NOT_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "source content review semantics drift",
    )
    require(review.get("eligibility_state") == boundaries["eligibility_state"], "source content review eligibility drift")
    require(review.get("maximum_next_state") == boundaries["maximum_next_state"], "source content review research boundary drift")
    require(review.get("human_review_required") is True, "source content review human review failed closed")
    for field in (
        "offer_approval_granted", "draft_approval_granted", "pricing_included",
        "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
        "persistence_executed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(review.get(field) is False, f"source content review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(review.get(flag) is False, f"source content review {flag} failed open")

    receipt = review.get("decision_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source content review decision receipt drift")
    require(receipt.get("decision_source") == "HUMAN", "source content review receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source reviewer_ref")
    source_decided_at = receipt.get("decided_at")
    require(
        isinstance(source_decided_at, str) and RFC3339_UTC_Z.fullmatch(source_decided_at) is not None,
        "source content review decided_at must be RFC3339 UTC-Z",
    )

    review_id = safe_ref(review.get("offer_content_review_id"), "offer_content_review_id")
    draft_id = safe_ref(review.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    safe_ref(review.get("source_draft_contract_id"), "source_draft_contract_id")
    org = safe_ref(review.get("organization_key"), "organization_key")
    prospect = safe_ref(review.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(review.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(review.get("selected_service_id"), "selected_service_id")
    verification_ref = safe_ref(review.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = review.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source content review source_as_of must be RFC3339 UTC-Z",
    )
    return (org, prospect, opportunity, service), review_id, draft_id, verification_ref, source_as_of, source_decided_at


def validate_readiness_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str, str, str, str]:
    require(isinstance(decision, dict), "offer finalization readiness decision must be an object")
    assert_no_person_level_fields(decision, "offer finalization readiness decision")
    assert_no_forbidden_finalization_payload(decision, "offer finalization readiness decision")
    require(set(decision) == DECISION_FIELDS, "offer finalization readiness decision fields drift")
    policy = contract["readiness"]
    require(decision.get("decision_source") == policy["decision_source"], "finalization readiness decision source must be HUMAN")
    require(decision.get("authorization_scope") == policy["authorization_scope"], "finalization readiness authorization scope mismatch")
    review_id = safe_ref(decision.get("offer_content_review_id"), "offer_content_review_id")
    draft_id = safe_ref(decision.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    scope_area = decision.get("commercial_scope_area")
    require(scope_area == contract["source_review"]["required_commercial_scope_area"], "readiness decision commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "readiness decision source_as_of must be RFC3339 UTC-Z",
    )
    outcome = decision.get("finalization_readiness_outcome")
    require(outcome in policy["allowed_finalization_readiness_outcomes"], "finalization readiness outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    return (org, prospect, opportunity, service), review_id, draft_id, verification_ref, source_as_of, outcome, reviewer_ref, decided_at, scope_area


def build_offer_finalization_readiness(
    review: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_REVIEW_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_review_id, source_draft_id, source_verification_ref, source_as_of, _ = validate_source_review(
        review, contract
    )
    (
        decision_identity, decision_review_id, decision_draft_id, decision_verification_ref,
        decision_source_as_of, outcome, reviewer_ref, decided_at, decision_scope,
    ) = validate_readiness_decision(decision, contract)
    require(decision_identity == source_identity, "offer finalization readiness identity mismatch")
    require(decision_review_id == source_review_id, "offer finalization readiness content review id mismatch")
    require(decision_draft_id == source_draft_id, "offer finalization readiness draft id mismatch")
    require(decision_scope == review["commercial_scope_area"], "offer finalization readiness scope mismatch")
    require(decision_verification_ref == source_verification_ref, "offer finalization readiness source verification mismatch")
    require(decision_source_as_of == source_as_of, "offer finalization readiness source_as_of mismatch")

    policy = contract["readiness"]
    readiness_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    next_gate_authorized = policy["outcome_next_gate_authorization_map"][outcome]
    require(next_gate_authorized is (next_gate is not None), "next-gate authorization mapping is inconsistent")
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_review_id, source_draft_id, org, prospect, opportunity, service,
        decision_scope, source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at,
    ))
    readiness_id = "OFFFINAL-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "offer_finalization_readiness_id": readiness_id,
        "record_state": output["record_state"],
        "source_content_review_contract_id": contract["source_review"]["contract_id"],
        "source_offer_content_review_id": source_review_id,
        "source_internal_offer_draft_id": source_draft_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": decision_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "finalization_readiness_outcome": outcome,
        "finalization_readiness_state": readiness_state,
        "authorization_scope": policy["authorization_scope"],
        "next_gate_authorization_granted": next_gate_authorized,
        "next_gate_hint": next_gate,
        "final_offer_generation_gate_required": next_gate is not None,
        "finalization_semantics": "INTERNAL_NEXT_GATE_READINESS_ONLY_NOT_FINAL_OFFER_GENERATION_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_generation_authorization_granted": False,
        "content_mutation_allowed": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "draft_persistence_allowed": False,
        "offer_persistence_allowed": False,
        "production_offer_generation_allowed": False,
        "final_offer_generation_allowed": False,
        "offer_engine_invocation_allowed": False,
        "pricing_decision_allowed": False,
        "crm_context_materialization_allowed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    for field in (
        "offer_approval_granted", "final_offer_approval_granted",
        "final_offer_generation_authorization_granted", "content_mutation_allowed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"offer finalization readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"offer finalization readiness {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only offer-finalization readiness gate")
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_REVIEW_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_offer_finalization_readiness(
        load_json(args.review),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
