#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_digital_ft_exact import ExactDigitalConflict, collect_exact, select_digital_candidate, validate_evidence

REF = "DIGITAL-2026-AI-DATA-10-COMPLIANCE"
PROGRAMME_CODE = "43152860"
STATUS_CODE = "31094501"
PROGRAMME_LABEL = "Digital Europe Programme (DIGITAL)"


def facet_payload():
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
        ]
    }


def search_payload(deadline="2027-03-03T17:00:00Z"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": "DIGITAL-2026-AI-DATA-10",
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic Digital Europe topic",
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
    taxonomy = {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": [
            {"identifier": "DIGITAL-2026-BESTUSE-10-EHDS", "programme_family_normalized": "DIGITAL_EUROPE", "status_label_candidate": "Forthcoming", "taxonomy_fingerprint": "1" * 64, "source_semantic_fingerprint": "2" * 64, "authority_url_candidate": ft.topic_url("DIGITAL-2026-BESTUSE-10-EHDS")},
            {"identifier": REF, "programme_family_normalized": "DIGITAL_EUROPE", "status_label_candidate": "Open", "taxonomy_fingerprint": "3" * 64, "source_semantic_fingerprint": "4" * 64, "authority_url_candidate": ft.topic_url(REF)},
        ],
    }
    selected = select_digital_candidate(taxonomy)
    assert selected["identifier"] == REF

    evidence = collect_exact(
        REF,
        run_id="synthetic",
        fetched_at="2026-09-01T20:10:00+00:00",
        source_candidate=selected,
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_family"] == "DIGITAL_EUROPE"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["publish_authorized"] is False

    bad_facet = facet_payload()
    bad_facet["facets"][0]["values"][0]["value"] = "Horizon Europe"
    try:
        collect_exact(REF, run_id="bad-programme", fetched_at="2026-09-01T20:10:00+00:00", post_func=make_post(facet=bad_facet), topic_func=topic)
        raise AssertionError("non-Digital programme label was accepted")
    except ValueError as exc:
        assert "not proven to belong to Digital Europe" in str(exc)

    conflict_rows = search_payload("2027-03-03T17:00:00Z") + search_payload("2027-04-01T17:00:00Z")
    try:
        collect_exact(REF, run_id="conflict", fetched_at="2026-09-01T20:10:00+00:00", post_func=make_post(search=conflict_rows), topic_func=topic)
        raise AssertionError("materially conflicting exact Digital Europe rows were accepted")
    except ExactDigitalConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
        raise AssertionError("self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_digital_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
