from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from municipal_document_shadow_lane import (  # noqa: E402
    _validate_official_document_url,
    materialize_document_evidence,
)
from test_core_v2_municipal_materiality_shadow_lane import MunicipalMaterialityShadowLaneTests  # noqa: E402,F401
from test_core_v2_municipal_fact_kernel_shadow_lane import MunicipalFactKernelShadowLaneTests  # noqa: E402,F401


class MunicipalDocumentShadowLaneTests(unittest.TestCase):
    def _document(self):
        return {
            "decision_number": 345,
            "decision_date": "2026-09-16",
            "registered_title": "Hotărârea nr. 345 privind un serviciu public local",
            "resolved": True,
            "official_html_url": "https://dm.primariavl.ro/dm/2026/hotarari.nsf/ABCDEF0123456789/$FILE/h345.htm",
            "http_status": 200,
            "source_sha256": "a" * 64,
            "document_text_sha256": "b" * 64,
            "document_unid": "ABCDEF0123456789",
            "operative_articles": ["Art. 1. Se aprobă măsura descrisă în hotărâre."],
            "vote_snippets": ["Hotărârea a fost adoptată cu voturile consemnate în document."],
            "money_snippets": [],
            "procurement_snippets": [],
            "project_snippets": [],
            "entity_snippets": [],
        }

    def test_official_document_url_is_strictly_bounded(self):
        good = self._document()["official_html_url"]
        self.assertEqual(_validate_official_document_url(good), good)
        for bad in (
            "http://dm.primariavl.ro/dm/2026/hotarari.nsf/A/$FILE/h345.htm",
            "https://evil.example/dm/2026/hotarari.nsf/A/$FILE/h345.htm",
            "https://dm.primariavl.ro/dm/2025/hotarari.nsf/A/$FILE/h345.htm",
            "https://user:pass@dm.primariavl.ro/dm/2026/hotarari.nsf/A/$FILE/h345.htm",
            "https://dm.primariavl.ro/dm/2026/hotarari.nsf/A/$FILE/h345.htm#fragment",
        ):
            with self.assertRaises(ValueError):
                _validate_official_document_url(bad)

    def test_verified_document_materializes_non_authorizing_evidence(self):
        document = self._document()
        first = materialize_document_evidence(document)
        second = materialize_document_evidence(document)
        self.assertEqual(first["state"], "DOCUMENT_EVIDENCE_READY")
        self.assertEqual(first["publication_authority"], "NONE")
        self.assertFalse(first["fact_kernel_promotion_allowed"])
        self.assertFalse(first["writer_allowed"])
        self.assertEqual(first["operative_article_count"], 1)
        self.assertGreaterEqual(first["evidence_count"], 2)
        self.assertEqual(
            [row["evidence_id"] for row in first["evidence"]],
            [row["evidence_id"] for row in second["evidence"]],
        )
        self.assertTrue(all(row["material_fact_status"] == "UNADJUDICATED" for row in first["evidence"]))
        self.assertTrue(all(row["epistemic_status"] == "FIRST_PARTY_DOCUMENT_TEXT" for row in first["evidence"]))
        self.assertNotIn("fact_kernel", first)
        self.assertNotIn("article_package", first)

    def test_off_surface_resolver_result_is_blocked(self):
        document = self._document()
        document["official_html_url"] = "https://example.com/dm/2026/hotarari.nsf/A/$FILE/h345.htm"
        result = materialize_document_evidence(document)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "resolved_document_off_surface_url")
        self.assertEqual(result["evidence"], [])

    def test_invalid_identity_hashes_are_blocked(self):
        for field, bad in (("source_sha256", "abc"), ("document_text_sha256", "g" * 64)):
            document = self._document()
            document[field] = bad
            result = materialize_document_evidence(document)
            self.assertEqual(result["state"], "BLOCKED")
            self.assertEqual(result["reason"], "resolved_document_invalid_identity_hashes")
            self.assertEqual(result["evidence"], [])

    def test_invalid_decision_identity_is_blocked(self):
        for field, bad in (("decision_number", 0), ("decision_date", "2025-09-16"), ("decision_date", "not-a-date")):
            document = self._document()
            document[field] = bad
            result = materialize_document_evidence(document)
            self.assertEqual(result["state"], "BLOCKED")
            self.assertEqual(result["reason"], "resolved_document_invalid_decision_identity")
            self.assertEqual(result["evidence"], [])

    def test_resolved_document_without_operative_article_is_blocked(self):
        document = self._document()
        document["operative_articles"] = []
        result = materialize_document_evidence(document)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "resolved_document_without_operative_article_evidence")
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])

    def test_unresolved_document_is_blocked_without_evidence(self):
        document = self._document()
        document["resolved"] = False
        document["reason"] = "ROW_DOCUMENT_URL_NOT_RESOLVED"
        result = materialize_document_evidence(document)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["reason"], "ROW_DOCUMENT_URL_NOT_RESOLVED")
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
