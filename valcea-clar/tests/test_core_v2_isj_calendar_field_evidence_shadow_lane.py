from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_calendar_field_evidence_shadow_lane import extract_calendar_field_evidence  # noqa: E402


def _page(number: int, text: str) -> dict:
    return {
        "page_number": number,
        "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "char_count": len(text),
    }


class ISJCalendarFieldEvidenceShadowLaneTests(unittest.TestCase):
    def _context(self) -> dict:
        page1 = _page(1, "ORDIN\nBucurești, 6 august 2026.\n1-4 septembrie\n7-9 septembrie")
        page2 = _page(
            2,
            "12-27 noiembrie Desfășurarea probelor de interviu\n"
            "Până la data de 16 decembrie Emiterea și comunicarea deciziilor de numire, cu intrare în vigoare de la 1 ianuarie 2027",
        )
        return {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "contest_context_verified": True,
            "contest_session_year": 2026,
            "rows": [
                {
                    "state": "BLOCKED",
                    "document_role": "REGISTRATION_NOTICE",
                    "document_label": "Important înscriere concurs Directori.pdf",
                    "contest_session_year": 2026,
                    "contest_session_field_evidence_id": "isj-field-session-2026",
                    "reason": "pdf_text_empty_or_too_short",
                },
                {
                    "state": "DOCUMENT_TEXT_EXTRACTED_SHADOW",
                    "document_role": "CONTEST_CALENDAR",
                    "document_label": "OMEC-4622-CALENDAR-CONCURS-DIRECTORI.pdf",
                    "document_content_evidence_id": "isj-context-document-content",
                    "document_text_evidence_id": "isj-context-document-text",
                    "normalized_text_sha256": "b" * 64,
                    "contest_session_year": 2026,
                    "contest_session_field_evidence_id": "isj-field-session-2026",
                    "pages": [page1, page2],
                },
            ],
        }

    def test_exact_calendar_fields_are_evidence_bound_and_non_authorizing(self):
        result = extract_calendar_field_evidence(self._context(), expected_year=2026)
        self.assertEqual(result["verified_calendar_document_count"], 1)
        self.assertEqual(result["field_evidence_count"], 4)
        self.assertEqual(result["blocked_count"], 0)
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        fields = {field["field"]: field for field in result["rows"][0]["fields"]}
        self.assertEqual(fields["calendar_order_date"]["value"], "2026-08-06")
        self.assertTrue(fields["calendar_order_date"]["normalized_date"])
        self.assertEqual(fields["interview_window_text"]["value"], "12-27 noiembrie")
        self.assertFalse(fields["interview_window_text"]["normalized_date"])
        self.assertEqual(fields["appointment_decision_deadline_text"]["value"], "Până la data de 16 decembrie")
        self.assertFalse(fields["appointment_decision_deadline_text"]["normalized_date"])
        self.assertEqual(fields["appointment_effective_date"]["value"], "2027-01-01")
        self.assertTrue(fields["appointment_effective_date"]["normalized_date"])
        for field in fields.values():
            self.assertEqual(field["contest_session_year"], 2026)
            self.assertEqual(field["contest_session_field_evidence_id"], "isj-field-session-2026")
            self.assertTrue(field["field_evidence_id"].startswith("isj-calendar-field-"))
            self.assertGreater(field["page_number"], 0)
            self.assertTrue(field["page_text_sha256"])
            self.assertFalse(field["material_fact_use"])
            self.assertFalse(field["fact_kernel_promotion_allowed"])
            self.assertFalse(field["writer_allowed"])

    def test_wrong_context_year_blocks(self):
        result = extract_calendar_field_evidence(self._context(), expected_year=2025)
        self.assertEqual(result["verified_calendar_document_count"], 0)
        self.assertEqual(result["field_evidence_count"], 0)
        self.assertEqual(result["blocked_count"], 1)

    def test_missing_exact_calendar_line_fails_closed(self):
        context = self._context()
        context["rows"][1]["pages"][1] = _page(2, "12-27 noiembrie\nPână la data de 16 decembrie")
        result = extract_calendar_field_evidence(context, expected_year=2026)
        self.assertEqual(result["verified_calendar_document_count"], 0)
        self.assertEqual(result["field_evidence_count"], 0)
        self.assertEqual(result["blocked_count"], 1)
        self.assertIn("expected_one_calendar_line", result["rows"][0]["error"])

    def test_duplicate_calendar_documents_fail_closed(self):
        context = self._context()
        context["rows"].append(dict(context["rows"][1]))
        result = extract_calendar_field_evidence(context, expected_year=2026)
        self.assertEqual(result["verified_calendar_document_count"], 0)
        self.assertEqual(result["field_evidence_count"], 0)
        self.assertEqual(result["blocked_count"], 1)
        self.assertEqual(result["rows"][0]["observed_calendar_document_count"], 2)

    def test_registration_pdf_block_does_not_block_verified_calendar(self):
        result = extract_calendar_field_evidence(self._context(), expected_year=2026)
        self.assertEqual(result["verified_calendar_document_count"], 1)
        self.assertEqual(result["rows"][0]["document_role"], "CONTEST_CALENDAR")


if __name__ == "__main__":
    unittest.main()
