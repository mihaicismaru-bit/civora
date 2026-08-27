#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_research_evaluation_review.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_research_evaluation_review_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_evaluation_transition_contract.json"
EVALUATION_CONTRACT_PATH = ROOT / "eucons" / "leads" / "research_evaluation_handoff_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_research_evaluation_review", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)
EVALUATION_CONTRACT = load(EVALUATION_CONTRACT_PATH)


def transition_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-EVALUATION-TRANSITION-001",
        "envelope_id": "EVTRANS-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_RESEARCH_EVALUATION_TRANSITION_ENVELOPE",
        "transition_status": "READY_FOR_RESEARCH_EVALUATION_REVIEW",
        "source_view_id": "EUCONS-R07-CLIENT-FINDER-OPERATOR-TRIAGE-SYNTHESIS-001",
        "source_queue_rank": 1,
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "source_status": "OFFICIAL_SOURCE_REVERIFIED",
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "decision_receipt": {
            "decision": "APPROVE_RESEARCH_EVALUATION_HANDOFF",
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-001",
            "decided_at": "2026-08-27T16:20:00Z",
        },
        "target_evaluation_contract_id": "EUCONS-E11-R07-EVALUATION-HANDOFF-001",
        "target_evaluation_record_state": "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW",
        "proposed_evaluation": {
            "schema_version": 1,
            "contract_id": "EUCONS-E11-R07-EVALUATION-HANDOFF-001",
            "evaluation_id": "EVAL-0123456789abcdef01234567",
            "record_state": "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW",
            "prospect_id": "PROSPECT-DEMO-001",
            "selected_opportunity_id": "OPP-DEMO-001",
            "selected_service_id": "SERVICE-DEMO-001",
            "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
            "eligibility_state": "NOT_ASSESSED",
            "maximum_next_state": "RESEARCH_READY",
            "source_provenance": {
                "source_product": "OFFICIAL_SOURCE_REVERIFICATION",
                "source_opportunity_id": "OPP-DEMO-001",
                "verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
            },
            "human_review_required": True,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "crm_write_enabled": False,
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "target_state_committed": False,
        "persistence_executed": False,
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def decision_fixture(outcome="RESEARCH_FIT_CONFIRMED"):
    return {
        "evaluation_id": "EVAL-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "research_outcome": outcome,
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-002",
        "decided_at": "2026-08-27T16:25:00Z",
    }


def build(transition=None, decision=None, contract=None, source_contract=None, evaluation_contract=None):
    return engine.build_research_evaluation_review(
        transition or transition_fixture(),
        decision or decision_fixture(),
        contract or CONTRACT,
        source_contract or SOURCE_CONTRACT,
        evaluation_contract or EVALUATION_CONTRACT,
    )


def must_fail(label, fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


fit = build()
assert fit["record_state"] == "CLIENT_FINDER_RESEARCH_EVALUATION_REVIEW_ENVELOPE"
assert fit["research_review_state"] == "RESEARCH_COMPLETE_COMMERCIAL_GATE_REQUIRED"
assert fit["next_gate_hint"] == "SEPARATE_COMMERCIAL_SCOPE_GATE_REQUIRED"
assert fit["commercial_scope_gate_required"] is True
assert fit["eligibility_state"] == "NOT_ASSESSED"
assert fit["maximum_next_state"] == "RESEARCH_READY"
assert fit["target_state_committed"] is False
assert fit["persistence_executed"] is False
assert fit["offer_engine_invocation_allowed"] is False
assert fit["commercial_scope_write_enabled"] is False
assert fit["pricing_decision_allowed"] is False
assert fit["crm_context_materialization_allowed"] is False
for flag in (
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert fit[flag] is False

more = build(decision=decision_fixture("MORE_RESEARCH_REQUIRED"))
assert more["research_review_state"] == "RESEARCH_CONTINUE"
assert more["next_gate_hint"] is None
assert more["commercial_scope_gate_required"] is False

no_fit = build(decision=decision_fixture("NO_RESEARCH_FIT"))
assert no_fit["research_review_state"] == "RESEARCH_CLOSED_NO_FIT"
assert no_fit["next_gate_hint"] is None
assert no_fit["commercial_scope_gate_required"] is False

bad = transition_fixture()
bad["source_status"] = "OFFICIAL_SOURCE_CONFLICT"
must_fail("source conflict", lambda: build(transition=bad))

bad = transition_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("non-human transition approval", lambda: build(transition=bad))

bad = transition_fixture()
bad["target_state_committed"] = True
must_fail("committed source transition", lambda: build(transition=bad))

bad = transition_fixture()
bad["persistence_executed"] = True
must_fail("persisted source transition", lambda: build(transition=bad))

bad = transition_fixture()
bad["proposed_evaluation"]["selected_service_id"] = "SERVICE-DRIFT"
must_fail("proposed evaluation identity drift", lambda: build(transition=bad))

bad = transition_fixture()
bad["proposed_evaluation"]["source_provenance"]["verification_ref"] = "OFFICIAL:DRIFT"
must_fail("verification reference drift", lambda: build(transition=bad))

bad = transition_fixture()
bad["proposed_evaluation"]["source_provenance"]["raw_url"] = "https://example.invalid/raw"
must_fail("non-minimized provenance", lambda: build(transition=bad))

bad = transition_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("person-level transition input", lambda: build(transition=bad))

bad = transition_fixture()
bad["conversion_probability"] = 0.9
must_fail("probability inference", lambda: build(transition=bad))

bad = transition_fixture()
bad["amount_minor"] = 10000
must_fail("pricing leakage", lambda: build(transition=bad))

bad_decision = decision_fixture()
bad_decision["selected_opportunity_id"] = "OPP-DRIFT"
must_fail("decision identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "SYSTEM"
must_fail("non-human evaluation decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["research_outcome"] = "ELIGIBLE"
must_fail("research outcome allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-27T19:25:00+03:00"
must_fail("non-UTC evaluation timestamp", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("offer engine boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["crm_context_materialization_allowed"] = True
must_fail("CRM context boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["decision"]["outcome_next_gate_map"]["RESEARCH_FIT_CONFIRMED"] = "OFFER"
must_fail("next-gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["automatic_offer_enabled"] = True
must_fail("source contract offer boundary", lambda: build(source_contract=bad_source_contract))

bad_evaluation_contract = copy.deepcopy(EVALUATION_CONTRACT)
bad_evaluation_contract["output"]["crm_write_enabled"] = True
must_fail("evaluation contract CRM boundary", lambda: build(evaluation_contract=bad_evaluation_contract))

print("EUCONS Client Finder research evaluation review fail-closed tests: PASS")
