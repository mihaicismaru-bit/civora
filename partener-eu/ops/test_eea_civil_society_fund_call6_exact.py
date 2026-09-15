#!/usr/bin/env python3
from __future__ import annotations

from urllib.error import URLError

from eea_civil_society_fund_call6_exact import EXACT_URL, INDEX_URL, collect_exact

INDEX_HTML = f"""
<html><body><h1>Calls</h1>
<h2>Apel #6 Protejarea drepturilor omului prin acțiuni climatice și de mediu</h2>
<a href="{EXACT_URL}">Detalii apel #6</a>
</body></html>
""".encode("utf-8")
DETAIL_HTML = """
<html><body>
<h1>Apel #6 Protejarea drepturilor omului prin actiuni climatice si de mediu</h1>
<p>EEA Civil Society Fund in Romania</p>
<p>Apeluri de proiecte</p><p>Deschis</p>
<p>Numarul Apelului de proiecte</p><p>6</p>
<p>Data publicarii</p><p>08/07/2026</p>
<p>Data limita pentru adresarea de intrebari</p><p>29/09/2026</p>
<p>Data limita de depunere a Cererilor de finantare</p><p>08/10/2026</p>
<p>Suma disponibila</p><p>€6,000,000</p>
<p>Valoarea minima a grantului</p><p>€15,000</p>
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


def redirect_fetch(url: str, *, timeout: float):
    raw, status, _, ctype = healthy_fetch(url, timeout=timeout)
    if url == EXACT_URL:
        return raw, status, "https://example.com/not-authority", ctype
    return raw, status, url, ctype


def degraded_fetch(url: str, *, timeout: float):
    if url == EXACT_URL:
        raise URLError("synthetic exact authority outage")
    return healthy_fetch(url, timeout=timeout)


def main() -> int:
    current = collect_exact(run_id="test-call6", fetched_at="2026-09-07T04:40:00+00:00", fetcher=healthy_fetch)
    assert current["source_health_state"] == "HEALTHY"
    assert current["official_call_identifier"] == "6"
    assert current["candidate_state"] == "OPEN_CALL"
    assert current["status_label"] == "Open"
    assert current["deadline_candidate"] == "2026-10-08"
    assert current["budget_candidate"] == "EUR 6,000,000"
    assert current["grant_min_candidate"] == "EUR 15,000"
    assert current["grant_max_candidate"] == "EUR 350,000"
    assert current["open_call_authorized"] is False
    assert current["publication_effect"] == "NONE"

    redirected = collect_exact(run_id="redirect", fetched_at="2026-09-07T04:41:00+00:00", fetcher=redirect_fetch)
    assert redirected["source_health_state"] == "DEGRADED"
    assert redirected["candidate_state"] == "UNKNOWN"
    assert redirected["lkg_required"] is True
    assert redirected["open_call_authorized"] is False

    degraded = collect_exact(run_id="outage", fetched_at="2026-09-07T04:42:00+00:00", fetcher=degraded_fetch)
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["deadline_candidate"] is None
    assert degraded["budget_candidate"] is None
    assert degraded["lkg_required"] is True

    print({
        "status": "PASS",
        "adapter": "EEA_CSF_RO_CALL6_EXACT",
        "official_call_identifier": "6",
        "candidate_state": current["candidate_state"],
        "redirect_drift_fails_closed": True,
        "transport_outage_fails_closed": True,
        "material_authorization": False,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
