#!/usr/bin/env python3
"""Offline regression tests for the resilient MIPE ingestion adapter."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "partener-eu" / "ingest" / "mipe_resilient_ingest.py"

spec = importlib.util.spec_from_file_location("mipe_resilient_ingest", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


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


def main() -> int:
    test_canonical_policy()
    test_reader_contract()
    test_fail_closed_reader()
    test_classification_is_conservative()
    print("MIPE resilient ingestion regression: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
