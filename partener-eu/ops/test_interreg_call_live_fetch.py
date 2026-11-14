#!/usr/bin/env python3
from __future__ import annotations

import sys
import json
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))

import interreg_call_live_fetch as live


def check(condition, message):
    if not condition:
        raise AssertionError(message)


# Transport aliases are not semantic evidence. If an official host fails TLS in the
# GitHub runner, live acquisition must preserve FETCH_FAILED rather than weaken
# certificate verification or treat a hostname variant as proof of a call state.
def fake_fetch(url: str):
    if "third-call-for-proposals" in url:
        body = b"""<html><body><h1>Third call for proposals</h1><p>The 3rd CfP is open until 15 December 2025.</p><p>Application deadline 15 December 2025.</p><p>Official programme authority exact-call regression control page with sufficient visible evidence.</p></body></html>"""
        return body, url, 200, "text/html; charset=utf-8"
    if "open-calls-for-proposals-call-6" in url:
        body = b"""<html><body><h1>Call 6</h1><p>Launching date - 23rd of June 2025.</p><p>The deadline was extended until 22nd of December 2025, 13:00 EET.</p><p>Official programme authority exact-call regression control page with sufficient visible evidence.</p></body></html>"""
        return body, url, 200, "text/html; charset=utf-8"
    if "1662-launching" in url:
        body = b"""<html><body><h1>Launching of the second call for small-scale projects</h1><p>The Managing Authority is launching the second call.</p><p>The deadline for online submission is 28 July 2025, 14:00.</p><p>Official programme authority exact-call regression control page with sufficient visible evidence.</p></body></html>"""
        return body, url, 200, "text/html; charset=utf-8"
    raise AssertionError(f"unexpected URL {url}")


def main():
    original = live._fetch
    try:
        live._fetch = fake_fetch
        evidence = live.build_live_evidence(run_id="interreg-call-live-regression")
        live.validate_envelope(evidence)
    finally:
        live._fetch = original

    check(evidence["probe_count"] == 3, "bounded exact-call probe set drifted")
    check(evidence["fetch_pass"] == 3 and evidence["fetch_fail"] == 0, "fixture fetch did not complete")
    check(evidence["publish_authorized"] is False and evidence["publication_effect"] == "NONE", "envelope became authorizing")
    check(evidence["canonical_corpus_mutation"] is False, "live evidence mutated canonical corpus")

    rows = {row["probe_id"]: row for row in evidence["rows"]}
    danube = rows["DRP-THIRD-CALL-2025"]
    check(danube["readback_verified"] is True, "exact Danube call markers were not verified")
    check(danube["normalized"]["observation_state"] == "REVIEW_REQUIRED", "stale OPEN escaped deadline reconciliation")
    check("open_status_conflicts_with_expired_deadline" in danube["normalized"]["review_reasons"], "deadline conflict missing")
    check(danube["normalized"]["raw_hash"] == danube["raw_hash"], "raw hash detached from normalized evidence")

    robg = rows["ROBG-CALL-6-2025"]
    check(robg["readback_verified"] is True, "RO-BG exact-call readback not verified")
    check(robg["normalized"]["observation_state"] != "OPEN_CALL", "expired RO-BG control became OPEN")

    roua = rows["ROUA-SECOND-SMALL-SCALE-2025"]
    check(roua["readback_verified"] is True, "RO-UA exact-call readback not verified")
    check(roua["normalized"]["observation_state"] == "REVIEW_REQUIRED", "expired launched call became OPEN")

    from interreg_call_reconcile import reconcile_live_evidence

    for row in evidence["rows"]:
        check(row["attempted_at"].endswith("Z"), "attempted_at missing from official probe")
        check(
            row["attempted_at"] <= row["fetched_at"] <= evidence["created_at"],
            "verified fetch was time-stamped before attempt or after manifest",
        )
        normalized = row["normalized"]
        check(
            normalized["fetched_at"] == row["fetched_at"],
            "normalized Interreg receipt borrowed a different fetch time",
        )
        check(normalized["publish_authorized"] is False and normalized["material_fact_use"] is False, "normalized row became authorizing")
        check(normalized["publication_effect"] == "NONE", "normalized row emitted publication effect")

    # Live TLS/HTTP failures are attempted observations, not acquired source
    # receipts. They must remain quarantined even when the other two probes PASS.
    def flaky_fetch(url):
        if "open-calls-for-proposals-call-6" in url:
            raise TimeoutError("official page unavailable")
        return fake_fetch(url)

    try:
        live._fetch = flaky_fetch
        partial = live.build_live_evidence(run_id="interreg-call-transport-failure")
    finally:
        live._fetch = original
    live.validate_envelope(partial)
    check(partial["fetch_pass"] == 2 and partial["fetch_fail"] == 1, "partial source health not counted")
    failure = next(row for row in partial["rows"] if row["fetch_status"] == "FAIL")
    check(failure["attempted_at"].endswith("Z"), "failed probe lost attempted_at")
    check(failure["fetched_at"] is None, "failed probe invented fetched_at")
    check(
        "raw_hash" not in failure and "normalized" not in failure and "final_url" not in failure,
        "failed probe invented a raw official receipt",
    )
    receipt = reconcile_live_evidence(partial)
    check(receipt["source_schema"] == live.SCHEMA, "V2 source schema detached in reconciliation")
    check(receipt["stats"]["ready_for_staging"] == 0, "failed probe became staging-ready")
    check(receipt["stats"]["review_required"] == 3, "failed probe escaped quarantine")
    quarantined_failed = next(
        item for item in receipt["quarantined_records"] if item["probe_id"] == failure["probe_id"]
    )
    check(quarantined_failed["fetched_at"] is None, "reconciliation fabricated fetch success")
    # Old immutable V1 receipts retain the original historical failed-row
    # timestamp semantics for replay; they are never silently rewritten to V2.
    legacy = json.loads(json.dumps(partial))
    legacy["schema"] = live.LEGACY_SCHEMA
    legacy["parser_version"] = "INTERREG_CALL_LIVE_FETCH_V1"
    for row in legacy["rows"]:
        row.pop("attempted_at", None)
        if row["fetch_status"] == "FAIL":
            row["fetched_at"] = legacy["created_at"]  # historical V1 shape
    live.validate_envelope(legacy)
    legacy_receipt = reconcile_live_evidence(legacy)
    check(legacy_receipt["source_schema"] == live.LEGACY_SCHEMA, "V1 replay schema lost")
    check(legacy_receipt["stats"]["ready_for_staging"] == 0, "historical V1 control became OPEN")

    for field, forged in (
        ("fetched_at", "2026-11-10T19:47:50Z"),
        ("raw_hash", "0" * 64),
        ("normalized", {"observation_state": "OPEN_CALL"}),
    ):
        tampered = json.loads(json.dumps(partial))
        failed = next(row for row in tampered["rows"] if row["fetch_status"] == "FAIL")
        failed[field] = forged
        try:
            live.validate_envelope(tampered)
        except ValueError as exc:
            check("forged a fetched receipt" in str(exc), f"{field}: wrong rejection {exc}")
        else:
            raise AssertionError(f"tampered {field} on failed exact-call probe passed validation")

    for fake_time in ("2026-11-10T22:00:00+02:00", "not-a-date", "2026-02-30T19:47:50Z"):
        tampered = json.loads(json.dumps(partial))
        tampered["rows"][0]["attempted_at"] = fake_time
        try:
            live.validate_envelope(tampered)
        except (ValueError, TypeError):
            pass
        else:
            raise AssertionError(f"invalid attempted_at admitted: {fake_time}")
    print("PASS Interreg exact-call live evidence stays bounded and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
