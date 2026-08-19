#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "leads" / "lead_contract.json").read_text(encoding="utf-8"))
FORMS = json.loads((EUCONS / "leads" / "forms.json").read_text(encoding="utf-8"))


def load_engine():
    path = EUCONS / "leads" / "process_lead.py"
    spec = importlib.util.spec_from_file_location("e11_lead_tests", path)
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


def must_fail(engine, payload, fragment: str):
    try:
        engine.process(payload, CONTRACT, FORMS)
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected failure containing {fragment!r}")


def main() -> None:
    engine = load_engine()
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

    print("PASS: E11 lead engine fail-closed regressions")


if __name__ == "__main__":
    main()
