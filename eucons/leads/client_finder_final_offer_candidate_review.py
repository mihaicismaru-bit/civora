#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_final_offer_candidate_review_contract.json"
DEFAULT_SOURCE_CANDIDATE_CONTRACT = EUCONS / "leads" / "client_finder_internal_final_offer_candidate_generation_contract.json"

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
FORBIDDEN_REVIEW_PAYLOAD_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "deadline", "budget", "indicator", "obligation",
    "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "price", "amount_minor", "pricing_rule", "discount", "fee", "quote",
    "payment_terms", "terms", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body", "offer_body", "proposal_text", "offer_text",
    "subject", "headline", "cta", "freeform_content", "material_claim", "claim_text", "edit_text",
    "final_offer", "final_offer_body", "final_offer_text", "attachment",
}
SOURCE_CANDIDATE_FIELDS = {
    "schema_version", "contract_id", "internal_final_offer_candidate_id", "record_state",
    "source_finalization_readiness_contract_id", "source_offer_finalization_readiness_id",
    "source_offer_content_review_id", "source_internal_offer_draft_id",
    "organization_key", "prospect_id", "selected_opportunity_id", "selected_service_id",
    "commercial_scope_area", "official_source_reverified", "official_source_verification_ref",
    "source_as_of", "generation_mode", "candidate_state", "content_scope", "candidate_sections",
    "next_gate_hint", "candidate_review_required", "candidate_semantics", "eligibility_state",
    "maximum_next_state", "internal_final_offer_candidate_generated", "candidate_content_included",
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "source_bound", "candidate_approval_granted",
    "target_state_committed", "persistence_executed", "candidate_persistence_allowed",
    "draft_persistence_allowed", "offer_persistence_allowed", "production_offer_generation_allowed",
    "final_offer_generation_allowed", "offer_engine_invocation_allowed", "pricing_decision_allowed",
    "crm_context_materialization_allowed", "human_review_required", "external_contact_enabled",
    "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
}
DECISION_FIELDS = {
    "internal_final_offer_candidate_id",
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
    "candidate_review_outcome",
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


def assert_no_forbidden_review_payload(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    forbidden = FORBIDDEN_REVIEW_PAYLOAD_KEYS & keys
    require(not forbidden, f"forbidden material/freeform field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def expected_candidate_sections(
    org: str,
    opportunity: str,
    service: str,
    verification_ref: str,
    source_as_of: str,
) -> list[dict[str, str]]:
    return [
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
                f"Conținutul rămâne legat de referința de verificare oficială {verification_ref} "
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


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "final-offer candidate review schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-CANDIDATE-REVIEW-001",
        "final-offer candidate review contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "final-offer candidate review contract is not canonical")
    require(contract.get("source_candidate") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-INTERNAL-FINAL-OFFER-CANDIDATE-GENERATION-001",
        "record_state": "CLIENT_FINDER_INTERNAL_FINAL_OFFER_CANDIDATE_ENVELOPE",
        "required_candidate_state": "INTERNAL_FINAL_OFFER_CANDIDATE_GENERATED_REVIEW_REQUIRED",
        "required_next_gate_hint": "SEPARATE_FINAL_OFFER_CANDIDATE_REVIEW_GATE_REQUIRED",
        "required_content_scope": "INTERNAL_SOURCE_BOUND_CANDIDATE_SKELETON_ONLY",
        "required_generation_mode": "DETERMINISTIC_INTERNAL_CANDIDATE_ONLY",
        "required_official_source_reverified": True,
        "required_source_bound": True,
        "required_candidate_review_required": True,
        "required_candidate_approval_granted": False,
        "required_commercial_scope_area": "SELECTED_SERVICE_ONLY",
    }, "source candidate policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "final-offer candidate review boundary drift")

    review = contract.get("review") or {}
    outcomes = ["CHANGES_REQUIRED", "REJECTED", "APPROVED_INTERNAL_ONLY"]
    require(review.get("decision_source") == "HUMAN", "candidate review decision source failed open")
    require(review.get("allowed_candidate_review_outcomes") == outcomes, "candidate review outcome allowlist drift")
    require(review.get("outcome_state_map") == {
        "CHANGES_REQUIRED": "INTERNAL_FINAL_OFFER_CANDIDATE_CHANGES_REQUIRED",
        "REJECTED": "INTERNAL_FINAL_OFFER_CANDIDATE_REJECTED",
        "APPROVED_INTERNAL_ONLY": "INTERNAL_FINAL_OFFER_CANDIDATE_APPROVED_INTERNAL_ONLY",
    }, "candidate review state mapping drift")
    require(review.get("outcome_next_gate_map") == {
        "CHANGES_REQUIRED": None,
        "REJECTED": None,
        "APPROVED_INTERNAL_ONLY": "SEPARATE_FINAL_OFFER_RELEASE_READINESS_GATE_REQUIRED",
    }, "candidate review next-gate mapping drift")
    require(review.get("decided_at_format") == "RFC3339_UTC_Z", "candidate review timestamp policy drift")

    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_FINAL_OFFER_CANDIDATE_REVIEW_ENVELOPE",
        "candidate review output-state drift",
    )
    require(output.get("human_review_required") is True, "candidate review human-review boundary failed open")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "final_offer_release_authorization_granted",
        "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "target_state_committed", "persistence_executed",
        "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"candidate review safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_candidate"]
    require(source_contract.get("id") == source["contract_id"], "source candidate contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source candidate contract is not canonical")
    generation = source_contract.get("generation") or {}
    require(
        generation.get("allowed_generation_modes") == [source["required_generation_mode"]],
        "source candidate generation mode drift",
    )
    require(generation.get("candidate_state") == source["required_candidate_state"], "source candidate state policy drift")
    require(generation.get("next_gate_hint") == source["required_next_gate_hint"], "source candidate next-gate policy drift")
    require(generation.get("content_scope") == source["required_content_scope"], "source candidate content scope policy drift")
    source_output = source_contract.get("output") or {}
    require(source_output.get("record_state") == source["record_state"], "source candidate output-state drift")
    for field in (
        "internal_final_offer_candidate_generated", "candidate_content_included", "source_bound",
        "candidate_review_required", "human_review_required",
    ):
        require(source_output.get(field) is True, f"source candidate {field} must remain enabled")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "candidate_approval_granted", "target_state_committed",
        "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(source_output.get(field) is False, f"source candidate {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source candidate {flag} failed open")


def validate_source_candidate(
    candidate: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str], str, str, str, str]:
    require(isinstance(candidate, dict), "internal final-offer candidate envelope must be an object")
    assert_no_person_level_fields(candidate, "source candidate envelope")
    assert_no_forbidden_review_payload(candidate, "source candidate envelope")
    require(set(candidate) == SOURCE_CANDIDATE_FIELDS, "source candidate envelope fields drift")
    source = contract["source_candidate"]
    boundaries = contract["required_boundaries"]
    require(candidate.get("schema_version") == 1, "source candidate schema drift")
    require(candidate.get("contract_id") == source["contract_id"], "source candidate contract id mismatch")
    require(candidate.get("record_state") == source["record_state"], "source candidate record state mismatch")
    require(candidate.get("candidate_state") == source["required_candidate_state"], "source candidate is not review-ready")
    require(candidate.get("next_gate_hint") == source["required_next_gate_hint"], "source candidate review-gate hint mismatch")
    require(candidate.get("content_scope") == source["required_content_scope"], "source candidate content scope mismatch")
    require(candidate.get("generation_mode") == source["required_generation_mode"], "source candidate generation mode mismatch")
    require(
        candidate.get("official_source_reverified") is source["required_official_source_reverified"],
        "source candidate official source is not reverified",
    )
    require(candidate.get("source_bound") is source["required_source_bound"], "source candidate is not source-bound")
    require(
        candidate.get("candidate_review_required") is source["required_candidate_review_required"],
        "source candidate no longer requires review",
    )
    require(
        candidate.get("candidate_approval_granted") is source["required_candidate_approval_granted"],
        "source candidate approval boundary drift",
    )
    require(
        candidate.get("commercial_scope_area") == source["required_commercial_scope_area"],
        "source candidate commercial scope drift",
    )
    require(
        candidate.get("candidate_semantics")
        == "INTERNAL_SOURCE_BOUND_CANDIDATE_NOT_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "source candidate semantics drift",
    )
    require(candidate.get("eligibility_state") == boundaries["eligibility_state"], "source candidate eligibility drift")
    require(candidate.get("maximum_next_state") == boundaries["maximum_next_state"], "source candidate research boundary drift")
    for field in (
        "internal_final_offer_candidate_generated", "candidate_content_included", "source_bound",
        "candidate_review_required", "human_review_required",
    ):
        require(candidate.get(field) is True, f"source candidate {field} failed closed")
    for field in (
        "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
        "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "candidate_approval_granted", "target_state_committed",
        "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
        "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(candidate.get(field) is False, f"source candidate {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(candidate.get(flag) is False, f"source candidate {flag} failed open")

    candidate_id = safe_ref(candidate.get("internal_final_offer_candidate_id"), "internal_final_offer_candidate_id")
    readiness_id = safe_ref(candidate.get("source_offer_finalization_readiness_id"), "source_offer_finalization_readiness_id")
    content_review_id = safe_ref(candidate.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(candidate.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    safe_ref(candidate.get("source_finalization_readiness_contract_id"), "source_finalization_readiness_contract_id")
    org = safe_ref(candidate.get("organization_key"), "organization_key")
    prospect = safe_ref(candidate.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(candidate.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(candidate.get("selected_service_id"), "selected_service_id")
    verification_ref = safe_ref(candidate.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = candidate.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "source candidate source_as_of must be RFC3339 UTC-Z",
    )
    require(
        candidate.get("candidate_sections")
        == expected_candidate_sections(org, opportunity, service, verification_ref, source_as_of),
        "source candidate sections drifted from deterministic candidate",
    )
    return (
        (org, prospect, opportunity, service),
        (readiness_id, content_review_id, draft_id, candidate_id),
        candidate["commercial_scope_area"],
        verification_ref,
        source_as_of,
        candidate_id,
    )


def validate_review_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], tuple[str, str, str, str], str, str, str, str, str, str]:
    require(isinstance(decision, dict), "final-offer candidate review decision must be an object")
    assert_no_person_level_fields(decision, "final-offer candidate review decision")
    assert_no_forbidden_review_payload(decision, "final-offer candidate review decision")
    require(set(decision) == DECISION_FIELDS, "final-offer candidate review decision fields drift")
    policy = contract["review"]
    require(decision.get("decision_source") == policy["decision_source"], "candidate review decision source must be HUMAN")
    candidate_id = safe_ref(decision.get("internal_final_offer_candidate_id"), "internal_final_offer_candidate_id")
    readiness_id = safe_ref(decision.get("source_offer_finalization_readiness_id"), "source_offer_finalization_readiness_id")
    content_review_id = safe_ref(decision.get("source_offer_content_review_id"), "source_offer_content_review_id")
    draft_id = safe_ref(decision.get("source_internal_offer_draft_id"), "source_internal_offer_draft_id")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    scope_area = decision.get("commercial_scope_area")
    require(scope_area == contract["source_candidate"]["required_commercial_scope_area"], "candidate review commercial scope drift")
    verification_ref = safe_ref(decision.get("official_source_verification_ref"), "official_source_verification_ref")
    source_as_of = decision.get("source_as_of")
    require(
        isinstance(source_as_of, str) and RFC3339_UTC_Z.fullmatch(source_as_of) is not None,
        "candidate review source_as_of must be RFC3339 UTC-Z",
    )
    outcome = decision.get("candidate_review_outcome")
    require(outcome in policy["allowed_candidate_review_outcomes"], "candidate review outcome escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    return (
        (org, prospect, opportunity, service),
        (readiness_id, content_review_id, draft_id, candidate_id),
        scope_area,
        verification_ref,
        source_as_of,
        outcome,
        reviewer_ref,
        decided_at,
    )


def build_final_offer_candidate_review(
    candidate: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_CANDIDATE_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_lineage, source_scope, source_verification_ref, source_as_of, source_candidate_id = (
        validate_source_candidate(candidate, contract)
    )
    (
        decision_identity, decision_lineage, decision_scope, decision_verification_ref,
        decision_source_as_of, outcome, reviewer_ref, decided_at,
    ) = validate_review_decision(decision, contract)
    require(decision_identity == source_identity, "final-offer candidate review identity mismatch")
    require(decision_lineage == source_lineage, "final-offer candidate review lineage mismatch")
    require(decision_scope == source_scope, "final-offer candidate review scope mismatch")
    require(decision_verification_ref == source_verification_ref, "final-offer candidate review source verification mismatch")
    require(decision_source_as_of == source_as_of, "final-offer candidate review source_as_of mismatch")

    policy = contract["review"]
    review_state = policy["outcome_state_map"][outcome]
    next_gate = policy["outcome_next_gate_map"][outcome]
    org, prospect, opportunity, service = source_identity
    readiness_id, content_review_id, draft_id, _ = source_lineage
    basis = "|".join((
        source_candidate_id, readiness_id, content_review_id, draft_id, org, prospect, opportunity, service,
        source_scope, source_verification_ref, source_as_of, outcome, reviewer_ref, decided_at,
    ))
    review_id = "OFFCANDREVIEW-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    approved_internal_only = outcome == "APPROVED_INTERNAL_ONLY"
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "final_offer_candidate_review_id": review_id,
        "record_state": output["record_state"],
        "source_candidate_contract_id": contract["source_candidate"]["contract_id"],
        "source_internal_final_offer_candidate_id": source_candidate_id,
        "source_offer_finalization_readiness_id": readiness_id,
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
        "candidate_review_outcome": outcome,
        "candidate_review_state": review_state,
        "internal_candidate_review_approved": approved_internal_only,
        "next_gate_hint": next_gate,
        "final_offer_release_readiness_gate_required": next_gate is not None,
        "candidate_review_semantics": "INTERNAL_CANDIDATE_REVIEW_ONLY_NOT_FINAL_OFFER_OR_RELEASE_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
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
        "candidate_approval_granted": False,
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
        "final_offer_approval_granted", "final_offer_release_authorization_granted",
        "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
        "new_financial_claims_included", "target_state_committed", "persistence_executed",
        "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
        "production_offer_generation_allowed", "final_offer_generation_allowed",
        "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"final-offer candidate review {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"final-offer candidate review {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human-only internal final-offer candidate review gate")
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_CANDIDATE_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_final_offer_candidate_review(
        load_json(args.candidate),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
