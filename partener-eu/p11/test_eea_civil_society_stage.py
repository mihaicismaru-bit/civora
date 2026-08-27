#!/usr/bin/env python3
from __future__ import annotations

import copy

from eea_civil_society_stage import (
    OUTPUT_MISSING_PROOFS,
    SCHEMA,
    build_staging_admission,
)


def reconciliation_fixture() -> dict:
    records = []
    for number, budget in ((1, 3718664), (2, 4500000)):
        code = f"EEA-CSF-RO-CALL-{number:02d}"
        records.append({
            "call_identifier": code,
            "call_number": number,
            "programme_family": "EEA Civil Society Fund Romania 2021-2028",
            "source_family": "EEA_NORWAY",
            "authority_class": "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA",
            "authority_url": f"https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-{number}-fixture",
            "source_run_id": "RUN-EEA-CSF-FIXTURE",
            "fetched_at": "2026-08-27T20:00:00+00:00",
            "raw_hash": f"{number:064x}",
            "semantic_fingerprint": f"{number + 20:064x}",
            "reconciliation_status": "PASS",
            "evidence_basis": "EXACT_OFFICIAL_CALL_PAGE_READBACK",
            "observation_state": "OPEN_CALL",
            "material_facts": {
                "title": f"Call #{number}: Fixture topic",
                "status": "OPEN_CALL",
                "publication_date": "2026-08-20",
                "submission_deadline": "2026-10-08",
                "questions_deadline": "2026-09-29",
                "budget_eur": budget,
                "grant_min_eur": 15000,
                "grant_max_eur": 350000,
                "eligible_applicants": "Non-profit organisations legally established in Romania",
            },
            "material_fact_use": True,
            "publish_authorized": False,
            "requires_reconcile": False,
            "ready_for_staging": True,
            "missing_proofs": [
                "CANONICAL_STAGING_ADMISSION",
                "PUBLIC_PROJECTION_QUALITY_GATE",
            ],
        })
    return {
        "schema": "PARTENER_EU_EEA_CSF_RECONCILIATION_RECEIPT_V1",
        "source_family": "EEA_NORWAY",
        "programme_family": "EEA Civil Society Fund Romania 2021-2028",
        "authority_class": "EEA_FMO_CIVIL_SOCIETY_FUND_ROMANIA",
        "reconciled_at": "2026-08-27T20:01:00+00:00",
        "source_run_id": "RUN-EEA-CSF-FIXTURE",
        "source_fetched_at": "2026-08-27T20:00:00+00:00",
        "source_evidence_hash": "a" * 64,
        "batch_semantic_hash": "b" * 64,
        "records": records,
        "stats": {
            "reconciled_calls": 2,
            "material_fact_ready_for_staging": 2,
            "total_call_budget_eur": sum(row[1] for row in ((1, 3718664), (2, 4500000))),
            "errors": 0,
            "conflicts": 0,
        },
        "material_fact_use": True,
        "ready_for_staging": True,
        "publish_authorized": False,
        "publication_effect": "NONE",
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
    assert first["stats"]["new_candidates"] == 2
    assert first["stats"]["canonical_matches"] == 0
    assert first["stats"]["ambiguous_review"] == 0
    assert first["canonical_corpus_mutation"] is False
    assert first["publish_authorized"] is False
    assert first["publication_effect"] == "NONE"
    assert first["material_fact_action"] == "NONE"
    assert first["missing_proofs"] == OUTPUT_MISSING_PROOFS
    assert first["p11_staging_ledger_sha256"] == second["p11_staging_ledger_sha256"]
    assert [row["candidate_id"] for row in first["records"]] == [row["candidate_id"] for row in second["records"]]
    assert all(row["staging_admission"] == "PASS" for row in first["records"])
    assert all(row["canonical_corpus_mutation"] is False for row in first["records"])
    assert all(row["publish_authorized"] is False for row in first["records"])
    assert all(row["missing_proofs"] == OUTPUT_MISSING_PROOFS for row in first["records"])

    unsafe = copy.deepcopy(source)
    unsafe["records"][0]["publish_authorized"] = True
    expect_failure(unsafe, "unsafe publish/reconcile state")

    unresolved = copy.deepcopy(source)
    unresolved["records"][0]["missing_proofs"] = ["PUBLIC_PROJECTION_QUALITY_GATE"]
    expect_failure(unresolved, "downstream proof contract drift")

    conflicted = copy.deepcopy(source)
    conflicted["stats"]["conflicts"] = 1
    expect_failure(conflicted, "errors/conflicts")

    incomplete = copy.deepcopy(source)
    incomplete["stats"]["material_fact_ready_for_staging"] = 1
    expect_failure(incomplete, "batch is incomplete")

    print("PASS EEA CSF canonical staging admission: deterministic, all-or-nothing, non-publishing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
