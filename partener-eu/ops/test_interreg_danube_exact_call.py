#!/usr/bin/env python3
from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "partener-eu" / "ingest"
sys.path.insert(0, str(INGEST))

import interreg_danube_exact_call as danube  # noqa: E402


EXACT_HTML = b"""<html><body>
<h1>Third call for proposals</h1>
<p>The 3rd CfP is open until 15 December 2025.</p>
<p>The Application Form (AF) must be submitted to the MA/JS through Jems by 15th of December, 14.00 Central European Time (CET).</p>
</body></html>"""

INDEX_HTML = b"""<html><body>
<h1>Calls for proposals</h1>
<h2>Closed calls</h2>
<div>Application deadline 15 Dec 2025 Third call for proposals</div>
</body></html>"""


def fetcher(url: str):
    if url == danube.EXACT_URL:
        raw = EXACT_HTML
    elif url == danube.INDEX_URL:
        raw = INDEX_HTML
    else:
        raise AssertionError(url)
    return raw, {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def assert_non_authorizing(obj: dict) -> None:
    for flag in danube.MATERIAL_FLAGS:
        assert obj[flag] is False, (flag, obj[flag])
    assert obj["publication_effect"] == "NONE"


def main() -> None:
    current, raw = danube.collect(
        run_id="regression-current",
        fetched_at="2026-09-02T09:00:00+00:00",
        fetcher=fetcher,
    )
    assert set(raw) == {"exact", "index"}
    assert current["schema"] == danube.SCHEMA
    assert current["call_identifier"] == "third-call-for-proposals"
    assert current["call_identifier_kind"] == "OFFICIAL_EXACT_ENDPOINT_SLUG"
    assert current["candidate_state"] == "CLOSED_CALL_CANDIDATE"
    assert current["candidate_status_label"] == "Closed calls"
    assert current["candidate_deadline_text"] == "15 December 2025, 14:00 CET"
    assert current["exact_authority_verified"] is True
    assert current["current_index_authority_verified"] is True
    assert_non_authorizing(current)

    baseline = danube.reconcile(current)
    assert baseline["schema"] == danube.RECONCILIATION_SCHEMA
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["semantic_change_count"] == 0
    assert baseline["material_admission_ready_for_downstream_review"] is False
    assert_non_authorizing(baseline)

    previous = copy.deepcopy(current)
    previous["run_id"] = "regression-previous"
    previous["fetched_at"] = "2026-09-02T08:00:00+00:00"
    same = danube.reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["material_admission_ready_for_downstream_review"] is True
    assert_non_authorizing(same)

    changed = copy.deepcopy(current)
    changed["exact_semantics"]["candidate_status_label"] = "Different official label"
    changed["exact_semantic_fingerprint"] = danube.sha256_json(changed["exact_semantics"])
    changed["candidate_status_label"] = "Different official label"
    try:
        danube.validate_evidence(changed)
    except ValueError:
        pass
    else:
        raise AssertionError("candidate lifecycle drift must fail closed")

    tampered = copy.deepcopy(current)
    tampered["closed_call_authorized"] = True
    try:
        danube.validate_evidence(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("closed-call authorization widening must fail closed")

    bad_authority = copy.deepcopy(current)
    bad_authority["exact_authority_url"] = "https://example.com/call"
    try:
        danube.validate_evidence(bad_authority)
    except ValueError:
        pass
    else:
        raise AssertionError("exact authority drift must fail closed")

    future_previous = copy.deepcopy(previous)
    future_previous["fetched_at"] = "2026-09-03T08:00:00+00:00"
    try:
        danube.reconcile(current, future_previous)
    except ValueError:
        pass
    else:
        raise AssertionError("newer previous evidence must fail closed")

    missing_index = INDEX_HTML.replace(b"Closed calls", b"Calls archive")

    def bad_fetcher(url: str):
        raw = EXACT_HTML if url == danube.EXACT_URL else missing_index
        return raw, {"requested_url": url, "final_url": url, "status": 200, "content_type": "text/html"}

    try:
        danube.collect(run_id="bad-index", fetcher=bad_fetcher)
    except ValueError:
        pass
    else:
        raise AssertionError("missing current-index closed classification must fail closed")

    print("PASS Danube exact-call V1: exact identity + current index evidence, baseline reconciliation, zero material authorization")


if __name__ == "__main__":
    main()
