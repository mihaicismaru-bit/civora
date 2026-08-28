#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_authorization.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_authorization_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_package_review_contract.json"

spec = importlib.util.spec_from_file_location("release_execution_authorization", ENGINE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))


def valid_source_review():
    result = {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-REVIEW-001",
        "final_offer_release_package_review_id": "OFFRELPKGREVIEW-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_ENVELOPE",
        "source_release_package_preparation_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-PREPARATION-001",
        "source_final_offer_release_package_preparation_id": "OFFRELPKGPREP-0123456789abcdef01234567",
        "source_final_offer_release_authorization_id": "OFFRELAUTH-0123456789abcdef01234567",
        "source_final_offer_release_readiness_id": "OFFRELREADY-0123456789abcdef01234567",
        "source_final_offer_candidate_review_id": "OFFCANDREVIEW-0123456789abcdef01234567",
        "source_internal_final_offer_candidate_id": "OFFCAND-0123456789abcdef01234567",
        "source_offer_finalization_readiness_id": "OFFFINALREADY-0123456789abcdef01234567",
        "source_offer_content_review_id": "OFFCONTENTREVIEW-0123456789abcdef01234567",
        "source_internal_offer_draft_id": "OFFDRAFT-0123456789abcdef01234567",
        "organization_key": "org-001",
        "prospect_id": "prospect-001",
        "selected_opportunity_id": "opp-001",
        "selected_service_id": "service-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "official-source-ref-001",
        "source_as_of": "2026-08-28T02:30:00Z",
        "package_review_outcome": "APPROVED_INTERNAL_ONLY",
        "package_review_state": "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_APPROVED_INTERNAL_ONLY",
        "internal_release_package_review_approved": True,
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_AUTHORIZATION_GATE_REQUIRED",
        "release_execution_authorization_gate_required": True,
        "package_review_semantics": "INTERNAL_RELEASE_PACKAGE_REVIEW_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "reviewer-ref-001",
            "decided_at": "2026-08-28T02:45:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "source_bound": True,
        "human_review_required": True,
    }
    for field in module.FALSE_BOUNDARY_FIELDS:
        result[field] = False
    for flag in module.DISABLED_ACTION_FLAGS:
        result[flag] = False
    return result


def valid_decision():
    source = valid_source_review()
    return {
        "source_final_offer_release_package_review_id": source["final_offer_release_package_review_id"],
        "source_final_offer_release_package_preparation_id": source["source_final_offer_release_package_preparation_id"],
        "source_final_offer_release_authorization_id": source["source_final_offer_release_authorization_id"],
        "source_final_offer_release_readiness_id": source["source_final_offer_release_readiness_id"],
        "source_final_offer_candidate_review_id": source["source_final_offer_candidate_review_id"],
        "source_internal_final_offer_candidate_id": source["source_internal_final_offer_candidate_id"],
        "source_offer_finalization_readiness_id": source["source_offer_finalization_readiness_id"],
        "source_offer_content_review_id": source["source_offer_content_review_id"],
        "source_internal_offer_draft_id": source["source_internal_offer_draft_id"],
        "organization_key": source["organization_key"],
        "prospect_id": source["prospect_id"],
        "selected_opportunity_id": source["selected_opportunity_id"],
        "selected_service_id": source["selected_service_id"],
        "commercial_scope_area": source["commercial_scope_area"],
        "official_source_verification_ref": source["official_source_verification_ref"],
        "source_as_of": source["source_as_of"],
        "release_execution_authorization_outcome": "RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "decision_source": "HUMAN",
        "reviewer_ref": "execution-reviewer-ref-001",
        "decided_at": "2026-08-28T03:15:00Z",
    }


def expect_rejected(source=None, decision=None, use_contract=None, use_source_contract=None):
    try:
        module.build_final_offer_release_execution_authorization(
            source if source is not None else valid_source_review(),
            decision if decision is not None else valid_decision(),
            use_contract if use_contract is not None else contract,
            use_source_contract if use_source_contract is not None else source_contract,
        )
    except ValueError:
        return
    raise AssertionError("unsafe release-execution authorization input was accepted")


source = valid_source_review()
decision = valid_decision()
result = module.build_final_offer_release_execution_authorization(source, decision, contract, source_contract)

assert result["release_execution_authorization_state"] == "FINAL_OFFER_RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY"
assert result["authorization_scope"] == "NEXT_GATE_ONLY"
assert result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_GATE_REQUIRED"
assert result["next_gate_authorized"] is True
assert result["final_offer_release_authorization_granted"] is False
assert result["release_executed"] is False
assert result["release_package_generated"] is False
assert result["release_package_approved"] is False
assert result["pricing_included"] is False
assert result["offer_engine_invocation_allowed"] is False
assert result["persistence_executed"] is False
assert result["crm_context_materialization_allowed"] is False
assert result["external_contact_enabled"] is False
assert result["automatic_send_enabled"] is False
assert result["crm_write_enabled"] is False
assert result["pipeline_write_enabled"] is False
assert result["eligibility_state"] == "NOT_ASSESSED"
assert result["maximum_next_state"] == "RESEARCH_READY"
assert result["human_review_required"] is True
assert result == module.build_final_offer_release_execution_authorization(
    valid_source_review(), valid_decision(), contract, source_contract
)

negative = valid_decision()
negative["release_execution_authorization_outcome"] = "RELEASE_EXECUTION_NOT_AUTHORIZED"
negative_result = module.build_final_offer_release_execution_authorization(
    valid_source_review(), negative, contract, source_contract
)
assert negative_result["next_gate_hint"] is None
assert negative_result["next_gate_authorized"] is False
assert negative_result["release_executed"] is False

for field, value in (
    ("package_review_outcome", "CHANGES_REQUIRED"),
    ("package_review_state", "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_CHANGES_REQUIRED"),
    ("next_gate_hint", None),
    ("internal_release_package_review_approved", False),
    ("release_execution_authorization_gate_required", False),
    ("official_source_reverified", False),
    ("source_bound", False),
    ("release_package_generated", True),
    ("release_package_approved", True),
    ("final_offer_release_authorization_granted", True),
    ("release_executed", True),
    ("automatic_send_enabled", True),
):
    bad = valid_source_review()
    bad[field] = value
    expect_rejected(source=bad)

bad = valid_source_review()
bad["source_as_of"] = "2026-08-28T05:30:00+03:00"
expect_rejected(source=bad)

bad = valid_source_review()
bad["decision_receipt"]["decision_source"] = "AI"
expect_rejected(source=bad)

bad = valid_source_review()
bad["decision_receipt"]["decided_at"] = "2026-08-28T05:45:00+03:00"
expect_rejected(source=bad)

bad = valid_source_review()
bad["recipient"] = "somewhere"
expect_rejected(source=bad)

for field, value in (
    ("source_final_offer_release_package_review_id", "different-review"),
    ("source_final_offer_release_package_preparation_id", "different-package"),
    ("source_final_offer_release_authorization_id", "different-lineage"),
    ("organization_key", "different-org"),
    ("selected_service_id", "different-service"),
    ("commercial_scope_area", "EXPANDED_SCOPE"),
    ("official_source_verification_ref", "different-source"),
    ("source_as_of", "2026-08-28T02:31:00Z"),
    ("release_execution_authorization_outcome", "EXECUTE_NOW"),
    ("authorization_scope", "EXECUTE_RELEASE"),
    ("decision_source", "AI"),
):
    bad = valid_decision()
    bad[field] = value
    expect_rejected(decision=bad)

bad = valid_decision()
bad["reviewer_ref"] = "reviewer@example.com"
expect_rejected(decision=bad)

bad = valid_decision()
bad["decided_at"] = "2026-08-28T06:15:00+03:00"
expect_rejected(decision=bad)

bad = valid_decision()
bad["price"] = 1000
expect_rejected(decision=bad)

drifted_contract = copy.deepcopy(contract)
drifted_contract["output"]["release_executed"] = True
expect_rejected(use_contract=drifted_contract)

drifted_source_contract = copy.deepcopy(source_contract)
drifted_source_contract["review"]["outcome_next_gate_map"]["APPROVED_INTERNAL_ONLY"] = None
expect_rejected(use_source_contract=drifted_source_contract)

print("PASS: Client Finder final-offer release execution authorization remains human-only, next-gate-only and fail-closed")
