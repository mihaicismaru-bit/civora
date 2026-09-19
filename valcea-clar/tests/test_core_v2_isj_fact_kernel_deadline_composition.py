from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_article_integrity import verify_isj_article_integrity  # noqa: E402
from isj_fact_kernel_integrity import verify_fact_kernel_integrity  # noqa: E402
from isj_fact_kernel_shadow_lane import compose_isj_fact_kernel  # noqa: E402
from isj_writer_shadow_lane import compose_isj_article  # noqa: E402


def field(name, value, evidence_id, state="FIELD_EVIDENCE_VERIFIED_SHADOW"):
    return {
        "field": name,
        "value": value,
        "state": state,
        "field_evidence_id": evidence_id,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
    }


class ISJFactKernelDeadlineCompositionTests(unittest.TestCase):
    def _inputs(self):
        ids = {
            "session": "isj-field-session",
            "count": "isj-field-count",
            "list_date": "isj-field-list-date",
            "appointment": "isj-calendar-field-appointment",
            "deadline": "isj-calendar-field-registration-deadline",
            "scope": "isj-calendar-scope-registration-window",
            "raw": "isj-calendar-field-registration-window-text",
            "document": "isj-calendar-document-text",
            "materiality_promotion": "isj-deadline-promotion-test",
            "fact_promotion": "isj-fact-kernel-deadline-promotion-test",
        }
        page_hash = "a" * 64
        excerpt = "Înscrierea candidaților: 14 septembrie - 2 octombrie."
        fields = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{"fields": [
                field("contest_session_year", 2026, ids["session"]),
                field("vacant_function_count", 146, ids["count"]),
                field("list_document_date", "2026-08-17", ids["list_date"]),
            ]}],
        }
        calendar = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "rows": [{"fields": [
                field("appointment_effective_date", "2027-01-01", ids["appointment"], "CALENDAR_FIELD_EVIDENCE_VERIFIED_SHADOW")
            ]}],
        }
        promoted = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "field_evidence_id": ids["deadline"],
            "promotion_evidence_id": ids["materiality_promotion"],
            "scope_field_evidence_id": ids["scope"],
            "source_registration_window_field_evidence_id": ids["raw"],
            "supporting_field_evidence_ids": [ids["scope"], ids["raw"]],
            "document_text_evidence_id": ids["document"],
            "page_number": 1,
            "page_text_sha256": page_hash,
            "excerpt": excerpt,
        }
        existing = [ids["session"], ids["count"], ids["list_date"], ids["appointment"]]
        materiality = {
            "publication_authority": "NONE",
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "state": "MATERIALITY_CANDIDATE_SHADOW",
            "materiality_candidates": [{
                "category": "LOCAL_EDUCATION_LEADERSHIP",
                "contest_session_year": 2026,
                "vacant_function_count": 146,
                "vacancy_list_date": "2026-08-17",
                "appointment_effective_date": "2027-01-01",
                "registration_deadline": "2026-10-02",
                "materiality_only_promoted_fields": {"registration_deadline": promoted},
                "field_evidence_ids": existing,
                "excluded_unverified_or_non_normalized_fields": [
                    "registration_deadline", "interview_window_text", "appointment_decision_deadline_text"
                ],
                "fact_kernel_status": "NOT_PROMOTED",
            }],
        }
        promotion_candidate = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "state": "FACT_KERNEL_FIELD_PROMOTION_VERIFIED_SHADOW",
            "field_evidence_id": ids["deadline"],
            "upstream_materiality_promotion_evidence_id": ids["materiality_promotion"],
            "fact_kernel_promotion_evidence_id": ids["fact_promotion"],
            "scope_field_evidence_id": ids["scope"],
            "source_registration_window_field_evidence_id": ids["raw"],
            "supporting_field_evidence_ids": [ids["scope"], ids["raw"]],
            "document_text_evidence_id": ids["document"],
            "page_number": 1,
            "page_text_sha256": page_hash,
            "excerpt": excerpt,
            "existing_fact_kernel_field_evidence_ids": existing,
            "fact_kernel_promotion_allowed": True,
            "writer_allowed": False,
        }
        promotion = {
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "state": "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW",
            "registration_deadline": "2026-10-02",
            "upstream_materiality_promotion_evidence_id": ids["materiality_promotion"],
            "fact_kernel_promotion_evidence_id": ids["fact_promotion"],
            "promotion_candidate_count": 1,
            "promotion_candidates": [promotion_candidate],
            "fact_kernel_promotion_allowed": True,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        validation = {
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "status": "PASS_SHADOW",
            "registration_deadline": "2026-10-02",
            "registration_deadline_field_evidence_id": ids["deadline"],
            "upstream_materiality_promotion_evidence_id": ids["materiality_promotion"],
            "fact_kernel_promotion_evidence_id": ids["fact_promotion"],
            "scope_field_evidence_id": ids["scope"],
            "source_registration_window_field_evidence_id": ids["raw"],
            "supporting_field_evidence_ids": [ids["scope"], ids["raw"]],
            "document_text_evidence_id": ids["document"],
            "page_number": 1,
            "page_text_sha256": page_hash,
            "excerpt": excerpt,
            "fact_kernel_promotion_allowed": True,
            "writer_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
        }
        return materiality, fields, calendar, promotion, validation

    def test_deadline_enters_fact_kernel_composition_without_writer_projection(self):
        materiality, fields, calendar, promotion, validation = self._inputs()
        fact = compose_isj_fact_kernel(materiality, fields, calendar, fact_deadline_promotion=promotion, fact_deadline_promotion_validation=validation)
        self.assertEqual(fact["state"], "FACT_KERNEL_VERIFIED_SHADOW")
        self.assertTrue(fact["fact_kernel_deadline_composition_consumed"])
        self.assertEqual(fact["promoted_fact_claim_count"], 1)
        row = fact["kernels"][0]
        promoted = row["promoted_fact_claims"][0]
        self.assertEqual(promoted["value"], "2026-10-02")
        self.assertIn("2 octombrie 2026", promoted["claim"])
        self.assertFalse(promoted["writer_projection_allowed"])
        self.assertEqual(len(row["fact_kernel"]["claims"]), 2)
        self.assertNotIn("2 octombrie 2026", " ".join(row["fact_kernel"]["claims"]))

        integrity = verify_fact_kernel_integrity(fact, promotion, validation)
        self.assertEqual(integrity["status"], "PASS_SHADOW")
        self.assertEqual(integrity["promoted_fact_verified_count"], 1)
        self.assertEqual(integrity["fabricated_claim_count"], 0)
        self.assertFalse(integrity["writer_deadline_projection_allowed"])

        article = compose_isj_article(fact, integrity)
        self.assertEqual(article["state"], "WRITTEN_SHADOW_PENDING_ARTICLE_INTEGRITY")
        self.assertNotIn("2 octombrie 2026", article["articles"][0]["article_package"]["body"])
        article_integrity = verify_isj_article_integrity(fact, integrity, article)
        self.assertEqual(article_integrity["status"], "PASS_SHADOW")

    def test_tampered_promoted_fact_binding_fails_integrity(self):
        materiality, fields, calendar, promotion, validation = self._inputs()
        fact = compose_isj_fact_kernel(materiality, fields, calendar, fact_deadline_promotion=promotion, fact_deadline_promotion_validation=validation)
        tampered = copy.deepcopy(fact)
        tampered["kernels"][0]["promoted_fact_claims"][0]["page_text_sha256"] = "0" * 64
        integrity = verify_fact_kernel_integrity(tampered, promotion, validation)
        self.assertEqual(integrity["status"], "BLOCKED")
        self.assertGreaterEqual(integrity["fabricated_claim_count"], 1)
        self.assertIn("deadline_promoted_fact_identity_mismatch:page_text_sha256", integrity["failures"])

    def test_promoted_fact_without_independent_upstream_validation_fails_closed(self):
        materiality, fields, calendar, promotion, validation = self._inputs()
        fact = compose_isj_fact_kernel(materiality, fields, calendar, fact_deadline_promotion=promotion, fact_deadline_promotion_validation=validation)
        integrity = verify_fact_kernel_integrity(fact)
        self.assertEqual(integrity["status"], "BLOCKED")
        self.assertIn("deadline_promoted_fact_missing_independent_upstream_evidence", integrity["failures"])


if __name__ == "__main__":
    unittest.main()
