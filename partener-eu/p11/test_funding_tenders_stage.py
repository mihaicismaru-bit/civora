#!/usr/bin/env python3
from __future__ import annotations

import copy

from funding_tenders_stage import (
    OUTPUT_MISSING_PROOFS,
    SCHEMA,
    build_staging_admission,
)


def reconciliation_fixture() -> dict:
    records = []
    for index, identifier in enumerate(("HORIZON-TEST-OPEN-01", "HORIZON-TEST-FORTHCOMING-02"), start=1):
        state = "OPEN_CALL" if index == 1 else "FORTHCOMING_CALL"
        status = "OPEN" if index == 1 else "FORTHCOMING"
        records.append({
            "identifier": identifier,
            "call_identifier": f"CALL-{index:02d}",
            "authority_url": f"https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/{identifier}",
            "source_run_id": "RUN-FT-FIXTURE",
            "fetched_at": "2026-08-27T21:00:00+00:00",
            "raw_hash": f"{index:064x}",
            "semantic_fingerprint": f"{index + 20:064x}",
            "raw_search_types": ["1" if index == 1 else "2"],
            "observation_state": state,
            "title": f"Fixture direct EU topic {index}",
            "programme_reference": f"FP-{100 + index}",
            "deadline": "2026-09-30T15:00:00+00:00",
            "budget_eur": 1000000 * index,
            "reconciliation_status": "PASS",
            "evidence_basis": "EC_SEARCH_FACET_PLUS_EXACT_TOPIC_READBACK",
            "material_facts": {
                "title": f"Fixture direct EU topic {index}",
                "status": status,
                "deadline": "2026-09-30T15:00:00+00:00",
                "call_identifier": f"CALL-{index:02d}",
                "budget_eur": 1000000 * index,
            },
            "material_fact_use": True,
            "ready_for_staging": True,
            "publish_authorized": False,
            "publication_effect": "NONE",
            "canonical_corpus_mutation": False,
            "material_fact_action": "NONE",
            "missing_proofs": [
                "CANONICAL_STAGING_ADMISSION",
                "PUBLIC_PROJECTION_QUALITY_GATE",
            ],
            "reasons": [],
        })
    quarantined = [{
        "identifier": "DIGITAL-PORTAL-ONLY-08",
        "call_identifier": "CALL-08",
        "authority_url": "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-details/DIGITAL-PORTAL-ONLY-08",
        "source_run_id": "RUN-FT-FIXTURE",
        "fetched_at": "2026-08-27T21:00:00+00:00",
        "raw_hash": "f" * 64,
        "semantic_fingerprint": "e" * 64,
        "raw_search_types": ["8"],
        "observation_state": "OPEN_CALL",
        "title": "Portal-listed third-party funding fixture",
        "programme_reference": "DIGITAL-REF",
        "deadline": "2024-01-01T00:00:00+00:00",
        "budget_eur": None,
        "reconciliation_status": "REVIEW_REQUIRED",
        "ready_for_staging": False,
        "material_fact_use": False,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "material_fact_action": "NONE",
        "reasons": [
            "NON_DIRECT_OR_PORTAL_ONLY_CALL_TYPE",
            "STALE_DEADLINE_CONTRADICTS_OPEN",
        ],
    }]
    return {
        "schema": "PARTENER_EU_FUNDING_TENDERS_RECONCILIATION_RECEIPT_V1",
        "source_schema": "PARTENER_EU_FUNDING_TENDERS_LIVE_EVIDENCE_V1",
        "source_family": "EU_DIRECT",
        "programme_family": "BRUSSELS",
        "authority_class": "EU_COMMISSION_FUNDING_TENDERS",
        "source_run_id": "RUN-FT-FIXTURE",
        "source_fetched_at": "2026-08-27T21:00:00+00:00",
        "source_evidence_hash": "a" * 64,
        "search_response_sha256": "b" * 64,
        "reconciled_at": "2026-08-27T21:01:00+00:00",
        "records": records,
        "quarantined_records": quarantined,
        "stats": {
            "normalized_records": 3,
            "ready_for_staging": 2,
            "review_required": 1,
            "direct_call_type_records": 2,
            "portal_only_or_non_direct_records": 1,
            "semantic_conflicts": 0,
            "stale_deadline_contradictions": 1,
        },
        "material_fact_use": True,
        "ready_for_staging": True,
        "publish_authorized": False,
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "material_fact_action": "NONE",
        "missing_proofs": [
            "CANONICAL_STAGING_ADMISSION",
            "PUBLIC_PROJECTION_QUALITY_GATE",
        ],
    }


def empty_bundle() -> dict:
    return {"opportunities": [], "evidence": []}


def expect_failure(receipt: dict, needle: str) -> None:
    try:
        build_staging_admission(receipt, empty_bundle())
    except ValueError as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in {exc!r}") from exc
    else:
        raise AssertionError(f"expected staging admission failure containing {needle!r}")


def main() -> int:
    source = reconciliation_fixture()
    first = build_staging_admission(source, empty_bundle())
    second = build_staging_admission(copy.deepcopy(source), empty_bundle())

    assert first["schema"] == SCHEMA
    assert first["canonical_staging_admission"] == "PASS"
    assert first["stats"]["staging_admitted"] == 2
    assert first["stats"]["review_required_preserved"] == 1
    assert first["stats"]["new_candidates"] == 2
    assert first["stats"]["canonical_matches"] == 0
    assert first["stats"]["ambiguous_review"] == 0
    assert first["canonical_corpus_mutation"] is False
    assert first["publish_authorized"] is False
    assert first["publication_effect"] == "NONE"
    assert first["material_fact_action"] == "NONE"
    assert first["programme_label_authorized"] is False
    assert first["missing_proofs"] == OUTPUT_MISSING_PROOFS
    assert first["quarantined_identifiers_preserved"] == ["DIGITAL-PORTAL-ONLY-08"]
    assert first["p11_staging_ledger_sha256"] == second["p11_staging_ledger_sha256"]
    assert [row["candidate_id"] for row in first["records"]] == [row["candidate_id"] for row in second["records"]]
    assert all(row["staging_admission"] == "PASS" for row in first["records"])
    assert all(row["programme_label_authorized"] is False for row in first["records"])
    assert all(row["canonical_corpus_mutation"] is False for row in first["records"])
    assert all(row["publish_authorized"] is False for row in first["records"])
    assert all(row["missing_proofs"] == OUTPUT_MISSING_PROOFS for row in first["records"])

    unsafe = copy.deepcopy(source)
    unsafe["records"][0]["publish_authorized"] = True
    expect_failure(unsafe, "unsafe publish/corpus state")

    unresolved = copy.deepcopy(source)
    unresolved["records"][0]["missing_proofs"] = ["PUBLIC_PROJECTION_QUALITY_GATE"]
    expect_failure(unresolved, "downstream proof contract drift")

    leaked_quarantine = copy.deepcopy(source)
    leaked_quarantine["quarantined_records"][0]["material_fact_use"] = True
    expect_failure(leaked_quarantine, "quarantined row became authorizing")

    non_direct = copy.deepcopy(source)
    non_direct["records"][0]["raw_search_types"] = ["8"]
    expect_failure(non_direct, "non-direct Search type reached staging")

    bad_stats = copy.deepcopy(source)
    bad_stats["stats"]["ready_for_staging"] = 1
    expect_failure(bad_stats, "ready_for_staging stats mismatch")

    print("PASS Funding & Tenders canonical staging admission: direct-only, deterministic, quarantine-preserving, non-publishing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
