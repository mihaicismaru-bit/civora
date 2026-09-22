#!/usr/bin/env python3
"""Offline regression tests for the resilient MIPE ingestion adapter."""
from __future__ import annotations

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


def main() -> int:
    test_canonical_policy()
    test_reader_contract()
    test_fail_closed_reader()
    test_classification_is_conservative()
    test_source_incident_isolation_keeps_direct_mysmis_usable()
    print("MIPE resilient ingestion regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
