#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
PRIORITY_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_priority_view_contract.json"
TRIAGE_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_triage_view_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


triage_view = load_module("r07_triage_fail_closed", EUCONS / "prospects" / "client_finder_triage_view.py")


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def synthetic_priority_result(priority_contract: dict) -> dict:
    safe_flags = {
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }
    return {
        "schema_version": 1,
        "contract_id": priority_contract["id"],
        "view_state": priority_contract["output"]["view_state"],
        "match_semantics": priority_contract["source_match_semantics"],
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "bridge_state": "READY",
        "summary": {"cards": 2, "matched": 1, "needs_verification": 1, "held": 0, "suppressed": 0},
        "cards": [
            {
                "rank": 1,
                "prospect_id": "PROS-SYNTH-A",
                "organization_key": "ORG-SYNTH-A",
                "state": "MATCHED_RESEARCH_CANDIDATE",
                "priority_state": "PRIORITY_HIGH_RESEARCH",
                "priority_score": 70,
                "attention_reason": "VERIFIED_OPPORTUNITY_SERVICE_OVERLAP",
                "selected_opportunity": {
                    "opportunity_id": "OPP-SYNTH-A",
                    "title": "Synthetic verified opportunity",
                    "programme": "Synthetic programme",
                    "relevance_score": 80,
                    "selected_service_id": "funding_strategy_and_eligibility",
                    "source_supported_deadline": "2026-09-30",
                    "verified_fact_classes": ["deadline", "programme"],
                },
                "selected_service_id": "funding_strategy_and_eligibility",
                "safe_next_action": "VERIFY_RESEARCH_CANDIDATE",
                "verification_questions": ["Confirm organization-level fit."],
                "source_ref_count": 2,
                "signal_count": 2,
                "evidence_label": "SOURCE_SUPPORTED_RESEARCH_MATCH",
                **safe_flags,
            },
            {
                "rank": 2,
                "prospect_id": "PROS-SYNTH-B",
                "organization_key": "ORG-SYNTH-B",
                "state": "REQUIRES_VERIFICATION",
                "priority_state": "PRIORITY_MEDIUM_RESEARCH",
                "priority_score": 90,
                "attention_reason": "ORGANIZATION_OR_PROJECT_FACTS_INCOMPLETE",
                "selected_opportunity": None,
                "selected_service_id": None,
                "safe_next_action": "VERIFY_ORGANIZATION_FACTS",
                "verification_questions": ["Verify organization-level facts."],
                "source_ref_count": 1,
                "signal_count": 1,
                "evidence_label": "REQUIRES_VERIFICATION",
                **safe_flags,
            },
        ],
        **safe_flags,
    }


def main() -> None:
    priority_contract = json.loads(PRIORITY_CONTRACT_PATH.read_text(encoding="utf-8"))
    triage_contract = json.loads(TRIAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    priority_result = synthetic_priority_result(priority_contract)

    triage = triage_view.build_triage_view(priority_result, contract=triage_contract, priority_contract=priority_contract)
    if triage["view_state"] != "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW":
        raise AssertionError("triage view state drift")
    if [card["prospect_id"] for card in triage["cards"]] != ["PROS-SYNTH-A", "PROS-SYNTH-B"]:
        raise AssertionError("default triage order no longer preserves research priority")
    if any(triage[flag] for flag in (
        "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
        "crm_write_enabled", "pipeline_write_enabled",
    )):
        raise AssertionError("triage view opened an external or persistence action")

    service_filtered = triage_view.build_triage_view(
        priority_result,
        filters={"selected_service_id": "funding_strategy_and_eligibility"},
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if [card["prospect_id"] for card in service_filtered["cards"]] != ["PROS-SYNTH-A"]:
        raise AssertionError("service triage filter returned an unsafe card")

    state_filtered = triage_view.build_triage_view(
        priority_result,
        filters={"state": "REQUIRES_VERIFICATION"},
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if [card["prospect_id"] for card in state_filtered["cards"]] != ["PROS-SYNTH-B"]:
        raise AssertionError("state triage filter returned an unsafe card")

    deadline_filtered = triage_view.build_triage_view(
        priority_result,
        filters={"has_source_supported_deadline": True},
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if [card["prospect_id"] for card in deadline_filtered["cards"]] != ["PROS-SYNTH-A"]:
        raise AssertionError("deadline-presence filter failed open")

    score_sorted = triage_view.build_triage_view(
        priority_result,
        sort_mode="SCORE_DESC",
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if [card["prospect_id"] for card in score_sorted["cards"]] != ["PROS-SYNTH-B", "PROS-SYNTH-A"]:
        raise AssertionError("score-desc triage ordering drift")

    deadline_sorted = triage_view.build_triage_view(
        priority_result,
        sort_mode="DEADLINE_ASC",
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if [card["prospect_id"] for card in deadline_sorted["cards"]] != ["PROS-SYNTH-A", "PROS-SYNTH-B"]:
        raise AssertionError("deadline triage ordering drift")

    if canonical(triage) != canonical(triage_view.build_triage_view(
        priority_result, contract=triage_contract, priority_contract=priority_contract
    )):
        raise AssertionError("Client Finder triage view is not deterministic")

    must_fail(
        "unknown triage filter",
        lambda: triage_view.build_triage_view(
            priority_result, filters={"buying_intent": "HIGH"},
            contract=triage_contract, priority_contract=priority_contract,
        ),
    )
    must_fail(
        "unknown triage sort",
        lambda: triage_view.build_triage_view(
            priority_result, sort_mode="BUYING_INTENT_DESC",
            contract=triage_contract, priority_contract=priority_contract,
        ),
    )

    person_priority = deepcopy(priority_result)
    person_priority["cards"][0]["personal_email"] = "person@example.invalid"
    must_fail(
        "triage person-level field",
        lambda: triage_view.build_triage_view(
            person_priority, contract=triage_contract, priority_contract=priority_contract
        ),
    )

    unsafe_deadline = deepcopy(priority_result)
    unsafe_deadline["cards"][0]["selected_opportunity"]["verified_fact_classes"] = ["programme"]
    must_fail(
        "triage unsupported deadline",
        lambda: triage_view.build_triage_view(
            unsafe_deadline, contract=triage_contract, priority_contract=priority_contract
        ),
    )

    unsafe_service = deepcopy(priority_result)
    unsafe_service["cards"][0]["selected_opportunity"]["selected_service_id"] = "DIFFERENT_SERVICE"
    must_fail(
        "triage mismatched service",
        lambda: triage_view.build_triage_view(
            unsafe_service, contract=triage_contract, priority_contract=priority_contract
        ),
    )

    unsafe_source_action = deepcopy(priority_result)
    unsafe_source_action["cards"][0]["crm_write_enabled"] = True
    must_fail(
        "source card CRM write enabled",
        lambda: triage_view.build_triage_view(
            unsafe_source_action, contract=triage_contract, priority_contract=priority_contract
        ),
    )

    unsafe_contract = deepcopy(triage_contract)
    unsafe_contract["output"]["crm_write_enabled"] = True
    must_fail(
        "triage CRM write enabled",
        lambda: triage_view.build_triage_view(
            priority_result, contract=unsafe_contract, priority_contract=priority_contract
        ),
    )

    print("PASS: Client Finder triage filtering/sorting is deterministic, person-safe, source-supported and non-writing")


if __name__ == "__main__":
    main()
