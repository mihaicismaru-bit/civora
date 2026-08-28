#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_gate.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_gate_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_execution_authorization_contract.json"

spec = importlib.util.spec_from_file_location("release_execution_gate", ENGINE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)

contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
source_contract = json.loads(SOURCE_CONTRACT_PATH.read_text(encoding="utf-8"))


def valid_source_authorization():
    result = {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-EXECUTION-AUTHORIZATION-001",
        "final_offer_release_execution_authorization_id": "OFFRELEXECAUTH-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_AUTHORIZATION_ENVELOPE",
        "source_release_package_review_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-PACKAGE-REVIEW-001",
        "source_final_offer_release_package_review_id": "OFFRELPKGREVIEW-0123456789abcdef01234567",
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
        "release_execution_authorization_outcome": "RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY",
        "release_execution_authorization_state": "FINAL_OFFER_RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_GATE_REQUIRED",
        "next_gate_authorized": True,
        "authorization_semantics": "NEXT_GATE_ENTRY_ONLY_NOT_RELEASE_AUTHORIZATION_OR_EXECUTION_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {
            "decision_source": "HUMAN",
            "reviewer_ref": "execution-reviewer-ref-001",
            "decided_at": "2026-08-28T03:15:00Z",
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


def expect_rejected(source=None, use_contract=None, use_source_contract=None):
    try:
        module.build_final_offer_release_execution_gate(
            source if source is not None else valid_source_authorization(),
            use_contract if use_contract is not None else contract,
            use_source_contract if use_source_contract is not None else source_contract,
        )
    except ValueError:
        return
    raise AssertionError("unsafe release-execution gate input was accepted")


source = valid_source_authorization()
result = module.build_final_offer_release_execution_gate(source, contract, source_contract)

assert result["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_EXECUTION_PREPARATION_ENVELOPE"
assert result["execution_preparation_mode"] == "DETERMINISTIC_INTERNAL_RELEASE_COMMAND_ONLY"
assert result["execution_preparation_state"] == "INTERNAL_FINAL_OFFER_RELEASE_EXECUTION_ENVELOPE_PREPARED_REVIEW_REQUIRED"
assert result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_EXECUTION_REVIEW_GATE_REQUIRED"
assert result["execution_command"] == {
    "command_type": "INTERNAL_RELEASE_EXECUTION_REVIEW_ENVELOPE_ONLY",
    "external_action": "NO_EXTERNAL_ACTION",
    "release_action": "NOT_EXECUTED",
    "send_action": "NOT_EXECUTED",
    "publication_action": "NOT_EXECUTED",
}
assert result["internal_execution_envelope_prepared"] is True
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
assert result == module.build_final_offer_release_execution_gate(valid_source_authorization(), contract, source_contract)
assert "recipient" not in result
assert "channel" not in result
assert "price" not in result

for field, value in (
    ("release_execution_authorization_outcome", "RELEASE_EXECUTION_NOT_AUTHORIZED"),
    ("release_execution_authorization_state", "FINAL_OFFER_RELEASE_EXECUTION_NOT_AUTHORIZED"),
    ("authorization_scope", "EXECUTE_RELEASE"),
    ("next_gate_hint", None),
    ("next_gate_authorized", False),
    ("official_source_reverified", False),
    ("source_bound", False),
    ("release_package_generated", True),
    ("release_package_approved", True),
    ("final_offer_release_authorization_granted", True),
    ("release_executed", True),
    ("automatic_send_enabled", True),
):
    bad = valid_source_authorization()
    bad[field] = value
    expect_rejected(source=bad)

bad = valid_source_authorization()
bad["source_as_of"] = "2026-08-28T05:30:00+03:00"
expect_rejected(source=bad)

bad = valid_source_authorization()
bad["decision_receipt"]["decision_source"] = "AI"
expect_rejected(source=bad)

bad = valid_source_authorization()
bad["decision_receipt"]["decided_at"] = "2026-08-28T06:15:00+03:00"
expect_rejected(source=bad)

bad = valid_source_authorization()
bad["decision_receipt"]["reviewer_ref"] = "reviewer@example.com"
expect_rejected(source=bad)

for field, value in (
    ("commercial_scope_area", "EXPANDED_SCOPE"),
    ("recipient", "somewhere"),
    ("channel", "email"),
    ("price", 1000),
    ("message_body", "send this"),
):
    bad = valid_source_authorization()
    bad[field] = value
    expect_rejected(source=bad)

bad = valid_source_authorization()
bad["organization_key"] = "org-002"
result_changed_identity = module.build_final_offer_release_execution_gate(bad, contract, source_contract)
assert result_changed_identity["final_offer_release_execution_preparation_id"] != result["final_offer_release_execution_preparation_id"]
assert result_changed_identity["release_executed"] is False

bad_contract = copy.deepcopy(contract)
bad_contract["execution_preparation"]["external_action"] = "SEND"
expect_rejected(use_contract=bad_contract)

bad_contract = copy.deepcopy(contract)
bad_contract["output"]["release_executed"] = True
expect_rejected(use_contract=bad_contract)

bad_source_contract = copy.deepcopy(source_contract)
bad_source_contract["authorization"]["outcome_next_gate_map"]["RELEASE_EXECUTION_GATE_AUTHORIZED_INTERNAL_ONLY"] = None
expect_rejected(use_source_contract=bad_source_contract)

bad_source_contract = copy.deepcopy(source_contract)
bad_source_contract["output"]["automatic_send_enabled"] = True
expect_rejected(use_source_contract=bad_source_contract)

print("PASS: Client Finder final-offer release execution gate prepares only a deterministic internal review envelope and remains fail-closed")
