#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "security" / "privacy_security_contract.json"
GUARDS_PATH = ROOT / "eucons" / "security" / "security_guards.py"


def load_guards():
    spec = importlib.util.spec_from_file_location("eucons_security_guards", GUARDS_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load E21 security guards")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def expect_value_error(label: str, fn) -> None:
    try:
        fn()
    except ValueError:
        return
    raise SystemExit(f"{label}: expected fail-closed ValueError")


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    guards = load_guards()

    base = {
        "contact_name": "Synthetic Contact",
        "email": "synthetic@example.invalid",
        "organization_name": "Synthetic Organization",
        "form_id": "project_evaluation",
        "submission_id": "synthetic-submission",
        "privacy_ack": True
    }
    expect_value_error("unknown field", lambda: guards.validate_purpose_payload("service_inquiry", {**base, "tracking_profile": "forbidden"}, contract=contract))
    expect_value_error("special category", lambda: guards.validate_purpose_payload("service_inquiry", {**base, "special_category_data": "synthetic"}, contract=contract))
    expect_value_error("missing required", lambda: guards.validate_purpose_payload("service_inquiry", {key: value for key, value in base.items() if key != "email"}, contract=contract))
    expect_value_error("unknown purpose", lambda: guards.validate_purpose_payload("shadow_profiling", base, contract=contract))

    expect_value_error("control character", lambda: guards.validate_untrusted_text("hello\x00world", contract=contract))
    expect_value_error("script markup", lambda: guards.validate_untrusted_text("<script>alert(1)</script>", long_text=True, contract=contract))
    expect_value_error("event handler", lambda: guards.validate_untrusted_text("<img src=x onerror=alert(1)>", long_text=True, contract=contract))
    expect_value_error("oversized short text", lambda: guards.validate_untrusted_text("x" * 301, contract=contract))

    if not guards.contains_secret_like("ACCESS_TOKEN='abcdefghijklmnopqrstuvwxyz0123456789'"):
        raise SystemExit("secret-like assignment was not detected")
    if not guards.contains_secret_like("ghp_abcdefghijklmnopqrstuvwxyz0123456789"):
        raise SystemExit("GitHub token shape was not detected")
    if guards.contains_secret_like("ACCESS_TOKEN is provided only at runtime"):
        raise SystemExit("secret scanner false-positive on documentation sentence")

    expect_value_error(
        "silent hold",
        lambda: guards.retention_decision("LEAD_INQUIRY", "2026-08-01T00:00:00Z", "2026-08-19T00:00:00Z", hold={}, contract=contract),
    )
    expect_value_error(
        "hold without review",
        lambda: guards.retention_decision("LEAD_INQUIRY", "2026-08-01T00:00:00Z", "2026-08-19T00:00:00Z", hold={"reason_code": "CONTRACT_DISPUTE"}, contract=contract),
    )
    held = guards.retention_decision(
        "LEAD_INQUIRY",
        "2026-08-01T00:00:00Z",
        "2026-08-19T00:00:00Z",
        hold={"reason_code": "CONTRACT_DISPUTE", "review_at": "2026-09-01T00:00:00Z"},
        contract=contract,
    )
    if held["state"] != "HELD":
        raise SystemExit("valid reviewed hold did not remain held")
    review_due = guards.retention_decision(
        "LEAD_INQUIRY",
        "2026-08-01T00:00:00Z",
        "2026-08-19T00:00:00Z",
        hold={"reason_code": "CONTRACT_DISPUTE", "review_at": "2026-08-18T00:00:00Z"},
        contract=contract,
    )
    if review_due["state"] != "HOLD_REVIEW_DUE":
        raise SystemExit("expired hold review failed to surface")

    contact_ref = "a" * 64
    consent_at = "2026-08-19T12:00:00Z"
    consent_id = guards.consent_receipt_id(contact_ref, "marketing_opportunities", "email", "v1", consent_at, "eucons_form")
    receipt = {
        "consent_receipt_id": consent_id,
        "contact_ref": contact_ref,
        "purpose_id": "marketing_opportunities",
        "channel": "email",
        "statement_version": "v1",
        "consent_at": consent_at,
        "source": "eucons_form"
    }
    guards.validate_consent_receipt(receipt, contract=contract)
    expect_value_error("tampered consent receipt", lambda: guards.validate_consent_receipt({**receipt, "consent_receipt_id": "0" * 64}, contract=contract))
    expect_value_error("withdrawal without suppression", lambda: guards.validate_withdrawal({"consent_receipt_id": consent_id, "withdrawn_at": "2026-08-19T13:00:00Z"}, contract=contract))
    guards.validate_withdrawal({"consent_receipt_id": consent_id, "withdrawn_at": "2026-08-19T13:00:00Z", "suppression_receipt_id": "b" * 64}, contract=contract)

    expect_value_error("header drift", lambda: guards.validate_security_headers({**contract["web_security"]["headers"], "X-Frame-Options": "SAMEORIGIN"}, contract=contract))

    logged = guards.redact_sensitive_logs({
        "contact_name": "Synthetic Contact",
        "access_token": "secret-value",
        "nested": [
            {"phone": "+40000000000"},
            "ACCESS_TOKEN=abcdefghijklmnopqrstuvwxyz0123456789"
        ],
        "status": "ok"
    }, contract=contract)
    if logged["contact_name"] != "[REDACTED]" or logged["access_token"] != "[REDACTED]" or logged["nested"][0]["phone"] != "[REDACTED]" or logged["nested"][1] != "[REDACTED]" or logged["status"] != "ok":
        raise SystemExit("sensitive logging did not fail closed")

    if contract["consent_lineage"]["privacy_ack_is_not_marketing_consent"] is not True:
        raise SystemExit("privacy acknowledgement must never imply marketing consent")
    if contract["consent_lineage"]["marketing_default"] is not False:
        raise SystemExit("marketing consent must default false")

    print("EUCONS E21 Privacy/Security fail-closed: PASS")


if __name__ == "__main__":
    main()
