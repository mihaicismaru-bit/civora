#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_commercial_scope_readiness.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_commercial_scope_readiness_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_research_evaluation_review_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_commercial_scope_readiness", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def review_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-RESEARCH-EVALUATION-REVIEW-001",
        "review_id": "EVREVIEW-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_RESEARCH_EVALUATION_REVIEW_ENVELOPE",
        "source_transition_contract_id": "EUCONS-R07-CLIENT-FINDER-EVALUATION-TRANSITION-001",
        "source_transition_envelope_id": "EVTRANS-0123456789abcdef01234567",
        "source_evaluation_contract_id": "EUCONS-E11-R07-EVALUATION-HANDOFF-001",
        "source_evaluation_id": "EVAL-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "research_outcome": "RESEARCH_FIT_CONFIRMED",
        "research_review_state": "RESEARCH_COMPLETE_COMMERCIAL_GATE_REQUIRED",
        "next_gate_hint": "SEPARATE_COMMERCIAL_SCOPE_GATE_REQUIRED",
        "commercial_scope_gate_required": True,
        "research_fit_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-002",
            "decided_at": "2026-08-27T16:25:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "target_state_committed": False,
        "persistence_executed": False,
        "offer_engine_invocation_allowed": False,
        "commercial_scope_write_enabled": False,
        "pricing_decision_allowed": False,
        "crm_context_materialization_allowed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def decision_fixture(outcome="COMMERCIAL_SCOPE_READY"):
    return {
        "source_review_id": "EVREVIEW-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "readiness_outcome": outcome,
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-003",
        "decided_at": "2026-08-27T17:00:00Z",
    }


def build(review=None, decision=None, contract=None, source_contract=None):
    return engine.build_commercial_scope_readiness(
        review or review_fixture(),
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


ready = build()
assert ready["record_state"] == "CLIENT_FINDER_COMMERCIAL_SCOPE_READINESS_ENVELOPE"
assert ready["commercial_scope_projection"] == {
    "area_code": "SELECTED_SERVICE_ONLY",
    "selected_service_id": "SERVICE-DEMO-001",
}
assert ready["commercial_scope_state"] == "COMMERCIAL_SCOPE_READY_FOR_SEPARATE_OFFER_GATE"
assert ready["next_gate_hint"] == "SEPARATE_OFFER_AUTHORIZATION_GATE_REQUIRED"
assert ready["offer_authorization_gate_required"] is True
assert ready["offer_authorization_granted"] is False
assert ready["offer_engine_invocation_allowed"] is False
assert ready["pricing_decision_allowed"] is False
assert ready["crm_context_materialization_allowed"] is False
assert ready["commercial_scope_persistence_allowed"] is False
assert ready["eligibility_state"] == "NOT_ASSESSED"
assert ready["maximum_next_state"] == "RESEARCH_READY"
assert ready["target_state_committed"] is False
assert ready["persistence_executed"] is False
for flag in (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert ready[flag] is False

more = build(decision=decision_fixture("MORE_COMMERCIAL_RESEARCH_REQUIRED"))
assert more["commercial_scope_state"] == "COMMERCIAL_SCOPE_RESEARCH_REQUIRED"
assert more["next_gate_hint"] is None
assert more["offer_authorization_gate_required"] is False

no_scope = build(decision=decision_fixture("NO_COMMERCIAL_SCOPE"))
assert no_scope["commercial_scope_state"] == "COMMERCIAL_SCOPE_CLOSED_NO_FIT"
assert no_scope["next_gate_hint"] is None
assert no_scope["offer_authorization_gate_required"] is False

bad = review_fixture()
bad["research_outcome"] = "MORE_RESEARCH_REQUIRED"
must_fail("unconfirmed research fit", lambda: build(review=bad))

bad = review_fixture()
bad["research_review_state"] = "RESEARCH_CONTINUE"
must_fail("source review state drift", lambda: build(review=bad))

bad = review_fixture()
bad["next_gate_hint"] = None
must_fail("missing commercial gate hint", lambda: build(review=bad))

bad = review_fixture()
bad["commercial_scope_gate_required"] = False
must_fail("commercial gate not required", lambda: build(review=bad))

bad = review_fixture()
bad["official_source_reverified"] = False
must_fail("official source not reverified", lambda: build(review=bad))

bad = review_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("non-human source review", lambda: build(review=bad))

bad = review_fixture()
bad["target_state_committed"] = True
must_fail("committed source review", lambda: build(review=bad))

bad = review_fixture()
bad["persistence_executed"] = True
must_fail("persisted source review", lambda: build(review=bad))

bad = review_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source review offer engine boundary", lambda: build(review=bad))

bad = review_fixture()
bad["commercial_scope_write_enabled"] = True
must_fail("source review commercial write boundary", lambda: build(review=bad))

bad = review_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("person-level source input", lambda: build(review=bad))

bad = review_fixture()
bad["conversion_probability"] = 0.8
must_fail("probability inference", lambda: build(review=bad))

bad = review_fixture()
bad["amount_minor"] = 10000
must_fail("pricing leakage", lambda: build(review=bad))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("service identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_review_id"] = "EVREVIEW-DRIFT"
must_fail("source review identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("scope area allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "SYSTEM"
must_fail("non-human commercial scope decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["readiness_outcome"] = "OFFER_READY"
must_fail("readiness outcome allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-27T20:00:00+03:00"
must_fail("non-UTC commercial scope timestamp", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["price"] = 1000
must_fail("decision pricing field", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_authorization_granted"] = True
must_fail("offer authorization boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("offer engine boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["pricing_decision_allowed"] = True
must_fail("pricing boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["decision"]["outcome_next_gate_map"]["COMMERCIAL_SCOPE_READY"] = "OFFER_ENGINE"
must_fail("next gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["commercial_scope_write_enabled"] = True
must_fail("source contract commercial scope write boundary", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder commercial scope readiness fail-closed tests: PASS")
