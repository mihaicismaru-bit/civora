#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "prospects" / "client_finder_operator_triage.py"
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_operator_triage_contract.json"

spec = importlib.util.spec_from_file_location("operator_triage", ENGINE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def safe_flags():
    return {
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def provenance_row(rank: int, org: str, prospect: str, opportunity: str, service: str, source_as_of: str, cue: str):
    return {
        "queue_rank": rank,
        "prospect_id": prospect,
        "organization_key": org,
        "opportunity_id": opportunity,
        "selected_service_id": service,
        "source_as_of": source_as_of,
        "relative_source_age_cue": cue,
        "source_projection_sha256_present": rank == 1,
        "verification_evidence_count": 2,
        "explanation_reasons": [
            "RELATIVE_SOURCE_AS_OF_ORDER_ONLY",
            "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED_BEFORE_MATERIAL_CLAIM",
            "VERIFICATION_REFERENCE_COUNT_PRESENT",
            "SOURCE_PROJECTION_HASH_AVAILABLE" if rank == 1 else "SOURCE_PROJECTION_HASH_NOT_AVAILABLE",
        ],
        "operator_next_step": "REVERIFY_OFFICIAL_SOURCE_BEFORE_MATERIAL_CLAIM",
        "threshold_applied": False,
        "source_age_classification": "NOT_CLASSIFIED",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        **safe_flags(),
    }


def provenance_view():
    rows = [
        provenance_row(
            1,
            "org-a",
            "prospect-a",
            "opp-a",
            "application_design_and_submission",
            "2026-08-25T09:00:00Z",
            "EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
        ),
        provenance_row(
            2,
            "org-b",
            "prospect-b",
            "opp-b",
            "funding_strategy_and_eligibility",
            "2026-08-27T08:00:00Z",
            "LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
        ),
    ]
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-PROVENANCE-TRIAGE-EXPLAINABILITY-001",
        "source_contract_id": "EUCONS-R07-CLIENT-FINDER-PROVENANCE-FRESHNESS-001",
        "view_state": "CLIENT_FINDER_PROVENANCE_TRIAGE_EXPLAINABILITY_VIEW",
        "semantics": "REVERIFICATION_QUEUE_EXPLAINABILITY_ONLY",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "summary": {
            "review_queue_rows": 2,
            "distinct_source_as_of_values": 2,
            "source_as_of_ties_present": False,
            "oldest_source_as_of": "2026-08-25T09:00:00Z",
            "newest_source_as_of": "2026-08-27T08:00:00Z",
            "threshold_applied": False,
            "source_age_classification": "NOT_CLASSIFIED",
        },
        "rows": rows,
        **safe_flags(),
    }


def score_breakdown(score: int):
    components = {
        "source_quality": 25,
        "freshness": 15,
        "signal_strength": 20,
        "service_coherence": 20,
        "actionability": 10,
    }
    gross = sum(components.values())
    penalties = {
        "unknown_assertions": gross - score,
        "low_confidence_inferences": 0,
        "total": gross - score,
    }
    return {
        "score": score,
        "gross_score": gross,
        "components": components,
        "penalties": penalties,
        "semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
    }


def matched_result(org: str, prospect: str, opportunity: str, service: str, score: int):
    return {
        "organization_key": org,
        "prospect_id": prospect,
        "state": "MATCHED_RESEARCH_CANDIDATE",
        "priority_state": "PRIORITY_HIGH_RESEARCH" if score >= 80 else "PRIORITY_MEDIUM_RESEARCH",
        "priority_score": score,
        "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
        "score_breakdown": score_breakdown(score),
        "recommended_service_id": service,
        "selected_service_id": service,
        "selected_service_support": {
            "service_id": service,
            "supporting_signal_ids": [f"sig-{org}"],
            "support_count": 1,
            "support_ratio": 1.0,
        },
        "selected_opportunity": {
            "opportunity_id": opportunity,
            "title": f"Synthetic opportunity {opportunity}",
            "programme": "Synthetic programme",
            "relevance_score": 75,
            "relevance_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
            "confidence": "HIGH",
            "verified_fact_classes": ["programme", "audience"],
            "matching_explanations": ["Verified organization terms overlap."],
        },
        "reason_codes": [
            "OFFICIAL_SOURCE_REVERIFICATION_REQUIRED",
            "PROSPECT_RESEARCH_PRIORITY_SCORED",
            "SIGNAL_SUPPORTED_SERVICE_OVERLAP",
            "VERIFIED_OPPORTUNITY_RELEVANCE",
            "VERIFIED_OPPORTUNITY_SERVICE_OVERLAP",
        ],
        "verification_questions": ["Is the official opportunity source still current?"],
        "source_ref_count": 2,
        "signal_ids": [f"sig-{org}"],
        "operator_next_step": "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH",
        "official_source_reverification_required": True,
        "material_claims_verified": False,
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        **safe_flags(),
        "evidence_label": "NON_EVIDENCE",
    }


def nonmatched_result():
    return {
        "organization_key": "org-c",
        "prospect_id": "prospect-c",
        "state": "REQUIRES_VERIFICATION",
        "priority_state": "PRIORITY_MEDIUM_RESEARCH",
        "priority_score": 55,
        "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
        "score_breakdown": score_breakdown(55),
        "recommended_service_id": "funding_strategy_and_eligibility",
        "selected_service_id": None,
        "selected_service_support": None,
        "selected_opportunity": None,
        "reason_codes": ["FACTS_OR_SERVICE_ALIGNMENT_REQUIRE_VERIFICATION"],
        "verification_questions": ["Verify organization evidence."],
        "source_ref_count": 1,
        "signal_ids": ["sig-org-c"],
        "operator_next_step": "VERIFY_ORGANIZATION_FACTS",
        "official_source_reverification_required": False,
        "material_claims_verified": False,
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        **safe_flags(),
        "evidence_label": "NON_EVIDENCE",
    }


def match_view():
    rows = [
        matched_result("org-b", "prospect-b", "opp-b", "funding_strategy_and_eligibility", 88),
        nonmatched_result(),
        matched_result("org-a", "prospect-a", "opp-a", "application_design_and_submission", 62),
    ]
    return {
        "schema_version": 1,
        "view_id": "EUCONS-R07-CLIENT-FINDER-MATCH-EXPLAINABILITY-001",
        "view_state": "CLIENT_FINDER_MATCH_EXPLAINABILITY_VIEW",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "priority_score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "summary": {
            "evaluated": 3,
            "matched": 2,
            "requires_verification": 1,
            "held": 0,
            "suppressed": 0,
        },
        "results": rows,
        **safe_flags(),
    }


def expect_error(fn, contains: str):
    try:
        fn()
    except (ValueError, AssertionError) as exc:
        assert contains in str(exc), str(exc)
    else:
        raise AssertionError(f"expected failure containing: {contains}")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_happy_path_uses_provenance_order_not_score_order():
    result = mod.build_operator_triage_view(provenance_view(), match_view(), contract())
    assert result["view_state"] == "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW"
    assert result["semantics"] == "OPERATOR_REVERIFICATION_AND_MATCH_REVIEW_ONLY"
    assert result["summary"] == {
        "queue_rows": 2,
        "matched_results": 2,
        "nonmatched_research_rows_not_in_queue": 1,
        "source_as_of_ties_present": False,
        "threshold_applied": False,
        "source_age_classification": "NOT_CLASSIFIED",
    }
    assert [row["organization_key"] for row in result["queue"]] == ["org-a", "org-b"]
    assert [row["priority_score"] for row in result["queue"]] == [62, 88]
    assert result["queue"][0]["relative_source_age_cue"] == "EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET"
    assert result["queue"][0]["operator_next_step"] == "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH"
    assert result["queue"][0]["official_source_reverification_required"] is True
    assert result["queue"][0]["material_claims_verified"] is False
    assert result["queue"][0]["source_age_classification"] == "NOT_CLASSIFIED"
    assert result["queue"][0]["threshold_applied"] is False
    assert canonical(result) == canonical(mod.build_operator_triage_view(provenance_view(), match_view(), contract()))
    serialized = canonical(result)
    for forbidden in (
        "source_provenance",
        "verification_evidence",
        "source_projection_sha256\"",
        "source_supported_deadline",
        "eligibility_probability",
        "award_probability",
        "conversion_probability",
        "buying_intent",
        "personal_email",
    ):
        assert forbidden not in serialized
    assert result["external_contact_enabled"] is False
    assert result["automatic_offer_enabled"] is False
    assert result["automatic_send_enabled"] is False
    assert result["crm_write_enabled"] is False
    assert result["pipeline_write_enabled"] is False


def test_join_identity_drift_fails_closed():
    provenance = provenance_view()
    provenance["rows"][0]["opportunity_id"] = "opp-wrong"
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "sets differ")


def test_matched_set_omission_fails_closed():
    provenance = provenance_view()
    provenance["rows"] = provenance["rows"][:1]
    provenance["summary"].update(
        {
            "review_queue_rows": 1,
            "distinct_source_as_of_values": 1,
            "oldest_source_as_of": "2026-08-25T09:00:00Z",
            "newest_source_as_of": "2026-08-25T09:00:00Z",
        }
    )
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "sets differ")


def test_source_age_or_threshold_classification_fails_closed():
    provenance = provenance_view()
    provenance["rows"][0]["source_age_classification"] = "OLD"
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "classified source age")
    provenance = provenance_view()
    provenance["summary"]["threshold_applied"] = True
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "applied a freshness threshold")


def test_external_action_and_forbidden_fields_fail_closed():
    match = match_view()
    match["results"][0]["crm_write_enabled"] = True
    expect_error(lambda: mod.build_operator_triage_view(provenance_view(), match, contract()), "crm_write_enabled failed open")
    match = match_view()
    match["results"][0]["award_probability"] = 0.8
    expect_error(lambda: mod.build_operator_triage_view(provenance_view(), match, contract()), "forbidden field present")
    provenance = provenance_view()
    provenance["rows"][0]["personal_email"] = "person@example.invalid"
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "forbidden field present")


def test_selected_identity_and_score_breakdown_drift_fail_closed():
    match = match_view()
    match["results"][0]["selected_service_support"]["service_id"] = "wrong-service"
    expect_error(lambda: mod.build_operator_triage_view(provenance_view(), match, contract()), "support identity drift")
    match = match_view()
    match["results"][0]["score_breakdown"]["score"] = 87
    expect_error(lambda: mod.build_operator_triage_view(provenance_view(), match, contract()), "priority score and breakdown drift")


def test_unexpected_source_shape_fails_closed():
    provenance = provenance_view()
    provenance["debug_payload"] = {"unexpected": True}
    expect_error(lambda: mod.build_operator_triage_view(provenance, match_view(), contract()), "top-level allowlist drift")


def test_atomic_output():
    result = mod.build_operator_triage_view(provenance_view(), match_view(), contract())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "operator-triage.json"
        mod.write_atomic(path, result)
        assert json.loads(path.read_text(encoding="utf-8")) == result
        assert not path.with_suffix(".json.tmp").exists()


def main():
    test_happy_path_uses_provenance_order_not_score_order()
    test_join_identity_drift_fails_closed()
    test_matched_set_omission_fails_closed()
    test_source_age_or_threshold_classification_fails_closed()
    test_external_action_and_forbidden_fields_fail_closed()
    test_selected_identity_and_score_breakdown_drift_fail_closed()
    test_unexpected_source_shape_fails_closed()
    test_atomic_output()
    print("client finder operator triage synthesis fail-closed tests: PASS")


if __name__ == "__main__":
    main()
