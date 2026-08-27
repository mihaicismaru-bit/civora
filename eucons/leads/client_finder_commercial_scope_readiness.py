#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_commercial_scope_readiness_contract.json"
DEFAULT_SOURCE_REVIEW_CONTRACT = EUCONS / "leads" / "client_finder_research_evaluation_review_contract.json"

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
FORBIDDEN_RAW_OR_COMMERCIAL_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "source_age_verdict", "source_quality_verdict", "price", "amount_minor", "pricing_rule",
    "discount", "fee", "quote", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body",
}
DECISION_FIELDS = {
    "source_review_id", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "commercial_scope_area", "readiness_outcome",
    "decision_source", "reviewer_ref", "decided_at",
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


def assert_safe_input(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    forbidden = FORBIDDEN_RAW_OR_COMMERCIAL_KEYS & keys
    require(not forbidden, f"forbidden raw/commercial/inference field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "commercial scope readiness schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-COMMERCIAL-SCOPE-READINESS-001",
        "commercial scope readiness contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "commercial scope readiness contract is not canonical")
    require(contract.get("source_review") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-RESEARCH-EVALUATION-REVIEW-001",
        "record_state": "CLIENT_FINDER_RESEARCH_EVALUATION_REVIEW_ENVELOPE",
        "required_research_outcome": "RESEARCH_FIT_CONFIRMED",
        "required_research_review_state": "RESEARCH_COMPLETE_COMMERCIAL_GATE_REQUIRED",
        "required_next_gate_hint": "SEPARATE_COMMERCIAL_SCOPE_GATE_REQUIRED",
        "required_official_source_reverified": True,
    }, "commercial scope source-review policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "commercial scope readiness boundary drift")
    require(contract.get("commercial_scope") == {
        "allowed_area_codes": ["SELECTED_SERVICE_ONLY"],
        "selected_service_must_match_source_review": True,
        "projection_is_non_persistent": True,
    }, "commercial scope projection policy drift")
    decision = contract.get("decision") or {}
    outcomes = [
        "MORE_COMMERCIAL_RESEARCH_REQUIRED",
        "NO_COMMERCIAL_SCOPE",
        "COMMERCIAL_SCOPE_READY",
    ]
    require(decision.get("decision_source") == "HUMAN", "commercial scope decision source failed open")
    require(decision.get("allowed_readiness_outcomes") == outcomes, "commercial scope outcome allowlist drift")
    require(decision.get("outcome_state_map") == {
        "MORE_COMMERCIAL_RESEARCH_REQUIRED": "COMMERCIAL_SCOPE_RESEARCH_REQUIRED",
        "NO_COMMERCIAL_SCOPE": "COMMERCIAL_SCOPE_CLOSED_NO_FIT",
        "COMMERCIAL_SCOPE_READY": "COMMERCIAL_SCOPE_READY_FOR_SEPARATE_OFFER_GATE",
    }, "commercial scope outcome-state mapping drift")
    require(decision.get("outcome_next_gate_map") == {
        "MORE_COMMERCIAL_RESEARCH_REQUIRED": None,
        "NO_COMMERCIAL_SCOPE": None,
        "COMMERCIAL_SCOPE_READY": "SEPARATE_OFFER_AUTHORIZATION_GATE_REQUIRED",
    }, "commercial scope next-gate mapping drift")
    require(decision.get("decided_at_format") == "RFC3339_UTC_Z", "commercial scope timestamp policy drift")
    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_COMMERCIAL_SCOPE_READINESS_ENVELOPE",
        "commercial scope output-state drift",
    )
    for field in (
        "target_state_committed",
        "persistence_executed",
        "commercial_scope_persistence_allowed",
        "offer_authorization_granted",
        "offer_engine_invocation_allowed",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    require(output.get("human_review_required") is True, "human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"commercial scope safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_review"]
    require(source_contract.get("id") == source["contract_id"], "source review contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source review contract is not canonical")
    require(
        (source_contract.get("output") or {}).get("record_state") == source["record_state"],
        "source review output state drift",
    )
    source_decision = source_contract.get("decision") or {}
    require(
        source["required_research_outcome"] in source_decision.get("allowed_research_outcomes", []),
        "source review no longer allows research-fit confirmation",
    )
    require(
        source_decision.get("outcome_review_map", {}).get(source["required_research_outcome"])
        == source["required_research_review_state"],
        "source review research-fit state mapping drift",
    )
    require(
        source_decision.get("outcome_next_gate_map", {}).get(source["required_research_outcome"])
        == source["required_next_gate_hint"],
        "source review next-gate mapping drift",
    )
    source_boundaries = source_contract.get("required_boundaries") or {}
    for key, expected in contract["required_boundaries"].items():
        require(source_boundaries.get(key) == expected, f"source review boundary drift: {key}")
    source_output = source_contract.get("output") or {}
    for field in (
        "target_state_committed",
        "persistence_executed",
        "offer_engine_invocation_allowed",
        "commercial_scope_write_enabled",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(source_output.get(field) is False, f"source review {field} failed open")
    require(source_output.get("human_review_required") is True, "source review human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source review {flag} failed open")


def validate_source_review(
    review: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str]:
    require(isinstance(review, dict), "research evaluation review envelope must be an object")
    assert_safe_input(review, "research evaluation review envelope")
    source = contract["source_review"]
    boundaries = contract["required_boundaries"]
    require(review.get("contract_id") == source["contract_id"], "source review contract id mismatch")
    require(review.get("record_state") == source["record_state"], "source review record state mismatch")
    require(review.get("research_outcome") == source["required_research_outcome"], "research fit is not confirmed")
    require(
        review.get("research_review_state") == source["required_research_review_state"],
        "source review is not commercial-gate ready",
    )
    require(review.get("next_gate_hint") == source["required_next_gate_hint"], "source review next-gate hint mismatch")
    require(review.get("commercial_scope_gate_required") is True, "source review did not require commercial scope gate")
    require(
        review.get("official_source_reverified") is source["required_official_source_reverified"],
        "source review official-source reverification missing",
    )
    require(
        review.get("research_fit_semantics")
        == "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "source review research-fit semantics drift",
    )
    require(review.get("eligibility_state") == boundaries["eligibility_state"], "source review eligibility drift")
    require(review.get("maximum_next_state") == boundaries["maximum_next_state"], "source review research boundary drift")
    require(review.get("target_state_committed") is False, "source review target state was committed")
    require(review.get("persistence_executed") is False, "source review persistence was executed")
    require(review.get("offer_engine_invocation_allowed") is False, "source review enabled offer engine")
    require(review.get("commercial_scope_write_enabled") is False, "source review enabled commercial scope writes")
    require(review.get("pricing_decision_allowed") is False, "source review enabled pricing")
    require(
        review.get("crm_context_materialization_allowed") is False,
        "source review enabled CRM context materialization",
    )
    require(review.get("human_review_required") is True, "source review human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(review.get(flag) is False, f"source review {flag} failed open")

    receipt = review.get("decision_receipt")
    require(isinstance(receipt, dict), "source review decision receipt missing")
    require(receipt.get("decision_source") == "HUMAN", "source review decision was not human")
    safe_ref(receipt.get("reviewer_ref"), "source review reviewer_ref")
    source_decided_at = receipt.get("decided_at")
    require(
        isinstance(source_decided_at, str) and RFC3339_UTC_Z.fullmatch(source_decided_at) is not None,
        "source review decided_at must be RFC3339 UTC-Z",
    )

    review_id = safe_ref(review.get("review_id"), "source review review_id")
    org = safe_ref(review.get("organization_key"), "organization_key")
    prospect = safe_ref(review.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(review.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(review.get("selected_service_id"), "selected_service_id")
    evaluation_id = safe_ref(review.get("source_evaluation_id"), "source_evaluation_id")
    verification_ref = safe_ref(review.get("official_source_verification_ref"), "official_source_verification_ref")
    return (org, prospect, opportunity, service), review_id, evaluation_id, verification_ref


def validate_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str]:
    require(isinstance(decision, dict), "commercial scope readiness decision must be an object")
    assert_safe_input(decision, "commercial scope readiness decision")
    require(set(decision) == DECISION_FIELDS, "commercial scope readiness decision fields drift")
    policy = contract["decision"]
    require(decision.get("decision_source") == policy["decision_source"], "commercial scope decision source must be HUMAN")
    source_review_id = safe_ref(decision.get("source_review_id"), "source_review_id")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    scope_area = decision.get("commercial_scope_area")
    require(scope_area in contract["commercial_scope"]["allowed_area_codes"], "commercial scope area escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    outcome = decision.get("readiness_outcome")
    require(outcome in policy["allowed_readiness_outcomes"], "commercial scope outcome escaped allowlist")
    return (org, prospect, opportunity, service), source_review_id, scope_area, outcome, reviewer_ref, decided_at


def build_commercial_scope_readiness(
    review: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_REVIEW_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    source_identity, source_review_id, evaluation_id, verification_ref = validate_source_review(review, contract)
    decision_identity, decision_review_id, scope_area, outcome, reviewer_ref, decided_at = validate_decision(decision, contract)
    require(decision_identity == source_identity, "commercial scope decision identity mismatch")
    require(decision_review_id == source_review_id, "commercial scope decision source_review_id mismatch")
    require(
        decision_identity[3] == source_identity[3],
        "commercial scope selected service must match source review",
    )

    scope_state = contract["decision"]["outcome_state_map"][outcome]
    next_gate = contract["decision"]["outcome_next_gate_map"][outcome]
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_review_id, evaluation_id, org, prospect, opportunity, service,
        verification_ref, scope_area, outcome, reviewer_ref, decided_at,
    ))
    commercial_scope_review_id = "COMSCOPE-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "commercial_scope_review_id": commercial_scope_review_id,
        "record_state": output["record_state"],
        "source_review_contract_id": contract["source_review"]["contract_id"],
        "source_review_id": source_review_id,
        "source_evaluation_id": evaluation_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "official_source_reverified": True,
        "official_source_verification_ref": verification_ref,
        "research_outcome": contract["source_review"]["required_research_outcome"],
        "commercial_scope_projection": {
            "area_code": scope_area,
            "selected_service_id": service,
        },
        "readiness_outcome": outcome,
        "commercial_scope_state": scope_state,
        "next_gate_hint": next_gate,
        "offer_authorization_gate_required": next_gate is not None,
        "commercial_scope_semantics": "HUMAN_SCOPE_READINESS_NOT_OFFER_PRICING_ELIGIBILITY_OR_BUYING_INTENT",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "target_state_committed": False,
        "persistence_executed": False,
        "commercial_scope_persistence_allowed": False,
        "offer_authorization_granted": False,
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
    require(result["target_state_committed"] is False, "commercial scope review committed target state")
    require(result["persistence_executed"] is False, "commercial scope review persisted state")
    require(result["commercial_scope_persistence_allowed"] is False, "commercial scope review enabled persistence")
    require(result["offer_authorization_granted"] is False, "commercial scope review granted offer authorization")
    require(result["offer_engine_invocation_allowed"] is False, "commercial scope review enabled offer engine")
    require(result["pricing_decision_allowed"] is False, "commercial scope review enabled pricing")
    require(
        result["crm_context_materialization_allowed"] is False,
        "commercial scope review enabled CRM context materialization",
    )
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"commercial scope review {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human commercial-scope readiness gate")
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_REVIEW_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_commercial_scope_readiness(
        load_json(args.review),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
