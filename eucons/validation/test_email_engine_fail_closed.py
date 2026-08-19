#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "eucons" / "email" / "email_contract.json").read_text(encoding="utf-8"))
ENGINE_PATH = ROOT / "eucons" / "email" / "email_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_email_failclosed", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load email engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ENGINE = load_engine()
LEAD = {
    "engine_id": "EUCONS_E11_LEAD_ENGINE",
    "dedupe_key": "d" * 64,
    "lead": {"contact_name": "Ana Test", "email": "ana.test@example.invalid"},
    "consent": {"privacy_ack": True, "marketing_consent": True, "marketing_allowed": True},
}
OFFER = {
    "engine_id": "EUCONS_E13_OFFER_ENGINE",
    "offer_id": "o" * 64,
    "content_sha256": "c" * 64,
    "version": 1,
    "automatic_send_allowed": False,
    "pricing": {"state": "HUMAN_REQUIRED", "rule_id": None, "amount_minor": None, "currency": None, "binding": False},
}
OPPORTUNITY = {
    "id": "OPP-1", "title": "Oportunitate", "actionable": True,
    "verified_fact_classes": ["STATUS"],
    "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "OPP-1"},
}


def request(message_type: str, context=None):
    return {
        "product": "EUCONS_COMMERCIAL_OS",
        "message_type": message_type,
        "recipient": "ana.test@example.invalid",
        "reference_id": "REQ-1",
        "context": context or {},
    }


def must_raise(name: str, req, lead=None, offer=None, opportunity=None) -> None:
    try:
        ENGINE.build_email(req, copy.deepcopy(lead or LEAD), copy.deepcopy(CONTRACT), offer=copy.deepcopy(offer), opportunity=copy.deepcopy(opportunity))
    except ENGINE.EmailEngineError:
        return
    raise SystemExit(f"{name}: engine failed open")


def main() -> None:
    lead = copy.deepcopy(LEAD); lead["consent"]["marketing_allowed"] = False; lead["consent"]["marketing_consent"] = False
    held = ENGINE.build_email(request("OPPORTUNITY_ALERT"), lead, CONTRACT, opportunity=copy.deepcopy(OPPORTUNITY))
    if held["item"]["decision"] != "HOLD" or "MARKETING_CONSENT_REQUIRED" not in held["item"]["hold_reasons"] or held["item"]["dispatch_state"] != "EMAIL_HOLD":
        raise SystemExit("marketing without consent failed open")

    r_hash = ENGINE.recipient_hash("ana.test@example.invalid")
    suppressed = ENGINE.build_email(request("LEAD_ACKNOWLEDGEMENT"), copy.deepcopy(LEAD), CONTRACT, suppressed_recipient_hashes=[r_hash])
    if suppressed["item"]["decision"] != "HOLD" or "RECIPIENT_SUPPRESSED" not in suppressed["item"]["hold_reasons"]:
        raise SystemExit("suppression list failed open")

    req = request("LEAD_ACKNOWLEDGEMENT"); req["recipient"] = "other@example.invalid"
    must_raise("recipient mismatch", req)
    lead = copy.deepcopy(LEAD); lead["consent"]["privacy_ack"] = False
    must_raise("privacy acknowledgement", request("LEAD_ACKNOWLEDGEMENT"), lead=lead)
    lead = copy.deepcopy(LEAD); lead["engine_id"] = "OTHER"
    must_raise("unknown lead engine", request("LEAD_ACKNOWLEDGEMENT"), lead=lead)

    opp = copy.deepcopy(OPPORTUNITY); opp["provenance"]["source_product"] = "OTHER"
    must_raise("wrong opportunity source", request("OPPORTUNITY_ALERT"), opportunity=opp)
    opp = copy.deepcopy(OPPORTUNITY); opp["actionable"] = False
    must_raise("non-actionable opportunity", request("OPPORTUNITY_ALERT"), opportunity=opp)
    opp = copy.deepcopy(OPPORTUNITY); opp["verified_fact_classes"] = []
    must_raise("unverified opportunity", request("OPPORTUNITY_ALERT"), opportunity=opp)

    offer = copy.deepcopy(OFFER); offer["automatic_send_allowed"] = True
    must_raise("offer auto-send enabled", request("OFFER_EMAIL"), offer=offer)
    offer = copy.deepcopy(OFFER); offer["pricing"]["amount_minor"] = 100000
    must_raise("numeric price without determined rule", request("OFFER_EMAIL"), offer=offer)
    offer = copy.deepcopy(OFFER); offer["pricing"] = {"state": "DETERMINED", "rule_id": None, "amount_minor": 100000, "currency": "EUR", "binding": True}
    must_raise("determined price without rule lineage", request("OFFER_EMAIL"), offer=offer)

    must_raise("follow-up without prior interaction", request("FOLLOW_UP"))
    must_raise("qualification without missing fields", request("QUALIFICATION_REQUEST"))
    must_raise("expiration without expiry", request("OFFER_EXPIRATION"), offer=copy.deepcopy(OFFER))

    try:
        ENGINE.assert_output_path_safe(ROOT / "eucons" / "email" / "unsafe-runtime-output.json")
    except ENGINE.EmailEngineError:
        pass
    else:
        raise SystemExit("repository PII-derived email output guard failed open")

    print("EUCONS E19 email fail-closed regressions: PASS")


if __name__ == "__main__":
    main()
