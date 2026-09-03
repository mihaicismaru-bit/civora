#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve()
INGEST = HERE.parent.parent / "ingest"
sys.path.insert(0, str(INGEST))

from eu_direct_edf_programme_intelligence import collect, validate_registry  # noqa: E402

REGISTRY_PATH = INGEST / "eu_direct_edf_programme_intelligence_registry.json"


def registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def fake_fetch(url: str):
    if "edf-work-programme-2026" in url:
        body = b"<html><h1>EDF Work Programme 2026</h1><p>Work Programme 2026</p><p>Call topics description</p></html>"
    elif "calls-proposals" in url:
        body = b"<html><h1>Calls for proposals</h1><p>Status</p><p>Opening date</p><p>Call status: Open</p></html>"
    else:
        body = b"<html><h1>European Defence Fund</h1><p>EDF Work Programme 2026</p></html>"
    return body, {
        "requested_url": url,
        "final_url": url,
        "http_status": 200,
        "content_type": "text/html; charset=utf-8",
    }


def degraded_fetch(url: str):
    if "calls-proposals" in url:
        raise TimeoutError("synthetic")
    return fake_fetch(url)


def main() -> int:
    reg = registry()
    validate_registry(reg)
    snap = collect(reg, "test-healthy", fetcher=fake_fetch)
    assert snap["source_count"] == 3
    assert snap["healthy_source_count"] == 3
    assert snap["degraded_source_count"] == 0
    assert snap["source_health_state"] == "HEALTHY"
    assert snap["market_intelligence_only"] is True
    assert snap["fit_score_is_not_eligibility"] is True
    assert {r["observation_state"] for r in snap["evidence"]} == {
        "PROGRAMME_INTELLIGENCE", "PROGRAMMING_PIPELINE", "CALL_INDEX_DISCOVERY"
    }
    for key in (
        "material_fact_use", "open_call_authorized", "closed_call_authorized",
        "deadline_authorized", "budget_authorized", "eligibility_authorized",
        "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        assert snap[key] is False
    # Literal Open on the generic official calls index must never promote this layer.
    assert snap["open_call_authorized"] is False
    assert "exact_call_or_topic_identifier" in snap["missing_for_open_confirmation"]

    degraded = collect(reg, "test-degraded", fetcher=degraded_fetch)
    assert degraded["source_health_state"] == "DEGRADED"
    assert degraded["lkg_required"] is True
    assert degraded["open_call_authorized"] is False
    assert degraded["publish_authorized"] is False

    bad = copy.deepcopy(reg)
    bad["sources"][1]["observation_state"] = "OPEN_CALL"
    try:
        validate_registry(bad)
        raise AssertionError("OPEN_CALL registry state was accepted")
    except ValueError:
        pass

    bad = copy.deepcopy(reg)
    bad["policy"]["open_call_authorized"] = True
    try:
        validate_registry(bad)
        raise AssertionError("authorizing registry was accepted")
    except ValueError:
        pass

    bad = copy.deepcopy(reg)
    bad["sources"][0]["url"] = "https://example.com/edf"
    try:
        validate_registry(bad)
        raise AssertionError("authority host drift was accepted")
    except ValueError:
        pass

    print(json.dumps({
        "unit": "EU_DIRECT_EDF_PROGRAMME_INTELLIGENCE",
        "healthy_sources": 3,
        "generic_index_literal_open_authorizes": False,
        "degraded_requires_lkg": True,
        "publication_effect": "NONE",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
