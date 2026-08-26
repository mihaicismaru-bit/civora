#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"
CONTRACT_PATH = EUCONS / "prospects" / "prospect_opportunity_match_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


matcher = load_module("r07_match_fail_closed", EUCONS / "prospects" / "prospect_opportunity_match.py")
engine = load_module("r07_engine_fail_closed", EUCONS / "prospects" / "client_finder_engine.py")
validator = load_module("r07_validator_helpers", EUCONS / "validation" / "validate_prospect_opportunity_match.py")


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    state = validator.build_state(engine, payload)
    projection = validator.synthetic_fresh_projection(payload["reference_time"])
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    unsafe_semantics = deepcopy(contract)
    unsafe_semantics["match_semantics"] = "ELIGIBILITY_AND_BUYING_INTENT"
    must_fail("unsafe match semantics", lambda: matcher.match_state(state, projection, payload["reference_time"], unsafe_semantics))

    unsafe_output = deepcopy(contract)
    unsafe_output["outputs"]["eligibility_state"] = "ELIGIBLE"
    must_fail("eligibility output", lambda: matcher.match_state(state, projection, payload["reference_time"], unsafe_output))

    unsafe_contact = deepcopy(contract)
    unsafe_contact["outputs"]["external_contact_enabled"] = True
    must_fail("external contact enabled", lambda: matcher.match_state(state, projection, payload["reference_time"], unsafe_contact))

    incomplete_types = deepcopy(contract)
    incomplete_types["profile_projection"]["organization_type_labels"].pop("NGO")
    must_fail("organization profile taxonomy incomplete", lambda: matcher.match_state(state, projection, payload["reference_time"], incomplete_types))

    mutable_projection = deepcopy(projection)
    mutable_projection["read_only"] = False
    must_fail("mutable opportunity projection", lambda: matcher.match_state(state, mutable_projection, payload["reference_time"]))

    future_projection = deepcopy(projection)
    future_projection["generated_at"] = "2026-08-27T01:20:00+03:00"
    must_fail("future opportunity projection", lambda: matcher.match_state(state, future_projection, payload["reference_time"]))

    missing_provenance = deepcopy(projection)
    missing_provenance["opportunities"][0]["provenance"]["verification_evidence"] = []
    must_fail("verified opportunity without evidence", lambda: matcher.match_state(state, missing_provenance, payload["reference_time"]))

    person_state = deepcopy(state)
    first_key = next(iter(person_state["records"]))
    person_state["records"][first_key]["organization"]["personal_email"] = "person@example.invalid"
    must_fail("person-level prospect field", lambda: matcher.match_state(person_state, projection, payload["reference_time"]))

    conflict_state = deepcopy(state)
    conflict_key = next(iter(conflict_state["records"]))
    conflict_record = conflict_state["records"][conflict_key]
    second_source = deepcopy(conflict_record["sources"][0])
    second_source["source_id"] = "SRC-R07-CONFLICT"
    second_source["url"] = "https://example.invalid/r07-conflict"
    second_source["content_hash"] = "e" * 64
    conflict_record["sources"].append(second_source)
    conflict_record["assertions"].append({
        "assertion_id": "AST-R07-CONFLICT",
        "classification": "CONFLICT",
        "subject": "funding_need",
        "statement": "Synthetic sources conflict about the need.",
        "source_refs": [conflict_record["sources"][0]["source_id"], second_source["source_id"]]
    })
    conflict_record["state"] = "HOLD_CONFLICT"
    conflict = matcher.match_state(conflict_state, projection, payload["reference_time"])
    conflict_row = next(row for row in conflict["results"] if row["organization_key"] == conflict_key)
    if conflict_row["state"] != "HOLD_CONFLICT" or conflict_row["selected_opportunity_id"] is not None:
        raise AssertionError("conflict was matched instead of held")

    suppressed_state = deepcopy(state)
    suppressed_key = next(iter(suppressed_state["records"]))
    suppressed_state["records"][suppressed_key]["state"] = "SUPPRESSED"
    suppressed_state["records"][suppressed_key]["suppression"] = {"active": True, "reason": "SYNTHETIC_SUPPRESSION"}
    suppressed = matcher.match_state(suppressed_state, projection, payload["reference_time"])
    suppressed_row = next(row for row in suppressed["results"] if row["organization_key"] == suppressed_key)
    if suppressed_row["state"] != "SUPPRESSED" or suppressed_row["next_best_action"] != "NO_ACTION_SUPPRESSED":
        raise AssertionError("suppressed prospect received an action")

    stale = deepcopy(projection)
    stale["bridge_state"] = "STALE_SOURCE_HOLD"
    stale["opportunities"][0]["commercial_state"] = "HOLD_STALE_SOURCE"
    stale["opportunities"][0]["actionable"] = False
    held = matcher.match_state(state, stale, payload["reference_time"])
    if held["summary"]["held_source"] != held["summary"]["evaluated_prospects"]:
        raise AssertionError("stale bridge did not hold all prospects")
    if any(row["external_contact_enabled"] or row["automatic_offer_enabled"] for row in held["results"]):
        raise AssertionError("external action opened on held results")

    print("PASS: R07 rejects unsafe semantics, mutable/future/unproven projections and person data; conflicts, suppression and stale sources remain held before matching")


if __name__ == "__main__":
    main()
