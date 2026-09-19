from __future__ import annotations

import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_field_materiality_shadow_lane import adjudicate_field_materiality  # noqa: E402
from isj_registration_deadline_promotion_shadow_lane import build_deadline_promotion  # noqa: E402
from validate_isj_registration_deadline_promotion import prove_tamper_regressions, validate as validate_deadline_promotion  # noqa: E402


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

    def _deadline_scope_fixtures(self):
        scope_id = "isj-calendar-scope-scope-001"
        raw_id = "isj-calendar-field-registration-001"
        deadline_id = "isj-calendar-scope-deadline-001"
        document_id = "isj-context-document-001"
        page_hash = "a" * 64
        excerpt = "14 septembrie-2 octombrie"
        scope = {
            "schema_version": "1.0",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "expected_contest_session_year": 2026,
            "same_document_year_scope_verified": True,
            "registration_deadline_normalized": True,
            "registration_deadline": "2026-10-02",
            "calendar_scope_session_year_field_evidence_id": scope_id,
            "registration_source_field_evidence_id": raw_id,
            "rows": [{
                "state": "CALENDAR_SCOPE_BINDING_VERIFIED_SHADOW",
                "contest_session_year": 2026,
                "fields": [{
                    "field": "registration_deadline",
                    "value": "2026-10-02",
                    "state": "CALENDAR_SCOPE_FIELD_EVIDENCE_VERIFIED_SHADOW",
                    "normalized_date": True,
                    "field_evidence_id": deadline_id,
                    "scope_field_evidence_id": scope_id,
                    "source_registration_window_field_evidence_id": raw_id,
                    "supporting_field_evidence_ids": [scope_id, raw_id],
                    "document_text_evidence_id": document_id,
                    "page_number": 1,
                    "page_text_sha256": page_hash,
                    "excerpt": excerpt,
                    "material_fact_use": False,
                    "fact_kernel_promotion_allowed": False,
                    "writer_allowed": False,
                }],
            }],
        }
        scope_validation = {
            "status": "PASS_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "same_document_year_scope_verified": True,
            "registration_deadline": "2026-10-02",
            "scope_field_evidence_id": scope_id,
            "source_registration_window_field_evidence_id": raw_id,
        }
        return scope, scope_validation

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

    def test_registration_deadline_promotion_requires_independent_scope_validation(self):
        scope, validation = self._deadline_scope_fixtures()
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "MATERIALITY_PROMOTION_VERIFIED_SHADOW")
        self.assertTrue(result["materiality_promotion_allowed"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertEqual(result["registration_deadline"], "2026-10-02")
        candidate = result["promotion_candidates"][0]
        self.assertEqual(candidate["field_evidence_id"], "isj-calendar-scope-deadline-001")
        self.assertEqual(candidate["supporting_field_evidence_ids"], ["isj-calendar-scope-scope-001", "isj-calendar-field-registration-001"])
        independent = validate_deadline_promotion(scope, validation, result, expected_year=2026)
        self.assertEqual(independent["status"], "PASS_SHADOW")
        self.assertEqual(independent["registration_deadline_field_evidence_id"], "isj-calendar-scope-deadline-001")
        self.assertEqual(prove_tamper_regressions(scope, validation, result, expected_year=2026), 3)

    def test_registration_deadline_promotion_fails_closed_on_evidence_divergence(self):
        scope, validation = self._deadline_scope_fixtures()
        validation["registration_deadline"] = "2026-10-03"
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["materiality_promotion_allowed"])
        self.assertEqual(result["promotion_candidate_count"], 0)


if __name__ == "__main__":
    unittest.main()
