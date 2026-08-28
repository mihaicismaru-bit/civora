#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_package_preparation_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_authorization_contract.json"

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
SOURCE_FALSE_BOUNDARY_FIELDS = tuple(field for field in FALSE_BOUNDARY_FIELDS if field != "release_package_approved")
FORBIDDEN_PERSON_LEVEL_KEYS = {
    "person_name", "personal_name", "personal_email", "personal_phone", "home_address",
    "personal_social_profile", "personal_identifier", "date_of_birth", "private_contact",
    "contact_name", "email", "phone", "cnp", "reviewer_name", "reviewer_email", "reviewer_phone",
}
FORBIDDEN_PACKAGE_INPUT_KEYS = {
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
SOURCE_AUTHORIZATION_FIELDS = {
    "schema_version", "contract_id", "final_offer_release_authorization_id", "record_state",
    "source_release_readiness_contract_id", "source_final_offer_release_readiness_id",
    "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id", "source_offer_content_review_id",
    "source_internal_offer_draft_id", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "commercial_scope_area", "official_source_reverified",
    "official_source_verification_ref", "source_as_of", "release_authorization_outcome",
    "release_authorization_state", "authorization_scope", "next_gate_hint", "next_gate_authorized",
    "release_authorization_semantics", "decision_receipt", "eligibility_state", "maximum_next_state",
    "human_review_required", "public_offer_content_included", "final_offer_generated",
    "offer_approval_granted", "final_offer_approval_granted", "final_offer_release_authorization_granted",
    "release_executed", "release_package_generated", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed", "offer_engine_invocation_allowed",
    "pricing_decision_allowed", "crm_context_materialization_allowed", "external_contact_enabled",
    "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}
PREPARATION_FIELDS = {
    "source_final_offer_release_authorization_id", "source_final_offer_release_readiness_id",
    "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id", "source_offer_content_review_id",
    "source_internal_offer_draft_id", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "commercial_scope_area", "official_source_verification_ref", "source_as_of",
    "preparation_mode",
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
    forbidden = FORBIDDEN_PACKAGE_INPUT_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "release-package-preparation schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-PREPARATION-001",
        "release-package-preparation contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "release-package-preparation contract is not canonical")
    require(contract.get("source_authorization") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-AUTHORIZATION-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_AUTHORIZATION_ENVELOPE",
        "required_release_authorization_outcome": "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "required_release_authorization_state": "FINAL_OFFER_RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "required_authorization_scope": "NEXT_GATE_ONLY",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_GATE_REQUIRED",
        "required_next_gate_authorized": True,
        "required_official_source_reverified": True,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source release-authorization policy drift")
    preparation = contract.get("preparation") or {}
    require(preparation.get("allowed_preparation_modes") == ["DETERMINISTIC_INTERNAL_METADATA_CHECKLIST_ONLY"], "preparation mode drift")
    require(preparation.get("source_as_of_format") == "RFC3339_UTC_Z", "preparation timestamp policy drift")
    require(preparation.get("package_state") == "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_PREPARED_REVIEW_REQUIRED", "preparation state drift")
    require(preparation.get("next_gate_hint") == "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_GATE_REQUIRED", "preparation next-gate drift")
    require(preparation.get("content_scope") == "INTERNAL_RELEASE_METADATA_AND_CHECKLIST_ONLY", "preparation content-scope drift")
    require(preparation.get("required_checklist") == [
        "SOURCE_AUTHORIZATION_MATCHED", "OFFICIAL_SOURCE_BINDING_PRESERVED",
        "SELECTED_SERVICE_SCOPE_PRESERVED", "NO_PUBLIC_OFFER_CONTENT_INCLUDED",
        "NO_PRICING_OR_MATERIAL_CLAIMS_INCLUDED", "NO_PERSISTENCE_CRM_OR_OUTREACH_ENABLED",
    ], "preparation checklist drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True, "external_contact_enabled": False,
        "automatic_offer_enabled": False, "automatic_send_enabled": False,
        "crm_write_enabled": False, "pipeline_write_enabled": False,
    }, "release-package-preparation boundary drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_ENVELOPE", "output-state drift")
    for field in ("internal_release_package_prepared", "release_package_metadata_included", "release_package_review_required", "source_bound", "human_review_required"):
        require(output.get(field) is True, f"{field} must remain enabled")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"release-package-preparation safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_authorization"]
    require(source_contract.get("id") == source["contract_id"], "source release-authorization contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source release-authorization contract is not canonical")
    source_policy = source_contract.get("authorization") or {}
    outcome = source["required_release_authorization_outcome"]
    require(outcome in source_policy.get("allowed_authorization_outcomes", []), "source positive authorization no longer allowed")
    require(source_policy.get("outcome_state_map", {}).get(outcome) == source["required_release_authorization_state"], "source authorization state drift")
    require(source_policy.get("authorization_scope") == source["required_authorization_scope"], "source authorization scope drift")
    require(source_policy.get("outcome_next_gate_map", {}).get(outcome) == source["required_next_gate_hint"], "source authorization next-gate drift")
    require(source_policy.get("outcome_next_gate_authorization_map", {}).get(outcome) is True, "source authorization next-gate permission drift")
    output = source_contract.get("output") or {}
    require(output.get("record_state") == source["record_state"], "source authorization output-state drift")
    require(output.get("human_review_required") is True, "source authorization human-review boundary failed open")
    for field in SOURCE_FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"source release-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source release-authorization {flag} failed open")


def validate_source_authorization(source_envelope: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(source_envelope, dict), "release-authorization envelope must be an object")
    assert_safe_input(source_envelope, "source release-authorization envelope")
    require(set(source_envelope) == SOURCE_AUTHORIZATION_FIELDS, "source release-authorization envelope fields drift")
    source = contract["source_authorization"]
    boundaries = contract["required_boundaries"]
    require(source_envelope.get("schema_version") == 1, "source release-authorization schema drift")
    require(source_envelope.get("contract_id") == source["contract_id"], "source release-authorization contract id mismatch")
    require(source_envelope.get("record_state") == source["record_state"], "source release-authorization record state mismatch")
    require(source_envelope.get("release_authorization_outcome") == source["required_release_authorization_outcome"], "source is not release-preparation authorized")
    require(source_envelope.get("release_authorization_state") == source["required_release_authorization_state"], "source release-authorization state mismatch")
    require(source_envelope.get("authorization_scope") == source["required_authorization_scope"], "source authorization scope mismatch")
    require(source_envelope.get("next_gate_hint") == source["required_next_gate_hint"], "source preparation gate hint mismatch")
    require(source_envelope.get("next_gate_authorized") is source["required_next_gate_authorized"], "source preparation gate not authorized")
    require(source_envelope.get("official_source_reverified") is source["required_official_source_reverified"], "source official source not reverified")
    require(source_envelope.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(source_envelope.get("release_authorization_semantics") == "INTERNAL_NEXT_GATE_AUTHORIZATION_ONLY_NOT_FINAL_RELEASE_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH", "source authorization semantics drift")
    require(source_envelope.get("eligibility_state") == boundaries["eligibility_state"], "source eligibility drift")
    require(source_envelope.get("maximum_next_state") == boundaries["maximum_next_state"], "source research boundary drift")
    require(source_envelope.get("human_review_required") is True, "source human review failed open")
    for field in SOURCE_FALSE_BOUNDARY_FIELDS:
        require(source_envelope.get(field) is False, f"source release-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_envelope.get(flag) is False, f"source release-authorization {flag} failed open")
    receipt = source_envelope.get("decision_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source decision receipt fields drift")
    require(receipt.get("decision_source") == "HUMAN", "source release-authorization receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "source decided_at must be RFC3339 UTC-Z")
    lineage_fields = (
        "final_offer_release_authorization_id", "source_final_offer_release_readiness_id",
        "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
        "source_offer_finalization_readiness_id", "source_offer_content_review_id", "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(source_envelope.get(field), field) for field in lineage_fields)
    identity = tuple(safe_ref(source_envelope.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    verification_ref = safe_ref(source_envelope.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = source_envelope.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source_as_of must be RFC3339 UTC-Z")
    return lineage, identity, source_envelope["commercial_scope_area"], verification_ref, source_as_of


def validate_preparation_request(request: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(request, dict), "release-package preparation request must be an object")
    assert_safe_input(request, "release-package preparation request")
    require(set(request) == PREPARATION_FIELDS, "release-package preparation request fields drift")
    mode = request.get("preparation_mode")
    require(mode in contract["preparation"]["allowed_preparation_modes"], "release-package preparation mode is not allowed")
    lineage_fields = (
        "source_final_offer_release_authorization_id", "source_final_offer_release_readiness_id",
        "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
        "source_offer_finalization_readiness_id", "source_offer_content_review_id", "source_internal_offer_draft_id",
    )
    lineage = tuple(safe_ref(request.get(field), field) for field in lineage_fields)
    identity = tuple(safe_ref(request.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    scope = safe_ref(request.get("commercial_scope_area"), "commercial_scope_area")
    verification_ref = safe_ref(request.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = request.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "request source_as_of must be RFC3339 UTC-Z")
    return lineage, identity, scope, verification_ref, source_as_of, mode


def build_final_offer_release_package_preparation(
    source_authorization: dict[str, Any],
    preparation_request: dict[str, Any],
    contract: dict[str, Any],
    source_contract: dict[str, Any],
) -> dict[str, Any]:
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_lineage, source_identity, source_scope, source_verification_ref, source_as_of = validate_source_authorization(source_authorization, contract)
    request_lineage, request_identity, request_scope, request_verification_ref, request_source_as_of, mode = validate_preparation_request(preparation_request, contract)
    require(request_lineage == source_lineage, "release-package preparation lineage mismatch")
    require(request_identity == source_identity, "release-package preparation identity mismatch")
    require(request_scope == source_scope, "release-package preparation scope mismatch")
    require(request_verification_ref == source_verification_ref, "release-package preparation source verification mismatch")
    require(request_source_as_of == source_as_of, "release-package preparation source_as_of mismatch")

    authorization_id, readiness_id, candidate_review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id = source_lineage
    org, prospect, opportunity, service = source_identity
    basis = "|".join((authorization_id, readiness_id, candidate_review_id, candidate_id, finalization_readiness_id, content_review_id, draft_id, org, prospect, opportunity, service, source_scope, source_verification_ref, source_as_of, mode))
    package_id = "OFFRELPREP-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    checklist = [{"check": check, "status": "PASS"} for check in contract["preparation"]["required_checklist"]]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_package_preparation_id": package_id,
        "record_state": contract["output"]["record_state"],
        "source_release_authorization_contract_id": contract["source_authorization"]["contract_id"],
        "source_final_offer_release_authorization_id": authorization_id,
        "source_final_offer_release_readiness_id": readiness_id,
        "source_final_offer_candidate_review_id": candidate_review_id,
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
        "preparation_mode": mode,
        "package_state": contract["preparation"]["package_state"],
        "content_scope": contract["preparation"]["content_scope"],
        "next_gate_hint": contract["preparation"]["next_gate_hint"],
        "package_metadata": {
            "source_authorization_id": authorization_id,
            "organization_key": org,
            "prospect_id": prospect,
            "opportunity_id": opportunity,
            "service_id": service,
            "commercial_scope_area": source_scope,
            "official_source_verification_ref": source_verification_ref,
            "source_as_of": source_as_of,
        },
        "preparation_checklist": checklist,
        "preparation_semantics": "INTERNAL_METADATA_CHECKLIST_ONLY_NOT_RELEASABLE_PACKAGE_FINAL_OFFER_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "internal_release_package_prepared": True,
        "release_package_metadata_included": True,
        "release_package_review_required": True,
        "source_bound": True,
        "human_review_required": True,
    }
    for field in FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in DISABLED_ACTION_FLAGS:
        result[flag] = False
    require(result["release_package_generated"] is False and result["release_executed"] is False, "release-package external boundary failed open")
    require(result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_GATE_REQUIRED", "release-package review gate failed open")
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="EUCONS Client Finder deterministic internal final-offer release-package preparation")
    parser.add_argument("--source-authorization", required=True, type=Path)
    parser.add_argument("--preparation-request", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_package_preparation(
        load_json(args.source_authorization), load_json(args.preparation_request),
        load_json(args.contract), load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
