import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

from shadow_site_package import build_shadow_packages


class ShadowSitePackageTest(unittest.TestCase):
    @staticmethod
    def article_doc():
        return {
            "rows": [
                {
                    "state": "VERIFIED_WRITTEN_SHADOW",
                    "articles": [
                        {
                            "article_id": "story-1",
                            "article_package": {
                                "headline": "Titlu verificat",
                                "dek": "Rezumat verificat",
                                "body": "Primul paragraf.\n\nAl doilea paragraf.",
                            },
                        }
                    ],
                }
            ]
        }

    @staticmethod
    def registry():
        return {
            "stories": {
                "story-1": {
                    "image_path": "valcea-clar/social/photos/approved/story-1.jpg",
                    "image": {
                        "alt_text": "Clădire publică într-o fotografie de arhivă.",
                        "credit": "Autor / Commons — CC BY-SA 4.0",
                        "editorial_note": "Foto de arhivă; nu surprinde evenimentul curent.",
                        "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                        "direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg",
                    },
                }
            }
        }

    @staticmethod
    def photo_truth(readback_ok=True):
        return {
            "rows": [
                {
                    "story_id": "story-1",
                    "status": "VISUAL_CANDIDATE_VERIFIED_SHADOW",
                    "external_readback": {"readback_ok": readback_ok},
                }
            ]
        }

    def test_staged_package_binds_expected_file_but_not_public_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            image = repo / "valcea-clar/social/photos/approved/story-1.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg-test")
            output_dir = Path(temp) / "out"
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(),
                visual_registry=self.registry(),
                repo_root=repo,
                output_dir=output_dir,
            )
            self.assertEqual(report["package_image_bound_shadow_count"], 1)
            self.assertEqual(report["blocked_count"], 0)
            self.assertFalse(report["public_article_binding_verified"])
            self.assertFalse(report["visual_ready"])
            row = report["rows"][0]
            self.assertEqual(row["status"], "PACKAGE_IMAGE_BOUND_SHADOW")
            self.assertTrue(row["staged_package_binding_verified"])
            self.assertFalse(row["public_article_binding_verified"])
            html = Path(row["package_path"]).read_text(encoding="utf-8")
            self.assertIn('/media/story-1.jpg', html)
            self.assertIn('Foto de arhivă', html)
            self.assertIn('Credit:', html)

    def test_missing_checkout_image_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(),
                visual_registry=self.registry(),
                repo_root=Path(temp),
                output_dir=Path(temp) / "out",
            )
            self.assertEqual(report["package_image_bound_shadow_count"], 0)
            self.assertEqual(report["blocked_count"], 1)
            self.assertEqual(report["rows"][0]["status"], "BLOCKED")
            self.assertIn("visual image file missing", report["rows"][0]["reason"])

    def test_external_photo_readback_is_required_before_staging(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            image = repo / "valcea-clar/social/photos/approved/story-1.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg-test")
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(readback_ok=False),
                visual_registry=self.registry(),
                repo_root=repo,
                output_dir=Path(temp) / "out",
            )
            self.assertEqual(report["blocked_count"], 1)
            self.assertEqual(report["rows"][0]["reason"], "photo_external_readback_not_verified")

    def test_pre_materialized_shadow_image_is_reused_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            output_dir = Path(temp) / "out"
            cached = output_dir / "media/story-1.jpg"
            cached.parent.mkdir(parents=True)
            cached.write_bytes(b"verified-shadow-image")
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(),
                visual_registry=self.registry(),
                repo_root=Path(temp) / "repo",
                output_dir=output_dir,
                allow_remote_materialization=True,
            )
            self.assertEqual(report["package_image_bound_shadow_count"], 1)
            self.assertEqual(report["blocked_count"], 0)
            row = report["rows"][0]
            self.assertEqual(row["materialized_image"]["mode"], "shadow_cache_reuse")
            self.assertFalse(row["public_article_binding_verified"])
            self.assertFalse(row["visual_ready"])


if __name__ == "__main__":
    unittest.main()
