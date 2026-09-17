#!/usr/bin/env python3
from __future__ import annotations

from eea_civil_society_fund_call4_exact import EXACT_URL, INDEX_URL, collect_exact

INDEX_HTML = f"""
<html><body><h1>Calls</h1>
<h2>Apel #4 Promovarea diversității, a egalității și combaterea violenței bazate pe gen</h2>
<a href="{EXACT_URL}">Detalii apel #4</a>
</body></html>
""".encode("utf-8")

DETAIL_HTML = """
<html><body>
<h1>Apel #4 Promovarea diversitatii, a egalitatii si combaterea violentei bazate pe gen</h1>
<p>EEA Civil Society Fund in Romania</p>
<p>Apeluri de proiecte</p><p>Deschis</p>
<p>Numarul Apelului de proiecte</p><p>4</p>
<p>Data publicarii</p><p>08/07/2026</p>
<p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
<p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
<p>Suma disponibila</p><p>€4,478,018</p>
<p>Valoarea minima a grantului</p><p>€100,000</p>
<p>Valoarea maxima a grantului</p><p>€350,000</p>
</body></html>
""".encode("utf-8")


def healthy_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        return DETAIL_HTML, 200, url, "text/html; charset=UTF-8"
    raise AssertionError(url)


def redirected_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        return DETAIL_HTML, 200, "https://example.org/not-authority", "text/html; charset=UTF-8"
    raise AssertionError(url)


def unrelated_open_fetch(url: str, *, timeout: float):
    del timeout
    if url == INDEX_URL:
        return INDEX_HTML, 200, url, "text/html; charset=UTF-8"
    if url == EXACT_URL:
        raw = DETAIL_HTML.replace(b"<p>Apeluri de proiecte</p><p>Deschis</p>", b"<p>Un alt program este deschis</p>")
        return raw, 200, url, "text/html; charset=UTF-8"
    raise AssertionError(url)


def main() -> int:
    evidence = collect_exact(
        run_id="call4-test",
        fetched_at="2026-09-07T05:00:00+00:00",
        fetcher=healthy_fetch,
    )
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["official_call_identifier"] == "4"
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["deadline_candidate"] == "2026-10-08"
    assert evidence["budget_candidate"] == "EUR 4,478,018"
    assert evidence["grant_min_candidate"] == "EUR 100,000"
    assert evidence["grant_max_candidate"] == "EUR 350,000"
    assert evidence["open_call_authorized"] is False
    assert evidence["publication_effect"] == "NONE"

    redirected = collect_exact(
        run_id="redirect-test",
        fetched_at="2026-09-07T05:01:00+00:00",
        fetcher=redirected_fetch,
    )
    assert redirected["source_health_state"] == "DEGRADED"
    assert redirected["candidate_state"] == "UNKNOWN"
    assert redirected["lkg_required"] is True
    assert redirected["open_call_authorized"] is False

    unrelated = collect_exact(
        run_id="lexical-test",
        fetched_at="2026-09-07T05:02:00+00:00",
        fetcher=unrelated_open_fetch,
    )
    assert unrelated["source_health_state"] == "HEALTHY"
    assert unrelated["candidate_state"] == "UNKNOWN"
    assert unrelated["open_call_authorized"] is False

    print({
        "status": "PASS",
        "adapter": "EEA_CSF_RO_CALL4_EXACT",
        "official_call_identifier": evidence["official_call_identifier"],
        "candidate_state": evidence["candidate_state"],
        "redirect_drift_fails_closed": True,
        "unrelated_open_text_does_not_set_status": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
