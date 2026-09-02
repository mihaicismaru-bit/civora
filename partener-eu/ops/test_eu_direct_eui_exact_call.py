#!/usr/bin/env python3
from __future__ import annotations

import copy
from urllib.error import URLError

from eu_direct_eui_exact_call import (
    DEFAULT_CALL_URL,
    DEFAULT_DISCOVERY_URL,
    ExactEUIEvidenceError,
    collect_exact,
    validate_evidence,
)

TOR_URL = "https://www.urban-initiative.eu/sites/default/files/2026-02/00_EN_ToR_4th%20EUI-IA%20Call%20for%20Proposals.pdf"

DISCOVERY_HTML = f"""
<html><body>
<h1>Call for Proposals</h1>
<article><h2>4th EUI Call for Innovative Actions</h2><div>Closed</div>
<a href="{DEFAULT_CALL_URL}">Find out more</a></article>
</body></html>
""".encode()

DETAIL_HTML = f"""
<html><body>
<h1>Fourth Call for Proposals EUI - Innovative Actions</h1>
<p>European Urban Initiative</p>
<p>The Call for Proposals is closed.</p>
<p>The fourth EUI-Innovative Actions (EUI-IA) Call for Proposals was launched on 25 February 2026
and closed on 15 June 2026 at 14.00 CEST with an allocated indicative budget of EUR 60 million ERDF.</p>
<a href="{TOR_URL}">Terms of References EUI-IA Call 4 (English)</a>
</body></html>
""".encode()

PDF = b"%PDF-1.7\n" + (b"EUI CALL 4 TERMS OF REFERENCE " * 80)


def fake_fetch(url: str, *, timeout: float, accept: str):
    del timeout, accept
    if url == DEFAULT_DISCOVERY_URL:
        return DISCOVERY_HTML, 200, url, "text/html; charset=UTF-8"
    if url == DEFAULT_CALL_URL:
        return DETAIL_HTML, 200, url, "text/html; charset=UTF-8"
    if url == TOR_URL:
        return PDF, 200, url, "application/pdf"
    raise AssertionError(f"unexpected URL {url}")


def main() -> int:
    evidence = collect_exact(
        run_id="synthetic-eui-exact",
        fetched_at="2026-09-03T00:01:00+00:00",
        fetcher=fake_fetch,
    )
    assert evidence["schema"] == "PARTENER_EU_EUI_EXACT_CALL_EVIDENCE_V1"
    assert evidence["source_family"] == "EU_DIRECT"
    assert evidence["programme_family"] == "EUROPEAN_URBAN_INITIATIVE"
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["lkg_required"] is False
    assert evidence["discovery_link_verified"] is True
    assert evidence["candidate_state"] == "CLOSED_CALL"
    assert evidence["status_label"] == "Closed"
    assert evidence["deadline_candidate"] == "2026-06-15T14:00:00+02:00"
    assert evidence["budget_candidate"] == "EUR 60 million ERDF provisional"
    assert evidence["official_call_identifier"] is None
    assert evidence["tor_url"] == TOR_URL
    assert len(evidence["tor_raw_sha256"]) == 64
    assert "official_call_or_topic_identifier" in evidence["missing_for_open_confirmation"]
    for key in (
        "material_fact_use", "open_call_authorized", "closed_call_authorized", "deadline_authorized",
        "budget_authorized", "eligibility_authorized", "publish_authorized", "distribution_authorized",
        "call_alert_authorized",
    ):
        assert evidence[key] is False

    tampered = copy.deepcopy(evidence)
    tampered["closed_call_authorized"] = True
    try:
        validate_evidence(tampered)
    except ExactEUIEvidenceError:
        pass
    else:
        raise AssertionError("EUI exact evidence accepted self-authorization")

    fabricated = copy.deepcopy(evidence)
    fabricated["official_call_identifier"] = "EUI-IA-CALL4-2026"
    try:
        validate_evidence(fabricated)
    except ExactEUIEvidenceError:
        pass
    else:
        raise AssertionError("EUI exact evidence accepted a fabricated formal identifier")

    try:
        collect_exact(
            run_id="bad-path",
            call_url="https://www.urban-initiative.eu/news/not-an-exact-call",
            fetcher=fake_fetch,
        )
    except ExactEUIEvidenceError:
        pass
    else:
        raise AssertionError("EUI exact adapter accepted a non-call path")

    def degraded_fetch(url: str, *, timeout: float, accept: str):
        if url == TOR_URL:
            raise URLError("synthetic ToR outage")
        return fake_fetch(url, timeout=timeout, accept=accept)

    degraded = collect_exact(
        run_id="synthetic-eui-degraded",
        fetched_at="2026-09-03T00:02:00+00:00",
        fetcher=degraded_fetch,
    )
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["lkg_required"] is True
    assert degraded["source_receipts"]["terms_of_reference"]["health_state"] == "DEGRADED_TRANSPORT"
    assert degraded["closed_call_authorized"] is False

    open_detail = DETAIL_HTML.replace(b"is closed", b"is open")
    def open_fetch(url: str, *, timeout: float, accept: str):
        if url == DEFAULT_CALL_URL:
            return open_detail, 200, url, "text/html; charset=UTF-8"
        return fake_fetch(url, timeout=timeout, accept=accept)

    opened = collect_exact(
        run_id="synthetic-eui-open",
        fetched_at="2026-09-03T00:03:00+00:00",
        fetcher=open_fetch,
    )
    assert opened["candidate_state"] == "OPEN_CALL"
    assert opened["official_call_identifier"] is None
    assert opened["open_call_authorized"] is False

    print({"status": "PASS", "adapter": "EUI_EXACT_CALL", "candidate": evidence["candidate_state"], "open_gate_identifier_present": False})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
