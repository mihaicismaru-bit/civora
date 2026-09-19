import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from photo_truth_gate import _candidate_fingerprint, assess_story_visual, build_photo_truth_report
from visual_readback import _filename, _read_binary_head, inspect_article_image


class _FakeImageResponse:
    status = 206
    headers = {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return "https://upload.wikimedia.org/example.jpg"

    def read(self, size=-1):
        return b"\xff\xd8\xff"[: max(0, size)] if size >= 0 else b"\xff\xd8\xff"


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

    def test_binary_image_readback_retries_429_only_and_preserves_external_truth(self):
        first = HTTPError(
            "https://upload.wikimedia.org/example.jpg",
            429,
            "Too Many Requests",
            {"Retry-After": "0"},
            None,
        )
        with patch("visual_readback.urlopen", side_effect=[first, _FakeImageResponse()]), patch("visual_readback.time.sleep") as sleep:
            result = _read_binary_head("https://upload.wikimedia.org/example.jpg", timeout=1.0)
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["readback_ok"])
        self.assertEqual(result["attempts"], 2)
        self.assertFalse(result["rate_limited"])
        sleep.assert_called_once()


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

    @staticmethod
    def public_safety_candidate():
        return {
            "candidate_id": "ps-1",
            "source_label": "isu",
            "source_url": "https://www.isuvl.igsu.ro/stiri-locale/exemplu-2026",
            "headline": "Intervenție ISU în Mădulari",
            "where": "Mădulari",
            "who": "Inspectoratul pentru Situații de Urgență Vâlcea",
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

    def test_public_safety_visual_assignment_without_exact_binding_fails_closed(self):
        candidate = self.public_safety_candidate()
        result = assess_story_visual(
            "ps-1",
            visual_registry=self.valid_registry("ps-1"),
            atlas={"assets": []},
            external_probe=False,
            candidate=candidate,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason"], "story_binding_missing")
        self.assertFalse(result["candidate_binding_verified"])

    def test_public_safety_visual_binding_rejects_source_url_drift(self):
        candidate = self.public_safety_candidate()
        registry = self.valid_registry("ps-1")
        registry["stories"]["ps-1"]["binding"] = {
            "source_label": "isu",
            "source_url": "https://www.isuvl.igsu.ro/stiri-locale/alta-poveste-2026",
            "candidate_fingerprint": _candidate_fingerprint(candidate),
        }
        result = assess_story_visual(
            "ps-1",
            visual_registry=registry,
            atlas={"assets": []},
            external_probe=False,
            candidate=candidate,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("story_binding_source_url_mismatch", result["problems"])

    def test_public_safety_visual_exact_source_and_fingerprint_binding_passes_shadow(self):
        candidate = self.public_safety_candidate()
        registry = self.valid_registry("ps-1")
        registry["stories"]["ps-1"]["binding"] = {
            "source_label": "isu",
            "source_url": candidate["source_url"],
            "candidate_fingerprint": _candidate_fingerprint(candidate),
        }
        result = assess_story_visual(
            "ps-1",
            visual_registry=registry,
            atlas={"assets": []},
            external_probe=False,
            candidate=candidate,
        )
        self.assertEqual(result["status"], "VISUAL_CANDIDATE_VERIFIED_SHADOW")
        self.assertTrue(result["candidate_binding_configured"])
        self.assertTrue(result["candidate_binding_verified"])
        self.assertEqual(result["candidate_fingerprint"], _candidate_fingerprint(candidate))

    def test_report_extracts_public_safety_and_municipal_written_candidates(self):
        public_safety = {
            "rows": [
                {
                    "detail_id": "ps-1",
                    "state": "VERIFIED_WRITTEN_SHADOW",
                    "fact_kernel": {
                        "where": "Mădulari",
                        "who": "ISU Vâlcea",
                        "source_url": "https://www.isuvl.igsu.ro/stiri-locale/exemplu-2026",
                    },
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
                            "fact_kernel": {
                                "where": "Râmnicu Vâlcea",
                                "who": "Consiliul Local",
                                "source_url": "https://www.primariavl.ro/hcl/343-2026",
                            },
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
        self.assertEqual(report["rows"][0]["article_source_url"], "https://www.isuvl.igsu.ro/stiri-locale/exemplu-2026")

    def test_integrity_verified_isj_candidate_enters_photo_gate_and_fails_closed_without_visual(self):
        isj_integrity = {
            "article_truth_state": "VERIFIED_WRITTEN_SHADOW",
            "article_integrity_verified": True,
            "publication_authority": "NONE",
            "verified_candidates": [
                {
                    "article_id": "isj-directori-2026-conducere-scoli",
                    "headline": "146 de funcții vacante de director și director adjunct",
                    "where": "județul Vâlcea",
                    "who": "Inspectoratul Școlar Județean Vâlcea",
                    "source_url": "https://www.isjvalcea.ro/management/concurs-directori-2026",
                }
            ],
        }
        report = build_photo_truth_report(
            [("isj", isj_integrity)],
            visual_registry={"stories": {}},
            atlas={"assets": []},
            external_probe=False,
        )
        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["visual_candidate_verified_shadow_count"], 0)
        self.assertEqual(report["blocked_count"], 1)
        self.assertEqual(report["rows"][0]["story_id"], "isj-directori-2026-conducere-scoli")
        self.assertEqual(report["rows"][0]["reason"], "no_story_specific_approved_visual")
        self.assertEqual(report["rows"][0]["article_source_url"], "https://www.isjvalcea.ro/management/concurs-directori-2026")
        self.assertFalse(report["social_publish_allowed"])


if __name__ == "__main__":
    unittest.main()
