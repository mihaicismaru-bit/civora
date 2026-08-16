#!/usr/bin/env python3
"""Acceptance tests for the adapter-gated social dispatch bridge."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import adapter_dispatch_bridge
import test_production_runtime as runtime_fixture


HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
REGISTRY_PATH = REPO_ROOT / "valcea-clar/social/channel_registry.json"
PRESENT_REFS = {
    "facebook": {"VALCEA_FB_PAGE_ACCESS_TOKEN"},
    "instagram": {"VALCEA_IG_ACCOUNT_ID", "VALCEA_IG_ACCESS_TOKEN"},
    "tiktok": {"VALCEA_TIKTOK_ACCESS_TOKEN", "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED"},
}


def _registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _runtime(platform: str = "facebook", *, human_approved: bool = True) -> dict:
    return runtime_fixture._run(platform, human_approved=human_approved)


def _bridge(platform: str = "facebook", *, refs=None, report: dict | None = None, registry: dict | None = None, outbox: dict | None = None) -> dict:
    return adapter_dispatch_bridge.bridge_runtime_handoff(
        copy.deepcopy(report or _runtime(platform)),
        copy.deepcopy(registry or _registry()),
        copy.deepcopy(PRESENT_REFS[platform] if refs is None else refs),
        copy.deepcopy(outbox),
    )


class AdapterDispatchBridgeAcceptance(unittest.TestCase):
    def test_three_active_publications_become_direct_ready_without_dispatch(self) -> None:
        results = {platform: _bridge(platform) for platform in ("facebook", "instagram", "tiktok")}
        for platform, result in results.items():
            self.assertFalse(result["blocked"], platform)
            self.assertEqual("DIRECT_READY", result["dispatch_disposition"], platform)
            self.assertTrue(result["adapter_handoff"]["dispatch_allowed"], platform)
            self.assertFalse(result["guards"]["credential_values_read"], platform)
            self.assertFalse(result["guards"]["network_dispatch_performed"], platform)
            self.assertTrue(result["commit_bundle"]["atomic_persist_required"], platform)
            self.assertEqual("READY", result["publication_status_after_bridge"], platform)

        self.assertEqual(3, len({result["adapter_handoff"]["handoff_id"] for result in results.values()}))
        self.assertEqual(3, len({result["channel_id"] for result in results.values()}))

    def test_missing_credential_reference_is_durable_blocked_auth_not_fake_publish(self) -> None:
        result = _bridge("facebook", refs=set())
        self.assertFalse(result["blocked"])
        self.assertEqual("BLOCKED_MISSING_CREDENTIALS", result["dispatch_disposition"])
        self.assertTrue(result["adapter_handoff"]["blocked_missing_credentials"])
        self.assertIn("VALCEA_FB_PAGE_ACCESS_TOKEN", result["adapter_handoff"]["missing_reference_names"])
        self.assertEqual("BLOCKED_AUTH", result["publication_status_after_bridge"])
        self.assertFalse(result["adapter_handoff"]["dispatch_allowed"])
        record = next(iter(result["commit_bundle"]["ledger"]["records"].values()))
        self.assertIsNone(record["remote_publication_id"])
        self.assertEqual("MISSING_CREDENTIAL_REFERENCES", record["state_reason"])

    def test_missing_credentials_can_transition_same_handoff_to_direct_ready(self) -> None:
        first = _bridge("facebook", refs=set())
        handoff_id = first["adapter_handoff"]["handoff_id"]
        second = _bridge("facebook", outbox=first["commit_bundle"]["outbox"])
        self.assertFalse(second["blocked"])
        self.assertEqual("UPDATED_HANDOFF_GATE", second["decision"])
        self.assertEqual("DIRECT_READY", second["dispatch_disposition"])
        self.assertEqual(handoff_id, second["adapter_handoff"]["handoff_id"])
        self.assertEqual("READY", second["publication_status_after_bridge"])

    def test_registry_can_force_durable_outbox_only_without_changing_native_product(self) -> None:
        registry = _registry()
        facebook = next(row for row in registry["channels"] if row["channel_id"] == "facebook")
        facebook["direct_publication_enabled"] = False
        facebook["publication_mode"] = "durable_outbox_only"
        facebook["adapter"] = None
        facebook["credentials"] = None
        result = _bridge("facebook", registry=registry, refs=set())
        self.assertFalse(result["blocked"])
        self.assertEqual("OUTBOX_ONLY", result["dispatch_disposition"])
        self.assertTrue(result["adapter_handoff"]["durable_outbox_only"])
        self.assertFalse(result["adapter_handoff"]["dispatch_allowed"])
        self.assertEqual("OUTBOX_READY", result["publication_status_after_bridge"])
        item = next(iter(result["commit_bundle"]["outbox"]["items"].values()))
        self.assertEqual("facebook", item["platform"])
        self.assertEqual("single_photo", item["adapter_payload"]["native_product"]["native_format"])

    def test_upstream_approval_hold_never_creates_adapter_handoff(self) -> None:
        report = _runtime("tiktok", human_approved=False)
        self.assertEqual("AWAITING_APPROVAL", report["disposition"])
        result = _bridge("tiktok", report=report)
        self.assertFalse(result["blocked"])
        self.assertEqual("HOLD_UPSTREAM", result["dispatch_disposition"])
        self.assertIsNone(result["adapter_handoff"])
        self.assertIsNone(result["commit_bundle"])

    def test_repeated_bridge_is_idempotent_and_bundle_stable(self) -> None:
        report = _runtime("instagram")
        first = _bridge("instagram", report=report)
        second = _bridge("instagram", report=report, outbox=first["commit_bundle"]["outbox"])
        self.assertEqual("DEDUPE_EXISTING_HANDOFF", second["decision"])
        self.assertEqual(first["adapter_handoff"]["handoff_id"], second["adapter_handoff"]["handoff_id"])
        self.assertEqual(first["bundle_fingerprint_sha256"], second["bundle_fingerprint_sha256"])
        self.assertEqual(first["commit_bundle"], second["commit_bundle"])

    def test_outbox_identity_is_channel_local_and_fail_closed(self) -> None:
        wrong = adapter_dispatch_bridge.empty_handoff_outbox("valcea", "valcea-instagram", "instagram")
        result = _bridge("facebook", outbox=wrong)
        self.assertTrue(result["blocked"])
        self.assertIn("OUTBOX_CHANNEL_MISMATCH", result["hard_blocks"])
        self.assertIn("OUTBOX_PLATFORM_MISMATCH", result["hard_blocks"])

    def test_instance_mismatch_between_runtime_and_registry_is_blocked(self) -> None:
        registry = _registry()
        registry["instance_id"] = "shadow"
        result = _bridge("facebook", registry=registry)
        self.assertTrue(result["blocked"])
        self.assertIn("REGISTRY_INSTANCE_MISMATCH", result["hard_blocks"])

    def test_runtime_network_or_secret_access_guard_is_fail_closed(self) -> None:
        report = _runtime("facebook")
        report["guards"]["network_calls_performed"] = True
        report["guards"]["credential_values_read"] = True
        result = _bridge("facebook", report=report)
        self.assertTrue(result["blocked"])
        self.assertIn("UPSTREAM_NETWORK_CALLS_FORBIDDEN", result["hard_blocks"])
        self.assertIn("UPSTREAM_CREDENTIAL_VALUES_READ", result["hard_blocks"])

    def test_secret_like_present_reference_is_rejected_as_a_value(self) -> None:
        result = _bridge("facebook", refs={"EAA_THIS_LOOKS_LIKE_A_TOKEN"})
        self.assertTrue(result["blocked"])
        self.assertIn("PRESENT_REFERENCE_NOT_NAME", result["hard_blocks"])
        self.assertFalse(result["guards"]["credential_values_exposed"])

    def test_result_contains_reference_names_but_never_credential_values(self) -> None:
        result = _bridge("facebook")
        text = json.dumps(result, ensure_ascii=False, sort_keys=True)
        self.assertIn("VALCEA_FB_PAGE_ACCESS_TOKEN", text)
        self.assertNotIn("EAA_FAKE_SECRET_VALUE", text)
        self.assertFalse(result["adapter_handoff"]["credential_values_exposed"])
        item = next(iter(result["commit_bundle"]["outbox"]["items"].values()))
        self.assertFalse(item["credential_values_included"])

    def test_native_cross_post_guard_cannot_be_weakened_at_bridge(self) -> None:
        report = _runtime("facebook")
        report["artifacts"]["format"]["product"]["verbatim_cross_platform_reuse_allowed"] = True
        result = _bridge("facebook", report=report)
        self.assertTrue(result["blocked"])
        self.assertIn("VERBATIM_CROSS_PLATFORM_REUSE", result["hard_blocks"])

    def test_zero_paid_dependency_registry_policy_is_enforced(self) -> None:
        registry = _registry()
        registry["policy"]["paid_social_scheduler_required"] = True
        registry["policy"]["paid_llm_api_required"] = True
        result = _bridge("facebook", registry=registry)
        self.assertTrue(result["blocked"])
        self.assertIn("PAID_SCHEDULER_POLICY_VIOLATION", result["hard_blocks"])
        self.assertIn("PAID_LLM_POLICY_VIOLATION", result["hard_blocks"])

    def test_direct_ready_without_adapter_is_blocked(self) -> None:
        registry = _registry()
        facebook = next(row for row in registry["channels"] if row["channel_id"] == "facebook")
        facebook["adapter"] = None
        result = _bridge("facebook", registry=registry)
        self.assertTrue(result["blocked"])
        self.assertIn("DIRECT_READY_WITHOUT_ADAPTER", result["hard_blocks"])

    def test_durable_paths_are_required_for_any_handoff(self) -> None:
        registry = _registry()
        facebook = next(row for row in registry["channels"] if row["channel_id"] == "facebook")
        facebook["outbox"] = None
        facebook["state"] = None
        result = _bridge("facebook", registry=registry)
        self.assertTrue(result["blocked"])
        self.assertIn("MISSING_DURABLE_OUTBOX_PATH", result["hard_blocks"])

    def test_handoff_preserves_visual_and_link_provenance_from_runtime(self) -> None:
        report = _runtime("instagram")
        result = _bridge("instagram", report=report)
        item = next(iter(result["commit_bundle"]["outbox"]["items"].values()))
        payload = item["adapter_payload"]
        self.assertEqual(
            report["artifacts"]["visual"]["binding"]["binding_fingerprint_sha256"],
            payload["visual_binding"]["binding_fingerprint_sha256"],
        )
        self.assertEqual(
            report["artifacts"]["link_binding"]["binding_fingerprint_sha256"],
            payload["link_binding"]["binding_fingerprint_sha256"],
        )
        self.assertEqual(report["pipeline_fingerprint_sha256"], payload["pipeline_fingerprint_sha256"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
