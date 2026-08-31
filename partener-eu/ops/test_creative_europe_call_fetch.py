#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / "ingest" / "creative_europe_call_fetch.py"
spec = importlib.util.spec_from_file_location("creative_europe_call_fetch", MODULE)
m = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(m)

RAW = b"""
<html><body><h3>CREA-CULT-2026-COOP</h3><span>Status:</span><span>closed</span>
<span>Deadline:</span><span>5 May 2026 17:00 CEST</span><h2>2026 European Cooperation Projects</h2>
<a href="/funding/calls/cooperation">Opportunity details</a></body></html>
"""


def ok_fetch(url: str):
    return {
        "requested_url": url,
        "final_url": "https://culture.ec.europa.eu/funding/calls",
        "status": 200,
        "content_type": "text/html; charset=UTF-8",
        "raw": RAW,
    }


evidence = m.collect_live(
    run_id="synthetic-live",
    fetched_at="2026-08-31T18:00:00+00:00",
    fetcher=ok_fetch,
)
assert evidence["stats"]["exact_crea_reference_candidates"] == 1
assert evidence["stats"]["open_call_authorized"] == 0
assert evidence["stats"]["records_requiring_ft_reconcile"] == 1
assert evidence["source_health"] == "HEALTHY"
assert evidence["lkg_required"] is False
assert evidence["open_call_authorized"] is False

for bad_url in (
    "http://culture.ec.europa.eu/funding/calls",
    "https://example.com/funding/calls",
    "https://culture.ec.europa.eu/creative-europe",
    "https://culture.ec.europa.eu/funding/calls?status=open",
):
    try:
        m.official_url(bad_url)
    except ValueError:
        pass
    else:
        raise AssertionError(f"unsafe URL accepted: {bad_url}")


def hostile_redirect(url: str):
    return {
        "requested_url": url,
        "final_url": "https://example.com/funding/calls",
        "status": 200,
        "content_type": "text/html",
        "raw": RAW,
    }


try:
    m.collect_live(run_id="hostile", fetcher=hostile_redirect)
except ValueError:
    pass
else:
    raise AssertionError("hostile redirect did not fail closed")


def empty_index(url: str):
    return {
        "requested_url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html",
        "raw": b"<html><body><h2>No explicit Creative Europe references</h2></body></html>",
    }


degraded = m.collect_live(run_id="empty", fetcher=empty_index)
assert degraded["stats"]["exact_crea_reference_candidates"] == 0
assert degraded["source_health"] == "DEGRADED_EMPTY_RENDERED_INDEX"
assert degraded["lkg_required"] is True
assert degraded["open_call_authorized"] is False
assert degraded["publication_effect"] == "NONE"

print("PASS Creative Europe bounded acquisition, degraded-empty persistence and hostile fail-closed regression")
