#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module():
    path = EUCONS / "leads" / "inbound_runtime.py"
    spec = importlib.util.spec_from_file_location("r05_inbound_fail_closed", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def request(request_id, step, answers, *, website="", age=2200):
    return {"request_id": request_id, "submission_age_ms": age, "website": website, "step": step, "answers": answers}


def expect_failure(runtime, state, payload, contract, forms, ux, lead_contract, fragment):
    try:
        runtime.advance(state, payload, contract, forms, ux, lead_contract)
    except runtime.InboundError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"fail-closed regression accepted: {fragment}")


def main():
    runtime = load_module()
    contract = json.loads((EUCONS / "leads" / "inbound_runtime_contract.json").read_text(encoding="utf-8"))
    forms = json.loads((EUCONS / "leads" / "forms.json").read_text(encoding="utf-8"))
    ux = json.loads((EUCONS / "web" / "jtbd_ux_contract.json").read_text(encoding="utf-8"))
    lead_contract = json.loads((EUCONS / "leads" / "lead_contract.json").read_text(encoding="utf-8"))
    state = runtime.empty_session("SYNTH-R05-FAIL", "JRN-FUNDING-FIT", contract, forms, ux)

    valid_profile = {
        "organization_name": "Organizație sintetică",
        "audience_id": "companies_entrepreneurs",
        "investment_terms": ["digitalizare"],
    }

    expect_failure(runtime, state, request("SPAM", "PROFILE", valid_profile, website="bot"), contract, forms, ux, lead_contract, "honeypot")
    expect_failure(runtime, state, request("FAST", "PROFILE", valid_profile, age=10), contract, forms, ux, lead_contract, "submission_age")
    expect_failure(runtime, state, request("ORDER", "CONTACT", {}), contract, forms, ux, lead_contract, "step order")
    expect_failure(runtime, state, request("EARLY-PII", "PROFILE", {**valid_profile, "email": "x@example.invalid"}), contract, forms, ux, lead_contract, "not allowed")

    incomplete = dict(valid_profile)
    incomplete.pop("investment_terms")
    expect_failure(runtime, state, request("MISSING", "PROFILE", incomplete), contract, forms, ux, lead_contract, "profile fields")

    first_request = request("FIRST", "PROFILE", valid_profile)
    first = runtime.advance(state, first_request, contract, forms, ux, lead_contract)
    conflict = request("FIRST", "CONTEXT", {})
    expect_failure(runtime, first["session"], conflict, contract, forms, ux, lead_contract, "idempotency conflict")

    second = runtime.advance(first["session"], request("SECOND", "CONTEXT", {}), contract, forms, ux, lead_contract)
    no_privacy = {"contact_name": "Sintetic", "email": "synthetic@example.invalid", "privacy_ack": False}
    expect_failure(runtime, second["session"], request("NO-PRIVACY", "CONTACT", no_privacy), contract, forms, ux, lead_contract, "privacy_ack")

    bad_email = {"contact_name": "Sintetic", "email": "invalid", "privacy_ack": True}
    expect_failure(runtime, second["session"], request("BAD-EMAIL", "CONTACT", bad_email), contract, forms, ux, lead_contract, "email")

    contact = {"contact_name": "Sintetic", "email": "synthetic@example.invalid", "privacy_ack": True}
    final = runtime.advance(second["session"], request("FINAL", "CONTACT", contact), contract, forms, ux, lead_contract)
    expect_failure(runtime, final["session"], request("AFTER", "CONTACT", contact), contract, forms, ux, lead_contract, "completed")

    assert final["lead_record"]["consent"]["marketing_allowed"] is False
    opted_in = runtime.empty_session("SYNTH-R05-OPTIN", "JRN-FUNDING-FIT", contract, forms, ux)
    opted_in = runtime.advance(opted_in, request("O1", "PROFILE", valid_profile), contract, forms, ux, lead_contract)["session"]
    opted_in = runtime.advance(opted_in, request("O2", "CONTEXT", {}), contract, forms, ux, lead_contract)["session"]
    opted_in_result = runtime.advance(opted_in, request("O3", "CONTACT", {**contact, "marketing_consent": True}), contract, forms, ux, lead_contract)
    assert opted_in_result["lead_record"]["consent"]["marketing_allowed"] is True

    try:
        runtime.assert_output_path_safe(EUCONS / "leads" / "unsafe-session.json")
    except runtime.InboundError:
        pass
    else:
        raise AssertionError("repository PII write must fail closed")
    runtime.assert_output_path_safe(Path("/tmp/eucons-r05-synthetic-session.json"))

    print(json.dumps({"status": "PASS", "phase": "R05", "negative_cases": 10}, ensure_ascii=False))


if __name__ == "__main__":
    main()
