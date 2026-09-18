import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

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


if __name__ == "__main__":
    unittest.main()
