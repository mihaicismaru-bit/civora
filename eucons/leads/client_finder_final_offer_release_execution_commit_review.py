#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_commit_review_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_commit_preparation_contract.json"

RFC3339_UTC_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$")
DISABLED_ACTION_FLAGS = (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
)
FALSE_BOUNDARY_FIELDS = (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "release_package_approved", "pricing_included",
    "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
    "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
)
FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone", "home_address",
    "personal_social_profile", "personal_identifier", "date_of_birth", "private_contact",
    "contact_name", "email", "phone", "cnp", "reviewer_name", "reviewer_email", "reviewer_phone",
}
FORBIDDEN_REVIEW_PAYLOAD_KEYS = {
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
LINEAGE_FIELDS = (
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
)
SOURCE_PREPARATION_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_execution_commit_preparation_id", "record_state",
    "source_authorization_contract_id", "source_final_offer_release_execution_commit_authorization_id",
    *LINEAGE_FIELDS,
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "preparation_mode", "commit_intent", "commit_preparation_state", "next_gate_hint",
    "commit_preparation_semantics", "eligibility_state", "maximum_next_state", "source_bound",
    "human_review_required", "commit_intent_generated", *FALSE_BOUNDARY_FIELDS, *DISABLED_ACTION_FLAGS,
}
DECISION_FIELDS = {
    "final_offer_release_execution_commit_preparation_id",
    "source_final_offer_release_execution_commit_authorization_id",
    *LINEAGE_FIELDS,
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id",
    "commercial_scope_area", "official_source_verification_ref", "source_as_of",
    "commit_review_outcome", "decision_source", "reviewer_ref", "decided_at",
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


def assert_safe_input(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    forbidden = FORBIDDEN_REVIEW_PAYLOAD_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "commit-review schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-REVIEW-001",
        "commit-review contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "commit-review contract is not canonical")
    source = contract.get("source_preparation") or {}
    require(source == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-PREPARATION-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_ENVELOPE",
        "required_preparation_state": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_PREPARED_REVIEW_REQUIRED",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_GATE_REQUIRED",
        "required_preparation_mode": "DETERMINISTIC_INTERNAL_COMMIT_INTENT_ONLY",
        "required_commit_intent": {
            "command_type": "INTERNAL_RELEASE_EXECUTION_COMMIT_INTENT_REVIEW_ENVELOPE_ONLY",
            "external_action": "NO_EXTERNAL_ACTION",
            "release_action": "NOT_EXECUTED",
            "send_action": "NOT_EXECUTED",
            "publication_action": "NOT_EXECUTED",
            "persistence_action": "NOT_EXECUTED",
        },
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_commit_intent_generated": True,
        "required_final_offer_release_authorization_granted": False,
        "required_release_executed": False,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source commit-preparation policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True, "external_contact_enabled": False,
        "automatic_offer_enabled": False, "automatic_send_enabled": False,
        "crm_write_enabled": False, "pipeline_write_enabled": False,
    }, "commit-review boundary drift")
    review = contract.get("review") or {}
    outcomes = ["CHANGES_REQUIRED", "REJECTED", "APPROVED_INTERNAL_ONLY"]
    require(review.get("decision_source") == "HUMAN", "commit-review decision source failed open")
    require(review.get("allowed_commit_review_outcomes") == outcomes, "commit-review outcome allowlist drift")
    require(review.get("outcome_state_map") == {
        "CHANGES_REQUIRED": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_CHANGES_REQUIRED",
        "REJECTED": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_REJECTED",
        "APPROVED_INTERNAL_ONLY": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_APPROVED_INTERNAL_ONLY",
    }, "commit-review state mapping drift")
    require(review.get("outcome_next_gate_map") == {
        "CHANGES_REQUIRED": None,
        "REJECTED": None,
        "APPROVED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_FINAL_AUTHORIZATION_GATE_REQUIRED",
    }, "commit-review next-gate mapping drift")
    require(review.get("decided_at_format") == "RFC3339_UTC_Z", "commit-review timestamp policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_ENVELOPE", "commit-review output-state drift")
    require(output.get("source_bound") is True and output.get("human_review_required") is True, "commit-review source/human boundary failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"commit-review safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_preparation"]
    require(source_contract.get("id") == source["contract_id"], "source commit-preparation contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source commit-preparation contract is not canonical")
    preparation = source_contract.get("preparation") or {}
    require(preparation.get("allowed_preparation_modes") == [source["required_preparation_mode"]], "source preparation mode drift")
    require(preparation.get("commit_intent") == source["required_commit_intent"], "source commit-intent policy drift")
    require(preparation.get("prepared_state") == source["required_preparation_state"], "source preparation state drift")
    require(preparation.get("next_gate_hint") == source["required_next_gate_hint"], "source preparation next-gate drift")
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source commit-preparation output-state drift")
    require(source_output.get("source_bound") is True and source_output.get("human_review_required") is True, "source commit-preparation source/human boundary failed open")
    require(source_output.get("commit_intent_generated") is True, "source commit-intent generation disabled")
    for field in FALSE_BOUNDARY_FIELDS:
        require(source_output.get(field) is False, f"source commit-preparation {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source commit-preparation {flag} failed open")


def validate_source_preparation(value: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(value, dict), "source commit-preparation envelope must be an object")
    assert_safe_input(value, "source commit-preparation envelope")
    require(set(value) == SOURCE_PREPARATION_FIELDS, "source commit-preparation envelope fields drift")
    source = contract["source_preparation"]
    boundaries = contract["required_boundaries"]
    require(value.get("schema_version") == 1, "source commit-preparation schema drift")
    require(value.get("contract_id") == source["contract_id"], "source commit-preparation contract mismatch")
    require(value.get("record_state") == source["record_state"], "source commit-preparation record state mismatch")
    require(value.get("commit_preparation_state") == source["required_preparation_state"], "source commit-intent is not review-ready")
    require(value.get("next_gate_hint") == source["required_next_gate_hint"], "source commit-review gate hint mismatch")
    require(value.get("preparation_mode") == source["required_preparation_mode"], "source preparation mode mismatch")
    require(value.get("commit_intent") == source["required_commit_intent"], "source commit-intent command drift")
    require(value.get("official_source_reverified") is source["required_official_source_reverified"], "source official source is not reverified")
    require(value.get("source_bound") is source["required_source_bound"], "source commit-preparation is not source-bound")
    require(value.get("commit_intent_generated") is source["required_commit_intent_generated"], "source commit-intent missing")
    require(value.get("final_offer_release_authorization_granted") is False, "source final release authority boundary drift")
    require(value.get("release_executed") is False, "source release execution boundary drift")
    require(value.get("release_package_generated") is False, "source release package generation boundary drift")
    require(value.get("release_package_approved") is False, "source release package approval boundary drift")
    require(value.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(value.get("commit_preparation_semantics") == "DETERMINISTIC_INTERNAL_COMMIT_INTENT_FOR_HUMAN_REVIEW_ONLY_NO_EXTERNAL_ACTION_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH", "source commit-preparation semantics drift")
    require(value.get("eligibility_state") == boundaries["eligibility_state"], "source eligibility drift")
    require(value.get("maximum_next_state") == boundaries["maximum_next_state"], "source research boundary drift")
    require(value.get("human_review_required") is True, "source human-review boundary failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(value.get(field) is False, f"source commit-preparation {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(value.get(flag) is False, f"source commit-preparation {flag} failed open")
    preparation_id = safe_ref(value.get("final_offer_release_execution_commit_preparation_id"), "final_offer_release_execution_commit_preparation_id")
    authorization_id = safe_ref(value.get("source_final_offer_release_execution_commit_authorization_id"), "source_final_offer_release_execution_commit_authorization_id")
    lineage = tuple(safe_ref(value.get(field), field) for field in LINEAGE_FIELDS)
    identity = tuple(safe_ref(value.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    verification_ref = safe_ref(value.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = value.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source source_as_of must be RFC3339 UTC-Z")
    return preparation_id, authorization_id, lineage, identity, value["commercial_scope_area"], verification_ref, source_as_of


def validate_review_decision(value: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(value, dict), "commit-review decision must be an object")
    assert_safe_input(value, "commit-review decision")
    require(set(value) == DECISION_FIELDS, "commit-review decision fields drift")
    policy = contract["review"]
    require(value.get("decision_source") == policy["decision_source"], "commit-review decision source must be HUMAN")
    preparation_id = safe_ref(value.get("final_offer_release_execution_commit_preparation_id"), "final_offer_release_execution_commit_preparation_id")
    authorization_id = safe_ref(value.get("source_final_offer_release_execution_commit_authorization_id"), "source_final_offer_release_execution_commit_authorization_id")
    lineage = tuple(safe_ref(value.get(field), field) for field in LINEAGE_FIELDS)
    identity = tuple(safe_ref(value.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    scope = value.get("commercial_scope_area")
    require(scope == contract["source_preparation"]["required_commercial_scope_area"], "commit-review commercial scope drift")
    verification_ref = safe_ref(value.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = value.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "commit-review source_as_of must be RFC3339 UTC-Z")
    outcome = value.get("commit_review_outcome")
    require(outcome in policy["allowed_commit_review_outcomes"], "commit-review outcome escaped allowlist")
    reviewer_ref = safe_ref(value.get("reviewer_ref"), "reviewer_ref")
    decided_at = value.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "commit-review decided_at must be RFC3339 UTC-Z")
    return preparation_id, authorization_id, lineage, identity, scope, verification_ref, source_as_of, outcome, reviewer_ref, decided_at


def build_final_offer_release_execution_commit_review(
    preparation: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source = validate_source_preparation(preparation, contract)
    reviewed = validate_review_decision(decision, contract)
    require(reviewed[:7] == source, "commit-review source lineage/identity/source binding mismatch")
    preparation_id, authorization_id, lineage, identity, scope, verification_ref, source_as_of = source
    outcome, reviewer_ref, decided_at = reviewed[7:]
    org, prospect, opportunity, service = identity
    basis = "|".join((preparation_id, authorization_id, *lineage, org, prospect, opportunity, service, scope, verification_ref, source_as_of, outcome, reviewer_ref, decided_at))
    review_id = "OFFRELEXECCOMMITREVIEW-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    policy = contract["review"]
    review_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    approved = outcome == "APPROVED_INTERNAL_ONLY"
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_execution_commit_review_id": review_id,
        "record_state": contract["output"]["record_state"],
        "source_commit_preparation_contract_id": contract["source_preparation"]["contract_id"],
        "source_final_offer_release_execution_commit_preparation_id": preparation_id,
        "source_final_offer_release_execution_commit_authorization_id": authorization_id,
        **{field: preparation[field] for field in LINEAGE_FIELDS},
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": scope,
        "official_source_reverified": True,
        "official_source_verification_ref": verification_ref,
        "source_as_of": source_as_of,
        "commit_review_outcome": outcome,
        "commit_review_state": review_state,
        "commit_intent_review_approved": approved,
        "next_gate_hint": next_gate,
        "final_release_execution_authorization_gate_required": next_gate is not None,
        "commit_review_semantics": "INTERNAL_COMMIT_INTENT_REVIEW_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
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
    require(result["final_offer_release_authorization_granted"] is False, "commit-review release authority failed open")
    require(result["release_executed"] is False and result["persistence_executed"] is False, "commit-review executed an action")
    require(result["automatic_send_enabled"] is False, "commit-review enabled send")
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release-execution commit-review gate")
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_execution_commit_review(
        load_json(args.preparation), load_json(args.decision), load_json(args.contract), load_json(args.source_contract)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
