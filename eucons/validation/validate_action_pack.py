#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
FIXTURE_PATH = EUCONS / "prospects" / "fixtures" / "client_finder_queue_non_evidence.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    engine = load_module("r08_action_pack_validator", EUCONS / "outreach" / "action_pack.py")
    client = load_module("r08_client_engine_validator", EUCONS / "prospects" / "client_finder_engine.py")
    matcher = load_module("r08_matcher_validator", EUCONS / "prospects" / "prospect_opportunity_match.py")
    fixture_helper = load_module("r08_r07_fixture_helper", EUCONS / "validation" / "validate_prospect_opportunity_match.py")
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    reference_time = payload["reference_time"]
    state = fixture_helper.build_state(client, payload)
    projection = fixture_helper.synthetic_fresh_projection(reference_time)
    matches = matcher.match_state(state, projection, reference_time)
    state_before = client.canonical_hash(state)
    matches_before = client.canonical_hash(matches)

    result = engine.build_action_packs(state, matches, reference_time)
    if result["summary"] != {"evaluated": 2, "ready_for_approval": 1, "held": 1, "suppressed": 0}:
        raise SystemExit("R08 action-pack summary drift")
    by_prospect = {row["prospect_id"]: row for row in result["results"]}
    ready = by_prospect["PROS-SYNTH-B"]
    held = by_prospect["PROS-SYNTH-A"]
    if ready["state"] != "READY_FOR_APPROVAL" or ready["action_pack"] is None:
        raise SystemExit("matched synthetic prospect did not produce an approval-gated pack")
    if held["state"] != "HOLD_RESEARCH_INCOMPLETE" or held["action_pack"] is not None:
        raise SystemExit("non-matched prospect received an action pack")

    pack = ready["action_pack"]
    if pack["eligibility_state"] != "NOT_ASSESSED" or pack["approval_state"] != "READY_FOR_APPROVAL":
        raise SystemExit("R08 crossed eligibility or approval boundary")
    if any(pack[key] for key in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled")):
        raise SystemExit("R08 opened an external action")
    if pack["outreach_draft"]["target"]["person"] is not None or pack["outreach_draft"]["target"]["contact_surface"] is not None:
        raise SystemExit("R08 targeted a person or invented a contact surface")
    if pack["outreach_draft"]["send_state"] != "BLOCKED_HUMAN_APPROVAL_AND_CONTACT_GOVERNANCE":
        raise SystemExit("R08 draft is not blocked for human approval")
    if pack["contact_governance"]["lawful_basis_assessment"] != "REVIEW_REQUIRED":
        raise SystemExit("lawful-basis assessment failed open")
    if pack["offer_skeleton"]["pricing"] != {"state": "HUMAN_REQUIRED", "amount_minor": None, "currency": None, "binding": False}:
        raise SystemExit("R08 generated a price or binding commercial term")
    if not pack["why_now_brief"]["facts"] or any(row["classification"] != "FACT" or not row["source_refs"] for row in pack["why_now_brief"]["facts"]):
        raise SystemExit("why-now brief is not fact-bound")
    questions = {row["question"] for row in pack["discovery_questions"]}
    if "Is external funding being considered for the investment?" not in questions:
        raise SystemExit("inference did not remain a discovery question")
    serialized_draft = json.dumps(pack["outreach_draft"], ensure_ascii=False).casefold()
    if "the investment may justify a funding-route review" in serialized_draft:
        raise SystemExit("inference leaked into the outreach statement")
    for forbidden_claim in ("este eligibil", "probabilitate de aprobare", "intenție de cumpărare"):
        if forbidden_claim in serialized_draft:
            raise SystemExit("forbidden commercial conclusion entered outreach")
    if client.canonical_hash(state) != state_before or client.canonical_hash(matches) != matches_before:
        raise SystemExit("R08 mutated an upstream input")

    repeated = engine.build_action_packs(state, matches, reference_time)
    if client.canonical_hash(result) != client.canonical_hash(repeated):
        raise SystemExit("R08 action-pack output is not deterministic")
    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "action-packs.json"
        engine.assert_output_path_safe(output)
        client.write_atomic(output, result)
        readback = json.loads(output.read_text(encoding="utf-8"))
        if client.canonical_hash(readback) != client.canonical_hash(result):
            raise SystemExit("R08 atomic readback drift")

    print(json.dumps({
        "status": "PASS",
        "unit": "R08-ACTION-PACK-001",
        "evaluated": result["summary"]["evaluated"],
        "ready_for_approval": result["summary"]["ready_for_approval"],
        "held": result["summary"]["held"],
        "fact_cards": len(pack["why_now_brief"]["facts"]),
        "discovery_questions": len(pack["discovery_questions"]),
        "pricing_state": pack["offer_skeleton"]["pricing"]["state"],
        "lawful_basis": pack["contact_governance"]["lawful_basis_assessment"],
        "production_records": result["production_records"],
        "external_contact": result["external_contact_enabled"]
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
