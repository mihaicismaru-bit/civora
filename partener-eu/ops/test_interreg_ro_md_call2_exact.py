#!/usr/bin/env python3
from __future__ import annotations

import copy

from interreg_ro_md_call2_exact import (
    EXACT_URL,
    INDEX_URL,
    MATERIAL_FLAGS,
    collect,
    reconcile,
    sha256_json,
)

EXACT_HTML = b"""<!doctype html><html><body>
<h1>Guidelines for Applicants - Small scale projects - Call 2</h1>
<p>The Managing Authority for Interreg NEXT Romania-Republic of Moldova Programme is launching the 2nd call for proposals for small scale projects.</p>
<p>The deadline for application is July 21, 2025, 14:00 CET (Romanian time).</p>
<p>The electronic system used for application (JEMS) can be accessed here.</p>
</body></html>"""
INDEX_HTML = b"""<!doctype html><html><body>
<h1>Calls for proposals</h1>
<p>Interreg NEXT Romania-Republic of Moldova Programme</p>
<h2>Guidelines for Applicants - Small scale projects - Call 2</h2>
</body></html>"""


def healthy_fetch(url: str):
    if url == EXACT_URL:
        raw = EXACT_HTML
    elif url == INDEX_URL:
        raw = INDEX_HTML
    else:
        raise AssertionError(url)
    return raw, {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def degraded_fetch(url: str):
    if url == INDEX_URL:
        raise OSError("synthetic current index failure")
    return healthy_fetch(url)


def main() -> int:
    previous, _ = collect(
        run_id="synthetic-previous",
        fetched_at="2026-09-07T18:00:00+00:00",
        fetcher=healthy_fetch,
    )
    current, _ = collect(
        run_id="synthetic-current",
        fetched_at="2026-09-07T18:05:00+00:00",
        fetcher=healthy_fetch,
    )
    assert current["source_health_state"] == "HEALTHY"
    assert current["official_call_identifier"] == "2"
    assert current["candidate_state"] == "CALL_WINDOW_EXPIRED_CANDIDATE"
    assert current["candidate_deadline_text"] == "July 21, 2025, 14:00 CET (Romanian time)"
    assert current["deadline_interpretation"] == "RAW_OFFICIAL_TEXT_ONLY_NO_TIMEZONE_NORMALIZATION"
    assert all(current[flag] is False for flag in MATERIAL_FLAGS)

    baseline = reconcile(previous, None)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is False

    replay = reconcile(current, previous)
    assert replay["reconciliation_state"] == "NO_CHANGE"
    assert replay["semantic_change_count"] == 0
    assert replay["material_admission_ready_for_downstream_review"] is True
    assert replay["lkg_is_current_truth"] is False
    assert all(replay[flag] is False for flag in MATERIAL_FLAGS)

    changed = copy.deepcopy(current)
    changed["fetched_at"] = "2026-09-07T18:10:00+00:00"
    changed["exact_semantics"]["call_title"] = "Synthetic changed exact title"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    changed_rec = reconcile(changed, current)
    assert changed_rec["reconciliation_state"] == "RO_MD_CALL2_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert changed_rec["semantic_change_count"] == 1
    assert changed_rec["open_call_authorized"] is False

    degraded, _ = collect(
        run_id="synthetic-degraded",
        fetched_at="2026-09-07T18:15:00+00:00",
        fetcher=degraded_fetch,
    )
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["candidate_deadline_text"] is None
    assert degraded["lkg_required"] is True
    degraded_rec = reconcile(degraded, current)
    assert degraded_rec["reconciliation_state"] == "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False
    assert degraded_rec["lkg_is_current_truth"] is False

    equal = copy.deepcopy(current)
    equal["fetched_at"] = previous["fetched_at"]
    try:
        reconcile(equal, previous)
    except ValueError as exc:
        assert "strictly older" in str(exc)
    else:
        raise AssertionError("equal-time previous evidence was accepted")

    widened = copy.deepcopy(previous)
    widened["open_call_authorized"] = True
    try:
        reconcile(current, widened)
    except ValueError:
        pass
    else:
        raise AssertionError("authorization-widened previous evidence was accepted")

    authority_drift = copy.deepcopy(current)
    authority_drift["exact_authority_url"] = "https://example.invalid/call-2"
    try:
        reconcile(authority_drift, previous)
    except ValueError:
        pass
    else:
        raise AssertionError("authority drift was accepted")

    print({
        "healthy_identity": current["official_call_identifier"],
        "candidate_state": current["candidate_state"],
        "same_identity_replay": replay["reconciliation_state"],
        "semantic_change_non_authorizing": changed_rec["reconciliation_state"],
        "degraded_fail_closed": degraded_rec["reconciliation_state"],
        "equal_time_rejected": True,
        "previous_authorization_widening_rejected": True,
        "authority_drift_rejected": True,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
