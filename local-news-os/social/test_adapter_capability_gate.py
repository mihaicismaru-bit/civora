#!/usr/bin/env python3
"""Acceptance tests for truthful installed-adapter capability gating."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import adapter_capability_gate
import production_runtime
import test_production_runtime as runtime_fixture

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
CAPABILITY_PATH = REPO_ROOT / "valcea-clar/social/adapter_capabilities.json"
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
PRESENT_REFS = {
    "facebook": {"VALCEA_FB_PAGE_ACCESS_TOKEN"},
    "instagram": {"VALCEA_IG_ACCOUNT_ID", "VALCEA_IG_ACCESS_TOKEN"},
    "tiktok": {"VALCEA_TIKTOK_ACCESS_TOKEN", "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED"},
}


def _capabilities() -> dict:
    return json.loads(CAPABILITY_PATH.read_text(encoding="utf-8"))


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _runtime(platform: str, *, single_photo_only: bool = False, human_approved: bool = True) -> dict:
    if not single_photo_only:
        return runtime_fixture._run(platform, human_approved=human_approved)
    story = runtime_fixture._story()
    channel = runtime_fixture._load_channel(platform)
    channel["native_formats"] = ["single_photo"]
    return production_runtime.orchestrate_channel(
        story,
        channel,
        runtime_fixture._inventory(story["story_id"]),
        runtime_fixture._history(channel),
        now=runtime_fixture.READY_NOW,
        human_approved=human_approved,
        canonical_url=runtime_fixture.CANONICAL_URL,
    )


def _bridge(platform: str, *, report: dict | None = None, capabilities: dict | None = None, registry: dict | None = None, refs=None, outbox=None) -> dict:
    return adapter_capability_gate.bridge_runtime_handoff_with_capabilities(
        copy.deepcopy(report or _runtime(platform)),
        copy.deepcopy(registry or _registry()),
        copy.deepcopy(capabilities or _capabilities()),
        copy.deepcopy(PRESENT_REFS[platform] if refs is None else refs),
        copy.deepcopy(outbox),
    )


class AdapterCapabilityGateAcceptance(unittest.TestCase):
    def test_live_capability_registry_is_truthful_and_valid(self) -> None:
        result = adapter_capability_gate.validate_capability_registry_path(
            Path("valcea-clar/social/adapter_capabilities.json"),
            Path("valcea-clar/social/channel_registry.json"),
            REPO_ROOT,
        )
        self.assertEqual("PASS", result["status"], result["errors"])
        self.assertEqual(["facebook", "instagram", "tiktok"], result["direct_platforms"])
        self.assertFalse(result["guards"]["credential_values_read"])
        self.assertTrue(result["guards"]["zero_paid_dependency"])

    def test_facebook_current_native_product_remains_direct_ready(self) -> None:
        result = _bridge("facebook")
        self.assertFalse(result["blocked"])
        self.assertEqual("DIRECT_READY", result["dispatch_disposition"])
        self.assertEqual("DIRECT_READY", result["capability_disposition"])
        self.assertTrue(result["capability_gate"]["compatible"])
        self.assertEqual("single_photo", result["capability_gate"]["native_format"])
        self.assertTrue(result["adapter_handoff"]["dispatch_allowed"])

    def test_instagram_carousel_is_now_direct_ready_with_native_adapter(self) -> None:
        report = _runtime("instagram")
        self.assertEqual("carousel", report["artifacts"]["format"]["product"]["native_format"])
        selected = report["artifacts"]["visual"]["binding"]["selected_assets"]
        self.assertEqual(2, len(selected))
        self.assertEqual(["photograph", "photograph"], [asset["kind"] for asset in selected])
        result = _bridge("instagram", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("DIRECT_READY", result["dispatch_disposition"])
        self.assertEqual("DIRECT_READY", result["capability_disposition"])
        self.assertEqual([], result["capability_gap_reasons"])
        self.assertTrue(result["capability_gate"]["compatible"])
        self.assertEqual("carousel", result["capability_gate"]["native_format"])
        self.assertEqual(["photograph", "photograph"], result["capability_gate"]["selected_media_kinds"])
        self.assertTrue(result["adapter_handoff"]["dispatch_allowed"])
        item = next(iter(result["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("carousel", item["adapter_payload"]["native_product"]["native_format"])
        self.assertEqual(report["artifacts"]["format"]["product"], item["adapter_payload"]["native_product"])
        self.assertFalse(result["guards"]["native_product_rewritten"])
        self.assertFalse(result["guards"]["fallback_format_invented"])

    def test_tiktok_short_video_is_preserved_until_video_adapter_exists(self) -> None:
        report = _runtime("tiktok")
        self.assertEqual("short", report["artifacts"]["format"]["product"]["native_format"])
        selected = report["artifacts"]["visual"]["binding"]["selected_assets"]
        self.assertEqual(["video"], [asset["kind"] for asset in selected])
        result = _bridge("tiktok", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("OUTBOX_ONLY", result["dispatch_disposition"])
        self.assertEqual("OUTBOX_ONLY_CAPABILITY_GAP", result["capability_disposition"])
        self.assertIn("UNSUPPORTED_NATIVE_FORMAT:short", result["capability_gap_reasons"])
        self.assertIn("UNSUPPORTED_MEDIA_KIND:video", result["capability_gap_reasons"])
        self.assertIn("VIDEO_NATIVE_PRODUCT_WITHOUT_VIDEO_ADAPTER", result["capability_gap_reasons"])
        item = next(iter(result["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("short", item["adapter_payload"]["native_product"]["native_format"])
        self.assertFalse(result["guards"]["native_product_rewritten"])
        self.assertFalse(result["guards"]["fallback_format_invented"])

    def test_instagram_single_photo_can_use_existing_adapter_without_cross_post_fallback(self) -> None:
        report = _runtime("instagram", single_photo_only=True)
        self.assertEqual("single_photo", report["artifacts"]["format"]["product"]["native_format"])
        result = _bridge("instagram", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("DIRECT_READY", result["dispatch_disposition"])
        self.assertEqual("DIRECT_READY", result["capability_disposition"])
        self.assertTrue(result["capability_gate"]["compatible"])
        self.assertEqual(["photograph"], result["capability_gate"]["selected_media_kinds"])

    def test_tiktok_single_photo_can_use_existing_adapter_when_editorial_product_selects_it(self) -> None:
        report = _runtime("tiktok", single_photo_only=True)
        self.assertEqual("single_photo", report["artifacts"]["format"]["product"]["native_format"])
        result = _bridge("tiktok", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("DIRECT_READY", result["dispatch_disposition"])
        self.assertEqual("DIRECT_READY", result["capability_disposition"])
        self.assertEqual("async_remote_status", result["capability_gate"]["completion_model"])
        self.assertTrue(result["capability_gate"]["remote_reconciliation_supported"])

    def test_missing_capability_contract_blocks_direct_handoff_fail_closed(self) -> None:
        capabilities = _capabilities()
        capabilities["adapters"] = [row for row in capabilities["adapters"] if row["platform"] != "facebook"]
        result = _bridge("facebook", capabilities=capabilities)
        self.assertTrue(result["blocked"])
        self.assertEqual("BLOCKED_ADAPTER_CAPABILITY_CONTRACT", result["decision"])
        self.assertIn("DIRECT_ADAPTER_CAPABILITY_MISSING", result["hard_blocks"])
        self.assertIsNone(result["adapter_handoff"])

    def test_adapter_path_mismatch_blocks_instead_of_routing_to_another_adapter(self) -> None:
        capabilities = _capabilities()
        facebook = next(row for row in capabilities["adapters"] if row["platform"] == "facebook")
        facebook["adapter"] = "valcea-clar/social/instagram_publish.py"
        result = _bridge("facebook", capabilities=capabilities)
        self.assertTrue(result["blocked"])
        self.assertIn("CAPABILITY_ADAPTER_PATH_MISMATCH", result["hard_blocks"])

    def test_capability_contract_cannot_claim_video_format_on_photo_only_adapter(self) -> None:
        capabilities = _capabilities()
        tiktok = next(row for row in capabilities["adapters"] if row["platform"] == "tiktok")
        tiktok["supported_native_formats"] = ["single_photo", "short"]
        result = adapter_capability_gate.validate_capability_registry(
            capabilities,
            _registry(),
            load_channel=lambda path: json.loads((REPO_ROOT / path).read_text(encoding="utf-8")),
            instance_root="valcea-clar",
        )
        self.assertEqual("BLOCKED", result["status"])
        self.assertIn("tiktok:VIDEO_FORMAT_DECLARED_WITHOUT_VIDEO_CAPABILITY", result["errors"])

    def test_capability_registry_rejects_secret_bearing_fields(self) -> None:
        capabilities = _capabilities()
        facebook = next(row for row in capabilities["adapters"] if row["platform"] == "facebook")
        facebook["access_token"] = "EAA_FAKE_SECRET"
        result = adapter_capability_gate.validate_capability_registry(
            capabilities,
            _registry(),
            instance_root="valcea-clar",
        )
        self.assertEqual("BLOCKED", result["status"])
        self.assertTrue(any("MUST_NOT_CONTAIN_SECRETS" in error for error in result["errors"]))

    def test_upstream_human_approval_hold_is_not_weakened_by_capability_gate(self) -> None:
        report = _runtime("tiktok", human_approved=False)
        self.assertEqual("AWAITING_APPROVAL", report["disposition"])
        result = _bridge("tiktok", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("HOLD_UPSTREAM", result["dispatch_disposition"])
        self.assertEqual("NOT_APPLICABLE_UPSTREAM_NOT_READY", result["capability_disposition"])
        self.assertIsNone(result["adapter_handoff"])

    def test_capability_result_is_deterministic_and_keeps_zero_paid_guards(self) -> None:
        report = _runtime("instagram")
        first = _bridge("instagram", report=report)
        second = _bridge("instagram", report=report)
        self.assertEqual(first, second)
        self.assertEqual("DIRECT_READY", first["dispatch_disposition"])
        self.assertTrue(first["guards"]["zero_paid_dependency"])
        self.assertFalse(first["guards"]["credential_values_read_by_capability_gate"])
        self.assertFalse(first["guards"]["network_dispatch_performed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
