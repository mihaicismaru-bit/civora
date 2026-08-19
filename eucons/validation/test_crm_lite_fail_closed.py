#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "crm" / "crm_contract.json").read_text(encoding="utf-8"))


def load_engine():
    path = EUCONS / "crm" / "crm_engine.py"
    spec = importlib.util.spec_from_file_location("e12_crm_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def lead_record():
    return {
        "engine_id": "EUCONS_E11_LEAD_ENGINE",
        "record_state": "QUALIFIED_INTAKE",
        "dedupe_key": "c" * 64,
        "lead": {"contact_name": "Synthetic", "email": "synthetic@example.invalid", "organization_name": "Synthetic Org", "audience_id": "companies_entrepreneurs"},
        "matching_profile": {"profile_id": "lead:test"},
        "scores": {"lead_score": 80},
        "next_action": "COMMERCIAL_REVIEW",
        "consent": {"privacy_ack": True, "marketing_consent": False, "marketing_allowed": False}
    }


def match_record(state="MATCH_CANDIDATE", source_product="PARTENER.EU"):
    return {
        "opportunity_id": "opp-1",
        "title": "Synthetic",
        "programme": "Synthetic",
        "score": 70,
        "confidence": "HIGH",
        "state": state,
        "source_provenance": {"source_product": source_product, "source_opportunity_id": "opp-1", "verification_evidence": [{"id":"ev"}]}
    }


def must_fail(fn, fragment: str):
    try:
        fn()
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected failure containing {fragment!r}")


def main() -> None:
    crm = load_engine()
    state, lead_id = crm.ingest_lead(crm.empty_state(), lead_record(), CONTRACT, at="2026-08-19T10:30:00Z")

    must_fail(lambda: crm.transition(state, lead_id, "OFFER", CONTRACT), "invalid crm transition")
    qualified = crm.transition(state, lead_id, "QUALIFIED", CONTRACT, next_action="CREATE_OPPORTUNITY")
    must_fail(lambda: crm.transition(qualified, lead_id, "OPPORTUNITY", CONTRACT, next_action="PREPARE_OFFER"), "owner required")
    owned = crm.assign_owner(qualified, lead_id, "owner")
    must_fail(lambda: crm.transition(owned, lead_id, "OPPORTUNITY", CONTRACT, next_action="PREPARE_OFFER"), "opportunity entity required")

    must_fail(lambda: crm.create_opportunity(owned, lead_id, match_record(state="REQUIRES_DATA")), "match_candidate")
    must_fail(lambda: crm.create_opportunity(owned, lead_id, match_record(source_product="OTHER")), "provenance")
    with_opp, _ = crm.create_opportunity(owned, lead_id, match_record())
    opportunity_stage = crm.transition(with_opp, lead_id, "OPPORTUNITY", CONTRACT, next_action="PREPARE_OFFER")
    must_fail(lambda: crm.transition(opportunity_stage, lead_id, "OFFER", CONTRACT, next_action="SEND"), "offer entity required")

    with_offer, _ = crm.register_offer(opportunity_stage, lead_id, "v1", "synthetic://offer")
    offered = crm.transition(with_offer, lead_id, "OFFER", CONTRACT, next_action="SEND")
    won = crm.transition(offered, lead_id, "WON", CONTRACT)
    must_fail(lambda: crm.transition(won, lead_id, "QUALIFIED", CONTRACT), "invalid crm transition")

    bad_consent = lead_record()
    bad_consent["consent"]["privacy_ack"] = False
    must_fail(lambda: crm.ingest_lead(crm.empty_state(), bad_consent, CONTRACT), "privacy")
    bad_dedupe = lead_record()
    bad_dedupe["dedupe_key"] = "short"
    must_fail(lambda: crm.ingest_lead(crm.empty_state(), bad_dedupe, CONTRACT), "dedupe")

    prior = crm.empty_state()
    later, _ = crm.ingest_lead(prior, lead_record(), CONTRACT)
    assert prior["activities"] == [], "prior state mutated despite append-only contract"
    crm.assert_audit(later, CONTRACT)

    try:
        crm.assert_output_path_safe(EUCONS / "crm" / "unsafe-runtime.json")
        raise AssertionError("repository runtime CRM write must fail")
    except ValueError:
        pass
    crm.assert_output_path_safe(Path("/tmp/eucons-crm-synthetic.json"))

    print("PASS: E12 CRM Lite fail-closed regressions")


if __name__ == "__main__":
    main()
