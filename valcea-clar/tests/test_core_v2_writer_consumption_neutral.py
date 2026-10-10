import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from isj_writer_deadline_consumption_shadow_lane import build_writer_deadline_consumption
from promoted_claim_writer_consumption import build_promoted_claim_writer_consumption
from validate_promoted_claim_writer_consumption_runtime import (
    prove_consumption_tamper_regressions,
    validate_promoted_claim_writer_consumption,
)


def boundary(**extra):
    return {
        "publication_authority": "NONE",
        "acceptance_ready": False,
        "production_writer_ready": False,
        "site_publish_allowed": False,
        "social_publish_allowed": False,
        **extra,
    }


class SourceNeutralWriterConsumptionTest(unittest.TestCase):
    def setUp(self):
        promoted = {
            "field": "registration_deadline",
            "value": "2026-10-02",
            "claim": "Înscrierile se încheie la 2 octombrie 2026.",
            "field_evidence_id": "field-evidence-1",
            "scope_field_evidence_id": "scope-evidence-1",
            "source_registration_window_field_evidence_id": "window-evidence-1",
            "document_text_evidence_id": "document-evidence-1",
            "upstream_materiality_promotion_evidence_id": "materiality-promotion-1",
            "fact_kernel_promotion_evidence_id": "fact-promotion-1",
            "page_text_sha256": "a" * 64,
            "claim_evidence_ids": ["claim-evidence-1", "claim-evidence-2"],
            "supporting_field_evidence_ids": ["supporting-evidence-1"],
            "page_number": 4,
            "excerpt": "Înscrierile se încheie la 2 octombrie 2026.",
        }
        self.fact_kernel = boundary(
            state="FACT_KERNEL_VERIFIED_SHADOW",
            writer_allowed=False,
            promoted_fact_claim_count=1,
            kernels=[{"promoted_fact_claims": [promoted]}],
        )
        self.fact_integrity = boundary(
            status="PASS_SHADOW",
            fact_kernel_integrity_verified=True,
            fabricated_claim_count=0,
            promoted_fact_verified_count=1,
        )
        candidate = {
            **promoted,
            "state": "WRITER_DEADLINE_PROJECTION_VERIFIED_SHADOW",
            "writer_projection_evidence_id": "isj-writer-deadline-projection-test",
            "writer_deadline_projection_allowed": True,
            "writer_allowed": False,
            "article_projection_allowed": False,
        }
        self.projection = boundary(
            state="WRITER_PROJECTION_VERIFIED_SHADOW",
            writer_deadline_projection_allowed=True,
            writer_allowed=False,
            article_projection_allowed=False,
            projection_candidate_count=1,
            projection_candidates=[candidate],
            writer_projection_evidence_id="isj-writer-deadline-projection-test",
            registration_deadline="2026-10-02",
        )
        self.projection_validation = boundary(
            status="PASS_SHADOW",
            writer_projection_allowed=True,
            writer_deadline_projection_allowed=True,
            article_projection_allowed=False,
            verified_projection_candidate_count=1,
            fabricated_claim_count=0,
            tamper_regressions_passed=4,
            writer_projection_evidence_id="isj-writer-deadline-projection-test",
            field="registration_deadline",
            value="2026-10-02",
            registration_deadline="2026-10-02",
        )

    def test_source_neutral_builder_preserves_legacy_deterministic_identity(self):
        legacy = build_writer_deadline_consumption(
            self.fact_kernel,
            self.fact_integrity,
            self.projection,
            self.projection_validation,
            expected_year=2026,
        )
        generic = build_promoted_claim_writer_consumption(
            self.fact_kernel,
            self.fact_integrity,
            self.projection,
            self.projection_validation,
            expected_year=2026,
        )
        self.assertEqual(legacy["state"], "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW")
        self.assertEqual(generic["state"], "WRITER_DEADLINE_CONSUMPTION_VERIFIED_SHADOW")
        self.assertEqual(generic["writer_projection_evidence_id"], legacy["writer_projection_evidence_id"])
        self.assertEqual(generic["writer_consumption_evidence_id"], legacy["writer_consumption_evidence_id"])
        self.assertEqual(generic["registration_deadline"], legacy["registration_deadline"])
        self.assertEqual(generic["consumption_candidates"], legacy["consumption_candidates"])
        self.assertTrue(generic["builder_source_neutral"])
        self.assertEqual(generic["canonical_writer_consumption_builder_path"], "SOURCE_NEUTRAL_MODULE")
        self.assertFalse(generic["legacy_module_path_required_for_canonical_runtime"])
        self.assertFalse(generic["source_specific_builder_canonical_producer"])
        self.assertFalse(generic["source_specific_comparator_runtime_dependency"])
        self.assertEqual(generic["publication_authority"], "NONE")
        self.assertFalse(generic["acceptance_ready"])

    def test_source_neutral_validator_is_independent_and_fail_closed(self):
        generic = build_promoted_claim_writer_consumption(
            self.fact_kernel,
            self.fact_integrity,
            self.projection,
            self.projection_validation,
            expected_year=2026,
        )
        report = validate_promoted_claim_writer_consumption(
            self.fact_kernel,
            self.fact_integrity,
            self.projection,
            self.projection_validation,
            generic,
            expected_year=2026,
        )
        self.assertEqual(report["status"], "PASS_SHADOW")
        self.assertEqual(report["writer_consumption_evidence_id"], generic["writer_consumption_evidence_id"])
        self.assertTrue(report["validator_source_neutral"])
        self.assertFalse(report["legacy_validator_required_for_canonical_runtime"])
        self.assertEqual(
            prove_consumption_tamper_regressions(
                self.fact_kernel,
                self.fact_integrity,
                self.projection,
                self.projection_validation,
                generic,
                expected_year=2026,
            ),
            4,
        )


if __name__ == "__main__":
    unittest.main()
