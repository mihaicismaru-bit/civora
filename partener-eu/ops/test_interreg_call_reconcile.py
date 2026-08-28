#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

from interreg_call import normalize_call_observation
from interreg_call_reconcile import reconcile_live_evidence


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def source_row(*, status="OPEN", deadline="2026-12-15T14:00:00+01:00", readback=True, title="Synthetic exact call"):
    raw = b"official exact-call synthetic regression bytes"
    raw_hash = hashlib.sha256(raw).hexdigest()
    url = "https://interreg-danube.eu/calls-for-proposals/synthetic-2026-call"
    normalized = normalize_call_observation(
        {
            "call_identifier": "SYNTHETIC-INTERREG-2026",
            "programme": "Danube Region Programme 2021-2027",
            "authority_url": url,
            "title": title,
            "official_status": status,
            "deadline": deadline,
            "readback_verified": readback,
        },
        fetched_at="2026-08-28T08:00:00Z",
        raw_hash=raw_hash,
        run_id="interreg-reconcile-regression",
    )
    return {
        "probe_id": "SYNTHETIC-INTERREG-2026",
        "call_identifier": "SYNTHETIC-INTERREG-2026",
        "programme": "Danube Region Programme 2021-2027",
        "registered_url": url,
        "final_url": url,
        "fetched_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-reconcile-regression",
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


def envelope(rows):
    return {
        "schema": "PARTENER_EU_INTERREG_CALL_LIVE_EVIDENCE_V1",
        "created_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-reconcile-regression",
        "source_family": "INTERREG",
        "authority_class": "OFFICIAL_INTERREG_PROGRAMME_AUTHORITY",
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "publish_authorized": False,
        "rows": rows,
    }


def main():
    clean = reconcile_live_evidence(envelope([source_row()]), reconciled_at="2026-08-28T08:01:00Z")
    check(clean["stats"]["ready_for_staging"] == 1, "fully evidenced current OPEN did not pass reconcile")
    check(clean["records"][0]["material_facts"]["status"] == "OPEN", "OPEN material status missing")
    check(clean["records"][0]["material_fact_use"] is True, "reconciled fact was not marked usable for staging")
    check(clean["publish_authorized"] is False and clean["canonical_corpus_mutation"] is False, "reconcile became publishing")
    check(clean["missing_proofs"] == ["CANONICAL_STAGING_ADMISSION", "PUBLIC_PROJECTION_QUALITY_GATE"], "downstream proof boundary drifted")

    stale = reconcile_live_evidence(envelope([source_row(deadline="2025-12-15T14:00:00+01:00")]), reconciled_at="2026-08-28T08:01:00Z")
    check(stale["stats"]["ready_for_staging"] == 0 and stale["stats"]["review_required"] == 1, "expired OPEN escaped reconcile")
    check("NON_ADMISSIBLE_CALL_STATE" in stale["quarantined_records"][0]["reasons"], "expired OPEN quarantine reason missing")

    unread = reconcile_live_evidence(envelope([source_row(readback=False)]), reconciled_at="2026-08-28T08:01:00Z")
    check(unread["stats"]["ready_for_staging"] == 0, "unverified exact page escaped reconcile")
    check("EXACT_CALL_READBACK_NOT_VERIFIED" in unread["quarantined_records"][0]["reasons"], "readback quarantine reason missing")

    failed = {
        "probe_id": "TLS-FAIL",
        "call_identifier": "CALL-X",
        "programme": "Interreg X",
        "registered_url": "https://interreg-danube.eu/calls-for-proposals/call-x",
        "fetched_at": "2026-08-28T08:00:00Z",
        "run_id": "interreg-reconcile-regression",
        "publication_effect": "NONE",
        "publish_authorized": False,
        "material_fact_use": False,
        "canonical_corpus_mutation": False,
        "fetch_status": "FAIL",
        "error_type": "URLError",
        "error": "certificate verify failed",
    }
    fail_receipt = reconcile_live_evidence(envelope([failed]), reconciled_at="2026-08-28T08:01:00Z")
    check(fail_receipt["stats"]["ready_for_staging"] == 0, "transport failure escaped reconcile")
    check("OFFICIAL_CALL_FETCH_FAILED" in fail_receipt["quarantined_records"][0]["reasons"], "transport failure reason missing")

    tampered = source_row()
    tampered["normalized"] = dict(tampered["normalized"])
    tampered["normalized"]["title"] = "Tampered title"
    drift = reconcile_live_evidence(envelope([tampered]), reconciled_at="2026-08-28T08:01:00Z")
    check(drift["stats"]["ready_for_staging"] == 0, "semantic fingerprint tampering escaped reconcile")
    check("SEMANTIC_FINGERPRINT_MISMATCH" in drift["quarantined_records"][0]["reasons"], "semantic drift reason missing")

    print("PASS INTERREG exact-call reconcile: current exact OPEN can become staging-ready; stale/unread/fetch-fail/drift stay quarantined and non-publishing")


if __name__ == "__main__":
    main()
