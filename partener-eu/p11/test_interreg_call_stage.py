#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

from interreg_call import normalize_call_observation
from interreg_call_reconcile import reconcile_live_evidence
from interreg_call_stage import OUTPUT_MISSING_PROOFS, SCHEMA, build_staging_admission


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def source_row(*, suffix="A", status="OPEN", deadline="2026-12-15T14:00:00+01:00", readback=True):
    raw = f"official exact-call staging regression bytes {suffix}".encode("utf-8")
    raw_hash = hashlib.sha256(raw).hexdigest()
    call_id = f"SYNTHETIC-INTERREG-2026-{suffix}"
    url = f"https://interreg-danube.eu/calls-for-proposals/synthetic-2026-call-{suffix.lower()}"
    programme = "Danube Region Programme 2021-2027"
    title = f"Synthetic exact Interreg call {suffix}"
    normalized = normalize_call_observation(
        {
            "call_identifier": call_id,
            "programme": programme,
            "authority_url": url,
            "title": title,
            "official_status": status,
            "deadline": deadline,
            "readback_verified": readback,
        },
        fetched_at="2026-08-28T08:00:00Z",
        raw_hash=raw_hash,
        run_id="interreg-stage-regression",
    )
    return {
        "probe_id": call_id,
        "call_identifier": call_id,
        "programme": programme,
        "registered_url": url,
        "final_url": url,
        "fetched_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-stage-regression",
        "publication_effect": "NONE",
        "publish_authorized": False,
        "material_fact_use": False,
        "canonical_corpus_mutation": False,
        "fetch_status": "PASS",
        "http_status": 200,
        "raw_hash": raw_hash,
        "readback_verified": readback,
        "declared_status_from_visible_text": status,
        "normalized": normalized,
    }


def failed_row():
    return {
        "probe_id": "TLS-FAIL",
        "call_identifier": "CALL-X",
        "programme": "Interreg X",
        "registered_url": "https://interreg-danube.eu/calls-for-proposals/call-x",
        "fetched_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-stage-regression",
        "publication_effect": "NONE",
        "publish_authorized": False,
        "material_fact_use": False,
        "canonical_corpus_mutation": False,
        "fetch_status": "FAIL",
        "error_type": "URLError",
        "error": "certificate verify failed",
    }


def envelope(rows):
    return {
        "schema": "PARTENER_EU_INTERREG_CALL_LIVE_EVIDENCE_V1",
        "created_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-stage-regression",
        "source_family": "INTERREG",
        "authority_class": "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY",
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "rows": rows,
    }


def receipt(rows):
    return reconcile_live_evidence(envelope(rows), reconciled_at="2026-08-28T08:01:00Z")


def empty_bundle():
    return {"opportunities": [], "evidence": []}


def expect_failure(reconciliation, needle, bundle=None):
    try:
        build_staging_admission(reconciliation, bundle or empty_bundle())
    except ValueError as exc:
        if needle not in str(exc):
            raise AssertionError(f"expected {needle!r} in {exc!r}") from exc
    else:
        raise AssertionError(f"expected staging failure containing {needle!r}")


def main():
    # Current live shape: no admissible calls, quarantine preserved, still PASS/non-publishing.
    zero = receipt([
        source_row(suffix="STALE", deadline="2025-12-15T14:00:00+01:00"),
        failed_row(),
    ])
    zero_stage = build_staging_admission(zero, empty_bundle())
    check(zero_stage["schema"] == SCHEMA, "stage schema drift")
    check(zero_stage["canonical_staging_admission"] == "PASS", "empty admission should be a valid fail-closed receipt")
    check(zero_stage["stats"]["staging_admitted"] == 0, "quarantine escaped empty staging")
    check(zero_stage["stats"]["review_required_preserved"] == 2, "quarantine count lost")
    check(zero_stage["material_fact_use"] is False, "empty staging became material")
    check(zero_stage["missing_proofs"] == [], "empty staging invented downstream proof demand")
    check(zero_stage["publish_authorized"] is False and zero_stage["canonical_corpus_mutation"] is False, "empty staging became publishing")

    clean = receipt([source_row()])
    first = build_staging_admission(clean, empty_bundle())
    second = build_staging_admission(copy.deepcopy(clean), empty_bundle())
    check(first["stats"]["staging_admitted"] == 1, "reconciled exact OPEN was not admitted")
    check(first["stats"]["new_candidates"] == 1, "new exact call was not a P11 NEW_CANDIDATE")
    check(first["stats"]["ambiguous_review"] == 0, "clean call became ambiguous")
    check(first["records"][0]["staging_admission"] == "PASS", "admission row not PASS")
    check(first["records"][0]["programme_label_authorized"] is False, "programme label was over-authorized")
    check(first["missing_proofs"] == OUTPUT_MISSING_PROOFS, "projection gate was skipped")
    check(first["records"][0]["missing_proofs"] == OUTPUT_MISSING_PROOFS, "row projection gate was skipped")
    check(first["publish_authorized"] is False and first["publication_effect"] == "NONE", "stage became publishing")
    check(first["p11_staging_ledger_sha256"] == second["p11_staging_ledger_sha256"], "P11 staging is not deterministic")
    check(first["records"][0]["candidate_id"] == second["records"][0]["candidate_id"], "candidate id is not deterministic")

    # Identical repeat observations collapse before P11 staging.
    duplicate = receipt([source_row(), source_row()])
    duplicate_stage = build_staging_admission(duplicate, empty_bundle())
    check(duplicate_stage["stats"]["reconciled_ready_occurrences"] == 2, "duplicate source occurrence missing")
    check(duplicate_stage["stats"]["deduplicated_ready"] == 1, "exact duplicate was not collapsed")
    check(duplicate_stage["stats"]["duplicate_observations_collapsed"] == 1, "duplicate collapse counter drift")
    check(duplicate_stage["records"][0]["duplicate_observations_collapsed"] == 2, "occurrence provenance lost")

    bad_identity = copy.deepcopy(clean)
    bad_identity["records"][0]["identity_fingerprint"] = "0" * 64
    expect_failure(bad_identity, "identity fingerprint drift")

    bad_facts = copy.deepcopy(clean)
    bad_facts["records"][0]["material_facts"]["title"] = "tampered after reconcile"
    expect_failure(bad_facts, "material_facts drift")

    non_admissible = copy.deepcopy(clean)
    non_admissible["records"][0]["observation_state"] = "PLANNED"
    expect_failure(non_admissible, "non-admissible observation state")

    leaked_quarantine = copy.deepcopy(zero)
    leaked_quarantine["quarantined_records"][0]["material_fact_use"] = True
    expect_failure(leaked_quarantine, "quarantined row became authorizing")

    # Same exact call identity with conflicting semantics must never enter P11 staging.
    conflict = copy.deepcopy(duplicate)
    conflict["records"][1]["semantic_fingerprint"] = "f" * 64
    expect_failure(conflict, "semantic conflict for identical normalized call identity")

    # Two distinct canonical matches for the same candidate identity force review.
    record = clean["records"][0]
    candidate_url = record["authority_url"]
    programme = f"INTERREG::{record['programme']}"
    call_id = record["call_identifier"]
    bundle = {
        "evidence": [{"evidence_id": "E-2", "source_url": candidate_url}],
        "opportunities": [
            {
                "opportunity_id": "OPP-CODE",
                "programme": programme,
                "code": call_id,
                "title": "Different canonical title",
                "evidence_refs": [],
            },
            {
                "opportunity_id": "OPP-URL",
                "programme": "Other Programme",
                "code": "OTHER",
                "title": "Other canonical item",
                "evidence_refs": ["E-2"],
            },
        ],
    }
    expect_failure(clean, "ambiguous canonical identity blocks staging admission", bundle=bundle)

    print("PASS INTERREG canonical staging admission: reconcile-only, deterministic dedup, quarantine-preserving, ambiguity-blocking, non-publishing")


if __name__ == "__main__":
    main()
