#!/usr/bin/env python3
"""Acceptance tests for VÂLCEA CLAR native TikTok short/video publishing."""
from __future__ import annotations

import copy
import unittest

import tiktok_publish


class TikTokNativeVideoAcceptance(unittest.TestCase):
    def payload(self, native_format: str = "short") -> dict:
        return tiktok_publish._test_native_payload(native_format)

    def settings(self, native_format: str = "short") -> dict:
        return tiktok_publish._test_publish_settings(native_format)

    def creator(self, token: str) -> dict:
        self.assertEqual("runtime-token", token)
        return {
            "creator_username": "valceaclar",
            "creator_nickname": "Vâlcea Clar",
            "privacy_level_options": ["PUBLIC_TO_EVERYONE", "SELF_ONLY"],
            "comment_disabled": False,
            "duet_disabled": False,
            "stitch_disabled": False,
        }

    def test_short_payload_requires_exactly_one_real_video(self) -> None:
        result = tiktok_publish.validate_native_payload(self.payload())
        self.assertEqual("short", result["native_format"])
        self.assertEqual("video", result["media"]["kind"])
        self.assertEqual(
            "https://valceaclar.ro/media/social/native-test.mp4",
            result["media"]["media_url"],
        )

    def test_single_photo_native_payload_remains_supported(self) -> None:
        result = tiktok_publish.validate_native_payload(self.payload("single_photo"))
        self.assertEqual("single_photo", result["native_format"])
        self.assertEqual("photograph", result["media"]["kind"])

    def test_short_rejects_photograph_instead_of_format_downgrade(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0] = tiktok_publish._test_asset("photograph")
        binding["selected_asset_ids"] = [binding["selected_assets"][0]["asset_id"]]
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = tiktok_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "must be video"):
            tiktok_publish.validate_native_payload(payload)

    def test_synthetic_video_is_fail_closed(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0]["synthetic"] = True
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = tiktok_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "synthetic"):
            tiktok_publish.validate_native_payload(payload)

    def test_missing_reuse_rights_is_fail_closed(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0]["rights_basis"] = ""
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = tiktok_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "reuse rights"):
            tiktok_publish.validate_native_payload(payload)

    def test_media_must_use_verified_valceaclar_domain(self) -> None:
        payload = self.payload()
        binding = payload["visual_binding"]
        binding["selected_assets"][0]["direct_source_url"] = "https://cdn.example.invalid/video.mp4"
        binding.pop("binding_fingerprint_sha256", None)
        binding["binding_fingerprint_sha256"] = tiktok_publish._digest(binding)
        with self.assertRaisesRegex(ValueError, "verified valceaclar.ro domain"):
            tiktok_publish.validate_native_payload(payload)

    def test_tampered_native_product_fingerprint_is_rejected(self) -> None:
        payload = self.payload()
        payload["native_product"]["hook"]["text"] = "Text changed after orchestration"
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            tiktok_publish.validate_native_payload(payload)

    def test_secret_bearing_adapter_payload_is_rejected(self) -> None:
        payload = self.payload()
        payload["access_token"] = "secret"
        with self.assertRaisesRegex(ValueError, "credential values"):
            tiktok_publish.validate_native_payload(payload)

    def test_explicit_consent_music_confirmation_and_interaction_choices_are_required(self) -> None:
        no_consent = self.settings()
        no_consent["consent"]["granted"] = False
        with self.assertRaisesRegex(ValueError, "publish consent"):
            tiktok_publish.validate_publish_settings(no_consent, native_format="short")

        no_music = self.settings()
        no_music["music_usage_confirmed"] = False
        with self.assertRaisesRegex(ValueError, "Music Usage Confirmation"):
            tiktok_publish.validate_publish_settings(no_music, native_format="short")

        no_choice = self.settings()
        no_choice.pop("allow_duet")
        with self.assertRaisesRegex(ValueError, "allow_duet"):
            tiktok_publish.validate_publish_settings(no_choice, native_format="short")

    def test_creator_privacy_options_are_queried_before_video_submission(self) -> None:
        settings = self.settings()
        settings["privacy_level"] = "FOLLOWER_OF_CREATOR"
        calls: list[str] = []

        def creator(token: str) -> dict:
            calls.append("creator_info")
            return self.creator(token)

        def request(path: str, token: str, *, payload: dict) -> dict:
            calls.append("network")
            return {"data": {"publish_id": "should-not-run"}, "error": {"code": "ok"}}

        with self.assertRaisesRegex(RuntimeError, "not currently allowed"):
            tiktok_publish.publish_native_payload(
                self.payload(),
                token="runtime-token",
                publish_settings=settings,
                creator_query_fn=creator,
                request_fn=request,
                video_preflight_fn=lambda url: None,
            )
        self.assertEqual(["creator_info"], calls)

    def test_video_submission_uses_native_video_init_and_returns_submission_not_fake_publication(self) -> None:
        calls: list[tuple[str, dict]] = []
        preflight: list[str] = []

        def request(path: str, token: str, *, payload: dict) -> dict:
            self.assertEqual("runtime-token", token)
            calls.append((path, copy.deepcopy(payload)))
            return {"data": {"publish_id": "v_pub_url~abc123"}, "error": {"code": "ok"}}

        result = tiktok_publish.publish_native_payload(
            self.payload(),
            token="runtime-token",
            publish_settings=self.settings(),
            creator_query_fn=self.creator,
            request_fn=request,
            video_preflight_fn=preflight.append,
        )
        self.assertEqual(
            ["https://valceaclar.ro/media/social/native-test.mp4"], preflight
        )
        self.assertEqual(1, len(calls))
        path, body = calls[0]
        self.assertEqual("/v2/post/publish/video/init/", path)
        self.assertEqual("PULL_FROM_URL", body["source_info"]["source"])
        self.assertEqual(
            "https://valceaclar.ro/media/social/native-test.mp4",
            body["source_info"]["video_url"],
        )
        self.assertEqual("PUBLIC_TO_EVERYONE", body["post_info"]["privacy_level"])
        self.assertFalse(body["post_info"]["disable_comment"])
        self.assertTrue(body["post_info"]["disable_duet"])
        self.assertTrue(body["post_info"]["disable_stitch"])
        self.assertFalse(body["post_info"]["brand_content_toggle"])
        self.assertFalse(body["post_info"]["brand_organic_toggle"])
        self.assertFalse(body["post_info"]["is_aigc"])
        self.assertIn("Trafic restricționat temporar", body["post_info"]["title"])
        self.assertIn("Intervalul verificat", body["post_info"]["title"])
        self.assertEqual("v_pub_url~abc123", result["remote_submission_id"])
        self.assertFalse(result["publication_confirmed"])
        self.assertNotIn("remote_publication_id", result)

    def test_creator_disabled_interactions_cannot_be_reenabled_by_local_settings(self) -> None:
        bodies: list[dict] = []

        def creator(token: str) -> dict:
            value = self.creator(token)
            value.update({"comment_disabled": True, "duet_disabled": True, "stitch_disabled": True})
            return value

        def request(path: str, token: str, *, payload: dict) -> dict:
            bodies.append(copy.deepcopy(payload))
            return {"data": {"publish_id": "v_pub_url~disabled"}, "error": {"code": "ok"}}

        settings = self.settings()
        settings.update({"allow_comment": True, "allow_duet": True, "allow_stitch": True})
        tiktok_publish.publish_native_payload(
            self.payload(), token="runtime-token", publish_settings=settings,
            creator_query_fn=creator, request_fn=request,
            video_preflight_fn=lambda url: None,
        )
        post = bodies[0]["post_info"]
        self.assertTrue(post["disable_comment"])
        self.assertTrue(post["disable_duet"])
        self.assertTrue(post["disable_stitch"])

    def test_status_reconciliation_requires_public_post_id_for_published_state(self) -> None:
        def response(data: dict):
            def request(path: str, token: str, *, payload: dict) -> dict:
                self.assertEqual("/v2/post/publish/status/fetch/", path)
                self.assertEqual({"publish_id": "v_pub_url~abc123"}, payload)
                return {"data": copy.deepcopy(data), "error": {"code": "ok"}}
            return request

        pending = tiktok_publish.reconcile_native_submission(
            "runtime-token", "v_pub_url~abc123",
            request_fn=response({"status": "PROCESSING_DOWNLOAD"}),
        )
        self.assertEqual("PENDING", pending["state"])
        self.assertFalse(pending["publication_confirmed"])

        proof_missing = tiktok_publish.reconcile_native_submission(
            "runtime-token", "v_pub_url~abc123",
            request_fn=response({"status": "PUBLISH_COMPLETE"}),
        )
        self.assertEqual("PENDING_PUBLICATION_PROOF", proof_missing["state"])
        self.assertFalse(proof_missing["publication_confirmed"])

        published = tiktok_publish.reconcile_native_submission(
            "runtime-token", "v_pub_url~abc123",
            request_fn=response({
                "status": "PUBLISH_COMPLETE",
                "publicaly_available_post_id": ["7499900011223344556"],
            }),
        )
        self.assertEqual("PUBLISHED", published["state"])
        self.assertEqual("7499900011223344556", published["remote_publication_id"])
        self.assertTrue(published["publication_confirmed"])

        failed = tiktok_publish.reconcile_native_submission(
            "runtime-token", "v_pub_url~abc123",
            request_fn=response({"status": "FAILED", "fail_reason": "video_pull_failed"}),
        )
        self.assertEqual("FAILED", failed["state"])
        self.assertFalse(failed["publication_confirmed"])

    def test_runtime_token_is_required_but_never_part_of_durable_payload(self) -> None:
        payload = self.payload()
        self.assertFalse(tiktok_publish._contains_secret_field(payload))
        with self.assertRaisesRegex(ValueError, "runtime access token"):
            tiktok_publish.publish_native_payload(
                payload,
                token="",
                publish_settings=self.settings(),
                creator_query_fn=self.creator,
                video_preflight_fn=lambda url: None,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
