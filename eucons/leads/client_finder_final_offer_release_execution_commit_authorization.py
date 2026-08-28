#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_commit_authorization_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_review_contract.json"

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
FORBIDDEN_AUTHORIZATION_PAYLOAD_KEYS = {
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
SOURCE_REVIEW_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_execution_review_id", "record_state",
    "source_execution_preparation_contract_id", "source_final_offer_release_execution_preparation_id",
    "source_final_offer_release_execution_authorization_id", "source_final_offer_release_package_review_id",
    "source_final_offer_release_package_preparation_id", "source_final_offer_release_authorization_id",
    "source_final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id",
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id",
    "commercial_scope_area", "official_source_reverified", "official_source_verification_ref",
    "source_as_of", "execution_review_outcome", "execution_review_state",
    "internal_execution_envelope_review_approved", "next_gate_hint",
    "release_execution_commit_authorization_gate_required", "execution_review_semantics",
    "decision_receipt", "eligibility_state", "maximum_next_state", "source_bound",
    "human_review_required",
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "release_package_approved", "pricing_included",
    "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
    "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
}
DECISION_FIELDS = {
    "source_final_offer_release_execution_review_id",
    "source_final_offer_release_execution_preparation_id",
    "source_final_offer_release_execution_authorization_id",
    "source_final_offer_release_package_review_id",
    "source_final_offer_release_package_preparation_id",
    "source_final_offer_release_authorization_id",
    "source_final_offer_release_readiness_id",
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
    "release_execution_commit_authorization_outcome",
    "authorization_scope",
    "decision_source",
    "reviewer_ref",
    "decided_at",
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
    require(contract.get("schema_version") == 1, "release-execution commit authorization schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-AUTHORIZATION-001",
        "release-execution commit authorization contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "release-execution commit authorization contract is not canonical")
    source = contract.get("source_review") or {}
    require(source == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-REVIEW-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_REVIEW_ENVELOPE",
        "required_execution_review_outcome": "APPROVED_INTERNAL_ONLY",
        "required_execution_review_state": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_APPROVED_INTERNAL_ONLY",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_GATE_REQUIRED",
        "required_internal_execution_envelope_review_approved": True,
        "required_release_execution_commit_authorization_gate_required": True,
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_final_offer_release_authorization_granted": False,
        "required_release_executed": False,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source release-execution review policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "release-execution commit authorization boundary drift")
    policy = contract.get("authorization") or {}
    outcomes = [
        "MORE_COMMIT_AUTHORIZATION_REVIEW_REQUIRED",
        "RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED",
        "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
    ]
    require(policy.get("decision_source") == "HUMAN", "release-execution commit authorization decision source failed open")
    require(policy.get("authorization_scope") == "NEXT_GATE_ONLY", "release-execution commit authorization scope drift")
    require(policy.get("allowed_authorization_outcomes") == outcomes, "release-execution commit authorization outcome allowlist drift")
    require(policy.get("outcome_state_map") == {
        "MORE_COMMIT_AUTHORIZATION_REVIEW_REQUIRED": "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_REVIEW_REQUIRED",
        "RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED": "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED",
        "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY": "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
    }, "release-execution commit authorization state map drift")
    require(policy.get("outcome_next_gate_map") == {
        "MORE_COMMIT_AUTHORIZATION_REVIEW_REQUIRED": None,
        "RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED": None,
        "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_GATE_REQUIRED",
    }, "release-execution commit authorization next-gate map drift")
    require(policy.get("outcome_next_gate_authorization_map") == {
        "MORE_COMMIT_AUTHORIZATION_REVIEW_REQUIRED": False,
        "RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED": False,
        "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY": True,
    }, "release-execution commit authorization next-gate authorization drift")
    require(policy.get("decided_at_format") == "RFC3339_UTC_Z", "release-execution commit authorization timestamp policy drift")
    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_ENVELOPE",
        "release-execution commit authorization output-state drift",
    )
    require(output.get("source_bound") is True, "release-execution commit authorization source binding failed open")
    require(output.get("human_review_required") is True, "release-execution commit authorization human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-execution commit authorization safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_review"]
    require(source_contract.get("id") == source["contract_id"], "source release-execution review contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source release-execution review contract is not canonical")
    review = source_contract.get("review") or {}
    outcome = source["required_execution_review_outcome"]
    require(outcome in review.get("allowed_execution_review_outcomes", []), "source execution-review outcome no longer allowed")
    require(
        review.get("outcome_state_map", {}).get(outcome) == source["required_execution_review_state"],
        "source execution-review state policy drift",
    )
    require(
        review.get("outcome_next_gate_map", {}).get(outcome) == source["required_next_gate_hint"],
        "source execution-review next-gate policy drift",
    )
    output = source_contract.get("output") or {}
    require(output.get("record_state") == source["record_state"], "source execution-review output-state drift")
    require(output.get("source_bound") is True, "source execution-review source binding failed open")
    require(output.get("human_review_required") is True, "source execution-review human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"source execution-review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source execution-review {flag} failed open")


def validate_source_review(review: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(review, dict), "release-execution review envelope must be an object")
    assert_safe_payload(review, "source release-execution review envelope")
    require(set(review) == SOURCE_REVIEW_FIELDS, "source release-execution review envelope fields drift")
    source = contract["source_review"]
    boundaries = contract["required_boundaries"]
    require(review.get("schema_version") == 1, "source execution-review schema drift")
    require(review.get("contract_id") == source["contract_id"], "source execution-review contract id mismatch")
    require(review.get("record_state") == source["record_state"], "source execution-review record state mismatch")
    require(review.get("execution_review_outcome") == source["required_execution_review_outcome"], "source execution review is not approved internal-only")
    require(review.get("execution_review_state") == source["required_execution_review_state"], "source execution-review state mismatch")
    require(review.get("next_gate_hint") == source["required_next_gate_hint"], "source commit-authorization gate hint mismatch")
    require(
        review.get("internal_execution_envelope_review_approved") is source["required_internal_execution_envelope_review_approved"],
        "source execution-envelope review approval boundary mismatch",
    )
    require(
        review.get("release_execution_commit_authorization_gate_required") is source["required_release_execution_commit_authorization_gate_required"],
        "source commit-authorization gate requirement mismatch",
    )
    require(review.get("official_source_reverified") is source["required_official_source_reverified"], "source official source not reverified")
    require(review.get("source_bound") is source["required_source_bound"], "source execution review is not source-bound")
    require(review.get("final_offer_release_authorization_granted") is source["required_final_offer_release_authorization_granted"], "source final release authority boundary drift")
    require(review.get("release_executed") is source["required_release_executed"], "source release execution boundary drift")
    require(review.get("release_package_generated") is source["required_release_package_generated"], "source release-package generation boundary drift")
    require(review.get("release_package_approved") is source["required_release_package_approved"], "source release-package approval boundary drift")
    require(review.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(
        review.get("execution_review_semantics") == "INTERNAL_RELEASE_EXECUTION_ENVELOPE_REVIEW_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "source execution-review semantics drift",
    )
    require(review.get("eligibility_state") == boundaries["eligibility_state"], "source execution-review eligibility drift")
    require(review.get("maximum_next_state") == boundaries["maximum_next_state"], "source execution-review research boundary drift")
    require(review.get("human_review_required") is True, "source execution-review human-review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(review.get(field) is False, f"source execution-review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(review.get(flag) is False, f"source execution-review {flag} failed open")

    receipt = review.get("decision_receipt")
    require(
        isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"},
        "source execution-review decision receipt fields drift",
    )
    require(receipt.get("decision_source") == "HUMAN", "source execution-review decision receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source execution-review reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "source execution-review decided_at must be RFC3339 UTC-Z",
    )

    review_id = safe_ref(review.get("final_offer_release_execution_review_id"), "final_offer_release_execution_review_id")
    preparation_id = safe_ref(
        review.get("source_final_offer_release_execution_preparation_id"),
        "source_final_offer_release_execution_preparation_id",
    )
    lineage_fields = (
        "source_final_offer_release_execution_authorization_id",
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
    lineage = tuple(safe_ref(review.get(field), field) for field in lineage_fields)
    identity = tuple(
        safe_ref(review.get(field), field)
        for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id")
    )
    verification_ref = safe_ref(review.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = review.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source execution-review source_as_of must be RFC3339 UTC-Z",
    )
    return review_id, preparation_id, lineage, identity, review["commercial_scope_area"], verification_ref, source_as_of


def validate_decision(decision: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(decision, dict), "release-execution commit authorization decision must be an object")
    assert_safe_payload(decision, "release-execution commit authorization decision")
    require(set(decision) == DECISION_FIELDS, "release-execution commit authorization decision fields drift")
    policy = contract["authorization"]
    require(decision.get("decision_source") == policy["decision_source"], "release-execution commit authorization decision source must be HUMAN")
    require(decision.get("authorization_scope") == policy["authorization_scope"], "release-execution commit authorization scope must be NEXT_GATE_ONLY")
    review_id = safe_ref(decision.get("source_final_offer_release_execution_review_id"), "source_final_offer_release_execution_review_id")
    preparation_id = safe_ref(
        decision.get("source_final_offer_release_execution_preparation_id"),
        "source_final_offer_release_execution_preparation_id",
    )
    lineage_fields = (
        "source_final_offer_release_execution_authorization_id",
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
    lineage = tuple(safe_ref(decision.get(field), field) for field in lineage_fields)
    identity = tuple(
        safe_ref(decision.get(field), field)
        for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id")
    )
    scope = decision.get("commercial_scope_area")
    require(scope == contract["source_review"]["required_commercial_scope_area"], "release-execution commit authorization commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "release-execution commit authorization source_as_of must be RFC3339 UTC-Z",
    )
    outcome = decision.get("release_execution_commit_authorization_outcome")
    require(outcome in policy["allowed_authorization_outcomes"], "release-execution commit authorization outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "release-execution commit authorization decided_at must be RFC3339 UTC-Z",
    )
    return review_id, preparation_id, lineage, identity, scope, verification_ref, source_as_of, outcome, reviewer_ref, decided_at


def build_final_offer_release_execution_commit_authorization(
    review: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_review_id, source_preparation_id, source_lineage, source_identity, source_scope, source_verification_ref, source_as_of = validate_source_review(review, contract)
    (
        decision_review_id, decision_preparation_id, decision_lineage, decision_identity, decision_scope,
        decision_verification_ref, decision_source_as_of, outcome, reviewer_ref, decided_at,
    ) = validate_decision(decision, contract)
    require(decision_review_id == source_review_id, "release-execution commit authorization source review id mismatch")
    require(decision_preparation_id == source_preparation_id, "release-execution commit authorization source preparation id mismatch")
    require(decision_lineage == source_lineage, "release-execution commit authorization lineage mismatch")
    require(decision_identity == source_identity, "release-execution commit authorization identity mismatch")
    require(decision_scope == source_scope, "release-execution commit authorization scope mismatch")
    require(decision_verification_ref == source_verification_ref, "release-execution commit authorization source verification mismatch")
    require(decision_source_as_of == source_as_of, "release-execution commit authorization source_as_of mismatch")

    policy = contract["authorization"]
    authorization_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    next_gate_authorized = policy["outcome_next_gate_authorization_map"][outcome]
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_review_id, source_preparation_id, *source_lineage, org, prospect, opportunity, service,
        source_scope, source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at,
    ))
    authorization_id = "OFFRELEXECCOMMITAUTH-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_execution_commit_authorization_id": authorization_id,
        "record_state": contract["output"]["record_state"],
        "source_execution_review_contract_id": contract["source_review"]["contract_id"],
        "source_final_offer_release_execution_review_id": source_review_id,
        "source_final_offer_release_execution_preparation_id": source_preparation_id,
        "source_final_offer_release_execution_authorization_id": source_lineage[0],
        "source_final_offer_release_package_review_id": source_lineage[1],
        "source_final_offer_release_package_preparation_id": source_lineage[2],
        "source_final_offer_release_authorization_id": source_lineage[3],
        "source_final_offer_release_readiness_id": source_lineage[4],
        "source_final_offer_candidate_review_id": source_lineage[5],
        "source_internal_final_offer_candidate_id": source_lineage[6],
        "source_offer_finalization_readiness_id": source_lineage[7],
        "source_offer_content_review_id": source_lineage[8],
        "source_internal_offer_draft_id": source_lineage[9],
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": source_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "release_execution_commit_authorization_outcome": outcome,
        "release_execution_commit_authorization_state": authorization_state,
        "authorization_scope": policy["authorization_scope"],
        "next_gate_hint": next_gate,
        "next_gate_authorized": next_gate_authorized,
        "authorization_semantics": "NEXT_INTERNAL_COMMIT_PREPARATION_GATE_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "source_bound": True,
        "human_review_required": True,
    }
    for field in FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in DISABLED_ACTION_FLAGS:
        result[flag] = False
    require(result["final_offer_release_authorization_granted"] is False, "commit authorization granted final release authority")
    require(result["release_executed"] is False, "commit authorization executed release")
    require(result["automatic_send_enabled"] is False, "commit authorization enabled send")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release execution commit-authorization gate")
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_execution_commit_authorization(
        load_json(args.review),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
