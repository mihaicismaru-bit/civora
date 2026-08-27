#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EUCONS = ROOT / "eucons"
CONTRACT_PATH = EUCONS / "prospects" / "client_finder_provenance_triage_explainability_contract.json"
MODULE_PATH = EUCONS / "prospects" / "client_finder_provenance_triage_explainability.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot load {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


explainability = load_module("r07_client_finder_provenance_triage_explainability", MODULE_PATH)


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


def source_row(
    rank: int,
    prospect_id: str,
    opportunity_id: str,
    source_as_of: str,
    projection_sha: str | None = None,
) -> dict:
    return {
        "prospect_id": prospect_id,
        "organization_key": f"ORG-{prospect_id}",
        "opportunity_id": opportunity_id,
        "selected_service_id": "funding_strategy_and_eligibility",
        "source_as_of": source_as_of,
        "source_projection_sha256": projection_sha,
        "verification_evidence_count": 2,
        "ordering_semantics": "OLDEST_SOURCE_AS_OF_FIRST_NOT_A_STALE_CLAIM",
        "human_review_required": True,
        "external_contact_enabled": False,
        "automatic_offer_enabled": False,
        "automatic_send_enabled": False,
        "crm_write_enabled": False,
        "pipeline_write_enabled": False,
        "freshness_rank": rank,
    }


def synthetic_freshness() -> dict:
    rows = [
        source_row(1, "PROS-SYNTH-A", "OPP-SYNTH-A", "2026-08-25T09:00:00Z", "a" * 64),
        source_row(2, "PROS-SYNTH-B", "OPP-SYNTH-B", "2026-08-27T08:00:00Z", None),
        source_row(3, "PROS-SYNTH-C", "OPP-SYNTH-C", "2026-08-27T08:00:00Z", "c" * 64),
    ]
    return {
        "schema_version": 1,
        "contract_id": "EUCONS-R07-CLIENT-FINDER-PROVENANCE-FRESHNESS-001",
        "source_contract_id": "EUCONS-R07-CLIENT-FINDER-TRIAGE-VIEW-002",
        "view_state": "CLIENT_FINDER_PROVENANCE_FRESHNESS_VIEW",
        "semantics": "OBSERVABILITY_ONLY_NO_STALE_THRESHOLD",
        "eligibility_state": "NOT_ASSESSED",
        "maximum_next_state": "RESEARCH_READY",
        "summary": {
            "matched_source_rows": 3,
            "oldest_source_as_of": "2026-08-25T09:00:00Z",
            "newest_source_as_of": "2026-08-27T08:00:00Z",
            "stale_threshold_applied": False,
        },
        "rows": rows,
        **safe_flags(),
    }


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    source = synthetic_freshness()

    result = explainability.build_provenance_triage_explainability_view(source, contract=contract)
    if result["view_state"] != "CLIENT_FINDER_PROVENANCE_TRIAGE_EXPLAINABILITY_VIEW":
        raise AssertionError("explainability view state drift")
    if result["semantics"] != "REVERIFICATION_QUEUE_EXPLAINABILITY_ONLY":
        raise AssertionError("explainability semantics drift")
    if [row["queue_rank"] for row in result["rows"]] != [1, 2, 3]:
        raise AssertionError("re-verification queue rank drift")
    if [row["relative_source_age_cue"] for row in result["rows"]] != [
        "EARLIEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
        "TIED_LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
        "TIED_LATEST_SOURCE_SNAPSHOT_IN_CURRENT_SET",
    ]:
        raise AssertionError("relative source-age cue drift")
    if result["rows"][1]["source_projection_sha256_present"] is not False:
        raise AssertionError("projection hash absence cue drift")
    if result["rows"][2]["source_projection_sha256_present"] is not True:
        raise AssertionError("projection hash presence cue drift")
    if result["summary"] != {
        "review_queue_rows": 3,
        "distinct_source_as_of_values": 2,
        "source_as_of_ties_present": True,
        "oldest_source_as_of": "2026-08-25T09:00:00Z",
        "newest_source_as_of": "2026-08-27T08:00:00Z",
        "threshold_applied": False,
        "source_age_classification": "NOT_CLASSIFIED",
    }:
        raise AssertionError("explainability summary drift")
    if any(result[flag] for flag in (
        "external_contact_enabled",
        "automatic_offer_enabled",
        "automatic_send_enabled",
        "crm_write_enabled",
        "pipeline_write_enabled",
    )):
        raise AssertionError("explainability opened an external or persistence action")
    if canonical(result) != canonical(explainability.build_provenance_triage_explainability_view(source, contract=contract)):
        raise AssertionError("explainability view is not deterministic")

    serialized = canonical(result).lower()
    if "stale" in serialized:
        raise AssertionError("output emitted a stale classification or label")
    if "buying_intent" in serialized:
        raise AssertionError("output emitted a buying-intent claim")
    if "a" * 64 in canonical(result) or "c" * 64 in canonical(result):
        raise AssertionError("output leaked source projection hash values")

    single_source = synthetic_freshness()
    single_source["rows"] = [single_source["rows"][0]]
    single_source["summary"] = {
        "matched_source_rows": 1,
        "oldest_source_as_of": "2026-08-25T09:00:00Z",
        "newest_source_as_of": "2026-08-25T09:00:00Z",
        "stale_threshold_applied": False,
    }
    single_result = explainability.build_provenance_triage_explainability_view(single_source, contract=contract)
    if single_result["rows"][0]["relative_source_age_cue"] != "ONLY_MATCHED_SOURCE_SNAPSHOT":
        raise AssertionError("single-source cue drift")

    empty_source = synthetic_freshness()
    empty_source["rows"] = []
    empty_source["summary"] = {
        "matched_source_rows": 0,
        "oldest_source_as_of": None,
        "newest_source_as_of": None,
        "stale_threshold_applied": False,
    }
    empty_result = explainability.build_provenance_triage_explainability_view(empty_source, contract=contract)
    if empty_result["summary"]["review_queue_rows"] != 0 or empty_result["rows"] != []:
        raise AssertionError("empty-source handling drift")

    wrong_source_contract = deepcopy(source)
    wrong_source_contract["source_contract_id"] = "UNEXPECTED-UPSTREAM"
    must_fail(
        "freshness upstream contract drift",
        lambda: explainability.build_provenance_triage_explainability_view(wrong_source_contract, contract=contract),
    )

    wrong_semantics = deepcopy(source)
    wrong_semantics["semantics"] = "STALE_CLASSIFICATION"
    must_fail(
        "freshness source semantics drift",
        lambda: explainability.build_provenance_triage_explainability_view(wrong_semantics, contract=contract),
    )

    threshold_applied = deepcopy(source)
    threshold_applied["summary"]["stale_threshold_applied"] = True
    must_fail(
        "source stale threshold applied",
        lambda: explainability.build_provenance_triage_explainability_view(threshold_applied, contract=contract),
    )

    non_z_timestamp = deepcopy(source)
    non_z_timestamp["rows"][0]["source_as_of"] = "2026-08-25T12:00:00+03:00"
    non_z_timestamp["summary"]["oldest_source_as_of"] = "2026-08-25T12:00:00+03:00"
    must_fail(
        "non-Z source timestamp",
        lambda: explainability.build_provenance_triage_explainability_view(non_z_timestamp, contract=contract),
    )

    rank_gap = deepcopy(source)
    rank_gap["rows"][1]["freshness_rank"] = 3
    must_fail(
        "non-contiguous freshness rank",
        lambda: explainability.build_provenance_triage_explainability_view(rank_gap, contract=contract),
    )

    wrong_order = deepcopy(source)
    wrong_order["rows"][0]["source_as_of"] = "2026-08-28T08:00:00Z"
    wrong_order["summary"]["oldest_source_as_of"] = "2026-08-28T08:00:00Z"
    must_fail(
        "freshness rows not oldest first",
        lambda: explainability.build_provenance_triage_explainability_view(wrong_order, contract=contract),
    )

    raw_evidence = deepcopy(source)
    raw_evidence["rows"][0]["verification_evidence"] = [{"raw": "blocked"}]
    must_fail(
        "raw verification evidence leakage",
        lambda: explainability.build_provenance_triage_explainability_view(raw_evidence, contract=contract),
    )

    person_level = deepcopy(source)
    person_level["personal_email"] = "person@example.invalid"
    must_fail(
        "person-level source field",
        lambda: explainability.build_provenance_triage_explainability_view(person_level, contract=contract),
    )

    unsafe_action = deepcopy(source)
    unsafe_action["rows"][0]["crm_write_enabled"] = True
    must_fail(
        "source row CRM write enabled",
        lambda: explainability.build_provenance_triage_explainability_view(unsafe_action, contract=contract),
    )

    zero_evidence = deepcopy(source)
    zero_evidence["rows"][0]["verification_evidence_count"] = 0
    must_fail(
        "zero verification reference count",
        lambda: explainability.build_provenance_triage_explainability_view(zero_evidence, contract=contract),
    )

    unexpected_top_level = deepcopy(source)
    unexpected_top_level["debug_payload"] = {"raw": "blocked"}
    must_fail(
        "unexpected source top-level field",
        lambda: explainability.build_provenance_triage_explainability_view(unexpected_top_level, contract=contract),
    )

    stale_threshold = deepcopy(contract)
    stale_threshold["thresholds"]["stale_after_hours"] = 24
    must_fail(
        "invented stale threshold",
        lambda: explainability.build_provenance_triage_explainability_view(source, contract=stale_threshold),
    )

    unsafe_output = deepcopy(contract)
    unsafe_output["output"]["automatic_send_enabled"] = True
    must_fail(
        "automatic send enabled",
        lambda: explainability.build_provenance_triage_explainability_view(source, contract=unsafe_output),
    )

    print("PASS: provenance triage explainability is deterministic, relative-only, threshold-free and non-writing")


if __name__ == "__main__":
    main()
