#!/usr/bin/env python3
from __future__ import annotations

import copy
from urllib.error import URLError

from eea_civil_society_fund_call5_exact import (
    EXACT_URL,
    INDEX_URL,
    ExactCSFCall5Error,
    collect_exact,
    validate_evidence,
)

INDEX_HTML = f"""
<html><body>
<h1>Calls</h1>
<article>
<h2>Apel #5 Incluziunea și creșterea capacității romilor prin dezvoltarea comunităților interetnice</h2>
<p>Apeluri de proiecte</p><p>Deschis</p>
<a href="{EXACT_URL}">Detalii apel #5</a>
</article>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><body>
<h1>Apel #5 Incluziunea si cresterea capacitatii romilor prin dezvoltarea comunitatilor interetnice</h1>
<p>EEA Civil Society Fund in Romania</p>
<p>Apeluri de proiecte</p><p>Deschis</p>
<section><h2>Call details</h2>
<p>Numarul Apelului de proiecte</p><p>5</p>
<p>Data publicarii</p><p>08/07/2026</p>
<p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
<p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
<p>Suma disponibila</p><p>€6,500,000</p>
<p>Valoarea minima a grantului</p><p>€15,000</p>
<p>Valoarea maxima a grantului</p><p>€350,000</p>
</section>
</body></html>
""".encode("utf-8")


def fake_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        return DETAIL_HTML, 200, url, "text/html; charset=UTF-8"
    raise AssertionError(f"unexpected URL {url}")


def main() -> int:
    evidence = collect_exact(
        run_id="synthetic-eea-csf-call5",
        fetched_at="2026-09-03T03:30:00+00:00",
        fetcher=fake_fetch,
    )
    assert evidence["schema"] == "PARTENER_EU_EEA_CSF_RO_CALL5_EXACT_EVIDENCE_V1"
    assert evidence["source_family"] == "EEA_NORWAY"
    assert evidence["programme_family"] == "EEA_CIVIL_SOCIETY_FUND_ROMANIA"
    assert evidence["official_call_identifier"] == "5"
    assert evidence["call_identifier_kind"] == "OFFICIAL_CALL_NUMBER"
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["lkg_required"] is False
    assert evidence["discovery_link_verified"] is True
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["deadline_candidate"] == "2026-10-08"
    assert evidence["budget_candidate"] == "EUR 6,500,000"
    assert evidence["grant_min_candidate"] == "EUR 15,000"
    assert evidence["grant_max_candidate"] == "EUR 350,000"
    for key in (
        "material_fact_use", "open_call_authorized", "closed_call_authorized", "deadline_authorized",
        "budget_authorized", "eligibility_authorized", "publish_authorized", "distribution_authorized",
        "call_alert_authorized",
    ):
        assert evidence[key] is False

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
    except ExactCSFCall5Error:
        pass
    else:
        raise AssertionError("EEA CSF exact evidence accepted self-authorization")

    wrong_call = copy.deepcopy(evidence)
    wrong_call["official_call_identifier"] = "6"
    try:
        validate_evidence(wrong_call)
    except ExactCSFCall5Error:
        pass
    else:
        raise AssertionError("EEA CSF exact evidence accepted call-number drift")

    ambiguous_detail = DETAIL_HTML.replace(
        b"<p>Apeluri de proiecte</p><p>Deschis</p>",
        b"<p>Biroul de asistenta este deschis de luni pana vineri.</p>",
    )

    def ambiguous_fetch(url: str, *, timeout: float):
        if url == EXACT_URL:
            return ambiguous_detail, 200, url, "text/html; charset=UTF-8"
        return fake_fetch(url, timeout=timeout)

    ambiguous = collect_exact(
        run_id="synthetic-eea-csf-ambiguous-open",
        fetched_at="2026-09-03T03:31:00+00:00",
        fetcher=ambiguous_fetch,
    )
    assert ambiguous["source_health_state"] == "HEALTHY"
    assert ambiguous["candidate_state"] == "UNKNOWN"
    assert ambiguous["open_call_authorized"] is False

    def degraded_fetch(url: str, *, timeout: float):
        if url == EXACT_URL:
            raise URLError("synthetic exact detail outage")
        return fake_fetch(url, timeout=timeout)

    degraded = collect_exact(
        run_id="synthetic-eea-csf-degraded",
        fetched_at="2026-09-03T03:32:00+00:00",
        fetcher=degraded_fetch,
    )
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["lkg_required"] is True
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["open_call_authorized"] is False

    try:
        from eea_civil_society_fund_call5_exact import _validate_url
        _validate_url("https://example.com/ro/eea-civil-society-fund-romania/calls", exact=False)
    except ExactCSFCall5Error:
        pass
    else:
        raise AssertionError("EEA CSF exact adapter accepted a non-official host")

    print({
        "status": "PASS",
        "adapter": "EEA_CSF_RO_CALL5_EXACT",
        "official_call_identifier": evidence["official_call_identifier"],
        "candidate_state": evidence["candidate_state"],
        "unrelated_open_text_does_not_set_status": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
