#!/usr/bin/env python3
"""Acceptance tests for the VÂLCEA CLAR Instagram native carousel adapter."""
from __future__ import annotations

import copy
import unittest

import instagram_publish


class InstagramNativeCarouselAcceptance(unittest.TestCase):
    def payload(self, native_format: str = "carousel") -> dict:
        return instagram_publish._test_native_payload(native_format)

    def test_carousel_payload_preserves_two_distinct_real_assets(self) -> None:
        result = instagram_publish.validate_native_payload(self.payload())
        self.assertEqual("carousel", result["native_format"])
        self.assertEqual(2, len(result["media"]))
        self.assertEqual(["asset-a", "asset-b"], [item["asset_id"] for item in result["media"]])
        self.assertEqual(
            [
                "https://valceaclar.ro/media/social/a.jpg",
                "https://valceaclar.ro/media/social/b.jpg",
            ],
            [item["image_url"] for item in result["media"]],
        )

    def test_single_photo_native_payload_remains_supported(self) -> None:
        result = instagram_publish.validate_native_payload(self.payload("single_photo"))
        self.assertEqual("single_photo", result["native_format"])
        self.assertEqual(1, len(result["media"]))

    def test_carousel_with_one_asset_fails_instead_of_silent_downgrade(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"] = binding["selected_assets"][:1]
        binding["selected_asset_ids"] = binding["selected_asset_ids"][:1]
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = instagram_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "carousel requires 2-10"):
            instagram_publish.validate_native_payload(payload)

    def test_synthetic_asset_is_fail_closed(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0]["synthetic"] = True
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = instagram_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "synthetic"):
            instagram_publish.validate_native_payload(payload)

    def test_missing_reuse_rights_is_fail_closed(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0]["rights_basis"] = ""
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = instagram_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "reuse rights"):
            instagram_publish.validate_native_payload(payload)

    def test_duplicate_carousel_media_is_rejected(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        duplicate = copy.deepcopy(binding["selected_assets"][0])
        binding["selected_assets"][1] = duplicate
        binding["selected_asset_ids"][1] = duplicate["asset_id"]
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = instagram_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "cannot repeat"):
            instagram_publish.validate_native_payload(payload)

    def test_tampered_native_product_fingerprint_is_rejected(self) -> None:
        payload = self.payload()
        payload["native_product"]["hook"]["text"] = "Text altered after orchestration"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            instagram_publish.validate_native_payload(payload)

    def test_secret_bearing_adapter_payload_is_rejected(self) -> None:
        payload = self.payload()
        payload["access_token"] = "EAA_FAKE"
        with self.assertRaisesRegex(ValueError, "credential values"):
            instagram_publish.validate_native_payload(payload)

    def test_graph_api_sequence_builds_children_then_carousel_parent_then_publish(self) -> None:
        payload = self.payload()
        post_calls: list[tuple[str, dict]] = []
        get_calls: list[str] = []
        preflight_urls: list[str] = []
        child_counter = {"value": 0}

        def fake_post(host: str, version: str, path: str, token: str, fields: dict[str, str]) -> dict:
            self.assertEqual("graph.facebook.com", host)
            self.assertEqual("v26.0", version)
            self.assertEqual("runtime-token", token)
            post_calls.append((path, copy.deepcopy(fields)))
            if path.endswith("/media_publish"):
                return {"id": "ig-media-123"}
            if fields.get("is_carousel_item") == "true":
                child_counter["value"] += 1
                return {"id": f"child-{child_counter['value']}"}
            if fields.get("media_type") == "CAROUSEL":
                return {"id": "carousel-parent"}
            raise AssertionError(f"unexpected Graph call: {path} {fields}")

        def fake_get(host: str, version: str, path: str, token: str, params: dict[str, str]) -> dict:
            self.assertEqual("runtime-token", token)
            self.assertEqual({"fields": "status_code"}, params)
            get_calls.append(path)
            return {"status_code": "FINISHED"}

        result = instagram_publish.publish_native_payload(
            payload,
            account_id="ig-account",
            token="runtime-token",
            graph_post_fn=fake_post,
            graph_get_fn=fake_get,
            preflight_fn=preflight_urls.append,
            sleep_fn=lambda _: None,
        )

        self.assertTrue(result["success"])
        self.assertEqual("ig-media-123", result["remote_publication_id"])
        self.assertEqual(["child-1", "child-2"], result["child_container_ids"])
        self.assertEqual(
            [
                "https://valceaclar.ro/media/social/a.jpg",
                "https://valceaclar.ro/media/social/b.jpg",
            ],
            preflight_urls,
        )
        child_calls = [fields for path, fields in post_calls if path.endswith("/media") and fields.get("is_carousel_item") == "true"]
        self.assertEqual(2, len(child_calls))
        parent_calls = [fields for path, fields in post_calls if path.endswith("/media") and fields.get("media_type") == "CAROUSEL"]
        self.assertEqual(1, len(parent_calls))
        self.assertEqual("child-1,child-2", parent_calls[0]["children"])
        self.assertEqual("Titlu verificat\n\nContext verificat.", parent_calls[0]["caption"])
        self.assertEqual(["child-1", "child-2", "carousel-parent"], get_calls)
        self.assertTrue(post_calls[-1][0].endswith("/media_publish"))
        self.assertEqual("carousel-parent", post_calls[-1][1]["creation_id"])

    def test_runtime_credentials_are_required_but_never_part_of_payload(self) -> None:
        payload = self.payload()
        self.assertFalse(instagram_publish._contains_secret_field(payload))
        with self.assertRaisesRegex(ValueError, "runtime account id and token"):
            instagram_publish.publish_native_payload(payload, account_id="", token="")


if __name__ == "__main__":
    unittest.main(verbosity=2)
