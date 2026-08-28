#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_readiness.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_readiness_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_candidate_review_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_final_offer_release_readiness", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)


def source_review_fixture():
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-CANDIDATE-REVIEW-001",
        "final_offer_candidate_review_id": "OFFCANDREVIEW-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_CANDIDATE_REVIEW_ENVELOPE",
        "source_candidate_contract_id": "EUCONS-R07-CLIENT-FINDER-INTERNAL-FINAL-OFFER-CANDIDATE-GENERATION-001",
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
        "candidate_review_outcome": "APPROVED_INTERNAL_ONLY",
        "candidate_review_state": "INTERNAL_FINAL_OFFER_CANDIDATE_APPROVED_INTERNAL_ONLY",
        "internal_candidate_review_approved": True,
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_READINESS_GATE_REQUIRED",
        "final_offer_release_readiness_gate_required": True,
        "candidate_review_semantics": "INTERNAL_CANDIDATE_REVIEW_ONLY_NOT_FINAL_OFFER_OR_RELEASE_APPROVAL_PRICING_PERSISTENCE_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "REVIEWER-OPAQUE-007",
            "decided_at": "2026-08-27T22:30:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_release_authorization_granted": False,
        "candidate_approval_granted": False,
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
        "release_readiness_outcome": "RELEASE_READY_INTERNAL_ONLY",
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-008",
        "decided_at": "2026-08-28T00:15:00Z",
    }


def build(source_review=None, decision=None, contract=None, source_contract=None):
    return engine.build_final_offer_release_readiness(
        source_review or source_review_fixture(),
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


result = build()
assert result["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_READINESS_ENVELOPE"
assert result["source_final_offer_candidate_review_id"] == "OFFCANDREVIEW-0123456789abcdef01234567"
assert result["source_internal_final_offer_candidate_id"] == "OFFCAND-0123456789abcdef01234567"
assert result["release_readiness_outcome"] == "RELEASE_READY_INTERNAL_ONLY"
assert result["release_readiness_state"] == "FINAL_OFFER_RELEASE_READY_INTERNAL_ONLY"
assert result["authorization_scope"] == "NEXT_GATE_ONLY"
assert result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_AUTHORIZATION_GATE_REQUIRED"
assert result["next_gate_authorized"] is True
assert result["official_source_reverified"] is True
assert result["official_source_verification_ref"] == "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1"
assert result["source_as_of"] == "2026-08-27T18:00:00Z"
assert result["decision_receipt"]["decision_source"] == "HUMAN"
assert result["eligibility_state"] == "NOT_ASSESSED"
assert result["maximum_next_state"] == "RESEARCH_READY"
for field in (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "pricing_included", "new_legal_claims_included", "new_financial_claims_included",
    "target_state_committed", "persistence_executed", "candidate_persistence_allowed",
    "draft_persistence_allowed", "offer_persistence_allowed", "production_offer_generation_allowed",
    "final_offer_generation_allowed", "offer_engine_invocation_allowed", "pricing_decision_allowed",
    "crm_context_materialization_allowed", "external_contact_enabled", "automatic_offer_enabled",
    "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
):
    assert result[field] is False
assert result["human_review_required"] is True

again = build()
assert again["final_offer_release_readiness_id"] == result["final_offer_release_readiness_id"]

more = decision_fixture()
more["release_readiness_outcome"] = "MORE_RELEASE_REVIEW_REQUIRED"
more_result = build(decision=more)
assert more_result["release_readiness_state"] == "FINAL_OFFER_RELEASE_REVIEW_REQUIRED"
assert more_result["next_gate_hint"] is None
assert more_result["next_gate_authorized"] is False

not_ready = decision_fixture()
not_ready["release_readiness_outcome"] = "RELEASE_NOT_READY"
not_ready_result = build(decision=not_ready)
assert not_ready_result["release_readiness_state"] == "FINAL_OFFER_RELEASE_NOT_READY"
assert not_ready_result["next_gate_hint"] is None
assert not_ready_result["next_gate_authorized"] is False

bad = source_review_fixture()
bad["candidate_review_outcome"] = "CHANGES_REQUIRED"
must_fail("unapproved source candidate review", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["candidate_review_state"] = "INTERNAL_FINAL_OFFER_CANDIDATE_CHANGES_REQUIRED"
must_fail("source candidate-review state drift", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["internal_candidate_review_approved"] = False
must_fail("source internal candidate approval marker missing", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["next_gate_hint"] = "SEND_FINAL_OFFER"
must_fail("source release-readiness gate hint drift", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["final_offer_release_readiness_gate_required"] = False
must_fail("source release-readiness requirement missing", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["official_source_reverified"] = False
must_fail("source official source not reverified", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["commercial_scope_area"] = "EXPANDED_SCOPE"
must_fail("source commercial scope expanded", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["source_as_of"] = "2026-08-28T03:00:00+03:00"
must_fail("source source_as_of not UTC-Z", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("source candidate review receipt not human", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["final_offer_release_authorization_granted"] = True
must_fail("source release authorization failed open", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["final_offer_generated"] = True
must_fail("source final offer generation failed open", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["offer_engine_invocation_allowed"] = True
must_fail("source offer engine failed open", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["persistence_executed"] = True
must_fail("source persistence failed open", lambda: build(source_review=bad))

bad = source_review_fixture()
bad["reviewer_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(source_review=bad))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "MODEL"
must_fail("release-readiness decision not human", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_final_offer_candidate_review_id"] = "OFFCANDREVIEW-DRIFT"
must_fail("candidate review id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_internal_final_offer_candidate_id"] = "OFFCAND-DRIFT"
must_fail("candidate id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_offer_finalization_readiness_id"] = "OFFFINAL-DRIFT"
must_fail("finalization readiness lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_offer_content_review_id"] = "OFFREVIEW-DRIFT"
must_fail("content review lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_internal_offer_draft_id"] = "OFFDRAFT-DRIFT"
must_fail("draft lineage drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["selected_service_id"] = "SERVICE-DRIFT"
must_fail("service identity drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["official_source_verification_ref"] = "OFFICIAL:DRIFT"
must_fail("official source verification drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("source_as_of drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["release_readiness_outcome"] = "RELEASE_AUTHORIZED"
must_fail("release outcome escaped allowlist", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["decided_at"] = "2026-08-28T03:15:00+03:00"
must_fail("decision time not UTC-Z", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["reviewer_ref"] = "name@example.com"
must_fail("unsafe reviewer ref", lambda: build(decision=bad_decision))

for key, value in (
    ("price", "1000 EUR"),
    ("budget", "500000"),
    ("deadline", "2026-09-30"),
    ("offer_body", "Please sign."),
    ("final_offer_text", "Final offer."),
    ("legal_conclusion", "Eligible."),
    ("financial_conclusion", "Profitable."),
    ("conversion_probability", 0.9),
    ("buying_intent", "HIGH"),
    ("recipient", "client"),
):
    bad_decision = decision_fixture()
    bad_decision[key] = value
    must_fail(f"forbidden decision payload {key}", lambda bad_decision=bad_decision: build(decision=bad_decision))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["readiness"]["authorization_scope"] = "RELEASE"
must_fail("contract authorization scope failed open", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["readiness"]["outcome_next_gate_map"]["RELEASE_READY_INTERNAL_ONLY"] = "SEND_FINAL_OFFER"
must_fail("contract next gate failed open", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_release_authorization_granted"] = True
must_fail("contract release authorization failed open", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["offer_engine_invocation_allowed"] = True
must_fail("contract Offer Engine failed open", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = "SEND_FINAL_OFFER"
must_fail("source contract next gate drift", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder final-offer release-readiness fail-closed checks passed.")
