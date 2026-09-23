import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from instagram_transform_diagnostic import (
    bounded_crop_boxes,
    select_near_match_targets,
    summarize_hypotheses,
    validate_output,
)


class InstagramTransformDiagnosticTest(unittest.TestCase):
    def test_bounded_crop_boxes_are_deterministic_and_horizontal_only(self):
        boxes = bounded_crop_boxes(1000, 500)
        self.assertEqual(len(boxes), 12)
        eighty = [row for row in boxes if row["crop_fraction"] == 0.80]
        self.assertEqual(
            [(row["anchor"], row["x"], row["y"], row["width"], row["height"]) for row in eighty],
            [
                ("left", 0, 0, 800, 500),
                ("center", 100, 0, 800, 500),
                ("right", 200, 0, 800, 500),
            ],
        )
        self.assertTrue(all(row["y"] == 0 and row["height"] == 500 for row in boxes))

    def test_select_targets_accepts_only_unique_below_threshold_near_match(self):
        identity = {
            "results": [
                {
                    "story_id": "water",
                    "identity_bound": False,
                    "identity_state": "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL",
                    "read_only_score_diagnostics": {
                        "diagnostic_state": "UNIQUE_BEST_BELOW_IDENTITY_THRESHOLDS",
                        "best_remote_id": "remote-water",
                        "best_composite_score": 0.671125,
                        "best_to_runner_up_margin": 0.671125,
                    },
                },
                {
                    "story_id": "already-bound",
                    "identity_bound": True,
                    "read_only_score_diagnostics": {
                        "diagnostic_state": "IDENTITY_ALREADY_BOUND",
                        "best_remote_id": "remote-bound",
                    },
                },
                {
                    "story_id": "not-near",
                    "identity_bound": False,
                    "read_only_score_diagnostics": {
                        "diagnostic_state": "NO_ACCEPTANCE_NEAR_MATCH",
                        "best_remote_id": "remote-other",
                    },
                },
            ]
        }
        targets = select_near_match_targets(identity)
        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0]["story_id"], "water")
        self.assertEqual(targets[0]["best_remote_id"], "remote-water")

    def test_transform_score_can_explain_near_match_but_never_promotes_identity(self):
        rows = [
            {
                "hypothesis_id": "horizontal_0.80_left_to_stretch",
                "correlation": 0.91,
                "mae_normalized": 0.07,
                "composite_score": 0.8463,
                "same_visual": True,
            },
            {
                "hypothesis_id": "horizontal_0.80_center_to_stretch",
                "correlation": 0.61,
                "mae_normalized": 0.19,
                "composite_score": 0.4941,
                "same_visual": False,
            },
        ]
        result = summarize_hypotheses(rows)
        self.assertEqual(
            result["diagnostic_state"],
            "BOUNDED_TRANSFORM_EXPLAINS_NEAR_MATCH_DIAGNOSTIC_ONLY",
        )
        self.assertTrue(result["hypothesis_clears_current_pixel_thresholds"])
        self.assertEqual(result["diagnostic_authority"], "NONE")
        self.assertFalse(result["acceptance_effect"])
        self.assertFalse(result["identity_promotion_allowed"])
        self.assertFalse(result["thresholds_changed"])
        self.assertEqual(result["best_hypothesis"]["rank"], 1)

    def test_non_explanatory_transform_remains_diagnostic_only(self):
        result = summarize_hypotheses([
            {
                "hypothesis_id": "horizontal_0.70_right_to_center_crop",
                "correlation": 0.74,
                "mae_normalized": 0.09,
                "composite_score": 0.6734,
                "same_visual": False,
            }
        ])
        self.assertEqual(result["diagnostic_state"], "BOUNDED_TRANSFORM_DID_NOT_EXPLAIN_NEAR_MATCH")
        self.assertFalse(result["hypothesis_clears_current_pixel_thresholds"])
        self.assertFalse(result["identity_promotion_allowed"])

    def test_validate_output_rejects_any_acceptance_authority_drift(self):
        valid = {
            "publication_authority": "NONE",
            "acceptance_effect": False,
            "identity_promotion_allowed": False,
            "thresholds_changed": False,
            "acceptance_ready": False,
            "results": [
                {
                    "publication_authority": "NONE",
                    "acceptance_effect": False,
                    "identity_promotion_allowed": False,
                }
            ],
        }
        validate_output(valid)
        invalid = dict(valid)
        invalid["identity_promotion_allowed"] = True
        with self.assertRaises(ValueError):
            validate_output(invalid)


if __name__ == "__main__":
    unittest.main()
