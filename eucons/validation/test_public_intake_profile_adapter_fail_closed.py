#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ADAPTER_PATH = ROOT / "eucons" / "leads" / "public_intake_profile_adapter.py"

spec = importlib.util.spec_from_file_location("eucons_public_intake_profile_adapter", ADAPTER_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def expect_fail(fn, contains: str) -> None:
    try:
        fn()
    except module.AdapterError as exc:
        if contains not in str(exc):
            raise AssertionError(f"expected error containing {contains!r}, got {str(exc)!r}") from exc
    else:
        raise AssertionError(f"expected AdapterError containing {contains!r}")


def payload_for(journey_id: str, answers: dict) -> dict:
    return {
        "session_id": "session-001",
        "journey_id": journey_id,
        "request_id": "request-001",
        "submission_age_ms": 1200,
        "website": "",
        "answers": answers,
    }


def main() -> None:
    adapter = module.load_json(module.ADAPTER_CONTRACT_PATH)
    guard = module.load_json(module.PUBLIC_GUARD_PATH)
    jtbd = module.load_json(module.JTBD_CONTRACT_PATH)
    inbound = module.load_json(module.INBOUND_CONTRACT_PATH)
    module.validate_configuration(adapter, guard, jtbd, inbound)

    funding = module.build_profile_envelope(payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
        "investment_terms": ["digitalizare", "eficienta energetica"],
    }), adapter, guard, jtbd, inbound)
    assert funding["state"] == "LOCAL_PROFILE_ENVELOPE_READY_REVIEW_REQUIRED"
    assert funding["route_sink"] == "LOCAL_ONLY_NO_SUBMIT"
    assert funding["request"]["step"] == "PROFILE"
    assert funding["runtime_acceptance"] == "NOT_EXECUTED"
    assert funding["eligibility_state"] == "NOT_ASSESSED"
    assert funding["next_gate"] == "R05_CANONICAL_RUNTIME_REMAINS_SEPARATELY_GATED"
    assert funding["transient_data_rule"] == "DO_NOT_PERSIST_OR_LOG_RAW_ANSWERS"
    assert all(value is False for value in funding["action_guards"].values())

    recovery = module.build_profile_envelope(payload_for("JRN-RECOVERY", {
        "organization_name": "Beneficiar Test",
        "audience_id": "public_authority",
        "project_stage": "implementation",
        "message": "Avem o intarziere la achizitie si trebuie ordonata cronologia documentelor.",
    }), adapter, guard, jtbd, inbound)
    assert recovery["form_id"] == inbound["journey_form_map"]["JRN-RECOVERY"]

    extra = payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
        "investment_terms": ["digitalizare"],
        "email": "operator@example.test",
    })
    expect_fail(lambda: module.build_profile_envelope(extra, adapter, guard, jtbd, inbound), "PROFILE answers must equal")

    missing = payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
    })
    expect_fail(lambda: module.build_profile_envelope(missing, adapter, guard, jtbd, inbound), "PROFILE answers must equal")

    email_in_message = payload_for("JRN-RECOVERY", {
        "organization_name": "Beneficiar Test",
        "audience_id": "public_authority",
        "project_stage": "implementation",
        "message": "Scrieti la nume@example.ro pentru documente.",
    })
    expect_fail(lambda: module.build_profile_envelope(email_in_message, adapter, guard, jtbd, inbound), "contact-like token")

    phone_in_message = payload_for("JRN-RECOVERY", {
        "organization_name": "Beneficiar Test",
        "audience_id": "public_authority",
        "project_stage": "implementation",
        "message": "Sunati la +40 712 345 678 pentru detalii.",
    })
    expect_fail(lambda: module.build_profile_envelope(phone_in_message, adapter, guard, jtbd, inbound), "contact-like token")

    honeypot = payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
        "investment_terms": ["digitalizare"],
    })
    honeypot["website"] = "spam.example"
    expect_fail(lambda: module.build_profile_envelope(honeypot, adapter, guard, jtbd, inbound), "honeypot")

    too_fast = payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
        "investment_terms": ["digitalizare"],
    })
    too_fast["submission_age_ms"] = 100
    expect_fail(lambda: module.build_profile_envelope(too_fast, adapter, guard, jtbd, inbound), "anti-abuse window")

    unknown_payload_field = payload_for("JRN-FUNDING-FIT", {
        "organization_name": "Exemplu SRL",
        "audience_id": "private_company",
        "investment_terms": ["digitalizare"],
    })
    unknown_payload_field["submit"] = True
    expect_fail(lambda: module.build_profile_envelope(unknown_payload_field, adapter, guard, jtbd, inbound), "payload fields must equal")

    unsafe_adapter = copy.deepcopy(adapter)
    unsafe_adapter["action_guards"]["backend_submit"] = True
    expect_fail(lambda: module.validate_configuration(unsafe_adapter, guard, jtbd, inbound), "external-action guards")

    unsafe_guard = copy.deepcopy(guard)
    unsafe_guard["runtime_boundaries"]["production_collection_enabled"] = True
    expect_fail(lambda: module.validate_configuration(adapter, unsafe_guard, jtbd, inbound), "production collection enabled")

    unsafe_inbound = copy.deepcopy(inbound)
    unsafe_inbound["production_collection_enabled"] = True
    expect_fail(lambda: module.validate_configuration(adapter, guard, jtbd, unsafe_inbound), "production collection unexpectedly enabled")

    drifted_guard = copy.deepcopy(guard)
    drifted_guard["journeys"][0]["allowed_profile_fields"] = ["organization_name"]
    expect_fail(lambda: module.validate_configuration(adapter, drifted_guard, jtbd, inbound), "first-step binding drift")

    print("PASS: public intake PROFILE adapter remains local-only and fail-closed")


if __name__ == "__main__":
    main()
