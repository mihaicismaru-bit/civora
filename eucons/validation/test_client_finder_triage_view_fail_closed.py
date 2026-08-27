#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"
MATCH_CONTRACT_PATH = EUCONS / "prospects" / "prospect_opportunity_match_contract.json"
PRIORITY_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_priority_view_contract.json"
TRIAGE_CONTRACT_PATH = EUCONS / "prospects" / "client_finder_triage_view_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matcher = load_module("r07_match_triage", EUCONS / "prospects" / "prospect_opportunity_match.py")
engine = load_module("r07_engine_triage", EUCONS / "prospects" / "client_finder_engine.py")
validator = load_module("r07_validator_triage", EUCONS / "validation" / "validate_prospect_opportunity_match.py")
priority_view = load_module("r07_priority_triage", EUCONS / "prospects" / "client_finder_priority_view.py")
triage_view = load_module("r07_triage_fail_closed", EUCONS / "prospects" / "client_finder_triage_view.py")


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def main() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    state = validator.build_state(engine, payload)
    projection = validator.synthetic_fresh_projection(payload["reference_time"])
    match_contract = json.loads(MATCH_CONTRACT_PATH.read_text(encoding="utf-8"))
    priority_contract = json.loads(PRIORITY_CONTRACT_PATH.read_text(encoding="utf-8"))
    triage_contract = json.loads(TRIAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    match_result = matcher.match_state(state, projection, payload["reference_time"], match_contract)
    priority_result = priority_view.build_priority_view(match_result, priority_contract, match_contract)
    triage = triage_view.build_triage_view(priority_result, contract=triage_contract, priority_contract=priority_contract)

    if triage["view_state"] != "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW":
        raise AssertionError("triage view state drift")
    if triage["summary"]["source_cards"] != len(priority_result["cards"]):
        raise AssertionError("triage source card count drift")
    if [card["prospect_id"] for card in triage["cards"]] != [card["prospect_id"] for card in priority_result["cards"]]:
        raise AssertionError("default triage order no longer preserves research priority")
    if any(triage[flag] for flag in (
        "external_contact_enabled",
        "automatic_offer_enabled",
        "automatic_send_enabled",
        "crm_write_enabled",
        "pipeline_write_enabled",
    )):
        raise AssertionError("triage view opened an external or persistence action")

    service_id = "funding_strategy_and_eligibility"
    service_filtered = triage_view.build_triage_view(
        priority_result,
        filters={"selected_service_id": service_id},
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if not service_filtered["cards"] or any(card["selected_service_id"] != service_id for card in service_filtered["cards"]):
        raise AssertionError("service triage filter returned an unsafe card")

    score_sorted = triage_view.build_triage_view(
        priority_result,
        sort_mode="SCORE_DESC",
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    scores = [card["priority_score"] for card in score_sorted["cards"] if card["priority_score"] is not None]
    if scores != sorted(scores, reverse=True):
        raise AssertionError("score-desc triage ordering drift")

    deadline_sorted = triage_view.build_triage_view(
        priority_result,
        sort_mode="DEADLINE_ASC",
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    deadline_flags = [card["has_source_supported_deadline"] for card in deadline_sorted["cards"]]
    if False in deadline_flags and True in deadline_flags:
        first_false = deadline_flags.index(False)
        if any(deadline_flags[first_false:]):
            raise AssertionError("deadline triage ordering placed unsupported deadline ahead of supported deadline")

    deadline_filtered = triage_view.build_triage_view(
        priority_result,
        filters={"has_source_supported_deadline": True},
        contract=triage_contract,
        priority_contract=priority_contract,
    )
    if any(not card["has_source_supported_deadline"] for card in deadline_filtered["cards"]):
        raise AssertionError("deadline-presence filter failed open")

    if canonical(triage) != canonical(triage_view.build_triage_view(
        priority_result, contract=triage_contract, priority_contract=priority_contract
    )):
        raise AssertionError("Client Finder triage view is not deterministic")

    must_fail(
        "unknown triage filter",
        lambda: triage_view.build_triage_view(
            priority_result,
            filters={"buying_intent": "HIGH"},
            contract=triage_contract,
            priority_contract=priority_contract,
        ),
    )
    must_fail(
        "unknown triage sort",
        lambda: triage_view.build_triage_view(
            priority_result,
            sort_mode="BUYING_INTENT_DESC",
            contract=triage_contract,
            priority_contract=priority_contract,
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
    deadline_card = next((card for card in unsafe_deadline["cards"] if card.get("selected_opportunity")), None)
    if deadline_card is not None:
        deadline_card["selected_opportunity"]["source_supported_deadline"] = "2099-12-31"
        deadline_card["selected_opportunity"]["verified_fact_classes"] = [
            value for value in deadline_card["selected_opportunity"].get("verified_fact_classes", [])
            if value != "deadline"
        ]
        must_fail(
            "triage unsupported deadline",
            lambda: triage_view.build_triage_view(
                unsafe_deadline, contract=triage_contract, priority_contract=priority_contract
            ),
        )

    unsafe_service = deepcopy(priority_result)
    selected_card = next((card for card in unsafe_service["cards"] if card.get("selected_service_id")), None)
    if selected_card is not None:
        selected_card["selected_opportunity"]["selected_service_id"] = "DIFFERENT_SERVICE"
        must_fail(
            "triage mismatched service",
            lambda: triage_view.build_triage_view(
                unsafe_service, contract=triage_contract, priority_contract=priority_contract
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

    print(
        "PASS: Client Finder triage filtering/sorting is deterministic, person-safe, source-supported and non-writing"
    )


if __name__ == "__main__":
    main()
