#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
SCORER_PATH = EUCONS / "prospects" / "prospect_scoring.py"
ENGINE_PATH = EUCONS / "prospects" / "client_finder_engine.py"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"
CONTRACT_PATH = EUCONS / "prospects" / "prospect_scoring_contract.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


scorer = load_module("prospect_scoring", SCORER_PATH)
engine = load_module("client_finder_engine_for_scoring_fail_closed", ENGINE_PATH)


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def main() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    state = engine.empty_state(payload["reference_time"])
    for observation in payload["observations"]:
        state = engine.ingest(state, observation["request_id"], observation["record"], payload["reference_time"])
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))

    bad_semantics = deepcopy(contract)
    bad_semantics["score_semantics"] = "ELIGIBILITY_PROBABILITY"
    must_fail("eligibility semantics", lambda: scorer.score_state(state, payload["reference_time"], bad_semantics))

    bad_total = deepcopy(contract)
    bad_total["positive_components"]["freshness"]["max_points"] = 21
    must_fail("positive total drift", lambda: scorer.score_state(state, payload["reference_time"], bad_total))

    missing_source_weight = deepcopy(contract)
    missing_source_weight["positive_components"]["source_quality"]["basis_points_by_source_type"].pop("PUBLIC_NEWS_DISCOVERY")
    must_fail("source weights incomplete", lambda: scorer.score_state(state, payload["reference_time"], missing_source_weight))

    unsafe_output = deepcopy(contract)
    unsafe_output["outputs"]["eligibility_state"] = "ELIGIBLE"
    must_fail("eligibility output", lambda: scorer.score_state(state, payload["reference_time"], unsafe_output))

    wrong_key = deepcopy(state)
    key = next(iter(wrong_key["records"]))
    wrong_key["records"]["0" * 64] = wrong_key["records"].pop(key)
    must_fail("identity key mismatch", lambda: scorer.score_state(wrong_key, payload["reference_time"]))

    person = deepcopy(state)
    first_key = next(iter(person["records"]))
    person["records"][first_key]["organization"]["personal_email"] = "person@example.invalid"
    must_fail("person data", lambda: scorer.score_state(person, payload["reference_time"]))

    unsafe_runtime = deepcopy(state)
    unsafe_runtime["production_collection_enabled"] = True
    must_fail("production runtime boundary", lambda: scorer.score_state(unsafe_runtime, payload["reference_time"]))

    must_fail("time rollback", lambda: scorer.score_state(state, "2026-08-25T23:00:00+03:00"))

    conflict = deepcopy(state)
    conflict_key = next(iter(conflict["records"]))
    record = conflict["records"][conflict_key]
    first_source = record["sources"][0]
    second_source = deepcopy(first_source)
    second_source["source_id"] = "SRC-SYNTH-CONFLICT"
    second_source["url"] = "https://example.invalid/synthetic-conflict"
    second_source["content_hash"] = "f" * 64
    record["sources"].append(second_source)
    record["assertions"].append({
        "assertion_id": "AST-SYNTH-CONFLICT",
        "classification": "CONFLICT",
        "subject": "synthetic_project_state",
        "statement": "Two synthetic sources conflict about project state.",
        "source_refs": [first_source["source_id"], second_source["source_id"]]
    })
    record["state"] = "HOLD_CONFLICT"
    held = scorer.score_state(conflict, payload["reference_time"])
    held_row = next(row for row in held["results"] if row["organization_key"] == conflict_key)
    if held_row["priority_state"] != "HOLD_CONFLICT" or held_row["score"] is not None or held_row["recommended_service_id"] is not None:
        raise AssertionError("conflict was ranked instead of held")

    suppressed = deepcopy(state)
    suppressed_key = next(iter(suppressed["records"]))
    suppressed["records"][suppressed_key]["state"] = "SUPPRESSED"
    suppressed["records"][suppressed_key]["suppression"] = {"active": True, "reason": "SYNTHETIC_SUPPRESSION"}
    suppressed_result = scorer.score_state(suppressed, payload["reference_time"])
    suppressed_row = next(row for row in suppressed_result["results"] if row["organization_key"] == suppressed_key)
    if suppressed_row["priority_state"] != "SUPPRESSED" or suppressed_row["score"] is not None:
        raise AssertionError("suppressed prospect was scored")

    print("PASS: prospect scoring rejects eligibility semantics, weight drift, identity/PII/runtime violations and holds conflicts or suppression before ranking")


if __name__ == "__main__":
    main()
