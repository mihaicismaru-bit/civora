import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "core_v2"
sys.path.insert(0, str(ROOT))

import shadow_site_package  # noqa: E402
from shadow_site_package import MAX_IMAGE_BYTES, _download_remote_image, build_shadow_packages  # noqa: E402
from site_visual_runtime_path_hydrator import hydrate_registry  # noqa: E402


class ShadowSitePackageTest(unittest.TestCase):
    @staticmethod
    def article_doc():
        return {
            "rows": [{
                "state": "VERIFIED_WRITTEN_SHADOW",
                "articles": [{
                    "article_id": "story-1",
                    "article_package": {
                        "headline": "Titlu verificat",
                        "dek": "Rezumat verificat",
                        "body": "Primul paragraf.\n\nAl doilea paragraf.",
                    },
                }],
            }]
        }

    @staticmethod
    def base_assignment(image_path="valcea-clar/social/photos/approved/story-1.jpg"):
        return {
            "image_path": image_path,
            "image": {
                "kind": "photograph",
                "synthetic": False,
                "alt_text": "Clădire publică într-o fotografie de arhivă.",
                "credit": "Autor / Commons — CC BY-SA 4.0",
                "editorial_note": "Foto de arhivă; nu surprinde evenimentul curent.",
                "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
                "direct_source_url": "https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg",
            },
        }

    @classmethod
    def registry(cls, image_path="valcea-clar/social/photos/approved/story-1.jpg"):
        return {"stories": {"story-1": cls.base_assignment(image_path)}}

    @staticmethod
    def photo_truth(readback_ok=True, *, exact_identity=False):
        external = {"readback_ok": readback_ok}
        if exact_identity:
            external.update({
                "direct_source_effective_ok": True,
                "direct_source_fallback_reason": "wikimedia_commons_source_page_identity_fallback_for_direct_429",
                "direct_source": {"http_status": 429, "rate_limited": True},
                "provenance_asset": {
                    "expected_filename": "Example.jpg",
                    "asset_identity_ok": True,
                    "license_present": True,
                },
            })
        return {
            "publication_authority": "NONE",
            "acceptance_ready": False,
            "rows": [{
                "story_id": "story-1",
                "status": "VISUAL_CANDIDATE_VERIFIED_SHADOW",
                "external_readback": external,
            }],
        }

    def test_local_staged_package_binds_expected_file_but_not_public_truth(self):
        with tempfile.TemporaryDirectory() as temp:
            repo = Path(temp) / "repo"
            image = repo / "valcea-clar/social/photos/approved/story-1.jpg"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"jpeg-test")
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(),
                visual_registry=self.registry(),
                repo_root=repo,
                output_dir=Path(temp) / "out",
            )
            self.assertEqual(report["package_image_bound_shadow_count"], 1)
            self.assertEqual(report["blocked_count"], 0)
            self.assertEqual(report["verified_remote_reference_bound_shadow_count"], 0)
            row = report["rows"][0]
            self.assertEqual(row["status"], "PACKAGE_IMAGE_BOUND_SHADOW")
            self.assertEqual(row["materialized_image"]["mode"], "checkout_copy")
            self.assertFalse(row["public_article_binding_verified"])
            self.assertFalse(row["visual_ready"])
            staged = Path(row["package_path"]).read_text(encoding="utf-8")
            self.assertIn('/media/story-1.jpg', staged)
            self.assertIn('Foto de arhivă', staged)

    def test_missing_checkout_image_blocks_without_remote_permission(self):
        with tempfile.TemporaryDirectory() as temp:
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=self.photo_truth(),
                visual_registry=self.registry(),
                repo_root=Path(temp),
                output_dir=Path(temp) / "out",
            )
            self.assertEqual(report["blocked_count"], 1)
            self.assertIn("visual image file missing", report["rows"][0]["reason"])

    def test_external_photo_readback_is_required_before_any_staging(self):
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

    def test_remote_materialization_uses_bounded_range_and_accepts_complete_206(self):
        payload = b"complete-jpeg-bytes"

        class FakeResponse:
            status = 206
            headers = {
                "Content-Type": "image/jpeg",
                "Content-Range": f"bytes 0-{len(payload)-1}/{len(payload)}",
            }
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
            def read(self, amount): return payload

        captured = {}
        def fake_urlopen(request, timeout):
            captured["range"] = request.headers.get("Range")
            captured["accept"] = request.headers.get("Accept")
            return FakeResponse()

        with patch.object(shadow_site_package, "urlopen", side_effect=fake_urlopen):
            data, content_type, attempts = _download_remote_image("https://example.test/image.jpg")
        self.assertEqual(data, payload)
        self.assertEqual(content_type, "image/jpeg")
        self.assertEqual(attempts, 1)
        self.assertEqual(captured["range"], f"bytes=0-{MAX_IMAGE_BYTES - 1}")
        self.assertEqual(captured["accept"], "image/*")

    def test_partial_206_is_rejected(self):
        class FakeResponse:
            status = 206
            headers = {"Content-Type": "image/jpeg", "Content-Range": "bytes 0-6/999"}
            def __enter__(self): return self
            def __exit__(self, exc_type, exc, tb): return False
            def read(self, amount): return b"partial"

        with patch.object(shadow_site_package, "urlopen", return_value=FakeResponse()):
            with self.assertRaisesRegex(ValueError, "complete image"):
                _download_remote_image("https://example.test/image.jpg")

    def test_exact_commons_asset_uses_verified_remote_reference_without_second_binary_fetch(self):
        original = "https://upload.wikimedia.org/wikipedia/commons/a/a9/Example.jpg"
        expected_thumb = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/a9/Example.jpg/960px-Example.jpg"
        raw_registry = {
            "publication_authority": "NONE",
            "stories": {"story-1": self.base_assignment(image_path="")},
        }
        truth = self.photo_truth(exact_identity=True)
        hydrated = hydrate_registry(raw_registry, truth)
        assignment = hydrated["stories"]["story-1"]
        self.assertEqual(hydrated["transport_fallback_story_count"], 1)
        self.assertTrue(assignment["runtime_transport_override_only"])
        self.assertEqual(assignment["runtime_materialization_canonical_direct_source_url"], original)
        self.assertEqual(assignment["runtime_materialization_url"], expected_thumb)
        self.assertEqual(assignment["image"]["canonical_direct_source_url"], original)

        with tempfile.TemporaryDirectory() as temp, patch.object(shadow_site_package, "urlopen") as network:
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=truth,
                visual_registry=hydrated,
                repo_root=Path(temp) / "repo",
                output_dir=Path(temp) / "out",
                allow_remote_materialization=True,
            )
            network.assert_not_called()
            row = report["rows"][0]
            staged = Path(row["package_path"]).read_text(encoding="utf-8")

        self.assertEqual(report["package_image_bound_shadow_count"], 1)
        self.assertEqual(report["verified_remote_reference_bound_shadow_count"], 1)
        self.assertEqual(report["blocked_count"], 0)
        self.assertEqual(row["materialized_image"]["mode"], "verified_remote_reference_read_only")
        self.assertEqual(row["materialized_image"]["canonical_source_url"], original)
        self.assertIn(expected_thumb, staged)
        self.assertFalse(row["public_article_binding_verified"])

    def test_remote_reference_fails_closed_if_runtime_canonical_identity_is_detached(self):
        truth = self.photo_truth(exact_identity=True)
        raw_registry = {
            "publication_authority": "NONE",
            "stories": {"story-1": self.base_assignment(image_path="")},
        }
        hydrated = hydrate_registry(raw_registry, truth)
        hydrated["stories"]["story-1"]["runtime_materialization_canonical_direct_source_url"] = (
            "https://upload.wikimedia.org/wikipedia/commons/0/00/Other.jpg"
        )
        with tempfile.TemporaryDirectory() as temp:
            report = build_shadow_packages(
                [self.article_doc()],
                photo_truth=truth,
                visual_registry=hydrated,
                repo_root=Path(temp) / "repo",
                output_dir=Path(temp) / "out",
                allow_remote_materialization=True,
            )
        self.assertEqual(report["package_image_bound_shadow_count"], 0)
        self.assertEqual(report["blocked_count"], 1)
        self.assertIn("canonical source mismatch", report["rows"][0]["reason"])


if __name__ == "__main__":
    unittest.main()
