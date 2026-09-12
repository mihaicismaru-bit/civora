#!/usr/bin/env python3
from __future__ import annotations

import copy

from eu_direct_eui_c2c_exact import (
    DEFAULT_CALL_URL, DEFAULT_GUIDANCE_URL, DEFAULT_PORTICO_URL,
    ExactC2CEvidenceError, collect_exact,
)
from eu_direct_eui_c2c_reconcile import reconcile

PAGE = b"""
<html><body>
<h1>City-to-City Exchanges</h1>
<p>The Call for Applications for City-to-City Exchanges is continuously open.</p>
<p>Applications can be submitted and approved for implementation on a rolling basis.</p>
<p>The call for applications for City-to-City Exchanges is open on a permanent basis.</p>
<p>The call is open to urban authorities from EU Member States.</p>
<p>City-to-City Exchanges support peer learning on policy challenges related to sustainable urban development.</p>
<p>The European Urban Initiative covers travel and accommodation costs, and it also offers moderation services.</p>
</body></html>
"""
PORTICO = b"""
<html><body>
European Urban Initiative
City-to-City Exchanges
Open
Deadline date : 17/11/2027
By European Urban Initiative
</body></html>
"""
PDF = b"%PDF-1.7\n" + (b"0" * 2048)


def fetcher(url: str, *, timeout: float, accept: str):
    del timeout, accept
    if url == DEFAULT_CALL_URL:
        return PAGE, 200, url, "text/html; charset=utf-8"
    if url == DEFAULT_GUIDANCE_URL:
        return PDF, 200, url, "application/pdf"
    if url == DEFAULT_PORTICO_URL:
        return PORTICO, 200, url, "text/html; charset=utf-8"
    raise AssertionError(url)


def test_authority_precedence() -> None:
    evidence = collect_exact(
        run_id="test-1", fetched_at="2026-09-07T16:00:00+00:00", fetcher=fetcher,
    )
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["candidate_state"] == "CONTINUOUS_OPPORTUNITY"
    assert evidence["deadline_candidate"] is None
    assert evidence["deadline_semantics"] == "NO_CURRENTLY_FIXED_END_DATE"
    assert evidence["official_call_identifier"] is None
    assert evidence["portico_metadata_observation"]["deadline_observed"] == "2027-11-17"
    assert evidence["authority_discrepancy"]["resolution"] == "EXACT_EUI_PAGE_AND_CURRENT_GUIDANCE_PREVAIL"
    assert evidence["open_call_authorized"] is False
    assert evidence["publish_authorized"] is False


def test_degraded_exact_authority_fails_closed() -> None:
    def bad_fetcher(url: str, *, timeout: float, accept: str):
        if url == DEFAULT_CALL_URL:
            return b"<html>City-to-City Exchanges</html>", 200, url, "text/html"
        return fetcher(url, timeout=timeout, accept=accept)
    evidence = collect_exact(
        run_id="test-2", fetched_at="2026-09-07T16:01:00+00:00", fetcher=bad_fetcher,
    )
    assert evidence["source_health_state"] == "DEGRADED"
    assert evidence["candidate_state"] == "UNKNOWN"
    assert evidence["deadline_candidate"] is None
    assert evidence["lkg_required"] is True
    assert evidence["open_call_authorized"] is False


def test_reconcile_strict_history_and_no_change() -> None:
    previous = collect_exact(
        run_id="prev", fetched_at="2026-09-07T15:00:00+00:00", fetcher=fetcher,
    )
    current = collect_exact(
        run_id="curr", fetched_at="2026-09-07T16:00:00+00:00", fetcher=fetcher,
    )
    receipt = reconcile(current, previous)
    assert receipt["reconciliation_state"] == "NO_CHANGE"
    assert receipt["semantic_change_count"] == 0
    assert receipt["material_admission_ready_for_downstream_review"] is False
    assert "official_call_or_topic_identifier" in receipt["missing_for_material_admission"]
    assert receipt["open_call_authorized"] is False
    newer = copy.deepcopy(current)
    newer["fetched_at"] = "2026-09-07T17:00:00+00:00"
    try:
        reconcile(current, newer)
    except ValueError as exc:
        assert "strictly older" in str(exc)
    else:
        raise AssertionError("newer previous evidence was accepted")


def test_authority_widening_rejected() -> None:
    try:
        collect_exact(
            run_id="test-3",
            call_url="https://example.com/capacity-building/city-to-city-exchanges/call",
            fetcher=fetcher,
        )
    except ExactC2CEvidenceError:
        pass
    else:
        raise AssertionError("authority host widening was accepted")


def main() -> int:
    test_authority_precedence()
    test_degraded_exact_authority_fails_closed()
    test_reconcile_strict_history_and_no_change()
    test_authority_widening_rejected()
    print("EUI C2C exact/reconcile regressions: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
