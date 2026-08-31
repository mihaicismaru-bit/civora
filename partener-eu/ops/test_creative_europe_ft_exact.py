#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

INGEST = Path(__file__).resolve().parents[1] / "ingest"
sys.path.insert(0, str(INGEST))
MODULE = INGEST / "creative_europe_ft_exact.py"
spec = importlib.util.spec_from_file_location("creative_europe_ft_exact", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

REF = "CREA-MEDIA-2026-DEVMINISLATE"

search_payload = {
    "results": [{
        "metadata": {
            "identifier": [REF],
            "callIdentifier": ["CREA-MEDIA-2026"],
            "status": ["31094502"],
            "programAbbreviation": ["CREA"],
            "programmePeriod": ["2021 - 2027"],
            "deadlineDate": ["2026-09-17"],
        },
        "content": "European mini-slate development",
    }]
}
facet_payload = {
    "facets": [{
        "name": "status",
        "values": [{"rawValue": "31094502", "value": "Open for submission"}],
    }]
}


def fake_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        raw = json.dumps(search_payload).encode()
        return search_payload, raw, {"url": endpoint, "http_status": 200, "sha256": "a" * 64}
    raw = json.dumps(facet_payload).encode()
    return facet_payload, raw, {"url": endpoint, "http_status": 200, "sha256": "b" * 64}


def fake_topic(url, *, max_bytes=None, opener=None):
    return {
        "url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html",
        "bytes": 10,
        "body_sha256": "c" * 64,
        "verified": True,
    }


e = m.collect_exact(
    REF,
    run_id="fixture",
    fetched_at="2026-08-31T18:00:00+00:00",
    post_func=fake_post,
    topic_func=fake_topic,
)
assert e["reference"] == REF
assert e["status_label"] == "Open"
assert e["candidate_observation_state"] == "OPEN_CALL"
assert e["open_call_authorized"] is False
assert e["requires_reconcile"] is True
assert e["authority_url_verified"] is True

bad = dict(e)
bad["open_call_authorized"] = True
try:
    m.validate_exact_evidence(bad)
except ValueError:
    pass
else:
    raise AssertionError("exact F&T evidence self-authorized OPEN")

try:
    m.validate_reference("EAC/A03/2021")
except ValueError:
    pass
else:
    raise AssertionError("non-CREA reference accepted")


def conflicting_post(endpoint, *, text, page_size, page_number, parts, max_bytes=None, opener=None):
    if "search" in endpoint and "facet" not in endpoint:
        payload = {"results": [
            search_payload["results"][0],
            {"metadata": {**search_payload["results"][0]["metadata"], "status": ["99999999"]}},
        ]}
        return payload, json.dumps(payload).encode(), {"url": endpoint, "http_status": 200, "sha256": "d" * 64}
    return fake_post(endpoint, text=text, page_size=page_size, page_number=page_number, parts=parts)


try:
    m.collect_exact(REF, run_id="conflict", post_func=conflicting_post, topic_func=fake_topic)
except ValueError:
    pass
else:
    raise AssertionError("conflicting exact records did not fail closed")

print("PASS Creative Europe exact structured F&T identity/status/topic regression")
