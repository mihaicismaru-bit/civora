#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENGINE_PATH = ROOT / "eucons" / "prospects" / "client_finder_source_authority_queue.py"
CONTRACT_PATH = ROOT / "eucons" / "prospects" / "client_finder_source_authority_queue_contract.json"

spec = importlib.util.spec_from_file_location("source_authority_queue", ENGINE_PATH)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def contract():
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def held_row(authority_state="WAITING_SOURCE", fact_classes=None, source_count=0):
    return {
        "organization_key": "org-a",
        "prospect_id": "prospect-a",
        "priority_state": "PRIORITY_HIGH_RESEARCH",
        "priority_score": 82,
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "state": "HOLD_SOURCE_STATE",
        "recommended_service_id": "funding_strategy_and_eligibility",
        "signal_supported_service_ids": ["funding_strategy_and_eligibility"],
        "source_refs": ["org-source"],
        "signal_ids": ["signal-1"],
        "verification_questions": ["Which official source confirms the current deadline?"],
        "opportunity_matches": [
            {
                "opportunity_id": "opp-1",
                "title": "Synthetic opportunity",
                "programme": "Synthetic programme",
                "relevance_score": 45,
                "relevance_semantics": "RELEVANCE_NOT_APPROVAL_PROBABILITY",
                "confidence": "LOW",
                "state": "HOLD_SOURCE_STATE",
                "authority_state": authority_state,
                "official_fact_classes": list(fact_classes or []),
                "official_source_count": source_count,
                "aligned_service_ids": [],
                "selected_service_id": None,
                "explanations": ["PARTENER.EU remains discovery/intelligence only."],
                "hard_exclusion_reasons": [],
                "verified_fact_classes": list(fact_classes or []),
                "discovery_projection_fact_classes": ["status", "deadline", "eligibility"],
                "source_supported_deadline": None,
                "source_provenance": {
                    "source_product": "PARTENER.EU",
                    "source_opportunity_id": "opp-1",
                    "source_projection_sha256": "a" * 64,
                    "source_as_of": "2026-08-28T20:00:00Z",
                    "verification_evidence": [{"id": "discovery-only"}],
                },
            }
        ],
        "selected_opportunity_id": None,
        "selected_service_id": None,
        "next_best_action": "WAIT_FOR_SOURCE",
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "evidence_label": "NON_EVIDENCE",
    }


def match_view(*rows, bridge_state="READY"):
    return {
        "schema_version": 1,
        "engine_id": "EUCONS_R07_PROSPECT_OPPORTUNITY_SERVICE_MATCH",
        "reference_time": "2026-08-29T00:00:00Z",
        "match_semantics": "RESEARCH_RELEVANCE_NOT_ELIGIBILITY_AWARD_OR_BUYING_INTENT",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "bridge_state": bridge_state,
        "partener_role": "DISCOVERY_ONLY",
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "results": list(rows),
    }


def expect_error(fn, contains):
    try:
        fn()
    except (ValueError, AssertionError) as exc:
        assert contains in str(exc), str(exc)
    else:
        raise AssertionError(f"expected failure containing: {contains}")


def test_waiting_source_becomes_minimized_operator_task():
    result = mod.build_queue(match_view(held_row()), contract())
    assert result["summary"] == {
        "source_held_prospects": 1,
        "tasks": 1,
        "official_authority_tasks": 1,
        "discovery_refresh_tasks": 0,
        "waiting_source": 1,
        "blocked_source_conflict": 0,
    }
    task = result["tasks"][0]
    assert task["task_type"] == "OFFICIAL_SOURCE_AUTHORITY_REVIEW"
    assert task["opportunity_id"] == "opp-1"
    assert task["authority_state"] == "WAITING_SOURCE"
    assert task["missing_required_official_fact_classes"] == ["deadline", "status"]
    assert task["operator_next_step"] == "VERIFY_OFFICIAL_STATUS_AND_DEADLINE_BEFORE_MATCHING"
    assert task["eligibility_state"] == "NOT_ASSESSED"
    assert task["external_contact_enabled"] is False
    serialized = json.dumps(result, sort_keys=True)
    for forbidden in (
        "source_provenance", "verification_evidence", "source_projection_sha256",
        "source_as_of", "source_supported_deadline", "material_facts", "verified_fact_hashes",
    ):
        assert forbidden not in serialized


def test_partial_binding_identifies_only_missing_required_class():
    result = mod.build_queue(match_view(held_row(fact_classes=["status"], source_count=1)), contract())
    task = result["tasks"][0]
    assert task["official_fact_classes"] == ["status"]
    assert task["missing_required_official_fact_classes"] == ["deadline"]
    assert task["official_source_count"] == 1


def test_official_conflict_fails_closed_into_review_task():
    result = mod.build_queue(match_view(held_row("BLOCKED_SOURCE_CONFLICT", [], 2)), contract())
    task = result["tasks"][0]
    assert result["summary"]["blocked_source_conflict"] == 1
    assert task["missing_required_official_fact_classes"] == ["deadline", "status"]
    assert task["operator_next_step"] == "RESOLVE_OFFICIAL_SOURCE_CONFLICT_BEFORE_MATCHING"


def test_stale_discovery_precedes_authority_review():
    result = mod.build_queue(match_view(held_row(), bridge_state="STALE_SOURCE_HOLD"), contract())
    task = result["tasks"][0]
    assert task["task_type"] == "DISCOVERY_SOURCE_REFRESH"
    assert task["authority_state"] == "NOT_EVALUATED_DISCOVERY_SOURCE_HOLD"
    assert task["opportunity_id"] is None
    assert task["missing_required_official_fact_classes"] == []
    assert task["operator_next_step"] == "REFRESH_DISCOVERY_SOURCE_AND_REEVALUATE"


def test_nonheld_rows_never_enter_queue():
    row = held_row("OFFICIAL_SOURCE_VERIFIED", ["status", "deadline"], 1)
    row["state"] = "MATCHED_RESEARCH_CANDIDATE"
    row["selected_opportunity_id"] = "opp-1"
    row["selected_service_id"] = "funding_strategy_and_eligibility"
    result = mod.build_queue(match_view(row), contract())
    assert result["summary"]["tasks"] == 0
    assert result["tasks"] == []


def test_partener_cannot_be_promoted_to_official_authority():
    view = match_view(held_row())
    view["partener_role"] = "AUTHORITATIVE"
    expect_error(lambda: mod.build_queue(view, contract()), "PARTENER discovery-only")


def test_source_authority_detail_drift_fails_closed():
    no_detail = held_row()
    no_detail["opportunity_matches"] = []
    expect_error(lambda: mod.build_queue(match_view(no_detail), contract()), "lacks WAITING_SOURCE/BLOCKED")

    verified_hold = held_row("OFFICIAL_SOURCE_VERIFIED", ["status", "deadline"], 1)
    expect_error(lambda: mod.build_queue(match_view(verified_hold), contract()), "lacks WAITING_SOURCE/BLOCKED")

    unsupported = held_row(fact_classes=["status", "deadline", "private_fact"], source_count=1)
    expect_error(lambda: mod.build_queue(match_view(unsupported), contract()), "unsupported official fact class")

    no_missing = held_row(fact_classes=["status", "deadline"], source_count=1)
    expect_error(lambda: mod.build_queue(match_view(no_missing), contract()), "no missing required official fact class")

    bad_count = held_row(source_count=True)
    expect_error(lambda: mod.build_queue(match_view(bad_count), contract()), "official source count invalid")

    conflict_with_classes = held_row("BLOCKED_SOURCE_CONFLICT", ["status"], 1)
    expect_error(lambda: mod.build_queue(match_view(conflict_with_classes), contract()), "must not retain authoritative fact classes")

    bad_provenance = held_row()
    bad_provenance["opportunity_matches"][0]["source_provenance"]["source_product"] = "PARTENER.EU-AS-OFFICIAL"
    expect_error(lambda: mod.build_queue(match_view(bad_provenance), contract()), "lost PARTENER discovery provenance")


def test_external_boundaries_and_contract_drift_fail_closed():
    unsafe = match_view(held_row())
    unsafe["crm_write_enabled"] = True
    expect_error(lambda: mod.build_queue(unsafe, contract()), "unsafe action boundary failed open")

    bad_contract = deepcopy(contract())
    bad_contract["source_view"]["partener_role"] = "AUTHORITATIVE"
    expect_error(lambda: mod.build_queue(match_view(held_row()), bad_contract), "PARTENER role failed open")

    bad_contract = deepcopy(contract())
    bad_contract["rules"]["partener_never_satisfies_official_authority"] = False
    expect_error(lambda: mod.build_queue(match_view(held_row()), bad_contract), "safety rule failed open")


def test_output_is_deterministic_and_repository_write_is_forbidden():
    first = held_row()
    second = deepcopy(first)
    second["organization_key"] = "org-b"
    second["prospect_id"] = "prospect-b"
    second["priority_score"] = 70
    second["opportunity_matches"][0]["opportunity_id"] = "opp-2"
    second["opportunity_matches"][0]["source_provenance"]["source_opportunity_id"] = "opp-2"
    result_a = mod.build_queue(match_view(second, first), contract())
    result_b = mod.build_queue(match_view(first, second), contract())
    assert result_a == result_b
    assert [task["organization_key"] for task in result_a["tasks"]] == ["org-a", "org-b"]

    expect_error(lambda: mod.write_atomic(ROOT / "eucons" / "unsafe-source-queue.json", result_a), "repository runtime output")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "source-authority-queue.json"
        mod.write_atomic(path, result_a)
        assert json.loads(path.read_text(encoding="utf-8")) == result_a
        assert not path.with_suffix(".json.tmp").exists()


def main():
    test_waiting_source_becomes_minimized_operator_task()
    test_partial_binding_identifies_only_missing_required_class()
    test_official_conflict_fails_closed_into_review_task()
    test_stale_discovery_precedes_authority_review()
    test_nonheld_rows_never_enter_queue()
    test_partener_cannot_be_promoted_to_official_authority()
    test_source_authority_detail_drift_fails_closed()
    test_external_boundaries_and_contract_drift_fail_closed()
    test_output_is_deterministic_and_repository_write_is_forbidden()
    print("client finder source authority queue fail-closed tests: PASS")


if __name__ == "__main__":
    main()
