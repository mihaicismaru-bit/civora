#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_candidate_review.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_candidate_review_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_final_offer_candidate_generation_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_final_offer_candidate_review", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def candidate_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-INTERNAL-FINAL-OFFER-CANDIDATE-GENERATION-001",
        "internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_INTERNAL_FINAL_OFFER_CANDIDATE_ENVELOPE",
        "source_finalization_readiness_contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-FINALIZATION-READINESS-001",
        "source_offer_finalization_readiness_id": "OFFFINAL-0123456789abcdef01234567",
        "source_offer_content_review_id": "OFFREVIEW-0123456789abcdef01234567",
        "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "generation_mode": "DETERMINISTIC_INTERNAL_CANDIDATE_ONLY",
        "candidate_state": "INTERNAL_FINAL_OFFER_CANDIDATE_GENERATED_REVIEW_REQUIRED",
        "content_scope": "INTERNAL_SOURCE_BOUND_CANDIDATE_SKELETON_ONLY",
        "candidate_sections": [
            {
                "section_code": "CONTEXT",
                "text": (
                    "Candidat intern de ofertă pentru organizația ORG-DEMO-001, în contextul oportunității "
                    "OPP-DEMO-001, limitat la serviciul selectat SERVICE-DEMO-001."
                ),
            },
            {
                "section_code": "SOURCE",
                "text": (
                    "Conținutul rămâne legat de referința de verificare oficială "
                    "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1 și de snapshot-ul sursei 2026-08-27T18:00:00Z."
                ),
            },
            {
                "section_code": "BOUNDARY",
                "text": (
                    "Acest candidat intern nu este ofertă finală sau aprobată și nu include preț, buget, termen, "
                    "indicatori, obligații ori concluzii juridice sau financiare."
                ),
            },
            {
                "section_code": "REVIEW",
                "text": (
                    "Orice afirmație materială trebuie reverificată în sursa oficială; candidatul necesită review uman "
                    "separat înainte de orice finalizare, persistență sau acțiune comercială."
                ),
            },
        ],
        "next_gate_hint": "SEPARATE_FINAL_OFFER_CANDIDATE_REVIEW_GATE_REQUIRED",
        "candidate_review_required": True,
        "candidate_semantics": "INTERNAL_SOURCE_BOUND_CANDIDATE_NOT_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "internal_final_offer_candidate_generated": True,
        "candidate_content_included": True,
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
        "source_bound": True,
        "candidate_approval_granted": False,
        "target_state_committed": False,
        "persistence_executed": False,
        "candidate_persistence_allowed": False,
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


def decision_fixture():
    return {
        "internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
        "source_offer_finalization_readiness_id": "OFFFINAL-0123456789abcdef01234567",
        "source_offer_content_review_id": "OFFREVIEW-0123456789abcdef01234567",
        "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "candidate_review_outcome": "APPROVED_INTERNAL_ONLY",
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-007",
        "decided_at": "2026-08-27T22:30:00Z",
    }


def build(candidate=None, decision=None, contract=None, source_contract=None):
    return engine.build_final_offer_candidate_review(
        candidate or candidate_fixture(),
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
assert review["record_state"] == "CLIENT_FINDER_FINAL_OFFER_CANDIDATE_REVIEW_ENVELOPE"
assert review["source_internal_final_offer_candidate_id"] == "OFFCAND-0123456789abcdef01234567"
assert review["source_offer_finalization_readiness_id"] == "OFFFINAL-0123456789abcdef01234567"
assert review["source_offer_content_review_id"] == "OFFREVIEW-0123456789abcdef01234567"
assert review["source_internal_offer_draft_id"] == "OFFDRAFT-0123456789abcdef01234567"
assert review["candidate_review_outcome"] == "APPROVED_INTERNAL_ONLY"
assert review["candidate_review_state"] == "INTERNAL_FINAL_OFFER_CANDIDATE_APPROVED_INTERNAL_ONLY"
assert review["internal_candidate_review_approved"] is True
assert review["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_READINESS_GATE_REQUIRED"
assert review["final_offer_release_readiness_gate_required"] is True
assert review["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert review["source_as_of"] == "2026-08-27T18:00:00Z"
assert review["decision_receipt"]["decision_source"] == "HUMAN"
assert review["eligibility_state"] == "NOT_ASSESSED"
assert review["maximum_next_state"] == "RESEARCH_READY"
for field in (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted",
    "candidate_approval_granted", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert review[field] is False
assert review["human_review_required"] is True

again = build()
assert again["final_offer_candidate_review_id"] == review["final_offer_candidate_review_id"]

changes = decision_fixture()
changes["candidate_review_outcome"] = "CHANGES_REQUIRED"
changes_result = build(decision=changes)
assert changes_result["next_gate_hint"] is None
assert changes_result["final_offer_release_readiness_gate_required"] is False
assert changes_result["internal_candidate_review_approved"] is False

bad = candidate_fixture()
bad["candidate_state"] = "FINAL_OFFER_READY"
must_fail("source candidate state escaped review", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["next_gate_hint"] = "SEND_OFFER"
must_fail("source candidate review gate drift", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["candidate_review_required"] = False
must_fail("source candidate review requirement missing", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["candidate_approval_granted"] = True
must_fail("source candidate pre-approved", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["official_source_reverified"] = False
must_fail("source official source not reverified", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["source_bound"] = False
must_fail("source candidate not source-bound", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["candidate_sections"][0]["text"] += " edited"
must_fail("source candidate deterministic section drift", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["source_as_of"] = "2026-08-28T01:00:00+03:00"
must_fail("source candidate source_as_of not UTC-Z", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["final_offer_generated"] = True
must_fail("source final offer generation failed open", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source offer engine failed open", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["persistence_executed"] = True
must_fail("source persistence failed open", lambda: build(candidate=bad))

bad = candidate_fixture()
bad["reviewer_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(candidate=bad))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "MODEL"
must_fail("candidate review decision not human", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["internal_final_offer_candidate_id"] = "OFFCAND-DRIFT"
must_fail("candidate id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_offer_finalization_readiness_id"] = "OFFFINAL-DRIFT"
must_fail("readiness lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_offer_content_review_id"] = "OFFREVIEW-DRIFT"
must_fail("content review lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_internal_offer_draft_id"] = "OFFDRAFT-DRIFT"
must_fail("draft lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("candidate review identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("candidate review commercial scope drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["official_source_verification_ref"] = "OFFICIAL:OTHER"
must_fail("candidate review source verification drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("candidate review source_as_of binding drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["candidate_review_outcome"] = "SEND_NOW"
must_fail("candidate review outcome escaped allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-28T01:30:00+03:00"
must_fail("candidate review decided_at not UTC-Z", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["offer_text"] = "Injected public offer"
must_fail("freeform offer text in review decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["price"] = 1000
must_fail("pricing in review decision", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["reviewer_name"] = "Forbidden Person"
must_fail("person-level review field", lambda: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_release_authorization_granted"] = True
must_fail("release authorization boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_generated"] = True
must_fail("final offer generated boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("review next gate drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["candidate_approval_granted"] = True
must_fail("source contract candidate approval boundary", lambda: build(source_contract=bad_source_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["generation"]["next_gate_hint"] = "SEND_OFFER"
must_fail("source contract next gate drift", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder final-offer candidate review fail-closed tests: PASS")
