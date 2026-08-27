#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_internal_final_offer_candidate_generation_contract.json"
DEFAULT_SOURCE_READINESS_CONTRACT = EUCONS / "leads" / "client_finder_offer_finalization_readiness_contract.json"

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
FORBIDDEN_CANDIDATE_INPUT_KEYS = {
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
SOURCE_READINESS_FIELDS = {
    "schema_version", "contract_id", "offer_finalization_readiness_id", "record_state",
    "source_content_review_contract_id", "source_offer_content_review_id", "source_internal_offer_draft_id",
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id",
    "commercial_scope_area", "official_source_reverified", "official_source_verification_ref", "source_as_of",
    "finalization_readiness_outcome", "finalization_readiness_state", "authorization_scope",
    "next_gate_authorization_granted", "next_gate_hint", "final_offer_generation_gate_required",
    "finalization_semantics", "decision_receipt", "eligibility_state", "maximum_next_state",
    "offer_approval_granted", "final_offer_approval_granted", "final_offer_generation_authorization_granted",
    "content_mutation_allowed", "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed", "offer_engine_invocation_allowed",
    "pricing_decision_allowed", "crm_context_materialization_allowed", "human_review_required",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
}
GENERATION_FIELDS = {
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


def assert_no_forbidden_candidate_payload(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    forbidden = FORBIDDEN_CANDIDATE_INPUT_KEYS & keys
    require(not forbidden, f"forbidden material/candidate field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "internal final-offer candidate schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-INTERNAL-FINAL-OFFER-CANDIDATE-GENERATION-001",
        "internal final-offer candidate contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "internal final-offer candidate contract is not canonical")
    require(contract.get("source_readiness") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-FINALIZATION-READINESS-001",
        "record_state": "CLIENT_FINDER_OFFER_FINALIZATION_READINESS_ENVELOPE",
        "required_finalization_readiness_outcome": "FINALIZATION_READY_INTERNAL_ONLY",
        "required_finalization_readiness_state": "FINALIZATION_READY_INTERNAL_ONLY",
        "required_authorization_scope": "NEXT_GATE_ONLY",
        "required_next_gate_authorization_granted": True,
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_GENERATION_GATE_REQUIRED",
        "required_final_offer_generation_gate_required": True,
        "required_official_source_reverified": True,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source finalization readiness policy drift")
    require(contract.get("generation") == {
        "allowed_generation_modes": ["DETERMINISTIC_INTERNAL_CANDIDATE_ONLY"],
        "source_as_of_format": "RFC3339_UTC_Z",
        "candidate_state": "INTERNAL_FINAL_OFFER_CANDIDATE_GENERATED_REVIEW_REQUIRED",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_CANDIDATE_REVIEW_GATE_REQUIRED",
        "content_scope": "INTERNAL_SOURCE_BOUND_CANDIDATE_SKELETON_ONLY",
    }, "internal final-offer candidate generation policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "internal final-offer candidate boundary drift")
    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_INTERNAL_FINAL_OFFER_CANDIDATE_ENVELOPE",
        "internal final-offer candidate output-state drift",
    )
    for field in (
        "internal_final_offer_candidate_generated", "candidate_content_included", "source_bound",
        "candidate_review_required", "human_review_required",
    ):
        require(output.get(field) is True, f"{field} must remain enabled")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "candidate_approval_granted", "target_state_committed",
        "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"internal final-offer candidate safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_readiness"]
    require(source_contract.get("id") == source["contract_id"], "source finalization readiness contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source finalization readiness contract is not canonical")
    require((source_contract.get("output") or {}).get("record_state") == source["record_state"], "source readiness output-state drift")
    readiness = source_contract.get("readiness") or {}
    require(
        readiness.get("outcome_state_map", {}).get(source["required_finalization_readiness_outcome"])
        == source["required_finalization_readiness_state"],
        "source readiness outcome-state drift",
    )
    require(readiness.get("authorization_scope") == source["required_authorization_scope"], "source readiness authorization scope drift")
    require(
        readiness.get("outcome_next_gate_map", {}).get(source["required_finalization_readiness_outcome"])
        == source["required_next_gate_hint"],
        "source readiness next-gate drift",
    )
    require(
        readiness.get("outcome_next_gate_authorization_map", {}).get(source["required_finalization_readiness_outcome"])
        is source["required_next_gate_authorization_granted"],
        "source readiness next-gate authorization drift",
    )
    source_review = source_contract.get("source_review") or {}
    require(
        source_review.get("required_official_source_reverified") is source["required_official_source_reverified"],
        "source readiness official-source prerequisite failed open",
    )
    require(
        source_review.get("required_commercial_scope_area") == source["required_commercial_scope_area"],
        "source readiness scope prerequisite drift",
    )
    output = source_contract.get("output") or {}
    require(output.get("human_review_required") is True, "source readiness human-review boundary failed open")
    for field in (
        "offer_approval_granted", "final_offer_approval_granted",
        "final_offer_generation_authorization_granted", "content_mutation_allowed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"source readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"source readiness {flag} failed open")


def validate_source_readiness(
    readiness: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str]:
    require(isinstance(readiness, dict), "offer finalization readiness envelope must be an object")
    assert_no_person_level_fields(readiness, "source finalization readiness envelope")
    assert_no_forbidden_candidate_payload(readiness, "source finalization readiness envelope")
    require(set(readiness) == SOURCE_READINESS_FIELDS, "source finalization readiness envelope fields drift")
    source = contract["source_readiness"]
    boundaries = contract["required_boundaries"]
    require(readiness.get("schema_version") == 1, "source finalization readiness schema drift")
    require(readiness.get("contract_id") == source["contract_id"], "source finalization readiness contract id mismatch")
    require(readiness.get("record_state") == source["record_state"], "source finalization readiness record state mismatch")
    require(
        readiness.get("finalization_readiness_outcome") == source["required_finalization_readiness_outcome"],
        "source finalization readiness is not ready internal only",
    )
    require(
        readiness.get("finalization_readiness_state") == source["required_finalization_readiness_state"],
        "source finalization readiness state mismatch",
    )
    require(readiness.get("authorization_scope") == source["required_authorization_scope"], "source readiness authorization scope mismatch")
    require(
        readiness.get("next_gate_authorization_granted") is source["required_next_gate_authorization_granted"],
        "source readiness next-gate authorization missing",
    )
    require(readiness.get("next_gate_hint") == source["required_next_gate_hint"], "source generation gate hint mismatch")
    require(
        readiness.get("final_offer_generation_gate_required") is source["required_final_offer_generation_gate_required"],
        "source generation gate requirement mismatch",
    )
    require(
        readiness.get("official_source_reverified") is source["required_official_source_reverified"],
        "source official source is not reverified",
    )
    require(readiness.get("commercial_scope_area") == source["required_commercial_scope_area"], "source commercial scope drift")
    require(
        readiness.get("finalization_semantics")
        == "INTERNAL_NEXT_GATE_READINESS_ONLY_NOT_FINAL_OFFER_GENERATION_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "source finalization semantics drift",
    )
    require(readiness.get("eligibility_state") == boundaries["eligibility_state"], "source readiness eligibility drift")
    require(readiness.get("maximum_next_state") == boundaries["maximum_next_state"], "source readiness research boundary drift")
    require(readiness.get("human_review_required") is True, "source readiness human review failed closed")
    for field in (
        "offer_approval_granted", "final_offer_approval_granted",
        "final_offer_generation_authorization_granted", "content_mutation_allowed",
        "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
        "target_state_committed", "persistence_executed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(readiness.get(field) is False, f"source readiness {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(readiness.get(flag) is False, f"source readiness {flag} failed open")
    receipt = readiness.get("decision_receipt")
    require(
        isinstance(receipt, dict) and set(receipt) == {"decision_source", "reviewer_ref", "decided_at"},
        "source readiness decision receipt drift",
    )
    require(receipt.get("decision_source") == "HUMAN", "source readiness receipt is not human")
    safe_ref(receipt.get("reviewer_ref"), "source readiness reviewer_ref")
    decided_at = receipt.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "source readiness decided_at must be RFC3339 UTC-Z",
    )
    readiness_id = safe_ref(readiness.get("offer_finalization_readiness_id"), "offer_finalization_readiness_id")
    content_review_id = safe_ref(readiness.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(readiness.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    safe_ref(readiness.get("source_content_review_contract_id"), "source_content_review_contract_id")
    org = safe_ref(readiness.get("organization_key"), "organization_key")
    prospect = safe_ref(readiness.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(readiness.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(readiness.get("selected_service_id"), "selected_service_id")
    verification_ref = safe_ref(readiness.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = readiness.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source readiness source_as_of must be RFC3339 UTC-Z",
    )
    return (org, prospect, opportunity, service), readiness_id, content_review_id, draft_id, verification_ref, source_as_of


def validate_generation_request(
    request: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str, str, str]:
    require(isinstance(request, dict), "internal final-offer candidate generation request must be an object")
    assert_no_person_level_fields(request, "candidate generation request")
    assert_no_forbidden_candidate_payload(request, "candidate generation request")
    require(set(request) == GENERATION_FIELDS, "candidate generation request fields drift")
    readiness_id = safe_ref(request.get("source_offer_finalization_readiness_id"), "source_offer_finalization_readiness_id")
    content_review_id = safe_ref(request.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(request.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    org = safe_ref(request.get("organization_key"), "organization_key")
    prospect = safe_ref(request.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(request.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(request.get("selected_service_id"), "selected_service_id")
    scope_area = request.get("commercial_scope_area")
    require(scope_area == contract["source_readiness"]["required_commercial_scope_area"], "candidate commercial scope drift")
    verification_ref = safe_ref(request.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = request.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "candidate source_as_of must be RFC3339 UTC-Z",
    )
    generation_mode = request.get("generation_mode")
    require(generation_mode in contract["generation"]["allowed_generation_modes"], "candidate generation mode escaped allowlist")
    return (
        (org, prospect, opportunity, service), readiness_id, content_review_id, draft_id,
        scope_area, verification_ref, source_as_of, generation_mode,
    )


def build_internal_final_offer_candidate(
    readiness: dict[str, Any],
    request: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_READINESS_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_readiness_id, source_content_review_id, source_draft_id, source_verification_ref, source_as_of = (
        validate_source_readiness(readiness, contract)
    )
    (
        request_identity, request_readiness_id, request_content_review_id, request_draft_id,
        request_scope, request_verification_ref, request_source_as_of, generation_mode,
    ) = validate_generation_request(request, contract)
    require(request_identity == source_identity, "candidate generation identity mismatch")
    require(request_readiness_id == source_readiness_id, "candidate generation source readiness mismatch")
    require(request_content_review_id == source_content_review_id, "candidate generation content review mismatch")
    require(request_draft_id == source_draft_id, "candidate generation draft mismatch")
    require(request_scope == readiness["commercial_scope_area"], "candidate generation commercial scope mismatch")
    require(request_verification_ref == source_verification_ref, "candidate generation source verification mismatch")
    require(request_source_as_of == source_as_of, "candidate generation source_as_of mismatch")

    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_readiness_id, source_content_review_id, source_draft_id, org, prospect, opportunity, service,
        request_scope, source_verification_ref, source_as_of, generation_mode,
    ))
    candidate_id = "OFFCAND-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    generation = contract["generation"]
    output = contract["output"]
    candidate_sections = [
        {
            "section_code": "CONTEXT",
            "text": (
                f"Candidat intern de ofertă pentru organizația {org}, în contextul oportunității {opportunity}, "
                f"limitat la serviciul selectat {service}."
            ),
        },
        {
            "section_code": "SOURCE",
            "text": (
                f"Conținutul rămâne legat de referința de verificare oficială {source_verification_ref} "
                f"și de snapshot-ul sursei {source_as_of}."
            ),
        },
        {
            "section_code": "BOUNDARY",
            "text": (
                "Acest candidat intern nu este ofertă finală sau aprobată și nu include preț, buget, termen, indicatori, "
                "obligații ori concluzii juridice sau financiare."
            ),
        },
        {
            "section_code": "REVIEW",
            "text": (
                "Orice afirmație materială trebuie reverificată în sursa oficială; candidatul necesită review uman separat "
                "înainte de orice finalizare, persistență sau acțiune comercială."
            ),
        },
    ]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "internal_final_offer_candidate_id": candidate_id,
        "record_state": output["record_state"],
        "source_finalization_readiness_contract_id": contract["source_readiness"]["contract_id"],
        "source_offer_finalization_readiness_id": source_readiness_id,
        "source_offer_content_review_id": source_content_review_id,
        "source_internal_offer_draft_id": source_draft_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "commercial_scope_area": request_scope,
        "official_source_reverified": True,
        "official_source_verification_ref": source_verification_ref,
        "source_as_of": source_as_of,
        "generation_mode": generation_mode,
        "candidate_state": generation["candidate_state"],
        "content_scope": generation["content_scope"],
        "candidate_sections": candidate_sections,
        "next_gate_hint": generation["next_gate_hint"],
        "candidate_review_required": True,
        "candidate_semantics": "INTERNAL_SOURCE_BOUND_CANDIDATE_NOT_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "internal_final_offer_candidate_generated": True,
        "candidate_content_included": True,
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "source_bound": True,
        "candidate_approval_granted": False,
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
        "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "candidate_approval_granted", "target_state_committed",
        "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"internal final-offer candidate {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"internal final-offer candidate {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder internal source-bound final-offer candidate generation gate")
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_READINESS_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_internal_final_offer_candidate(
        load_json(args.readiness),
        load_json(args.request),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
