from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_embedded_target_shadow_lane import resolve_embedded_target_identities  # noqa: E402


class ISJEmbeddedTargetShadowLaneTests(unittest.TestCase):
    def _embedded(self, url: str = "https://www.isjvalcea.ro/management/concurs-directori-2026"):
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{
                "signal_id": "isj-ref-x",
                "evidence_id": "isj-detail-x",
                "topic_class": "STAFFING_MANAGEMENT",
                "label": "concurs directori 2026",
                "detail_url": url,
                "state": "EMBEDDED_NOTICE_EVIDENCE_SHADOW",
                "embedded_file_labels": [
                    "Important inscriere concurs Directori.pdf",
                    "LISTA POSTURI CONCURS DIRECTORI 2026.pdf",
                ],
                "current_year_embedded_labels": [
                    "LISTA POSTURI CONCURS DIRECTORI 2026.pdf",
                ],
                "explicit_current_material_catalog": True,
            }],
        }

    def test_official_parent_can_bind_visible_label_to_unique_drive_target(self):
        body = b"""<html><body><h1>CONCURS DIRECTORI 2026</h1>
        <a href="https://drive.google.com/file/d/AAAABBBBCCCC11112222/view">Important inscriere concurs Directori.pdf</a>
        <a href="https://drive.google.com/file/d/DDDDEEEEFFFF33334444/view">LISTA POSTURI CONCURS DIRECTORI 2026.pdf</a>
        </body></html>"""
        result = resolve_embedded_target_identities(
            self._embedded(),
            allow_network=True,
            current_year=2026,
            fetcher=lambda url: (body, url, "text/html"),
        )
        self.assertEqual(result["embedded_target_identity_shadow_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["state"], "EMBEDDED_TARGET_IDENTITY_SHADOW")
        self.assertEqual(row["target_identity_bound_count"], 2)
        self.assertEqual(row["current_year_target_identity_bound_count"], 1)
        current = [item for item in row["bindings"] if item["current_year_label"]][0]
        self.assertEqual(current["state"], "TARGET_IDENTITY_BOUND_SHADOW")
        self.assertEqual(current["target_class"], "GOOGLE_DRIVE_FILE")
        self.assertEqual(current["resource_id"], "DDDDEEEEFFFF33334444")
        self.assertFalse(current["content_fetched"])
        self.assertFalse(row["embedded_targets_fetched"])
        self.assertFalse(row["embedded_document_content_verified"])
        self.assertFalse(row["fact_kernel_promotion_allowed"])
        self.assertFalse(row["writer_allowed"])

    def test_google_drive_icon_is_not_document_identity(self):
        body = b"""<html><body><h1>CONCURS DIRECTORI 2026</h1>
        <a href="https://www.google.com/images/icons/product/drive-32.png">Image</a>
        <span>LISTA POSTURI CONCURS DIRECTORI 2026.pdf</span>
        </body></html>"""
        result = resolve_embedded_target_identities(
            self._embedded(),
            allow_network=True,
            current_year=2026,
            fetcher=lambda url: (body, url, "text/html"),
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["current_year_target_identity_bound_count"], 0)
        current = [item for item in row["bindings"] if item["current_year_label"]][0]
        self.assertEqual(current["reason"], "no_trustworthy_document_target_near_label")

    def test_docs_google_resource_identity_is_supported_without_fetching_content(self):
        body = b"""<html><body><h1>CONCURS DIRECTORI 2026</h1>
        <a href="https://docs.google.com/document/d/DocResource_1234567890/edit">LISTA POSTURI CONCURS DIRECTORI 2026.pdf</a>
        </body></html>"""
        embedded = self._embedded()
        embedded["rows"][0]["embedded_file_labels"] = ["LISTA POSTURI CONCURS DIRECTORI 2026.pdf"]
        result = resolve_embedded_target_identities(
            embedded,
            allow_network=True,
            current_year=2026,
            fetcher=lambda url: (body, url, "text/html"),
        )
        binding = result["rows"][0]["bindings"][0]
        self.assertEqual(binding["target_class"], "GOOGLE_DOCUMENT")
        self.assertTrue(binding["target_identity_verified"])
        self.assertTrue(binding["future_content_fetch_eligible"])
        self.assertFalse(binding["content_fetched"])

    def test_non_live_never_fetches_parent(self):
        called = False
        def fetcher(url):
            nonlocal called
            called = True
            raise AssertionError("network must stay disabled")
        result = resolve_embedded_target_identities(
            self._embedded(),
            allow_network=False,
            current_year=2026,
            fetcher=fetcher,
        )
        self.assertFalse(called)
        self.assertEqual(result["rows"][0]["reason"], "network_read_not_enabled")

    def test_external_parent_is_rejected_before_fetch(self):
        called = False
        def fetcher(url):
            nonlocal called
            called = True
            raise AssertionError("external parent must never be fetched")
        result = resolve_embedded_target_identities(
            self._embedded("https://drive.google.com/file/d/AAAABBBBCCCC11112222/view"),
            allow_network=True,
            current_year=2026,
            fetcher=fetcher,
        )
        self.assertFalse(called)
        self.assertEqual(result["rows"][0]["reason"], "parent_not_first_party_https")


if __name__ == "__main__":
    unittest.main()
