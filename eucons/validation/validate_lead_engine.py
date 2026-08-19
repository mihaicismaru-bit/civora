#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> None:
    lead_engine = load_module("e11_lead", EUCONS / "leads" / "process_lead.py")
    matcher = load_module("e11_match", EUCONS / "opportunities" / "match_opportunities.py")
    lead_contract = json.loads((EUCONS / "leads" / "lead_contract.json").read_text(encoding="utf-8"))
    forms_doc = json.loads((EUCONS / "leads" / "forms.json").read_text(encoding="utf-8"))
    storage = json.loads((EUCONS / "leads" / "storage_contract.json").read_text(encoding="utf-8"))
    matching_contract = json.loads((EUCONS / "opportunities" / "matching_contract.json").read_text(encoding="utf-8"))
    commercial = json.loads((EUCONS / "canon" / "commercial_canon.json").read_text(encoding="utf-8"))

    assert lead_contract["production_collection_enabled"] is False
    assert storage["production_enabled"] is False
    assert storage["repository_policy"]["pii_writes_under_repository_root_forbidden"] is True
    assert lead_contract["consent"]["privacy_ack_required"] is True
    assert lead_contract["consent"]["marketing_consent_default"] is False

    form_ids = {form["id"] for form in forms_doc["forms"]}
    assert form_ids == set(lead_contract["scoring"]["form_intent"])
    cta_ids = {cta["id"] for cta in commercial["ctas"]}
    assert {form["cta_id"] for form in forms_doc["forms"]} == cta_ids

    bridge = {
        "bridge_state": "READY",
        "opportunities": [{
            "id": "synthetic-energy",
            "title": "Investiții în energie solară pentru întreprinderi",
            "programme": "Program test",
            "code": "TEST",
            "commercial_state": "VERIFIED_AVAILABLE",
            "actionable": True,
            "material_facts": {
                "status": "OPEN",
                "deadline": {"closes_at": "2026-10-01T12:00:00+03:00"},
                "eligibility": {"activity_codes_at_application": ["CAEN 10"], "eligible_classes": ["întreprindere agricolă"]},
                "grant": {"maximum_eur": 1000000}
            },
            "provenance": {"source_product": "PARTENER.EU", "source_opportunity_id": "synthetic-energy", "verification_evidence": [{"id": "EV-SYNTHETIC"}]}
        }]
    }
    intake = {
        "form_id": "project_evaluation",
        "submission_id": "SYNTH-E11-001",
        "submission_age_ms": 2400,
        "website": "",
        "privacy_ack": True,
        "contact_name": "Synthetic Contact",
        "email": "synthetic@example.invalid",
        "organization_name": "Synthetic Agro SRL",
        "audience_id": "companies_entrepreneurs",
        "organization_labels": ["întreprindere", "agricolă"],
        "activity_codes": ["CAEN 10"],
        "county": "Vâlcea",
        "region_terms": ["România"],
        "investment_terms": ["energie", "solară"],
        "requested_grant_eur": 500000,
        "project_stage": "idea",
        "timeline": "now_30_days",
        "message": "Synthetic qualification fixture; no real person or organization."
    }

    normalized_once = lead_engine.validate_and_normalize(intake, lead_contract, forms_doc)
    pre_match_record = lead_engine.process(intake, lead_contract, forms_doc)
    match_result = matcher.match(pre_match_record["matching_profile"], bridge, matching_contract)
    final_record = lead_engine.process(intake, lead_contract, forms_doc, match_result)

    assert normalized_once["email"] == "synthetic@example.invalid"
    assert final_record["dedupe_key"] == pre_match_record["dedupe_key"]
    assert len(final_record["dedupe_key"]) == 64
    assert match_result["summary"]["candidates"] == 1
    assert final_record["scores"]["matching_candidate_count"] == 1
    assert final_record["scores"]["lead_score"] >= 70
    assert final_record["next_action"] == "COMMERCIAL_REVIEW"
    assert final_record["consent"]["marketing_consent"] is False
    assert final_record["consent"]["marketing_allowed"] is False
    assert final_record["storage_state"] == "PROVIDER_ADAPTER_REQUIRED"
    assert final_record["matching_profile"]["profile_id"] == "lead:SYNTH-E11-001"

    print(json.dumps({
        "status": "PASS",
        "phase": "E11",
        "forms": len(forms_doc["forms"]),
        "lead_score": final_record["scores"]["lead_score"],
        "intent_score": final_record["scores"]["intent_score"],
        "urgency_score": final_record["scores"]["urgency_score"],
        "matching_candidates": match_result["summary"]["candidates"],
        "next_action": final_record["next_action"],
        "production_collection": "DISABLED_UNTIL_BACKEND_AUTHORIZED"
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
