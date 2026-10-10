from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_embedded_content_shadow_lane import capture_verified_document_contents  # noqa: E402


class ISJEmbeddedContentShadowLaneTests(unittest.TestCase):
    def _target_report(self):
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{
                "signal_id": "isj-ref-x",
                "evidence_id": "isj-detail-x",
                "topic_class": "STAFFING_MANAGEMENT",
                "label": "concurs directori 2026",
                "state": "EMBEDDED_TARGET_IDENTITY_SHADOW",
                "bindings": [{
                    "label": "LISTA POSTURI CONCURS DIRECTORI 2026.pdf",
                    "state": "TARGET_IDENTITY_BOUND_SHADOW",
                    "target_identity_verified": True,
                    "target_class": "GOOGLE_DRIVE_FILE",
                    "resource_id": "DDDDEEEEFFFF33334444",
                    "current_year_label": True,
                    "future_content_fetch_eligible": True,
                }],
            }],
        }

    def _extraction(self, text="Pagina oficiala concurs directori 2026\nLista posturilor vacante publicata oficial."):
        text_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return {
            "normalized_text": text,
            "normalized_text_sha256": text_sha,
            "page_count_observed": 1,
            "nonempty_page_count": 1,
            "nonempty_char_count": len(text),
            "normalization": "fixture-normalization",
            "pages": [{
                "page_number": 1,
                "text": text,
                "text_sha256": text_sha,
                "char_count": len(text),
            }],
            "extractor_provenance": {
                "name": "fixture_pdftotext",
                "version": "fixture-1",
                "args": ["-layout", "-enc", "UTF-8", "-eol", "unix"],
                "shell": False,
                "ocr_used": False,
            },
        }

    def test_verified_pdf_text_is_extracted_but_not_promoted(self):
        pdf = b"%PDF-1.7\nshadow-test\n%%EOF\n"
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (pdf, "https://drive.usercontent.google.com/download?id=DDDDEEEEFFFF33334444", "application/pdf"),
            extractor=lambda body: self._extraction(),
        )
        self.assertEqual(result["selected_document_count"], 1)
        self.assertEqual(result["document_content_captured_shadow_count"], 1)
        self.assertEqual(result["document_text_extracted_shadow_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["state"], "DOCUMENT_TEXT_EXTRACTED_SHADOW")
        self.assertTrue(row["content_verified"])
        self.assertEqual(row["content_container"], "PDF")
        self.assertTrue(row["document_content_evidence_id"].startswith("isj-document-"))
        self.assertTrue(row["document_text_evidence_id"].startswith("isj-document-text-"))
        self.assertFalse(row["raw_bytes_persisted"])
        self.assertTrue(row["text_extracted"])
        self.assertEqual(row["extractor_provenance"]["name"], "fixture_pdftotext")
        self.assertFalse(row["extractor_provenance"]["ocr_used"])
        self.assertFalse(row["field_extraction_allowed"])
        self.assertFalse(row["fact_kernel_promotion_allowed"])
        self.assertFalse(row["writer_allowed"])

    def test_text_hash_mismatch_is_rejected(self):
        pdf = b"%PDF-1.7\nshadow-test\n%%EOF\n"
        extraction = self._extraction()
        extraction["normalized_text_sha256"] = "0" * 64
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (pdf, "https://drive.usercontent.google.com/download?id=DDDDEEEEFFFF33334444", "application/pdf"),
            extractor=lambda body: extraction,
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertIn("pdf_text_sha256_mismatch", row["error"])
        self.assertFalse(row["text_extracted"])

    def test_empty_extracted_text_is_rejected(self):
        pdf = b"%PDF-1.7\nshadow-test\n%%EOF\n"
        extraction = self._extraction("x")
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (pdf, "https://drive.usercontent.google.com/download?id=DDDDEEEEFFFF33334444", "application/pdf"),
            extractor=lambda body: extraction,
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertIn("pdf_text_empty_or_too_short", row["error"])

    def test_html_interstitial_is_rejected(self):
        html = b"<html><body>Google Drive warning</body></html>"
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (html, "https://drive.usercontent.google.com/download?id=DDDDEEEEFFFF33334444", "text/html"),
            extractor=lambda body: self._extraction(),
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertFalse(row["content_verified"])
        self.assertIn("document_content_type_not_allowlisted", row["error"])

    def test_unknown_octet_stream_magic_is_rejected(self):
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (b"not-a-document", "https://drive.usercontent.google.com/download?id=DDDDEEEEFFFF33334444", "application/octet-stream"),
            extractor=lambda body: self._extraction(),
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertFalse(row["content_verified"])
        self.assertIn("octet_stream_magic_unrecognized", row["error"])

    def test_redirect_to_untrusted_host_is_rejected(self):
        pdf = b"%PDF-1.7\nshadow-test\n%%EOF\n"
        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=True,
            fetcher=lambda url: (pdf, "https://example.com/file.pdf", "application/pdf"),
            extractor=lambda body: self._extraction(),
        )
        row = result["rows"][0]
        self.assertEqual(row["state"], "BLOCKED")
        self.assertFalse(row["content_verified"])
        self.assertIn("document_redirect_host_not_allowlisted", row["error"])

    def test_non_live_does_not_fetch_or_extract(self):
        called = False
        extracted = False

        def fetcher(url):
            nonlocal called
            called = True
            raise AssertionError("network must stay disabled")

        def extractor(body):
            nonlocal extracted
            extracted = True
            raise AssertionError("extractor must stay disabled")

        result = capture_verified_document_contents(
            self._target_report(),
            allow_network=False,
            fetcher=fetcher,
            extractor=extractor,
        )
        self.assertFalse(called)
        self.assertFalse(extracted)
        self.assertEqual(result["rows"][0]["reason"], "network_read_not_enabled")

    def test_non_current_binding_is_not_selected(self):
        report = self._target_report()
        report["rows"][0]["bindings"][0]["current_year_label"] = False
        result = capture_verified_document_contents(
            report,
            allow_network=True,
            fetcher=lambda url: (_ for _ in ()).throw(AssertionError()),
            extractor=lambda body: (_ for _ in ()).throw(AssertionError()),
        )
        self.assertEqual(result["selected_document_count"], 0)
        self.assertEqual(result["rows"], [])


if __name__ == "__main__":
    unittest.main()
