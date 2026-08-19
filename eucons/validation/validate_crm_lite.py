#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "crm" / "crm_engine.py"
    spec = importlib.util.spec_from_file_location("e12_crm", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def synthetic_e11():
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_E11_LEAD_ENGINE",
        "record_state": "QUALIFIED_INTAKE",
        "dedupe_key": "a" * 64,
        "lead": {
            "contact_name": "Synthetic Contact",
            "email": "synthetic@example.invalid",
            "phone": "",
            "organization_name": "Synthetic Organization",
            "audience_id": "companies_entrepreneurs"
        },
        "matching_profile": {"profile_id": "lead:SYNTH-E12"},
        "scores": {"lead_score": 95, "intent_score": 83, "urgency_score": 100},
        "next_action": "COMMERCIAL_REVIEW",
        "consent": {"privacy_ack": True, "marketing_consent": False, "marketing_allowed": False}
    }


def synthetic_match():
    return {
        "opportunity_id": "synthetic-partener-opportunity",
        "title": "Synthetic verified funding opportunity",
        "programme": "Synthetic programme",
        "score": 80,
        "confidence": "HIGH",
        "state": "MATCH_CANDIDATE",
        "source_provenance": {
            "source_product": "PARTENER.EU",
            "source_opportunity_id": "synthetic-partener-opportunity",
            "source_projection_sha256": "b" * 64,
            "verification_evidence": [{"id": "SYNTH-EV"}]
        }
    }


def main() -> None:
    crm = load_engine()
    contract = json.loads((EUCONS / "crm" / "crm_contract.json").read_text(encoding="utf-8"))
    storage = json.loads((EUCONS / "crm" / "storage_contract.json").read_text(encoding="utf-8"))
    assert contract["production_persistence_enabled"] is False
    assert storage["production_enabled"] is False
    assert contract["entities"] == ["organizations", "contacts", "leads", "opportunities", "offers", "activities"]
    assert contract["lead_lifecycle"] == ["NEW", "QUALIFIED", "OPPORTUNITY", "OFFER", "NEGOTIATION", "WON", "LOST"]

    state0 = crm.empty_state()
    state1, lead_id = crm.ingest_lead(state0, synthetic_e11(), contract, at="2026-08-19T10:20:00Z")
    assert state0 == crm.empty_state(), "ingest must not mutate prior state"
    assert state1["leads"][lead_id]["stage"] == "NEW"
    assert state1["contacts"][state1["leads"][lead_id]["contact_id"]]["consent"]["marketing_allowed"] is False

    state2, duplicate_id = crm.ingest_lead(state1, synthetic_e11(), contract, at="2026-08-19T10:21:00Z")
    assert duplicate_id == lead_id
    assert len(state2["leads"]) == 1
    assert state2["activities"][-1]["event_type"] == "LEAD_SEEN_AGAIN"

    state3 = crm.transition(state2, lead_id, "QUALIFIED", contract, next_action="CREATE_OPPORTUNITY", at="2026-08-19T10:22:00Z")
    state4 = crm.assign_owner(state3, lead_id, "commercial-owner", at="2026-08-19T10:23:00Z")
    state5, opportunity_id = crm.create_opportunity(state4, lead_id, synthetic_match(), at="2026-08-19T10:24:00Z")
    assert state5["opportunities"][opportunity_id]["source_provenance"]["source_product"] == "PARTENER.EU"
    state6 = crm.transition(state5, lead_id, "OPPORTUNITY", contract, next_action="PREPARE_OFFER", at="2026-08-19T10:25:00Z")
    state7, offer_id = crm.register_offer(state6, lead_id, "v1", "synthetic://offer/v1", at="2026-08-19T10:26:00Z")
    assert state7["offers"][offer_id]["lead_id"] == lead_id
    state8 = crm.transition(state7, lead_id, "OFFER", contract, next_action="SEND_OFFER", at="2026-08-19T10:27:00Z")
    state9 = crm.transition(state8, lead_id, "NEGOTIATION", contract, next_action="FOLLOW_UP", at="2026-08-19T10:28:00Z")
    final = crm.transition(state9, lead_id, "WON", contract, at="2026-08-19T10:29:00Z")
    assert final["leads"][lead_id]["stage"] == "WON"
    assert final["leads"][lead_id]["next_action"] is None
    crm.assert_audit(final, contract)
    assert [a["sequence"] for a in final["activities"]] == list(range(1, len(final["activities"]) + 1))
    assert final["revision"] > state1["revision"]

    print(json.dumps({
        "status": "PASS",
        "phase": "E12",
        "organizations": len(final["organizations"]),
        "contacts": len(final["contacts"]),
        "leads": len(final["leads"]),
        "opportunities": len(final["opportunities"]),
        "offers": len(final["offers"]),
        "activities": len(final["activities"]),
        "terminal_stage": final["leads"][lead_id]["stage"],
        "production_persistence": "DISABLED_UNTIL_BACKEND_AUTHORIZED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
