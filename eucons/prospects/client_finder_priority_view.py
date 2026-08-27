#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_priority_view_contract.json"
DEFAULT_MATCH_CONTRACT_PATH = EUCONS / "prospects" / "prospect_opportunity_match_contract.json"

FORBIDDEN_PERSON_KEYS = {
    "person_name",
    "personal_name",
    "personal_email",
    "personal_phone",
    "home_address",
    "personal_social_profile",
    "personal_identifier",
    "date_of_birth",
    "private_contact",
    "contact_name",
    "email",
    "phone",
    "cnp",
}

DISABLED_ACTION_FLAGS = (
    "external_contact_enabled",
    "automatic_offer_enabled",
    "automatic_send_enabled",
    "crm_write_enabled",
    "pipeline_write_enabled",
)


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


def validate_contract(contract: dict[str, Any], match_contract: dict[str, Any]) -> None:
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-PRIORITY-VIEW-001",
            "priority view contract id drift")
    require(contract.get("status") == "CANONICAL", "priority view contract is not canonical")
    require(contract.get("source_contract_id") == match_contract.get("id"), "source contract mismatch")
    require(contract.get("source_match_semantics") == match_contract.get("match_semantics"),
            "source semantics drift")
    require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "eligibility boundary drift")
    require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "research boundary drift")

    source_outputs = match_contract.get("outputs") or {}
    require(source_outputs.get("eligibility_state") == contract["required_eligibility_state"],
            "source eligibility boundary drift")
    require(source_outputs.get("maximum_next_state") == contract["required_maximum_next_state"],
            "source research boundary drift")
    require(source_outputs.get("external_contact_enabled") is False, "source contact boundary failed open")
    require(source_outputs.get("automatic_offer_enabled") is False, "source offer boundary failed open")

    expected_states = {
        source_outputs.get("matched"),
        source_outputs.get("requires_verification"),
        source_outputs.get("no_current_opportunity"),
        source_outputs.get("held_source"),
        source_outputs.get("held_conflict"),
        source_outputs.get("suppressed"),
    }
    state_priority = contract.get("state_priority") or {}
    require(set(state_priority) == expected_states and all(isinstance(value, int) and value >= 0 for value in state_priority.values()),
            "priority view state taxonomy drift")

    priority_order = contract.get("research_priority_order") or {}
    require(set(priority_order) == {
        "PRIORITY_HIGH_RESEARCH",
        "PRIORITY_MEDIUM_RESEARCH",
        "PRIORITY_LOW_RESEARCH",
        "HOLD_CONFLICT",
        "HOLD_SOURCE_STATE",
        "HOLD_SOURCE_OR_RECORD_STATE",
        "SUPPRESSED",
    }, "research priority taxonomy drift")

    output = contract.get("output") or {}
    require(output.get("view_state") == "CLIENT_FINDER_RESEARCH_PRIORITY_VIEW", "view state drift")
    require(output.get("eligibility_state") == "NOT_ASSESSED", "view eligibility boundary failed open")
    require(output.get("maximum_next_state") == "RESEARCH_READY", "view research boundary failed open")
    require(output.get("human_review_required") is True, "human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"{flag} must remain disabled")

    rules = contract.get("rules") or {}
    for name in (
        "deterministic_ranking",
        "never_expose_person_level_fields",
        "selected_opportunity_and_service_only_from_verified_match",
        "deadline_only_when_source_supported",
        "no_eligibility_award_probability_or_buying_intent_claim",
        "no_external_action_or_persistence",
    ):
        require(rules.get(name) is True, f"priority view rule failed open: {name}")


def _match_index(row: dict[str, Any]) -> dict[str, dict[str, Any]]:
    matches = row.get("opportunity_matches") or []
    require(isinstance(matches, list), "opportunity matches must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for match in matches:
        require(isinstance(match, dict), "opportunity match must be an object")
        opportunity_id = match.get("opportunity_id")
        if opportunity_id is not None:
            require(isinstance(opportunity_id, str) and opportunity_id.strip(), "invalid opportunity id")
            require(opportunity_id not in indexed, "duplicate opportunity id")
            indexed[opportunity_id] = match
    return indexed


def _selected_opportunity(row: dict[str, Any], matched_state: str) -> dict[str, Any] | None:
    selected_id = row.get("selected_opportunity_id")
    selected_service_id = row.get("selected_service_id")
    if row.get("state") != matched_state:
        require(selected_id is None and selected_service_id is None,
                "non-matched prospect retained selected opportunity or service")
        return None

    require(isinstance(selected_id, str) and selected_id.strip(), "matched prospect missing selected opportunity")
    require(isinstance(selected_service_id, str) and selected_service_id.strip(),
            "matched prospect missing selected service")
    selected = _match_index(row).get(selected_id)
    require(selected is not None, "selected opportunity is not present in match rows")
    require(selected.get("selected_service_id") == selected_service_id,
            "selected service differs from verified opportunity-service overlap")
    require(selected_service_id in (selected.get("aligned_service_ids") or []),
            "selected service is not in verified overlap")

    deadline = selected.get("source_supported_deadline")
    verified_classes = set(selected.get("verified_fact_classes") or [])
    if deadline is not None:
        require("deadline" in verified_classes, "deadline exposed without verified source class")
    return selected


def _priority_score(row: dict[str, Any]) -> int | None:
    score = row.get("priority_score")
    require(score is None or (isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100),
            "invalid research priority score")
    return score


def build_priority_view(
    match_result: dict[str, Any],
    contract: dict[str, Any] | None = None,
    match_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT_PATH)
    match_contract = match_contract or load_json(DEFAULT_MATCH_CONTRACT_PATH)
    validate_contract(contract, match_contract)
    require(isinstance(match_result, dict), "match result must be an object")
    require(match_result.get("match_semantics") == contract["source_match_semantics"], "match semantics drift")
    require(match_result.get("eligibility_state") == contract["required_eligibility_state"],
            "match eligibility boundary failed open")
    require(match_result.get("maximum_next_state") == contract["required_maximum_next_state"],
            "match research boundary failed open")
    bridge_state = match_result.get("bridge_state")
    require(isinstance(bridge_state, str) and bridge_state.strip(), "missing bridge state")

    rows = match_result.get("results")
    require(isinstance(rows, list), "match results must be a list")
    if FORBIDDEN_PERSON_KEYS & set(recursive_keys(rows)):
        raise ValueError("person-level field entered Client Finder priority view")

    matched_state = match_contract["outputs"]["matched"]
    cards: list[dict[str, Any]] = []
    seen_prospects: set[str] = set()
    for row in rows:
        require(isinstance(row, dict), "match row must be an object")
        prospect_id = row.get("prospect_id")
        organization_key = row.get("organization_key")
        require(isinstance(prospect_id, str) and prospect_id.strip(), "invalid prospect id")
        require(isinstance(organization_key, str) and organization_key.strip(), "invalid organization key")
        require(prospect_id not in seen_prospects, "duplicate prospect id")
        seen_prospects.add(prospect_id)

        state = row.get("state")
        require(state in contract["state_priority"], "unknown Client Finder state")
        if state == matched_state:
            require(bridge_state == "READY", "matched prospect requires READY bridge")
        require(row.get("eligibility_state") == "NOT_ASSESSED", "row eligibility boundary failed open")
        require(row.get("maximum_next_state") == "RESEARCH_READY", "row research boundary failed open")
        require(row.get("external_contact_enabled") is False, "row contact boundary failed open")
        require(row.get("automatic_offer_enabled") is False, "row offer boundary failed open")
        score = _priority_score(row)
        selected = _selected_opportunity(row, matched_state)

        priority_state = row.get("priority_state")
        require(priority_state in contract["research_priority_order"], "unknown research priority state")
        questions = row.get("verification_questions") or []
        require(isinstance(questions, list) and all(isinstance(value, str) for value in questions),
                "verification questions must be strings")
        safe_next_action = row.get("next_best_action")
        require(safe_next_action in set((match_contract.get("next_best_actions") or {}).values()),
                "unknown next-best action")

        cards.append({
            "prospect_id": prospect_id,
            "organization_key": organization_key,
            "state": state,
            "priority_state": priority_state,
            "priority_score": score,
            "attention_reason": contract["attention_reason_by_state"][state],
            "selected_opportunity": None if selected is None else {
                "opportunity_id": selected["opportunity_id"],
                "title": selected.get("title"),
                "programme": selected.get("programme"),
                "relevance_score": selected.get("relevance_score"),
                "selected_service_id": row["selected_service_id"],
                "source_supported_deadline": selected.get("source_supported_deadline"),
                "verified_fact_classes": sorted(selected.get("verified_fact_classes") or []),
            },
            "selected_service_id": row.get("selected_service_id"),
            "safe_next_action": safe_next_action,
            "verification_questions": sorted(set(questions)),
            "source_ref_count": len(set(row.get("source_refs") or [])),
            "signal_count": len(set(row.get("signal_ids") or [])),
            "evidence_label": row.get("evidence_label"),
            "human_review_required": True,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "automatic_send_enabled": False,
            "crm_write_enabled": False,
            "pipeline_write_enabled": False,
        })

    state_priority = contract["state_priority"]
    research_priority = contract["research_priority_order"]
    cards.sort(key=lambda card: (
        state_priority[card["state"]],
        research_priority[card["priority_state"]],
        -(card["priority_score"] if card["priority_score"] is not None else -1),
        card["prospect_id"],
    ))
    for rank, card in enumerate(cards, start=1):
        card["rank"] = rank

    output = contract["output"]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "view_state": output["view_state"],
        "match_semantics": contract["source_match_semantics"],
        "eligibility_state": output["eligibility_state"],
        "maximum_next_state": output["maximum_next_state"],
        "bridge_state": match_result.get("bridge_state"),
        "summary": {
            "cards": len(cards),
            "matched": sum(card["state"] == matched_state for card in cards),
            "needs_verification": sum(card["state"] == match_contract["outputs"]["requires_verification"] for card in cards),
            "held": sum(card["state"] in {
                match_contract["outputs"]["held_source"],
                match_contract["outputs"]["held_conflict"],
            } for card in cards),
            "suppressed": sum(card["state"] == match_contract["outputs"]["suppressed"] for card in cards),
        },
        "cards": cards,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Build a deterministic, non-writing Client Finder priority view")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = build_priority_view(load_json(args.input))
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
