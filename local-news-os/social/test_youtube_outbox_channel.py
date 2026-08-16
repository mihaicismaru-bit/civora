#!/usr/bin/env python3
"""Acceptance tests for YouTube Shorts as an independent durable-outbox publication.

No YouTube upload credentials or verified adapter are assumed. The acceptance target is
therefore a complete native video product with real-media provenance, independent state,
and an idempotent OUTBOX_ONLY bridge handoff. Direct publication must remain impossible.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

import adapter_dispatch_bridge
import production_runtime


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
YOUTUBE_CONFIG = REPO_ROOT / "valcea-clar/social/channels/youtube.json"
TIKTOK_CONFIG = REPO_ROOT / "valcea-clar/social/channels/tiktok.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
NOW = "2026-08-16T09:00:00Z"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "youtube-outbox-traffic-20260816",
        "material_fact_gate": "PASS",
        "headline": "Trafic restricționat temporar pe un tronson din Râmnicu Vâlcea",
        "dek": "Restricția este programată între 08:00 și 18:00, iar șoferii vor fi deviați pe ruta semnalizată.",
        "paragraphs": [
            "Măsura este temporară și vizează intervalul anunțat în notificarea verificată.",
            "Semnalizarea din teren indică ruta alternativă pentru traficul local.",
        ],
        "facts": [
            {"fact_id": "f1", "text": "Intervalul anunțat este 08:00–18:00."},
            {"fact_id": "f2", "text": "Traficul este deviat pe ruta semnalizată."},
        ],
        "quotes": [
            {"quote_id": "q1", "text": "Respectați semnalizarea temporară din zonă."},
        ],
        "topics": ["service_journalism", "local_events", "infrastructure", "civic_updates"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo", "carousel", "short"],
        "confidence": 99,
        "locality": 1.0,
        "proximity": 1.0,
        "utility": 0.95,
        "share_value": 0.82,
        "save_value": 0.72,
        "conversation_value": 0.55,
        "urgency": 0.35,
        "lifecycle_stage": "baseline",
    }


def _inventory(story_id: str, *, include_video: bool = True) -> dict:
    assets = [
        {
            "instance_id": "valcea",
            "asset_id": "youtube-real-photo-a",
            "kind": "photo",
            "sha256": _digest("youtube-real-photo-a"),
            "synthetic": False,
            "subject_match": True,
            "editor_approved": True,
            "story_ids": [story_id],
            "source_type": "staff",
            "rights_basis": "owned",
            "credit": "VÂLCEA CLAR / acceptance fixture",
            "alt_text": "Semnalizare temporară de trafic într-o zonă urbană din Râmnicu Vâlcea.",
        }
    ]
    if include_video:
        assets.append(
            {
                "instance_id": "valcea",
                "asset_id": "youtube-real-video-a",
                "kind": "video",
                "sha256": _digest("youtube-real-video-a"),
                "synthetic": False,
                "subject_match": True,
                "editor_approved": True,
                "story_ids": [story_id],
                "source_type": "staff",
                "rights_basis": "owned",
                "credit": "VÂLCEA CLAR / acceptance fixture",
                "alt_text": "Secvență video reală cu semnalizarea temporară și traseul de deviere.",
            }
        )
    return {"instance_id": "valcea", "assets": assets}


def _history(channel: dict) -> dict:
    return {
        "instance_id": channel["instance_id"],
        "channel_id": channel["channel_id"],
        "records": [],
    }


def _run(channel: dict, *, include_video: bool = True, canonical_url: str | None = None) -> dict:
    story = _story()
    return production_runtime.orchestrate_channel(
        story,
        channel,
        _inventory(story["story_id"], include_video=include_video),
        _history(channel),
        now=NOW,
        human_approved=True,
        canonical_url=canonical_url,
    )


class YouTubeOutboxAcceptance(unittest.TestCase):
    def setUp(self) -> None:
        self.youtube = _load(YOUTUBE_CONFIG)
        self.tiktok = _load(TIKTOK_CONFIG)
        self.registry = _load(REGISTRY_PATH)

    def test_channel_is_configured_as_independent_outbox_only_publication(self) -> None:
        self.assertEqual("youtube", self.youtube["platform"])
        self.assertEqual("valcea-youtube", self.youtube["channel_id"])
        self.assertEqual("outbox_only", self.youtube["status"])
        self.assertEqual(["short", "long_video"], self.youtube["native_formats"])
        self.assertEqual("none:youtube-upload-access-not-verified", self.youtube["credentials_ref"])
        self.assertEqual("valcea-clar/social/youtube_outbox.json", self.youtube["publication_state"]["outbox_path"])
        self.assertEqual("valcea-clar/social/youtube_state.json", self.youtube["publication_state"]["state_path"])
        self.assertTrue(self.youtube["metrics"]["observed_only"])
        self.assertEqual([], self.youtube["metrics"]["sources"])
        self.assertTrue(self.youtube["zero_paid_dependency"])

    def test_runtime_builds_native_short_from_shared_verified_fact_kernel(self) -> None:
        report = _run(self.youtube)
        self.assertFalse(report["blocked"])
        self.assertEqual("OUTBOX_READY", report["disposition"])
        self.assertTrue(report["handoff"]["durable_outbox_ready"])
        self.assertFalse(report["handoff"]["adapter_dispatch_eligible"])

        product = report["artifacts"]["format"]["product"]
        self.assertEqual("short", product["native_format"])
        self.assertEqual("video_package", product["format_family"])
        self.assertEqual("short_video", product["native_structure"]["surface"])
        self.assertFalse(product["native_structure"]["voiceover_generation_allowed"])
        self.assertEqual("NATIVE_PRODUCT_ONLY", product["cross_post_policy"])
        self.assertFalse(product["verbatim_cross_platform_reuse_allowed"])
        self.assertFalse(product["analytics_used"])

    def test_youtube_and_tiktok_are_independently_formatted_sibling_products(self) -> None:
        youtube_report = _run(self.youtube)
        tiktok_report = _run(self.tiktok)
        youtube_product = youtube_report["artifacts"]["format"]["product"]
        tiktok_product = tiktok_report["artifacts"]["format"]["product"]

        self.assertEqual("short", youtube_product["native_format"])
        self.assertEqual("short", tiktok_product["native_format"])
        self.assertNotEqual(youtube_product["product_id"], tiktok_product["product_id"])
        self.assertNotEqual(
            youtube_product["product_fingerprint_sha256"],
            tiktok_product["product_fingerprint_sha256"],
        )
        self.assertEqual(4, len(youtube_product["content_blocks"]))
        self.assertEqual(3, len(tiktok_product["content_blocks"]))
        self.assertNotEqual(youtube_product, tiktok_product)

    def test_visual_router_requires_and_binds_real_video_with_provenance(self) -> None:
        report = _run(self.youtube)
        binding = report["artifacts"]["visual"]["binding"]
        self.assertEqual("VISUAL_READY", binding["status"])
        self.assertEqual(["youtube-real-video-a"], binding["selected_asset_ids"])
        self.assertEqual("video", binding["selected_assets"][0]["kind"])
        self.assertTrue(binding["provenance_complete"])
        self.assertTrue(binding["reuse_rights_complete"])
        self.assertFalse(binding["synthetic_media_used"])

    def test_missing_real_video_fails_closed_before_outbox(self) -> None:
        report = _run(self.youtube, include_video=False)
        self.assertTrue(report["blocked"])
        self.assertEqual("BLOCKED_VISUAL", report["disposition"])
        self.assertIn("INSUFFICIENT_APPROVED_REAL_MEDIA", report["hard_blocks"])
        self.assertNotIn("publication", report["artifacts"])

    def test_native_complete_short_does_not_require_site_link(self) -> None:
        report = _run(self.youtube, canonical_url=None)
        self.assertFalse(report["blocked"])
        self.assertEqual("NATIVE_STANDALONE", report["artifacts"]["link_binding"]["status"])
        self.assertEqual("OUTBOX_READY", report["disposition"])

    def test_bridge_persists_outbox_only_and_cannot_claim_direct_publish(self) -> None:
        report = _run(self.youtube)
        bridged = adapter_dispatch_bridge.bridge_runtime_handoff(report, self.registry, present_refs=set())
        self.assertFalse(bridged["blocked"])
        self.assertEqual("OUTBOX_ONLY", bridged["dispatch_disposition"])
        self.assertEqual("OUTBOX_READY", bridged["publication_status_after_bridge"])
        self.assertEqual("OUTBOX_ONLY", bridged["runtime_gate"]["decision"])
        self.assertTrue(bridged["adapter_handoff"]["durable_outbox_only"])
        self.assertFalse(bridged["adapter_handoff"]["dispatch_allowed"])
        self.assertIsNone(bridged["adapter_handoff"]["adapter"])
        self.assertEqual([], bridged["adapter_handoff"]["credential_reference_names"])
        self.assertFalse(bridged["guards"]["network_dispatch_performed"])
        self.assertTrue(bridged["guards"]["zero_paid_dependency"])

        outbox_items = bridged["commit_bundle"]["outbox"]["items"]
        self.assertEqual(1, len(outbox_items))
        item = next(iter(outbox_items.values()))
        self.assertEqual("valcea-clar/social/youtube_outbox.json", item["physical_outbox_path"])
        self.assertEqual("valcea-clar/social/youtube_state.json", item["physical_state_path"])
        self.assertFalse(item["credential_values_included"])
        self.assertFalse(item["network_dispatch_performed"])
        self.assertEqual(
            report["artifacts"]["format"]["product"],
            item["adapter_payload"]["native_product"],
        )

    def test_bridge_outbox_registration_is_idempotent(self) -> None:
        report = _run(self.youtube)
        first = adapter_dispatch_bridge.bridge_runtime_handoff(report, self.registry, present_refs=set())
        second = adapter_dispatch_bridge.bridge_runtime_handoff(
            report,
            self.registry,
            present_refs=set(),
            outbox=first["commit_bundle"]["outbox"],
        )
        self.assertFalse(second["blocked"])
        self.assertEqual("DEDUPE_EXISTING_HANDOFF", second["decision"])
        self.assertEqual("OUTBOX_ONLY", second["dispatch_disposition"])
        self.assertEqual(1, len(second["commit_bundle"]["outbox"]["items"]))

    def test_registry_never_invents_unverified_youtube_adapter_or_credentials(self) -> None:
        entries = [row for row in self.registry["channels"] if row.get("channel_id") == "youtube"]
        self.assertEqual(1, len(entries))
        entry = entries[0]
        self.assertFalse(entry["direct_publication_enabled"])
        self.assertEqual("durable_outbox_only", entry["publication_mode"])
        self.assertIsNone(entry["adapter"])
        self.assertIsNone(entry["credentials"])
        self.assertFalse(entry["requirements"]["verified_upload_access"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
