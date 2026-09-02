#!/usr/bin/env python3
from __future__ import annotations

import copy
from eea_norway_romania_programme_watch import (
    CIVIL_SOCIETY_CALLS_URL, EEA_MOU_URL, NFP_DIRECTORY_URL, NORWAY_MOU_URL,
    ROMANIA_COOPERATION_URL, collect, validate_receipt,
)

COOPERATION = b"""<html><body><h1>Renewed cooperation with Romania</h1>
<p>EEA and Norway Grants 2021\xe2\x80\x932028. The Donor States agreed nine programmes in Romania.</p>
<h2>Programmes 2021-2028</h2><p>EEA Civil Society Fund Romania</p>
<p>Green Transition - Programme Operator: Ministry of Environment, Water and Forestry</p>
<p>Clean Energy Transition - Programme Operator: The Financial Mechanism Office</p>
<p>Local Development - Programme Operator: Romanian Social Development Fund</p>
<p>Research and Innovation - Programme Operator: Executive Agency for Higher Education, Research, Development and Innovation Funding</p>
<p>Green Business and Innovation - Programme Operator: The Financial Mechanism Office</p>
<p>Culture - Programme Operator: Ministry of Culture</p>
<p>Justice - Programme Operator: Ministry of Justice</p>
<p>Home Affairs - Programme Operator: Ministry of Internal Affairs</p>
<p>Institutional Cooperation and Capacity Building - Programme Operator: Ministry of Investments and European Projects</p>
</body></html>"""
EEA_MOU = b"<html><body>MoU Romania 2021-2028 EEA 2021-2028</body></html>"
NORWAY_MOU = b"<html><body>MoU Romania 2021-2028 Norway 2021-2028</body></html>"
NFP = b"<html><body><h1>National Focal Points</h1><p>The National Focal Points serve as the main contact institutions for the EEA and Norway Grants.</p><p>2021\xe2\x80\x932028 funding period</p><h3>Poland</h3></body></html>"
CALLS = b"""<html><body><h1>Calls</h1><p>Call for projects</p>
<a href="/en/eea-civil-society-fund-romania/calls/call-1-strengthening-democracy">Call #1 Strengthening Democracy</a>
<a href="/en/eea-civil-society-fund-romania/calls/call-2-civic-participation">Call #2 Civic Participation</a>
<a href="/en/eea-civil-society-fund-romania/calls/faqs">FAQs</a>
</body></html>"""


def fake_fetch(url: str):
    raw = {ROMANIA_COOPERATION_URL:COOPERATION, EEA_MOU_URL:EEA_MOU, NORWAY_MOU_URL:NORWAY_MOU, NFP_DIRECTORY_URL:NFP, CIVIL_SOCIETY_CALLS_URL:CALLS}[url]
    return raw, {"requested_url":url,"final_url":url,"status":200,"content_type":"text/html"}


def fail(fn, needle: str) -> None:
    try: fn()
    except ValueError as exc: assert needle.casefold() in str(exc).casefold(), (needle, str(exc))
    else: raise AssertionError(f"expected ValueError containing {needle!r}")


def main() -> int:
    r, raw = collect(run_id="synthetic-eea-1", fetched_at="2026-09-02T03:00:00+00:00", fetcher=fake_fetch)
    assert r["schema"] == "PARTENER_EU_EEA_NORWAY_ROMANIA_PROGRAMME_WATCH_V1"
    assert r["source_family"] == "EEA_NORWAY" and r["programme_family"] == "EEA_NORWAY_ROMANIA_2021_2028"
    assert r["source_health"] == "HEALTHY" and r["market_intelligence_only"] is True
    assert len(r["programmes"]) == 9 and len(r["call_discovery"]) == 2
    assert all("faqs" not in x["url"] for x in r["call_discovery"])
    assert r["national_focal_point_observation"]["state"] == "ROMANIA_NOT_YET_PRESENT_IN_CURRENT_FMO_NFP_DIRECTORY"
    assert r["programme_fit_evidence"]["facts"]["fit_state"] == "ROMANIA_BENEFICIARY_STATE_PROGRAMME_LEVEL_FIT_DEMONSTRATED_NON_AUTHORIZING"
    assert all(r[k] is False for k in ("open_call_authorized","deadline_authorized","budget_authorized","eligibility_authorized","publish_authorized","distribution_authorized","call_alert_authorized"))
    assert sorted(raw) == ["civil-society-calls","eea-mou","nfp-directory","norway-mou","romania-cooperation"]
    validate_receipt(r)

    t=copy.deepcopy(r); t["open_call_authorized"]=True; fail(lambda:validate_receipt(t),"attempted authorization")
    t=copy.deepcopy(r); t["programming_observations"][0]["observation_state"]="OPEN_CALL"; fail(lambda:validate_receipt(t),"escaped PROGRAMMING")
    t=copy.deepcopy(r); t["call_discovery"][0]["open_call_authorized"]=True; fail(lambda:validate_receipt(t),"attempted authorization")
    t=copy.deepcopy(r); t["programme_fit_evidence"]["facts"]["fit_state"]="ELIGIBLE_APPLICANT"; fail(lambda:validate_receipt(t),"semantic fingerprint mismatch")
    t=copy.deepcopy(r); t["call_discovery"][0]["url"]="https://eeagrants.org/en/eea-civil-society-fund-romania/calls/faqs"; fail(lambda:validate_receipt(t),"includes non-call page")
    print("EEA/Norway Romania programme watch fail-closed regression: PASS")
    return 0

if __name__ == "__main__": raise SystemExit(main())
