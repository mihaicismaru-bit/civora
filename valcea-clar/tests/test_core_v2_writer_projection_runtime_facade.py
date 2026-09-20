import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

import isj_writer_deadline_projection_shadow_lane as facade


class WriterProjectionRuntimeFacadeTest(unittest.TestCase):
    def test_source_neutral_builder_is_canonical_and_isj_logic_is_comparison_only(self):
        generic = {
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
        comparison = {
            "status": "PASS_SHADOW",
            "writer_projection_evidence_id": generic["writer_projection_evidence_id"],
            "source_specific_lineage_equivalent": True,
            "source_specific_authority_flags_equivalent": True,
        }
        independent = {
            "status": "PASS_SHADOW",
            "writer_projection_evidence_id": generic["writer_projection_evidence_id"],
        }
        with patch.object(facade, "build_source_neutral_projection", return_value=dict(generic)) as build_generic, \
             patch.object(facade, "compare_source_specific_projection", return_value=comparison) as compare_legacy, \
             patch.object(facade, "validate_source_neutral_projection", return_value=independent), \
             patch.object(facade, "prove_projection_tamper_regressions", return_value=4):
            result = facade.build_writer_deadline_projection({}, {}, expected_year=2026)

        build_generic.assert_called_once_with({}, {}, identity_prefix="isj-writer-deadline-projection")
        compare_legacy.assert_called_once()
        self.assertEqual(result["state"], "WRITER_PROJECTION_VERIFIED_SHADOW")
        self.assertEqual(result["canonical_writer_projection_builder_path"], "SOURCE_NEUTRAL_RUNTIME_FACADE")
        self.assertTrue(result["canonical_writer_projection_runtime_facade"])
        self.assertFalse(result["source_specific_builder_canonical_producer"])
        self.assertTrue(result["source_specific_builder_comparison_only"])
        self.assertEqual(result["source_specific_comparator_status"], "PASS_SHADOW")
        self.assertEqual(result["source_neutral_projection_tamper_regressions_passed"], 4)
        self.assertFalse(result["source_specific_builder_retirement_performed"])
        self.assertFalse(result["article_projection_allowed"])
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])

    def test_comparator_mismatch_fails_closed(self):
        generic = {
            "state": "WRITER_PROJECTION_VERIFIED_SHADOW",
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "production_writer_ready": False,
            "writer_allowed": False,
            "article_projection_allowed": False,
            "site_publish_allowed": False,
            "social_publish_allowed": False,
            "writer_deadline_projection_allowed": True,
            "promoted_claim_projection_allowed": True,
            "writer_projection_evidence_id": "isj-writer-deadline-projection-abc",
            "projection_candidate_count": 1,
            "projection_candidates": [{}],
        }
        comparison = {"status": "BLOCKED", "reason": "mismatch"}
        with patch.object(facade, "build_source_neutral_projection", return_value=dict(generic)), \
             patch.object(facade, "compare_source_specific_projection", return_value=comparison):
            result = facade.build_writer_deadline_projection({}, {}, expected_year=2026)
        self.assertEqual(result["state"], "BLOCKED")
        self.assertFalse(result["writer_deadline_projection_allowed"])
        self.assertEqual(result["projection_candidate_count"], 0)
        self.assertEqual(result["publication_authority"], "NONE")
        self.assertFalse(result["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
