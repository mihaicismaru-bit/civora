from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_fact_kernel_integrity import verify_fact_kernel_integrity  # noqa: E402
from isj_fact_kernel_shadow_lane import compose_isj_fact_kernel  # noqa: E402


def field(name, value, evidence_id, state="FIELD_EVIDENCE_VERIFIED_SHADOW"):
    return {"field": name, "value": value, "state": state, "field_evidence_id": evidence_id, "fact_kernel_promotion_allowed": False, "writer_allowed": False}


class ISJFactKernelShadowLaneTests(unittest.TestCase):
    def _inputs(self):
        ids = {
            "session": "isj-field-session",
            "count": "isj-field-count",
            "list_date": "isj-field-list-date",
            "appointment": "isj-calendar-field-appointment",
        }
        fields = {
            "publication_authority": "NONE", "fact_kernel_promotion_allowed": False, "writer_allowed": False,
            "rows": [{"fields": [field("contest_session_year", 2026, ids["session"]), field("vacant_function_count", 146, ids["count"]), field("list_document_date", "2026-08-17", ids["list_date"])]}],
        }
        calendar = {
            "publication_authority": "NONE", "fact_kernel_promotion_allowed": False, "writer_allowed": False,
            "rows": [{"fields": [field("appointment_effective_date", "2027-01-01", ids["appointment"], "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW")]}],
        }
        materiality = {
            "publication_authority": "NONE", "fact_kernel_promotion_allowed": False, "writer_allowed": False,
            "state": "MATERIALITY_CANDIDATE_SHADOW",
            "materiality_candidates": [{
                "category": "LOCAL_EDUCATION_LEADERSHIP",
                "contest_session_year": 2026,
                "vacant_function_count": 146,
                "vacancy_list_date": "2026-08-17",
                "appointment_effective_date": "2027-01-01",
                "field_evidence_ids": [ids["session"], ids["count"], ids["list_date"], ids["appointment"]],
                "excluded_unverified_or_non_normalized_fields": ["registration_deadline", "interview_window_text", "appointment_decision_deadline_text"],
                "fact_kernel_status": "NOT_PROMOTED",
            }],
        }
        return materiality, fields, calendar

    def test_compose_and_integrity_pass_without_writer_authority(self):
        materiality, fields, calendar = self._inputs()
        result = compose_isj_fact_kernel(materiality, fields, calendar)
        self.assertEqual(result["state"], "FACT_KERNEL_VERIFIED_SHADOW")
        self.assertEqual(result["fact_kernel_count"], 1)
        self.assertFalse(result["writer_allowed"])
        row = result["kernels"][0]
        self.assertEqual(len(row["fact_kernel"]["claims"]), 2)
        self.assertEqual(len(row["fact_kernel"]["evidence_ids"]), 4)
        self.assertEqual(row["integrity_status"], "PENDING_SEPARATE_GATE")
        integrity = verify_fact_kernel_integrity(result)
        self.assertEqual(integrity["status"], "PASS_SHADOW")
        self.assertEqual(integrity["verified_claim_count"], 2)
        self.assertEqual(integrity["fabricated_claim_count"], 0)
        self.assertFalse(integrity["writer_allowed"])

    def test_candidate_value_mismatch_blocks_kernel(self):
        materiality, fields, calendar = self._inputs()
        materiality["materiality_candidates"][0]["vacant_function_count"] = 147
        result = compose_isj_fact_kernel(materiality, fields, calendar)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertEqual(result["fact_kernel_count"], 0)

    def test_unverified_claim_fails_separate_integrity_gate(self):
        materiality, fields, calendar = self._inputs()
        result = compose_isj_fact_kernel(materiality, fields, calendar)
        row = result["kernels"][0]
        bad = "Înscrierile se încheie la 30 septembrie 2026."
        row["fact_kernel"]["claims"].append(bad)
        integrity = verify_fact_kernel_integrity(result)
        self.assertEqual(integrity["status"], "BLOCKED")
        self.assertGreaterEqual(integrity["fabricated_claim_count"], 1)

    def test_materiality_without_candidate_does_not_promote(self):
        materiality, fields, calendar = self._inputs()
        materiality["state"] = "NO_STORY"
        materiality["materiality_candidates"] = []
        result = compose_isj_fact_kernel(materiality, fields, calendar)
        self.assertEqual(result["state"], "NO_STORY")
        self.assertEqual(result["fact_kernel_count"], 0)


if __name__ == "__main__":
    unittest.main()
