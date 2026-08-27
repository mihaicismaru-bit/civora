#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_internal_offer_draft_generation_contract.json"
DEFAULT_SOURCE_AUTHORIZATION_CONTRACT = EUCONS / "leads" / "client_finder_offer_preparation_authorization_contract.json"

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
FORBIDDEN_DRAFT_INPUT_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "price", "amount_minor", "pricing_rule", "discount", "fee", "quote",
    "payment_terms", "terms", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body", "offer_body", "proposal_text", "offer_text",
    "subject", "headline", "cta", "freeform_content", "material_claim", "claim_text",
}
GENERATION_FIELDS = {
    "source_offer_preparation_authorization_id",
    "organization_key",
    "prospect_id",
    "selected_opportunity_id",
    "selected_service_id",
    "commercial_scope_area",
    "official_source_verification_ref",
    "source_as_of",
    "generation_mode",
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


def assert_safe_generation_input(value: Any) -> None:
    assert_no_person_level_fields(value, "draft generation request")
    keys = set(recursive_keys(value))
    forbidden = FORBIDDEN_DRAFT_INPUT_KEYS & keys
    require(not forbidden, f"forbidden material/freeform field entered draft request: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "internal offer draft schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-INTERNAL-OFFER-DRAFT-GENERATION-001",
        "internal offer draft contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "internal offer draft contract is not canonical")
    require(contract.get("source_authorization") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-PREPARATION-AUTHORIZATION-001",
        "record_state": "CLIENT_FINDER_OFFER_PREPARATION_AUTHORIZATION_ENVELOPE",
        "required_authorization_outcome": "OFFER_PREPARATION_AUTHORIZED",
        "required_offer_preparation_state": "OFFER_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "required_next_gate_hint": "SEPARATE_OFFER_DRAFT_GENERATION_GATE_REQUIRED",
        "required_offer_draft_generation_gate_required": True,
        "required_authorization_capability": "INTERNAL_DRAFT_PREPARATION_ONLY",
        "required_official_source_reverified": True,
        "required_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source authorization policy drift")
    require(contract.get("generation") == {
        "allowed_generation_modes": ["DETERMINISTIC_INTERNAL_TEMPLATE_ONLY"],
        "source_as_of_format": "RFC3339_UTC_Z",
        "draft_state": "INTERNAL_OFFER_DRAFT_GENERATED_REVIEW_REQUIRED",
        "next_gate_hint": "SEPARATE_OFFER_CONTENT_REVIEW_GATE_REQUIRED",
        "content_scope": "INTERNAL_TEMPLATE_SKELETON_ONLY",
    }, "internal draft generation policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "internal draft boundary drift")

    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_INTERNAL_OFFER_DRAFT_ENVELOPE", "draft output state drift")
    for field in ("internal_draft_generated", "internal_draft_content_included", "source_bound", "draft_review_required", "human_review_required"):
        require(output.get(field) is True, f"{field} must remain enabled")
    for field in (
        "public_offer_content_included", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "draft_approval_granted", "target_state_committed",
        "persistence_executed", "draft_persistence_allowed", "production_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"internal draft safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_authorization"]
    require(source_contract.get("id") == source["contract_id"], "source authorization contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source authorization contract is not canonical")
    require((source_contract.get("output") or {}).get("record_state") == source["record_state"], "source authorization output-state drift")
    auth = source_contract.get("authorization") or {}
    require(source["required_authorization_outcome"] in auth.get("allowed_authorization_outcomes", []), "source no longer allows preparation authorization")
    require(
        auth.get("outcome_state_map", {}).get(source["required_authorization_outcome"])
        == source["required_offer_preparation_state"],
        "source preparation-state mapping drift",
    )
    require(
        auth.get("outcome_next_gate_map", {}).get(source["required_authorization_outcome"])
        == source["required_next_gate_hint"],
        "source next-gate mapping drift",
    )
    require(source["required_authorization_capability"] in auth.get("allowed_capabilities", []), "source capability allowlist drift")
    source_output = source_contract.get("output") or {}
    for field in (
        "target_state_committed", "persistence_executed", "offer_preparation_persistence_allowed",
        "offer_authorization_granted", "offer_content_included", "pricing_included",
        "offer_draft_generation_allowed", "offer_generation_allowed", "offer_engine_invocation_allowed",
        "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(source_output.get(field) is False, f"source authorization {field} failed open")
    require(source_output.get("human_review_required") is True, "source authorization human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source authorization {flag} failed open")


def validate_source_authorization(
    authorization: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str]:
    require(isinstance(authorization, dict), "offer preparation authorization envelope must be an object")
    assert_no_person_level_fields(authorization, "source authorization envelope")
    keys = set(recursive_keys(authorization))
    forbidden = FORBIDDEN_DRAFT_INPUT_KEYS & keys
    require(not forbidden, f"forbidden material/freeform field entered source authorization: {sorted(forbidden)[0] if forbidden else ''}")
    source = contract["source_authorization"]
    boundaries = contract["required_boundaries"]
    require(authorization.get("contract_id") == source["contract_id"], "source authorization contract id mismatch")
    require(authorization.get("record_state") == source["record_state"], "source authorization record state mismatch")
    require(authorization.get("authorization_outcome") == source["required_authorization_outcome"], "offer preparation was not authorized")
    require(authorization.get("offer_preparation_state") == source["required_offer_preparation_state"], "offer preparation state is not generation-ready")
    require(authorization.get("next_gate_hint") == source["required_next_gate_hint"], "source authorization next-gate hint mismatch")
    require(
        authorization.get("offer_draft_generation_gate_required") is source["required_offer_draft_generation_gate_required"],
        "source authorization did not require draft generation gate",
    )
    require(authorization.get("authorization_capability") == source["required_authorization_capability"], "source authorization capability mismatch")
    require(authorization.get("official_source_reverified") is source["required_official_source_reverified"], "official source reverification missing")
    projection = authorization.get("commercial_scope_projection")
    require(isinstance(projection, dict), "source commercial scope projection missing")
    require(set(projection) == {"area_code", "selected_service_id"}, "source commercial scope projection fields drift")
    require(projection.get("area_code") == source["required_scope_area"], "source commercial scope area mismatch")
    require(projection.get("selected_service_id") == authorization.get("selected_service_id"), "source commercial scope service mismatch")
    require(
        authorization.get("authorization_semantics")
        == "INTERNAL_PREPARATION_PERMISSION_NOT_OFFER_GENERATION_PRICING_ELIGIBILITY_OR_OUTREACH",
        "source authorization semantics drift",
    )
    require(authorization.get("offer_preparation_authorized") is True, "source authorization decision derivation failed")
    require(authorization.get("eligibility_state") == boundaries["eligibility_state"], "source authorization eligibility drift")
    require(authorization.get("maximum_next_state") == boundaries["maximum_next_state"], "source authorization research boundary drift")
    require(authorization.get("target_state_committed") is False, "source authorization committed target state")
    require(authorization.get("persistence_executed") is False, "source authorization persisted state")
    for field in (
        "offer_preparation_persistence_allowed", "offer_authorization_granted", "offer_content_included",
        "pricing_included", "offer_draft_generation_allowed", "offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(authorization.get(field) is False, f"source authorization {field} failed open")
    require(authorization.get("human_review_required") is True, "source authorization human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(authorization.get(flag) is False, f"source authorization {flag} failed open")
    receipt = authorization.get("decision_receipt")
    require(isinstance(receipt, dict), "source authorization decision receipt missing")
    require(receipt.get("decision_source") == "HUMAN", "source authorization decision was not human")
    safe_ref(receipt.get("reviewer_ref"), "source authorization reviewer_ref")
    source_decided_at = receipt.get("decided_at")
    require(
        isinstance(source_decided_at, str) and RFC3339_UTC_Z.fullmatch(source_decided_at) is not None,
        "source authorization decided_at must be RFC3339 UTC-Z",
    )

    authorization_id = safe_ref(authorization.get("offer_preparation_authorization_id"), "offer_preparation_authorization_id")
    verification_ref = safe_ref(authorization.get("official_source_verification_ref"), "official_source_verification_ref")
    org = safe_ref(authorization.get("organization_key"), "organization_key")
    prospect = safe_ref(authorization.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(authorization.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(authorization.get("selected_service_id"), "selected_service_id")
    return (org, prospect, opportunity, service), authorization_id, verification_ref, projection["area_code"]


def validate_generation_request(
    request: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str]:
    require(isinstance(request, dict), "draft generation request must be an object")
    assert_safe_generation_input(request)
    require(set(request) == GENERATION_FIELDS, "draft generation request fields drift")
    source_authorization_id = safe_ref(
        request.get("source_offer_preparation_authorization_id"),
        "source_offer_preparation_authorization_id",
    )
    org = safe_ref(request.get("organization_key"), "organization_key")
    prospect = safe_ref(request.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(request.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(request.get("selected_service_id"), "selected_service_id")
    scope_area = request.get("commercial_scope_area")
    require(scope_area == contract["source_authorization"]["required_scope_area"], "draft commercial scope area drift")
    verification_ref = safe_ref(request.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = request.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source_as_of must be RFC3339 UTC-Z",
    )
    generation_mode = request.get("generation_mode")
    require(generation_mode in contract["generation"]["allowed_generation_modes"], "draft generation mode escaped allowlist")
    return (org, prospect, opportunity, service), source_authorization_id, scope_area, verification_ref, source_as_of, generation_mode


def build_internal_offer_draft(
    authorization: dict[str, Any],
    request: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_AUTHORIZATION_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_authorization_id, source_verification_ref, source_scope = validate_source_authorization(
        authorization, contract
    )
    request_identity, request_authorization_id, request_scope, request_verification_ref, source_as_of, generation_mode = (
        validate_generation_request(request, contract)
    )
    require(request_identity == source_identity, "draft generation identity mismatch")
    require(request_authorization_id == source_authorization_id, "draft generation source authorization mismatch")
    require(request_scope == source_scope, "draft generation commercial scope mismatch")
    require(request_verification_ref == source_verification_ref, "draft generation source binding mismatch")

    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_authorization_id, org, prospect, opportunity, service,
        request_scope, source_verification_ref, source_as_of, generation_mode,
    ))
    draft_id = "OFFDRAFT-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    generation = contract["generation"]
    output = contract["output"]
    draft_sections = [
        {
            "section_code": "CONTEXT",
            "text": (
                f"Draft intern pentru organizația {org}, în contextul oportunității {opportunity}, "
                f"limitat la serviciul selectat {service}."
            ),
        },
        {
            "section_code": "BOUNDARY",
            "text": (
                "Acest draft nu confirmă eligibilitatea și nu include preț, buget, termen, indicatori, "
                "obligații ori concluzii juridice sau financiare."
            ),
        },
        {
            "section_code": "REVIEW",
            "text": (
                "Orice afirmație materială trebuie reverificată în sursa oficială înainte de utilizare; "
                "draftul necesită review uman separat înainte de orice pas comercial ulterior."
            ),
        },
    ]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "internal_offer_draft_id": draft_id,
        "record_state": output["record_state"],
        "source_offer_preparation_contract_id": contract["source_authorization"]["contract_id"],
        "source_offer_preparation_authorization_id": source_authorization_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": request_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "generation_mode": generation_mode,
        "draft_state": generation["draft_state"],
        "content_scope": generation["content_scope"],
        "draft_sections": draft_sections,
        "next_gate_hint": generation["next_gate_hint"],
        "draft_review_required": True,
        "draft_semantics": "INTERNAL_SOURCE_BOUND_TEMPLATE_NOT_APPROVED_OFFER_PRICING_ELIGIBILITY_OR_OUTREACH",
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "internal_draft_generated": True,
        "internal_draft_content_included": True,
        "public_offer_content_included": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "source_bound": True,
        "draft_approval_granted": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "draft_persistence_allowed": False,
        "production_offer_generation_allowed": False,
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
        "public_offer_content_included", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "draft_approval_granted", "target_state_committed",
        "persistence_executed", "draft_persistence_allowed", "production_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"internal draft {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"internal draft {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder internal source-bound offer-draft generation gate")
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_AUTHORIZATION_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_internal_offer_draft(
        load_json(args.authorization),
        load_json(args.request),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
