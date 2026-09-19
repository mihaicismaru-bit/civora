import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

import instagram_visual_identity as identity_module
from instagram_visual_identity import compare_vectors, identity_decision


class InstagramVisualIdentityTest(unittest.TestCase):
    def test_exact_and_near_reencoded_vectors_match(self):
        left = [(i * 17 + (i // 11) * 7) % 256 for i in range(1024)]
        exact = compare_vectors(left, list(left))
        self.assertTrue(exact["same_visual"])
        self.assertEqual(exact["correlation"], 1.0)
        self.assertEqual(exact["mae_normalized"], 0.0)

        near = [max(0, min(255, value + (1 if i % 5 else -1))) for i, value in enumerate(left)]
        transformed = compare_vectors(left, near)
        self.assertTrue(transformed["same_visual"])
        self.assertGreaterEqual(transformed["correlation"], 0.80)
        self.assertLessEqual(transformed["mae_normalized"], 0.12)

    def test_different_visual_fails_closed(self):
        left = [(i * 13) % 256 for i in range(1024)]
        right = [255 - value for value in left]
        result = compare_vectors(left, right)
        self.assertFalse(result["same_visual"])
        self.assertLess(result["correlation"], 0.0)

    def test_identity_requires_exactly_one_dominant_remote_match(self):
        unique = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": True, "composite_score": 0.73},
            {"remote_id": "b", "media_url": "https://example.test/b.jpg", "same_visual": False, "composite_score": 0.10},
        ])
        self.assertTrue(unique["identity_bound"])
        self.assertEqual(unique["matched_remote_id"], "a")
        self.assertEqual(unique["identity_state"], "APPROVED_VISUAL_MATCHED_REMOTE_IMAGE_UNIQUE")
        self.assertGreaterEqual(unique["match_margin"], 0.20)

        ambiguous = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": True, "composite_score": 0.97},
            {"remote_id": "b", "media_url": "https://example.test/b.jpg", "same_visual": True, "composite_score": 0.96},
        ])
        self.assertFalse(ambiguous["identity_bound"])
        self.assertEqual(ambiguous["identity_state"], "AMBIGUOUS_MULTIPLE_REMOTE_MATCHES")

        close_runner_up = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": True, "composite_score": 0.74},
            {"remote_id": "b", "media_url": "https://example.test/b.jpg", "same_visual": False, "composite_score": 0.63},
        ])
        self.assertFalse(close_runner_up["identity_bound"])
        self.assertEqual(close_runner_up["identity_state"], "BLOCKED_INSUFFICIENT_UNIQUENESS_MARGIN")
        self.assertLess(close_runner_up["match_margin"], 0.20)

        none = identity_decision([
            {"remote_id": "a", "media_url": "https://example.test/a.jpg", "same_visual": False, "composite_score": 0.55},
        ])
        self.assertFalse(none["identity_bound"])
        self.assertEqual(none["identity_state"], "NO_REMOTE_IMAGE_MATCHED_APPROVED_VISUAL")

    def test_missing_repo_asset_can_hydrate_only_from_exact_verified_provenance(self):
        candidate = {
            "real_visual_internal_evidence": True,
            "visual_image_path": "valcea-clar/social/photos/approved/launch-ramnicu-valcea-panorama.jpg",
            "visual_source_url": "https://commons.wikimedia.org/wiki/File:Ramnicu_Valcea_panorama.jpg",
            "visual_direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
            "visual_rights_basis": "creative_commons",
        }
        source_html = """
        <html><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "contentUrl": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
          "license": "https://creativecommons.org/licenses/by-sa/4.0/"
        }
        </script></html>
        """

        def fake_download(_url, target, _timeout=20.0):
            target.write_bytes(b"verified-approved-image-bytes")
            return {
                "download_ok": True,
                "http_status": 200,
                "content_type": "image/jpeg",
                "bytes_downloaded": target.stat().st_size,
                "final_url": candidate["visual_direct_source_url"],
                "attempts": 1,
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approved.img"
            with patch.object(identity_module, "_fetch_text", return_value={
                "readback_ok": True,
                "http_status": 200,
                "content_type": "text/html",
                "final_url": candidate["visual_source_url"],
                "body": source_html,
            }), patch.object(identity_module, "_download_approved_source", side_effect=fake_download):
                result = identity_module._hydrate_approved_visual(candidate, target)

        self.assertTrue(result["hydration_ok"])
        self.assertEqual(result["hydration_state"], "VERIFIED_PROVENANCE_HYDRATED_SHADOW")
        self.assertEqual(result["hydration_transport"], "exact_approved_original")
        self.assertEqual(result["approved_visual_path"], candidate["visual_image_path"])
        self.assertEqual(result["source_url"], candidate["visual_source_url"])
        self.assertEqual(result["direct_source_url"], candidate["visual_direct_source_url"])
        self.assertEqual(len(result["hydrated_sha256"]), 64)
        self.assertGreater(result["hydrated_bytes"], 0)
        self.assertTrue(result["provenance_asset"]["asset_identity_ok"])
        self.assertTrue(result["provenance_asset"]["license_present"])
        self.assertIsNone(result["exact_derivative_download"])

    def test_wikimedia_derivative_urls_are_deterministic_same_asset_only(self):
        direct = "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg"
        self.assertEqual(
            identity_module._wikimedia_exact_derivative_urls(direct),
            [
                "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8d/Ramnicu_Valcea_panorama.jpg/1280px-Ramnicu_Valcea_panorama.jpg",
                "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8d/Ramnicu_Valcea_panorama.jpg/960px-Ramnicu_Valcea_panorama.jpg",
            ],
        )
        self.assertEqual(identity_module._wikimedia_exact_derivative_urls("https://example.test/a.jpg"), [])
        self.assertEqual(
            identity_module._wikimedia_exact_derivative_urls(
                "https://upload.wikimedia.org/wikipedia/commons/thumb/8/8d/a.jpg/960px-a.jpg"
            ),
            [],
        )

    def test_exact_wikimedia_derivative_is_allowed_only_after_original_429_and_verified_identity(self):
        candidate = {
            "real_visual_internal_evidence": True,
            "visual_image_path": "valcea-clar/social/photos/approved/launch-ramnicu-valcea-panorama.jpg",
            "visual_source_url": "https://commons.wikimedia.org/wiki/File:Ramnicu_Valcea_panorama.jpg",
            "visual_direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
            "visual_rights_basis": "creative_commons",
        }
        source_html = """
        <html><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "contentUrl": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
          "license": "https://creativecommons.org/licenses/by-sa/4.0/"
        }
        </script></html>
        """

        def fake_derivative(_url, target, _timeout=20.0):
            target.write_bytes(b"exact-derived-pixels")
            return {
                "download_ok": True,
                "http_status": 200,
                "content_type": "image/jpeg",
                "bytes_downloaded": target.stat().st_size,
                "final_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8d/Ramnicu_Valcea_panorama.jpg/1280px-Ramnicu_Valcea_panorama.jpg",
                "derivative_url": "https://thumb.wikimedia.org/wikipedia/commons/thumb/8/8d/Ramnicu_Valcea_panorama.jpg/1280px-Ramnicu_Valcea_panorama.jpg",
                "derivative_identity_ok": True,
                "attempts": [],
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approved.img"
            with patch.object(identity_module, "_fetch_text", return_value={
                "readback_ok": True,
                "http_status": 200,
                "content_type": "text/html",
                "final_url": candidate["visual_source_url"],
                "body": source_html,
            }), patch.object(identity_module, "_download_approved_source", return_value={
                "download_ok": False,
                "http_status": 429,
                "reason": "http_error",
                "attempts": 3,
            }), patch.object(identity_module, "_download_exact_wikimedia_derivative", side_effect=fake_derivative) as derivative:
                result = identity_module._hydrate_approved_visual(candidate, target)

        self.assertTrue(result["hydration_ok"])
        self.assertEqual(
            result["hydration_state"],
            "VERIFIED_PROVENANCE_HYDRATED_EXACT_WIKIMEDIA_DERIVATIVE_SHADOW",
        )
        self.assertEqual(result["hydration_transport"], "exact_wikimedia_derivative_after_original_429")
        self.assertTrue(result["exact_derivative_identity_bound_to_original"])
        derivative.assert_called_once_with(candidate["visual_direct_source_url"], target)

    def test_derivative_fallback_is_not_used_for_non_429_failure(self):
        candidate = {
            "real_visual_internal_evidence": True,
            "visual_image_path": "valcea-clar/social/photos/approved/launch-ramnicu-valcea-panorama.jpg",
            "visual_source_url": "https://commons.wikimedia.org/wiki/File:Ramnicu_Valcea_panorama.jpg",
            "visual_direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
            "visual_rights_basis": "creative_commons",
        }
        source_html = """
        <html><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "contentUrl": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
          "license": "https://creativecommons.org/licenses/by-sa/4.0/"
        }
        </script></html>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approved.img"
            with patch.object(identity_module, "_fetch_text", return_value={
                "readback_ok": True,
                "http_status": 200,
                "content_type": "text/html",
                "final_url": candidate["visual_source_url"],
                "body": source_html,
            }), patch.object(identity_module, "_download_approved_source", return_value={
                "download_ok": False,
                "http_status": 404,
                "reason": "http_error",
                "attempts": 1,
            }), patch.object(identity_module, "_download_exact_wikimedia_derivative") as derivative:
                result = identity_module._hydrate_approved_visual(candidate, target)

        self.assertFalse(result["hydration_ok"])
        self.assertEqual(result["hydration_state"], "BLOCKED_APPROVED_SOURCE_DOWNLOAD")
        self.assertFalse(result["exact_derivative_fallback_allowed"])
        derivative.assert_not_called()

    def test_hydration_rejects_wrong_provenance_asset_before_download(self):
        candidate = {
            "real_visual_internal_evidence": True,
            "visual_image_path": "valcea-clar/social/photos/approved/launch-ramnicu-valcea-panorama.jpg",
            "visual_source_url": "https://commons.wikimedia.org/wiki/File:Ramnicu_Valcea_panorama.jpg",
            "visual_direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
            "visual_rights_basis": "creative_commons",
        }
        wrong_html = """
        <html><script type="application/ld+json">
        {
          "@type": "ImageObject",
          "contentUrl": "https://upload.wikimedia.org/wikipedia/commons/a/aa/Different.jpg",
          "license": "https://creativecommons.org/licenses/by-sa/4.0/"
        }
        </script></html>
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "approved.img"
            with patch.object(identity_module, "_fetch_text", return_value={
                "readback_ok": True,
                "http_status": 200,
                "content_type": "text/html",
                "final_url": candidate["visual_source_url"],
                "body": wrong_html,
            }), patch.object(identity_module, "_download_approved_source") as download, patch.object(
                identity_module, "_download_exact_wikimedia_derivative"
            ) as derivative:
                result = identity_module._hydrate_approved_visual(candidate, target)

        self.assertFalse(result["hydration_ok"])
        self.assertEqual(result["hydration_state"], "BLOCKED_PROVENANCE_ASSET_IDENTITY")
        download.assert_not_called()
        derivative.assert_not_called()


if __name__ == "__main__":
    unittest.main()
