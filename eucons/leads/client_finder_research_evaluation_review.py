#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_research_evaluation_review_contract.json"
DEFAULT_SOURCE_TRANSITION_CONTRACT = EUCONS / "leads" / "client_finder_evaluation_transition_contract.json"
DEFAULT_SOURCE_EVALUATION_CONTRACT = EUCONS / "leads" / "research_evaluation_handoff_contract.json"

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
FORBIDDEN_RAW_OR_INFERENCE_KEYS = {
    "verification_evidence", "source_projection_sha256", "source_projection_hash", "content_hash",
    "source_supported_deadline", "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "source_age_verdict", "source_quality_verdict", "price", "amount_minor", "pricing_rule",
    "offer_id", "crm_state", "lead_id",
}
DECISION_FIELDS = {
    "evaluation_id", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "research_outcome", "decision_source", "reviewer_ref", "decided_at",
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
    forbidden = FORBIDDEN_RAW_OR_INFERENCE_KEYS & keys
    require(not forbidden, f"forbidden commercial/raw/inference field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "research evaluation review schema drift")
    require(
        contract.get("id") == "EUCONS-R07-CLIENT-FINDER-RESEARCH-EVALUATION-REVIEW-001",
        "research evaluation review contract id drift",
    )
    require(contract.get("status") == "CANONICAL", "research evaluation review contract is not canonical")
    require(contract.get("source_transition") == {
        "contract_id": "EUCONS-R07-CLIENT-FINDER-EVALUATION-TRANSITION-001",
        "record_state": "CLIENT_FINDER_RESEARCH_EVALUATION_TRANSITION_ENVELOPE",
        "required_transition_status": "READY_FOR_RESEARCH_EVALUATION_REVIEW",
        "required_source_status": "OFFICIAL_SOURCE_REVERIFIED",
        "required_transition_decision": "APPROVE_RESEARCH_EVALUATION_HANDOFF",
    }, "research evaluation source-transition drift")
    require(contract.get("source_evaluation") == {
        "contract_id": "EUCONS-E11-R07-EVALUATION-HANDOFF-001",
        "record_state": "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW",
    }, "research evaluation source-evaluation drift")
    require(contract.get("required_boundaries") == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "research evaluation review boundary drift")
    decision = contract.get("decision") or {}
    outcomes = ["MORE_RESEARCH_REQUIRED", "NO_RESEARCH_FIT", "RESEARCH_FIT_CONFIRMED"]
    require(decision.get("decision_source") == "HUMAN", "research evaluation decision source failed open")
    require(decision.get("allowed_research_outcomes") == outcomes, "research outcome allowlist drift")
    require(decision.get("outcome_review_map") == {
        "MORE_RESEARCH_REQUIRED": "RESEARCH_CONTINUE",
        "NO_RESEARCH_FIT": "RESEARCH_CLOSED_NO_FIT",
        "RESEARCH_FIT_CONFIRMED": "RESEARCH_COMPLETE_COMMERCIAL_GATE_REQUIRED",
    }, "research outcome review mapping drift")
    require(decision.get("outcome_next_gate_map") == {
        "MORE_RESEARCH_REQUIRED": None,
        "NO_RESEARCH_FIT": None,
        "RESEARCH_FIT_CONFIRMED": "SEPARATE_COMMERCIAL_SCOPE_GATE_REQUIRED",
    }, "research outcome next-gate mapping drift")
    require(decision.get("decided_at_format") == "RFC3339_UTC_Z", "research decision timestamp policy drift")
    output = contract.get("output") or {}
    require(
        output.get("record_state") == "CLIENT_FINDER_RESEARCH_EVALUATION_REVIEW_ENVELOPE",
        "research evaluation review output-state drift",
    )
    for field in (
        "target_state_committed",
        "persistence_executed",
        "offer_engine_invocation_allowed",
        "commercial_scope_write_enabled",
        "pricing_decision_allowed",
        "crm_context_materialization_allowed",
    ):
        require(output.get(field) is False, f"{field} must remain disabled")
    require(output.get("human_review_required") is True, "human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"research evaluation review safety rule failed open: {name}")


def validate_source_contracts(
    source_contract: dict[str, Any],
    evaluation_contract: dict[str, Any],
    contract: dict[str, Any],
) -> None:
    source = contract["source_transition"]
    require(source_contract.get("id") == source["contract_id"], "source transition contract mismatch")
    require(source_contract.get("status") == "CANONICAL", "source transition contract is not canonical")
    require(
        (source_contract.get("output") or {}).get("record_state") == source["record_state"],
        "source transition output state drift",
    )
    require(
        (source_contract.get("target_evaluation") or {}).get("contract_id")
        == contract["source_evaluation"]["contract_id"],
        "source transition target contract drift",
    )
    require(
        (source_contract.get("target_evaluation") or {}).get("record_state")
        == contract["source_evaluation"]["record_state"],
        "source transition target state drift",
    )
    source_boundaries = source_contract.get("required_boundaries") or {}
    for key, expected in contract["required_boundaries"].items():
        require(source_boundaries.get(key) == expected, f"source transition boundary drift: {key}")
    source_output = source_contract.get("output") or {}
    require(source_output.get("target_state_committed") is False, "source transition target-state commit failed open")
    require(source_output.get("persistence_executed") is False, "source transition persistence failed open")
    require(source_output.get("human_review_required") is True, "source transition human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"source transition {flag} failed open")
    decision = source_contract.get("decision") or {}
    require(decision.get("decision_source") == "HUMAN", "source transition decision source failed open")
    require(
        decision.get("status_decision_map", {}).get(source["required_source_status"])
        == source["required_transition_decision"],
        "source transition approval mapping drift",
    )
    require(
        decision.get("status_transition_map", {}).get(source["required_source_status"])
        == source["required_transition_status"],
        "source transition status mapping drift",
    )

    evaluation = contract["source_evaluation"]
    require(evaluation_contract.get("id") == evaluation["contract_id"], "source evaluation contract mismatch")
    require(evaluation_contract.get("status") == "CANONICAL", "source evaluation contract is not canonical")
    require(
        (evaluation_contract.get("output") or {}).get("record_state") == evaluation["record_state"],
        "source evaluation record-state drift",
    )
    require(
        evaluation_contract.get("required_eligibility_state") == contract["required_boundaries"]["eligibility_state"],
        "source evaluation eligibility boundary drift",
    )
    require(
        evaluation_contract.get("required_maximum_next_state") == contract["required_boundaries"]["maximum_next_state"],
        "source evaluation research boundary drift",
    )
    evaluation_output = evaluation_contract.get("output") or {}
    require(evaluation_output.get("human_review_required") is True, "source evaluation human review failed open")
    for flag in ("external_contact_enabled", "automatic_offer_enabled", "crm_write_enabled"):
        require(evaluation_output.get(flag) is False, f"source evaluation {flag} failed open")


def validate_transition_envelope(
    transition: dict[str, Any],
    contract: dict[str, Any],
    evaluation_contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str]:
    require(isinstance(transition, dict), "evaluation transition envelope must be an object")
    assert_safe_input(transition, "evaluation transition envelope")
    source = contract["source_transition"]
    boundaries = contract["required_boundaries"]
    require(transition.get("contract_id") == source["contract_id"], "transition contract id mismatch")
    require(transition.get("record_state") == source["record_state"], "transition record state mismatch")
    require(
        transition.get("transition_status") == source["required_transition_status"],
        "transition is not ready for research evaluation review",
    )
    require(transition.get("source_status") == source["required_source_status"], "transition source is not reverified")
    require(
        transition.get("target_evaluation_contract_id") == contract["source_evaluation"]["contract_id"],
        "transition target evaluation contract mismatch",
    )
    require(
        transition.get("target_evaluation_record_state") == contract["source_evaluation"]["record_state"],
        "transition target evaluation state mismatch",
    )
    require(transition.get("target_state_committed") is False, "transition target state was committed")
    require(transition.get("persistence_executed") is False, "transition persistence was executed")
    require(transition.get("eligibility_state") == boundaries["eligibility_state"], "transition eligibility drift")
    require(transition.get("maximum_next_state") == boundaries["maximum_next_state"], "transition research boundary drift")
    require(transition.get("human_review_required") is True, "transition human review failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(transition.get(flag) is False, f"transition {flag} failed open")
    receipt = transition.get("decision_receipt")
    require(isinstance(receipt, dict), "transition decision receipt missing")
    require(receipt.get("decision") == source["required_transition_decision"], "transition approval decision mismatch")
    require(receipt.get("decision_source") == "HUMAN", "transition approval was not human")
    safe_ref(receipt.get("reviewer_ref"), "transition reviewer_ref")
    transition_decided_at = receipt.get("decided_at")
    require(
        isinstance(transition_decided_at, str) and RFC3339_UTC_Z.fullmatch(transition_decided_at) is not None,
        "transition decided_at must be RFC3339 UTC-Z",
    )

    org = safe_ref(transition.get("organization_key"), "organization_key")
    prospect = safe_ref(transition.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(transition.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(transition.get("selected_service_id"), "selected_service_id")
    verification_ref = safe_ref(transition.get("official_source_verification_ref"), "official_source_verification_ref")
    envelope_id = safe_ref(transition.get("envelope_id"), "source transition envelope_id")

    proposed = transition.get("proposed_evaluation")
    require(isinstance(proposed, dict), "approved transition must contain proposed evaluation")
    require(
        proposed.get("contract_id") == contract["source_evaluation"]["contract_id"],
        "proposed evaluation contract mismatch",
    )
    require(
        proposed.get("record_state") == contract["source_evaluation"]["record_state"],
        "proposed evaluation state mismatch",
    )
    evaluation_id = safe_ref(proposed.get("evaluation_id"), "evaluation_id")
    require(proposed.get("prospect_id") == prospect, "proposed evaluation prospect identity drift")
    require(proposed.get("selected_opportunity_id") == opportunity, "proposed evaluation opportunity identity drift")
    require(proposed.get("selected_service_id") == service, "proposed evaluation service identity drift")
    require(
        proposed.get("match_semantics") == evaluation_contract.get("source_match_semantics"),
        "proposed evaluation match semantics drift",
    )
    require(proposed.get("eligibility_state") == boundaries["eligibility_state"], "proposed evaluation eligibility drift")
    require(
        proposed.get("maximum_next_state") == boundaries["maximum_next_state"],
        "proposed evaluation research boundary drift",
    )
    require(proposed.get("human_review_required") is True, "proposed evaluation human review failed open")
    for flag in ("external_contact_enabled", "automatic_offer_enabled", "crm_write_enabled"):
        require(proposed.get(flag) is False, f"proposed evaluation {flag} failed open")
    provenance = proposed.get("source_provenance")
    require(isinstance(provenance, dict), "proposed evaluation provenance reference missing")
    require(
        set(provenance) == {"source_product", "source_opportunity_id", "verification_ref"},
        "proposed evaluation provenance must remain minimized",
    )
    require(provenance.get("source_product") == "OFFICIAL_SOURCE_REVERIFICATION", "proposed evaluation source-product drift")
    require(provenance.get("source_opportunity_id") == opportunity, "proposed evaluation source opportunity drift")
    require(provenance.get("verification_ref") == verification_ref, "proposed evaluation verification reference drift")
    return (org, prospect, opportunity, service), evaluation_id, envelope_id


def validate_decision(
    decision: dict[str, Any],
    contract: dict[str, Any],
) -> tuple[tuple[str, str, str, str], str, str, str, str]:
    require(isinstance(decision, dict), "research evaluation decision must be an object")
    assert_safe_input(decision, "research evaluation decision")
    require(set(decision) == DECISION_FIELDS, "research evaluation decision fields drift")
    policy = contract["decision"]
    require(decision.get("decision_source") == policy["decision_source"], "research evaluation decision source must be HUMAN")
    evaluation_id = safe_ref(decision.get("evaluation_id"), "evaluation_id")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    reviewer_ref = safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(
        isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None,
        "decided_at must be RFC3339 UTC-Z",
    )
    outcome = decision.get("research_outcome")
    require(outcome in policy["allowed_research_outcomes"], "research outcome escaped allowlist")
    return (org, prospect, opportunity, service), evaluation_id, outcome, reviewer_ref, decided_at


def build_research_evaluation_review(
    transition: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    source_contract: dict[str, Any] | None = None,
    evaluation_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    source_contract = source_contract or load_json(DEFAULT_SOURCE_TRANSITION_CONTRACT)
    evaluation_contract = evaluation_contract or load_json(DEFAULT_SOURCE_EVALUATION_CONTRACT)
    validate_contract(contract)
    validate_source_contracts(source_contract, evaluation_contract, contract)
    source_identity, source_evaluation_id, source_envelope_id = validate_transition_envelope(
        transition, contract, evaluation_contract
    )
    decision_identity, decision_evaluation_id, outcome, reviewer_ref, decided_at = validate_decision(decision, contract)
    require(decision_identity == source_identity, "research evaluation decision identity mismatch")
    require(decision_evaluation_id == source_evaluation_id, "research evaluation decision evaluation_id mismatch")

    review_state = contract["decision"]["outcome_review_map"][outcome]
    next_gate = contract["decision"]["outcome_next_gate_map"][outcome]
    org, prospect, opportunity, service = source_identity
    verification_ref = transition["official_source_verification_ref"]
    basis = "|".join((
        source_envelope_id, source_evaluation_id, org, prospect, opportunity, service,
        verification_ref, outcome, reviewer_ref, decided_at,
    ))
    review_id = "EVREVIEW-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "review_id": review_id,
        "record_state": output["record_state"],
        "source_transition_contract_id": contract["source_transition"]["contract_id"],
        "source_transition_envelope_id": source_envelope_id,
        "source_evaluation_contract_id": contract["source_evaluation"]["contract_id"],
        "source_evaluation_id": source_evaluation_id,
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "match_semantics": evaluation_contract["source_match_semantics"],
        "official_source_reverified": True,
        "official_source_verification_ref": verification_ref,
        "research_outcome": outcome,
        "research_review_state": review_state,
        "next_gate_hint": next_gate,
        "commercial_scope_gate_required": next_gate is not None,
        "research_fit_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": reviewer_ref,
            "decided_at": decided_at,
        },
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "target_state_committed": False,
        "persistence_executed": False,
        "offer_engine_invocation_allowed": False,
        "commercial_scope_write_enabled": False,
        "pricing_decision_allowed": False,
        "crm_context_materialization_allowed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    require(result["target_state_committed"] is False, "research review committed a target state")
    require(result["persistence_executed"] is False, "research review persisted state")
    require(result["offer_engine_invocation_allowed"] is False, "research review enabled offer engine")
    require(
        result["crm_context_materialization_allowed"] is False,
        "research review enabled CRM context materialization",
    )
    require(result["pricing_decision_allowed"] is False, "research review enabled pricing")
    for flag in DISABLED_ACTION_FLAGS:
        require(result[flag] is False, f"research review {flag} failed open")
    return result


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="EUCONS Client Finder research-evaluation human review gate")
    parser.add_argument("--transition", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--source-contract", default=str(DEFAULT_SOURCE_TRANSITION_CONTRACT), type=Path)
    parser.add_argument("--evaluation-contract", default=str(DEFAULT_SOURCE_EVALUATION_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_research_evaluation_review(
        load_json(args.transition),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.source_contract),
        load_json(args.evaluation_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
