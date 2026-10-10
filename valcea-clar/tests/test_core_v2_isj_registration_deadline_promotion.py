from __future__ import annotations

import copy
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_registration_deadline_promotion_shadow_lane import build_deadline_promotion  # noqa: E402
from validate_isj_registration_deadline_promotion import prove_tamper_regressions, validate  # noqa: E402
from isj_fact_kernel_deadline_promotion_shadow_lane import build_fact_kernel_deadline_promotion  # noqa: E402
from validate_isj_fact_kernel_deadline_promotion import (  # noqa: E402
    prove_tamper_regressions as prove_fact_kernel_tamper_regressions,
    validate as validate_fact_kernel_promotion,
)


class ISJRegistrationDeadlinePromotionTests(unittest.TestCase):
    def _fixtures(self):
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

    def _materiality_fixture(self, promotion, independent):
        promoted = copy.deepcopy(promotion["promotion_candidates"][0])
        existing_ids = [
            "isj-field-session-001",
            "isj-field-vacancies-001",
            "isj-field-list-date-001",
            "isj-calendar-appointment-001",
        ]
        return {
            "source_kind": "isj_valcea",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "material_fact_use": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "production_writer_ready": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "mode": "ISJ_FIELD_MATERIALITY_SHADOW",
            "state": "MATERIALITY_CANDIDATE_SHADOW",
            "materiality_candidate_count": 1,
            "registration_deadline_materiality_consumed": True,
            "registration_deadline": promotion["registration_deadline"],
            "registration_deadline_promotion_evidence_id": promotion["promotion_evidence_id"],
            "unresolved_fields": [],
            "materiality_candidates": [{
                "category": "LOCAL_EDUCATION_LEADERSHIP",
                "contest_session_year": 2026,
                "vacant_function_count": 12,
                "vacancy_list_date": "2026-09-10",
                "appointment_effective_date": "2026-12-21",
                "registration_deadline": promotion["registration_deadline"],
                "field_evidence_ids": existing_ids,
                "materiality_only_promoted_fields": {
                    "registration_deadline": promoted,
                },
                "excluded_unverified_or_non_normalized_fields": [
                    "registration_deadline",
                    "interview_window_text",
                    "appointment_decision_deadline_text",
                ],
                "fact_kernel_status": "NOT_PROMOTED",
            }],
            "fabricated_claim_count": 0,
        }

    def test_gate_promotes_only_to_materiality_and_preserves_exact_identity(self):
        scope, validation = self._fixtures()
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "MATERIALITY_PROMOTION_VERIFIED_SHADOW")
        self.assertTrue(result["materiality_promotion_allowed"])
        self.assertFalse(result["fact_kernel_promotion_allowed"])
        self.assertFalse(result["writer_allowed"])
        self.assertFalse(result["site_publish_allowed"])
        self.assertFalse(result["social_publish_allowed"])
        self.assertFalse(result["acceptance_ready"])
        self.assertEqual(result["registration_deadline"], "2026-10-02")
        self.assertEqual(result["promotion_candidate_count"], 1)
        candidate = result["promotion_candidates"][0]
        self.assertEqual(candidate["field_evidence_id"], "isj-calendar-scope-deadline-001")
        self.assertEqual(candidate["supporting_field_evidence_ids"], ["isj-calendar-scope-scope-001", "isj-calendar-field-registration-001"])
        self.assertTrue(candidate["materiality_promotion_allowed"])
        self.assertFalse(candidate["fact_kernel_promotion_allowed"])

        independent = validate(scope, validation, result, expected_year=2026)
        self.assertEqual(independent["status"], "PASS_SHADOW")
        self.assertEqual(independent["registration_deadline_field_evidence_id"], "isj-calendar-scope-deadline-001")
        self.assertEqual(independent["promotion_evidence_id"], result["promotion_evidence_id"])

    def test_gate_fails_closed_if_independent_validation_not_passed(self):
        scope, validation = self._fixtures()
        validation["status"] = "FAILED"
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["materiality_promotion_allowed"])
        self.assertEqual(result["promotion_candidate_count"], 0)

    def test_gate_fails_closed_if_scope_and_validator_deadline_diverge(self):
        scope, validation = self._fixtures()
        validation["registration_deadline"] = "2026-10-03"
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("deadline_disagrees", result.get("detail", ""))

    def test_gate_fails_closed_if_exact_supporting_evidence_identity_changes(self):
        scope, validation = self._fixtures()
        scope["rows"][0]["fields"][0]["supporting_field_evidence_ids"] = ["isj-calendar-field-registration-001", "isj-calendar-scope-scope-001"]
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["materiality_promotion_allowed"])

    def test_gate_rejects_elapsed_deadline(self):
        scope, validation = self._fixtures()
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 10, 3))
        self.assertEqual(result["state"], "BLOCKED")
        self.assertIn("already_elapsed", result.get("detail", ""))

    def test_independent_validator_rejects_tamper_cases(self):
        scope, validation = self._fixtures()
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        self.assertEqual(prove_tamper_regressions(scope, validation, result, expected_year=2026), 3)

    def test_validator_rejects_top_level_promotion_evidence_tamper(self):
        scope, validation = self._fixtures()
        result = build_deadline_promotion(scope, validation, expected_year=2026, as_of=date(2026, 9, 19))
        tampered = copy.deepcopy(result)
        tampered["promotion_evidence_id"] = "isj-deadline-promotion-tampered"
        with self.assertRaises(AssertionError):
            validate(scope, validation, tampered, expected_year=2026)

    def test_fact_kernel_gate_preserves_exact_materiality_and_upstream_identity(self):
        scope, scope_validation = self._fixtures()
        promotion = build_deadline_promotion(scope, scope_validation, expected_year=2026, as_of=date(2026, 9, 19))
        independent = validate(scope, scope_validation, promotion, expected_year=2026)
        materiality = self._materiality_fixture(promotion, independent)

        fact_promotion = build_fact_kernel_deadline_promotion(
            materiality,
            promotion,
            independent,
            expected_year=2026,
        )
        self.assertEqual(fact_promotion["state"], "FACT_KERNEL_PROMOTION_VERIFIED_SHADOW")
        self.assertTrue(fact_promotion["material_fact_use"])
        self.assertTrue(fact_promotion["fact_kernel_promotion_allowed"])
        self.assertFalse(fact_promotion["writer_allowed"])
        self.assertFalse(fact_promotion["site_publish_allowed"])
        self.assertFalse(fact_promotion["social_publish_allowed"])
        self.assertFalse(fact_promotion["acceptance_ready"])
        self.assertEqual(fact_promotion["registration_deadline"], "2026-10-02")
        self.assertEqual(
            fact_promotion["upstream_materiality_promotion_evidence_id"],
            promotion["promotion_evidence_id"],
        )

        verified = validate_fact_kernel_promotion(
            materiality,
            promotion,
            independent,
            fact_promotion,
            expected_year=2026,
        )
        self.assertEqual(verified["status"], "PASS_SHADOW")
        self.assertTrue(verified["fact_kernel_promotion_allowed"])
        self.assertFalse(verified["writer_allowed"])
        self.assertEqual(
            verified["fact_kernel_promotion_evidence_id"],
            fact_promotion["fact_kernel_promotion_evidence_id"],
        )

    def test_fact_kernel_gate_fails_closed_if_materiality_upstream_promotion_id_changes(self):
        scope, scope_validation = self._fixtures()
        promotion = build_deadline_promotion(scope, scope_validation, expected_year=2026, as_of=date(2026, 9, 19))
        independent = validate(scope, scope_validation, promotion, expected_year=2026)
        materiality = self._materiality_fixture(promotion, independent)
        materiality["registration_deadline_promotion_evidence_id"] = "isj-deadline-promotion-tampered"
        result = build_fact_kernel_deadline_promotion(materiality, promotion, independent, expected_year=2026)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["fact_kernel_promotion_allowed"])

    def test_fact_kernel_gate_fails_closed_if_deadline_was_already_inserted_into_kernel_ids(self):
        scope, scope_validation = self._fixtures()
        promotion = build_deadline_promotion(scope, scope_validation, expected_year=2026, as_of=date(2026, 9, 19))
        independent = validate(scope, scope_validation, promotion, expected_year=2026)
        materiality = self._materiality_fixture(promotion, independent)
        deadline_id = promotion["registration_deadline_field_evidence_id"]
        materiality["materiality_candidates"][0]["field_evidence_ids"][0] = deadline_id
        result = build_fact_kernel_deadline_promotion(materiality, promotion, independent, expected_year=2026)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["fact_kernel_promotion_allowed"])

    def test_fact_kernel_independent_validator_rejects_tamper_cases(self):
        scope, scope_validation = self._fixtures()
        promotion = build_deadline_promotion(scope, scope_validation, expected_year=2026, as_of=date(2026, 9, 19))
        independent = validate(scope, scope_validation, promotion, expected_year=2026)
        materiality = self._materiality_fixture(promotion, independent)
        fact_promotion = build_fact_kernel_deadline_promotion(materiality, promotion, independent, expected_year=2026)
        self.assertEqual(
            prove_fact_kernel_tamper_regressions(
                materiality,
                promotion,
                independent,
                fact_promotion,
                expected_year=2026,
            ),
            3,
        )


if __name__ == "__main__":
    unittest.main()
