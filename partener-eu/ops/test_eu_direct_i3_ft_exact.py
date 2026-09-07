#!/usr/bin/env python3
from __future__ import annotations
import copy
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))
import funding_tenders_fetch as ft
from eu_direct_i3_ft_exact import ExactI3Conflict, collect_exact, validate_evidence

REF = "I3-2026-INV1"
PROGRAMME_CODE = "43252474"
STATUS_CODE = "31094502"
PROGRAMME_LABEL = "Interregional Innovation Investments (I3) Instrument"
EISMEA_URL = "https://eismea.ec.europa.eu/funding-opportunities/calls-proposals/interregional-innovation-investments-strand-1-i3-2026-inv1_en"


def facet_payload():
    return {"facets": [
        {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
        {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
    ]}


def search_payload(deadline="2026-11-12T17:00:00+01:00"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": REF,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic I3 Strand 1",
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


def degraded_topic(url):
    return {"url": url, "final_url": url, "http_status": 404, "content_type": "text/html", "bytes": 0, "body_sha256": None, "verified": False, "error": "HTTPError: HTTP Error 404: Not Found"}


def eismea_open(url, *, timeout=25.0):
    assert url == EISMEA_URL
    raw = b"<html><body>Interregional Innovation Investments Strand 1 I3-2026-INV1 Status Open</body></html>"
    return raw, 200, url, "text/html; charset=UTF-8"


def eismea_closed(url, *, timeout=25.0):
    raw = b"<html><body>Interregional Innovation Investments Strand 1 I3-2026-INV1 Status Closed</body></html>"
    return raw, 200, url, "text/html; charset=UTF-8"


def eismea_marker_drift(url, *, timeout=25.0):
    raw = b"<html><body>generic page without bounded reference</body></html>"
    return raw, 200, url, "text/html; charset=UTF-8"


def main():
    evidence = collect_exact(
        REF,
        eismea_url=EISMEA_URL,
        run_id="synthetic",
        fetched_at="2026-09-06T07:30:00+00:00",
        post_func=make_post(),
        topic_func=topic,
        eismea_fetcher=eismea_open,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["programme_family"] == "I3"
    assert evidence["source_health_state"] == "HEALTHY"
    assert evidence["evidence_usable_for_reconciliation"] is True
    assert evidence["cross_authority_status_consistent"] is True
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["budget_authorized"] is False
    assert evidence["eligibility_authorized"] is False
    assert evidence["publish_authorized"] is False
    assert evidence["distribution_authorized"] is False
    assert evidence["publication_effect"] == "NONE"

    degraded = collect_exact(
        REF,
        eismea_url=EISMEA_URL,
        run_id="degraded",
        fetched_at="2026-09-06T07:31:00+00:00",
        post_func=make_post(),
        topic_func=degraded_topic,
        eismea_fetcher=eismea_open,
    )
    validate_evidence(degraded)
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["status_label"] is None
    assert degraded["deadline_candidate"] is None
    assert degraded["budget_candidate"] is None
    assert degraded["source_health_state"] == "DEGRADED_EXACT_AUTHORITY_CHAIN"
    assert degraded["lkg_required"] is True
    assert degraded["evidence_usable_for_reconciliation"] is False
    assert degraded["structured_candidate_snapshot"]["status_label"] == "Open"

    conflict = collect_exact(
        REF,
        eismea_url=EISMEA_URL,
        run_id="status-conflict",
        fetched_at="2026-09-06T07:32:00+00:00",
        post_func=make_post(),
        topic_func=topic,
        eismea_fetcher=eismea_closed,
    )
    validate_evidence(conflict)
    assert conflict["candidate_state"] == "UNKNOWN"
    assert conflict["cross_authority_status_consistent"] is False
    assert conflict["evidence_usable_for_reconciliation"] is False
    assert conflict["lkg_required"] is True

    marker_drift = collect_exact(
        REF,
        eismea_url=EISMEA_URL,
        run_id="marker-drift",
        fetched_at="2026-09-06T07:33:00+00:00",
        post_func=make_post(),
        topic_func=topic,
        eismea_fetcher=eismea_marker_drift,
    )
    validate_evidence(marker_drift)
    assert marker_drift["candidate_state"] == "UNKNOWN"
    assert marker_drift["eismea_receipt"]["health_state"] == "DEGRADED_MARKER_MISMATCH"
    assert marker_drift["lkg_required"] is True

    bad = facet_payload()
    bad["facets"][0]["values"][0]["value"] = "Single Market Programme (SMP)"
    try:
        collect_exact(
            REF,
            eismea_url=EISMEA_URL,
            run_id="wrong-programme",
            fetched_at="2026-09-06T07:34:00+00:00",
            post_func=make_post(facet=bad),
            topic_func=topic,
            eismea_fetcher=eismea_open,
        )
        raise AssertionError("wrong programme accepted")
    except ValueError as exc:
        assert "not proven to belong to I3" in str(exc)

    variant = search_payload("2026-11-12T17:00:00+01:00") + search_payload("2026-12-12T17:00:00+01:00")
    try:
        collect_exact(
            REF,
            eismea_url=EISMEA_URL,
            run_id="conflicting-records",
            fetched_at="2026-09-06T07:35:00+00:00",
            post_func=make_post(search=variant),
            topic_func=topic,
            eismea_fetcher=eismea_open,
        )
        raise AssertionError("conflicting exact records accepted")
    except ExactI3Conflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
        raise AssertionError("I3 exact evidence self-authorized OPEN")
    except ValueError:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["exact_semantics"]["status_label"] = "Closed"
    try:
        validate_evidence(tampered)
        raise AssertionError("semantic tampering accepted")
    except ValueError:
        pass

    try:
        collect_exact(
            "I3-2026",
            eismea_url=EISMEA_URL,
            run_id="bad-reference",
            post_func=make_post(),
            topic_func=topic,
            eismea_fetcher=eismea_open,
        )
        raise AssertionError("non-exact I3 reference accepted")
    except ValueError:
        pass

    print("eu_direct_i3_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
