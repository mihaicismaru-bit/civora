import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

import isj_writer_deadline_projection_shadow_lane as facade


class WriterProjectionRuntimeFacadeTest(unittest.TestCase):
    def _generic(self):
        return {
            "schema_version": "1.0",
            "mode": "CORE_V2_SOURCE_NEUTRAL_PROMOTED_CLAIM_WRITER_PROJECTION_SHADOW",
            "state": "WRITER_PROJECTION_VERIFIED_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "production_writer_ready": False,
            "writer_allowed": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "fabricated_claim_count": 0,
            "writer_deadline_projection_allowed": True,
            "promoted_claim_projection_allowed": True,
            "registration_deadline": "2026-10-02",
            "writer_projection_evidence_id": "isj-writer-deadline-projection-d9ae7b38596fc02a6ee7524d",
            "projection_candidate_count": 1,
            "projection_candidates": [{}],
            "truth_rule": "generic",
        }

    def test_source_neutral_runtime_success_has_no_source_specific_comparator_dependency(self):
        generic = self._generic()
        independent = {
            "status": "PASS_SHADOW",
            "writer_projection_evidence_id": generic["writer_projection_evidence_id"],
        }
        self.assertFalse(hasattr(facade, "compare_source_specific_projection"))
        with patch.object(facade, "build_source_neutral_projection", return_value=dict(generic)) as build_generic, \
             patch.object(facade, "validate_source_neutral_projection", return_value=independent) as validate_generic, \
             patch.object(facade, "prove_projection_tamper_regressions", return_value=4) as prove_tamper:
            result = facade.build_writer_deadline_projection({}, {}, expected_year=2026)

        build_generic.assert_called_once_with({}, {}, identity_prefix="isj-writer-deadline-projection")
        validate_generic.assert_called_once()
        prove_tamper.assert_called_once()
        self.assertEqual(result["state"], "WRITER_PROJECTION_VERIFIED_SHADOW")
        self.assertEqual(result["canonical_writer_projection_builder_path"], "SOURCE_NEUTRAL_RUNTIME_FACADE")
        self.assertTrue(result["canonical_writer_projection_runtime_facade"])
        self.assertFalse(result["source_specific_builder_canonical_producer"])
        self.assertFalse(result["source_specific_builder_comparison_only"])
        self.assertFalse(result["source_specific_comparator_runtime_dependency"])
        self.assertEqual(result["source_specific_comparator_execution"], "INDEPENDENT_CI_REGRESSION_ONLY")
        self.assertEqual(result["source_specific_comparator_status"], "NOT_RUN_CANONICAL_PATH")
        self.assertEqual(result["source_neutral_projection_tamper_regressions_passed"], 4)
        self.assertFalse(result["source_specific_builder_retirement_performed"])
        self.assertFalse(result["article_projection_allowed"])
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])

    def test_source_neutral_validation_failure_still_fails_closed(self):
        generic = self._generic()
        independent = {"status": "BLOCKED", "reason": "projection_lineage_mismatch"}
        with patch.object(facade, "build_source_neutral_projection", return_value=dict(generic)), \
             patch.object(facade, "validate_source_neutral_projection", return_value=independent):
            result = facade.build_writer_deadline_projection({}, {}, expected_year=2026)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["writer_deadline_projection_allowed"])
        self.assertEqual(result["projection_candidate_count"], 0)
        self.assertFalse(result["source_specific_comparator_runtime_dependency"])
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
