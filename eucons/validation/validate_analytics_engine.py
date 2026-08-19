#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "analytics" / "analytics_contract.json"
ENGINE_PATH = ROOT / "eucons" / "analytics" / "analytics_engine.py"


def load_engine():
    spec = importlib.util.spec_from_file_location("eucons_analytics_engine", ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise SystemExit("cannot load analytics engine")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    engine = load_engine()
    if contract["engine_id"] != "EUCONS_E20_ANALYTICS_ENGINE":
        raise SystemExit("E20 engine id drift")
    if contract["transport"]["mode"] != "DRY_RUN_ONLY" or contract["transport"]["production_transport_enabled"] is not False:
        raise SystemExit("E20 transport must remain provider-neutral dry-run")
    if contract["privacy"]["raw_pii_forbidden"] is not True or contract["privacy"]["data_minimization"] is not True:
        raise SystemExit("E20 privacy/minimization contract missing")

    lead_id = "a" * 64
    offer_id = "b" * 64
    session_id = "c" * 64
    fixture_props = {
        "page_view": {"path": "/"},
        "service_view": {"service_id": "SRV-01", "path": "/servicii/pregatire-proiect/"},
        "opportunity_view": {"opportunity_id": "OPP-01", "path": "/finantari/OPP-01/"},
        "case_view": {"case_id": "CASE-01", "path": "/proiecte/CASE-01/"},
        "cta_click": {"cta_id": "CTA-EVALUARE", "path": "/evaluare-proiect/"},
        "evaluation_started": {"form_id": "project_evaluation"},
        "evaluation_completed": {"form_id": "project_evaluation"},
        "lead_created": {"lead_id": lead_id},
        "lead_qualified": {"lead_id": lead_id, "lead_score": 82},
        "offer_generated": {"lead_id": lead_id, "offer_id": offer_id},
        "offer_sent": {"lead_id": lead_id, "offer_id": offer_id},
        "client_won": {"lead_id": lead_id, "opportunity_id": "OPP-01"},
    }
    outputs = []
    for index, event_name in enumerate(contract["events"], start=1):
        payload = {
            "product": "EUCONS_COMMERCIAL_OS",
            "event_name": event_name,
            "occurred_at": f"2026-08-19T12:{index:02d}:00Z",
            "session_id": session_id,
            "properties": fixture_props[event_name],
            "attribution": {
                "first_touch": {"source": "linkedin", "medium": "social", "campaign": "eucons-launch", "landing_path": "/"},
                "last_touch": {"source": "eucons", "medium": "website", "referrer_domain": "eucons.ro", "landing_path": "/evaluare-proiect/"},
            },
        }
        first = engine.build_event(payload, contract)
        replay = engine.build_event(payload, contract)
        if first != replay:
            raise SystemExit(f"{event_name}: analytics replay is not deterministic")
        event = first["event"]
        if event["event_id"] != event["idempotency_key"] or len(event["event_id"]) != 64:
            raise SystemExit(f"{event_name}: event id/idempotency drift")
        if event["transported"] is not False or first["direct_transport_enabled"] is not False or first["dry_run"] is not True:
            raise SystemExit(f"{event_name}: transport enabled prematurely")
        if event["funnel_stage"] != contract["events"][event_name]["stage"]:
            raise SystemExit(f"{event_name}: funnel stage drift")
        if not first["receipt"]["receipt_hash"]:
            raise SystemExit(f"{event_name}: immutable receipt missing")
        outputs.append(first)

    if len(outputs) != 12:
        raise SystemExit("E20 canonical funnel event count drift")
    stages = {row["event"]["funnel_stage"] for row in outputs}
    expected_stages = {"AWARENESS", "CONSIDERATION", "INTENT", "LEAD", "OPPORTUNITY", "OFFER", "WON"}
    if stages != expected_stages:
        raise SystemExit("E20 funnel stage coverage incomplete")
    print(f"EUCONS E20 Analytics Engine: PASS ({len(outputs)} events; {len(stages)} funnel stages; provider transport disabled)")


if __name__ == "__main__":
    main()
