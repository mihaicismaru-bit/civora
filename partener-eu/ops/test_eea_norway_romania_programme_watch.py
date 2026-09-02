#!/usr/bin/env python3
from __future__ import annotations

import copy

from eea_norway_romania_programme_watch import (
    CIVIL_SOCIETY_CALLS_URL,
    EEA_MOU_URL,
    NFP_DIRECTORY_URL,
    NORWAY_MOU_URL,
    ROMANIA_COOPERATION_URL,
    collect,
    validate_receipt,
)

COOPERATION = b"""
<html><body>
<h1>Renewed cooperation with Romania</h1>
<p>Iceland, Liechtenstein and Norway signed Memoranda under the EEA and Norway Grants 2021\xe2\x80\x932028.</p>
<p>The Donor States agreed nine programmes in Romania.</p>
<h2>Programmes 2021-2028</h2>
<p>EEA Civil Society Fund Romania</p>
<h4>Green Transition</h4><p>Programme Operator: Ministry of Environment, Water and Forestry</p>
<h4>Clean Energy Transition</h4><p>Programme Operator: The Financial Mechanism Office</p>
<h4>Local Development</h4><p>Programme Operator: Romanian Social Development Fund</p>
<h4>Research and Innovation</h4><p>Programme Operator: Executive Agency for Higher Education, Research, Development and Innovation Funding</p>
<h4>Green Business and Innovation</h4><p>Programme Operator: The Financial Mechanism Office</p>
<h4>Culture</h4><p>Programme Operator: Ministry of Culture</p>
<h4>Justice</h4><p>Programme Operator: Ministry of Justice</p>
<h4>Home Affairs</h4><p>Programme Operator: Ministry of Internal Affairs</p>
<h4>Institutional Cooperation and Capacity Building</h4><p>Programme Operator: Ministry of Investments and European Projects</p>
</body></html>
"""
EEA_MOU = b"<html><body><h1>MoU Romania 2021-2028 EEA</h1><p>2021-2028</p></body></html>"
NORWAY_MOU = b"<html><body><h1>MoU Romania 2021-2028 Norway</h1><p>2021-2028</p></body></html>"
NFP = b"""
<html><body><h1>National Focal Points</h1>
<p>The National Focal Points serve as the main contact institutions for the EEA and Norway Grants.</p>
<p>Contact details are available under the 2021\xe2\x80\x932028 funding period.</p>
<h3>Poland</h3>
</body></html>
"""
CALLS = b"""
<html><body><h1>Calls</h1><p>Call for projects</p>
<a href="/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy">Call #1 Strengthening Democracy</a>
<a href="https://eeagrants.org/en/eea-civil-society-fund-romania/calls/call-2-civic-participation">Call #2 Civic Participation</a>
</body></html>
"""


def fake_fetch(url: str):
    bodies = {
        ROMANIA_COOPERATION_URL: COOPERATION,
        EEA_MOU_URL: EEA_MOU,
        NORWAY_MOU_URL: NORWAY_MOU,
        NFP_DIRECTORY_URL: NFP,
        CIVIL_SOCIETY_CALLS_URL: CALLS,
    }
    raw = bodies[url]
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
        run_id="synthetic-eea-1",
        fetched_at="2026-09-02T03:00:00+00:00",
        fetcher=fake_fetch,
    )
    assert receipt["schema"] == "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1"
    assert receipt["source_family"] == "EEA_NORWAY"
    assert receipt["programme_family"] == "EEA_NORWAY_ROMANIA_2021_2028"
    assert receipt["source_health"] == "HEALTHY"
    assert receipt["market_intelligence_only"] is True
    assert receipt["open_call_authorized"] is False
    assert receipt["deadline_authorized"] is False
    assert receipt["budget_authorized"] is False
    assert receipt["eligibility_authorized"] is False
    assert receipt["publication_effect"] == "NONE"
    assert len(receipt["programmes"]) == 9
    assert len(receipt["call_discovery"]) == 2
    assert receipt["programme_fit_evidence"]["facts"]["fit_state"] == (
        "ROMANIA_BENEFICIARY_STATE_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING"
    )
    assert receipt["national_focal_point_observation"]["state"] == (
        "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY"
    )
    assert all(row["observation_state"] == "PROGRAMMING" for row in receipt["programmes"])
    assert all(row["observation_state"] == "CALL_DISCOVERY_ONLY" for row in receipt["call_discovery"])
    assert sorted(raw) == [
        "civil-society-calls",
        "eea-mou",
        "nfp-directory",
        "norway-mou",
        "romania-cooperation",
    ]
    validate_receipt(receipt)

    tampered = copy.deepcopy(receipt)
    tampered["open_call_authorized"] = True
    expect_failure(lambda: validate_receipt(tampered), "attempted authorization")

    tampered = copy.deepcopy(receipt)
    tampered["programming_observations"][0]["observation_state"] = "OPEN_CALL"
    expect_failure(lambda: validate_receipt(tampered), "escaped PROGRAMMING")

    tampered = copy.deepcopy(receipt)
    tampered["call_discovery"][0]["open_call_authorized"] = True
    expect_failure(lambda: validate_receipt(tampered), "attempted authorization")

    tampered = copy.deepcopy(receipt)
    tampered["programme_fit_evidence"]["facts"]["fit_state"] = "ELIGIBLE_APPLICANT"
    expect_failure(lambda: validate_receipt(tampered), "semantic fingerprint mismatch")

    tampered = copy.deepcopy(receipt)
    tampered["call_discovery"][0]["url"] = "https://example.com/call-1"
    expect_failure(lambda: validate_receipt(tampered), "left official call surface")

    print("EEA/Norway Romania programme watch fail-closed regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
