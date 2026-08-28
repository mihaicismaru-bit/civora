#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_package_review_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_package_preparation_contract.json"

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
}
SOURCE_PREPARATION_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_package_preparation_id", "record_state",
    "source_release_authorization_contract_id", "source_final_offer_release_authorization_id",
    "source_final_offer_release_readiness_id", "source_final_offer_candidate_review_id",
    "source_internal_final_offer_candidate_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id", "organization_key",
    "prospect_id", "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "preparation_mode", "package_state", "content_scope", "next_gate_hint", "package_metadata",
    "preparation_checklist", "preparation_semantics", "eligibility_state", "maximum_next_state",
    "internal_release_package_prepared", "release_package_metadata_included",
    "release_package_review_required", "source_bound", "human_review_required",
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
    "final_offer_release_package_preparation_id",
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
    "package_review_outcome",
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
    require(contract.get("schema_version") == 1, "release-package review schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-REVIEW-001",
        "release-package review contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "release-package review contract is not canonical")
    require(contract.get("source_preparation") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-PREPARATION-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_ENVELOPE",
        "required_package_state": "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_PREPARED_REVIEW_REQUIRED",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_GATE_REQUIRED",
        "required_content_scope": "INTERNAL_RELEASE_METADATA_AND_CHECKLIST_ONLY",
        "required_preparation_mode": "DETERMINISTIC_INTERNAL_METADATA_CHECKLIST_ONLY",
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_release_package_review_required": True,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "required_checklist": [
            "SOURCE_AUTHORIZATION_MATCHED",
            "OFFICIAL_SOURCE_BINDING_PRESERVED",
            "SELECTED_SERVICE_SCOPE_PRESERVED",
            "NO_PUBLIC_OFFER_CONTENT_INCLUDED",
            "NO_PRICING_OR_MATERIAL_CLAIMS_INCLUDED",
            "NO_PERSISTENCE_CRM_OR_OUTREACH_ENABLED",
        ],
    }, "source release-package preparation policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "release-package review boundary drift")
    review = contract.get("review") or {}
    outcomes = ["CHANGES_REQUIRED", "REJECTED", "APPROVED_INTERNAL_ONLY"]
    require(review.get("decision_source") == "HUMAN", "release-package review decision source failed open")
    require(review.get("allowed_package_review_outcomes") == outcomes, "release-package review outcome allowlist drift")
    require(review.get("outcome_state_map") == {
        "CHANGES_REQUIRED": "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_CHANGES_REQUIRED",
        "REJECTED": "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_REJECTED",
        "APPROVED_INTERNAL_ONLY": "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_APPROVED_INTERNAL_ONLY",
    }, "release-package review state mapping drift")
    require(review.get("outcome_next_gate_map") == {
        "CHANGES_REQUIRED": None,
        "REJECTED": None,
        "APPROVED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_AUTHORIZATION_GATE_REQUIRED",
    }, "release-package review next-gate mapping drift")
    require(review.get("decided_at_format") == "RFC3339_UTC_Z", "release-package review timestamp policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_ENVELOPE", "release-package review output-state drift")
    require(output.get("source_bound") is True, "release-package review source binding failed open")
    require(output.get("human_review_required") is True, "release-package review human-review boundary failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-package review safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_preparation"]
    require(source_contract.get("id") == source["contract_id"], "source release-package preparation contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source release-package preparation contract is not canonical")
    preparation = source_contract.get("preparation") or {}
    require(preparation.get("allowed_preparation_modes") == [source["required_preparation_mode"]], "source preparation mode drift")
    require(preparation.get("package_state") == source["required_package_state"], "source package state policy drift")
    require(preparation.get("next_gate_hint") == source["required_next_gate_hint"], "source package next-gate policy drift")
    require(preparation.get("content_scope") == source["required_content_scope"], "source package content-scope policy drift")
    require(preparation.get("required_checklist") == source["required_checklist"], "source package checklist policy drift")
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source package output-state drift")
    for field in (
        "internal_release_package_prepared", "release_package_metadata_included",
        "release_package_review_required", "source_bound", "human_review_required",
    ):
        require(source_output.get(field) is True, f"source package {field} must remain enabled")
    for field in FALSE_BOUNDARY_FIELDS:
        require(source_output.get(field) is False, f"source package {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source package {flag} failed open")


def validate_source_preparation(
    package: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, str, str, str], str, str, str, str]:
    require(isinstance(package, dict), "release-package preparation envelope must be an object")
    assert_safe_input(package, "source release-package preparation envelope")
    require(set(package) == SOURCE_PREPARATION_FIELDS, "source release-package preparation envelope fields drift")
    source = contract["source_preparation"]
    boundaries = contract["required_boundaries"]
    require(package.get("schema_version") == 1, "source release-package preparation schema drift")
    require(package.get("contract_id") == source["contract_id"], "source release-package preparation contract id mismatch")
    require(package.get("record_state") == source["record_state"], "source release-package preparation record state mismatch")
    require(package.get("package_state") == source["required_package_state"], "source release package is not review-ready")
    require(package.get("next_gate_hint") == source["required_next_gate_hint"], "source release-package review gate hint mismatch")
    require(package.get("content_scope") == source["required_content_scope"], "source release-package content scope mismatch")
    require(package.get("preparation_mode") == source["required_preparation_mode"], "source release-package preparation mode mismatch")
    require(package.get("official_source_reverified") is source["required_official_source_reverified"], "source official source is not reverified")
    require(package.get("source_bound") is source["required_source_bound"], "source release package is not source-bound")
    require(package.get("release_package_review_required") is source["required_release_package_review_required"], "source release package no longer requires review")
    require(package.get("release_package_generated") is source["required_release_package_generated"], "source release package generation boundary drift")
    require(package.get("release_package_approved") is source["required_release_package_approved"], "source release package approval boundary drift")
    require(package.get("commercial_scope_area") == source["required_commercial_scope_area"], "source release-package commercial scope drift")
    require(package.get("preparation_semantics") == "INTERNAL_METADATA_CHECKLIST_ONLY_NOT_RELEASABLE_PACKAGE_FINAL_OFFER_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH", "source release-package preparation semantics drift")
    require(package.get("eligibility_state") == boundaries["eligibility_state"], "source release-package eligibility drift")
    require(package.get("maximum_next_state") == boundaries["maximum_next_state"], "source release-package research boundary drift")
    for field in (
        "internal_release_package_prepared", "release_package_metadata_included",
        "release_package_review_required", "source_bound", "human_review_required",
    ):
        require(package.get(field) is True, f"source release package {field} failed closed")
    for field in FALSE_BOUNDARY_FIELDS:
        require(package.get(field) is False, f"source release package {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(package.get(flag) is False, f"source release package {flag} failed open")

    package_id = safe_ref(package.get("final_offer_release_package_preparation_id"), "final_offer_release_package_preparation_id")
    safe_ref(package.get("source_release_authorization_contract_id"), "source_release_authorization_contract_id")
    lineage_fields = (
        "source_final_offer_release_authorization_id",
        "source_final_offer_release_readiness_id",
        "source_final_offer_candidate_review_id",
        "source_internal_final_offer_candidate_id",
        "source_offer_finalization_readiness_id",
        "source_offer_content_review_id",
        "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(package.get(field), field) for field in lineage_fields)
    identity = tuple(
        safe_ref(package.get(field), field)
        for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id")
    )
    scope = package["commercial_scope_area"]
    verification_ref = safe_ref(package.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = package.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source release-package source_as_of must be RFC3339 UTC-Z")
    org, prospect, opportunity, service = identity
    expected_metadata = {
        "source_authorization_id": lineage[0],
        "organization_key": org,
        "prospect_id": prospect,
        "opportunity_id": opportunity,
        "service_id": service,
        "commercial_scope_area": scope,
        "official_source_verification_ref": verification_ref,
        "source_as_of": source_as_of,
    }
    require(package.get("package_metadata") == expected_metadata, "source release-package metadata drifted from deterministic preparation")
    expected_checklist = [{"check": item, "status": "PASS"} for item in source["required_checklist"]]
    require(package.get("preparation_checklist") == expected_checklist, "source release-package checklist drifted from deterministic preparation")
    return lineage, identity, scope, verification_ref, source_as_of, package_id


def validate_review_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, str, str, str], str, str, str, str, str, str, str]:
    require(isinstance(decision, dict), "release-package review decision must be an object")
    assert_safe_input(decision, "release-package review decision")
    require(set(decision) == DECISION_FIELDS, "release-package review decision fields drift")
    policy = contract["review"]
    require(decision.get("decision_source") == policy["decision_source"], "release-package review decision source must be HUMAN")
    package_id = safe_ref(decision.get("final_offer_release_package_preparation_id"), "final_offer_release_package_preparation_id")
    lineage_fields = (
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
    require(scope == contract["source_preparation"]["required_commercial_scope_area"], "release-package review commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "release-package review source_as_of must be RFC3339 UTC-Z")
    outcome = decision.get("package_review_outcome")
    require(outcome in policy["allowed_package_review_outcomes"], "release-package review outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "release-package review decided_at must be RFC3339 UTC-Z")
    return lineage, identity, scope, verification_ref, source_as_of, package_id, outcome, reviewer_ref, decided_at


def build_final_offer_release_package_review(
    package: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_lineage, source_identity, source_scope, source_verification_ref, source_as_of, source_package_id = validate_source_preparation(package, contract)
    (
        decision_lineage, decision_identity, decision_scope, decision_verification_ref,
        decision_source_as_of, decision_package_id, outcome, reviewer_ref, decided_at,
    ) = validate_review_decision(decision, contract)
    require(decision_package_id == source_package_id, "release-package review preparation id mismatch")
    require(decision_lineage == source_lineage, "release-package review lineage mismatch")
    require(decision_identity == source_identity, "release-package review identity mismatch")
    require(decision_scope == source_scope, "release-package review scope mismatch")
    require(decision_verification_ref == source_verification_ref, "release-package review source verification mismatch")
    require(decision_source_as_of == source_as_of, "release-package review source_as_of mismatch")

    policy = contract["review"]
    review_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_package_id, *source_lineage, org, prospect, opportunity, service, source_scope,
        source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at,
    ))
    review_id = "OFFRELPKGREVIEW-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    approved_internal_only = outcome == "APPROVED_INTERNAL_ONLY"
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_package_review_id": review_id,
        "record_state": contract["output"]["record_state"],
        "source_release_package_preparation_contract_id": contract["source_preparation"]["contract_id"],
        "source_final_offer_release_package_preparation_id": source_package_id,
        "source_final_offer_release_authorization_id": source_lineage[0],
        "source_final_offer_release_readiness_id": source_lineage[1],
        "source_final_offer_candidate_review_id": source_lineage[2],
        "source_internal_final_offer_candidate_id": source_lineage[3],
        "source_offer_finalization_readiness_id": source_lineage[4],
        "source_offer_content_review_id": source_lineage[5],
        "source_internal_offer_draft_id": source_lineage[6],
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": source_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "package_review_outcome": outcome,
        "package_review_state": review_state,
        "internal_release_package_review_approved": approved_internal_only,
        "next_gate_hint": next_gate,
        "release_execution_authorization_gate_required": next_gate is not None,
        "package_review_semantics": "INTERNAL_RELEASE_PACKAGE_REVIEW_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
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
    require(result["final_offer_release_authorization_granted"] is False, "release-package review release authorization failed open")
    require(result["release_executed"] is False and result["release_package_generated"] is False, "release-package review execution boundary failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only final-offer release-package review gate")
    parser.add_argument("--package", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_package_review(
        load_json(args.package),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
