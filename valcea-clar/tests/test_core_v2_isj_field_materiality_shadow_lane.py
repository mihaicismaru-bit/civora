from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_field_materiality_shadow_lane import adjudicate_field_materiality  # noqa: E402


def field(name, value, evidence_id, *, normalized_date=None, calendar=False):
    row = {
        "field": name,
        "value": value,
        "state": "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW" if calendar else "FIELD_EVIDENCE_VERIFIED_SHADOW",
        "field_evidence_id": evidence_id,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
    }
    if normalized_date is not None:
        row["normalized_date"] = normalized_date
    return row


class ISJFieldMaterialityShadowLaneTests(unittest.TestCase):
    def _reports(self):
        field_report = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{
                "state": "FIELD_EVIDENCE_VERIFIED_SHADOW",
                "publication_authority": "NONE",
                "fact_kernel_promotion_allowed": False,
                "writer_allowed": False,
                "fields": [
                    field("contest_session_year", 2026, "isj-field-session"),
                    field("vacant_function_count", 146, "isj-field-count"),
                    field("list_document_date", "2026-08-17", "isj-field-list-date"),
                    field("minimum_preuniversity_seniority_years", 5, "isj-field-seniority"),
                ],
            }],
        }
        calendar_report = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{
                "state": "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW",
                "publication_authority": "NONE",
                "fact_kernel_promotion_allowed": False,
                "writer_allowed": False,
                "fields": [
                    field("calendar_order_date", "2026-08-06", "isj-calendar-field-order", normalized_date=True, calendar=True),
                    field("interview_window_text", "12-27 noiembrie", "isj-calendar-field-interview", normalized_date=False, calendar=True),
                    field("appointment_decision_deadline_text", "Până la data de 16 decembrie", "isj-calendar-field-decision", normalized_date=False, calendar=True),
                    field("appointment_effective_date", "2027-01-01", "isj-calendar-field-effective", normalized_date=True, calendar=True),
                ],
            }],
        }
        return field_report, calendar_report

    def test_materiality_uses_only_exact_normalized_current_fields(self):
        fields, calendar = self._reports()
        result = adjudicate_field_materiality(fields, calendar, as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "MATERIALITY_CANDIDATE_SHADOW")
        self.assertEqual(result["materiality_candidate_count"], 1)
        candidate = result["materiality_candidates"][0]
        self.assertEqual(candidate["contest_session_year"], 2026)
        self.assertEqual(candidate["vacant_function_count"], 146)
        self.assertEqual(candidate["vacancy_list_date"], "2026-08-17")
        self.assertEqual(candidate["appointment_effective_date"], "2027-01-01")
        self.assertEqual(candidate["field_evidence_ids"], ["isj-field-session", "isj-field-count", "isj-field-list-date", "isj-calendar-field-effective"])
        self.assertIn("registration_deadline", candidate["excluded_unverified_or_non_normalized_fields"])
        self.assertIn("interview_window_text", candidate["excluded_unverified_or_non_normalized_fields"])
        self.assertNotIn("isj-calendar-field-interview", candidate["field_evidence_ids"])
        self.assertFalse(result["material_fact_use"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["site_publish_allowed"])
        self.assertFalse(result["social_publish_allowed"])
        self.assertEqual(result["fabricated_claim_count"], 0)

    def test_missing_appointment_date_blocks(self):
        fields, calendar = self._reports()
        calendar["rows"][0]["fields"] = [f for f in calendar["rows"][0]["fields"] if f["field"] != "appointment_effective_date"]
        result = adjudicate_field_materiality(fields, calendar, as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("appointment_effective_date", result["missing_fields"])

    def test_stale_list_terminates_no_story(self):
        fields, calendar = self._reports()
        for f in fields["rows"][0]["fields"]:
            if f["field"] == "list_document_date":
                f["value"] = "2026-01-01"
        result = adjudicate_field_materiality(fields, calendar, as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "NO_STORY")

    def test_wrong_session_year_terminates_no_story(self):
        fields, calendar = self._reports()
        for f in fields["rows"][0]["fields"]:
            if f["field"] == "contest_session_year":
                f["value"] = 2025
        result = adjudicate_field_materiality(fields, calendar, as_of=date(2026, 9, 18))
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["materiality_candidate_count"], 0)

    def test_promotion_boundary_violation_is_rejected(self):
        fields, calendar = self._reports()
        fields["fact_kernel_promotion_allowed"] = True
        with self.assertRaises(ValueError):
            adjudicate_field_materiality(fields, calendar, as_of=date(2026, 9, 18))


if __name__ == "__main__":
    unittest.main()
