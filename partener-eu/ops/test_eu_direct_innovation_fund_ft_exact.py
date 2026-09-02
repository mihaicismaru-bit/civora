#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_innovation_fund_ft_exact import ExactInnovationFundConflict, collect_exact, validate_evidence

REF = "INNOVFUND-2025-NZT-GENERAL-LSP"
CALL = "INNOVFUND-2025-NZT"
PROGRAMME_CODE = "43089234"
STATUS_CODE = "31094503"
PROGRAMME_LABEL = "Innovation Fund (INNOVFUND)"
DISCOVERY = "https://cinea.ec.europa.eu/funding-opportunities/calls-proposals/innovation-fund-2025-net-zero-technologies-call_en"


def facet_payload(status="Closed"):
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": status}]},
        ]
    }


def search_payload(deadline="2026-04-23T17:00:00Z"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": CALL,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Innovation Fund 2025 Net Zero Technologies - General decarbonisation - Large-Scale Projects",
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
        fetched_at="2026-09-02T22:00:00+00:00",
        expected_call_identifier=CALL,
        discovery_source_url=DISCOVERY,
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "CLOSED_CALL"
    assert evidence["status_label"] == "Closed"
    assert evidence["call_identifier"] == CALL
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_family"] == "INNOVATION_FUND"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["closed_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["publish_authorized"] is False

    bad_facet = facet_payload()
    bad_facet["facets"][0]["values"][0]["value"] = "Horizon Europe"
    try:
        collect_exact(REF, run_id="bad-programme", fetched_at="2026-09-02T22:00:00+00:00", expected_call_identifier=CALL, post_func=make_post(facet=bad_facet), topic_func=topic)
        raise AssertionError("non-Innovation-Fund programme label was accepted")
    except ValueError as exc:
        assert "not proven to belong to Innovation Fund" in str(exc)

    wrong_call = search_payload()
    wrong_call[0]["callIdentifier"] = "INNOVFUND-2025-WRONG"
    try:
        collect_exact(REF, run_id="bad-call", fetched_at="2026-09-02T22:00:00+00:00", expected_call_identifier=CALL, post_func=make_post(search=wrong_call), topic_func=topic)
        raise AssertionError("wrong call identity was accepted")
    except ValueError as exc:
        assert "call identity mismatch" in str(exc)

    conflict_rows = search_payload("2026-04-23T17:00:00Z") + search_payload("2026-04-24T17:00:00Z")
    try:
        collect_exact(REF, run_id="conflict", fetched_at="2026-09-02T22:00:00+00:00", expected_call_identifier=CALL, post_func=make_post(search=conflict_rows), topic_func=topic)
        raise AssertionError("materially conflicting exact Innovation Fund rows were accepted")
    except ExactInnovationFundConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["closed_call_authorized"] = True
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
        assert "official CINEA/DG CLIMA authority" in str(exc)

    print("eu_direct_innovation_fund_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
