from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_embedded_notice_shadow_lane import resolve_embedded_notice_evidence  # noqa: E402


class ISJEmbeddedNoticeShadowLaneTests(unittest.TestCase):
    def _reports(self, body: bytes, *, url: str = "https://www.isjvalcea.ro/management/concurs-directori-2026"):
        sha = hashlib.sha256(body).hexdigest()
        detail = {
            "publication_authority": "NONE",
            "rows": [{
                "signal_id": "isj-ref-x",
                "evidence_id": "isj-detail-x",
                "topic_class": "STAFFING_MANAGEMENT",
                "label": "concurs directori 2026",
                "detail_url": url,
                "detail_sha256": sha,
                "state": "DETAIL_EVIDENCE_SHADOW",
                "detail_readback_verified": True,
            }],
        }
        materiality = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{
                "signal_id": "isj-ref-x",
                "evidence_id": "isj-detail-x",
                "topic_class": "STAFFING_MANAGEMENT",
                "label": "concurs directori 2026",
                "detail_url": url,
                "state": "BLOCKED",
                "reason": "current_year_detail_without_explicit_material_event",
                "embedded_file_or_notice_evidence_required": True,
            }],
        }
        return detail, materiality

    def test_current_year_embedded_catalog_is_evidence_only(self):
        body = b"""<html><body><h1>CONCURS DIRECTORI 2026</h1>
        <div>Important inscriere concurs Directori.pdf</div>
        <div>LISTA POSTURI CONCURS DIRECTORI 2026.pdf</div>
        <div>OMEC-4622-CALENDAR-CONCURS-DIRECTORI.pdf</div>
        <div>OMEC-4155-Metodologie CONCURS DIRECTORI 2026.pdf</div>
        </body></html>"""
        detail, materiality = self._reports(body)
        result = resolve_embedded_notice_evidence(detail, materiality, allow_network=True, current_year=2026, fetcher=lambda url: (body, url, "text/html"))
        self.assertEqual(result["embedded_notice_evidence_shadow_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["state"], "EMBEDDED_NOTICE_EVIDENCE_SHADOW")
        self.assertTrue(row["registration_notice_present"])
        self.assertTrue(row["vacancy_list_present"])
        self.assertTrue(row["calendar_document_present"])
        self.assertGreaterEqual(row["current_year_embedded_label_count"], 1)
        self.assertFalse(row["embedded_targets_fetched"])
        self.assertFalse(row["fact_kernel_promotion_allowed"])
        self.assertFalse(row["writer_allowed"])
        self.assertFalse(row["event_time_verified"])
        self.assertFalse(row["deadline_verified"])

    def test_changed_parent_bytes_fail_closed(self):
        body = b"<html><body>LISTA POSTURI CONCURS DIRECTORI 2026.pdf</body></html>"
        detail, materiality = self._reports(body)
        changed = body + b" changed"
        result = resolve_embedded_notice_evidence(detail, materiality, allow_network=True, current_year=2026, fetcher=lambda url: (changed, url, "text/html"))
        self.assertEqual(result["rows"][0]["reason"], "detail_changed_since_verified_evidence")

    def test_external_parent_is_never_fetched(self):
        body = b"<html><body>LISTA POSTURI CONCURS DIRECTORI 2026.pdf</body></html>"
        detail, materiality = self._reports(body, url="https://drive.google.com/file/d/x")
        called = False
        def fetcher(url):
            nonlocal called
            called = True
            raise AssertionError("must not fetch external parent")
        result = resolve_embedded_notice_evidence(detail, materiality, allow_network=True, current_year=2026, fetcher=fetcher)
        self.assertFalse(called)
        self.assertEqual(result["rows"][0]["reason"], "embedded_catalog_parent_not_first_party_https")

    def test_no_document_labels_stays_blocked(self):
        body = b"<html><body><h1>CONCURS DIRECTORI 2026</h1><p>Pagina de categorie.</p></body></html>"
        detail, materiality = self._reports(body)
        result = resolve_embedded_notice_evidence(detail, materiality, allow_network=True, current_year=2026, fetcher=lambda url: (body, url, "text/html"))
        self.assertEqual(result["embedded_notice_evidence_shadow_count"], 0)
        self.assertEqual(result["rows"][0]["reason"], "no_embedded_document_labels_observed")

    def test_year_in_category_only_does_not_promote(self):
        body = b"<html><body><h1>CONCURS DIRECTORI 2026</h1><div>Procedura inscriere concurs.pdf</div><div>Calendar concurs.pdf</div></body></html>"
        detail, materiality = self._reports(body)
        result = resolve_embedded_notice_evidence(detail, materiality, allow_network=True, current_year=2026, fetcher=lambda url: (body, url, "text/html"))
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertEqual(row["reason"], "embedded_catalog_present_but_current_materiality_unproven")
        self.assertEqual(row["current_year_embedded_label_count"], 0)


if __name__ == "__main__":
    unittest.main()
