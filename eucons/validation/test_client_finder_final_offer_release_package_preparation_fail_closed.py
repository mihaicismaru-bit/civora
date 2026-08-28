#!/usr/bin/env python3
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_package_preparation.py"
CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_package_preparation_contract.json"
SOURCE_CONTRACT_PATH = ROOT / "eucons" / "leads" / "client_finder_final_offer_release_authorization_contract.json"

spec = importlib.util.spec_from_file_location("eucons_client_finder_final_offer_release_package_preparation", ENGINE_PATH)
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
        "contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-AUTHORIZATION-001",
        "final_offer_release_authorization_id": "OFFRELAUTH-0123456789abcdef01234567",
        "record_state": "CLIENT_FINDER_FINAL_OFFER_RELEASE_AUTHORIZATION_ENVELOPE",
        "source_release_readiness_contract_id": "EUCONS-R07-CLIENT-FINDER-FINAL-OFFER-RELEASE-READINESS-001",
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
        "official_source_reverified": True,
        "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
        "source_as_of": "2026-08-27T18:00:00Z",
        "release_authorization_outcome": "RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "release_authorization_state": "FINAL_OFFER_RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY",
        "authorization_scope": "NEXT_GATE_ONLY",
        "next_gate_hint": "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_GATE_REQUIRED",
        "next_gate_authorized": True,
        "release_authorization_semantics": "INTERNAL_NEXT_GATE_AUTHORIZATION_ONLY_NOT_FINAL_RELEASE_SEND_PUBLICATION_PRICING_PERSISTENCE_CRM_OR_OUTREACH",
        "decision_receipt": {"decision_source": "HUMAN", "reviewer_ref": "REVIEWER-OPAQUE-009", "decided_at": "2026-08-28T00:45:00Z"},
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "human_review_required": True,
        "public_offer_content_included": False,
        "final_offer_generated": False,
        "offer_approval_granted": False,
        "final_offer_approval_granted": False,
        "final_offer_release_authorization_granted": False,
        "release_executed": False,
        "release_package_generated": False,
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
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def request_fixture():
    return {
        "source_final_offer_release_authorization_id": "OFFRELAUTH-0123456789abcdef01234567",
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
        "preparation_mode": "DETERMINISTIC_INTERNAL_METADATA_CHECKLIST_ONLY",
    }


def build(source=None, request=None, contract=None, source_contract=None):
    return engine.build_final_offer_release_package_preparation(
        source or source_fixture(), request or request_fixture(), contract or CONTRACT, source_contract or SOURCE_CONTRACT
    )


def must_fail(label, fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError(f"{label} failed open")


result = build()
assert result["record_state"] == "CLIENT_FINDER_FINAL_OFFER_RELEASE_PACKAGE_PREPARATION_ENVELOPE"
assert result["package_state"] == "INTERNAL_FINAL_OFFER_RELEASE_PACKAGE_PREPARED_REVIEW_REQUIRED"
assert result["content_scope"] == "INTERNAL_RELEASE_METADATA_AND_CHECKLIST_ONLY"
assert result["next_gate_hint"] == "SEPARATE_FINAL_OFFER_RELEASE_PACKAGE_REVIEW_GATE_REQUIRED"
assert result["preparation_mode"] == "DETERMINISTIC_INTERNAL_METADATA_CHECKLIST_ONLY"
assert result["internal_release_package_prepared"] is True
assert result["release_package_metadata_included"] is True
assert result["release_package_review_required"] is True
assert result["source_bound"] is True
assert result["human_review_required"] is True
assert result["eligibility_state"] == "NOT_ASSESSED"
assert result["maximum_next_state"] == "RESEARCH_READY"
assert result["preparation_checklist"] == [
    {"check": check, "status": "PASS"} for check in CONTRACT["preparation"]["required_checklist"]
]
assert result["package_metadata"] == {
    "source_authorization_id": "OFFRELAUTH-0123456789abcdef01234567",
    "organization_key": "ORG-DEMO-001",
    "prospect_id": "PROSPECT-DEMO-001",
    "opportunity_id": "OPP-DEMO-001",
    "service_id": "SERVICE-DEMO-001",
    "commercial_scope_area": "SELECTED_SERVICE_ONLY",
    "official_source_verification_ref": "OFFICIAL:2026-08-27:OPP-DEMO-001:NOTICE-1",
    "source_as_of": "2026-08-27T18:00:00Z",
}
for field in engine.FALSE_BOUNDARY_FIELDS + engine.DISABLED_ACTION_FLAGS:
    assert result[field] is False
assert build()["final_offer_release_package_preparation_id"] == result["final_offer_release_package_preparation_id"]
assert build()["preparation_checklist"] == result["preparation_checklist"]

bad = source_fixture(); bad["release_authorization_outcome"] = "RELEASE_PREPARATION_NOT_AUTHORIZED"
must_fail("non-authorized source outcome", lambda: build(source=bad))
bad = source_fixture(); bad["release_authorization_state"] = "FINAL_OFFER_RELEASE_PREPARATION_NOT_AUTHORIZED"
must_fail("non-authorized source state", lambda: build(source=bad))
bad = source_fixture(); bad["next_gate_hint"] = "SEND_FINAL_OFFER"
must_fail("source next gate drift", lambda: build(source=bad))
bad = source_fixture(); bad["next_gate_authorized"] = False
must_fail("source preparation gate authorization missing", lambda: build(source=bad))
bad = source_fixture(); bad["official_source_reverified"] = False
must_fail("official source not reverified", lambda: build(source=bad))
bad = source_fixture(); bad["decision_receipt"]["decision_source"] = "MODEL"
must_fail("source decision receipt not human", lambda: build(source=bad))
bad = source_fixture(); bad["source_as_of"] = "2026-08-28T03:00:00+03:00"
must_fail("source timestamp not UTC-Z", lambda: build(source=bad))
bad = source_fixture(); bad["release_package_generated"] = True
must_fail("source release package generation failed open", lambda: build(source=bad))
bad = source_fixture(); bad["release_executed"] = True
must_fail("source release execution failed open", lambda: build(source=bad))
bad = source_fixture(); bad["offer_engine_invocation_allowed"] = True
must_fail("source Offer Engine failed open", lambda: build(source=bad))
bad = source_fixture(); bad["reviewer_name"] = "Forbidden Person"
must_fail("source person-level field", lambda: build(source=bad))
bad = source_fixture(); bad["budget"] = 100000
must_fail("source material value injected", lambda: build(source=bad))

bad_request = request_fixture(); bad_request["preparation_mode"] = "GENERATE_SENDABLE_PACKAGE"
must_fail("preparation mode escaped allowlist", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["source_final_offer_release_authorization_id"] = "OFFRELAUTH-DRIFT"
must_fail("authorization lineage drift", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["source_internal_final_offer_candidate_id"] = "OFFCAND-DRIFT"
must_fail("candidate lineage drift", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["selected_service_id"] = "SERVICE-DRIFT"
must_fail("service identity drift", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["official_source_verification_ref"] = "OFFICIAL:DRIFT"
must_fail("official source verification drift", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["source_as_of"] = "2026-08-27T19:00:00Z"
must_fail("source_as_of lineage drift", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["recipient"] = "someone@example.com"
must_fail("recipient injected", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["offer_body"] = "Forbidden offer text"
must_fail("offer content injected", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["price"] = 100
must_fail("pricing injected", lambda: build(request=bad_request))
bad_request = request_fixture(); bad_request["personal_email"] = "person@example.com"
must_fail("person-level request field", lambda: build(request=bad_request))

contract = copy.deepcopy(CONTRACT); contract["output"]["release_package_generated"] = True
must_fail("contract releasable package boundary failed open", lambda: build(contract=contract))
contract = copy.deepcopy(CONTRACT); contract["preparation"]["content_scope"] = "FULL_OFFER_CONTENT"
must_fail("contract content scope failed open", lambda: build(contract=contract))
contract = copy.deepcopy(CONTRACT); contract["preparation"]["required_checklist"] = ["SOURCE_AUTHORIZATION_MATCHED"]
must_fail("contract checklist weakened", lambda: build(contract=contract))
source_contract = copy.deepcopy(SOURCE_CONTRACT); source_contract["output"]["release_executed"] = True
must_fail("source contract release execution boundary failed open", lambda: build(source_contract=source_contract))
source_contract = copy.deepcopy(SOURCE_CONTRACT); source_contract["authorization"]["outcome_next_gate_map"]["RELEASE_PREPARATION_AUTHORIZED_INTERNAL_ONLY"] = "SEND_FINAL_OFFER"
must_fail("source contract next-gate drift", lambda: build(source_contract=source_contract))

print("EUCONS Client Finder final-offer release-package preparation fail-closed: PASS")
