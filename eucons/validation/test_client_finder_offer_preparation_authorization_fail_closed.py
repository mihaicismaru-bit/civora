#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_preparation_authorization.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_preparation_authorization_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_commercial_scope_readiness_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_offer_preparation_authorization", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def readiness_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-COMMERCIAL-SCOPE-READINESS-001",
        "commercial_scope_review_id": "COMSCOPE-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_COMMERCIAL_SCOPE_READINESS_ENVELOPE",
        "source_review_contract_id": "EUCONS-R07-CLIENT-FINDER-RESEARCH-EVALUATION-REVIEW-001",
        "source_review_id": "EVREVIEW-0123456789abcdef01234567",
        "source_evaluation_id": "EVAL-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "research_outcome": "RESEARCH_FIT_CONFIRMED",
        "commercial_scope_projection": {
            "area_code": "SELECTED_SERVICE_ONLY",
            "selected_service_id": "SERVICE-DEMO-001",
        },
        "readiness_outcome": "COMMERCIAL_SCOPE_READY",
        "commercial_scope_state": "COMMERCIAL_SCOPE_READY_FOR_SEPARATE_OFFER_GATE",
        "next_gate_hint": "SEPARATE_OFFER_AUTHORIZATION_GATE_REQUIRED",
        "offer_authorization_gate_required": True,
        "commercial_scope_semantics": "HUMAN_SCOPE_READINESS_NOT_OFFER_PRICING_ELIGIBILITY_OR_BUYING_INTENT",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-003",
            "decided_at": "2026-08-27T17:00:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "target_state_committed": False,
        "persistence_executed": False,
        "commercial_scope_persistence_allowed": False,
        "offer_authorization_granted": False,
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


def decision_fixture(outcome="OFFER_PREPARATION_AUTHORIZED"):
    return {
        "source_commercial_scope_review_id": "COMSCOPE-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "authorized_capability": "INTERNAL_DRAFT_PREPARATION_ONLY",
        "authorization_outcome": outcome,
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-004",
        "decided_at": "2026-08-27T18:10:00Z",
    }


def build(readiness=None, decision=None, contract=None, source_contract=None):
    return engine.build_offer_preparation_authorization(
        readiness or readiness_fixture(),
        decision or decision_fixture(),
        contract or CONTRACT,
        source_contract or SOURCE_CONTRACT,
    )


def must_fail(label, fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


authorized = build()
assert authorized["record_state"] == "CLIENT_FINDER_OFFER_PREPARATION_AUTHORIZATION_ENVELOPE"
assert authorized["commercial_scope_projection"] == {
    "area_code": "SELECTED_SERVICE_ONLY",
    "selected_service_id": "SERVICE-DEMO-001",
}
assert authorized["authorization_capability"] == "INTERNAL_DRAFT_PREPARATION_ONLY"
assert authorized["authorization_outcome"] == "OFFER_PREPARATION_AUTHORIZED"
assert authorized["offer_preparation_state"] == "OFFER_PREPARATION_AUTHORIZED_INTERNAL_ONLY"
assert authorized["offer_preparation_authorized"] is True
assert authorized["next_gate_hint"] == "SEPARATE_OFFER_DRAFT_GENERATION_GATE_REQUIRED"
assert authorized["offer_draft_generation_gate_required"] is True
assert authorized["authorization_semantics"] == (
    "INTERNAL_PREPARATION_PERMISSION_NOT_OFFER_GENERATION_PRICING_ELIGIBILITY_OR_OUTREACH"
)
assert authorized["offer_authorization_granted"] is False
assert authorized["offer_content_included"] is False
assert authorized["pricing_included"] is False
assert authorized["offer_draft_generation_allowed"] is False
assert authorized["offer_generation_allowed"] is False
assert authorized["offer_engine_invocation_allowed"] is False
assert authorized["pricing_decision_allowed"] is False
assert authorized["crm_context_materialization_allowed"] is False
assert authorized["offer_preparation_persistence_allowed"] is False
assert authorized["eligibility_state"] == "NOT_ASSESSED"
assert authorized["maximum_next_state"] == "RESEARCH_READY"
assert authorized["target_state_committed"] is False
assert authorized["persistence_executed"] is False
for flag in (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert authorized[flag] is False

research = build(decision=decision_fixture("MORE_OFFER_PREPARATION_RESEARCH_REQUIRED"))
assert research["offer_preparation_state"] == "OFFER_PREPARATION_RESEARCH_REQUIRED"
assert research["offer_preparation_authorized"] is False
assert research["next_gate_hint"] is None
assert research["offer_draft_generation_gate_required"] is False

closed = build(decision=decision_fixture("OFFER_PREPARATION_NOT_AUTHORIZED"))
assert closed["offer_preparation_state"] == "OFFER_PREPARATION_CLOSED"
assert closed["offer_preparation_authorized"] is False
assert closed["next_gate_hint"] is None
assert closed["offer_draft_generation_gate_required"] is False

bad = readiness_fixture()
bad["readiness_outcome"] = "MORE_COMMERCIAL_RESEARCH_REQUIRED"
must_fail("commercial scope not ready", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["commercial_scope_state"] = "COMMERCIAL_SCOPE_RESEARCH_REQUIRED"
must_fail("commercial scope state drift", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["next_gate_hint"] = None
must_fail("missing offer authorization gate hint", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["offer_authorization_gate_required"] = False
must_fail("offer authorization gate not required", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["official_source_reverified"] = False
must_fail("official source not reverified", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["commercial_scope_projection"]["area_code"] = "FREEFORM_SCOPE"
must_fail("source commercial scope area drift", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["commercial_scope_projection"]["selected_service_id"] = "SERVICE-DRIFT"
must_fail("source scope service drift", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("non-human source readiness decision", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["target_state_committed"] = True
must_fail("committed source readiness", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["persistence_executed"] = True
must_fail("persisted source readiness", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["offer_authorization_granted"] = True
must_fail("source readiness offer authorization boundary", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source readiness offer engine boundary", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("person-level source input", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["conversion_probability"] = 0.8
must_fail("probability inference", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["offer_body"] = "Forbidden offer content"
must_fail("offer content leakage", lambda: build(readiness=bad))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("service identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_commercial_scope_review_id"] = "COMSCOPE-DRIFT"
must_fail("source commercial scope review drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("decision commercial scope drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["authorized_capability"] = "GENERATE_AND_SEND_OFFER"
must_fail("authorization capability allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "SYSTEM"
must_fail("non-human offer preparation decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["authorization_outcome"] = "OFFER_APPROVED"
must_fail("authorization outcome allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-27T21:10:00+03:00"
must_fail("non-UTC offer preparation timestamp", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["price"] = 1000
must_fail("decision pricing field", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["proposal_body"] = "Forbidden draft"
must_fail("decision offer content field", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_draft_generation_allowed"] = True
must_fail("offer draft generation boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("offer engine boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["pricing_decision_allowed"] = True
must_fail("pricing boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["authorization"]["outcome_next_gate_map"]["OFFER_PREPARATION_AUTHORIZED"] = "OFFER_ENGINE"
must_fail("next gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["offer_authorization_granted"] = True
must_fail("source contract offer authorization boundary", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder offer preparation authorization fail-closed tests: PASS")
