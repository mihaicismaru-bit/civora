#!/usr/bin/env python3
from __future__ import annotations

import sys
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

    for row in evidence["rows"]:
        normalized = row["normalized"]
        check(normalized["publish_authorized"] is False and normalized["material_fact_use"] is False, "normalized row became authorizing")
        check(normalized["publication_effect"] == "NONE", "normalized row emitted publication effect")

    print("PASS Interreg exact-call live evidence stays bounded and fail-closed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
