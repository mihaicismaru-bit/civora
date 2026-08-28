#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_final_offer_candidate_generation.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_internal_final_offer_candidate_generation_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_offer_finalization_readiness_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_internal_final_offer_candidate_generation", ENGINE_PATH)
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
        "contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-FINALIZATION-READINESS-001",
        "offer_finalization_readiness_id": "OFFFINAL-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_OFFER_FINALIZATION_READINESS_ENVELOPE",
        "source_content_review_contract_id": "EUCONS-R07-CLIENT-FINDER-OFFER-CONTENT-REVIEW-001",
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
        "finalization_readiness_outcome": "FINALIZATION_READY_INTERNAL_ONLY",
        "finalization_readiness_state": "FINALIZATION_READY_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "next_gate_authorization_granted": True,
        "next_gate_hint": "SEPARATE_FINAL_OFFER_GENERATION_GATE_REQUIRED",
        "final_offer_generation_gate_required": True,
        "finalization_semantics": "INTERNAL_NEXT_GATE_READINESS_ONLY_NOT_FINAL_OFFER_GENERATION_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-006",
            "decided_at": "2026-08-27T21:30:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_generation_authorization_granted": False,
        "content_mutation_allowed": False,
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


def request_fixture():
    return {
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
        "generation_mode": "DETERMINISTIC_INTERNAL_CANDIDATE_ONLY",
    }


def build(readiness=None, request=None, contract=None, source_contract=None):
    return engine.build_internal_final_offer_candidate(
        readiness or readiness_fixture(),
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


candidate = build()
assert candidate["record_state"] == "CLIENT_FINDER_INTERNAL_FINAL_OFFER_CANDIDATE_ENVELOPE"
assert candidate["source_offer_finalization_readiness_id"] == "OFFFINAL-0123456789abcdef01234567"
assert candidate["source_offer_content_review_id"] == "OFFREVIEW-0123456789abcdef01234567"
assert candidate["source_internal_offer_draft_id"] == "OFFDRAFT-0123456789abcdef01234567"
assert candidate["candidate_state"] == "INTERNAL_FINAL_OFFER_CANDIDATE_GENERATED_REVIEW_REQUIRED"
assert candidate["content_scope"] == "INTERNAL_SOURCE_BOUND_CANDIDATE_SKELETON_ONLY"
assert candidate["next_gate_hint"] == "SEPARATE_FINAL_OFFER_CANDIDATE_REVIEW_GATE_REQUIRED"
assert candidate["generation_mode"] == "DETERMINISTIC_INTERNAL_CANDIDATE_ONLY"
assert candidate["candidate_review_required"] is True
assert candidate["source_bound"] is True
assert [section["section_code"] for section in candidate["candidate_sections"]] == [
    "CONTEXT", "SOURCE", "BOUNDARY", "REVIEW"
]
assert candidate["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert candidate["source_as_of"] == "2026-08-27T18:00:00Z"
assert candidate["eligibility_state"] == "NOT_ASSESSED"
assert candidate["maximum_next_state"] == "RESEARCH_READY"
for field in (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "candidate_approval_granted", "target_state_committed",
    "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
):
    assert candidate[field] is False
assert candidate["human_review_required"] is True

again = build()
assert again["internal_final_offer_candidate_id"] == candidate["internal_final_offer_candidate_id"]
assert again["candidate_sections"] == candidate["candidate_sections"]

bad = readiness_fixture()
bad["finalization_readiness_outcome"] = "FINALIZATION_NOT_READY"
must_fail("source finalization not ready", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["next_gate_authorization_granted"] = False
must_fail("source next-gate authorization missing", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["next_gate_hint"] = None
must_fail("source generation gate hint missing", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["final_offer_generation_gate_required"] = False
must_fail("source generation gate requirement missing", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["authorization_scope"] = "FINAL_OFFER_GENERATION"
must_fail("source readiness authorization escaped next-gate only", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["official_source_reverified"] = False
must_fail("source official source not reverified", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("source commercial scope drift", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["source_as_of"] = "2026-08-28T00:30:00+03:00"
must_fail("source_as_of not UTC-Z", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("source readiness receipt not human", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["final_offer_generation_allowed"] = True
must_fail("source final-offer generation failed open", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source offer engine failed open", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["persistence_executed"] = True
must_fail("source persistence failed open", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["person_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(readiness=bad))

bad = readiness_fixture()
bad["price"] = 1000
must_fail("source pricing payload", lambda: build(readiness=bad))

bad_request = request_fixture()
bad_request["source_offer_finalization_readiness_id"] = "OFFFINAL-DRIFT"
must_fail("candidate readiness id drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["source_offer_content_review_id"] = "OFFREVIEW-DRIFT"
must_fail("candidate content review id drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["source_internal_offer_draft_id"] = "OFFDRAFT-DRIFT"
must_fail("candidate draft id drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["selected_service_id"] = "SERVICE-DRIFT"
must_fail("candidate identity drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["commercial_scope_area"] = "FREEFORM_SCOPE"
must_fail("candidate commercial scope drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["official_source_verification_ref"] = "OFFICIAL:OTHER"
must_fail("candidate source verification drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("candidate source_as_of binding drift", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["generation_mode"] = "PRODUCTION_OFFER_ENGINE"
must_fail("candidate generation mode escaped allowlist", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["offer_text"] = "Injected offer body"
must_fail("freeform offer text in candidate request", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["price"] = 1000
must_fail("pricing in candidate request", lambda: build(request=bad_request))

bad_request = request_fixture()
bad_request["reviewer_name"] = "Forbidden Person"
must_fail("person-level candidate field", lambda: build(request=bad_request))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_generated"] = True
must_fail("final offer generated boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_approval_granted"] = True
must_fail("offer approval boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["generation"]["allowed_generation_modes"] = ["PRODUCTION_OFFER_ENGINE"]
must_fail("contract generation mode drift", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["generation"]["next_gate_hint"] = "SEND_OFFER"
must_fail("candidate next gate policy drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["final_offer_generation_allowed"] = True
must_fail("source contract final-offer generation boundary", lambda: build(source_contract=bad_source_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["readiness"]["outcome_next_gate_map"]["FINALIZATION_READY_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("source contract next gate drift", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder internal final-offer candidate generation fail-closed tests: PASS")
