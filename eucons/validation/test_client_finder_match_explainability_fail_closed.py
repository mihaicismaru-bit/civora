#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "prospects" / "client_finder_match_explainability.py"
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_match_explainability_contract.json"

spec = importlib.util.spec_from_file_location("match_explainability", ENGINE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def score_view():
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_R06_PROSPECT_PRIORITY_SCORING",
        "reference_time": "2026-08-27T12:00:00Z",
        "score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "external_contact_enabled": False,
        "results": [
            {
                "organization_key": "org-a",
                "prospect_id": "prospect-a",
                "priority_state": "PRIORITY_HIGH_RESEARCH",
                "score": 82,
                "score_semantics": "COMMERCIAL_RESEARCH_PRIORITY_NOT_ELIGIBILITY_OR_CONVERSION_PROBABILITY",
                "eligibility_state": "NOT_ASSESSED",
                "maximum_next_state": "RESEARCH_READY",
                "recommended_service_id": "application_design_and_submission",
                "service_ranking": [
                    {
                        "service_id": "application_design_and_submission",
                        "supporting_signal_ids": ["sig-1", "sig-2"],
                        "support_count": 2,
                        "support_ratio": 1.0,
                    }
                ],
                "components": {
                    "source_quality": 25,
                    "freshness": 17,
                    "signal_strength": 22,
                    "service_coherence": 20,
                    "actionability": 8,
                },
                "gross_score": 92,
                "penalties": {
                    "unknown_assertions": 8,
                    "low_confidence_inferences": 2,
                    "total": 10,
                },
                "explanations": ["Research-priority score only."],
                "verification_questions": ["Is the need still current?"],
                "source_refs": ["src-org"],
                "signal_ids": ["sig-1", "sig-2"],
                "evidence_label": "NON_EVIDENCE",
            }
        ],
    }


def match_view():
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_R07_PROSPECT_OPPORTUNITY_SERVICE_MATCH",
        "reference_time": "2026-08-27T12:00:00Z",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "bridge_state": "READY",
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "results": [
            {
                "organization_key": "org-a",
                "prospect_id": "prospect-a",
                "priority_state": "PRIORITY_HIGH_RESEARCH",
                "priority_score": 82,
                "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
                "eligibility_state": "NOT_ASSESSED",
                "maximum_next_state": "RESEARCH_READY",
                "state": "MATCHED_RESEARCH_CANDIDATE",
                "recommended_service_id": "application_design_and_submission",
                "signal_supported_service_ids": ["application_design_and_submission", "funding_strategy_and_eligibility"],
                "source_refs": ["src-org"],
                "signal_ids": ["sig-1", "sig-2"],
                "verification_questions": ["Is the official opportunity source still current?"],
                "opportunity_matches": [
                    {
                        "opportunity_id": "opp-1",
                        "title": "Synthetic verified opportunity",
                        "programme": "Synthetic programme",
                        "relevance_score": 74,
                        "relevance_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
                        "confidence": "HIGH",
                        "state": "MATCH_CANDIDATE",
                        "aligned_service_ids": ["application_design_and_submission", "funding_strategy_and_eligibility"],
                        "selected_service_id": "application_design_and_submission",
                        "explanations": ["Verified organization terms overlap."],
                        "hard_exclusion_reasons": [],
                        "verified_fact_classes": ["programme", "audience"],
                        "source_supported_deadline": "2026-12-31",
                        "source_provenance": {
                            "source_product": "PARTENER.EU",
                            "source_projection_hash": "secret-hash",
                            "verification_evidence": ["raw-evidence"],
                        },
                    }
                ],
                "selected_opportunity_id": "opp-1",
                "selected_service_id": "application_design_and_submission",
                "next_best_action": "VERIFY_OPPORTUNITY_CONDITIONS_AND_PREPARE_RESEARCH_BRIEF",
                "external_contact_enabled": False,
                "automatic_offer_enabled": False,
                "evidence_label": "NON_EVIDENCE",
            }
        ],
    }


def expect_error(fn, contains: str):
    try:
        fn()
    except (ValueError, AssertionError) as exc:
        assert contains in str(exc), str(exc)
    else:
        raise AssertionError(f"expected failure containing: {contains}")


def test_happy_path_is_minimized_and_explainable():
    result = mod.build_view(match_view(), score_view(), contract())
    assert result["summary"] == {"evaluated": 1, "matched": 1, "requires_verification": 0, "held": 0, "suppressed": 0}
    row = result["results"][0]
    assert row["priority_score"] == 82
    assert row["score_breakdown"]["components"]["service_coherence"] == 20
    assert row["selected_opportunity"]["opportunity_id"] == "opp-1"
    assert row["selected_service_support"]["supporting_signal_ids"] == ["sig-1", "sig-2"]
    assert row["operator_next_step"] == "REVERIFY_OFFICIAL_SOURCE_AND_VALIDATE_MATCH_BEFORE_OUTREACH"
    assert row["official_source_reverification_required"] is True
    assert row["material_claims_verified"] is False
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in ["source_provenance", "verification_evidence", "source_projection_hash", "source_supported_deadline", "secret-hash", "raw-evidence"]:
        assert forbidden not in serialized
    assert result["external_contact_enabled"] is False
    assert result["automatic_send_enabled"] is False
    assert result["crm_write_enabled"] is False


def test_score_drift_fails_closed():
    score = score_view()
    score["results"][0]["score"] = 81
    expect_error(lambda: mod.build_view(match_view(), score, contract()), "priority score mismatch")


def test_service_alignment_drift_fails_closed():
    match = match_view()
    match["results"][0]["opportunity_matches"][0]["aligned_service_ids"] = ["funding_strategy_and_eligibility"]
    expect_error(lambda: mod.build_view(match, score_view(), contract()), "not opportunity-aligned")


def test_external_action_flag_fails_closed():
    match = match_view()
    match["results"][0]["crm_write_enabled"] = True
    expect_error(lambda: mod.build_view(match, score_view(), contract()), "unsafe action boundary failed open")


def test_inference_and_person_fields_fail_closed():
    score = score_view()
    score["results"][0]["award_probability"] = 0.9
    expect_error(lambda: mod.build_view(match_view(), score, contract()), "forbidden inference field present")
    match = match_view()
    match["results"][0]["personal_email"] = "person@example.invalid"
    expect_error(lambda: mod.build_view(match, score_view(), contract()), "person-level field present")


def test_join_and_nonmatched_selection_fail_closed():
    score = score_view()
    score["results"][0]["organization_key"] = "org-b"
    expect_error(lambda: mod.build_view(match_view(), score, contract()), "organization sets differ")
    match = match_view()
    match["results"][0]["state"] = "REQUIRES_VERIFICATION"
    expect_error(lambda: mod.build_view(match, score_view(), contract()), "non-matched row cannot expose selected")


def test_cli_atomic_output():
    result = mod.build_view(match_view(), score_view(), contract())
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "view.json"
        mod.write_atomic(path, result)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded == result
        assert not path.with_suffix(".json.tmp").exists()


def main():
    test_happy_path_is_minimized_and_explainable()
    test_score_drift_fails_closed()
    test_service_alignment_drift_fails_closed()
    test_external_action_flag_fails_closed()
    test_inference_and_person_fields_fail_closed()
    test_join_and_nonmatched_selection_fail_closed()
    test_cli_atomic_output()
    print("client finder match explainability fail-closed tests: PASS")


if __name__ == "__main__":
    main()
