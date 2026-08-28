#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_review_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_gate_contract.json"

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
SOURCE_PREPARATION_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_execution_preparation_id", "record_state",
    "source_execution_authorization_contract_id", "source_final_offer_release_execution_authorization_id",
    "source_final_offer_release_package_review_id", "source_final_offer_release_package_preparation_id",
    "source_final_offer_release_authorization_id", "source_final_offer_release_readiness_id",
    "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id", "source_offer_content_review_id", "source_internal_offer_draft_id",
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "execution_preparation_mode", "execution_command", "execution_preparation_state", "next_gate_hint",
    "execution_semantics", "source_authorization_receipt", "eligibility_state", "maximum_next_state",
    "source_bound", "human_review_required", "internal_execution_envelope_prepared",
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
    "final_offer_release_execution_preparation_id",
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
    "execution_review_outcome",
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


def assert_safe_input(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    forbidden = FORBIDDEN_REVIEW_PAYLOAD_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "release-execution review schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-REVIEW-001",
        "release-execution review contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "release-execution review contract is not canonical")
    require(contract.get("source_preparation") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-GATE-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_PREPARATION_ENVELOPE",
        "required_execution_preparation_state": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_PREPARED_REVIEW_REQUIRED",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_REVIEW_GATE_REQUIRED",
        "required_preparation_mode": "DETERMINISTIC_INTERNAL_RELEASE_COMMAND_ONLY",
        "required_execution_command": {
            "command_type": "INTERNAL_RELEASE_EXECUTION_REVIEW_ENVELOPE_ONLY",
            "external_action": "NO_EXTERNAL_ACTION",
            "release_action": "NOT_EXECUTED",
            "send_action": "NOT_EXECUTED",
            "publication_action": "NOT_EXECUTED",
        },
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_internal_execution_envelope_prepared": True,
        "required_final_offer_release_authorization_granted": False,
        "required_release_executed": False,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source release-execution preparation policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "release-execution review boundary drift")
    review = contract.get("review") or {}
    outcomes = ["CHANGES_REQUIRED", "REJECTED", "APPROVED_INTERNAL_ONLY"]
    require(review.get("decision_source") == "HUMAN", "release-execution review decision source failed open")
    require(review.get("allowed_execution_review_outcomes") == outcomes, "release-execution review outcome allowlist drift")
    require(review.get("outcome_state_map") == {
        "CHANGES_REQUIRED": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_CHANGES_REQUIRED",
        "REJECTED": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_REJECTED",
        "APPROVED_INTERNAL_ONLY": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_APPROVED_INTERNAL_ONLY",
    }, "release-execution review state mapping drift")
    require(review.get("outcome_next_gate_map") == {
        "CHANGES_REQUIRED": None,
        "REJECTED": None,
        "APPROVED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_GATE_REQUIRED",
    }, "release-execution review next-gate mapping drift")
    require(review.get("decided_at_format") == "RFC3339_UTC_Z", "release-execution review timestamp policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_REVIEW_ENVELOPE", "release-execution review output-state drift")
    require(output.get("source_bound") is True, "release-execution review source binding failed open")
    require(output.get("human_review_required") is True, "release-execution review human-review boundary failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-execution review safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_preparation"]
    require(source_contract.get("id") == source["contract_id"], "source release-execution preparation contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source release-execution preparation contract is not canonical")
    preparation = source_contract.get("execution_preparation") or {}
    require(preparation.get("mode") == source["required_preparation_mode"], "source execution-preparation mode drift")
    require(preparation.get("prepared_state") == source["required_execution_preparation_state"], "source execution-preparation state drift")
    require(preparation.get("next_gate_hint") == source["required_next_gate_hint"], "source execution-preparation next-gate drift")
    require({
        "command_type": preparation.get("command_type"),
        "external_action": preparation.get("external_action"),
        "release_action": preparation.get("release_action"),
        "send_action": preparation.get("send_action"),
        "publication_action": preparation.get("publication_action"),
    } == source["required_execution_command"], "source deterministic execution command policy drift")
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source execution-preparation output-state drift")
    require(source_output.get("source_bound") is True, "source execution-preparation source binding failed open")
    require(source_output.get("human_review_required") is True, "source execution-preparation human review failed open")
    require(source_output.get("internal_execution_envelope_prepared") is True, "source execution envelope preparation disabled")
    for field in FALSE_BOUNDARY_FIELDS:
        require(source_output.get(field) is False, f"source execution-preparation {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source execution-preparation {flag} failed open")


def validate_source_preparation(
    preparation: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, str, str, str], str, str, str, str]:
    require(isinstance(preparation, dict), "release-execution preparation envelope must be an object")
    assert_safe_input(preparation, "source release-execution preparation envelope")
    require(set(preparation) == SOURCE_PREPARATION_FIELDS, "source release-execution preparation envelope fields drift")
    source = contract["source_preparation"]
    boundaries = contract["required_boundaries"]
    require(preparation.get("schema_version") == 1, "source release-execution preparation schema drift")
    require(preparation.get("contract_id") == source["contract_id"], "source release-execution preparation contract id mismatch")
    require(preparation.get("record_state") == source["record_state"], "source release-execution preparation record state mismatch")
    require(preparation.get("execution_preparation_state") == source["required_execution_preparation_state"], "source execution envelope is not review-ready")
    require(preparation.get("next_gate_hint") == source["required_next_gate_hint"], "source execution review gate hint mismatch")
    require(preparation.get("execution_preparation_mode") == source["required_preparation_mode"], "source execution preparation mode mismatch")
    require(preparation.get("execution_command") == source["required_execution_command"], "source deterministic execution command drift")
    require(preparation.get("official_source_reverified") is source["required_official_source_reverified"], "source official source is not reverified")
    require(preparation.get("source_bound") is source["required_source_bound"], "source execution preparation is not source-bound")
    require(preparation.get("internal_execution_envelope_prepared") is source["required_internal_execution_envelope_prepared"], "source internal execution envelope missing")
    require(preparation.get("final_offer_release_authorization_granted") is source["required_final_offer_release_authorization_granted"], "source final release authority boundary drift")
    require(preparation.get("release_executed") is source["required_release_executed"], "source release execution boundary drift")
    require(preparation.get("release_package_generated") is source["required_release_package_generated"], "source release package generation boundary drift")
    require(preparation.get("release_package_approved") is source["required_release_package_approved"], "source release package approval boundary drift")
    require(preparation.get("commercial_scope_area") == source["required_commercial_scope_area"], "source execution commercial scope drift")
    require(
        preparation.get("execution_semantics") == "INTERNAL_REVIEW_ENVELOPE_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "source execution preparation semantics drift",
    )
    require(preparation.get("eligibility_state") == boundaries["eligibility_state"], "source execution preparation eligibility drift")
    require(preparation.get("maximum_next_state") == boundaries["maximum_next_state"], "source execution preparation research boundary drift")
    require(preparation.get("human_review_required") is True, "source execution preparation human review failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(preparation.get(field) is False, f"source execution preparation {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(preparation.get(flag) is False, f"source execution preparation {flag} failed open")

    receipt = preparation.get("source_authorization_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source authorization receipt fields drift")
    require(receipt.get("decision_source") == "HUMAN", "source authorization receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source authorization reviewer_ref")
    source_authorized_at = receipt.get("decided_at")
    require(isinstance(source_authorized_at, str) and RFC3339_UTC_Z.fullmatch(source_authorized_at) is not None, "source authorization decided_at must be RFC3339 UTC-Z")

    preparation_id = safe_ref(preparation.get("final_offer_release_execution_preparation_id"), "final_offer_release_execution_preparation_id")
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
    lineage = tuple(safe_ref(preparation.get(field), field) for field in lineage_fields)
    identity = tuple(
        safe_ref(preparation.get(field), field)
        for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id")
    )
    scope = preparation["commercial_scope_area"]
    verification_ref = safe_ref(preparation.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = preparation.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source execution preparation source_as_of must be RFC3339 UTC-Z")
    return lineage, identity, scope, verification_ref, source_as_of, preparation_id


def validate_review_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, str, str, str], str, str, str, str, str, str, str]:
    require(isinstance(decision, dict), "release-execution review decision must be an object")
    assert_safe_input(decision, "release-execution review decision")
    require(set(decision) == DECISION_FIELDS, "release-execution review decision fields drift")
    policy = contract["review"]
    require(decision.get("decision_source") == policy["decision_source"], "release-execution review decision source must be HUMAN")
    preparation_id = safe_ref(decision.get("final_offer_release_execution_preparation_id"), "final_offer_release_execution_preparation_id")
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
    require(scope == contract["source_preparation"]["required_commercial_scope_area"], "release-execution review commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "release-execution review source_as_of must be RFC3339 UTC-Z")
    outcome = decision.get("execution_review_outcome")
    require(outcome in policy["allowed_execution_review_outcomes"], "release-execution review outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "release-execution review decided_at must be RFC3339 UTC-Z")
    return lineage, identity, scope, verification_ref, source_as_of, preparation_id, outcome, reviewer_ref, decided_at


def build_final_offer_release_execution_review(
    preparation: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_lineage, source_identity, source_scope, source_verification_ref, source_as_of, source_preparation_id = validate_source_preparation(preparation, contract)
    (
        decision_lineage, decision_identity, decision_scope, decision_verification_ref,
        decision_source_as_of, decision_preparation_id, outcome, reviewer_ref, decided_at,
    ) = validate_review_decision(decision, contract)
    require(decision_preparation_id == source_preparation_id, "release-execution review preparation id mismatch")
    require(decision_lineage == source_lineage, "release-execution review lineage mismatch")
    require(decision_identity == source_identity, "release-execution review identity mismatch")
    require(decision_scope == source_scope, "release-execution review scope mismatch")
    require(decision_verification_ref == source_verification_ref, "release-execution review source verification mismatch")
    require(decision_source_as_of == source_as_of, "release-execution review source_as_of mismatch")

    policy = contract["review"]
    review_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_preparation_id, *source_lineage, org, prospect, opportunity, service, source_scope,
        source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at,
    ))
    review_id = "OFFRELEXECREVIEW-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    approved_internal_only = outcome == "APPROVED_INTERNAL_ONLY"
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_execution_review_id": review_id,
        "record_state": contract["output"]["record_state"],
        "source_execution_preparation_contract_id": contract["source_preparation"]["contract_id"],
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
        "execution_review_outcome": outcome,
        "execution_review_state": review_state,
        "internal_execution_envelope_review_approved": approved_internal_only,
        "next_gate_hint": next_gate,
        "release_execution_commit_authorization_gate_required": next_gate is not None,
        "execution_review_semantics": "INTERNAL_RELEASE_EXECUTION_ENVELOPE_REVIEW_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
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
    require(result["final_offer_release_authorization_granted"] is False, "release-execution review release authority failed open")
    require(result["release_executed"] is False and result["automatic_send_enabled"] is False, "release-execution review external action failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release-execution review gate")
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_execution_review(
        load_json(args.preparation),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
