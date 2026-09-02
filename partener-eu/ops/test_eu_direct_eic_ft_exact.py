#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_eic_ft_exact import ExactEICConflict, collect_exact, validate_evidence

REF = "HORIZON-EIC-2026-PATHFINDERCHALLENGES-01-01"
PROGRAMME_CODE = "43108390"
STATUS_CODE = "31094501"
PROGRAMME_LABEL = "Horizon Europe"


def facet_payload(status="Open"):
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": status}]},
        ]
    }


def search_payload(deadline="2026-10-28T17:00:00Z"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": "HORIZON-EIC-2026-PATHFINDERCHALLENGES-01",
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic EIC Pathfinder Challenge topic",
        "deadlineDate": deadline,
    }]


def receipt(url):
    return {"url": url, "final_url": url, "http_status": 200, "content_type": "application/json", "bytes": 2, "sha256": "a" * 64}


def make_post(search=None, facet=None):
    search = search if search is not None else search_payload()
    facet = facet if facet is not None else facet_payload()

    def post(endpoint, **kwargs):
        if endpoint == ft.SEARCH_ENDPOINT:
            return copy.deepcopy(search), b"{}", receipt(endpoint)
        if endpoint == ft.FACET_ENDPOINT:
            return copy.deepcopy(facet), b"{}", receipt(endpoint)
        raise AssertionError(endpoint)

    return post


def topic(url):
    return {"url": url, "final_url": url, "http_status": 200, "content_type": "text/html", "bytes": 10, "body_sha256": "b" * 64, "verified": True}


def main():
    evidence = collect_exact(
        REF,
        run_id="synthetic",
        fetched_at="2026-09-02T17:00:00+00:00",
        discovery_source_url="https://eic.ec.europa.eu/eic-funding-opportunities/eic-pathfinder/eic-pathfinder-challenges-2026_en",
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_family"] == "HORIZON_EUROPE_EIC"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["publish_authorized"] is False

    bad_facet = facet_payload()
    bad_facet["facets"][0]["values"][0]["value"] = "Digital Europe Programme"
    try:
        collect_exact(REF, run_id="bad-programme", fetched_at="2026-09-02T17:00:00+00:00", post_func=make_post(facet=bad_facet), topic_func=topic)
        raise AssertionError("non-Horizon programme label was accepted")
    except ValueError as exc:
        assert "not proven to belong to Horizon Europe" in str(exc)

    conflict_rows = search_payload("2026-10-28T17:00:00Z") + search_payload("2026-11-01T17:00:00Z")
    try:
        collect_exact(REF, run_id="conflict", fetched_at="2026-09-02T17:00:00+00:00", post_func=make_post(search=conflict_rows), topic_func=topic)
        raise AssertionError("materially conflicting exact EIC rows were accepted")
    except ExactEICConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
        raise AssertionError("self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    bad_discovery = copy.deepcopy(evidence)
    bad_discovery["discovery_source_url"] = "https://example.com/not-official"
    try:
        validate_evidence(bad_discovery)
        raise AssertionError("non-official discovery provenance was accepted")
    except ValueError as exc:
        assert "official EIC authority" in str(exc)

    print("eu_direct_eic_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
