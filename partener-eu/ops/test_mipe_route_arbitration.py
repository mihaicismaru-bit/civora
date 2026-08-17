#!/usr/bin/env python3
"""Offline regression for MIPE authoritative-route arbitration."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "normalize_mipe_health.py"
spec = importlib.util.spec_from_file_location("normalize_mipe_health", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

NOW = dt.datetime(2026, 8, 16, 15, 10, tzinfo=dt.timezone.utc)


def degraded_hosted_state() -> dict:
    return {
        "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
        "lastRun": {
            "observedAt": "2026-08-16T15:01:24+00:00",
            "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
            "roots": [{"target": module.PDDS_PRIORITY_SEED, "ok": False, "transport": "direct-canonical", "error": "Network is unreachable"}],
            "transportMode": "primary-direct-unavailable",
            "sourceAvailable": False,
        },
        "items": [{"id": "mysmis-1", "url": "https://reporting.mysmis2021.gov.ro/example", "title": "MySMIS direct evidence", "verification": "CANONICAL_OFFICIAL_FETCH", "retrievalTransport": "direct-canonical"}],
        "runs": [],
    }


def fresh_ro_corpus() -> dict:
    return {
        "schemaVersion": 3,
        "status": "PASS",
        "lastRun": {
            "observedAt": "2026-08-16T14:08:25+00:00",
            "sourceAvailable": True,
            "collectorVersion": "3.0",
            "transport": "playwright-edge-direct-romania-v3",
            "acceptedPages": 1,
            "roots": [{"root": module.PDDS_PRIORITY_SEED, "ok": True, "status": 200, "finalUrl": module.PDDS_PRIORITY_SEED}],
        },
        "pages": [{
            "id": "mipe-page-1",
            "url": "https://mfe.gov.ro/ghiduri_peos/apel-test/",
            "title": "Apel test",
            "programme": "PEO",
            "pageClass": "CALL_OR_GUIDE",
            "kind": "GUIDE_PUBLISHED",
            "summary": "Ghid oficial MIPE",
            "textPreview": "Text oficial suficient pentru verificarea provenienței.",
            "observedAt": "2026-08-16T14:08:25+00:00",
            "retrievalTransport": "playwright-edge-direct-romania-v3",
            "verification": "CANONICAL_OFFICIAL_FETCH",
            "documents": [],
            "contentHash": "a" * 64,
        }],
    }


def test_fresh_ro_direct_route_wins_over_hosted_egress_failure() -> None:
    state, changed = module.normalize_state(degraded_hosted_state(), fresh_ro_corpus(), reference_time=NOW)
    assert changed is True
    assert state["status"] == "OK"
    assert state["canonicalRoute"] == "romaniaWindows"
    assert state["routeHealth"]["romaniaWindows"]["status"] == "PASS"
    assert state["routeHealth"]["githubHosted"]["status"] == "DEGRADED"
    assert state["lastRun"]["prioritySeedAvailable"] is True
    assert state["lastRun"]["primaryOfficialRootAvailable"] is True
    assert state["lastRun"]["sourceHealth"] == "PRIMARY_SOURCES_AVAILABLE_VIA_ROMANIA_DIRECT"
    by_url = {row["url"]: row for row in state["items"]}
    assert "https://mfe.gov.ro/ghiduri_peos/apel-test/" in by_url
    assert by_url["https://mfe.gov.ro/ghiduri_peos/apel-test/"]["retrievalTransport"].startswith("direct")
    assert "https://reporting.mysmis2021.gov.ro/example" in by_url


def test_stale_ro_corpus_does_not_mask_hosted_failure() -> None:
    corpus = fresh_ro_corpus()
    corpus["lastRun"]["observedAt"] = "2026-08-16T08:00:00+00:00"
    state, _ = module.normalize_state(degraded_hosted_state(), corpus, reference_time=NOW)
    assert state["status"] == "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"
    assert state.get("canonicalRoute") is None


def test_untrusted_ro_page_fails_closed() -> None:
    corpus = fresh_ro_corpus()
    corpus["pages"][0]["url"] = "https://example.com/fake"
    assert module.fresh_authoritative_romania_corpus(corpus, reference_time=NOW) is False


def main() -> int:
    test_fresh_ro_direct_route_wins_over_hosted_egress_failure()
    test_stale_ro_corpus_does_not_mask_hosted_failure()
    test_untrusted_ro_page_fails_closed()
    print("MIPE route arbitration regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
