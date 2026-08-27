#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT = EUCONS / "leads" / "client_finder_evaluation_transition_contract.json"
DEFAULT_TARGET_CONTRACT = EUCONS / "leads" / "research_evaluation_handoff_contract.json"
TARGET_ENGINE = EUCONS / "leads" / "research_evaluation_handoff.py"

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
    "source_provenance", "verification_evidence", "source_projection_sha256",
    "source_projection_hash", "content_hash", "source_supported_deadline",
    "eligibility_probability", "award_probability", "conversion_probability",
    "buying_intent", "purchase_intent", "legal_conclusion", "financial_conclusion",
    "source_age_verdict", "source_quality_verdict",
}
DECISION_FIELDS = {
    "queue_rank", "organization_key", "prospect_id", "selected_opportunity_id",
    "selected_service_id", "source_status", "decision", "decision_source",
    "verification_ref", "reviewer_ref", "decided_at",
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


def validate_contract(contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 1, "evaluation transition schema drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-EVALUATION-TRANSITION-001", "evaluation transition contract id drift")
    require(contract.get("status") == "CANONICAL", "evaluation transition contract is not canonical")
    source = contract.get("source_triage") or {}
    require(source == {
        "view_id": "EUCONS-R07-CLIENT-FINDER-OPERATOR-TRIAGE-SYNTHESIS-001",
        "view_state": "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW",
        "semantics": "OPERATOR_REVERIFICATION_AND_MATCH_REVIEW_ONLY",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "required_operator_next_step": "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH",
    }, "evaluation transition source contract drift")
    target = contract.get("target_evaluation") or {}
    require(target == {
        "contract_id": "EUCONS-E11-R07-EVALUATION-HANDOFF-001",
        "record_state": "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW",
    }, "evaluation transition target contract drift")
    boundaries = contract.get("required_boundaries") or {}
    require(boundaries == {
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }, "evaluation transition boundary drift")
    decision = contract.get("decision") or {}
    require(decision.get("decision_source") == "HUMAN", "decision source failed open")
    statuses = decision.get("allowed_source_statuses")
    decisions = decision.get("allowed_decisions")
    require(statuses == ["SOURCE_NOT_REVERIFIED", "OFFICIAL_SOURCE_CONFLICT", "OFFICIAL_SOURCE_REVERIFIED"], "source status allowlist drift")
    require(decisions == ["REQUEST_OFFICIAL_SOURCE_REVERIFICATION", "BLOCK_SOURCE_CONFLICT", "APPROVE_RESEARCH_EVALUATION_HANDOFF"], "decision allowlist drift")
    require(decision.get("status_decision_map") == dict(zip(statuses, decisions)), "source status/decision map drift")
    require(decision.get("status_transition_map") == {
        "SOURCE_NOT_REVERIFIED": "WAITING_SOURCE",
        "OFFICIAL_SOURCE_CONFLICT": "BLOCKED",
        "OFFICIAL_SOURCE_REVERIFIED": "READY_FOR_RESEARCH_EVALUATION_REVIEW",
    }, "source status/transition map drift")
    require(decision.get("verification_ref_required_for") == ["OFFICIAL_SOURCE_CONFLICT", "OFFICIAL_SOURCE_REVERIFIED"], "verification reference policy drift")
    require(decision.get("decided_at_format") == "RFC3339_UTC_Z", "decision timestamp policy drift")
    output = contract.get("output") or {}
    require(output.get("record_state") == "CLIENT_FINDER_RESEARCH_EVALUATION_TRANSITION_ENVELOPE", "transition envelope state drift")
    require(output.get("target_state_committed") is False, "target state commit failed open")
    require(output.get("persistence_executed") is False, "persistence boundary failed open")
    require(output.get("human_review_required") is True, "human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")
    for name, enabled in (contract.get("rules") or {}).items():
        require(enabled is True, f"transition safety rule failed open: {name}")


def validate_target_contract(target: dict[str, Any], contract: dict[str, Any]) -> None:
    expected = contract["target_evaluation"]
    require(target.get("id") == expected["contract_id"], "target evaluation contract mismatch")
    require(target.get("status") == "CANONICAL", "target evaluation contract is not canonical")
    require(target.get("source_match_semantics") == contract["source_triage"]["match_semantics"], "target match semantics drift")
    require(target.get("required_source_state") == "MATCHED_RESEARCH_CANDIDATE", "target source-state drift")
    require(target.get("required_eligibility_state") == contract["required_boundaries"]["eligibility_state"], "target eligibility boundary drift")
    require(target.get("required_maximum_next_state") == contract["required_boundaries"]["maximum_next_state"], "target research boundary drift")
    output = target.get("output") or {}
    require(output.get("record_state") == expected["record_state"], "target evaluation state drift")
    require(output.get("human_review_required") is True, "target human review failed open")
    for flag in ("external_contact_enabled", "automatic_offer_enabled", "crm_write_enabled"):
        require(output.get(flag) is False, f"target {flag} failed open")


def assert_safe_input(value: Any, label: str) -> None:
    keys = set(recursive_keys(value))
    person = FORBIDDEN_PERSON_LEVEL_KEYS & keys
    require(not person, f"person-level field entered {label}: {sorted(person)[0] if person else ''}")
    forbidden = FORBIDDEN_RAW_OR_INFERENCE_KEYS & keys
    require(not forbidden, f"forbidden raw/inference field entered {label}: {sorted(forbidden)[0] if forbidden else ''}")


def assert_boundaries(value: dict[str, Any], contract: dict[str, Any], label: str) -> None:
    boundaries = contract["required_boundaries"]
    require(value.get("eligibility_state") == boundaries["eligibility_state"], f"{label} eligibility boundary drift")
    require(value.get("maximum_next_state") == boundaries["maximum_next_state"], f"{label} research boundary drift")
    require(value.get("human_review_required") is True, f"{label} human review boundary failed open")
    for flag in DISABLED_ACTION_FLAGS:
        require(value.get(flag) is False, f"{label} {flag} failed open")


def validate_triage_view(view: dict[str, Any], contract: dict[str, Any]) -> list[dict[str, Any]]:
    require(isinstance(view, dict), "operator triage view must be an object")
    assert_safe_input(view, "operator triage")
    source = contract["source_triage"]
    require(view.get("view_id") == source["view_id"], "operator triage view id mismatch")
    require(view.get("view_state") == source["view_state"], "operator triage view state mismatch")
    require(view.get("semantics") == source["semantics"], "operator triage semantics mismatch")
    require(view.get("match_semantics") == source["match_semantics"], "operator triage match semantics mismatch")
    assert_boundaries(view, contract, "operator triage")
    queue = view.get("queue")
    require(isinstance(queue, list), "operator triage queue must be a list")
    seen_ranks: set[int] = set()
    seen_identity: set[tuple[str, str, str, str]] = set()
    for row in queue:
        require(isinstance(row, dict), "operator triage row must be an object")
        assert_boundaries(row, contract, "operator triage row")
        rank = row.get("queue_rank")
        require(isinstance(rank, int) and not isinstance(rank, bool) and rank > 0, "invalid operator triage queue rank")
        require(rank not in seen_ranks, "duplicate operator triage queue rank")
        seen_ranks.add(rank)
        org = safe_ref(row.get("organization_key"), "organization_key")
        prospect = safe_ref(row.get("prospect_id"), "prospect_id")
        service = safe_ref(row.get("selected_service_id"), "selected_service_id")
        selected = row.get("selected_opportunity")
        require(isinstance(selected, dict), "selected opportunity missing")
        opportunity = safe_ref(selected.get("opportunity_id"), "selected_opportunity_id")
        identity = (org, prospect, opportunity, service)
        require(identity not in seen_identity, "duplicate operator triage identity")
        seen_identity.add(identity)
        require(row.get("operator_next_step") == source["required_operator_next_step"], "operator triage next-step drift")
        require(row.get("official_source_reverification_required") is True, "official-source reverification boundary failed open")
        require(row.get("material_claims_verified") is False, "material claims were marked verified upstream")
        require(row.get("source_age_classification") == "NOT_CLASSIFIED", "source age was classified upstream")
        require(row.get("threshold_applied") is False, "freshness threshold was applied upstream")
    return queue


def validate_decision(decision: dict[str, Any], contract: dict[str, Any]) -> tuple[str, str, str, str, str]:
    require(isinstance(decision, dict), "decision must be an object")
    assert_safe_input(decision, "human transition decision")
    require(set(decision) == DECISION_FIELDS, "human transition decision fields drift")
    policy = contract["decision"]
    require(decision.get("decision_source") == policy["decision_source"], "decision source must be HUMAN")
    rank = decision.get("queue_rank")
    require(isinstance(rank, int) and not isinstance(rank, bool) and rank > 0, "invalid decision queue rank")
    org = safe_ref(decision.get("organization_key"), "organization_key")
    prospect = safe_ref(decision.get("prospect_id"), "prospect_id")
    opportunity = safe_ref(decision.get("selected_opportunity_id"), "selected_opportunity_id")
    service = safe_ref(decision.get("selected_service_id"), "selected_service_id")
    safe_ref(decision.get("reviewer_ref"), "reviewer_ref")
    decided_at = decision.get("decided_at")
    require(isinstance(decided_at, str) and RFC3339_UTC_Z.fullmatch(decided_at) is not None, "decided_at must be RFC3339 UTC-Z")
    source_status = decision.get("source_status")
    require(source_status in policy["allowed_source_statuses"], "source status escaped allowlist")
    expected_decision = policy["status_decision_map"][source_status]
    require(decision.get("decision") == expected_decision, "source status/decision mismatch")
    verification_ref = decision.get("verification_ref")
    if source_status in policy["verification_ref_required_for"]:
        safe_ref(verification_ref, "verification_ref")
    else:
        require(verification_ref is None, "verification_ref must be absent until an official source is available")
    return org, prospect, opportunity, service, source_status


def find_selected_row(queue: list[dict[str, Any]], decision: dict[str, Any], identity: tuple[str, str, str, str]) -> dict[str, Any]:
    rank = decision["queue_rank"]
    matches = []
    for row in queue:
        selected = row["selected_opportunity"]
        row_identity = (
            str(row["organization_key"]).strip(),
            str(row["prospect_id"]).strip(),
            str(selected["opportunity_id"]).strip(),
            str(row["selected_service_id"]).strip(),
        )
        if row["queue_rank"] == rank and row_identity == identity:
            matches.append(row)
    require(len(matches) == 1, "human selection does not match exactly one operator triage row")
    return matches[0]


def load_target_engine():
    spec = importlib.util.spec_from_file_location("eucons_research_evaluation_handoff_transition", TARGET_ENGINE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def build_transition_envelope(
    triage_view: dict[str, Any],
    decision: dict[str, Any],
    contract: dict[str, Any] | None = None,
    target_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT)
    target_contract = target_contract or load_json(DEFAULT_TARGET_CONTRACT)
    validate_contract(contract)
    validate_target_contract(target_contract, contract)
    queue = validate_triage_view(triage_view, contract)
    org, prospect, opportunity, service, source_status = validate_decision(decision, contract)
    selected = find_selected_row(queue, decision, (org, prospect, opportunity, service))
    transition_status = contract["decision"]["status_transition_map"][source_status]
    verification_ref = decision["verification_ref"]
    proposed_evaluation = None
    if transition_status == "READY_FOR_RESEARCH_EVALUATION_REVIEW":
        synthetic_match = {
            "prospect_id": prospect,
            "state": target_contract["required_source_state"],
            "match_semantics": target_contract["source_match_semantics"],
            "eligibility_state": target_contract["required_eligibility_state"],
            "maximum_next_state": target_contract["required_maximum_next_state"],
            "selected_opportunity_id": opportunity,
            "selected_service_id": service,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "opportunity_matches": [{
                "opportunity_id": opportunity,
                "aligned_service_ids": [service],
                "selected_service_id": service,
                "source_provenance": {
                    "source_product": "OFFICIAL_SOURCE_REVERIFICATION",
                    "source_opportunity_id": opportunity,
                    "verification_ref": verification_ref,
                },
            }],
        }
        handoff = load_target_engine()
        proposed_evaluation = handoff.build_evaluation_handoff(synthetic_match, target_contract)
        require(proposed_evaluation.get("record_state") == contract["target_evaluation"]["record_state"], "proposed evaluation target-state drift")
        require(proposed_evaluation.get("human_review_required") is True, "proposed evaluation human review failed open")
        require(proposed_evaluation.get("external_contact_enabled") is False, "proposed evaluation enabled external contact")
        require(proposed_evaluation.get("automatic_offer_enabled") is False, "proposed evaluation enabled automatic offer")
        require(proposed_evaluation.get("crm_write_enabled") is False, "proposed evaluation enabled CRM write")
    basis = "|".join((
        org, prospect, opportunity, service, source_status, decision["decision"],
        verification_ref or "NO_SOURCE_REF", decision["reviewer_ref"], decision["decided_at"],
    ))
    envelope_id = "EVTRANS-" + hashlib.sha256(basis.encode("utf-8")).hexdigest()[:24]
    output = contract["output"]
    result = {
        "schema_version": 1,
        "contract_id": contract["id"],
        "envelope_id": envelope_id,
        "record_state": output["record_state"],
        "transition_status": transition_status,
        "source_view_id": contract["source_triage"]["view_id"],
        "source_queue_rank": selected["queue_rank"],
        "organization_key": org,
        "prospect_id": prospect,
        "selected_opportunity_id": opportunity,
        "selected_service_id": service,
        "match_semantics": contract["source_triage"]["match_semantics"],
        "source_status": source_status,
        "official_source_verification_ref": verification_ref,
        "decision_receipt": {
            "decision": decision["decision"],
            "decision_source": decision["decision_source"],
            "reviewer_ref": decision["reviewer_ref"],
            "decided_at": decision["decided_at"],
        },
        "target_evaluation_contract_id": contract["target_evaluation"]["contract_id"],
        "target_evaluation_record_state": contract["target_evaluation"]["record_state"],
        "proposed_evaluation": proposed_evaluation,
        "eligibility_state": contract["required_boundaries"]["eligibility_state"],
        "maximum_next_state": contract["required_boundaries"]["maximum_next_state"],
        "target_state_committed": False,
        "persistence_executed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    require(result["target_state_committed"] is False and result["persistence_executed"] is False, "transition executed a write")
    assert_boundaries(result, contract, "transition envelope")
    return result


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="EUCONS Client Finder research-evaluation transition gate")
    parser.add_argument("--triage-view", required=True, type=Path)
    parser.add_argument("--decision", required=True, type=Path)
    parser.add_argument("--contract", default=str(DEFAULT_CONTRACT), type=Path)
    parser.add_argument("--target-contract", default=str(DEFAULT_TARGET_CONTRACT), type=Path)
    args = parser.parse_args()
    result = build_transition_envelope(
        load_json(args.triage_view),
        load_json(args.decision),
        load_json(args.contract),
        load_json(args.target_contract),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
