#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT = json.loads((EUCONS / "leads" / "client_finder_evaluation_transition_contract.json").read_text(encoding="utf-8"))
TARGET_CONTRACT = json.loads((EUCONS / "leads" / "research_evaluation_handoff_contract.json").read_text(encoding="utf-8"))


def load_transition():
    path = EUCONS / "leads" / "client_finder_evaluation_transition.py"
    spec = importlib.util.spec_from_file_location("eucons_client_finder_evaluation_transition_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def valid_triage():
    return {
        "schema_version": 1,
        "view_id": "EUCONS-R07-CLIENT-FINDER-OPERATOR-TRIAGE-SYNTHESIS-001",
        "view_state": "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW",
        "semantics": "OPERATOR_REVERIFICATION_AND_MATCH_REVIEW_ONLY",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "summary": {
            "queue_rows": 1, "matched_results": 1, "nonmatched_research_rows_not_in_queue": 0,
            "source_as_of_ties_present": False, "threshold_applied": False, "source_age_classification": "NOT_CLASSIFIED",
        },
        "queue": [{
            "queue_rank": 1,
            "organization_key": "ORG-SYNTH-001",
            "prospect_id": "PROS-SYNTH-001",
            "priority_state": "HIGH_RESEARCH_PRIORITY",
            "priority_score": 80,
            "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
            "score_breakdown": None,
            "recommended_service_id": "funding_strategy_and_eligibility",
            "selected_service_id": "funding_strategy_and_eligibility",
            "selected_service_support": {"service_id": "funding_strategy_and_eligibility", "supporting_signal_ids": ["SIG-1"], "support_count": 1, "support_ratio": 1.0},
            "selected_opportunity": {
                "opportunity_id": "OPP-SYNTH-001", "title": "Synthetic opportunity", "programme": "Synthetic",
                "relevance_score": 0.9, "relevance_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
                "confidence": "HIGH", "verified_fact_classes": ["IDENTITY"], "matching_explanations": ["Synthetic test"],
            },
            "source_as_of": "2026-08-27T12:00:00Z",
            "relative_source_age_cue": "ONLY_MATCHED_SOURCE_SNAPSHOT",
            "source_projection_sha256_present": True,
            "verification_reference_count": 1,
            "provenance_explanation_reasons": ["OFFICIAL_SOURCE_REVERIFICATION_REQUIRED_BEFORE_MATERIAL_CLAIM"],
            "match_reason_codes": ["MATCHED"],
            "verification_questions": ["Confirm official source."],
            "source_ref_count": 1,
            "signal_ids": ["SIG-1"],
            "operator_next_step": "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH",
            "official_source_reverification_required": True,
            "material_claims_verified": False,
            "source_age_classification": "NOT_CLASSIFIED",
            "threshold_applied": False,
            "eligibility_state": "NOT_ASSESSED",
            "maximum_next_state": "RESEARCH_READY",
            "human_review_required": True,
            "external_contact_enabled": False,
            "automatic_offer_enabled": False,
            "automatic_send_enabled": False,
            "crm_write_enabled": False,
            "pipeline_write_enabled": False,
            "evidence_label": "RESEARCH_ONLY",
        }],
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def decision(source_status, decision_value, verification_ref):
    return {
        "queue_rank": 1,
        "organization_key": "ORG-SYNTH-001",
        "prospect_id": "PROS-SYNTH-001",
        "selected_opportunity_id": "OPP-SYNTH-001",
        "selected_service_id": "funding_strategy_and_eligibility",
        "source_status": source_status,
        "decision": decision_value,
        "decision_source": "HUMAN",
        "verification_ref": verification_ref,
        "reviewer_ref": "HUMAN-REVIEWER-REF-001",
        "decided_at": "2026-08-27T15:30:00Z",
    }


def must_fail(module, triage, human_decision, fragment, contract=None, target_contract=None):
    try:
        module.build_transition_envelope(
            triage, human_decision, contract or CONTRACT, target_contract or TARGET_CONTRACT
        )
    except ValueError as exc:
        assert fragment.lower() in str(exc).lower(), (fragment, str(exc))
        return
    raise AssertionError(f"expected failure containing {fragment!r}")


def main():
    module = load_transition()
    triage = valid_triage()

    waiting = module.build_transition_envelope(
        triage,
        decision("SOURCE_NOT_REVERIFIED", "REQUEST_OFFICIAL_SOURCE_REVERIFICATION", None),
        CONTRACT,
        TARGET_CONTRACT,
    )
    assert waiting["transition_status"] == "WAITING_SOURCE"
    assert waiting["proposed_evaluation"] is None
    assert waiting["target_state_committed"] is False
    assert waiting["persistence_executed"] is False

    blocked = module.build_transition_envelope(
        triage,
        decision("OFFICIAL_SOURCE_CONFLICT", "BLOCK_SOURCE_CONFLICT", "SRCREF-CONFLICT-001"),
        CONTRACT,
        TARGET_CONTRACT,
    )
    assert blocked["transition_status"] == "BLOCKED"
    assert blocked["proposed_evaluation"] is None
    assert blocked["target_state_committed"] is False

    approved_decision = decision(
        "OFFICIAL_SOURCE_REVERIFIED",
        "APPROVE_RESEARCH_EVALUATION_HANDOFF",
        "SRCREF-OFFICIAL-001",
    )
    ready = module.build_transition_envelope(triage, approved_decision, CONTRACT, TARGET_CONTRACT)
    assert ready["transition_status"] == "READY_FOR_RESEARCH_EVALUATION_REVIEW"
    assert ready["target_state_committed"] is False
    assert ready["persistence_executed"] is False
    evaluation = ready["proposed_evaluation"]
    assert evaluation["contract_id"] == "EUCONS-E11-R07-EVALUATION-HANDOFF-001"
    assert evaluation["record_state"] == "RESEARCH_EVALUATION_PENDING_HUMAN_REVIEW"
    assert evaluation["source_provenance"] == {
        "source_product": "OFFICIAL_SOURCE_REVERIFICATION",
        "source_opportunity_id": "OPP-SYNTH-001",
        "verification_ref": "SRCREF-OFFICIAL-001",
    }
    assert evaluation["eligibility_state"] == "NOT_ASSESSED"
    assert evaluation["maximum_next_state"] == "RESEARCH_READY"
    assert evaluation["human_review_required"] is True
    assert evaluation["external_contact_enabled"] is False
    assert evaluation["automatic_offer_enabled"] is False
    assert evaluation["crm_write_enabled"] is False
    assert module.build_transition_envelope(triage, approved_decision, CONTRACT, TARGET_CONTRACT)["envelope_id"] == ready["envelope_id"]

    machine = deepcopy(approved_decision)
    machine["decision_source"] = "AUTOMATION"
    must_fail(module, triage, machine, "HUMAN")

    mismatch = deepcopy(approved_decision)
    mismatch["selected_opportunity_id"] = "OPP-OTHER"
    must_fail(module, triage, mismatch, "exactly one")

    missing_ref = deepcopy(approved_decision)
    missing_ref["verification_ref"] = None
    must_fail(module, triage, missing_ref, "verification_ref")

    conflict_approved = decision("OFFICIAL_SOURCE_CONFLICT", "APPROVE_RESEARCH_EVALUATION_HANDOFF", "SRCREF-CONFLICT-001")
    must_fail(module, triage, conflict_approved, "status/decision")

    missing_source_approved = decision("SOURCE_NOT_REVERIFIED", "APPROVE_RESEARCH_EVALUATION_HANDOFF", None)
    must_fail(module, triage, missing_source_approved, "status/decision")

    naive_time = deepcopy(approved_decision)
    naive_time["decided_at"] = "2026-08-27T15:30:00"
    must_fail(module, triage, naive_time, "UTC-Z")

    extra_decision_field = deepcopy(approved_decision)
    extra_decision_field["note"] = "unsafe shape drift"
    must_fail(module, triage, extra_decision_field, "fields drift")

    person_level = deepcopy(approved_decision)
    person_level["reviewer_email"] = "synthetic@example.invalid"
    must_fail(module, triage, person_level, "person-level")

    upstream_contact = deepcopy(triage)
    upstream_contact["queue"][0]["external_contact_enabled"] = True
    must_fail(module, upstream_contact, approved_decision, "external_contact_enabled")

    upstream_eligibility = deepcopy(triage)
    upstream_eligibility["queue"][0]["eligibility_state"] = "ELIGIBLE"
    must_fail(module, upstream_eligibility, approved_decision, "eligibility")

    upstream_material_claim = deepcopy(triage)
    upstream_material_claim["queue"][0]["material_claims_verified"] = True
    must_fail(module, upstream_material_claim, approved_decision, "material claims")

    upstream_threshold = deepcopy(triage)
    upstream_threshold["queue"][0]["threshold_applied"] = True
    must_fail(module, upstream_threshold, approved_decision, "freshness threshold")

    raw_provenance = deepcopy(triage)
    raw_provenance["queue"][0]["source_provenance"] = {"url": "https://example.invalid"}
    must_fail(module, raw_provenance, approved_decision, "forbidden raw/inference")

    failed_open_contract = deepcopy(CONTRACT)
    failed_open_contract["output"]["crm_write_enabled"] = True
    must_fail(module, triage, approved_decision, "crm_write_enabled", failed_open_contract)

    failed_open_target = deepcopy(TARGET_CONTRACT)
    failed_open_target["output"]["external_contact_enabled"] = True
    must_fail(module, triage, approved_decision, "target external_contact_enabled", target_contract=failed_open_target)

    print("PASS: Client Finder evaluation transition waits on missing source, blocks conflicts and requires human verified-source approval")


if __name__ == "__main__":
    main()
