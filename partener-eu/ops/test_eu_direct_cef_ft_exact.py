#!/usr/bin/env python3
from __future__ import annotations

import copy
import pathlib
import sys
from urllib.error import HTTPError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_cef_ft_exact import ExactCefConflict, collect_exact, select_cef_candidate, validate_evidence

REF = "CEF-T-2026-AFIFGEN-COSTS"
PROGRAMME_CODE = "43251567"
STATUS_CODE = "31094501"
PROGRAMME_LABEL = "Connecting Europe Facility (CEF)"


def facet_payload():
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
        ]
    }


def search_payload(deadline="2027-01-15T17:00:00Z"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": "CEF-T-2026-AFIFGEN",
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic CEF transport topic",
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


class FakeResponse:
    def __init__(self, url, *, status=200, content_type="text/html; charset=utf-8", body=b"topic"):
        self._url = url
        self.status = status
        self.headers = {"Content-Type": content_type}
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self._url

    def getcode(self):
        return self.status

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]


class SequenceOpener:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def open(self, req, timeout=None):
        self.calls += 1
        if not self.outcomes:
            raise AssertionError("unexpected extra topic readback attempt")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def http_error(url, status):
    return HTTPError(url, status, f"HTTP {status}", hdrs=None, fp=None)


def assert_topic_readback_resilience():
    url = ft.topic_url(REF)

    sleeps = []
    opener = SequenceOpener([http_error(url, 404), FakeResponse(url)])
    recovered = ft._topic_readback(url, opener=opener, sleeper=sleeps.append)
    assert recovered["verified"] is True
    assert recovered["attempt_count"] == 2
    assert recovered["recovery_state"] == "RECOVERED_AFTER_TRANSIENT_FAILURE"
    assert recovered["attempts"][0]["outcome"] == "TRANSPORT_FAILURE"
    assert recovered["attempts"][0]["http_status"] == 404
    assert recovered["attempts"][0]["retriable"] is True
    assert recovered["attempts"][1]["outcome"] == "VERIFIED"
    assert sleeps == [ft.TOPIC_READBACK_BACKOFF_SECONDS[0]]

    sleeps = []
    opener = SequenceOpener([http_error(url, 404), http_error(url, 404), http_error(url, 404)])
    exhausted = ft._topic_readback(url, opener=opener, sleeper=sleeps.append)
    assert exhausted["verified"] is False
    assert exhausted["failure_class"] == "TRANSIENT_READBACK_EXHAUSTED"
    assert exhausted["attempt_count"] == 3
    assert [row["http_status"] for row in exhausted["attempts"]] == [404, 404, 404]
    assert all(row["retriable"] is True for row in exhausted["attempts"])
    assert sleeps == list(ft.TOPIC_READBACK_BACKOFF_SECONDS)

    opener = SequenceOpener([http_error(url, 403), FakeResponse(url)])
    denied = ft._topic_readback(url, opener=opener, sleeper=lambda _: None)
    assert denied["verified"] is False
    assert denied["failure_class"] == "NON_RETRYABLE_READBACK_FAILURE"
    assert denied["attempt_count"] == 1
    assert opener.calls == 1

    drift_url = "https://example.com/not-authority/topic-details/" + REF
    opener = SequenceOpener([FakeResponse(drift_url), FakeResponse(url)])
    drift = ft._topic_readback(url, opener=opener, sleeper=lambda _: None)
    assert drift["verified"] is False
    assert drift["failure_class"] == "AUTHORITY_OR_CONTENT_DRIFT"
    assert drift["attempt_count"] == 1
    assert drift["attempts"][0]["retriable"] is False
    assert opener.calls == 1

    try:
        ft._topic_readback(url, opener=SequenceOpener([]), max_attempts=0, sleeper=lambda _: None)
        raise AssertionError("invalid retry bound was accepted")
    except ValueError as exc:
        assert "max_attempts" in str(exc)


def main():
    assert_topic_readback_resilience()

    taxonomy = {
        "schema": "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1",
        "market_intelligence_only": True,
        "material_fact_use": False,
        "records": [
            {"identifier": "CEF-T-2026-MILMOB-WORKS", "programme_family_normalized": "CEF", "status_label_candidate": "Forthcoming", "taxonomy_fingerprint": "1" * 64, "source_semantic_fingerprint": "2" * 64, "authority_url_candidate": ft.topic_url("CEF-T-2026-MILMOB-WORKS")},
            {"identifier": REF, "programme_family_normalized": "CEF", "status_label_candidate": "Open", "taxonomy_fingerprint": "3" * 64, "source_semantic_fingerprint": "4" * 64, "authority_url_candidate": ft.topic_url(REF)},
        ],
    }
    selected = select_cef_candidate(taxonomy)
    assert selected["identifier"] == REF

    evidence = collect_exact(
        REF,
        run_id="synthetic",
        fetched_at="2026-09-01T18:00:00+00:00",
        source_candidate=selected,
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["status_label"] == "Open"
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_family"] == "CEF"
    assert evidence["material_fact_use"] is False
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["publish_authorized"] is False

    bad_facet = facet_payload()
    bad_facet["facets"][0]["values"][0]["value"] = "Horizon Europe"
    try:
        collect_exact(REF, run_id="bad-programme", fetched_at="2026-09-01T18:00:00+00:00", post_func=make_post(facet=bad_facet), topic_func=topic)
        raise AssertionError("non-CEF programme label was accepted")
    except ValueError as exc:
        assert "not proven to belong to CEF" in str(exc)

    conflict_rows = search_payload("2027-01-15T17:00:00Z") + search_payload("2027-02-01T17:00:00Z")
    try:
        collect_exact(REF, run_id="conflict", fetched_at="2026-09-01T18:00:00+00:00", post_func=make_post(search=conflict_rows), topic_func=topic)
        raise AssertionError("materially conflicting exact CEF rows were accepted")
    except ExactCefConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
        raise AssertionError("self-authorization was accepted")
    except ValueError as exc:
        assert "attempted authorization" in str(exc)

    print("eu_direct_cef_ft_exact regression: PASS")


if __name__ == "__main__":
    main()
