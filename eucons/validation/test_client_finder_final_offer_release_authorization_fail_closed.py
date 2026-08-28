#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_authorization.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_authorization_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_readiness_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_final_offer_release_authorization", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def source_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-READINESS-001",
        "final_offer_release_readiness_id": "OFFRELREADY-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_READINESS_ENVELOPE",
        "source_candidate_review_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-CANDIDATE-REVIEW-001",
        "source_final_offer_candidate_review_id": "OFFCANDREVIEW-0123456789abcdef01234567",
        "source_internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
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
        "release_readiness_outcome": "RELEASE_READY_INTERNAL_ONLY",
        "release_readiness_state": "FINAL_OFFER_RELEASE_READY_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_AUTHORIZATION_GATE_REQUIRED",
        "next_gate_authorized": True,
        "release_readiness_semantics": "INTERNAL_RELEASE_READINESS_ONLY_NOT_RELEASE_AUTHORIZATION_FINAL_OFFER_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {"decision_source": "HUMAN", "reviewer_ref": "REVIEWER-OPAQUE-008", "decided_at": "2026-08-28T00:15:00Z"},
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_release_authorization_granted": False,
        "release_executed": False,
        "pricing_included": False,
        "new_legal_claims_included": False,
        "new_financial_claims_included": False,
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
        "source_final_offer_release_readiness_id": "OFFRELREADY-0123456789abcdef01234567",
        "source_final_offer_candidate_review_id": "OFFCANDREVIEW-0123456789abcdef01234567",
        "source_internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
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
        "release_authorization_outcome": "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-009",
        "decided_at": "2026-08-28T00:45:00Z",
    }


def build(source=None, decision=None, contract=None, source_contract=None):
    return engine.build_final_offer_release_authorization(
        source or source_fixture(), decision or decision_fixture(), contract or CONTRACT, source_contract or SOURCE_CONTRACT
    )


def must_fail(label, fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


result = build()
assert result["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_AUTHORIZATION_ENVELOPE"
assert result["release_authorization_outcome"] == "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY"
assert result["release_authorization_state"] == "FINAL_OFFER_RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY"
assert result["authorization_scope"] == "NEXT_GATE_ONLY"
assert result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_GATE_REQUIRED"
assert result["next_gate_authorized"] is True
assert result["official_source_reverified"] is True
assert result["eligibility_state"] == "NOT_ASSESSED"
assert result["maximum_next_state"] == "RESEARCH_READY"
for field in engine.FALSE_BOUNDARY_FIELDS + engine.DISABLED_ACTION_FLAGS:
    assert result[field] is False
assert result["human_review_required"] is True
assert build()["final_offer_release_authorization_id"] == result["final_offer_release_authorization_id"]

more = decision_fixture()
more["release_authorization_outcome"] = "MORE_AUTHORIZATION_REVIEW_REQUIRED"
more_result = build(decision=more)
assert more_result["release_authorization_state"] == "FINAL_OFFER_RELEASE_AUTHORIZATION_REVIEW_REQUIRED"
assert more_result["next_gate_hint"] is None and more_result["next_gate_authorized"] is False

blocked = decision_fixture()
blocked["release_authorization_outcome"] = "RELEASE_PREPARATION_NOT_AUTHORIZED"
blocked_result = build(decision=blocked)
assert blocked_result["release_authorization_state"] == "FINAL_OFFER_RELEASE_PREPARATION_NOT_AUTHORIZED"
assert blocked_result["next_gate_hint"] is None and blocked_result["next_gate_authorized"] is False

bad = source_fixture(); bad["release_readiness_outcome"] = "RELEASE_NOT_READY"
must_fail("non-ready source outcome", lambda: build(source=bad))
bad = source_fixture(); bad["release_readiness_state"] = "FINAL_OFFER_RELEASE_NOT_READY"
must_fail("non-ready source state", lambda: build(source=bad))
bad = source_fixture(); bad["next_gate_hint"] = "SEND_FINAL_OFFER"
must_fail("source next gate drift", lambda: build(source=bad))
bad = source_fixture(); bad["next_gate_authorized"] = False
must_fail("source next gate authorization missing", lambda: build(source=bad))
bad = source_fixture(); bad["official_source_reverified"] = False
must_fail("official source not reverified", lambda: build(source=bad))
bad = source_fixture(); bad["final_offer_release_authorization_granted"] = True
must_fail("source final release authorization failed open", lambda: build(source=bad))
bad = source_fixture(); bad["release_executed"] = True
must_fail("source release execution failed open", lambda: build(source=bad))
bad = source_fixture(); bad["offer_engine_invocation_allowed"] = True
must_fail("source Offer Engine failed open", lambda: build(source=bad))
bad = source_fixture(); bad["reviewer_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(source=bad))
bad = source_fixture(); bad["source_as_of"] = "2026-08-28T03:00:00+03:00"
must_fail("source timestamp not UTC-Z", lambda: build(source=bad))

bad_decision = decision_fixture(); bad_decision["decision_source"] = "MODEL"
must_fail("authorization decision not human", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["source_final_offer_release_readiness_id"] = "OFFRELREADY-DRIFT"
must_fail("readiness id drift", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["source_internal_final_offer_candidate_id"] = "OFFCAND-DRIFT"
must_fail("candidate lineage drift", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("service identity drift", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["official_source_verification_ref"] = "OFFICIAL:DRIFT"
must_fail("official source verification drift", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("source_as_of lineage drift", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["release_authorization_outcome"] = "RELEASE_EXECUTED"
must_fail("outcome escaped allowlist", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["price"] = 100
must_fail("pricing injected", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["recipient"] = "someone@example.com"
must_fail("recipient injected", lambda: build(decision=bad_decision))
bad_decision = decision_fixture(); bad_decision["decided_at"] = "2026-08-28T03:45:00+03:00"
must_fail("decision timestamp not UTC-Z", lambda: build(decision=bad_decision))

contract = copy.deepcopy(CONTRACT); contract["output"]["final_offer_release_authorization_granted"] = True
must_fail("contract release authorization boundary failed open", lambda: build(contract=contract))
contract = copy.deepcopy(CONTRACT); contract["authorization"]["authorization_scope"] = "FINAL_RELEASE"
must_fail("contract authorization scope failed open", lambda: build(contract=contract))
source_contract = copy.deepcopy(SOURCE_CONTRACT); source_contract["output"]["release_executed"] = True
must_fail("source contract release execution boundary failed open", lambda: build(source_contract=source_contract))

print("EUCONS Client Finder final-offer release authorization fail-closed: PASS")
