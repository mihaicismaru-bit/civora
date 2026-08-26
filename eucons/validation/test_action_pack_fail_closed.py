#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"
CONTRACT_PATH = EUCONS / "outreach" / "action_pack_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    action = load_module("r08_action_pack_fail_closed", EUCONS / "outreach" / "action_pack.py")
    client = load_module("r08_client_engine_fail_closed", EUCONS / "prospects" / "client_finder_engine.py")
    matcher = load_module("r08_matcher_fail_closed", EUCONS / "prospects" / "prospect_opportunity_match.py")
    fixture_helper = load_module("r08_fixture_helper_fail_closed", EUCONS / "validation" / "validate_prospect_opportunity_match.py")
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    reference_time = payload["reference_time"]
    state = fixture_helper.build_state(client, payload)
    projection = fixture_helper.synthetic_fresh_projection(reference_time)
    matches = matcher.match_state(state, projection, reference_time)
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    person_targeting = deepcopy(contract)
    person_targeting["contact_governance"]["person_targeting_allowed"] = True
    must_fail("person targeting", lambda: action.build_action_packs(state, matches, reference_time, contract=person_targeting))

    private_contact = deepcopy(contract)
    private_contact["contact_governance"]["private_contact_data_allowed"] = True
    must_fail("private contact data", lambda: action.build_action_packs(state, matches, reference_time, contract=private_contact))

    numeric_price = deepcopy(contract)
    numeric_price["commercial_boundary"]["numeric_price_allowed"] = True
    must_fail("numeric price", lambda: action.build_action_packs(state, matches, reference_time, contract=numeric_price))

    auto_send = deepcopy(contract)
    auto_send["external_action_gate"]["autonomous_send"] = True
    must_fail("autonomous send", lambda: action.build_action_packs(state, matches, reference_time, contract=auto_send))

    lawful_basis = deepcopy(contract)
    lawful_basis["contact_governance"]["lawful_basis_default_state"] = "APPROVED"
    must_fail("pre-approved lawful basis", lambda: action.build_action_packs(state, matches, reference_time, contract=lawful_basis))

    inference_as_fact = deepcopy(contract)
    inference_as_fact["truth_policy"]["outreach_statement_allowed_classes"] = ["FACT", "INFERENCE"]
    must_fail("inference in outreach", lambda: action.build_action_packs(state, matches, reference_time, contract=inference_as_fact))

    eligible = deepcopy(matches)
    eligible["eligibility_state"] = "ELIGIBLE"
    must_fail("inferred eligibility", lambda: action.build_action_packs(state, eligible, reference_time))

    person_state = deepcopy(state)
    first_key = next(iter(person_state["records"]))
    person_state["records"][first_key]["organization"]["personal_email"] = "person@example.invalid"
    must_fail("person-level input", lambda: action.build_action_packs(person_state, matches, reference_time))

    unknown_service = deepcopy(matches)
    ready = next(row for row in unknown_service["results"] if row["state"] == "MATCHED_RESEARCH_CANDIDATE")
    ready["recommended_service_id"] = "invented_service"
    must_fail("unknown service", lambda: action.build_action_packs(state, unknown_service, reference_time))

    missing_source = deepcopy(state)
    ready_match = next(row for row in matches["results"] if row["state"] == "MATCHED_RESEARCH_CANDIDATE")
    ready_record = missing_source["records"][ready_match["organization_key"]]
    fact_id = ready_match["truth"]["facts"][0]
    next(row for row in ready_record["assertions"] if row["assertion_id"] == fact_id)["source_refs"] = []
    must_fail("fact without source", lambda: action.build_action_packs(missing_source, matches, reference_time))

    suppressed_state = deepcopy(state)
    suppressed_match = deepcopy(matches)
    ready_match = next(row for row in suppressed_match["results"] if row["state"] == "MATCHED_RESEARCH_CANDIDATE")
    suppressed_state["records"][ready_match["organization_key"]]["state"] = "SUPPRESSED"
    suppressed_state["records"][ready_match["organization_key"]]["suppression"] = {"active": True, "reason": "SYNTHETIC_SUPPRESSION"}
    ready_match["state"] = "SUPPRESSED"
    suppressed = action.build_action_packs(suppressed_state, suppressed_match, reference_time)
    row = next(item for item in suppressed["results"] if item["prospect_id"] == ready_match["prospect_id"])
    if row["state"] != "SUPPRESSED" or row["action_pack"] is not None:
        raise AssertionError("suppressed prospect received an action pack")

    stale_matches = matcher.match_state(state, {**deepcopy(projection), "bridge_state": "STALE_SOURCE_HOLD"}, reference_time)
    stale = action.build_action_packs(state, stale_matches, reference_time)
    if any(row["action_pack"] is not None for row in stale["results"]):
        raise AssertionError("stale source produced an action pack")

    must_fail("repository output", lambda: action.assert_output_path_safe(EUCONS / "outreach" / "runtime-action-pack.json"))
    print("PASS: R08 rejects person targeting, private contacts, prices, inference-as-fact, unsafe eligibility and autonomous send; suppression and stale research produce no action pack")


if __name__ == "__main__":
    main()
