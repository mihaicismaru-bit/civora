#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_engine():
    path = EUCONS / "offers" / "offer_engine.py"
    spec = importlib.util.spec_from_file_location("e13_offer_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def crm_fixture():
    lead_id = "LEA-synthetic"
    opportunity_id = "OPP-synthetic"
    return {
        "leads": {lead_id: {"id": lead_id, "stage": "OPPORTUNITY", "owner": "commercial-owner", "next_action": "PREPARE_OFFER"}},
        "opportunities": {
            opportunity_id: {
                "id": opportunity_id,
                "lead_id": lead_id,
                "source_opportunity_id": "source-1",
                "title": "Synthetic opportunity",
                "programme": "Synthetic programme",
                "source_provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "source-1"}
            }
        }
    }, lead_id, opportunity_id


def expect_fail(fn, label: str) -> None:
    try:
        fn()
    except Exception:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def main() -> None:
    engine = load_engine()
    contract = json.loads((EUCONS / "offers" / "offer_contract.json").read_text(encoding="utf-8"))
    services = json.loads((EUCONS / "services" / "service_registry.json").read_text(encoding="utf-8"))
    crm, lead_id, opportunity_id = crm_fixture()

    base = dict(
        crm_state=crm,
        lead_id=lead_id,
        opportunity_id=opportunity_id,
        service_ids=["funding_strategy_and_eligibility"],
        assumptions=["Synthetic assumption."],
        exclusions=["Synthetic exclusion."],
        service_registry=services,
        contract=contract,
    )

    expect_fail(lambda: engine.compose_offer(**{**base, "service_ids": ["missing-service"]}), "unknown service")
    expect_fail(lambda: engine.compose_offer(**{**base, "service_ids": ["funding_strategy_and_eligibility", "funding_strategy_and_eligibility"]}), "duplicate service")
    expect_fail(lambda: engine.compose_offer(**{**base, "assumptions": []}), "missing assumptions")
    expect_fail(lambda: engine.compose_offer(**{**base, "exclusions": []}), "missing exclusions")

    wrong_stage = copy.deepcopy(crm)
    wrong_stage["leads"][lead_id]["stage"] = "NEW"
    expect_fail(lambda: engine.compose_offer(**{**base, "crm_state": wrong_stage}), "wrong CRM stage")

    no_owner = copy.deepcopy(crm)
    no_owner["leads"][lead_id]["owner"] = "UNASSIGNED"
    expect_fail(lambda: engine.compose_offer(**{**base, "crm_state": no_owner}), "missing CRM owner")

    wrong_lead = copy.deepcopy(crm)
    wrong_lead["opportunities"][opportunity_id]["lead_id"] = "LEA-other"
    expect_fail(lambda: engine.compose_offer(**{**base, "crm_state": wrong_lead}), "opportunity lead mismatch")

    no_provenance = copy.deepcopy(crm)
    no_provenance["opportunities"][opportunity_id]["source_provenance"] = {}
    expect_fail(lambda: engine.compose_offer(**{**base, "crm_state": no_provenance}), "missing opportunity provenance")

    expect_fail(
        lambda: engine.compose_offer(**{**base, "pricing_rule": {"rule_id": "invented-rule", "amount_minor": 500000, "currency": "RON"}}),
        "numeric price without approved pricing rule",
    )

    v1 = engine.compose_offer(**base)
    corrupted_parent = copy.deepcopy(v1)
    corrupted_parent["lead_id"] = "LEA-other"
    expect_fail(lambda: engine.compose_offer(**{**base, "previous_offer": corrupted_parent}), "lineage lead drift")

    missing_hash = copy.deepcopy(v1)
    missing_hash["content_sha256"] = ""
    expect_fail(lambda: engine.compose_offer(**{**base, "previous_offer": missing_hash}), "lineage immutable hash missing")

    expect_fail(lambda: engine.assert_output_path_safe(EUCONS / "offers" / "runtime-offer.json"), "repository runtime output")

    assert v1["automatic_send_allowed"] is False
    assert v1["pricing"]["amount_minor"] is None
    print("PASS: E13 offer engine fail-closed regressions")


if __name__ == "__main__":
    main()
