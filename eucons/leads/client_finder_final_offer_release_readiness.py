#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_readiness_contract.json"
DEFAULT_SOURCE_REVIEW_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_candidate_review_contract.json"

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
FORBIDDEN_READINESS_PAYLOAD_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "price", "amount_minor", "pricing_rule", "discount", "fee", "quote",
    "payment_terms", "terms", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body", "offer_body", "proposal_text", "offer_text",
    "subject", "headline", "cta", "freeform_content", "material_claim", "claim_text", "edit_text",
    "final_offer", "final_offer_body", "final_offer_text", "attachment", "recipient", "channel",
}
SOURCE_REVIEW_FIELDS = {
    "schema_version", "contract_id", "final_offer_candidate_review_id", "record_state",
    "source_candidate_contract_id", "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id", "source_offer_content_review_id",
    "source_internal_offer_draft_id", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "commercial_scope_area", "official_source_reverified",
    "official_source_verification_ref", "source_as_of", "candidate_review_outcome",
    "candidate_review_state", "internal_candidate_review_approved", "next_gate_hint",
    "final_offer_release_readiness_gate_required", "candidate_review_semantics", "decision_receipt",
    "eligibility_state", "maximum_next_state", "public_offer_content_included", "final_offer_generated",
    "offer_approval_granted", "final_offer_approval_granted", "final_offer_release_authorization_granted",
    "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "human_review_required", "external_contact_enabled", "automatic_offer_enabled",
    "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}
DECISION_FIELDS = {
    "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id",
    "source_offer_content_review_id",
    "source_internal_offer_draft_id",
    "organization_key",
    "prospect_id",
    "selected_opportunity_id",
    "selected_service_id",
    "commercial_scope_area",
    "official_source_verification_ref",
    "source_as_of",
    "release_readiness_outcome",
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


def assert_no_forbidden_readiness_payload(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    forbidden = FORBIDDEN_READINESS_PAYLOAD_KEYS & keys
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "final-offer release-readiness schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-READINESS-001",
        "final-offer release-readiness contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "final-offer release-readiness contract is not canonical")
    require(contract.get("source_review") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-CANDIDATE-REVIEW-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_CANDIDATE_REVIEW_ENVELOPE",
        "required_candidate_review_outcome": "APPROVED_INTERNAL_ONLY",
        "required_candidate_review_state": "INTERNAL_FINAL_OFFER_CANDIDATE_APPROVED_INTERNAL_ONLY",
        "required_internal_candidate_review_approved": True,
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_READINESS_GATE_REQUIRED",
        "required_release_readiness_gate_required": True,
        "required_official_source_reverified": True,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source candidate-review policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "final-offer release-readiness boundary drift")

    readiness = contract.get("readiness") or {}
    outcomes = ["MORE_RELEASE_REVIEW_REQUIRED", "RELEASE_NOT_READY", "RELEASE_READY_INTERNAL_ONLY"]
    require(readiness.get("decision_source") == "HUMAN", "release-readiness decision source failed open")
    require(readiness.get("authorization_scope") == "NEXT_GATE_ONLY", "release-readiness authorization scope drift")
    require(readiness.get("allowed_release_readiness_outcomes") == outcomes, "release-readiness outcome allowlist drift")
    require(readiness.get("outcome_state_map") == {
        "MORE_RELEASE_REVIEW_REQUIRED": "FINAL_OFFER_RELEASE_REVIEW_REQUIRED",
        "RELEASE_NOT_READY": "FINAL_OFFER_RELEASE_NOT_READY",
        "RELEASE_READY_INTERNAL_ONLY": "FINAL_OFFER_RELEASE_READY_INTERNAL_ONLY",
    }, "release-readiness state mapping drift")
    require(readiness.get("outcome_next_gate_map") == {
        "MORE_RELEASE_REVIEW_REQUIRED": None,
        "RELEASE_NOT_READY": None,
        "RELEASE_READY_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_AUTHORIZATION_GATE_REQUIRED",
    }, "release-readiness next-gate mapping drift")
    require(readiness.get("outcome_next_gate_authorization_map") == {
        "MORE_RELEASE_REVIEW_REQUIRED": False,
        "RELEASE_NOT_READY": False,
        "RELEASE_READY_INTERNAL_ONLY": True,
    }, "release-readiness next-gate authorization drift")
    require(readiness.get("decided_at_format") == "RFC3339_UTC_Z", "release-readiness timestamp policy drift")

    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_READINESS_ENVELOPE",
        "release-readiness output-state drift",
    )
    require(output.get("human_review_required") is True, "release-readiness human-review boundary failed open")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "candidate_persistence_allowed",
        "draft_persistence_allowed", "offer_persistence_allowed", "production_offer_generation_allowed",
        "final_offer_generation_allowed", "offer_engine_invocation_allowed", "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-readiness safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_review"]
    require(source_contract.get("id") == source["contract_id"], "source candidate-review contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source candidate-review contract is not canonical")
    review = source_contract.get("review") or {}
    require(
        source["required_candidate_review_outcome"] in review.get("allowed_candidate_review_outcomes", []),
        "source candidate-review outcome no longer allowed",
    )
    require(
        review.get("outcome_state_map", {}).get(source["required_candidate_review_outcome"])
        == source["required_candidate_review_state"],
        "source candidate-review state policy drift",
    )
    require(
        review.get("outcome_next_gate_map", {}).get(source["required_candidate_review_outcome"])
        == source["required_next_gate_hint"],
        "source candidate-review next-gate policy drift",
    )
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source candidate-review output-state drift")
    require(source_output.get("human_review_required") is True, "source candidate-review human-review failed open")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "final_offer_release_authorization_granted",
        "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "target_state_committed", "persistence_executed",
        "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(source_output.get(field) is False, f"source candidate-review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source candidate-review {flag} failed open")


def validate_source_review(
    review: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str, str], str, str, str, str]:
    require(isinstance(review, dict), "final-offer candidate review envelope must be an object")
    assert_no_person_level_fields(review, "source candidate review envelope")
    assert_no_forbidden_readiness_payload(review, "source candidate review envelope")
    require(set(review) == SOURCE_REVIEW_FIELDS, "source candidate review envelope fields drift")
    source = contract["source_review"]
    boundaries = contract["required_boundaries"]
    require(review.get("schema_version") == 1, "source candidate-review schema drift")
    require(review.get("contract_id") == source["contract_id"], "source candidate-review contract id mismatch")
    require(review.get("record_state") == source["record_state"], "source candidate-review record state mismatch")
    require(
        review.get("candidate_review_outcome") == source["required_candidate_review_outcome"],
        "source candidate-review is not approved internal-only",
    )
    require(
        review.get("candidate_review_state") == source["required_candidate_review_state"],
        "source candidate-review state mismatch",
    )
    require(
        review.get("internal_candidate_review_approved") is source["required_internal_candidate_review_approved"],
        "source candidate-review approval marker mismatch",
    )
    require(review.get("next_gate_hint") == source["required_next_gate_hint"], "source release-readiness gate hint mismatch")
    require(
        review.get("final_offer_release_readiness_gate_required") is source["required_release_readiness_gate_required"],
        "source release-readiness gate requirement missing",
    )
    require(
        review.get("official_source_reverified") is source["required_official_source_reverified"],
        "source candidate-review official source is not reverified",
    )
    require(
        review.get("commercial_scope_area") == source["required_commercial_scope_area"],
        "source candidate-review commercial scope drift",
    )
    require(
        review.get("candidate_review_semantics")
        == "INTERNAL_CANDIDATE_REVIEW_ONLY_NOT_FINAL_OFFER_OR_RELEASE_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "source candidate-review semantics drift",
    )
    require(review.get("eligibility_state") == boundaries["eligibility_state"], "source candidate-review eligibility drift")
    require(review.get("maximum_next_state") == boundaries["maximum_next_state"], "source candidate-review research boundary drift")
    require(review.get("human_review_required") is True, "source candidate-review human review failed open")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "final_offer_release_authorization_granted",
        "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "target_state_committed", "persistence_executed",
        "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(review.get(field) is False, f"source candidate-review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(review.get(flag) is False, f"source candidate-review {flag} failed open")
    receipt = review.get("decision_receipt")
    require(isinstance(receipt, dict), "source candidate-review decision receipt missing")
    require(set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source candidate-review receipt fields drift")
    require(receipt.get("decision_source") == "HUMAN", "source candidate-review decision receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source reviewer_ref")
    source_review_decided_at = receipt.get("decided_at")
    require(
        isinstance(source_review_decided_at, str) and RFC3339_UTC_Z.fullmatch(source_review_decided_at) is not None,
        "source candidate-review decided_at must be RFC3339 UTC-Z",
    )

    review_id = safe_ref(review.get("final_offer_candidate_review_id"), "final_offer_candidate_review_id")
    candidate_id = safe_ref(review.get("source_internal_final_offer_candidate_id"), "source_internal_final_offer_candidate_id")
    readiness_id = safe_ref(review.get("source_offer_finalization_readiness_id"), "source_offer_finalization_readiness_id")
    content_review_id = safe_ref(review.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(review.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    safe_ref(review.get("source_candidate_contract_id"), "source_candidate_contract_id")
    org = safe_ref(review.get("organization_key"), "organization_key")
    prospect = safe_ref(review.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(review.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(review.get("selected_service_id"), "selected_service_id")
    verification_ref = safe_ref(review.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = review.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source candidate-review source_as_of must be RFC3339 UTC-Z",
    )
    return (
        (org, prospect, opportunity, service),
        (review_id, candidate_id, readiness_id, content_review_id, draft_id),
        review["commercial_scope_area"],
        verification_ref,
        source_as_of,
        review_id,
    )


def validate_readiness_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str, str], str, str, str, str, str, str]:
    require(isinstance(decision, dict), "final-offer release-readiness decision must be an object")
    assert_no_person_level_fields(decision, "final-offer release-readiness decision")
    assert_no_forbidden_readiness_payload(decision, "final-offer release-readiness decision")
    require(set(decision) == DECISION_FIELDS, "final-offer release-readiness decision fields drift")
    policy = contract["readiness"]
    require(decision.get("decision_source") == policy["decision_source"], "release-readiness decision source must be HUMAN")
    review_id = safe_ref(decision.get("source_final_offer_candidate_review_id"), "source_final_offer_candidate_review_id")
    candidate_id = safe_ref(decision.get("source_internal_final_offer_candidate_id"), "source_internal_final_offer_candidate_id")
    readiness_id = safe_ref(decision.get("source_offer_finalization_readiness_id"), "source_offer_finalization_readiness_id")
    content_review_id = safe_ref(decision.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(decision.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    scope_area = decision.get("commercial_scope_area")
    require(scope_area == contract["source_review"]["required_commercial_scope_area"], "release-readiness commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "release-readiness source_as_of must be RFC3339 UTC-Z",
    )
    outcome = decision.get("release_readiness_outcome")
    require(outcome in policy["allowed_release_readiness_outcomes"], "release-readiness outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    return (
        (org, prospect, opportunity, service),
        (review_id, candidate_id, readiness_id, content_review_id, draft_id),
        scope_area,
        verification_ref,
        source_as_of,
        outcome,
        reviewer_ref,
        decided_at,
    )


def build_final_offer_release_readiness(
    source_review: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_REVIEW_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_lineage, source_scope, source_verification_ref, source_as_of, source_review_id = (
        validate_source_review(source_review, contract)
    )
    (
        decision_identity, decision_lineage, decision_scope, decision_verification_ref,
        decision_source_as_of, outcome, reviewer_ref, decided_at,
    ) = validate_readiness_decision(decision, contract)
    require(decision_identity == source_identity, "final-offer release-readiness identity mismatch")
    require(decision_lineage == source_lineage, "final-offer release-readiness lineage mismatch")
    require(decision_scope == source_scope, "final-offer release-readiness scope mismatch")
    require(
        decision_verification_ref == source_verification_ref,
        "final-offer release-readiness source verification mismatch",
    )
    require(decision_source_as_of == source_as_of, "final-offer release-readiness source_as_of mismatch")

    policy = contract["readiness"]
    readiness_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    next_gate_authorized = policy["outcome_next_gate_authorization_map"][outcome]
    org, prospect, opportunity, service = source_identity
    review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id = source_lineage
    basis = "|".join((
        source_review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id,
        org, prospect, opportunity, service, source_scope, source_verification_ref, source_as_of,
        outcome, reviewer_ref, decided_at,
    ))
    release_readiness_id = "OFFRELREADY-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_readiness_id": release_readiness_id,
        "record_state": contract["output"]["record_state"],
        "source_candidate_review_contract_id": contract["source_review"]["contract_id"],
        "source_final_offer_candidate_review_id": review_id,
        "source_internal_final_offer_candidate_id": candidate_id,
        "source_offer_finalization_readiness_id": finalization_readiness_id,
        "source_offer_content_review_id": content_review_id,
        "source_internal_offer_draft_id": draft_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": source_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "release_readiness_outcome": outcome,
        "release_readiness_state": readiness_state,
        "authorization_scope": policy["authorization_scope"],
        "next_gate_hint": next_gate,
        "next_gate_authorized": next_gate_authorized,
        "release_readiness_semantics": "INTERNAL_RELEASE_READINESS_ONLY_NOT_RELEASE_AUTHORIZATION_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_release_authorization_granted": False,
        "release_executed": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "candidate_persistence_allowed": False,
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
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "candidate_persistence_allowed",
        "draft_persistence_allowed", "offer_persistence_allowed", "production_offer_generation_allowed",
        "final_offer_generation_allowed", "offer_engine_invocation_allowed", "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"final-offer release-readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"final-offer release-readiness {flag} failed open")
    require(
        (next_gate is None and next_gate_authorized is False)
        or (
            next_gate == "SEPARATE_FINAL_OFFER_RELEASE_AUTHORIZATION_GATE_REQUIRED"
            and next_gate_authorized is True
            and outcome == "RELEASE_READY_INTERNAL_ONLY"
        ),
        "release-readiness next-gate authorization failed open",
    )
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release-readiness gate")
    parser.add_argument("--source-review", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_REVIEW_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_readiness(
        load_json(args.source_review),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
