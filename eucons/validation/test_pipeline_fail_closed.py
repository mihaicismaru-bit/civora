#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "crm" / "pipeline_contract.json").read_text(encoding="utf-8"))


def load_engine():
    path = EUCONS / "crm" / "pipeline_engine.py"
    spec = importlib.util.spec_from_file_location("r10_pipeline_fail_closed", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def must_fail(fn, fragment: str) -> None:
    try:
        fn()
    except ValueError as exc:
        assert fragment.casefold() in str(exc).casefold(), (fragment, str(exc))
        return
    raise AssertionError(f"expected failure containing {fragment!r}")


def receipt(kind: str, details: dict, *, receipt_id: str = "REC-TEST", automated: bool = False) -> dict:
    return {
        "receipt_id": receipt_id,
        "kind": kind,
        "at": "2026-08-26T02:00:00+03:00",
        "actor": "synthetic-human",
        "artifact_ref": "synthetic://test",
        "automated": automated,
        "details": details,
    }


def main() -> None:
    engine = load_engine()
    attribution = {"origin": "PROSPECT_DISCOVERY", "first_touch_ref": "SRC-1", "source_refs": ["SRC-1"], "assisted_content_refs": []}
    state, record_id = engine.ingest(
        engine.empty_state("2026-08-26T01:00:00+03:00", CONTRACT),
        "REQ-1", "PROSPECT_DISCOVERY", "PROS-1", "ORG-1", attribution,
        next_action="REVIEW", due_at="2026-08-27T01:00:00+03:00", at="2026-08-26T01:00:00+03:00", contract=CONTRACT,
    )

    must_fail(lambda: engine.transition(state, record_id, "MATCHED", receipt("R07_MATCH_RECORD", {}), next_action="NEXT", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "invalid pipeline transition")
    must_fail(lambda: engine.transition(state, record_id, "QUALIFIED", receipt("QUALIFICATION_REVIEW", {"email": "forbidden@example.invalid"}), next_action="NEXT", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "personal data")
    must_fail(lambda: engine.transition(state, record_id, "QUALIFIED", receipt("QUALIFICATION_REVIEW", {}, automated=True), next_action="NEXT", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "cannot be automated")
    must_fail(lambda: engine.ingest(state, "REQ-PERSON", "PROSPECT_DISCOVERY", "PROS-2", "ORG-2", attribution, contact_reference="PERSON-REF", next_action="REVIEW", due_at="2026-08-27T01:00:00+03:00", at="2026-08-26T01:00:00+03:00", contract=CONTRACT), "personal contact")
    bad_attribution = copy.deepcopy(attribution)
    bad_attribution["origin"] = "INBOUND"
    must_fail(lambda: engine.ingest(state, "REQ-BAD-ATTR", "PROSPECT_DISCOVERY", "PROS-3", "ORG-3", bad_attribution, next_action="REVIEW", due_at="2026-08-27T01:00:00+03:00", at="2026-08-26T01:00:00+03:00", contract=CONTRACT), "origin")
    must_fail(lambda: engine.ingest(state, "REQ-1", "PROSPECT_DISCOVERY", "PROS-CONFLICT", "ORG-1", attribution, next_action="REVIEW", due_at="2026-08-27T01:00:00+03:00", at="2026-08-26T01:00:00+03:00", contract=CONTRACT), "idempotency conflict")

    qualified = engine.transition(state, record_id, "QUALIFIED", receipt("QUALIFICATION_REVIEW", {"qualified": True}), next_action="MATCH", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT)
    bad_match = {"engine_id": "WRONG", "state": "MATCHED_RESEARCH_CANDIDATE", "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY", "opportunity_id": "O", "service_id": "S", "source_provenance_ref": "P", "authority_state": "OFFICIAL_SOURCE_VERIFIED", "official_fact_classes": ["status", "deadline"], "official_source_count": 1}
    must_fail(lambda: engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", bad_match, receipt_id="REC-BAD-MATCH"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "R07 match gate")

    authority_stripped = {"engine_id": "EUCONS_R07_PROSPECT_OPPORTUNITY_SERVICE_MATCH", "state": "MATCHED_RESEARCH_CANDIDATE", "eligibility_state": "NOT_ASSESSED", "maximum_next_state": "RESEARCH_READY", "opportunity_id": "O", "service_id": "S", "source_provenance_ref": "P"}
    must_fail(lambda: engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", authority_stripped, receipt_id="REC-NO-AUTHORITY"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "official-source authority")

    waiting_source = {**authority_stripped, "authority_state": "WAITING_SOURCE", "official_fact_classes": [], "official_source_count": 0}
    must_fail(lambda: engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", waiting_source, receipt_id="REC-WAITING-SOURCE"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "official-source authority")

    missing_deadline = {**authority_stripped, "authority_state": "OFFICIAL_SOURCE_VERIFIED", "official_fact_classes": ["status"], "official_source_count": 1}
    must_fail(lambda: engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", missing_deadline, receipt_id="REC-MISSING-DEADLINE"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "fact authority")

    zero_sources = {**authority_stripped, "authority_state": "OFFICIAL_SOURCE_VERIFIED", "official_fact_classes": ["status", "deadline"], "official_source_count": 0}
    must_fail(lambda: engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", zero_sources, receipt_id="REC-ZERO-SOURCES"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT), "official-source lineage")

    good_match = {**authority_stripped, "authority_state": "OFFICIAL_SOURCE_VERIFIED", "official_fact_classes": ["deadline", "status"], "official_source_count": 1}
    matched = engine.transition(qualified, record_id, "MATCHED", receipt("R07_MATCH_RECORD", good_match, receipt_id="REC-GOOD-MATCH"), next_action="PACK", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT)
    good_pack = {"engine_id": "EUCONS_R08_ORGANIZATION_ACTION_PACK", "state": "READY_FOR_APPROVAL", "eligibility_state": "NOT_ASSESSED", "maximum_state": "READY_FOR_APPROVAL", "action_pack_id": "PACK-1"}
    prepared = engine.transition(matched, record_id, "OUTREACH_PREPARED", receipt("R08_ACTION_PACK", good_pack, receipt_id="REC-GOOD-PACK"), next_action="CONTACT_REVIEW", due_at="2026-08-27T01:00:00+03:00", contract=CONTRACT)
    incomplete_approval = {"lawful_basis_reviewed": True, "business_contact_surface_verified": True, "suppression_clear": False, "opt_out_ready": True, "channel": "EMAIL"}
    must_fail(lambda: engine.transition(prepared, record_id, "CONTACT_APPROVED", receipt("HUMAN_CONTACT_APPROVAL", incomplete_approval, receipt_id="REC-BAD-APPROVAL"), next_action="SEND", due_at="2026-08-27T01:00:00+03:00", owner="owner", contract=CONTRACT), "governance incomplete")

    bad_authority_contract = copy.deepcopy(CONTRACT)
    bad_authority_contract["upstream_gates"]["R07_MATCH_RECORD"]["authority_state"] = "WAITING_SOURCE"
    must_fail(lambda: engine.validate_contract(bad_authority_contract), "official-source authority")
    bad_fact_contract = copy.deepcopy(CONTRACT)
    bad_fact_contract["upstream_gates"]["R07_MATCH_RECORD"]["required_official_fact_classes"] = ["status"]
    must_fail(lambda: engine.validate_contract(bad_fact_contract), "fact gate")
    bad_contract = copy.deepcopy(CONTRACT)
    bad_contract["contact_gate"]["automatic_send"] = True
    must_fail(lambda: engine.validate_contract(bad_contract), "contact boundary")
    bad_state = copy.deepcopy(prepared)
    bad_state["automatic_send_enabled"] = True
    must_fail(lambda: engine.assert_state(bad_state, CONTRACT), "automatic external action")
    must_fail(lambda: engine.assert_output_path_safe(EUCONS / "crm" / "unsafe-runtime.json"), "repository root")
    engine.assert_output_path_safe(Path("/tmp/eucons-r10-pipeline.json"))

    print("PASS: R10 rejects authority-stripped R07 matches and preserves unified pipeline fail-closed regressions")


if __name__ == "__main__":
    main()
