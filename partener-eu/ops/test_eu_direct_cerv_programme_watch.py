#!/usr/bin/env python3
from __future__ import annotations

import copy

from eu_direct_cerv_programme_watch import (
    NCP_URL,
    PROGRAMME_OVERVIEW_URL,
    build_receipt,
    collect,
    validate_receipt,
)

OVERVIEW = b"""
<html><body>
<h1>Citizens, Equality, Rights and Values programme overview</h1>
<p>This programme supports civil society organisations active at local, regional,
national and transnational level.</p>
<p>Visit the Funding and Tenders portal for proposal calls.</p>
<a href="/files/cerv-indicative-planning-2026.pdf">CERV Indicative Planning 2026</a>
<a href="https://commission.europa.eu/files/cerv-work-programme-2026-2027.pdf">
CERV Work Programme 2026-2027</a>
</body></html>
"""

NCP = b"""
<html><body>
<h1>CERV National Contact Points</h1>
<table><tr><td>Romania</td><td>Ministry of Culture of Romania</td></tr></table>
</body></html>
"""


def fake_fetch(url: str):
    if url == PROGRAMME_OVERVIEW_URL:
        raw = OVERVIEW
    elif url == NCP_URL:
        raw = NCP
    else:
        raise AssertionError(url)
    return raw, {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def expect_failure(callable_, needle: str) -> None:
    try:
        callable_()
    except ValueError as exc:
        assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else:
        raise AssertionError(f"expected ValueError containing {needle!r}")


def main() -> int:
    receipt, raw = collect(
        run_id="synthetic-1",
        fetched_at="2026-09-02T00:00:00+00:00",
        fetcher=fake_fetch,
    )
    assert receipt["schema"] == "PARTENER_EU_CERV_PROGRAMME_WATCH_V1"
    assert receipt["source_family"] == "EU_DIRECT"
    assert receipt["programme_family"] == "CERV"
    assert receipt["source_health"] == "HEALTHY"
    assert receipt["market_intelligence_only"] is True
    assert receipt["open_call_authorized"] is False
    assert receipt["eligibility_authorized"] is False
    assert receipt["publication_effect"] == "NONE"
    assert receipt["programme_fit_evidence"]["facts"]["fit_state"] == (
        "ROMANIA_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING"
    )
    assert [row["observation_state"] for row in receipt["programming_observations"]] == [
        "PLANNED",
        "PROGRAMMING",
    ]
    assert all(
        row["open_call_authorized"] is False
        for row in receipt["programming_observations"]
    )
    assert sorted(raw) == [
        "cerv-national-contact-points.html",
        "cerv-programme-overview.html",
    ]
    validate_receipt(receipt)

    tampered = copy.deepcopy(receipt)
    tampered["open_call_authorized"] = True
    expect_failure(lambda: validate_receipt(tampered), "attempted authorization")

    tampered = copy.deepcopy(receipt)
    tampered["programming_observations"][0]["observation_state"] = "OPEN_CALL"
    expect_failure(lambda: validate_receipt(tampered), "may not authorize calls")

    tampered = copy.deepcopy(receipt)
    tampered["programme_fit_evidence"]["facts"]["fit_state"] = "ELIGIBLE"
    expect_failure(lambda: validate_receipt(tampered), "semantic fingerprint mismatch")

    bad_ncp = NCP.replace(b"Romania", b"Country")
    expect_failure(
        lambda: build_receipt(
            overview_raw=OVERVIEW,
            overview_meta=fake_fetch(PROGRAMME_OVERVIEW_URL)[1],
            ncp_raw=bad_ncp,
            ncp_meta=fake_fetch(NCP_URL)[1],
            fetched_at="2026-09-02T00:00:00+00:00",
            run_id="synthetic-2",
        ),
        "missing required official semantic anchors",
    )

    print("CERV programme watch fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
