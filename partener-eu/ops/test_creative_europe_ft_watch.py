#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
MODULE = INGEST / "creative_europe_ft_watch.py"
spec = importlib.util.spec_from_file_location("creative_europe_ft_watch", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

OPEN = "CREA-MEDIA-2026-DEVMINISLATE"
FORTHCOMING = "CREA-CULT-2027-COOP"
CONFLICT = "CREA-CROSS-2026-CONFLICT"

page1 = {
    "results": [
        {"metadata": {
            "identifier": [OPEN], "callIdentifier": ["CREA-MEDIA-2026"],
            "status": ["31094502"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"], "deadlineDate": ["2026-09-17"],
        }, "content": "European mini-slate development"},
        {"metadata": {
            "identifier": [CONFLICT], "callIdentifier": ["CREA-CROSS-2026"],
            "status": ["31094502"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Conflicting fixture"},
    ]
}
page2 = {
    "results": [
        {"metadata": {
            "identifier": [FORTHCOMING], "callIdentifier": ["CREA-CULT-2027"],
            "status": ["31094501"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"], "deadlineDate": ["2027-05-01"],
        }, "content": "Future cooperation projects"},
        {"metadata": {
            "identifier": [CONFLICT], "callIdentifier": ["CREA-CROSS-2026"],
            "status": ["99999999"], "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Conflicting fixture"},
        {"metadata": {
            "identifier": ["EAC/A03/2021"], "status": ["31094502"],
            "programmePeriod": ["2021 - 2027"],
        }, "content": "Not Creative Europe structured topic"},
    ]
}
facet = {
    "facets": [{
        "name": "status",
        "values": [
            {"rawValue": "31094502", "value": "Open for submission"},
            {"rawValue": "31094501", "value": "Forthcoming"},
        ],
    }]
}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = page1 if page_number == 1 else page2 if page_number == 2 else {"results": []}
        raw = json.dumps(payload, sort_keys=True).encode()
        return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}
    raw = json.dumps(facet, sort_keys=True).encode()
    return facet, raw, {"url": endpoint, "http_status": 200, "sha256": "b" * 64}


e = m.collect_watch(
    run_id="fixture",
    fetched_at="2026-09-01T02:30:00+00:00",
    text="CREA-",
    page_size=2,
    max_pages=3,
    post_func=fake_post,
)
assert e["source_health"] == "HEALTHY"
assert e["open_call_authorized"] is False
assert e["stats"]["search_records"] == 5
assert e["stats"]["non_crea_records_excluded"] == 1
assert e["stats"]["explicit_crea_references_seen"] == 3
assert e["stats"]["exact_reference_candidates"] == 2
assert e["stats"]["conflicting_references_excluded"] == 1
assert [c["reference"] for c in e["candidates"]] == [OPEN, FORTHCOMING]
assert e["candidates"][0]["candidate_observation_state"] == "OPEN_CANDIDATE_NON_AUTHORIZING"
assert e["candidates"][1]["candidate_observation_state"] == "FORTHCOMING_CANDIDATE_NON_AUTHORIZING"
assert all(c["authority_url_verified"] is False for c in e["candidates"])
assert all(c["requires_exact_topic_readback"] is True for c in e["candidates"])

bad = dict(e)
bad["open_call_authorized"] = True
try:
    m.validate_watch_evidence(bad)
except ValueError:
    pass
else:
    raise AssertionError("programme watch self-authorized OPEN")

bad_candidate = json.loads(json.dumps(e))
bad_candidate["candidates"][0]["authority_url_verified"] = True
try:
    m.validate_watch_evidence(bad_candidate)
except ValueError:
    pass
else:
    raise AssertionError("programme watch claimed exact topic verification without readback")


def empty_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = {"results": []}
    else:
        payload = {"facets": []}
    raw = json.dumps(payload).encode()
    return payload, raw, {"url": endpoint, "http_status": 200, "sha256": "c" * 64}


empty = m.collect_watch(
    run_id="empty",
    fetched_at="2026-09-01T02:30:00+00:00",
    post_func=empty_post,
)
assert empty["source_health"] == "DEGRADED_EMPTY_STRUCTURED_DISCOVERY"
assert empty["lkg_required"] is True
assert empty["stats"]["exact_reference_candidates"] == 0
assert empty["open_call_authorized"] is False

print("PASS Creative Europe programme-wide structured F&T watch stays non-authorizing")
