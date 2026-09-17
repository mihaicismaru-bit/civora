#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_horizon_cl5_2026_09_exact import (
    CALL_IDENTIFIER,
    CINEA_URL,
    MATERIAL_FLAGS,
    collect_exact,
    validate_evidence,
)
from eu_direct_horizon_cl5_2026_09_reconcile import reconcile, validate_reconciliation

PROGRAMME_CODE = "43108390"
STATUS_OPEN = "31094501"
STATUS_CLOSED = "31094503"


def facet_payload(status_code=STATUS_OPEN, status_label="Open"):
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": "Horizon Europe"}]},
            {"name": "status", "values": [{"rawValue": status_code, "value": status_label}]},
        ]
    }


def search_payload(status_code=STATUS_OPEN, deadline="2026-09-15T17:00:00+02:00"):
    return [
        {
            "identifier": "HORIZON-CL5-2026-09-D1-01",
            "topicAbbreviation": "HORIZON-CL5-2026-09-D1-01",
            "callIdentifier": CALL_IDENTIFIER,
            "type": "1",
            "frameworkProgramme": PROGRAMME_CODE,
            "programmePeriod": "2021 - 2027",
            "status": status_code,
            "title": "Synthetic Cluster 5 topic one",
            "deadlineDate": deadline,
        },
        {
            "identifier": "HORIZON-CL5-2026-09-D2-02",
            "topicAbbreviation": "HORIZON-CL5-2026-09-D2-02",
            "callIdentifier": CALL_IDENTIFIER,
            "type": "1",
            "frameworkProgramme": PROGRAMME_CODE,
            "programmePeriod": "2021 - 2027",
            "status": status_code,
            "title": "Synthetic Cluster 5 topic two",
            "deadlineDate": deadline,
        },
    ]


def receipt(url):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "application/json",
        "bytes": 2,
        "sha256": "a" * 64,
    }


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


def cinea_html(status="Open", deadline="15 September 2026, 17:00 (CEST)"):
    return f"""<!doctype html><html><body>
    <h1>EUR 223.2 m for cross-sectoral solutions</h1>
    <div>Call for proposals</div>
    <div>Status {status}</div>
    <div>Deadline date {deadline}</div>
    <div>Funding programme Horizon Europe – the Framework Programme for Research and Innovation (2021/2027)</div>
    <div>using the call reference: {CALL_IDENTIFIER} (8 topics)</div>
    </body></html>""".encode("utf-8")


def make_cinea(status="Open"):
    raw = cinea_html(status=status)

    def fetch(url):
        assert url == CINEA_URL
        return raw, {
            "requested_url": url,
            "final_url": url,
            "http_status": 200,
            "content_type": "text/html",
            "bytes": len(raw),
            "sha256": "b" * 64,
        }

    return fetch


def broken_cinea(url):
    raise OSError("synthetic transport failure")


def main():
    baseline = collect_exact(
        run_id="synthetic-baseline",
        fetched_at="2026-09-08T02:00:00+00:00",
        post_func=make_post(),
        cinea_fetcher=make_cinea("Open"),
    )
    validate_evidence(baseline)
    assert baseline["source_health_state"] == "HEALTHY"
    assert baseline["candidate_state"] == "OPEN_CALL"
    assert baseline["status_label"] == "Open"
    assert baseline["authority_agreement_verified"] is True
    assert baseline["structured_snapshot"]["topic_count"] == 2
    assert baseline["deadline_candidate"] == "15 September 2026, 17:00 (CEST)"
    assert baseline["material_admission_ready_for_downstream_review"] is False
    assert all(baseline[key] is False for key in MATERIAL_FLAGS)
    assert baseline["publication_effect"] == "NONE"

    baseline_rec = reconcile(baseline)
    validate_reconciliation(baseline_rec)
    assert baseline_rec["reconciliation_state"] == "BASELINE_CURRENT_HEALTHY_NON_AUTHORIZING"
    assert baseline_rec["material_admission_ready_for_downstream_review"] is False

    replay = collect_exact(
        run_id="synthetic-replay",
        fetched_at="2026-09-08T02:00:02+00:00",
        post_func=make_post(),
        cinea_fetcher=make_cinea("Open"),
    )
    replay_rec = reconcile(replay, baseline)
    validate_reconciliation(replay_rec)
    assert replay_rec["reconciliation_state"] == "NO_CHANGE"
    assert replay_rec["semantic_change_count"] == 0
    assert replay_rec["previous_same_identity_restored"] is True
    assert replay_rec["previous_strictly_older"] is True
    assert replay_rec["material_admission_ready_for_downstream_review"] is True
    assert replay_rec["open_call_authorized"] is False
    assert replay_rec["deadline_authorized"] is False
    assert replay_rec["publish_authorized"] is False

    closed = collect_exact(
        run_id="synthetic-closed",
        fetched_at="2026-09-08T02:00:03+00:00",
        post_func=make_post(search=search_payload(STATUS_CLOSED), facet=facet_payload(STATUS_CLOSED, "Closed")),
        cinea_fetcher=make_cinea("Closed"),
    )
    changed = reconcile(closed, replay)
    assert changed["reconciliation_state"] == "SEMANTIC_CHANGE_REVIEW_REQUIRED"
    assert changed["semantic_change_count"] == 1
    assert changed["material_admission_ready_for_downstream_review"] is False
    assert changed["closed_call_authorized"] is False

    degraded = collect_exact(
        run_id="synthetic-degraded",
        fetched_at="2026-09-08T02:00:04+00:00",
        post_func=make_post(),
        cinea_fetcher=broken_cinea,
    )
    validate_evidence(degraded)
    assert degraded["source_health_state"] == "DEGRADED_SEMANTIC_OR_TRANSPORT"
    assert degraded["candidate_state"] == "UNKNOWN"
    assert degraded["status_label"] is None
    assert degraded["deadline_candidate"] is None
    assert degraded["lkg_required"] is True
    degraded_rec = reconcile(degraded, replay)
    assert degraded_rec["reconciliation_state"] == "CURRENT_DEGRADED_LKG_REQUIRED_NON_AUTHORIZING"
    assert degraded_rec["source_health_watch_candidate"] is True
    assert degraded_rec["lkg_is_current_truth"] is False
    assert degraded_rec["material_admission_ready_for_downstream_review"] is False

    conflict = collect_exact(
        run_id="synthetic-conflict",
        fetched_at="2026-09-08T02:00:05+00:00",
        post_func=make_post(search=search_payload(STATUS_CLOSED), facet=facet_payload(STATUS_CLOSED, "Closed")),
        cinea_fetcher=make_cinea("Open"),
    )
    assert conflict["source_health_state"] == "DEGRADED_SEMANTIC_OR_TRANSPORT"
    assert conflict["candidate_state"] == "UNKNOWN"
    assert "status disagreement" in conflict["degradation_reason"]

    tampered_previous = copy.deepcopy(replay)
    tampered_previous["open_call_authorized"] = True
    try:
        reconcile(closed, tampered_previous)
        raise AssertionError("previous authorization widening was accepted")
    except ValueError as exc:
        assert "authorization" in str(exc)

    same_time = copy.deepcopy(replay)
    same_time["fetched_at"] = closed["fetched_at"]
    try:
        reconcile(closed, same_time)
        raise AssertionError("equal-time previous evidence was accepted")
    except ValueError as exc:
        assert "strictly older" in str(exc)

    bad_programme = facet_payload()
    bad_programme["facets"][0]["values"][0]["value"] = "Digital Europe Programme"
    degraded_programme = collect_exact(
        run_id="bad-programme",
        fetched_at="2026-09-08T02:00:06+00:00",
        post_func=make_post(facet=bad_programme),
        cinea_fetcher=make_cinea("Open"),
    )
    assert degraded_programme["candidate_state"] == "UNKNOWN"
    assert degraded_programme["lkg_required"] is True

    print("eu_direct_horizon_cl5_2026_09 exact + reconcile regression: PASS")


if __name__ == "__main__":
    main()
