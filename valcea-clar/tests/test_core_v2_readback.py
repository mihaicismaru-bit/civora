import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from build_shadow_candidate_ledger import _canonical_visual_binding
from external_readback import inspect_html
from meta_readback import parse_meta_error_body, parse_meta_object
from visual_readback import _effective_direct_source_status, inspect_provenance_asset


class ExternalReadbackTest(unittest.TestCase):
    def test_site_readback_requires_route_canonical_and_newsarticle(self):
        html = """
        <html><head>
        <link rel="canonical" href="https://valceaclar.ro/stiri/test-story/">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"NewsArticle","url":"https://valceaclar.ro/stiri/test-story/","headline":"Test"}
        </script>
        </head><body>ok</body></html>
        """
        result = inspect_html(
            html,
            requested_url="https://valceaclar.ro/stiri/test-story/",
            final_url="https://valceaclar.ro/stiri/test-story/",
            expected_story_id="test-story",
        )
        self.assertTrue(result["readback_ok"])
        self.assertEqual(result["newsarticle_count"], 1)

    def test_site_readback_rejects_wrong_canonical(self):
        html = """
        <html><head>
        <link rel="canonical" href="https://valceaclar.ro/stiri/other-story/">
        <script type="application/ld+json">{"@type":"NewsArticle"}</script>
        </head></html>
        """
        result = inspect_html(
            html,
            requested_url="https://valceaclar.ro/stiri/test-story/",
            final_url="https://valceaclar.ro/stiri/test-story/",
            expected_story_id="test-story",
        )
        self.assertFalse(result["readback_ok"])

    def test_meta_readback_requires_matching_remote_id_and_permalink(self):
        ok = parse_meta_object(
            "facebook",
            "123_456",
            {"id": "123_456", "permalink_url": "https://facebook.example/posts/456"},
        )
        self.assertTrue(ok["readback_ok"])
        bad = parse_meta_object(
            "facebook",
            "123_456",
            {"id": "999", "permalink_url": "https://facebook.example/posts/999"},
        )
        self.assertFalse(bad["readback_ok"])

    def test_instagram_readback_accepts_permalink_field(self):
        result = parse_meta_object(
            "instagram",
            "180000",
            {"id": "180000", "permalink": "https://instagram.example/p/abc"},
        )
        self.assertTrue(result["readback_ok"])
        self.assertEqual(result["publication_authority"], "NONE")

    def test_meta_error_body_keeps_diagnostic_without_token(self):
        detail = parse_meta_error_body(
            b'{"error":{"message":"Unsupported get request","type":"GraphMethodException","code":100,"error_subcode":33,"fbtrace_id":"abc"}}'
        )
        self.assertEqual(detail["error_code"], 100)
        self.assertEqual(detail["error_subcode"], 33)
        self.assertEqual(detail["error_type"], "GraphMethodException")
        self.assertEqual(detail["error_message"], "Unsupported get request")
        self.assertNotIn("access_token", detail)

    def test_commons_provenance_jsonld_binds_exact_direct_asset_and_license(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG?utm_source=commons.wikimedia.org","license":"https://creativecommons.org/licenses/by-sa/3.0","name":"CET Govora"}
        </script>
        </head></html>
        """
        result = inspect_provenance_asset(
            html,
            expected_direct_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
        )
        self.assertTrue(result["asset_identity_ok"])
        self.assertTrue(result["license_present"])
        self.assertEqual(result["matching_imageobject_count"], 1)

    def test_commons_provenance_jsonld_rejects_wrong_asset(self):
        html = """
        <script type="application/ld+json">
        {"@type":"ImageObject","contentUrl":"https://upload.wikimedia.org/wikipedia/commons/x/x1/Other.JPG","license":"https://creativecommons.org/licenses/by/4.0"}
        </script>
        """
        result = inspect_provenance_asset(
            html,
            expected_direct_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
        )
        self.assertFalse(result["asset_identity_ok"])
        self.assertFalse(result["license_present"])

    def test_direct_429_fallback_is_narrow_to_verified_wikimedia_asset(self):
        ok, reason = _effective_direct_source_status(
            source_url="https://commons.wikimedia.org/wiki/File:CET_Govora_(dinspre_nord-vest).JPG",
            direct_source_url="https://upload.wikimedia.org/wikipedia/commons/a/a8/CET_Govora_%28dinspre_nord-vest%29.JPG",
            direct_source={"readback_ok": False, "rate_limited": True, "http_status": 429},
            provenance_asset={"asset_identity_ok": True, "license_present": True},
        )
        self.assertTrue(ok)
        self.assertEqual(reason, "wikimedia_commons_source_page_identity_fallback_for_direct_429")

        bad, bad_reason = _effective_direct_source_status(
            source_url="https://example.com/source",
            direct_source_url="https://example.com/image.jpg",
            direct_source={"readback_ok": False, "rate_limited": True, "http_status": 429},
            provenance_asset={"asset_identity_ok": True, "license_present": True},
        )
        self.assertFalse(bad)
        self.assertIsNone(bad_reason)

    def test_canonical_visual_binding_requires_same_asset_source_rights_and_verified_provenance(self):
        source_url = "https://commons.wikimedia.org/wiki/File:Expected.jpg"
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url=source_url,
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image={
                "public_url": "https://valceaclar.ro/media/social/expected.jpg",
                "source_url": source_url,
                "rights_basis": "creative_commons",
                "provenance_status": "VERIFIED",
            },
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "CONSISTENT")
        self.assertTrue(result["canonical_site_image_bound"])
        self.assertTrue(result["canonical_site_visual_filename_match"])
        self.assertTrue(result["canonical_site_visual_source_match"])
        self.assertTrue(result["canonical_site_visual_rights_match"])
        self.assertTrue(result["canonical_site_visual_provenance_verified"])

    def test_canonical_visual_binding_detects_social_visual_present_but_site_unbound(self):
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url="https://commons.wikimedia.org/wiki/File:Expected.jpg",
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image=None,
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "SOCIAL_VISUAL_PRESENT_SITE_UNBOUND")
        self.assertFalse(result["canonical_site_image_bound"])

    def test_canonical_visual_binding_detects_different_site_asset(self):
        source_url = "https://commons.wikimedia.org/wiki/File:Expected.jpg"
        result = _canonical_visual_binding(
            expected_image_path="valcea-clar/social/photos/approved/expected.jpg",
            visual_source_url=source_url,
            visual_rights_basis="creative_commons",
            real_visual=True,
            manifest_image={
                "public_url": "https://valceaclar.ro/media/social/other.jpg",
                "source_url": source_url,
                "rights_basis": "creative_commons",
                "provenance_status": "VERIFIED",
            },
        )
        self.assertEqual(result["canonical_site_visual_binding_state"], "SITE_BOUND_DIFFERENT_ASSET")
        self.assertFalse(result["canonical_site_visual_filename_match"])


if __name__ == "__main__":
    unittest.main()
