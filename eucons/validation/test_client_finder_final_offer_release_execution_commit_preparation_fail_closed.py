#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from eucons.leads.client_finder_final_offer_release_execution_commit_preparation import (  # noqa: E402
    build_final_offer_release_execution_commit_preparation,
    load_json,
)

CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_commit_preparation_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_commit_authorization_contract.json"
FALSE_FIELDS = (
    "public_offer_content_included", "final_offer_generated", "offer_approval_granted",
    "final_offer_approval_granted", "final_offer_release_authorization_granted", "release_executed",
    "release_package_generated", "release_package_approved", "pricing_included", "new_legal_claims_included",
    "new_financial_claims_included", "target_state_committed", "persistence_executed",
    "candidate_persistence_allowed", "draft_persistence_allowed", "offer_persistence_allowed",
    "production_offer_generation_allowed", "final_offer_generation_allowed", "offer_engine_invocation_allowed",
    "pricing_decision_allowed", "crm_context_materialization_allowed", "external_contact_enabled",
    "automatic_offer_enabled", "automatic_send_enabled", "crm_write_enabled", "pipeline_write_enabled",
)


def expect_fail(fn, label: str) -> None:
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"expected fail-closed rejection: {label}")


def source_authorization() -> dict:
    value = {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-COMMIT-AUTHORIZATION-001",
        "final_offer_release_execution_commit_authorization_id": "OFFRELEXECCOMMITAUTH-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_AUTHORIZATION_ENVELOPE",
        "source_execution_review_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-REVIEW-001",
        "source_final_offer_release_execution_review_id": "RELEXECREVIEW-001",
        "source_final_offer_release_execution_preparation_id": "RELEXECPREP-001",
        "source_final_offer_release_execution_authorization_id": "RELEXECAUTH-001",
        "source_final_offer_release_package_review_id": "RELPKGREVIEW-001",
        "source_final_offer_release_package_preparation_id": "RELPKGPREP-001",
        "source_final_offer_release_authorization_id": "RELAUTH-001",
        "source_final_offer_release_readiness_id": "RELREADY-001",
        "source_final_offer_candidate_review_id": "CANDREVIEW-001",
        "source_internal_final_offer_candidate_id": "CANDIDATE-001",
        "source_offer_finalization_readiness_id": "FINALREADY-001",
        "source_offer_content_review_id": "CONTENTREVIEW-001",
        "source_internal_offer_draft_id": "DRAFT-001",
        "organization_key": "ORG-001",
        "prospect_id": "PROSPECT-001",
        "selected_opportunity_id": "OPP-001",
        "selected_service_id": "SERVICE-001",
        "commercial_scope_area": "SELECTED_SERVICE_ONLY",
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL-SOURCE-VERIFY-001",
        "source_as_of": "2026-08-28T07:00:00Z",
        "release_execution_commit_authorization_outcome": "RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "release_execution_commit_authorization_state": "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_GATE_REQUIRED",
        "next_gate_authorized": True,
        "authorization_semantics": "NEXT_INTERNAL_COMMIT_PREPARATION_GATE_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "OPERATOR-REF-001",
            "decided_at": "2026-08-28T07:05:00Z",
        },
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "source_bound": True,
        "human_review_required": True,
    }
    for field in FALSE_FIELDS:
        value[field] = False
    return value


def preparation_request(source: dict) -> dict:
    fields = (
        "source_final_offer_release_execution_review_id",
        "source_final_offer_release_execution_preparation_id",
        "source_final_offer_release_execution_authorization_id",
        "source_final_offer_release_package_review_id",
        "source_final_offer_release_package_preparation_id",
        "source_final_offer_release_authorization_id",
        "source_final_offer_release_readiness_id",
        "source_final_offer_candidate_review_id",
        "source_internal_final_offer_candidate_id",
        "source_offer_finalization_readiness_id",
        "source_offer_content_review_id",
        "source_internal_offer_draft_id",
    )
    value = {
        "source_final_offer_release_execution_commit_authorization_id": source["final_offer_release_execution_commit_authorization_id"],
        **{field: source[field] for field in fields},
        "organization_key": source["organization_key"],
        "prospect_id": source["prospect_id"],
        "selected_opportunity_id": source["selected_opportunity_id"],
        "selected_service_id": source["selected_service_id"],
        "commercial_scope_area": source["commercial_scope_area"],
        "official_source_verification_ref": source["official_source_verification_ref"],
        "source_as_of": source["source_as_of"],
        "preparation_mode": "DETERMINISTIC_INTERNAL_COMMIT_INTENT_ONLY",
    }
    return value


def main() -> None:
    contract = load_json(CONTRACT_PATH)
    source_contract = load_json(SOURCE_CONTRACT_PATH)
    source = source_authorization()
    request = preparation_request(source)

    first = build_final_offer_release_execution_commit_preparation(source, request, contract, source_contract)
    second = build_final_offer_release_execution_commit_preparation(copy.deepcopy(source), copy.deepcopy(request), contract, source_contract)
    assert first == second, "commit-preparation output must be deterministic"
    assert first["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_PREPARATION_ENVELOPE"
    assert first["commit_preparation_state"] == "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_INTENT_PREPARED_REVIEW_REQUIRED"
    assert first["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_COMMIT_REVIEW_GATE_REQUIRED"
    assert first["preparation_mode"] == "DETERMINISTIC_INTERNAL_COMMIT_INTENT_ONLY"
    assert first["commit_intent"] == {
        "command_type": "INTERNAL_RELEASE_EXECUTION_COMMIT_INTENT_REVIEW_ENVELOPE_ONLY",
        "external_action": "NO_EXTERNAL_ACTION",
        "release_action": "NOT_EXECUTED",
        "send_action": "NOT_EXECUTED",
        "publication_action": "NOT_EXECUTED",
        "persistence_action": "NOT_EXECUTED",
    }
    assert first["commit_intent_generated"] is True
    assert first["human_review_required"] is True
    assert first["source_bound"] is True
    assert first["eligibility_state"] == "NOT_ASSESSED"
    assert first["maximum_next_state"] == "RESEARCH_READY"
    for field in FALSE_FIELDS:
        assert first[field] is False, f"boundary opened: {field}"

    bad = copy.deepcopy(source)
    bad["decision_receipt"]["decision_source"] = "SYSTEM"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(bad, request, contract, source_contract), "non-human source authorization")

    bad = copy.deepcopy(source)
    bad["release_execution_commit_authorization_state"] = "FINAL_OFFER_RELEASE_EXECUTION_COMMIT_NOT_AUTHORIZED"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(bad, request, contract, source_contract), "source authorization state drift")

    bad = copy.deepcopy(source)
    bad["next_gate_authorized"] = False
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(bad, request, contract, source_contract), "source next gate not authorized")

    bad = copy.deepcopy(source)
    bad["official_source_reverified"] = False
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(bad, request, contract, source_contract), "official source not reverified")

    bad = copy.deepcopy(source)
    bad["release_executed"] = True
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(bad, request, contract, source_contract), "source already executed")

    bad = copy.deepcopy(request)
    bad["source_final_offer_release_execution_commit_authorization_id"] = "OTHER-AUTH"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "authorization id mismatch")

    bad = copy.deepcopy(request)
    bad["selected_opportunity_id"] = "OTHER-OPP"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "identity mismatch")

    bad = copy.deepcopy(request)
    bad["official_source_verification_ref"] = "OTHER-SOURCE"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "verification reference mismatch")

    bad = copy.deepcopy(request)
    bad["source_as_of"] = "2026-08-28T10:00:00+03:00"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "non UTC-Z source_as_of")

    bad = copy.deepcopy(request)
    bad["preparation_mode"] = "EXECUTE_NOW"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "preparation mode escaped allowlist")

    bad = copy.deepcopy(request)
    bad["recipient"] = "external-target"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "recipient leakage")

    bad = copy.deepcopy(request)
    bad["price"] = 100
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, bad, contract, source_contract), "pricing leakage")

    bad_contract = copy.deepcopy(contract)
    bad_contract["preparation"]["commit_intent"]["external_action"] = "EXTERNAL_ACTION"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, request, bad_contract, source_contract), "contract command drift")

    bad_source_contract = copy.deepcopy(source_contract)
    bad_source_contract["authorization"]["authorization_scope"] = "FULL_RELEASE"
    expect_fail(lambda: build_final_offer_release_execution_commit_preparation(source, request, contract, bad_source_contract), "source contract authorization drift")

    print(json.dumps({
        "status": "PASS",
        "contract_id": first["contract_id"],
        "record_state": first["record_state"],
        "commit_preparation_state": first["commit_preparation_state"],
        "next_gate_hint": first["next_gate_hint"],
        "external_action": first["commit_intent"]["external_action"],
        "release_executed": first["release_executed"],
        "automatic_send_enabled": first["automatic_send_enabled"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
