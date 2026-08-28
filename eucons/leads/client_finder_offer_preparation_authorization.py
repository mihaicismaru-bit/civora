#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_offer_preparation_authorization_contract.json"
DEFAULT_SOURCE_READINESS_CONTRACT = EUCONS / "leads" / "client_finder_commercial_scope_readiness_contract.json"

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
FORBIDDEN_RAW_OR_OFFER_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "source_age_verdict", "source_quality_verdict", "price", "amount_minor", "pricing_rule",
    "discount", "fee", "quote", "offer_id", "proposal_id", "crm_state", "pipeline_state", "lead_id",
    "message_body", "email_body", "proposal_body", "offer_body", "proposal_text", "offer_text",
    "subject", "headline", "cta", "terms", "payment_terms",
}
DECISION_FIELDS = {
    "source_commercial_scope_review_id", "organization_key", "prospect_id",
    "selected_opportunity_id", "selected_service_id", "commercial_scope_area",
    "authorized_capability", "authorization_outcome", "decision_source",
    "reviewer_ref", "decided_at",
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
    forbidden = FORBIDDEN_RAW_OR_OFFER_KEYS & keys
    require(not forbidden, f"forbidden raw/offer/inference field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "offer preparation authorization schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-OFFER-PREPARATION-AUTHORIZATION-001",
        "offer preparation authorization contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "offer preparation authorization contract is not canonical")
    require(contract.get("source_readiness") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-COMMERCIAL-SCOPE-READINESS-001",
        "record_state": "CLIENT_FINDER_COMMERCIAL_SCOPE_READINESS_ENVELOPE",
        "required_readiness_outcome": "COMMERCIAL_SCOPE_READY",
        "required_commercial_scope_state": "COMMERCIAL_SCOPE_READY_FOR_SEPARATE_OFFER_GATE",
        "required_next_gate_hint": "SEPARATE_OFFER_AUTHORIZATION_GATE_REQUIRED",
        "required_offer_authorization_gate_required": True,
        "required_official_source_reverified": True,
        "required_scope_area": "SELECTED_SERVICE_ONLY",
    }, "offer preparation source-readiness policy drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "offer preparation authorization boundary drift")
    auth = contract.get("authorization") or {}
    outcomes = [
        "MORE_OFFER_PREPARATION_RESEARCH_REQUIRED",
        "OFFER_PREPARATION_NOT_AUTHORIZED",
        "OFFER_PREPARATION_AUTHORIZED",
    ]
    require(auth.get("decision_source") == "HUMAN", "offer preparation decision source failed open")
    require(auth.get("allowed_capabilities") == ["INTERNAL_DRAFT_PREPARATION_ONLY"], "authorization capability drift")
    require(auth.get("allowed_authorization_outcomes") == outcomes, "authorization outcome allowlist drift")
    require(auth.get("outcome_state_map") == {
        "MORE_OFFER_PREPARATION_RESEARCH_REQUIRED": "OFFER_PREPARATION_RESEARCH_REQUIRED",
        "OFFER_PREPARATION_NOT_AUTHORIZED": "OFFER_PREPARATION_CLOSED",
        "OFFER_PREPARATION_AUTHORIZED": "OFFER_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
    }, "authorization outcome-state mapping drift")
    require(auth.get("outcome_next_gate_map") == {
        "MORE_OFFER_PREPARATION_RESEARCH_REQUIRED": None,
        "OFFER_PREPARATION_NOT_AUTHORIZED": None,
        "OFFER_PREPARATION_AUTHORIZED": "SEPARATE_OFFER_DRAFT_GENERATION_GATE_REQUIRED",
    }, "authorization next-gate mapping drift")
    require(auth.get("decided_at_format") == "RFC3339_UTC_Z", "authorization timestamp policy drift")
    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_OFFER_PREPARATION_AUTHORIZATION_ENVELOPE",
        "offer preparation output-state drift",
    )
    require(
        output.get("offer_preparation_authorized_is_decision_derived") is True,
        "offer preparation authorization derivation drift",
    )
    for field in (
        "target_state_committed",
        "persistence_executed",
        "offer_preparation_persistence_allowed",
        "offer_authorization_granted",
        "offer_content_included",
        "pricing_included",
        "offer_draft_generation_allowed",
        "offer_generation_allowed",
        "offer_engine_invocation_allowed",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    require(output.get("human_review_required") is True, "human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"offer preparation safety rule failed open: {name}")


def validate_source_contract(source_contract: dict[str, Any], contract: dict[str, Any]) -> None:
    source = contract["source_readiness"]
    require(source_contract.get("id") == source["contract_id"], "source readiness contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source readiness contract is not canonical")
    require(
        (source_contract.get("output") or {}).get("record_state") == source["record_state"],
        "source readiness output state drift",
    )
    source_decision = source_contract.get("decision") or {}
    require(
        source["required_readiness_outcome"] in source_decision.get("allowed_readiness_outcomes", []),
        "source readiness no longer allows commercial scope ready",
    )
    require(
        source_decision.get("outcome_state_map", {}).get(source["required_readiness_outcome"])
        == source["required_commercial_scope_state"],
        "source readiness state mapping drift",
    )
    require(
        source_decision.get("outcome_next_gate_map", {}).get(source["required_readiness_outcome"])
        == source["required_next_gate_hint"],
        "source readiness next-gate mapping drift",
    )
    require(
        source["required_scope_area"] in (source_contract.get("commercial_scope") or {}).get("allowed_area_codes", []),
        "source readiness scope allowlist drift",
    )
    source_boundaries = source_contract.get("required_boundaries") or {}
    for key, expected in contract["required_boundaries"].items():
        require(source_boundaries.get(key) == expected, f"source readiness boundary drift: {key}")
    source_output = source_contract.get("output") or {}
    for field in (
        "target_state_committed",
        "persistence_executed",
        "commercial_scope_persistence_allowed",
        "offer_authorization_granted",
        "offer_engine_invocation_allowed",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(source_output.get(field) is False, f"source readiness {field} failed open")
    require(source_output.get("human_review_required") is True, "source readiness human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source readiness {flag} failed open")


def validate_source_readiness(
    readiness: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str]:
    require(isinstance(readiness, dict), "commercial scope readiness envelope must be an object")
    assert_safe_input(readiness, "commercial scope readiness envelope")
    source = contract["source_readiness"]
    boundaries = contract["required_boundaries"]
    require(readiness.get("contract_id") == source["contract_id"], "source readiness contract id mismatch")
    require(readiness.get("record_state") == source["record_state"], "source readiness record state mismatch")
    require(
        readiness.get("readiness_outcome") == source["required_readiness_outcome"],
        "commercial scope is not ready",
    )
    require(
        readiness.get("commercial_scope_state") == source["required_commercial_scope_state"],
        "commercial scope state is not offer-gate ready",
    )
    require(readiness.get("next_gate_hint") == source["required_next_gate_hint"], "source readiness next-gate hint mismatch")
    require(
        readiness.get("offer_authorization_gate_required") is source["required_offer_authorization_gate_required"],
        "source readiness did not require offer authorization gate",
    )
    require(
        readiness.get("official_source_reverified") is source["required_official_source_reverified"],
        "source readiness official-source reverification missing",
    )
    require(
        readiness.get("commercial_scope_semantics")
        == "HUMAN_SCOPE_READINESS_NOT_OFFER_PRICING_ELIGIBILITY_OR_BUYING_INTENT",
        "source readiness semantics drift",
    )
    projection = readiness.get("commercial_scope_projection")
    require(isinstance(projection, dict), "commercial scope projection missing")
    require(set(projection) == {"area_code", "selected_service_id"}, "commercial scope projection fields drift")
    require(projection.get("area_code") == source["required_scope_area"], "commercial scope area mismatch")
    require(
        projection.get("selected_service_id") == readiness.get("selected_service_id"),
        "commercial scope projection service mismatch",
    )
    require(readiness.get("eligibility_state") == boundaries["eligibility_state"], "source readiness eligibility drift")
    require(readiness.get("maximum_next_state") == boundaries["maximum_next_state"], "source readiness research boundary drift")
    require(readiness.get("target_state_committed") is False, "source readiness target state was committed")
    require(readiness.get("persistence_executed") is False, "source readiness persistence was executed")
    require(
        readiness.get("commercial_scope_persistence_allowed") is False,
        "source readiness enabled commercial scope persistence",
    )
    require(readiness.get("offer_authorization_granted") is False, "source readiness granted offer authorization")
    require(readiness.get("offer_engine_invocation_allowed") is False, "source readiness enabled offer engine")
    require(readiness.get("pricing_decision_allowed") is False, "source readiness enabled pricing")
    require(
        readiness.get("crm_context_materialization_allowed") is False,
        "source readiness enabled CRM context materialization",
    )
    require(readiness.get("human_review_required") is True, "source readiness human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(readiness.get(flag) is False, f"source readiness {flag} failed open")

    receipt = readiness.get("decision_receipt")
    require(isinstance(receipt, dict), "source readiness decision receipt missing")
    require(receipt.get("decision_source") == "HUMAN", "source readiness decision was not human")
    safe_ref(receipt.get("reviewer_ref"), "source readiness reviewer_ref")
    source_decided_at = receipt.get("decided_at")
    require(
        isinstance(source_decided_at, str) and RFC3339_UTC_Z.fullmatch(source_decided_at) is not None,
        "source readiness decided_at must be RFC3339 UTC-Z",
    )

    source_review_id = safe_ref(readiness.get("source_review_id"), "source_review_id")
    evaluation_id = safe_ref(readiness.get("source_evaluation_id"), "source_evaluation_id")
    readiness_id = safe_ref(readiness.get("commercial_scope_review_id"), "commercial_scope_review_id")
    verification_ref = safe_ref(readiness.get("official_source_verification_ref"), "official_source_verification_ref")
    org = safe_ref(readiness.get("organization_key"), "organization_key")
    prospect = safe_ref(readiness.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(readiness.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(readiness.get("selected_service_id"), "selected_service_id")
    return (org, prospect, opportunity, service), readiness_id, source_review_id, evaluation_id, verification_ref


def validate_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str, str, str]:
    require(isinstance(decision, dict), "offer preparation authorization decision must be an object")
    assert_safe_input(decision, "offer preparation authorization decision")
    require(set(decision) == DECISION_FIELDS, "offer preparation authorization decision fields drift")
    policy = contract["authorization"]
    require(decision.get("decision_source") == policy["decision_source"], "offer preparation decision source must be HUMAN")
    source_readiness_id = safe_ref(
        decision.get("source_commercial_scope_review_id"),
        "source_commercial_scope_review_id",
    )
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    scope_area = decision.get("commercial_scope_area")
    require(scope_area == contract["source_readiness"]["required_scope_area"], "commercial scope area drift")
    capability = decision.get("authorized_capability")
    require(capability in policy["allowed_capabilities"], "authorization capability escaped allowlist")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    outcome = decision.get("authorization_outcome")
    require(outcome in policy["allowed_authorization_outcomes"], "authorization outcome escaped allowlist")
    return (
        (org, prospect, opportunity, service),
        source_readiness_id,
        scope_area,
        capability,
        outcome,
        reviewer_ref,
        decided_at,
    )


def build_offer_preparation_authorization(
    readiness: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_READINESS_CONTRACT)
    validate_contract(contract)
    validate_source_contract(source_contract, contract)
    (
        source_identity,
        source_readiness_id,
        source_review_id,
        evaluation_id,
        verification_ref,
    ) = validate_source_readiness(readiness, contract)
    (
        decision_identity,
        decision_readiness_id,
        scope_area,
        capability,
        outcome,
        reviewer_ref,
        decided_at,
    ) = validate_decision(decision, contract)
    require(decision_identity == source_identity, "offer preparation authorization identity mismatch")
    require(
        decision_readiness_id == source_readiness_id,
        "offer preparation authorization source review mismatch",
    )
    require(
        decision_identity[3] == readiness["commercial_scope_projection"]["selected_service_id"],
        "offer preparation selected service does not match commercial scope projection",
    )
    require(
        scope_area == readiness["commercial_scope_projection"]["area_code"],
        "offer preparation scope does not match commercial scope projection",
    )

    preparation_state = contract["authorization"]["outcome_state_map"][outcome]
    next_gate = contract["authorization"]["outcome_next_gate_map"][outcome]
    authorized = outcome == "OFFER_PREPARATION_AUTHORIZED"
    org, prospect, opportunity, service = source_identity
    basis = "|".join((
        source_readiness_id, source_review_id, evaluation_id, org, prospect, opportunity,
        service, verification_ref, scope_area, capability, outcome, reviewer_ref, decided_at,
    ))
    authorization_id = "OFFPREP-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "offer_preparation_authorization_id": authorization_id,
        "record_state": output["record_state"],
        "source_commercial_scope_contract_id": contract["source_readiness"]["contract_id"],
        "source_commercial_scope_review_id": source_readiness_id,
        "source_research_review_id": source_review_id,
        "source_evaluation_id": evaluation_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "official_source_reverified": True,
        "official_source_verification_ref": verification_ref,
        "commercial_scope_projection": {
            "area_code": scope_area,
            "selected_service_id": service,
        },
        "authorization_capability": capability,
        "authorization_outcome": outcome,
        "offer_preparation_state": preparation_state,
        "offer_preparation_authorized": authorized,
        "next_gate_hint": next_gate,
        "offer_draft_generation_gate_required": next_gate is not None,
        "authorization_semantics": (
            "INTERNAL_PREPARATION_PERMISSION_NOT_OFFER_GENERATION_PRICING_ELIGIBILITY_OR_OUTREACH"
        ),
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "target_state_committed": False,
        "persistence_executed": False,
        "offer_preparation_persistence_allowed": False,
        "offer_authorization_granted": False,
        "offer_content_included": False,
        "pricing_included": False,
        "offer_draft_generation_allowed": False,
        "offer_generation_allowed": False,
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
    require(
        result["offer_preparation_authorized"] is authorized,
        "offer preparation authorization derivation failed",
    )
    require(result["target_state_committed"] is False, "offer preparation authorization committed target state")
    require(result["persistence_executed"] is False, "offer preparation authorization persisted state")
    require(
        result["offer_preparation_persistence_allowed"] is False,
        "offer preparation authorization enabled persistence",
    )
    for field in (
        "offer_authorization_granted",
        "offer_content_included",
        "pricing_included",
        "offer_draft_generation_allowed",
        "offer_generation_allowed",
        "offer_engine_invocation_allowed",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(result[field] is False, f"offer preparation authorization {field} failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"offer preparation authorization {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder human offer-preparation authorization gate")
    parser.add_argument("--readiness", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_READINESS_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_offer_preparation_authorization(
        load_json(args.readiness),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
