#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
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


def receipt(receipt_id: str, kind: str, at: str, details: dict, actor: str = "synthetic-human-reviewer") -> dict:
    return {
        "receipt_id": receipt_id,
        "kind": kind,
        "at": at,
        "actor": actor,
        "artifact_ref": f"synthetic://pipeline/{receipt_id}",
        "automated": False,
        "details": details,
    }


def main() -> None:
    pipeline = load_module("r10_pipeline", EUCONS / "crm" / "pipeline_engine.py")
    client = load_module("r10_client", EUCONS / "prospects" / "client_finder_engine.py")
    matcher = load_module("r10_matcher", EUCONS / "prospects" / "prospect_opportunity_match.py")
    action = load_module("r10_action", EUCONS / "outreach" / "action_pack.py")
    fixture = load_module("r10_fixture", EUCONS / "validation" / "validate_prospect_opportunity_match.py")
    contract = json.loads((EUCONS / "crm" / "pipeline_contract.json").read_text(encoding="utf-8"))
    pipeline.validate_contract(contract)

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    source_state = fixture.build_state(client, payload)
    matches = matcher.match_state(source_state, fixture.synthetic_fresh_projection(payload["reference_time"]), payload["reference_time"])
    action_packs = action.build_action_packs(source_state, matches, payload["reference_time"])
    matched = next(row for row in matches["results"] if row["state"] == "MATCHED_RESEARCH_CANDIDATE")
    prepared = next(row for row in action_packs["results"] if row["state"] == "READY_FOR_APPROVAL")
    pack = prepared["action_pack"]

    state0 = pipeline.empty_state("2026-08-26T01:20:00+03:00", contract)
    attribution = {
        "origin": "PROSPECT_DISCOVERY",
        "first_touch_ref": "SRC-SYNTH-B",
        "source_refs": ["SRC-SYNTH-B"],
        "assisted_content_refs": [],
    }
    state1, record_id = pipeline.ingest(
        state0,
        "REQ-R10-PROSPECT-001",
        "PROSPECT_DISCOVERY",
        matched["prospect_id"],
        matched["organization_key"],
        attribution,
        next_action="HUMAN_QUALIFICATION_REVIEW",
        due_at="2026-08-27T09:00:00+03:00",
        at="2026-08-26T01:20:00+03:00",
        contract=contract,
    )
    assert state0 == pipeline.empty_state("2026-08-26T01:20:00+03:00", contract), "ingest mutated prior state"
    replay, replay_id = pipeline.ingest(
        state1,
        "REQ-R10-PROSPECT-001",
        "PROSPECT_DISCOVERY",
        matched["prospect_id"],
        matched["organization_key"],
        attribution,
        next_action="HUMAN_QUALIFICATION_REVIEW",
        due_at="2026-08-27T09:00:00+03:00",
        at="2026-08-26T01:20:00+03:00",
        contract=contract,
    )
    assert replay_id == record_id and pipeline.canonical_hash(replay) == pipeline.canonical_hash(state1)

    qualification_receipt = receipt(
        "REC-QUAL-001", "QUALIFICATION_REVIEW", "2026-08-26T01:30:00+03:00",
        {"qualified": True, "basis": "SYNTHETIC_ORGANIZATION_SIGNAL_REVIEW"},
    )
    state2 = pipeline.transition(state1, record_id, "QUALIFIED", qualification_receipt, next_action="VERIFY_MATCH", due_at="2026-08-27T09:00:00+03:00", contract=contract)
    transition_replay = pipeline.transition(state2, record_id, "QUALIFIED", qualification_receipt, next_action="VERIFY_MATCH", due_at="2026-08-27T09:00:00+03:00", contract=contract)
    assert pipeline.canonical_hash(transition_replay) == pipeline.canonical_hash(state2)
    state3 = pipeline.transition(state2, record_id, "MATCHED", receipt(
        "REC-MATCH-001", "R07_MATCH_RECORD", "2026-08-26T01:40:00+03:00",
        {
            "engine_id": matches["engine_id"],
            "state": matched["state"],
            "eligibility_state": matched["eligibility_state"],
            "maximum_next_state": matched["maximum_next_state"],
            "opportunity_id": matched["selected_opportunity_id"],
            "service_id": matched["recommended_service_id"],
            "source_provenance_ref": matched["opportunity_matches"][0]["source_provenance"]["source_projection_sha256"],
        },
    ), next_action="PREPARE_ACTION_PACK", due_at="2026-08-27T09:00:00+03:00", contract=contract)
    state4 = pipeline.transition(state3, record_id, "OUTREACH_PREPARED", receipt(
        "REC-PACK-001", "R08_ACTION_PACK", "2026-08-26T01:50:00+03:00",
        {
            "engine_id": action_packs["engine_id"],
            "state": prepared["state"],
            "eligibility_state": pack["eligibility_state"],
            "maximum_state": action_packs["maximum_state"],
            "action_pack_id": pack["action_pack_id"],
        },
    ), next_action="REVIEW_CONTACT_GOVERNANCE", due_at="2026-08-27T09:00:00+03:00", contract=contract)

    stale = pipeline.stale_report(state4, "2026-09-01T02:00:00+03:00", contract)
    assert stale["stale_count"] == 1 and stale["records"][0]["stage"] == "OUTREACH_PREPARED"
    assert stale["automatic_contact_enabled"] is False

    state5 = pipeline.transition(state4, record_id, "CONTACT_APPROVED", receipt(
        "REC-CONTACT-APPROVAL-001", "HUMAN_CONTACT_APPROVAL", "2026-08-26T02:00:00+03:00",
        {"lawful_basis_reviewed": True, "business_contact_surface_verified": True, "suppression_clear": True, "opt_out_ready": True, "channel": "PUBLIC_BUSINESS_EMAIL"},
    ), next_action="HUMAN_SEND_IF_STILL_APPROPRIATE", due_at="2026-08-27T09:00:00+03:00", owner="synthetic-commercial-owner", contract=contract)
    state6 = pipeline.transition(state5, record_id, "CONTACTED", receipt(
        "REC-CONTACTED-001", "EXTERNAL_CONTACT_RECEIPT", "2026-08-26T02:10:00+03:00",
        {"sent": True, "channel": "PUBLIC_BUSINESS_EMAIL", "external_action_id": "SYNTHETIC-NON-EVIDENCE-CONTACT"},
    ), next_action="WAIT_FOR_OR_RECORD_RESPONSE", due_at="2026-09-02T09:00:00+03:00", contract=contract)
    state7 = pipeline.transition(state6, record_id, "DISCOVERY", receipt(
        "REC-DISCOVERY-001", "DISCOVERY_RECEIPT", "2026-08-26T02:20:00+03:00",
        {"occurred": True, "outcome": "SYNTHETIC_SCOPE_DISCUSSION"},
    ), next_action="PREPARE_HUMAN_REVIEWED_OFFER", due_at="2026-08-28T09:00:00+03:00", contract=contract)
    state8 = pipeline.transition(state7, record_id, "OFFER", receipt(
        "REC-OFFER-001", "HUMAN_APPROVED_OFFER", "2026-08-26T02:30:00+03:00",
        {"human_approved": True, "binding": False, "offer_ref": "SYNTHETIC-NON-BINDING-OFFER"},
    ), next_action="WAIT_FOR_HUMAN_RECORDED_DECISION", due_at="2026-09-02T09:00:00+03:00", contract=contract)
    state9 = pipeline.transition(state8, record_id, "WON", receipt(
        "REC-WON-001", "ACCEPTANCE_OR_CONTRACT_RECEIPT", "2026-08-26T02:40:00+03:00",
        {"accepted": True, "acceptance_reference": "SYNTHETIC-NON-EVIDENCE-ACCEPTANCE"},
    ), next_action="ACTIVATE_CLIENT_RECORD", due_at="2026-08-27T09:00:00+03:00", contract=contract)
    state10 = pipeline.transition(state9, record_id, "CLIENT", receipt(
        "REC-CLIENT-001", "CLIENT_ACTIVATION_RECEIPT", "2026-08-26T02:50:00+03:00",
        {"activated": True, "client_ref": "SYNTHETIC-CLIENT"},
    ), next_action="ACTIVATE_PROJECT_RECORD", due_at="2026-08-28T09:00:00+03:00", contract=contract)
    state11 = pipeline.transition(state10, record_id, "PROJECT", receipt(
        "REC-PROJECT-001", "PROJECT_ACTIVATION_RECEIPT", "2026-08-26T03:00:00+03:00",
        {"activated": True, "project_ref": "SYNTHETIC-PROJECT"},
    ), next_action="REVIEW_CASE_STUDY_CANDIDACY", due_at="2026-09-25T09:00:00+03:00", contract=contract)
    final = pipeline.transition(state11, record_id, "CASE_STUDY_CANDIDATE", receipt(
        "REC-CASE-001", "CASE_STUDY_CANDIDACY_REVIEW", "2026-08-26T03:10:00+03:00",
        {"candidate": True, "publication_state": "NEEDS_REVIEW"},
    ), contract=contract)

    inbound_attribution = {
        "origin": "INBOUND",
        "first_touch_ref": "JOURNEY-FUNDING-FIT",
        "source_refs": ["E11-DEDUPE-" + "a" * 16],
        "assisted_content_refs": ["AUTHORITY-CANDIDATE-SYNTHETIC"],
    }
    with_inbound, inbound_id = pipeline.ingest(
        final,
        "REQ-R10-INBOUND-001",
        "INBOUND",
        "E11-" + "a" * 64,
        "ORG-OPAQUE-SYNTHETIC",
        inbound_attribution,
        contact_reference="CONTACT-OPAQUE-SYNTHETIC",
        next_action="HUMAN_QUALIFICATION_REVIEW",
        due_at="2026-08-27T09:00:00+03:00",
        at="2026-08-26T03:20:00+03:00",
        contract=contract,
    )
    pipeline.assert_state(with_inbound, contract)
    assert with_inbound["records"][inbound_id]["stage"] == "LEAD"
    assert with_inbound["records"][record_id]["stage"] == "CASE_STUDY_CANDIDATE"
    assert with_inbound["records"][record_id]["case_study_publication_state"] == "NEEDS_REVIEW"
    assert all(with_inbound[key] is False for key in ("external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled"))
    serialized = json.dumps(with_inbound, ensure_ascii=False).casefold()
    for forbidden in ("companie sintetică beta", "beta.synthetic.invalid", "synthetic@example.invalid"):
        assert forbidden not in serialized, "raw organization/contact identity leaked into unified pipeline"

    print(json.dumps({
        "status": "PASS",
        "unit": "R10-PIPELINE-001",
        "entry_lanes_validated": 2,
        "pipeline_records": len(with_inbound["records"]),
        "prospect_terminal_stage": with_inbound["records"][record_id]["stage"],
        "inbound_stage": with_inbound["records"][inbound_id]["stage"],
        "audit_events": len(with_inbound["audit"]),
        "tasks": len(with_inbound["tasks"]),
        "stale_detection": "PASS",
        "eligibility_state": with_inbound["eligibility_state"],
        "production_records": 0,
        "external_contact": False,
        "automatic_send": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
