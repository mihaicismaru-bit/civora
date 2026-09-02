#!/usr/bin/env python3
from __future__ import annotations

import copy

from eu_direct_eui_exact_call import DEFAULT_CALL_URL, DEFAULT_DISCOVERY_URL, collect_exact
from eu_direct_eui_exact_call_reconcile import reconcile

TOR_URL = "https://www.urban-initiative.eu/sites/default/files/2026-02/00_EN_ToR_4th%20EUI-IA%20Call%20for%20Proposals.pdf"
DISCOVERY_HTML = f"<h2>4th EUI Call for Innovative Actions</h2><a href='{DEFAULT_CALL_URL}'>Find out more</a>".encode()
DETAIL_HTML = f"""
<h1>Fourth Call for Proposals EUI - Innovative Actions</h1>
<p>European Urban Initiative</p><p>The Call for Proposals is closed.</p>
<p>25 February 2026 - 15 June 2026 at 14.00 CEST - EUR 60 million ERDF</p>
<a href='{TOR_URL}'>Terms of References EUI-IA Call 4 (English)</a>
""".encode()
PDF = b"%PDF-1.7\n" + (b"TERMS OF REFERENCE " * 100)


def fake_fetch(url: str, *, timeout: float, accept: str):
    del timeout, accept
    if url == DEFAULT_DISCOVERY_URL:
        return DISCOVERY_HTML, 200, url, "text/html"
    if url == DEFAULT_CALL_URL:
        return DETAIL_HTML, 200, url, "text/html"
    if url == TOR_URL:
        return PDF, 200, url, "application/pdf"
    raise AssertionError(url)


def make(at: str):
    return collect_exact(run_id="reconcile-test", fetched_at=at, fetcher=fake_fetch)


def main() -> int:
    previous = make("2026-09-03T00:01:00+00:00")
    current = make("2026-09-03T00:02:00+00:00")

    baseline = reconcile(previous)
    assert baseline["reconciliation_state"] == "BASELINE_CAPTURED_NON_AUTHORIZING"
    assert baseline["material_admission_ready_for_downstream_review"] is True
    assert baseline["closed_call_authorized"] is False
    assert "field_scoped_material_admission" in baseline["missing_for_material_admission"]

    same = reconcile(current, previous)
    assert same["reconciliation_state"] == "NO_CHANGE"
    assert same["semantic_change_count"] == 0
    assert same["material_admission_ready_for_downstream_review"] is True
    assert same["closed_call_authorized"] is False

    changed = copy.deepcopy(current)
    changed["fetched_at"] = "2026-09-03T00:03:00+00:00"
    changed["exact_semantics"] = dict(changed["exact_semantics"])
    changed["exact_semantics"]["deadline_candidate"] = "2026-06-16"
    from eu_direct_eui_exact_call import sha256_json
    changed["deadline_candidate"] = "2026-06-16"
    changed["exact_semantic_fingerprint"] = sha256_json(changed["exact_semantics"])
    diff = reconcile(changed, current)
    assert diff["reconciliation_state"] == "EUI_EXACT_CALL_SEMANTIC_CHANGE_RECONCILED_NON_AUTHORIZING"
    assert diff["semantic_change_count"] == 1
    assert diff["deadline_authorized"] is False

    try:
        reconcile(previous, current)
    except ValueError as exc:
        assert "newer than current" in str(exc)
    else:
        raise AssertionError("EUI reconciliation accepted inverted history")

    open_current = copy.deepcopy(current)
    open_current["candidate_state"] = "OPEN_CALL"
    open_current["status_label"] = "Open"
    open_current["exact_semantics"] = dict(open_current["exact_semantics"])
    open_current["exact_semantics"]["candidate_state"] = "OPEN_CALL"
    open_current["exact_semantics"]["status_label"] = "Open"
    open_current["exact_semantic_fingerprint"] = sha256_json(open_current["exact_semantics"])
    open_gate = reconcile(open_current)
    assert open_gate["material_admission_ready_for_downstream_review"] is False
    assert "official_call_or_topic_identifier" in open_gate["missing_for_material_admission"]
    assert open_gate["open_call_authorized"] is False

    print({"status": "PASS", "reconciler": "EUI_EXACT_CALL", "same_identity": "NO_CHANGE", "open_without_identifier_review_ready": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
