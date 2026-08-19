#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "email" / "email_contract.json"
ENGINE_PATH = ROOT / "eucons" / "email" / "email_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_email_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load email engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    engine = load_engine()
    if contract["engine_id"] != "EUCONS_E19_COMMERCIAL_EMAIL_ENGINE":
        raise SystemExit("E19 engine id drift")
    if contract["dispatch"]["mode"] != "DRY_RUN_ONLY" or contract["dispatch"]["real_sending_enabled"] is not False:
        raise SystemExit("E19 real sending must remain disabled")
    if contract["consent"]["marketing_consent_required_for_marketing_types"] is not True:
        raise SystemExit("E19 marketing consent gate missing")

    lead = {
        "engine_id": "EUCONS_E11_LEAD_ENGINE",
        "dedupe_key": "d" * 64,
        "lead": {"contact_name": "Ana Test", "email": "ana.test@example.invalid"},
        "consent": {"privacy_ack": True, "marketing_consent": True, "marketing_allowed": True},
    }
    offer = {
        "engine_id": "EUCONS_E13_OFFER_ENGINE",
        "offer_id": "o" * 64,
        "content_sha256": "c" * 64,
        "version": 1,
        "automatic_send_allowed": False,
        "pricing": {"state": "HUMAN_REQUIRED", "rule_id": None, "amount_minor": None, "currency": None, "binding": False},
    }
    opportunity = {
        "id": "OPP-TEST-1",
        "title": "Oportunitate verificată pentru test",
        "programme": "Program Test",
        "actionable": True,
        "verified_fact_classes": ["STATUS", "DEADLINE"],
        "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "OPP-TEST-1"},
    }

    requests = [
        ({"message_type": "LEAD_ACKNOWLEDGEMENT", "reference_id": "REQ-1", "context": {}}, None, None),
        ({"message_type": "QUALIFICATION_REQUEST", "reference_id": "REQ-2", "context": {"missing_fields": ["cod CAEN", "valoarea investiției"]}}, None, None),
        ({"message_type": "OPPORTUNITY_ALERT", "reference_id": "REQ-3", "context": {}}, None, opportunity),
        ({"message_type": "OFFER_EMAIL", "reference_id": "REQ-4", "context": {}}, offer, None),
        ({"message_type": "FOLLOW_UP", "reference_id": "REQ-5", "context": {"prior_interaction_id": "ACT-1"}}, None, None),
        ({"message_type": "OFFER_EXPIRATION", "reference_id": "REQ-6", "context": {"expires_at": "2026-09-15"}}, offer, None),
    ]
    outputs = []
    for request, maybe_offer, maybe_opportunity in requests:
        request = {"product": "EUCONS_COMMERCIAL_OS", "recipient": "ana.test@example.invalid", **request}
        result = engine.build_email(request, lead, contract, offer=maybe_offer, opportunity=maybe_opportunity)
        outputs.append(result)
        item = result["item"]
        if item["decision"] != "READY" or item["dispatch_state"] != "EMAIL_OUTBOX_READY_MAILBOX_AUTH_REQUIRED":
            raise SystemExit(f"{item['message_type']} did not enter dry-run READY outbox")
        if item["sent"] is not False or result["direct_sending_enabled"] is not False or result["dry_run"] is not True:
            raise SystemExit("E19 falsely claims live sending")
        if item["idempotency_key"] != item["item_id"] or item["max_attempts"] != 3:
            raise SystemExit("E19 idempotency/retry contract drift")
        if not result["receipt"]["receipt_hash"]:
            raise SystemExit("E19 immutable receipt missing")
        if "ana.test@example.invalid" in json.dumps(result, ensure_ascii=False):
            raise SystemExit("E19 output leaked raw recipient address")

    marketing = next(row for row in outputs if row["item"]["message_type"] == "OPPORTUNITY_ALERT")
    if marketing["item"]["unsubscribe_required"] is not True or "{UNSUBSCRIBE_URL}" not in marketing["item"]["body"]:
        raise SystemExit("E19 marketing unsubscribe contract missing")
    offer_output = next(row for row in outputs if row["item"]["message_type"] == "OFFER_EMAIL")
    if "preț numeric" not in offer_output["item"]["body"] or any(token in offer_output["item"]["body"] for token in ["1000.00", "5000.00"]):
        raise SystemExit("E19 human-required pricing presentation drift")
    if len({row["item"]["item_id"] for row in outputs}) != len(outputs):
        raise SystemExit("E19 message ids must remain deterministic and distinct")

    print(f"EUCONS E19 Commercial Email Engine: PASS ({len(outputs)} consent-aware dry-run message types; mailbox gate closed)")


if __name__ == "__main__":
    main()
