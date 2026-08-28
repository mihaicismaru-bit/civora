#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_commit_review.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_commit_review_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_commit_preparation_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_final_offer_release_execution_commit_review", ENGINE_PATH)
engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(engine)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


CONTRACT = load(CONTRACT_PATH)
SOURCE_CONTRACT = load(SOURCE_CONTRACT_PATH)

FALSE_FIELDS = (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "release_package_approved", "pricing_included",
    "new_legal_claims_included", "new_financial_claims_included", "target_state_committed",
    "persistence_executed", "candidate_persistence_allowed", "draft_persistence_allowed",
    "offer_persistence_allowed", "production_offer_generation_allowed", "final_offer_generation_allowed",
    "offer_engine_invocation_allowed", "pricing_decision_allowed", "crm_context_materialization_allowed",
    "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
    "crm_write_enabled", "pipeline_write_enabled",
)
LINEAGE = {
    "source_final_offer_release_execution_review_id": "OFFRELEXECREVIEW-0123456789abcdef01234567",
    "source_final_offer_release_execution_preparation_id": "OFFRELEXECPREP-0123456789abcdef01234567",
    "source_final_offer_release_execution_authorization_id": "OFFRELEXECAUTH-0123456789abcdef01234567",
    "source_final_offer_release_package_review_id": "OFFRELPKGREVIEW-0123456789abcdef01234567",
    "source_final_offer_release_package_preparation_id": "OFFRELPREP-0123456789abcdef01234567",
    "source_final_offer_release_authorization_id": "OFFRELAUTH-0123456789abcdef01234567",
    "source_final_offer_release_readiness_id": "OFFRELREADY-0123456789abcdef01234567",
    "source_final_offer_candidate_review_id": "OFFCANDREVIEW-0123456789abcdef01234567",
    "source_internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
    "source_offer_finalization_readiness_id": "OFFFINAL-0123456789abcdef01234567",
    "source_offer_content_review_id": "OFFREVIEW-0123456789abcdef01234567",
    "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
}


def preparation_fixture():
    result = {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-PREPARATION-001",
        "final_offer_release_execution_commit_preparation_id": "OFFRELEXECCOMMITPREP-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_ENVELOPE",
        "source_authorization_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-AUTHORIZATION-001",
        "source_final_offer_release_execution_commit_authorization_id": "OFFRELEXECCOMMITAUTH-0123456789abcdef01234567",
        **LINEAGE,
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-28:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-28T01:00:00Z",
        "preparation_mode": "DETERMINISTIC_INTERNAL_COMMIT_INTENT_ONLY",
        "commit_intent": {
            "command_type": "INTERNAL_RELEASE_EXECUTION_COMMIT_INTENT_REVIEW_ENVELOPE_ONLY",
            "external_action": "NO_EXTERNAL_ACTION",
            "release_action": "NOT_EXECUTED",
            "send_action": "NOT_EXECUTED",
            "publication_action": "NOT_EXECUTED",
            "persistence_action": "NOT_EXECUTED",
        },
        "commit_preparation_state": "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_PREPARED_REVIEW_REQUIRED",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_GATE_REQUIRED",
        "commit_preparation_semantics": "DETERMINISTIC_INTERNAL_COMMIT_INTENT_FOR_HUMAN_REVIEW_ONLY_NO_EXTERNAL_ACTION_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "source_bound": True,
        "human_review_required": True,
        "commit_intent_generated": True,
    }
    for field in FALSE_FIELDS:
        result[field] = False
    return result


def decision_fixture():
    return {
        "final_offer_release_execution_commit_preparation_id": "OFFRELEXECCOMMITPREP-0123456789abcdef01234567",
        "source_final_offer_release_execution_commit_authorization_id": "OFFRELEXECCOMMITAUTH-0123456789abcdef01234567",
        **LINEAGE,
        "organization_key": "ORG-DEMO-001",
        "prospect_id": "PROSPECT-DEMO-001",
        "selected_opportunity_id": "OPP-DEMO-001",
        "selected_service_id": "SERVICE-DEMO-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_verification_ref": "OFFICIAL:2026-08-28:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-28T01:00:00Z",
        "commit_review_outcome": "APPROVED_INTERNAL_ONLY",
        "decision_source": "HUMAN",
        "reviewer_ref": "REVIEWER-OPAQUE-011",
        "decided_at": "2026-08-28T09:00:00Z",
    }


def build(preparation=None, decision=None, contract=None, source_contract=None):
    return engine.build_final_offer_release_execution_commit_review(
        preparation or preparation_fixture(),
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
assert review["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_ENVELOPE"
assert review["commit_review_outcome"] == "APPROVED_INTERNAL_ONLY"
assert review["commit_review_state"] == "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_APPROVED_INTERNAL_ONLY"
assert review["commit_intent_review_approved"] is True
assert review["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_FINAL_AUTHORIZATION_GATE_REQUIRED"
assert review["final_release_execution_authorization_gate_required"] is True
assert review["decision_receipt"]["decision_source"] == "HUMAN"
assert review["eligibility_state"] == "NOT_ASSESSED"
assert review["maximum_next_state"] == "RESEARCH_READY"
assert review["source_bound"] is True
assert review["human_review_required"] is True
for field in FALSE_FIELDS:
    assert review[field] is False
assert build()["final_offer_release_execution_commit_review_id"] == review["final_offer_release_execution_commit_review_id"]

changes = decision_fixture()
changes["commit_review_outcome"] = "CHANGES_REQUIRED"
changes_result = build(decision=changes)
assert changes_result["next_gate_hint"] is None
assert changes_result["final_release_execution_authorization_gate_required"] is False
assert changes_result["commit_intent_review_approved"] is False

for field, value in (
    ("commit_preparation_state", "RELEASE_EXECUTED"),
    ("next_gate_hint", "SEND_OFFER"),
    ("preparation_mode", "EXECUTE_RELEASE"),
    ("official_source_reverified", False),
    ("source_bound", False),
    ("commit_intent_generated", False),
    ("release_executed", True),
    ("final_offer_release_authorization_granted", True),
    ("offer_engine_invocation_allowed", True),
    ("persistence_executed", True),
):
    bad = preparation_fixture()
    bad[field] = value
    must_fail(f"source boundary {field}", lambda b=bad: build(preparation=b))

bad = preparation_fixture()
bad["commit_intent"]["external_action"] = "SEND"
must_fail("commit-intent external action drift", lambda: build(preparation=bad))

bad = preparation_fixture()
bad["commit_intent"]["persistence_action"] = "EXECUTED"
must_fail("commit-intent persistence drift", lambda: build(preparation=bad))

bad = preparation_fixture()
bad["source_as_of"] = "2026-08-28T04:00:00+03:00"
must_fail("source_as_of not UTC-Z", lambda: build(preparation=bad))

bad = preparation_fixture()
bad["recipient"] = "external"
must_fail("source recipient leakage", lambda: build(preparation=bad))

bad_decision = decision_fixture()
bad_decision["decision_source"] = "MODEL"
must_fail("commit review decision not human", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["final_offer_release_execution_commit_preparation_id"] = "OFFRELEXECCOMMITPREP-DRIFT"
must_fail("commit preparation id drift", lambda: build(decision=bad_decision))

bad_decision = decision_fixture()
bad_decision["source_final_offer_release_execution_commit_authorization_id"] = "OFFRELEXECCOMMITAUTH-DRIFT"
must_fail("commit authorization id drift", lambda: build(decision=bad_decision))

for field in LINEAGE:
    bad_decision = decision_fixture()
    bad_decision[field] = "DRIFT-" + field
    must_fail(f"lineage drift {field}", lambda d=bad_decision: build(decision=d))

for field, value in (
    ("selected_service_id", "SERVICE-DRIFT"),
    ("commercial_scope_area", "FREEFORM_SCOPE"),
    ("official_source_verification_ref", "OFFICIAL:OTHER"),
    ("source_as_of", "2026-08-28T01:01:00Z"),
    ("commit_review_outcome", "SEND_NOW"),
    ("decided_at", "2026-08-28T12:00:00+03:00"),
):
    bad_decision = decision_fixture()
    bad_decision[field] = value
    must_fail(f"decision drift {field}", lambda d=bad_decision: build(decision=d))

for field, value in (
    ("offer_text", "Injected offer"),
    ("price", 1000),
    ("recipient", "external-target"),
    ("channel", "email"),
):
    bad_decision = decision_fixture()
    bad_decision[field] = value
    must_fail(f"forbidden decision field {field}", lambda d=bad_decision: build(decision=d))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["output"]["final_offer_release_authorization_granted"] = True
must_fail("release authority boundary", lambda: build(contract=bad_contract))

bad_contract = copy.deepcopy(CONTRACT)
bad_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = "SEND_OFFER"
must_fail("review next-gate drift", lambda: build(contract=bad_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["preparation"]["commit_intent"]["external_action"] = "SEND"
must_fail("source contract command boundary", lambda: build(source_contract=bad_source_contract))

bad_source_contract = copy.deepcopy(SOURCE_CONTRACT)
bad_source_contract["output"]["release_executed"] = True
must_fail("source contract release boundary", lambda: build(source_contract=bad_source_contract))

print("EUCONS Client Finder final-offer release-execution commit-review fail-closed tests: PASS")
