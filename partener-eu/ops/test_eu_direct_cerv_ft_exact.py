#!/usr/bin/env python3
from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "ingest"))

import funding_tenders_fetch as ft
from eu_direct_cerv_ft_exact import ExactCERVConflict, collect_exact, validate_evidence

REF = "CERV-2026-CHAR-LITI-CHARTER"
CALL = "CERV-2026-CHAR-LITI"
PROGRAMME_CODE = "43251589"
STATUS_CODE = "31094502"
PROGRAMME_LABEL = "Citizens, Equality, Rights and Values Programme (CERV)"


def facet_payload():
    return {
        "facets": [
            {"name": "frameworkProgramme", "values": [{"rawValue": PROGRAMME_CODE, "value": PROGRAMME_LABEL}]},
            {"name": "status", "values": [{"rawValue": STATUS_CODE, "value": "Open"}]},
        ]
    }


def search_payload(deadline="2026-10-01T17:00:00Z"):
    return [{
        "identifier": REF,
        "topicAbbreviation": REF,
        "callIdentifier": CALL,
        "type": "1",
        "frameworkProgramme": PROGRAMME_CODE,
        "programmePeriod": "2021 - 2027",
        "status": STATUS_CODE,
        "title": "Synthetic CERV topic",
        "deadlineDate": deadline,
    }]


def pack(endpoint, payload):
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return payload, raw, {
        "url": endpoint,
        "final_url": endpoint,
        "http_status": 200,
        "content_type": "application/json",
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def make_post(search=None, facet=None):
    search = search if search is not None else search_payload()
    facet = facet if facet is not None else facet_payload()
    def post(endpoint, **kwargs):
        if endpoint == ft.SEARCH_ENDPOINT:
            return pack(endpoint, copy.deepcopy(search))
        if endpoint == ft.FACET_ENDPOINT:
            return pack(endpoint, copy.deepcopy(facet))
        raise AssertionError(endpoint)
    return post


def topic(url):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": "b" * 64,
        "verified": True,
    }


def main() -> int:
    source_candidate = {
        "identifier": REF,
        "source_discovery_fingerprint": "1" * 64,
        "source_candidate_fingerprint": "2" * 64,
        "source_status_label_candidate": "Open",
        "source_authority_url_candidate": ft.topic_url(REF),
        "source_call_identifier": CALL,
    }
    evidence = collect_exact(
        REF,
        run_id="synthetic",
        fetched_at="2026-09-02T01:00:00+00:00",
        source_candidate=source_candidate,
        post_func=make_post(),
        topic_func=topic,
    )
    validate_evidence(evidence)
    assert evidence["candidate_state"] == "OPEN_CALL"
    assert evidence["programme_family"] == "CERV"
    assert evidence["authority_url_verified"] is True
    assert evidence["programme_label_official"] == PROGRAMME_LABEL
    assert evidence["open_call_authorized"] is False
    assert evidence["deadline_authorized"] is False
    assert evidence["eligibility_authorized"] is False

    bad = facet_payload()
    bad["facets"][0]["values"][0]["value"] = "Digital Europe Programme (DIGITAL)"
    try:
        collect_exact(
            REF,
            run_id="bad",
            fetched_at="2026-09-02T01:00:00+00:00",
            post_func=make_post(facet=bad),
            topic_func=topic,
        )
        raise AssertionError("wrong programme accepted")
    except ValueError as exc:
        assert "not proven to belong to CERV" in str(exc)

    conflict = search_payload("2026-10-01T17:00:00Z") + search_payload("2026-11-01T17:00:00Z")
    try:
        collect_exact(
            REF,
            run_id="conflict",
            fetched_at="2026-09-02T01:00:00+00:00",
            post_func=make_post(search=conflict),
            topic_func=topic,
        )
        raise AssertionError("conflicting exact rows accepted")
    except ExactCERVConflict:
        pass

    tampered = copy.deepcopy(evidence)
    tampered["open_call_authorized"] = True
    try:
        validate_evidence(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("exact CERV evidence self-authorized OPEN")

    tampered = copy.deepcopy(evidence)
    tampered["authority_url_verified"] = False
    try:
        validate_evidence(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("exact CERV evidence accepted lost authority proof")

    tampered = copy.deepcopy(evidence)
    tampered["source_candidate"]["identifier"] = "CERV-2026-DAPHNE-CHILDREN"
    try:
        validate_evidence(tampered)
    except ValueError:
        pass
    else:
        raise AssertionError("exact CERV evidence accepted source identity drift")

    print("eu_direct_cerv_ft_exact regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
