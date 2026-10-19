from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "core_v2"))

from public_safety_full_shadow_lane import (  # noqa: E402
    compose_full_shadow_package,
    reconcile_event_time,
    verify_full_receipt,
)
from public_safety_shadow_lane import verify_receipt  # noqa: E402


class PublicSafetyFullShadowLaneTests(unittest.TestCase):
    def _isu_detail(self):
        return {
            "authority_class": "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE",
            "observation_state": "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
            "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            "verification_state": "ISU_SOURCE_TEXT_EVIDENCE_CAPTURED_NON_AUTHORIZING",
            "detail_url": "https://isuvl.igsu.ro/stiri-locale/incendiu-test-123",
            "detail_sha256": "e" * 64,
            "index_evidence_sha256": "f" * 64,
            "index_title": "Incendiu izbucnit într-o gospodărie din localitatea Mădulari",
            "visible_title": "Incendiu izbucnit într-o gospodărie din localitatea Mădulari",
            "explicit_date_text": "18.09.2026",
            "field_evidence": [
                {
                    "excerpt": "Pompierii au intervenit în localitatea Mădulari pentru stingerea incendiului.",
                    "epistemic_tags": ["ISU_REPORTED_OBSERVATION", "RESPONSE_ACTION"],
                    "evidence_sha256": "1" * 64,
                    "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
                {
                    "excerpt": "Sursa menționează o cauză probabilă și un număr raportat de persoane afectate.",
                    "epistemic_tags": ["REPORTED_CAUSE_OR_ORIGIN", "REPORTED_AFFECTED_OR_CASUALTY", "REPORTED_NUMERIC_COUNT"],
                    "evidence_sha256": "2" * 64,
                    "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
                },
            ],
        }

    def _receipt(self, detail):
        return {
            "status": "PASS",
            "authority_class": "FIRST_PARTY_COUNTY_EMERGENCY_ARTICLE_DETAIL_EVIDENCE",
            "observation_state": "ISU_SOURCE_DETAIL_EVIDENCE_NON_AUTHORIZING",
            "source_assertion_scope": "ISU_FIRST_PARTY_STATEMENT_ONLY_NOT_INDEPENDENT_VERIFICATION",
            "material_fact_use": False,
            "fact_kernel_write_authorized": False,
            "details": [detail],
        }

    def test_publication_date_is_not_silently_reused_as_event_time(self):
        detail = self._isu_detail()
        event = reconcile_event_time(detail, source_visible_date=date(2026, 9, 18))
        self.assertEqual(event.status, "UNKNOWN")
        self.assertIsNone(event.event_date)
        result = verify_full_receipt("isu", self._receipt(detail), as_of=date(2026, 9, 18))
        self.assertEqual(result["structured_editorial_count"], 1)
        row = result["rows"][0]
        self.assertEqual(row["currentness"]["event_time"]["status"], "UNKNOWN")
        self.assertFalse(row["currentness"]["publication_date_is_event_time"])
        self.assertIn("momentul evenimentului nu este confirmat separat", row["fact_kernel"]["when"])

    def test_explicit_event_date_and_clock_require_event_role_marker(self):
        detail = self._isu_detail()
        detail["field_evidence"][0]["excerpt"] = (
            "În data de 17 septembrie 2026, în jurul orei 14:30, pompierii au intervenit în localitatea Mădulari."
        )
        event = reconcile_event_time(detail, source_visible_date=date(2026, 9, 18))
        self.assertEqual(event.status, "EXPLICIT_DATETIME")
        self.assertEqual(event.event_date, "2026-09-17")
        self.assertEqual(event.event_time, "14:30")
        self.assertEqual(event.evidence_ids, ("field:" + "1" * 64,))

    def test_multiple_explicit_event_dates_are_ambiguous_not_guessed(self):
        detail = self._isu_detail()
        detail["field_evidence"][0]["excerpt"] = "În data de 17 septembrie 2026 pompierii au intervenit în Mădulari."
        detail["field_evidence"][1]["excerpt"] = "În data de 18 septembrie 2026 a fost consemnată o altă etapă a intervenției."
        event = reconcile_event_time(detail, source_visible_date=date(2026, 9, 18))
        self.assertEqual(event.status, "AMBIGUOUS")
        self.assertIsNone(event.event_date)

    def test_structured_material_facts_are_evidence_bound(self):
        detail = self._isu_detail()
        base = verify_receipt("isu", self._receipt(detail), as_of=date(2026, 9, 18))
        self.assertEqual(base["verified_written_shadow_count"], 1)
        enriched = compose_full_shadow_package("isu", detail, base["rows"][0])
        self.assertEqual(enriched["integrity"]["status"], "PASS")
        self.assertEqual(enriched["integrity"]["fabricated_claims"], 0)
        self.assertGreaterEqual(len(enriched["material_facts"]), 2)
        for fact in enriched["material_facts"]:
            self.assertEqual(fact["epistemic_status"], "ATTRIBUTED_FIRST_PARTY_REPORT")
            self.assertTrue(fact["evidence_ids"][0].startswith("field:"))
        package = enriched["article_package"]
        kernel_claims = enriched["fact_kernel"]["claims"]
        for claim in package["claims"]:
            self.assertEqual(claim["text"], kernel_claims[claim["kernel_claim_index"]])
        self.assertEqual(package["writer_id"], "shadow_structured_editorial_v2")
        self.assertFalse(package["production_writer_ready"])

    def test_future_event_date_relative_to_source_is_flagged(self):
        detail = self._isu_detail()
        detail["field_evidence"][0]["excerpt"] = "În data de 21 septembrie 2026 pompierii au intervenit în Mădulari."
        event = reconcile_event_time(detail, source_visible_date=date(2026, 9, 18))
        self.assertEqual(event.status, "ANOMALOUS_FUTURE")
        self.assertEqual(event.event_date, "2026-09-21")


if __name__ == "__main__":
    unittest.main()
