#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "offers" / "offer_engine.py"
    spec = importlib.util.spec_from_file_location("e13_offer", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def synthetic_crm():
    lead_id = "LEA-synthetic"
    opportunity_id = "OPP-synthetic"
    return {
        "schema_version": 1,
        "revision": 7,
        "leads": {
            lead_id: {
                "id": lead_id,
                "stage": "OPPORTUNITY",
                "owner": "commercial-owner",
                "next_action": "PREPARE_OFFER"
            }
        },
        "opportunities": {
            opportunity_id: {
                "id": opportunity_id,
                "lead_id": lead_id,
                "source_opportunity_id": "synthetic-partener-opportunity",
                "title": "Synthetic verified opportunity",
                "programme": "Synthetic programme",
                "source_provenance": {
                    "source_product": "PARTENER.EU",
                    "source_opportunity_id": "synthetic-partener-opportunity",
                    "source_projection_sha256": "b" * 64,
                    "verification_evidence": [{"id": "SYNTH-EV"}]
                }
            }
        }
    }, lead_id, opportunity_id


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "offers" / "offer_contract.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    assert contract["production_sending_enabled"] is False
    assert contract["pricing"]["approved_pricing_rule_ids"] == []
    crm, lead_id, opportunity_id = synthetic_crm()
    before = copy.deepcopy(crm)

    v1 = engine.compose_offer(
        crm_state=crm,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        service_ids=["funding_strategy_and_eligibility"],
        assumptions=["Clientul furnizează date complete și actuale pentru analiza contractată."],
        exclusions=["Depunerea cererii de finanțare nu este inclusă în acest serviciu."],
        service_registry=services,
        contract=contract,
    )
    assert crm == before, "offer composition must not mutate CRM state"
    assert v1["version"] == 1 and v1["parent_offer_id"] is None
    assert v1["pricing"] == {"state": "HUMAN_REQUIRED", "rule_id": None, "amount_minor": None, "currency": None, "binding": False}
    assert v1["automatic_send_allowed"] is False
    assert v1["send_state"] == "BLOCKED_PRICE_HUMAN_REQUIRED"
    assert v1["status"] == "DRAFT_HUMAN_PRICE_REQUIRED"
    assert contract["projection"]["human_price_placeholder"] in v1["html"]
    assert "noindex,nofollow" in v1["html"]
    assert re.fullmatch(r"[0-9a-f]{64}", v1["offer_id"])
    assert re.fullmatch(r"[0-9a-f]{64}", v1["content_sha256"])
    assert v1["scope"][0]["deliverables"] and v1["scope"][0]["boundaries"]

    frozen_v1 = copy.deepcopy(v1)
    v2 = engine.compose_offer(
        crm_state=crm,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        service_ids=["funding_strategy_and_eligibility", "application_design_and_submission"],
        assumptions=["A doua versiune extinde aria numai pe baza solicitării comerciale validate."],
        exclusions=["Serviciile juridice specializate nu sunt incluse implicit."],
        service_registry=services,
        contract=contract,
        previous_offer=v1,
    )
    assert v1 == frozen_v1, "previous offer must remain immutable"
    assert v2["version"] == 2
    assert v2["parent_offer_id"] == v1["offer_id"]
    assert v2["offer_id"] != v1["offer_id"]
    assert v2["lead_id"] == v1["lead_id"] and v2["opportunity_id"] == v1["opportunity_id"]
    assert len(v2["scope"]) == 2

    print(json.dumps({
        "status": "PASS",
        "phase": "E13",
        "versions_validated": [v1["version"], v2["version"]],
        "services_v2": len(v2["scope"]),
        "pricing_state": v2["pricing"]["state"],
        "automatic_send_allowed": v2["automatic_send_allowed"],
        "html_projection": "PASS",
        "lineage": "PASS"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
