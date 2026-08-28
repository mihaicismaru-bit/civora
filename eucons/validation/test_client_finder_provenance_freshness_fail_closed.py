#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "prospects" / "client_finder_provenance_freshness_contract.json"
MODULE_PATH = EUCONS / "prospects" / "client_finder_provenance_freshness.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


freshness = load_module("r07_client_finder_provenance_freshness", MODULE_PATH)


def must_fail(label: str, fn) -> None:
    try:
        fn()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError(f"{label} failed open")


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_flags() -> dict:
    return {
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
    }


def matched_card(rank: int, prospect_id: str, opportunity_id: str, source_as_of: str) -> dict:
    return {
        "source_rank": rank,
        "triage_rank": rank,
        "prospect_id": prospect_id,
        "organization_key": f"ORG-{prospect_id}",
        "state": "MATCHED_RESEARCH_CANDIDATE",
        "priority_state": "PRIORITY_HIGH_RESEARCH",
        "priority_score": 70,
        "attention_reason": "VERIFIED_OPPORTUNITY_SERVICE_OVERLAP",
        "selected_opportunity": {
            "opportunity_id": opportunity_id,
            "title": "Synthetic verified opportunity",
            "programme": "Synthetic programme",
            "relevance_score": 80,
            "selected_service_id": "funding_strategy_and_eligibility",
            "source_supported_deadline": "2026-09-30",
            "verified_fact_classes": ["deadline", "programme"],
            "source_trace": {
                "source_product": "PARTENER.EU",
                "source_opportunity_id": opportunity_id,
                "source_as_of": source_as_of,
                "source_projection_sha256": "a" * 64,
                "verification_evidence_count": 2,
            },
        },
        "selected_service_id": "funding_strategy_and_eligibility",
        "safe_next_action": "VERIFY_RESEARCH_CANDIDATE",
        "verification_questions": ["Confirm organization-level fit."],
        "source_ref_count": 2,
        "signal_count": 2,
        "evidence_label": "SOURCE_SUPPORTED_RESEARCH_MATCH",
        "has_source_supported_deadline": True,
        **safe_flags(),
    }


def unmatched_card(rank: int, prospect_id: str) -> dict:
    return {
        "source_rank": rank,
        "triage_rank": rank,
        "prospect_id": prospect_id,
        "organization_key": f"ORG-{prospect_id}",
        "state": "REQUIRES_VERIFICATION",
        "priority_state": "PRIORITY_MEDIUM_RESEARCH",
        "priority_score": 50,
        "attention_reason": "ORGANIZATION_OR_PROJECT_FACTS_INCOMPLETE",
        "selected_opportunity": None,
        "selected_service_id": None,
        "safe_next_action": "VERIFY_ORGANIZATION_FACTS",
        "verification_questions": ["Verify organization-level facts."],
        "source_ref_count": 1,
        "signal_count": 1,
        "evidence_label": "REQUIRES_VERIFICATION",
        "has_source_supported_deadline": False,
        **safe_flags(),
    }


def synthetic_triage() -> dict:
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-TRIAGE-VIEW-002",
        "source_contract_id": "EUCONS-R07-CLIENT-FINDER-PRIORITY-VIEW-001",
        "view_state": "CLIENT_FINDER_OPERATOR_TRIAGE_VIEW",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "bridge_state": "READY",
        "filters": {},
        "sort_mode": "RESEARCH_PRIORITY",
        "summary": {"source_cards": 3, "visible_cards": 3, "with_source_supported_deadline": 2},
        "cards": [
            matched_card(1, "PROS-SYNTH-A", "OPP-SYNTH-A", "2026-08-27T08:00:00Z"),
            matched_card(2, "PROS-SYNTH-B", "OPP-SYNTH-B", "2026-08-26T09:00:00Z"),
            unmatched_card(3, "PROS-SYNTH-C"),
        ],
        **safe_flags(),
    }


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    triage = synthetic_triage()

    result = freshness.build_provenance_freshness_view(triage, contract=contract)
    if result["view_state"] != "CLIENT_FINDER_PROVENANCE_FRESHNESS_VIEW":
        raise AssertionError("freshness view state drift")
    if result["semantics"] != "OBSERVABILITY_ONLY_NO_STALE_THRESHOLD":
        raise AssertionError("freshness semantics drift")
    if [row["prospect_id"] for row in result["rows"]] != ["PROS-SYNTH-B", "PROS-SYNTH-A"]:
        raise AssertionError("oldest-source-first ordering drift")
    if [row["freshness_rank"] for row in result["rows"]] != [1, 2]:
        raise AssertionError("freshness ranking drift")
    if result["summary"] != {
        "matched_source_rows": 2,
        "oldest_source_as_of": "2026-08-26T09:00:00Z",
        "newest_source_as_of": "2026-08-27T08:00:00Z",
        "stale_threshold_applied": False,
    }:
        raise AssertionError("freshness summary drift")
    if any(result[flag] for flag in (
        "external_contact_enabled", "automatic_offer_enabled", "automatic_send_enabled",
        "crm_write_enabled", "pipeline_write_enabled",
    )):
        raise AssertionError("freshness view opened an external or persistence action")
    if canonical(result) != canonical(freshness.build_provenance_freshness_view(triage, contract=contract)):
        raise AssertionError("freshness view is not deterministic")

    offset_timestamp = deepcopy(triage)
    offset_timestamp["cards"][0]["selected_opportunity"]["source_trace"]["source_as_of"] = "2026-08-27T11:00:00+03:00"
    must_fail(
        "non-Z source_as_of",
        lambda: freshness.build_provenance_freshness_view(offset_timestamp, contract=contract),
    )

    date_only = deepcopy(triage)
    date_only["cards"][0]["selected_opportunity"]["source_trace"]["source_as_of"] = "2026-08-27"
    must_fail(
        "date-only source_as_of",
        lambda: freshness.build_provenance_freshness_view(date_only, contract=contract),
    )

    impossible_time = deepcopy(triage)
    impossible_time["cards"][0]["selected_opportunity"]["source_trace"]["source_as_of"] = "2026-02-30T08:00:00Z"
    must_fail(
        "invalid calendar source_as_of",
        lambda: freshness.build_provenance_freshness_view(impossible_time, contract=contract),
    )

    noisy_trace = deepcopy(triage)
    noisy_trace["cards"][0]["selected_opportunity"]["source_trace"]["verification_evidence"] = [{"raw": "blocked"}]
    must_fail(
        "raw evidence in freshness source trace",
        lambda: freshness.build_provenance_freshness_view(noisy_trace, contract=contract),
    )

    wrong_source = deepcopy(triage)
    wrong_source["cards"][0]["selected_opportunity"]["source_trace"]["source_product"] = "UNVERIFIED_SOURCE"
    must_fail(
        "freshness source product drift",
        lambda: freshness.build_provenance_freshness_view(wrong_source, contract=contract),
    )

    wrong_opportunity = deepcopy(triage)
    wrong_opportunity["cards"][0]["selected_opportunity"]["source_trace"]["source_opportunity_id"] = "OPP-OTHER"
    must_fail(
        "freshness source opportunity mismatch",
        lambda: freshness.build_provenance_freshness_view(wrong_opportunity, contract=contract),
    )

    unsafe_action = deepcopy(triage)
    unsafe_action["cards"][0]["crm_write_enabled"] = True
    must_fail(
        "freshness source card CRM write enabled",
        lambda: freshness.build_provenance_freshness_view(unsafe_action, contract=contract),
    )

    person_level = deepcopy(triage)
    person_level["cards"][0]["personal_email"] = "person@example.invalid"
    must_fail(
        "person-level field in freshness source",
        lambda: freshness.build_provenance_freshness_view(person_level, contract=contract),
    )

    stale_threshold = deepcopy(contract)
    stale_threshold["provenance"]["stale_after_hours"] = 24
    must_fail(
        "invented stale threshold",
        lambda: freshness.build_provenance_freshness_view(triage, contract=stale_threshold),
    )

    unsafe_output = deepcopy(contract)
    unsafe_output["output"]["automatic_send_enabled"] = True
    must_fail(
        "freshness automatic send enabled",
        lambda: freshness.build_provenance_freshness_view(triage, contract=unsafe_output),
    )

    print("PASS: Client Finder provenance freshness view is strict, deterministic, threshold-free and non-writing")


if __name__ == "__main__":
    main()
