#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_content_review.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_content_review_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_offer_draft_generation_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_offer_content_review", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def draft_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-INTERNAL-OFFER-DRAFT-GENERATION-001",
        "internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_INTERNAL_OFFER_DRAFT_ENVELOPE",
        "source_offer_preparation_contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-PREPARATION-AUTHORIZATION-001",
        "source_offer_preparation_authorization_id": "OFFPREP-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "generation_mode": "DETERMINISTIC_INTERNAL_TEMPLATE_ONLY",
        "draft_state": "INTERNAL_OFFER_DRAFT_GENERATED_REVIEW_REQUIRED",
        "content_scope": "INTERNAL_TEMPLATE_SKELETON_ONLY",
        "draft_sections": [
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
        ],
        "next_gate_hint": "SEPARATE_OFFER_CONTENT_REVIEW_GATE_REQUIRED",
        "draft_review_required": True,
        "draft_semantics": "INTERNAL_SOURCE_BOUND_TEMPLATE_NOT_APPROVED_OFFER_PRICING_ELIGIBILITY_OR_OUTREACH",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "internal_draft_generated": True,
        "internal_draft_content_included": True,
        "public_offer_content_included": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "source_bound": True,
        "draft_approval_granted": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "draft_persistence_allowed": False,
        "production_offer_generation_allowed": False,
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


def decision_fixture(outcome="APPROVED_INTERNAL_ONLY"):
    return {
        "internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "content_review_outcome": outcome,
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-005",
        "decided_at": "2026-08-27T20:15:00Z",
    }


def build(draft=None, decision=None, contract=None, source_contract=None):
    return engine.build_offer_content_review(
        draft or draft_fixture(),
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


review = build()
assert review["record_state"] == "CLIENT_FINDER_OFFER_CONTENT_REVIEW_ENVELOPE"
assert review["source_internal_offer_draft_id"] == "OFFDRAFT-0123456789abcdef01234567"
assert review["content_review_outcome"] == "APPROVED_INTERNAL_ONLY"
assert review["content_review_state"] == "INTERNAL_DRAFT_CONTENT_APPROVED_INTERNAL_ONLY"
assert review["internal_content_review_approved"] is True
assert review["next_gate_hint"] == "SEPARATE_OFFER_FINALIZATION_GATE_REQUIRED"
assert review["offer_finalization_gate_required"] is True
assert review["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert review["source_as_of"] == "2026-08-27T18:00:00Z"
assert review["decision_receipt"]["decision_source"] == "HUMAN"
assert review["eligibility_state"] == "NOT_ASSESSED"
assert review["maximum_next_state"] == "RESEARCH_READY"
for field in (
    "offer_approval_granted", "draft_approval_granted", "pricing_included",
    "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
    "persistence_executed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert review[field] is False
assert review["human_review_required"] is True

changes = build(decision=decision_fixture("CHANGES_REQUIRED"))
assert changes["content_review_state"] == "INTERNAL_DRAFT_CHANGES_REQUIRED"
assert changes["internal_content_review_approved"] is False
assert changes["next_gate_hint"] is None
assert changes["offer_finalization_gate_required"] is False

rejected = build(decision=decision_fixture("REJECTED"))
assert rejected["content_review_state"] == "INTERNAL_DRAFT_REJECTED"
assert rejected["internal_content_review_approved"] is False
assert rejected["next_gate_hint"] is None
assert rejected["offer_finalization_gate_required"] is False

bad = draft_fixture()
bad["draft_state"] = "INTERNAL_OFFER_DRAFT_GENERATED"
must_fail("source draft state drift", lambda: build(draft=bad))

bad = draft_fixture()
bad["next_gate_hint"] = None
must_fail("source content review gate hint missing", lambda: build(draft=bad))

bad = draft_fixture()
bad["content_scope"] = "FREEFORM_OFFER"
must_fail("source content scope drift", lambda: build(draft=bad))

bad = draft_fixture()
bad["generation_mode"] = "MODEL_FREEFORM"
must_fail("source generation mode drift", lambda: build(draft=bad))

bad = draft_fixture()
bad["official_source_reverified"] = False
must_fail("source official source not reverified", lambda: build(draft=bad))

bad = draft_fixture()
bad["source_bound"] = False
must_fail("source draft not source-bound", lambda: build(draft=bad))

bad = draft_fixture()
bad["source_as_of"] = "2026-08-27T21:00:00+03:00"
must_fail("source_as_of not UTC-Z", lambda: build(draft=bad))

bad = draft_fixture()
bad["draft_sections"][0]["text"] = "Modified freeform offer text"
must_fail("source deterministic draft content drift", lambda: build(draft=bad))

bad = draft_fixture()
bad["draft_approval_granted"] = True
must_fail("source draft approval failed open", lambda: build(draft=bad))

bad = draft_fixture()
bad["pricing_included"] = True
must_fail("source draft pricing failed open", lambda: build(draft=bad))

bad = draft_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source draft offer engine failed open", lambda: build(draft=bad))

bad = draft_fixture()
bad["persistence_executed"] = True
must_fail("source draft persistence failed open", lambda: build(draft=bad))

bad = draft_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("source draft person-level field", lambda: build(draft=bad))

bad = draft_fixture()
bad["budget"] = "100000"
must_fail("source draft material payload", lambda: build(draft=bad))

bad_decision = decision_fixture()
bad_decision["internal_offer_draft_id"] = "OFFDRAFT-DRIFT"
must_fail("review draft id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("review identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("review commercial scope drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["official_source_verification_ref"] = "OFFICIAL:OTHER"
must_fail("review source verification drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("review source_as_of binding drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "MODEL"
must_fail("review decision not human", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-27T23:15:00+03:00"
must_fail("review decided_at not UTC-Z", lambda: build(decision=bad_decision))

bad_decision = decision_fixture("APPROVE_AND_SEND")
must_fail("review outcome escaped allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["offer_text"] = "Injected offer body"
must_fail("freeform offer text in review decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["price"] = 1000
must_fail("pricing in review decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["reviewer_name"] = "Forbidden Person"
must_fail("person-level review field", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_approval_granted"] = True
must_fail("offer approval boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("offer engine boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["pricing_decision_allowed"] = True
must_fail("pricing decision boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("next gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["draft_approval_granted"] = True
must_fail("source contract draft approval boundary", lambda: build(source_contract=bad_source_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["generation"]["next_gate_hint"] = "SEND_OFFER"
must_fail("source contract next gate drift", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder offer-content review fail-closed tests: PASS")
