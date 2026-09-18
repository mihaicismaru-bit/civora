import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from external_readback import inspect_html
from meta_readback import parse_meta_error_body, parse_meta_object


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


if __name__ == "__main__":
    unittest.main()
