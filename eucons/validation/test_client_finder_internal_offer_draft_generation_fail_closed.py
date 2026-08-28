#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_offer_draft_generation.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_offer_draft_generation_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_preparation_authorization_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_internal_offer_draft_generation", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def authorization_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-PREPARATION-AUTHORIZATION-001",
        "offer_preparation_authorization_id": "OFFPREP-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_OFFER_PREPARATION_AUTHORIZATION_ENVELOPE",
        "source_commercial_scope_contract_id": "EUCONS-R07-CLIENT-FINDER-COMMERCIAL-SCOPE-READINESS-001",
        "source_commercial_scope_review_id": "COMSCOPE-0123456789abcdef01234567",
        "source_research_review_id": "EVREVIEW-0123456789abcdef01234567",
        "source_evaluation_id": "EVAL-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "commercial_scope_projection": {
            "area_code": "SELECTED_SERVICE_ONLY",
            "selected_service_id": "SERVICE-DEMO-001",
        },
        "authorization_capability": "INTERNAL_DRAFT_PREPARATION_ONLY",
        "authorization_outcome": "OFFER_PREPARATION_AUTHORIZED",
        "offer_preparation_state": "OFFER_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "offer_preparation_authorized": True,
        "next_gate_hint": "SEPARATE_OFFER_DRAFT_GENERATION_GATE_REQUIRED",
        "offer_draft_generation_gate_required": True,
        "authorization_semantics": "INTERNAL_PREPARATION_PERMISSION_NOT_OFFER_GENERATION_PRICING_ELIGIBILITY_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-004",
            "decided_at": "2026-08-27T18:10:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "target_state_committed": False,
        "persistence_executed": False,
        "offer_preparation_persistence_allowed": False,
        "offer_authorization_granted": False,
        "offer_content_included": False,
        "pricing_included": False,
        "offer_draft_generation_allowed": False,
        "offer_generation_allowed": False,
        "offer_engine_invocation_allowed": False,
        "pricing_decision_allowed": False,
        "crm_context_materialization_allowed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def request_fixture():
    return {
        "source_offer_preparation_authorization_id": "OFFPREP-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "generation_mode": "DETERMINISTIC_INTERNAL_TEMPLATE_ONLY",
    }


def build(authorization=None, request=None, contract=None, source_contract=None):
    return engine.build_internal_offer_draft(
        authorization or authorization_fixture(),
        request or request_fixture(),
        contract or CONTRACT,
        source_contract or SOURCE_CONTRACT,
    )


def must_fail(label, fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


draft = build()
assert draft["record_state"] == "CLIENT_FINDER_INTERNAL_OFFER_DRAFT_ENVELOPE"
assert draft["draft_state"] == "INTERNAL_OFFER_DRAFT_GENERATED_REVIEW_REQUIRED"
assert draft["content_scope"] == "INTERNAL_TEMPLATE_SKELETON_ONLY"
assert draft["generation_mode"] == "DETERMINISTIC_INTERNAL_TEMPLATE_ONLY"
assert draft["source_offer_preparation_authorization_id"] == "OFFPREP-0123456789abcdef01234567"
assert draft["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert draft["source_as_of"] == "2026-08-27T18:00:00Z"
assert draft["next_gate_hint"] == "SEPARATE_OFFER_CONTENT_REVIEW_GATE_REQUIRED"
assert draft["draft_review_required"] is True
assert draft["internal_draft_generated"] is True
assert draft["internal_draft_content_included"] is True
assert draft["public_offer_content_included"] is False
assert draft["pricing_included"] is False
assert draft["new_legal_claims_included"] is False
assert draft["new_financial_claims_included"] is False
assert draft["source_bound"] is True
assert draft["draft_approval_granted"] is False
assert draft["offer_engine_invocation_allowed"] is False
assert draft["pricing_decision_allowed"] is False
assert draft["crm_context_materialization_allowed"] is False
assert draft["draft_persistence_allowed"] is False
assert draft["eligibility_state"] == "NOT_ASSESSED"
assert draft["maximum_next_state"] == "RESEARCH_READY"
assert draft["target_state_committed"] is False
assert draft["persistence_executed"] is False
assert [section["section_code"] for section in draft["draft_sections"]] == ["CONTEXT", "BOUNDARY", "REVIEW"]
assert draft["draft_sections"] == [
    {
        "section_code": "CONTEXT",
        "text": "Draft intern pentru organizația ORG-DEMO-001, în contextul oportunității OPP-DEMO-001, limitat la serviciul selectat SERVICE-DEMO-001.",
    },
    {
        "section_code": "BOUNDARY",
        "text": "Acest draft nu confirmă eligibilitatea și nu include preț, buget, termen, indicatori, obligații ori concluzii juridice sau financiare.",
    },
    {
        "section_code": "REVIEW",
        "text": "Orice afirmație materială trebuie reverificată în sursa oficială înainte de utilizare; draftul necesită review uman separat înainte de orice pas comercial ulterior.",
    },
]
for flag in (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert draft[flag] is False

bad = authorization_fixture()
bad["authorization_outcome"] = "OFFER_PREPARATION_NOT_AUTHORIZED"
must_fail("unauthorized preparation", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["offer_preparation_state"] = "OFFER_PREPARATION_CLOSED"
must_fail("source preparation state drift", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["next_gate_hint"] = None
must_fail("missing draft generation gate hint", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["offer_draft_generation_gate_required"] = False
must_fail("draft generation gate not required", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["authorization_capability"] = "GENERATE_AND_SEND_OFFER"
must_fail("source capability drift", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["official_source_reverified"] = False
must_fail("official source not reverified", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["commercial_scope_projection"]["area_code"] = "FREEFORM_SCOPE"
must_fail("source commercial scope drift", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["commercial_scope_projection"]["selected_service_id"] = "SERVICE-DRIFT"
must_fail("source selected service drift", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("source decision not human", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["decision_receipt"]["decided_at"] = "2026-08-27T21:10:00+03:00"
must_fail("source decision timestamp not UTC-Z", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["target_state_committed"] = True
must_fail("source committed target state", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["persistence_executed"] = True
must_fail("source persisted state", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["offer_content_included"] = True
must_fail("source already contains offer content", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["pricing_included"] = True
must_fail("source pricing boundary", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source offer engine boundary", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("person-level source input", lambda: build(authorization=bad))

bad = authorization_fixture()
bad["budget"] = "100000"
must_fail("material budget field in source", lambda: build(authorization=bad))

bad_request = request_fixture()
bad_request["selected_service_id"] = "SERVICE-DRIFT"
must_fail("request identity drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["source_offer_preparation_authorization_id"] = "OFFPREP-DRIFT"
must_fail("source authorization id drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("request commercial scope drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["official_source_verification_ref"] = "OFFICIAL:OTHER"
must_fail("official source binding drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["source_as_of"] = "2026-08-27T21:00:00+03:00"
must_fail("source_as_of not UTC-Z", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["generation_mode"] = "FREEFORM_OFFER"
must_fail("generation mode allowlist", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["price"] = 1000
must_fail("pricing field in request", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["proposal_body"] = "Forbidden freeform draft"
must_fail("freeform offer content in request", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["legal_conclusion"] = "Eligible"
must_fail("legal conclusion in request", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["contact_name"] = "Forbidden Person"
must_fail("person-level request input", lambda: build(request=bad_request))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["draft_persistence_allowed"] = True
must_fail("draft persistence boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("offer engine boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["pricing_decision_allowed"] = True
must_fail("pricing boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["generation"]["next_gate_hint"] = "SEND_OFFER"
must_fail("next gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["offer_draft_generation_allowed"] = True
must_fail("source contract generation boundary", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder internal offer-draft generation fail-closed tests: PASS")
