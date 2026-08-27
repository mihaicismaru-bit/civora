#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
DEFAULT_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_triage_view_contract.json"
DEFAULT_PRIORITY_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_priority_view_contract.json"

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

EXPECTED_SOURCE_TRACE_FIELDS = {
    "source_product",
    "source_opportunity_id",
    "source_as_of",
    "source_projection_sha256",
    "verification_evidence_count",
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


def validate_contract(contract: dict[str, Any], priority_contract: dict[str, Any]) -> None:
    require(contract.get("schema_version") == 2, "triage contract schema version drift")
    require(contract.get("id") == "EUCONS-R07-CLIENT-FINDER-TRIAGE-VIEW-002", "triage contract id drift")
    require(contract.get("status") == "CANONICAL", "triage contract is not canonical")
    require(contract.get("source_contract_id") == priority_contract.get("id"), "triage source contract mismatch")
    require(contract.get("source_view_state") == priority_contract.get("output", {}).get("view_state"),
            "triage source view state drift")
    require(contract.get("required_eligibility_state") == "NOT_ASSESSED", "triage eligibility boundary drift")
    require(contract.get("required_maximum_next_state") == "RESEARCH_READY", "triage research boundary drift")
    require(set(contract.get("allowed_filters") or []) == {
        "state", "selected_service_id", "has_source_supported_deadline"
    }, "triage filter allowlist drift")
    require(set(contract.get("allowed_sort_modes") or []) == {
        "RESEARCH_PRIORITY", "SCORE_DESC", "DEADLINE_ASC"
    }, "triage sort allowlist drift")
    require(contract.get("default_sort_mode") == "RESEARCH_PRIORITY", "triage default sort drift")

    provenance = contract.get("provenance") or {}
    require(provenance.get("matched_selected_opportunity_source_trace_required") is True,
            "matched triage provenance requirement failed open")
    require(provenance.get("required_source_product") == "PARTENER.EU",
            "triage provenance source product drift")
    require(set(provenance.get("required_source_trace_fields") or []) == EXPECTED_SOURCE_TRACE_FIELDS,
            "triage provenance field allowlist drift")
    require(provenance.get("raw_verification_evidence_exposed") is False,
            "triage raw evidence exposure failed open")
    require(provenance.get("unmatched_source_trace_required") is False,
            "unmatched triage cards unexpectedly require provenance")

    source_output = priority_contract.get("output") or {}
    require(source_output.get("eligibility_state") == "NOT_ASSESSED", "priority eligibility boundary failed open")
    require(source_output.get("maximum_next_state") == "RESEARCH_READY", "priority research boundary failed open")
    require(source_output.get("human_review_required") is True, "priority human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(source_output.get(flag) is False, f"priority {flag} must remain disabled")

    output = contract.get("output") or {}
    require(output.get("view_state") == "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW", "triage view state drift")
    require(output.get("eligibility_state") == "NOT_ASSESSED", "triage eligibility boundary failed open")
    require(output.get("maximum_next_state") == "RESEARCH_READY", "triage research boundary failed open")
    require(output.get("human_review_required") is True, "triage human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(output.get(flag) is False, f"triage {flag} must remain disabled")

    rules = contract.get("rules") or {}
    for name in (
        "deterministic_filtering_and_sorting",
        "unknown_filters_or_sort_modes_fail_closed",
        "never_expose_person_level_fields",
        "deadline_only_when_source_supported",
        "selected_service_must_match_selected_opportunity",
        "matched_cards_require_minimized_verified_source_trace",
        "safe_output_whitelist_only",
        "no_external_action_or_persistence",
    ):
        require(rules.get(name) is True, f"triage rule failed open: {name}")


def _validated_card(card: dict[str, Any], contract: dict[str, Any]) -> dict[str, Any]:
    require(isinstance(card, dict), "triage source card must be an object")
    if FORBIDDEN_PERSON_KEYS & set(recursive_keys(card)):
        raise ValueError("person-level field entered Client Finder triage view")

    prospect_id = card.get("prospect_id")
    organization_key = card.get("organization_key")
    require(isinstance(prospect_id, str) and prospect_id.strip(), "invalid triage prospect id")
    require(isinstance(organization_key, str) and organization_key.strip(), "invalid triage organization key")
    require(isinstance(card.get("rank"), int) and card["rank"] > 0, "invalid source research rank")
    score = card.get("priority_score")
    require(score is None or (isinstance(score, int) and not isinstance(score, bool) and 0 <= score <= 100),
            "invalid triage priority score")
    require(card.get("human_review_required") is True, "source card human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(card.get(flag) is False, f"source card {flag} failed open")

    selected_service_id = card.get("selected_service_id")
    selected = card.get("selected_opportunity")
    safe_source_trace = None
    if selected_service_id is None:
        require(selected is None, "opportunity exposed without selected service")
        deadline = None
        verified_classes: list[str] = []
    else:
        require(isinstance(selected_service_id, str) and selected_service_id.strip(), "invalid selected service id")
        require(isinstance(selected, dict), "selected service missing selected opportunity")
        require(selected.get("selected_service_id") == selected_service_id,
                "selected service differs from selected opportunity")
        verified_classes = selected.get("verified_fact_classes") or []
        require(isinstance(verified_classes, list) and all(isinstance(value, str) for value in verified_classes),
                "verified fact classes must be strings")
        deadline = selected.get("source_supported_deadline")
        if deadline is not None:
            require(isinstance(deadline, str) and deadline.strip(), "invalid source-supported deadline")
            require("deadline" in set(verified_classes), "deadline exposed without verified source class")

        provenance_contract = contract["provenance"]
        source_trace = selected.get("source_trace")
        if provenance_contract["matched_selected_opportunity_source_trace_required"]:
            require(isinstance(source_trace, dict), "matched selected opportunity missing required source trace")
        if source_trace is not None:
            require(isinstance(source_trace, dict), "invalid selected-opportunity source trace")
            required_fields = set(provenance_contract["required_source_trace_fields"])
            require(required_fields <= set(source_trace), "selected-opportunity source trace is incomplete")
            require(source_trace.get("source_product") == provenance_contract["required_source_product"],
                    "triage source product drift")
            require(source_trace.get("source_opportunity_id") == selected.get("opportunity_id"),
                    "triage source opportunity id mismatch")
            source_as_of = source_trace.get("source_as_of")
            require(isinstance(source_as_of, str) and source_as_of.strip(), "invalid triage source as-of")
            projection_sha = source_trace.get("source_projection_sha256")
            require(projection_sha is None or (
                isinstance(projection_sha, str)
                and len(projection_sha) == 64
                and all(char in "0123456789abcdef" for char in projection_sha.lower())
            ), "invalid triage source projection hash")
            evidence_count = source_trace.get("verification_evidence_count")
            require(isinstance(evidence_count, int) and not isinstance(evidence_count, bool) and evidence_count > 0,
                    "invalid triage verification evidence count")
            safe_source_trace = {
                "source_product": provenance_contract["required_source_product"],
                "source_opportunity_id": source_trace["source_opportunity_id"],
                "source_as_of": source_as_of,
                "source_projection_sha256": projection_sha,
                "verification_evidence_count": evidence_count,
            }

    questions = card.get("verification_questions") or []
    require(isinstance(questions, list) and all(isinstance(value, str) for value in questions),
            "triage verification questions must be strings")

    safe_selected = None
    if selected is not None:
        safe_selected = {
            "opportunity_id": selected.get("opportunity_id"),
            "title": selected.get("title"),
            "programme": selected.get("programme"),
            "relevance_score": selected.get("relevance_score"),
            "selected_service_id": selected_service_id,
            "source_supported_deadline": deadline,
            "verified_fact_classes": sorted(set(verified_classes)),
            "source_trace": safe_source_trace,
        }

    return {
        "source_rank": card["rank"],
        "prospect_id": prospect_id,
        "organization_key": organization_key,
        "state": card.get("state"),
        "priority_state": card.get("priority_state"),
        "priority_score": score,
        "attention_reason": card.get("attention_reason"),
        "selected_opportunity": safe_selected,
        "selected_service_id": selected_service_id,
        "safe_next_action": card.get("safe_next_action"),
        "verification_questions": sorted(set(questions)),
        "source_ref_count": card.get("source_ref_count"),
        "signal_count": card.get("signal_count"),
        "evidence_label": card.get("evidence_label"),
        "has_source_supported_deadline": deadline is not None,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def _validate_filters(filters: dict[str, Any], contract: dict[str, Any]) -> None:
    require(isinstance(filters, dict), "triage filters must be an object")
    unknown = set(filters) - set(contract["allowed_filters"])
    require(not unknown, f"unknown triage filter: {sorted(unknown)}")
    if "state" in filters:
        require(isinstance(filters["state"], str) and filters["state"].strip(), "invalid state filter")
    if "selected_service_id" in filters:
        require(isinstance(filters["selected_service_id"], str) and filters["selected_service_id"].strip(),
                "invalid selected service filter")
    if "has_source_supported_deadline" in filters:
        require(isinstance(filters["has_source_supported_deadline"], bool), "invalid deadline-presence filter")


def _matches_filters(card: dict[str, Any], filters: dict[str, Any]) -> bool:
    if "state" in filters and card["state"] != filters["state"]:
        return False
    if "selected_service_id" in filters and card["selected_service_id"] != filters["selected_service_id"]:
        return False
    if "has_source_supported_deadline" in filters:
        if card["has_source_supported_deadline"] is not filters["has_source_supported_deadline"]:
            return False
    return True


def _sort_cards(cards: list[dict[str, Any]], sort_mode: str) -> None:
    if sort_mode == "RESEARCH_PRIORITY":
        cards.sort(key=lambda card: (card["source_rank"], card["prospect_id"]))
        return
    if sort_mode == "SCORE_DESC":
        cards.sort(key=lambda card: (
            card["priority_score"] is None,
            -(card["priority_score"] if card["priority_score"] is not None else -1),
            card["source_rank"],
            card["prospect_id"],
        ))
        return
    if sort_mode == "DEADLINE_ASC":
        cards.sort(key=lambda card: (
            not card["has_source_supported_deadline"],
            (card["selected_opportunity"] or {}).get("source_supported_deadline") or "",
            card["source_rank"],
            card["prospect_id"],
        ))
        return
    raise ValueError("unsupported triage sort mode")


def build_triage_view(
    priority_result: dict[str, Any],
    filters: dict[str, Any] | None = None,
    sort_mode: str | None = None,
    contract: dict[str, Any] | None = None,
    priority_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or load_json(DEFAULT_CONTRACT_PATH)
    priority_contract = priority_contract or load_json(DEFAULT_PRIORITY_CONTRACT_PATH)
    validate_contract(contract, priority_contract)
    require(isinstance(priority_result, dict), "priority view must be an object")
    require(priority_result.get("contract_id") == contract["source_contract_id"], "priority view contract mismatch")
    require(priority_result.get("view_state") == contract["source_view_state"], "priority view state mismatch")
    require(priority_result.get("eligibility_state") == contract["required_eligibility_state"],
            "priority eligibility boundary failed open")
    require(priority_result.get("maximum_next_state") == contract["required_maximum_next_state"],
            "priority research boundary failed open")
    require(priority_result.get("human_review_required") is True, "priority human review requirement missing")
    for flag in DISABLED_ACTION_FLAGS:
        require(priority_result.get(flag) is False, f"priority {flag} failed open")

    raw_cards = priority_result.get("cards")
    require(isinstance(raw_cards, list), "priority cards must be a list")
    if FORBIDDEN_PERSON_KEYS & set(recursive_keys(raw_cards)):
        raise ValueError("person-level field entered Client Finder triage view")

    applied_filters = dict(filters or {})
    _validate_filters(applied_filters, contract)
    applied_sort = sort_mode or contract["default_sort_mode"]
    require(applied_sort in contract["allowed_sort_modes"], "unsupported triage sort mode")

    cards = [_validated_card(card, contract) for card in raw_cards]
    require(len({card["prospect_id"] for card in cards}) == len(cards), "duplicate triage prospect id")
    cards = [card for card in cards if _matches_filters(card, applied_filters)]
    _sort_cards(cards, applied_sort)
    for triage_rank, card in enumerate(cards, start=1):
        card["triage_rank"] = triage_rank

    output = contract["output"]
    return {
        "schema_version": 1,
        "contract_id": contract["id"],
        "source_contract_id": contract["source_contract_id"],
        "view_state": output["view_state"],
        "eligibility_state": output["eligibility_state"],
        "maximum_next_state": output["maximum_next_state"],
        "bridge_state": priority_result.get("bridge_state"),
        "filters": applied_filters,
        "sort_mode": applied_sort,
        "summary": {
            "source_cards": len(raw_cards),
            "visible_cards": len(cards),
            "with_source_supported_deadline": sum(card["has_source_supported_deadline"] for card in cards),
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
    parser = argparse.ArgumentParser(description="Build a deterministic, non-writing Client Finder operator triage view")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--filters", type=Path)
    parser.add_argument("--sort", choices=("RESEARCH_PRIORITY", "SCORE_DESC", "DEADLINE_ASC"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    filter_payload = load_json(args.filters) if args.filters else None
    result = build_triage_view(load_json(args.input), filters=filter_payload, sort_mode=args.sort)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
