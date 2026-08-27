#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_finalization_readiness.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_finalization_readiness_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_content_review_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_offer_finalization_readiness", ENGINE_PATH)
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
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-CONTENT-REVIEW-001",
        "offer_content_review_id": "OFFREVIEW-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_OFFER_CONTENT_REVIEW_ENVELOPE",
        "source_draft_contract_id": "EUCONS-R07-CLIENT-FINDER-INTERNAL-OFFER-DRAFT-GENERATION-001",
        "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "content_review_outcome": "APPROVED_INTERNAL_ONLY",
        "content_review_state": "INTERNAL_DRAFT_CONTENT_APPROVED_INTERNAL_ONLY",
        "internal_content_review_approved": True,
        "next_gate_hint": "SEPARATE_OFFER_FINALIZATION_GATE_REQUIRED",
        "offer_finalization_gate_required": True,
        "content_review_semantics": "INTERNAL_CONTENT_REVIEW_ONLY_NOT_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-005",
            "decided_at": "2026-08-27T20:15:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "offer_approval_granted": False,
        "draft_approval_granted": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "draft_persistence_allowed": False,
        "offer_persistence_allowed": False,
        "production_offer_generation_allowed": False,
        "final_offer_generation_allowed": False,
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


def decision_fixture(outcome="FINALIZATION_READY_INTERNAL_ONLY"):
    return {
        "offer_content_review_id": "OFFREVIEW-0123456789abcdef01234567",
        "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "authorization_scope": "NEXT_GATE_ONLY",
        "finalization_readiness_outcome": outcome,
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-006",
        "decided_at": "2026-08-27T21:30:00Z",
    }


def build(review=None, decision=None, contract=None, source_contract=None):
    return engine.build_offer_finalization_readiness(
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


readiness = build()
assert readiness["record_state"] == "CLIENT_FINDER_OFFER_FINALIZATION_READINESS_ENVELOPE"
assert readiness["source_offer_content_review_id"] == "OFFREVIEW-0123456789abcdef01234567"
assert readiness["source_internal_offer_draft_id"] == "OFFDRAFT-0123456789abcdef01234567"
assert readiness["finalization_readiness_outcome"] == "FINALIZATION_READY_INTERNAL_ONLY"
assert readiness["finalization_readiness_state"] == "FINALIZATION_READY_INTERNAL_ONLY"
assert readiness["authorization_scope"] == "NEXT_GATE_ONLY"
assert readiness["next_gate_authorization_granted"] is True
assert readiness["next_gate_hint"] == "SEPARATE_FINAL_OFFER_GENERATION_GATE_REQUIRED"
assert readiness["final_offer_generation_gate_required"] is True
assert readiness["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert readiness["source_as_of"] == "2026-08-27T18:00:00Z"
assert readiness["decision_receipt"]["decision_source"] == "HUMAN"
assert readiness["eligibility_state"] == "NOT_ASSESSED"
assert readiness["maximum_next_state"] == "RESEARCH_READY"
for field in (
    "offer_approval_granted", "final_offer_approval_granted",
    "final_offer_generation_authorization_granted", "content_mutation_allowed",
    "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert readiness[field] is False
assert readiness["human_review_required"] is True

more_review = build(decision=decision_fixture("MORE_FINALIZATION_REVIEW_REQUIRED"))
assert more_review["finalization_readiness_state"] == "FINALIZATION_REVIEW_REQUIRED"
assert more_review["next_gate_authorization_granted"] is False
assert more_review["next_gate_hint"] is None
assert more_review["final_offer_generation_gate_required"] is False

not_ready = build(decision=decision_fixture("FINALIZATION_NOT_READY"))
assert not_ready["finalization_readiness_state"] == "FINALIZATION_NOT_READY"
assert not_ready["next_gate_authorization_granted"] is False
assert not_ready["next_gate_hint"] is None
assert not_ready["final_offer_generation_gate_required"] is False

bad = review_fixture()
bad["content_review_outcome"] = "CHANGES_REQUIRED"
must_fail("source review not approved internal only", lambda: build(review=bad))

bad = review_fixture()
bad["content_review_state"] = "INTERNAL_DRAFT_CHANGES_REQUIRED"
must_fail("source content review state drift", lambda: build(review=bad))

bad = review_fixture()
bad["internal_content_review_approved"] = False
must_fail("source internal approval missing", lambda: build(review=bad))

bad = review_fixture()
bad["next_gate_hint"] = None
must_fail("source finalization gate hint missing", lambda: build(review=bad))

bad = review_fixture()
bad["offer_finalization_gate_required"] = False
must_fail("source finalization gate requirement missing", lambda: build(review=bad))

bad = review_fixture()
bad["official_source_reverified"] = False
must_fail("source official source not reverified", lambda: build(review=bad))

bad = review_fixture()
bad["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("source commercial scope drift", lambda: build(review=bad))

bad = review_fixture()
bad["source_as_of"] = "2026-08-27T21:00:00+03:00"
must_fail("source_as_of not UTC-Z", lambda: build(review=bad))

bad = review_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("source review receipt not human", lambda: build(review=bad))

bad = review_fixture()
bad["final_offer_generation_allowed"] = True
must_fail("source final offer generation failed open", lambda: build(review=bad))

bad = review_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source offer engine failed open", lambda: build(review=bad))

bad = review_fixture()
bad["persistence_executed"] = True
must_fail("source persistence failed open", lambda: build(review=bad))

bad = review_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(review=bad))

bad = review_fixture()
bad["price"] = 1000
must_fail("source pricing payload", lambda: build(review=bad))

bad_decision = decision_fixture()
bad_decision["offer_content_review_id"] = "OFFREVIEW-DRIFT"
must_fail("readiness content review id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_internal_offer_draft_id"] = "OFFDRAFT-DRIFT"
must_fail("readiness draft id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("readiness identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("readiness commercial scope drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["official_source_verification_ref"] = "OFFICIAL:OTHER"
must_fail("readiness source verification drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("readiness source_as_of binding drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["authorization_scope"] = "FINAL_OFFER_GENERATION"
must_fail("readiness authorization scope escaped next-gate only", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "MODEL"
must_fail("readiness decision not human", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-28T00:30:00+03:00"
must_fail("readiness decided_at not UTC-Z", lambda: build(decision=bad_decision))

bad_decision = decision_fixture("APPROVE_AND_GENERATE")
must_fail("readiness outcome escaped allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["offer_text"] = "Injected offer body"
must_fail("freeform offer text in readiness decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["price"] = 1000
must_fail("pricing in readiness decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["reviewer_name"] = "Forbidden Person"
must_fail("person-level readiness field", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_generation_allowed"] = True
must_fail("final offer generation boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_approval_granted"] = True
must_fail("offer approval boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["readiness"]["authorization_scope"] = "FINAL_OFFER_GENERATION"
must_fail("contract authorization scope drift", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["readiness"]["outcome_next_gate_map"]["FINALIZATION_READY_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("next gate policy drift", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["readiness"]["outcome_next_gate_authorization_map"]["FINALIZATION_NOT_READY"] = True
must_fail("next gate authorization map drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["offer_approval_granted"] = True
must_fail("source contract offer approval boundary", lambda: build(source_contract=bad_source_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("source contract next gate drift", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder offer-finalization readiness fail-closed tests: PASS")
