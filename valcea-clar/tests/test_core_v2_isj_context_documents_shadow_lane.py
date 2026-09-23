from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_context_documents_shadow_lane import capture_context_documents  # noqa: E402


def _page(text: str) -> dict:
    return {
        "page_number": 1,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
    }


class ISJContextDocumentsShadowLaneTests(unittest.TestCase):
    def _targets(self) -> dict:
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [
                {
                    "state": "EMBEDDED_TARGET_IDENTITY_SHADOW",
                    "signal_id": "isj-ref-x",
                    "evidence_id": "isj-detail-x",
                    "label": "concurs directori 2026",
                    "bindings": [
                        {
                            "state": "TARGET_IDENTITY_BOUND_SHADOW",
                            "label": "Important inscriere concurs Directori.pdf",
                            "target_identity_verified": True,
                            "future_content_fetch_eligible": True,
                            "target_class": "GOOGLE_DRIVE_FILE",
                            "resource_id": "AAAABBBBCCCC11112222",
                        },
                        {
                            "state": "TARGET_IDENTITY_BOUND_SHADOW",
                            "label": "OMEC-4622-CALENDAR-CONCURS-DIRECTORI.pdf",
                            "target_identity_verified": True,
                            "future_content_fetch_eligible": True,
                            "target_class": "GOOGLE_DRIVE_FILE",
                            "resource_id": "DDDDEEEEFFFF33334444",
                        },
                        {
                            "state": "TARGET_IDENTITY_BOUND_SHADOW",
                            "label": "Procedura concurs directori.pdf",
                            "target_identity_verified": True,
                            "future_content_fetch_eligible": True,
                            "target_class": "GOOGLE_DRIVE_FILE",
                            "resource_id": "GGGGHHHHIIII55556666",
                        },
                        {
                            "state": "TARGET_IDENTITY_BOUND_SHADOW",
                            "label": "LISTA POSTURI CONCURS DIRECTORI 2026.pdf",
                            "target_identity_verified": True,
                            "future_content_fetch_eligible": True,
                            "target_class": "GOOGLE_DRIVE_FILE",
                            "resource_id": "JJJJKKKKLLLL77778888",
                        },
                    ],
                }
            ],
        }

    def _fields(self, year: int = 2026) -> dict:
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [
                {
                    "state": "FIELD_EVIDENCE_VERIFIED_SHADOW",
                    "fields": [
                        {
                            "state": "FIELD_EVIDENCE_VERIFIED_SHADOW",
                            "field": "contest_session_year",
                            "value": year,
                            "field_evidence_id": "isj-field-year-2026",
                            "document_text_evidence_id": "isj-document-text-vacancy",
                            "page_number": 1,
                            "page_text_sha256": "a" * 64,
                        }
                    ],
                }
            ],
        }

    @staticmethod
    def _extractor(_: bytes) -> dict:
        text = "Calendar concurs directori. Inscrierile se fac conform documentului oficial."
        page = _page(text)
        return {
            "normalized_text": text,
            "normalized_text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "page_count_observed": 1,
            "nonempty_page_count": 1,
            "nonempty_char_count": len(text),
            "normalization": "test",
            "extractor_provenance": {
                "name": "test_extractor",
                "version": "1",
                "args": [],
                "timeout_seconds": 1,
                "shell": False,
                "ocr_used": False,
            },
            "pages": [page],
        }

    def test_verified_contest_context_allows_role_routing_without_filename_year_inference(self):
        calls: list[str] = []

        def fetcher(url: str):
            calls.append(url)
            return b"%PDF-1.4\ncontext", url, "application/pdf"

        result = capture_context_documents(
            self._targets(),
            self._fields(),
            allow_network=True,
            expected_year=2026,
            fetcher=fetcher,
            extractor=self._extractor,
        )
        self.assertTrue(result["contest_context_verified"])
        self.assertEqual(result["selected_context_document_count"], 3)
        self.assertEqual(result["document_text_extracted_shadow_count"], 3)
        self.assertEqual(result["blocked_count"], 0)
        self.assertEqual(
            result["selected_roles"],
            ["CONTEST_CALENDAR", "CONTEST_PROCEDURE", "REGISTRATION_NOTICE"],
        )
        self.assertEqual(len(calls), 3)
        for row in result["rows"]:
            self.assertEqual(row["contest_session_year"], 2026)
            self.assertEqual(row["contest_session_field_evidence_id"], "isj-field-year-2026")
            self.assertEqual(row["context_binding_method"], "verified_contest_session_field_evidence_plus_same_parent_document_target")
            self.assertFalse(row["deadline_verified"])
            self.assertFalse(row["calendar_verified"])
            self.assertFalse(row["event_time_verified"])
            self.assertFalse(row["fact_kernel_promotion_allowed"])
            self.assertFalse(row["writer_allowed"])

    def test_missing_verified_session_context_blocks_before_network(self):
        called = False

        def fetcher(url: str):
            nonlocal called
            called = True
            raise AssertionError("network must not be used without verified contest context")

        result = capture_context_documents(
            self._targets(),
            {"publication_authority": "NONE", "fact_kernel_promotion_allowed": False, "writer_allowed": False, "rows": []},
            allow_network=True,
            expected_year=2026,
            fetcher=fetcher,
            extractor=self._extractor,
        )
        self.assertFalse(called)
        self.assertFalse(result["contest_context_verified"])
        self.assertEqual(result["selected_context_document_count"], 0)
        self.assertEqual(result["blocked_count"], 1)

    def test_wrong_year_context_does_not_authorize_sibling_documents(self):
        called = False

        def fetcher(url: str):
            nonlocal called
            called = True
            raise AssertionError("wrong-year context must fail closed")

        result = capture_context_documents(
            self._targets(),
            self._fields(year=2025),
            allow_network=True,
            expected_year=2026,
            fetcher=fetcher,
            extractor=self._extractor,
        )
        self.assertFalse(called)
        self.assertFalse(result["contest_context_verified"])
        self.assertEqual(result["blocked_count"], 1)

    def test_non_live_keeps_selected_documents_blocked_without_fetch(self):
        called = False

        def fetcher(url: str):
            nonlocal called
            called = True
            raise AssertionError("network must stay disabled")

        result = capture_context_documents(
            self._targets(),
            self._fields(),
            allow_network=False,
            expected_year=2026,
            fetcher=fetcher,
            extractor=self._extractor,
        )
        self.assertFalse(called)
        self.assertTrue(result["contest_context_verified"])
        self.assertEqual(result["selected_context_document_count"], 3)
        self.assertEqual(result["blocked_count"], 3)
        self.assertEqual(result["document_text_extracted_shadow_count"], 0)

    def test_unverified_target_identity_is_not_selected(self):
        targets = self._targets()
        targets["rows"][0]["bindings"][0]["target_identity_verified"] = False
        result = capture_context_documents(
            targets,
            self._fields(),
            allow_network=False,
            expected_year=2026,
        )
        self.assertEqual(result["selected_context_document_count"], 2)


if __name__ == "__main__":
    unittest.main()
