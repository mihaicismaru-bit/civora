#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_commit_preparation_contract.json"
DEFAULT_SOURCE_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_release_execution_commit_authorization_contract.json"

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
FORBIDDEN_PREPARATION_PAYLOAD_KEYS = {
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
    "schema_version", "contract_id", "final_offer_release_execution_commit_authorization_id", "record_state",
    "source_execution_review_contract_id", "source_final_offer_release_execution_review_id",
    "source_final_offer_release_execution_preparation_id", "source_final_offer_release_execution_authorization_id",
    "source_final_offer_release_package_review_id", "source_final_offer_release_package_preparation_id",
    "source_final_offer_release_authorization_id", "source_final_offer_release_readiness_id",
    "source_final_offer_candidate_review_id", "source_internal_final_offer_candidate_id",
    "source_offer_finalization_readiness_id", "source_offer_content_review_id", "source_internal_offer_draft_id",
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "release_execution_commit_authorization_outcome", "release_execution_commit_authorization_state",
    "authorization_scope", "next_gate_hint", "next_gate_authorized", "authorization_semantics", "decision_receipt",
    "eligibility_state", "maximum_next_state", "source_bound", "human_review_required",
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted", "final_offer_approval_granted",
    "final_offer_release_authorization_granted", "release_executed", "release_package_generated",
    "release_package_approved", "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled",
    "pipeline_write_enabled",
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
REQUEST_FIELDS = {
    "source_final_offer_release_execution_commit_authorization_id",
    *LINEAGE_FIELDS,
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id",
    "commercial_scope_area", "official_source_verification_ref", "source_as_of", "preparation_mode",
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
    forbidden = FORBIDDEN_PREPARATION_PAYLOAD_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "commit-preparation schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-PREPARATION-001",
        "commit-preparation contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "commit-preparation contract is not canonical")
    source = contract.get("source_authorization") or {}
    require(source == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-AUTHORIZATION-001",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_ENVELOPE",
        "required_authorization_outcome": "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "required_authorization_state": "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "required_authorization_scope": "NEXT_GATE_ONLY",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_GATE_REQUIRED",
        "required_next_gate_authorized": True,
        "required_decision_source": "HUMAN",
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_final_offer_release_authorization_granted": False,
        "required_release_executed": False,
        "required_release_package_generated": False,
        "required_release_package_approved": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source commit-authorization policy drift")
    preparation = contract.get("preparation") or {}
    require(preparation.get("allowed_preparation_modes") == ["DETERMINISTIC_INTERNAL_COMMIT_INTENT_ONLY"], "commit-preparation mode allowlist drift")
    require(preparation.get("commit_intent") == {
        "command_type": "INTERNAL_RELEASE_EXECUTION_COMMIT_INTENT_REVIEW_ENVELOPE_ONLY",
        "external_action": "NO_EXTERNAL_ACTION",
        "release_action": "NOT_EXECUTED",
        "send_action": "NOT_EXECUTED",
        "publication_action": "NOT_EXECUTED",
        "persistence_action": "NOT_EXECUTED",
    }, "commit-intent command drift")
    require(preparation.get("prepared_state") == "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_PREPARED_REVIEW_REQUIRED", "commit-preparation state drift")
    require(preparation.get("next_gate_hint") == "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_GATE_REQUIRED", "commit-preparation next-gate drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "commit-preparation boundary drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_ENVELOPE", "commit-preparation output-state drift")
    require(output.get("source_bound") is True, "commit-preparation source binding failed open")
    require(output.get("human_review_required") is True, "commit-preparation human review failed open")
    require(output.get("commit_intent_generated") is True, "commit-intent generation failed closed unexpectedly")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"commit-preparation safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_authorization"]
    require(source_contract.get("id") == source["contract_id"], "source commit-authorization contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source commit-authorization contract is not canonical")
    policy = source_contract.get("authorization") or {}
    outcome = source["required_authorization_outcome"]
    require(outcome in policy.get("allowed_authorization_outcomes", []), "source positive authorization outcome no longer allowed")
    require(policy.get("decision_source") == source["required_decision_source"], "source authorization decision-source drift")
    require(policy.get("authorization_scope") == source["required_authorization_scope"], "source authorization scope drift")
    require(policy.get("outcome_state_map", {}).get(outcome) == source["required_authorization_state"], "source authorization state policy drift")
    require(policy.get("outcome_next_gate_map", {}).get(outcome) == source["required_next_gate_hint"], "source authorization next-gate policy drift")
    require(policy.get("outcome_next_gate_authorization_map", {}).get(outcome) is source["required_next_gate_authorized"], "source next-gate authorization policy drift")
    output = source_contract.get("output") or {}
    require(output.get("record_state") == source["record_state"], "source commit-authorization output-state drift")
    require(output.get("source_bound") is True and output.get("human_review_required") is True, "source commit-authorization review/source boundary failed open")
    for field in FALSE_BOUNDARY_FIELDS:
        require(output.get(field) is False, f"source commit-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source commit-authorization {flag} failed open")


def validate_source_authorization(value: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(value, dict), "source commit-authorization envelope must be an object")
    assert_safe_payload(value, "source commit-authorization envelope")
    require(set(value) == SOURCE_AUTHORIZATION_FIELDS, "source commit-authorization envelope fields drift")
    source = contract["source_authorization"]
    boundaries = contract["required_boundaries"]
    require(value.get("schema_version") == 1, "source commit-authorization schema drift")
    require(value.get("contract_id") == source["contract_id"], "source commit-authorization contract mismatch")
    require(value.get("record_state") == source["record_state"], "source commit-authorization record state mismatch")
    require(value.get("release_execution_commit_authorization_outcome") == source["required_authorization_outcome"], "source commit preparation is not authorized")
    require(value.get("release_execution_commit_authorization_state") == source["required_authorization_state"], "source commit-authorization state mismatch")
    require(value.get("authorization_scope") == source["required_authorization_scope"], "source authorization scope is not NEXT_GATE_ONLY")
    require(value.get("next_gate_hint") == source["required_next_gate_hint"], "source commit-preparation gate hint mismatch")
    require(value.get("next_gate_authorized") is source["required_next_gate_authorized"], "source commit-preparation gate is not authorized")
    require(value.get("official_source_reverified") is source["required_official_source_reverified"], "source official source not reverified")
    require(value.get("source_bound") is source["required_source_bound"], "source authorization is not source-bound")
    require(value.get("final_offer_release_authorization_granted") is False, "source final release authority boundary drift")
    require(value.get("release_executed") is False, "source release execution boundary drift")
    require(value.get("release_package_generated") is False, "source release-package generation boundary drift")
    require(value.get("release_package_approved") is False, "source release-package approval boundary drift")
    require(value.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(value.get("eligibility_state") == boundaries["eligibility_state"], "source eligibility drift")
    require(value.get("maximum_next_state") == boundaries["maximum_next_state"], "source research boundary drift")
    require(value.get("human_review_required") is True, "source human-review boundary failed open")
    require(value.get("authorization_semantics") == "NEXT_INTERNAL_COMMIT_PREPARATION_GATE_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH", "source authorization semantics drift")
    for field in FALSE_BOUNDARY_FIELDS:
        require(value.get(field) is False, f"source commit-authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(value.get(flag) is False, f"source commit-authorization {flag} failed open")
    receipt = value.get("decision_receipt")
    require(isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"}, "source decision receipt fields drift")
    require(receipt.get("decision_source") == source["required_decision_source"], "source commit authorization is not human")
    safe_ref(receipt.get("reviewer_ref"), "source reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "source decided_at must be RFC3339 UTC-Z")
    authorization_id = safe_ref(value.get("final_offer_release_execution_commit_authorization_id"), "final_offer_release_execution_commit_authorization_id")
    lineage = tuple(safe_ref(value.get(field), field) for field in LINEAGE_FIELDS)
    identity = tuple(safe_ref(value.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    verification_ref = safe_ref(value.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = value.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "source source_as_of must be RFC3339 UTC-Z")
    return authorization_id, lineage, identity, value["commercial_scope_area"], verification_ref, source_as_of


def validate_request(value: dict[str, Any], contract: dict[str, Any]):
    require(isinstance(value, dict), "commit-preparation request must be an object")
    assert_safe_payload(value, "commit-preparation request")
    require(set(value) == REQUEST_FIELDS, "commit-preparation request fields drift")
    authorization_id = safe_ref(value.get("source_final_offer_release_execution_commit_authorization_id"), "source_final_offer_release_execution_commit_authorization_id")
    lineage = tuple(safe_ref(value.get(field), field) for field in LINEAGE_FIELDS)
    identity = tuple(safe_ref(value.get(field), field) for field in ("organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id"))
    scope = value.get("commercial_scope_area")
    require(scope == contract["source_authorization"]["required_commercial_scope_area"], "commit-preparation commercial scope drift")
    verification_ref = safe_ref(value.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = value.get("source_as_of")
    require(isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None, "commit-preparation source_as_of must be RFC3339 UTC-Z")
    mode = value.get("preparation_mode")
    require(mode in contract["preparation"]["allowed_preparation_modes"], "commit-preparation mode escaped allowlist")
    return authorization_id, lineage, identity, scope, verification_ref, source_as_of, mode


def build_final_offer_release_execution_commit_preparation(
    authorization: dict[str, Any],
    request: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_authorization_id, source_lineage, source_identity, source_scope, source_verification_ref, source_as_of = validate_source_authorization(authorization, contract)
    request_authorization_id, request_lineage, request_identity, request_scope, request_verification_ref, request_source_as_of, mode = validate_request(request, contract)
    require(request_authorization_id == source_authorization_id, "commit-preparation source authorization id mismatch")
    require(request_lineage == source_lineage, "commit-preparation lineage mismatch")
    require(request_identity == source_identity, "commit-preparation identity mismatch")
    require(request_scope == source_scope, "commit-preparation scope mismatch")
    require(request_verification_ref == source_verification_ref, "commit-preparation source verification mismatch")
    require(request_source_as_of == source_as_of, "commit-preparation source_as_of mismatch")
    org, prospect, opportunity, service = source_identity
    basis = "|".join((source_authorization_id, *source_lineage, org, prospect, opportunity, service, source_scope, source_verification_ref, source_as_of, mode))
    preparation_id = "OFFRELEXECCOMMITPREP-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    policy = contract["preparation"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_release_execution_commit_preparation_id": preparation_id,
        "record_state": contract["output"]["record_state"],
        "source_authorization_contract_id": contract["source_authorization"]["contract_id"],
        "source_final_offer_release_execution_commit_authorization_id": source_authorization_id,
        **{field: authorization[field] for field in LINEAGE_FIELDS},
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": source_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "preparation_mode": mode,
        "commit_intent": dict(policy["commit_intent"]),
        "commit_preparation_state": policy["prepared_state"],
        "next_gate_hint": policy["next_gate_hint"],
        "commit_preparation_semantics": "DETERMINISTIC_INTERNAL_COMMIT_INTENT_FOR_HUMAN_REVIEW_ONLY_NO_EXTERNAL_ACTION_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "source_bound": True,
        "human_review_required": True,
        "commit_intent_generated": True,
    }
    for field in FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in DISABLED_ACTION_FLAGS:
        result[flag] = False
    require(result["commit_intent"]["external_action"] == "NO_EXTERNAL_ACTION", "commit intent escaped no-external-action boundary")
    require(result["release_executed"] is False and result["persistence_executed"] is False, "commit preparation executed an action")
    require(result["automatic_send_enabled"] is False, "commit preparation enabled send")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder deterministic final-offer release execution commit-preparation gate")
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_release_execution_commit_preparation(
        load_json(args.authorization),
        load_json(args.request),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
