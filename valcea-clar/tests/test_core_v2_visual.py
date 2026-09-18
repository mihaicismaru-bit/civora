import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from photo_truth_gate import assess_story_visual, build_photo_truth_report
from visual_readback import _filename, inspect_article_image


class VisualReadbackTest(unittest.TestCase):
    def test_filename_from_url_or_repo_path(self):
        self.assertEqual(_filename("valcea-clar/social/photos/approved/cet.jpg"), "cet.jpg")
        self.assertEqual(_filename("https://example.test/media/cet.jpg?x=1"), "cet.jpg")

    def test_article_image_binding_resolves_relative_url(self):
        html = '<html><body><img src="/media/cet.jpg" alt="Foto de arhivă"></body></html>'
        result = inspect_article_image(
            html,
            article_url="https://valceaclar.ro/stiri/cet/",
            expected_filename="cet.jpg",
        )
        self.assertTrue(result["article_image_bound"])
        self.assertEqual(result["matching_image_count"], 1)
        self.assertEqual(result["matching_images"][0]["url"], "https://valceaclar.ro/media/cet.jpg")

    def test_article_image_binding_fails_wrong_file(self):
        html = '<html><body><img src="/media/other.jpg"></body></html>'
        result = inspect_article_image(
            html,
            article_url="https://valceaclar.ro/stiri/cet/",
            expected_filename="cet.jpg",
        )
        self.assertFalse(result["article_image_bound"])


class PhotoTruthGateTest(unittest.TestCase):
    @staticmethod
    def valid_registry(story_id="story-1"):
        return {
            "stories": {
                story_id: {
                    "image_path": "valcea-clar/social/photos/approved/story-1.jpg",
                    "image": {
                        "kind": "photograph",
                        "synthetic": False,
                        "subject_match": True,
                        "editor_approved": True,
                        "contextual_archive": True,
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg",
                        "credit": "Example / Wikimedia Commons — CC BY-SA 4.0",
                        "rights_basis": "creative_commons",
                        "editorial_note": "Foto de arhivă; imaginea nu surprinde evenimentul curent.",
                    },
                }
            }
        }

    def test_story_specific_real_rights_cleared_visual_passes_shadow_gate(self):
        result = assess_story_visual(
            "story-1",
            visual_registry=self.valid_registry(),
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(result["status"], "VISUAL_CANDIDATE_VERIFIED_SHADOW")
        self.assertTrue(result["visual_ready_for_future_site_binding"])
        self.assertFalse(result["article_binding_verified"])
        self.assertFalse(result["social_publish_allowed"])
        self.assertEqual(result["publication_authority"], "NONE")

    def test_missing_story_assignment_blocks_even_when_atlas_has_same_asset(self):
        result = assess_story_visual(
            "story-1",
            visual_registry={"stories": {}},
            atlas={
                "assets": [
                    {
                        "asset_id": "atlas-1",
                        "source_story_ids": ["story-1"],
                        "automatic_story_assignment_allowed": False,
                    }
                ]
            },
            external_probe=False,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "atlas_asset_does_not_inherit_story_approval")
        self.assertFalse(result["social_publish_allowed"])

    def test_text_card_or_synthetic_asset_cannot_substitute_for_photo(self):
        registry = self.valid_registry()
        image = registry["stories"]["story-1"]["image"]
        image["kind"] = "text_card"
        image["synthetic"] = True
        result = assess_story_visual(
            "story-1",
            visual_registry=registry,
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("not_real_photograph", result["problems"])
        self.assertIn("synthetic_as_photo_forbidden", result["problems"])

    def test_archive_context_requires_explicit_disclosure(self):
        registry = self.valid_registry()
        registry["stories"]["story-1"]["image"]["editorial_note"] = ""
        result = assess_story_visual(
            "story-1",
            visual_registry=registry,
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("archive_context_disclosure_missing", result["problems"])

    def test_subject_match_and_editor_approval_are_both_required(self):
        registry = self.valid_registry()
        image = registry["stories"]["story-1"]["image"]
        image["subject_match"] = False
        image["editor_approved"] = False
        result = assess_story_visual(
            "story-1",
            visual_registry=registry,
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("subject_match_not_proven", result["problems"])
        self.assertIn("editor_approval_missing", result["problems"])

    def test_report_extracts_public_safety_and_municipal_written_candidates(self):
        public_safety = {
            "rows": [
                {
                    "detail_id": "ps-1",
                    "state": "VERIFIED_WRITTEN_SHADOW",
                    "fact_kernel": {"where": "Mădulari", "who": "ISU Vâlcea"},
                    "article_package": {"headline": "Incendiu în Mădulari"},
                }
            ]
        }
        municipal = {
            "rows": [
                {
                    "decision_number": 343,
                    "state": "VERIFIED_WRITTEN_SHADOW",
                    "articles": [
                        {
                            "article_id": "hcl-343-local-public-finance",
                            "fact_kernel": {"where": "Râmnicu Vâlcea", "who": "Consiliul Local"},
                            "article_package": {"headline": "Buget local"},
                        }
                    ],
                }
            ]
        }
        report = build_photo_truth_report(
            [("isu", public_safety), ("municipal", municipal)],
            visual_registry={"stories": {}},
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(report["candidate_count"], 2)
        self.assertEqual(report["visual_candidate_verified_shadow_count"], 0)
        self.assertEqual(report["blocked_count"], 2)
        self.assertFalse(report["social_publish_allowed"])
        self.assertFalse(report["acceptance_ready"])


if __name__ == "__main__":
    unittest.main()
