#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
SCORER_PATH = EUCONS / "prospects" / "prospect_scoring.py"
ENGINE_PATH = EUCONS / "prospects" / "client_finder_engine.py"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_state(engine, payload):
    state = engine.empty_state(payload["reference_time"])
    for observation in payload["observations"]:
        state = engine.ingest(state, observation["request_id"], observation["record"], payload["reference_time"])
    return state


def by_prospect(result: dict) -> dict:
    return {row["prospect_id"]: row for row in result["results"]}


def main() -> None:
    scorer = load_module("prospect_scoring", SCORER_PATH)
    engine = load_module("client_finder_engine_for_scoring", ENGINE_PATH)
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    state = build_state(engine, payload)

    baseline = scorer.score_state(state, payload["reference_time"])
    if baseline["score_semantics"] != "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY":
        raise SystemExit("prospect score semantics drift")
    if baseline["eligibility_state"] != "NOT_ASSESSED" or baseline["maximum_next_state"] != "RESEARCH_READY":
        raise SystemExit("scoring exceeded qualification boundary")
    if baseline["summary"]["evaluated"] != 2 or baseline["summary"]["held_or_suppressed"] != 0:
        raise SystemExit("baseline scoring cardinality drift")
    if any(row["priority_state"] == "PRIORITY_HIGH_RESEARCH" for row in baseline["results"]):
        raise SystemExit("single-signal record incorrectly reached high priority")
    if any(row["recommended_service_id"] not in {service["service_id"] for service in row["service_ranking"]} for row in baseline["results"]):
        raise SystemExit("recommended service is not signal-supported")

    multi = deepcopy(state)
    alfa_key = engine.VALIDATOR.organization_key(payload["observations"][0]["record"]["organization"])
    alfa = multi["records"][alfa_key]
    alfa["signals"].append({
        "signal_id": "SIGNAL-SYNTH-A-FRICTION",
        "signal_type": "SIG-IMPLEMENTATION-FRICTION",
        "source_refs": ["SRC-SYNTH-A"],
        "observed_at": "2026-08-26T01:12:00+03:00",
        "expires_at": "2026-09-09T01:12:00+03:00",
        "fact_assertion_ids": ["AST-A-FACT"],
        "confidence": 0.8,
        "why_now": "Synthetic implementation-friction signal inside its revalidation window.",
        "job_ids": ["JTBD-BEN-01"],
        "service_ids": ["implementation_and_reporting"]
    })
    multi_result = scorer.score_state(multi, payload["reference_time"])
    high = by_prospect(multi_result)["PROS-SYNTH-A"]
    if high["priority_state"] != "PRIORITY_HIGH_RESEARCH":
        raise SystemExit("multi-signal P0 prospect did not reach high research priority")
    if high["recommended_service_id"] != "implementation_and_reporting":
        raise SystemExit("dominant service recommendation drift")
    if high["eligibility_state"] != "NOT_ASSESSED":
        raise SystemExit("high score was converted into eligibility")

    uncertain = deepcopy(multi)
    beta_key = engine.VALIDATOR.organization_key(payload["observations"][2]["record"]["organization"])
    uncertain["records"][beta_key]["assertions"].append({
        "assertion_id": "AST-B-UNKNOWN",
        "classification": "UNKNOWN",
        "subject": "available_internal_capacity",
        "statement": "Synthetic fixture does not establish internal delivery capacity.",
        "source_refs": [],
        "verification_question": "What internal project-delivery capacity is already available?"
    })
    uncertain_result = scorer.score_state(uncertain, payload["reference_time"])
    beta_before = by_prospect(multi_result)["PROS-SYNTH-B"]
    beta_after = by_prospect(uncertain_result)["PROS-SYNTH-B"]
    if beta_after["penalties"]["unknown_assertions"] != 8 or beta_after["score"] != beta_before["score"] - 8:
        raise SystemExit("UNKNOWN penalty is not explicit and deterministic")
    if "What internal project-delivery capacity is already available?" not in beta_after["verification_questions"]:
        raise SystemExit("verification question lost")

    repeated = scorer.score_state(uncertain, payload["reference_time"])
    if engine.canonical_hash(uncertain_result) != engine.canonical_hash(repeated):
        raise SystemExit("prospect scoring is not deterministic")
    for row in uncertain_result["results"]:
        if row["score"] is not None and row["score"] != row["gross_score"] - row["penalties"]["total"]:
            raise SystemExit("score breakdown does not reconcile")
    serialized = json.dumps(uncertain_result, ensure_ascii=False).casefold()
    for forbidden in ("instituție sintetică alfa", "companie sintetică beta", "alfa.synthetic.invalid", "beta.synthetic.invalid"):
        if forbidden in serialized:
            raise SystemExit("identity field leaked into scoring output")

    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "scores.json"
        engine.write_atomic(output, uncertain_result)
        readback = json.loads(output.read_text(encoding="utf-8"))
        if engine.canonical_hash(readback) != engine.canonical_hash(uncertain_result):
            raise SystemExit("prospect score readback drift")

    print(json.dumps({
        "status": "PASS",
        "unit": "R06-CF-SCORING-001",
        "baseline_organizations": baseline["summary"]["evaluated"],
        "multi_signal_high_priority": high["prospect_id"],
        "recommended_service": high["recommended_service_id"],
        "unknown_penalty": beta_after["penalties"]["unknown_assertions"],
        "eligibility_state": high["eligibility_state"],
        "production_records": 0,
        "external_contact": False
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
