#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def value_for(field, journey_id):
    values = {
        "organization_name": "Organizație sintetică R05",
        "audience_id": "existing_beneficiaries" if journey_id in {"JRN-IMPLEMENTATION", "JRN-RECOVERY"} else "companies_entrepreneurs",
        "investment_terms": ["digitalizare", "echipamente"],
        "project_stage": "at_risk" if journey_id == "JRN-RECOVERY" else ("implementation" if journey_id == "JRN-IMPLEMENTATION" else "preparation"),
        "message": "Context sintetic folosit exclusiv pentru validarea runtime-ului.",
        "activity_codes": ["CAEN 6201"],
        "county": "Vâlcea",
        "requested_grant_eur": 250000,
        "timeline": "31_90_days",
    }
    return values[field]


def request(request_id, step, answers):
    return {
        "request_id": request_id,
        "submission_age_ms": 2400,
        "website": "",
        "step": step,
        "answers": answers,
    }


def main():
    runtime = load_module("r05_inbound", EUCONS / "leads" / "inbound_runtime.py")
    contract = json.loads((EUCONS / "leads" / "inbound_runtime_contract.json").read_text(encoding="utf-8"))
    forms = json.loads((EUCONS / "leads" / "forms.json").read_text(encoding="utf-8"))
    ux = json.loads((EUCONS / "web" / "jtbd_ux_contract.json").read_text(encoding="utf-8"))
    lead_contract = json.loads((EUCONS / "leads" / "lead_contract.json").read_text(encoding="utf-8"))

    assert contract["id"] == "R05-INBOUND-001"
    assert contract["phase"] == "R05_INBOUND_RUNTIME"
    assert contract["status"] == "CANONICAL"
    assert contract["production_collection_enabled"] is False
    assert contract["privacy_and_purpose"]["marketing_requires_explicit_consent"] is True
    assert contract["privacy_and_purpose"]["marketing_never_conditions_operational_response"] is True
    assert contract["privacy_and_purpose"]["repository_pii_writes_forbidden"] is True
    assert contract["idempotency"]["same_request_id_with_different_payload_is_conflict"] is True
    assert contract["recovery"]["resume_token_is_not_authentication"] is True

    journeys = {row["id"]: row for row in ux["journeys"]}
    forms_by_id = {row["id"]: row for row in forms["forms"]}
    assert set(contract["journey_form_map"]) == set(journeys)

    completed = []
    for index, (journey_id, form_id) in enumerate(contract["journey_form_map"].items(), start=1):
        journey = journeys[journey_id]
        form = forms_by_id[form_id]
        assert set(form["required"]) == set(journey["first_step_fields"])
        assert set(form["progressive_optional"]) == set(journey["later_fields"])

        state = runtime.empty_session(f"SYNTH-R05-{index}", journey_id, contract, forms, ux)
        assert state["stage"] == "PROFILE"
        assert len(state["resume"]["token"]) == 64
        assert state["resume"]["authentication_state"] == "PROVIDER_AUTH_REQUIRED"

        profile = {field: value_for(field, journey_id) for field in journey["first_step_fields"]}
        first_request = request(f"REQ-{index}-1", "PROFILE", profile)
        first = runtime.advance(state, first_request, contract, forms, ux, lead_contract)
        assert first["session"]["stage"] == "CONTEXT"
        assert first["response"]["eligibility_state"] == "NOT_ASSESSED"
        assert first["response"]["funding_claim_state"] == "NO_PROGRAMME_CLAIM_WITHOUT_VERIFIED_MATCH"
        assert set(first["response"]["recommended_service_ids"]) == set(journey["service_ids"])

        replay = runtime.advance(first["session"], first_request, contract, forms, ux, lead_contract)
        assert replay["response"]["state"] == "IDEMPOTENT_REPLAY"
        assert replay["session"] == first["session"]

        context = {field: value_for(field, journey_id) for field in journey["later_fields"]}
        second = runtime.advance(first["session"], request(f"REQ-{index}-2", "CONTEXT", context), contract, forms, ux, lead_contract)
        assert second["session"]["stage"] == "CONTACT"
        assert second["lead_record"] is None

        contact = {
            "contact_name": "Persoană Sintetică",
            "email": f"r05-{index}@example.invalid",
            "phone": "",
            "privacy_ack": True,
            "marketing_consent": False,
            "submitted_at": "2026-08-25T20:00:00Z",
        }
        final = runtime.advance(second["session"], request(f"REQ-{index}-3", "CONTACT", contact), contract, forms, ux, lead_contract)
        assert final["session"]["stage"] == "COMPLETED"
        assert final["response"]["state"] == "QUALIFIED_INTAKE"
        assert final["response"]["eligibility_state"] == "NOT_ASSESSED"
        assert final["lead_record"]["consent"]["marketing_allowed"] is False
        assert final["session"]["contact_receipt"]["raw_contact_retained_in_session"] is False
        serialized_session = json.dumps(final["session"], ensure_ascii=False)
        assert contact["email"] not in serialized_session
        assert contact["contact_name"] not in serialized_session
        completed.append(final)

    assert len({row["session"]["resume"]["token"] for row in completed}) == 4

    production = load_module("r05_production_builder", EUCONS / "deployment" / "build_production_ready.py")
    with tempfile.TemporaryDirectory() as td:
        target = Path(td) / "site"
        build = production.build_site(target)
        assert build["production_deployed"] is False
        for journey_id, form_id in contract["journey_form_map"].items():
            journey = journeys[journey_id]
            page = (target / journey["path"].strip("/") / "index.html").read_text(encoding="utf-8")
            assert page.count('action="/api/inbound/sessions"') == 3
            assert page.count("data-eucons-inbound-form") == 3
            assert 'data-step="PROFILE"' in page and 'data-step="CONTEXT"' in page and 'data-step="CONTACT"' in page
            assert f'data-journey-id="{journey_id}"' in page
            assert f'data-form-id="{form_id}"' in page
            assert 'name="privacy_ack"' in page and 'name="marketing_consent"' in page
            for field in journey["first_step_fields"] + journey["later_fields"]:
                assert f'name="{field}"' in page
        browser_adapter = (target / "assets" / "forms.js").read_text(encoding="utf-8")
        assert 'fetch(form.action' in browser_adapter
        assert 'Content-Type": "application/json"' in browser_adapter
        assert "localStorage" not in browser_adapter
    print(json.dumps({
        "status": "PASS",
        "phase": "R05",
        "journeys": len(completed),
        "progressive_steps": 3,
        "idempotency": "PASS",
        "marketing_separation": "PASS",
        "raw_contact_in_resumable_session": False,
        "production_collection": "DISABLED_UNTIL_PROVIDER_ACTIVATION",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
