#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "leads" / "lead_contract.json").read_text(encoding="utf-8"))
FORMS = json.loads((EUCONS / "leads" / "forms.json").read_text(encoding="utf-8"))
EVALUATION_CONTRACT = json.loads((EUCONS / "leads" / "research_evaluation_handoff_contract.json").read_text(encoding="utf-8"))


def load_engine():
    path = EUCONS / "leads" / "process_lead.py"
    spec = importlib.util.spec_from_file_location("e11_lead_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_evaluation_handoff():
    path = EUCONS / "leads" / "research_evaluation_handoff.py"
    spec = importlib.util.spec_from_file_location("e11_r07_evaluation_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_payload():
    return {
        "form_id": "proposal_request",
        "submission_id": "SYNTH-E11-TEST",
        "submission_age_ms": 2500,
        "website": "",
        "privacy_ack": True,
        "contact_name": "Synthetic Person",
        "email": "synthetic@example.invalid",
        "organization_name": "Synthetic Organization",
        "audience_id": "companies_entrepreneurs",
        "message": "Synthetic request used only for validation.",
        "timeline": "31_90_days",
        "project_stage": "preparation"
    }


def valid_research_match():
    return {
        "prospect_id": "PROS-SYNTH-E11-TEST",
        "state": "MATCHED_RESEARCH_CANDIDATE",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "selected_opportunity_id": "SYNTH-OPP-E11-TEST",
        "selected_service_id": "funding_strategy_and_eligibility",
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "opportunity_matches": [{
            "opportunity_id": "SYNTH-OPP-E11-TEST",
            "aligned_service_ids": ["funding_strategy_and_eligibility"],
            "selected_service_id": "funding_strategy_and_eligibility",
            "source_provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "SYNTH-OPP-E11-TEST"},
        }],
    }


def must_fail(engine, payload, fragment: str):
    try:
        engine.process(payload, CONTRACT, FORMS)
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected failure containing {fragment!r}")


def handoff_must_fail(handoff, record, fragment: str, contract=None):
    try:
        handoff.build_evaluation_handoff(record, contract or EVALUATION_CONTRACT)
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected evaluation handoff failure containing {fragment!r}")


def main() -> None:
    engine = load_engine()
    handoff = load_evaluation_handoff()
    base = valid_payload()

    spam = dict(base, website="filled-by-bot")
    must_fail(engine, spam, "honeypot")

    too_fast = dict(base, submission_age_ms=100)
    must_fail(engine, too_fast, "submission_age")

    no_privacy = dict(base, privacy_ack=False)
    must_fail(engine, no_privacy, "privacy")

    bad_email = dict(base, email="invalid")
    must_fail(engine, bad_email, "email")

    bad_audience = dict(base, audience_id="made_up")
    must_fail(engine, bad_audience, "audience")

    missing_form_field = dict(base)
    missing_form_field.pop("organization_name")
    must_fail(engine, missing_form_field, "organization_name")

    unknown = dict(base, invented_field="x")
    must_fail(engine, unknown, "unsupported")

    no_marketing = engine.process(base, CONTRACT, FORMS)
    assert no_marketing["consent"]["marketing_allowed"] is False
    with_marketing = engine.process(dict(base, marketing_consent=True), CONTRACT, FORMS)
    assert with_marketing["consent"]["marketing_allowed"] is True

    duplicate = dict(base, submission_id="SYNTH-E11-DIFFERENT")
    assert engine.process(base, CONTRACT, FORMS)["dedupe_key"] == engine.process(duplicate, CONTRACT, FORMS)["dedupe_key"]

    recovery = dict(base, form_id="project_recovery", project_stage="at_risk")
    assert engine.process(recovery, CONTRACT, FORMS)["next_action"] == "PRIORITY_DIAGNOSTIC"

    try:
        engine.assert_output_path_safe(EUCONS / "leads" / "unsafe-real-lead.json")
        raise AssertionError("repository PII write must be rejected")
    except ValueError:
        pass
    engine.assert_output_path_safe(Path("/tmp/eucons-synthetic-lead.json"))

    research = valid_research_match()
    evaluation = handoff.build_evaluation_handoff(research, EVALUATION_CONTRACT)
    assert evaluation["selected_service_id"] == research["selected_service_id"]
    assert evaluation["selected_opportunity_id"] == research["selected_opportunity_id"]
    assert evaluation["human_review_required"] is True
    assert evaluation["external_contact_enabled"] is False
    assert evaluation["automatic_offer_enabled"] is False
    assert evaluation["crm_write_enabled"] is False
    assert handoff.build_evaluation_handoff(research, EVALUATION_CONTRACT)["evaluation_id"] == evaluation["evaluation_id"]

    not_matched = deepcopy(research)
    not_matched["state"] = "REQUIRES_VERIFICATION"
    handoff_must_fail(handoff, not_matched, "not evaluation-ready")

    eligibility_crossed = deepcopy(research)
    eligibility_crossed["eligibility_state"] = "ELIGIBLE"
    handoff_must_fail(handoff, eligibility_crossed, "eligibility")

    commercial_crossed = deepcopy(research)
    commercial_crossed["maximum_next_state"] = "COMMERCIAL_READY"
    handoff_must_fail(handoff, commercial_crossed, "research boundary")

    contact_enabled = deepcopy(research)
    contact_enabled["external_contact_enabled"] = True
    handoff_must_fail(handoff, contact_enabled, "external contact")

    offer_enabled = deepcopy(research)
    offer_enabled["automatic_offer_enabled"] = True
    handoff_must_fail(handoff, offer_enabled, "automatic offer")

    pair_drift = deepcopy(research)
    pair_drift["opportunity_matches"][0]["aligned_service_ids"] = ["application_design_and_submission"]
    handoff_must_fail(handoff, pair_drift, "not aligned")

    person_level = deepcopy(research)
    person_level["opportunity_matches"][0]["source_provenance"]["personal_email"] = "synthetic@example.invalid"
    handoff_must_fail(handoff, person_level, "person-level")

    failed_open_contract = deepcopy(EVALUATION_CONTRACT)
    failed_open_contract["output"]["crm_write_enabled"] = True
    handoff_must_fail(handoff, research, "crm_write_enabled", failed_open_contract)

    print("PASS: E11 lead engine and R07 research evaluation handoff fail-closed regressions")


if __name__ == "__main__":
    main()
