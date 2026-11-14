#!/usr/bin/env python3
"""Offline regression tests for the resilient MIPE ingestion adapter."""
from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"
INDEX_MODULE_PATH = ROOT / "partener-eu" / "ingest" / "intelligence_index.py"

spec = importlib.util.spec_from_file_location("mipe_resilient_ingest", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

index_spec = importlib.util.spec_from_file_location("partener_intelligence_index", INDEX_MODULE_PATH)
assert index_spec and index_spec.loader
index_module = importlib.util.module_from_spec(index_spec)
index_spec.loader.exec_module(index_module)

mysmis_spec = importlib.util.spec_from_file_location(
    "partener_mysmis_consultant", ROOT / "partener-eu/ingest/build_mysmis_consultant_registry.py"
)
assert mysmis_spec and mysmis_spec.loader
mysmis_module = importlib.util.module_from_spec(mysmis_spec)
mysmis_spec.loader.exec_module(mysmis_module)


def test_canonical_policy() -> None:
    assert module.canonicalize("https://mfe.gov.ro/ghiduri_peos/?utm_source=test") == "https://mfe.gov.ro/ghiduri_peos/"
    assert module.canonicalize("https://oportunitati-ue.gov.ro/example") == "https://oportunitati-ue.gov.ro/example"
    assert module.canonicalize("https://example.com/fake-mipe") is None
    assert not module.is_official("https://news.example/mfe.gov.ro")


def test_reader_contract() -> None:
    sample = b"""Title: PEO - S-a lansat apelul pentru tineri NEET\nURL Source: https://mfe.gov.ro/peo-apel-neet/\nPublished Time: 2026-08-12\nMarkdown Content:\n# PEO - S-a lansat apelul pentru tineri NEET\nApelul este deschis in MySMIS pana la 30 septembrie 2026. Bugetul este de 20 milioane euro.\n[Descarca ghidul](https://mfe.gov.ro/wp-content/uploads/2026/08/ghid.pdf)\n"""
    parsed = module.parse_reader(sample, "https://mfe.gov.ro/peo-apel-neet/")
    assert parsed
    assert parsed["canonical"] == "https://mfe.gov.ro/peo-apel-neet/"
    assert "tineri NEET" in parsed["title"]
    assert parsed["links"]
    assert module.classify_kind(parsed["title"], parsed["body"]) == "CALL_OPENED"
    docs = module.document_links(parsed["links"], parsed["canonical"])
    assert docs and docs[0]["url"].endswith("ghid.pdf")


def test_fail_closed_reader() -> None:
    hostile = b"""Title: Fake\nURL Source: https://example.com/not-official\nMarkdown Content:\nPretins apel MIPE.\n"""
    assert module.parse_reader(hostile, "https://mfe.gov.ro/fake/") is None
    assert module.fetch_document("https://example.com/not-official")[0] is None


def test_classification_is_conservative() -> None:
    assert module.classify_kind("Consultare publică pentru ghid", "") == "CONSULTATION_OPENED"
    assert module.classify_kind("Corrigendum nr. 2", "") == "GUIDE_MODIFIED"
    assert module.classify_kind("Comunicat general", "Ministerul prezintă bilanțul.") == "OFFICIAL_UPDATE"


def test_source_incident_isolation_keeps_direct_mysmis_usable() -> None:
    """A legacy MIPE transport incident must not poison a healthy direct MySMIS authority.

    The aggregate MIPE publication corpus and the direct MySMIS call registry are
    independent evidence channels. The former may remain fail-closed/LKG while
    current T1 MySMIS evidence remains eligible for reconciliation. This is the
    core dependency-isolation guarantee used by the Funding Intelligence plane.
    """
    legacy_mipe = {
        "id": "MIPE_CORPUS",
        "tier": "T1",
        "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
        "sourceAvailable": False,
        "freshness": {"status": "CURRENT"},
        "materialFactUse": True,
        "dependencyScopes": ["MIPE_MANAGED_PROGRAMMES"],
        "lastKnownGoodPreserved": True,
        "resolutionTaskRequired": False,
        "contract": {"status": "PASS"},
    }
    direct_mysmis = {
        "id": "SRC-MYSMIS-CALLS",
        "tier": "T1",
        "status": "PASS",
        "freshness": {"status": "CURRENT"},
        "materialFactUse": True,
        "dependencyScopes": ["2021-2027"],
        "lastKnownGoodPreserved": True,
        "resolutionTaskRequired": False,
        "contract": {"status": "PASS"},
    }

    legacy_gate = index_module.dependency_gate(legacy_mipe)
    mysmis_gate = index_module.dependency_gate(direct_mysmis)

    assert legacy_gate["availability"] == "UNAVAILABLE_LAST_KNOWN_GOOD"
    assert legacy_gate["materialFactGate"] == "BLOCKED_SOURCE_DEPENDENCIES"
    assert legacy_gate["blocksUnrelatedSources"] is False
    assert mysmis_gate["availability"] == "AVAILABLE"
    assert mysmis_gate["materialFactGate"] == "RECONCILIATION_REQUIRED"
    assert mysmis_gate["blockingReasons"] == []
    assert mysmis_gate["blocksUnrelatedSources"] is False
    assert mysmis_gate["publishMaterialFacts"] is False



def test_mysmis_consultant_requires_current_dual_proof() -> None:
    """A live transport probe never refreshes an older material registry snapshot."""
    now = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone.utc)
    old = {
        "url": mysmis_module.DEFAULT_URL,
        "observedAt": "2026-08-17T21:43:22+00:00",
        "verification": "CANONICAL_OFFICIAL_FETCH",
        "retrievalTransport": "direct-canonical",
        "registrySnapshot": {"A": {"programme": "PEO", "call": "Historic call"}},
    }
    # The MIPE aggregate health and MySMIS authority are separate channels:
    # a NEW directly acquired MySMIS item is valid even if MIPE is degraded.
    state = {"status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED", "items": [old]}
    assert mysmis_module.extract_snapshot(state, now) is None, "historical LKG must not claim OK_DIRECT"

    fresh = {**old, "observedAt": "2026-11-12T08:35:54+00:00"}
    state["items"].append(fresh)
    result = mysmis_module.extract_snapshot(state, now)
    assert result and result["observedAt"] == fresh["observedAt"]
    assert result["directOnly"] is True and len(result["calls"]) == 1

    # A lone label is never proof; require verification AND direct transport.
    for mutation in (
        {"verification": ""},
        {"verification": "INFERRED_FROM_INDEX"},
        {"retrievalTransport": "bing-rss-discovery-only"},
        {"retrievalTransport": ""},
        {"observedAt": "2026-11-12T09:01:00+00:00"},
        {"observedAt": "2026-11-12 08:35:54"},
        {"observedAt": "bogus"},
        {"url": "https://reporting.mysmis2021.gov.ro/ords/other-report"},
        {"url": mysmis_module.DEFAULT_URL + "?fake=true"},
        {"url": mysmis_module.DEFAULT_URL.replace("https://", "http://")},
        {"url": "https://reporting.mysmis2021.gov.ro.evil.test" + mysmis_module.DEFAULT_URL.split(".gov.ro", 1)[1]},
    ):
        assert mysmis_module.extract_snapshot({"items": [{**fresh, **mutation}]}, now) is None, mutation

    # An item older than the source-specific SLA must become unavailable.
    too_old = {**fresh, "observedAt": "2026-11-12T00:30:00+00:00"}
    assert mysmis_module.extract_snapshot({"items": [too_old]}, now) is None
    assert mysmis_module.official_reporting_url(mysmis_module.DEFAULT_URL)
    assert not mysmis_module.official_reporting_url(mysmis_module.DEFAULT_URL + "#shadow")


def test_mysmis_legacy_snapshot_cannot_evade_freshness() -> None:
    now = dt.datetime(2026, 11, 12, 9, 0, tzinfo=dt.timezone.utc)
    data = {
        "lastRun": {
            "observedAt": "2026-08-17T21:43:22+00:00",
            "registrySnapshot": {
                "status": "OK",
                "directOnly": True,
                "canonicalUrl": mysmis_module.DEFAULT_URL,
                "calls": [{"programme": "PEO", "call": "Historic call"}],
            },
        },
    }
    assert mysmis_module.extract_snapshot(data, now) is None
    data["lastRun"]["observedAt"] = "2026-11-12T08:40:00+00:00"
    assert mysmis_module.extract_snapshot(data, now)["calls"][0]["programme"] == "PEO"
    data["lastRun"]["registrySnapshot"]["directOnly"] = False
    assert mysmis_module.extract_snapshot(data, now) is None

def test_failed_mipe_heartbeat_is_not_fresh_official_evidence() -> None:
    """Fresh transport failure may update monitoring, not the canonical corpus clock."""
    now = dt.datetime(2026, 11, 14, 14, tzinfo=dt.timezone.utc)
    failed = {
        "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED",
        "lastRun": {"observedAt": "2026-11-14T12:35:20Z", "sourceAvailable": False},
        "items": [],
    }
    corpus, _ = index_module.mipe_records(failed, now, {"freshnessSlaHours": 4})
    assert corpus["lastAttemptFreshness"]["status"] == "CURRENT"
    assert corpus["freshness"]["status"] == "UNKNOWN"
    assert corpus["sourceAvailable"] is False
    assert corpus["failClosed"] is True

    # A success requires both live source evidence and a healthy corpus status.
    fresh = {**failed, "status": "OK", "lastRun": {**failed["lastRun"], "sourceAvailable": True}}
    successful, _ = index_module.mipe_records(fresh, now, {"freshnessSlaHours": 4})
    assert successful["freshness"]["status"] == "CURRENT"
    still_degraded = {**fresh, "status": "DEGRADED_LAST_KNOWN_GOOD_PRESERVED"}
    degraded, _ = index_module.mipe_records(still_degraded, now, {"freshnessSlaHours": 4})
    assert degraded["lastAttemptFreshness"]["status"] == "CURRENT"
    assert degraded["freshness"]["status"] == "UNKNOWN"


def main() -> int:
    test_canonical_policy()
    test_reader_contract()
    test_fail_closed_reader()
    test_classification_is_conservative()
    test_source_incident_isolation_keeps_direct_mysmis_usable()
    test_mysmis_consultant_requires_current_dual_proof()
    test_mysmis_legacy_snapshot_cannot_evade_freshness()
    test_failed_mipe_heartbeat_is_not_fresh_official_evidence()
    print("MIPE resilient ingestion regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
