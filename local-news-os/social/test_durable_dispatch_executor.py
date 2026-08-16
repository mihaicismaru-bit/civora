#!/usr/bin/env python3
"""Acceptance tests for the crash-safe LOCAL NEWS OS durable dispatch executor."""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import unittest

import durable_dispatch_executor as executor


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def bridge_result(platform: str = "facebook") -> dict:
    channel_id = f"valcea-{platform}"
    adapter = f"valcea-clar/social/{platform}_publish.py"
    publication_id = f"publication:{digest({'platform': platform})[:24]}"
    product_id = f"social-product:{channel_id}:story-1"
    payload = {
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "story_id": "story-1",
        "publication_id": publication_id,
        "dedupe_key": digest({"channel": channel_id, "story": "story-1"}),
        "product_id": product_id,
        "product_fingerprint_sha256": digest({"product": product_id}),
        "pipeline_fingerprint_sha256": digest({"pipeline": platform}),
        "native_product": {
            "product_id": product_id,
            "native_format": {
                "facebook": "single_photo",
                "instagram": "carousel",
                "tiktok": "short",
            }.get(platform, "native_post"),
            "cross_post_policy": "NATIVE_PRODUCT_ONLY",
            "verbatim_cross_platform_reuse_allowed": False,
        },
        "visual_binding": {"binding_fingerprint_sha256": digest({"visual": platform})},
        "link_binding": {"binding_fingerprint_sha256": digest({"link": platform})},
    }
    refs = {
        "facebook": ["VALCEA_FB_PAGE_ACCESS_TOKEN"],
        "instagram": ["VALCEA_IG_ACCOUNT_ID", "VALCEA_IG_ACCESS_TOKEN"],
        "tiktok": ["VALCEA_TIKTOK_ACCESS_TOKEN", "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED"],
    }.get(platform, ["VALCEA_TEST_ACCESS_TOKEN"])
    item = {
        "handoff_id": "handoff:" + digest({"platform": platform, "publication": publication_id})[:24],
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "publication_id": publication_id,
        "story_id": "story-1",
        "product_id": product_id,
        "dispatch_disposition": "DIRECT_READY",
        "adapter": adapter,
        "physical_outbox_path": "valcea-clar/social/facebook_outbox.json",
        "physical_state_path": f"valcea-clar/social/{platform}_state.json",
        "credential_reference_names": refs,
        "missing_reference_names": [],
        "credential_values_included": False,
        "network_dispatch_performed": False,
        "adapter_payload": payload,
        "adapter_payload_fingerprint_sha256": digest(payload),
    }
    item["handoff_fingerprint_sha256"] = digest(item)
    record = {
        "publication_id": publication_id,
        "dedupe_key": payload["dedupe_key"],
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "story_id": "story-1",
        "product_id": product_id,
        "product_fingerprint_sha256": payload["product_fingerprint_sha256"],
        "status": "READY",
        "state_reason": "ADAPTER_RUNTIME_GATE_CLEAR",
        "attempt_count": 0,
        "attempts": [],
        "remote_publication_id": None,
        "next_attempt_at": None,
        "guards": {
            "native_product_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "editorial_gates_weakened": False,
            "zero_paid_dependency": True,
        },
    }
    ledger = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "records": {publication_id: record},
        "guards": {
            "instance_isolation": True,
            "channel_state_independent": True,
            "zero_paid_dependency": True,
        },
    }
    outbox = {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "items": {item["handoff_id"]: item},
        "guards": {
            "channel_outbox_logically_independent": True,
            "credential_values_allowed": False,
            "network_dispatch_performed": False,
            "zero_paid_dependency": True,
        },
    }
    bundle = {
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "handoff_id": item["handoff_id"],
        "ledger": ledger,
        "outbox": outbox,
        "atomic_persist_required": True,
        "network_dispatch_performed": False,
    }
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": channel_id,
        "platform": platform,
        "blocked": False,
        "hard_blocks": [],
        "decision": "REGISTERED_HANDOFF",
        "dispatch_disposition": "DIRECT_READY",
        "adapter_handoff": {
            "handoff_id": item["handoff_id"],
            "adapter": adapter,
            "dispatch_allowed": True,
            "durable_outbox_only": False,
            "blocked_missing_credentials": False,
            "credential_reference_names": refs,
            "missing_reference_names": [],
            "credential_values_exposed": False,
        },
        "commit_bundle": bundle,
        "bundle_fingerprint_sha256": digest(bundle),
        "guards": {
            "verified_native_product_required": True,
            "channel_state_independent": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }


def initialized(platform: str = "facebook") -> dict:
    result = executor.initialize_dispatch_state(bridge_result(platform))
    assert result["blocked"] is False, result
    return result["state"]


def record(state: dict) -> dict:
    handoff = state["outbox"]["items"][state["handoff_id"]]
    return state["ledger"]["records"][handoff["publication_id"]]


def claimed(platform: str = "facebook", now: str = "2026-08-16T03:00:00Z") -> dict:
    result = executor.claim_dispatch(initialized(platform), now, "worker-a", lease_seconds=60)
    assert result["decision"] == "CLAIMED", result
    return result


class DurableDispatchExecutorAcceptance(unittest.TestCase):
    def test_three_native_channels_initialize_independently(self) -> None:
        states = {platform: initialized(platform) for platform in ("facebook", "instagram", "tiktok")}
        self.assertEqual(3, len({state["handoff_id"] for state in states.values()}))
        self.assertEqual(3, len({state["channel_id"] for state in states.values()}))
        self.assertEqual("single_photo", states["facebook"]["outbox"]["items"][states["facebook"]["handoff_id"]]["adapter_payload"]["native_product"]["native_format"])
        self.assertEqual("carousel", states["instagram"]["outbox"]["items"][states["instagram"]["handoff_id"]]["adapter_payload"]["native_product"]["native_format"])
        self.assertEqual("short", states["tiktok"]["outbox"]["items"][states["tiktok"]["handoff_id"]]["adapter_payload"]["native_product"]["native_format"])

    def test_only_direct_ready_bridge_can_initialize_executor(self) -> None:
        bridge = bridge_result()
        bridge["dispatch_disposition"] = "OUTBOX_ONLY"
        bridge["adapter_handoff"]["dispatch_allowed"] = False
        result = executor.initialize_dispatch_state(bridge)
        self.assertTrue(result["blocked"])
        self.assertIn("BRIDGE_NOT_DIRECT_READY", result["hard_blocks"])

    def test_tampered_bridge_bundle_fingerprint_fails_closed(self) -> None:
        bridge = bridge_result()
        bridge["commit_bundle"]["ledger"]["records"][next(iter(bridge["commit_bundle"]["ledger"]["records"]))]["story_id"] = "tampered"
        result = executor.initialize_dispatch_state(bridge)
        self.assertTrue(result["blocked"])
        self.assertIn("BRIDGE_BUNDLE_FINGERPRINT_INVALID", result["hard_blocks"])

    def test_tampered_immutable_handoff_fails_closed(self) -> None:
        state = initialized()
        state["outbox"]["items"][state["handoff_id"]]["adapter"] = "valcea-clar/social/other_publish.py"
        state = executor._seal_state(state)
        result = executor.claim_dispatch(state, "2026-08-16T03:00:00Z", "worker-a")
        self.assertTrue(result["blocked"])
        self.assertIn("HANDOFF_FINGERPRINT_INVALID", result["hard_blocks"])

    def test_claim_marks_publishing_before_any_adapter_and_preserves_exact_adapter(self) -> None:
        state = initialized("instagram")
        result = executor.claim_dispatch(state, "2026-08-16T03:00:00Z", "worker-a", lease_seconds=60)
        self.assertEqual("CLAIMED", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertTrue(result["compare_and_swap_required"])
        self.assertTrue(result["persist_before_adapter_required"])
        self.assertFalse(result["adapter_invoked"])
        self.assertEqual("valcea-clar/social/instagram_publish.py", result["adapter_invocation"]["adapter"])
        self.assertFalse(result["adapter_invocation"]["credential_values_included"])

    def test_second_worker_cannot_claim_active_lease(self) -> None:
        first = claimed()
        second = executor.claim_dispatch(first["state"], "2026-08-16T03:00:30Z", "worker-b", lease_seconds=60)
        self.assertEqual("LEASE_HELD", second["decision"])
        self.assertEqual("worker-a", second["active_worker_id"])
        self.assertFalse(second["adapter_invoked"])

    def test_expired_publishing_lease_requires_reconciliation_not_blind_resend(self) -> None:
        first = claimed()
        second = executor.claim_dispatch(first["state"], "2026-08-16T03:01:01Z", "worker-b", lease_seconds=60)
        self.assertEqual("RECONCILIATION_REQUIRED", second["decision"])
        self.assertEqual("PUBLISHING_LEASE_EXPIRED_REMOTE_STATE_UNKNOWN", second["reason"])
        self.assertFalse(second["adapter_invoked"])

    def test_execute_persists_claim_before_adapter_invocation(self) -> None:
        events: list[str] = []
        persisted: dict[str, dict] = {}

        def persist_claim(expected: str, state: dict) -> bool:
            events.append("persist_claim")
            self.assertEqual("PUBLISHING", record(state)["status"])
            persisted["claim"] = state
            return True

        def invoke(invocation: dict) -> dict:
            events.append("invoke_adapter")
            self.assertIn("claim", persisted)
            return {"success": True, "remote_publication_id": "ig_123"}

        def persist_result(expected: str, state: dict) -> bool:
            events.append("persist_result")
            self.assertEqual(persisted["claim"]["state_fingerprint_sha256"], expected)
            self.assertEqual("PUBLISHED", record(state)["status"])
            return True

        result = executor.execute_dispatch(
            initialized("instagram"),
            "2026-08-16T03:00:00Z",
            "worker-a",
            persist_claim=persist_claim,
            invoke_adapter=invoke,
            persist_result=persist_result,
            lease_seconds=60,
        )
        self.assertEqual(["persist_claim", "invoke_adapter", "persist_result"], events)
        self.assertEqual("PUBLISHED", result["decision"])
        self.assertTrue(result["claim_persisted_before_adapter"])
        self.assertTrue(result["result_persisted"])

    def test_claim_cas_conflict_prevents_adapter_call(self) -> None:
        calls = {"adapter": 0}

        def invoke(_: dict) -> dict:
            calls["adapter"] += 1
            return {"success": True, "remote_publication_id": "fb_1"}

        result = executor.execute_dispatch(
            initialized(),
            "2026-08-16T03:00:00Z",
            "worker-a",
            persist_claim=lambda expected, state: False,
            invoke_adapter=invoke,
        )
        self.assertEqual("CLAIM_PERSIST_CONFLICT", result["decision"])
        self.assertEqual(0, calls["adapter"])
        self.assertFalse(result["adapter_invoked"])

    def test_success_requires_remote_publication_id_and_becomes_published(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": True, "remote_publication_id": "fb_remote_123"},
        )
        self.assertEqual("PUBLISHED", result["decision"])
        self.assertEqual("PUBLISHED", result["publication_status"])
        self.assertEqual("fb_remote_123", result["record"]["remote_publication_id"])
        self.assertNotIn("dispatch_execution", result["record"])
        self.assertEqual(1, len(result["record"]["dispatch_history"]))

    def test_success_without_remote_id_stays_publishing_for_reconciliation(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": True},
        )
        self.assertEqual("RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertTrue(result["adapter_invoked"])

    def test_transient_failure_uses_existing_retry_policy(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "http_status": 503},
        )
        self.assertEqual("RETRY_SCHEDULED", result["decision"])
        self.assertEqual("RETRY_WAIT", result["publication_status"])
        self.assertEqual("2026-08-16T03:01:10Z", result["record"]["next_attempt_at"])

    def test_retry_after_rate_limit_is_honoured(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "http_status": 429, "retry_after_seconds": 600},
        )
        self.assertEqual("RETRY_SCHEDULED", result["decision"])
        self.assertEqual("2026-08-16T03:10:10Z", result["record"]["next_attempt_at"])

    def test_retry_wait_is_not_claimed_early_but_is_claimed_when_due(self) -> None:
        first = claimed()
        failed = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "http_status": 503},
        )
        early = executor.claim_dispatch(failed["state"], "2026-08-16T03:01:09Z", "worker-b", lease_seconds=60)
        self.assertEqual("RETRY_NOT_DUE", early["decision"])
        due = executor.claim_dispatch(failed["state"], "2026-08-16T03:01:10Z", "worker-b", lease_seconds=60)
        self.assertEqual("CLAIMED", due["decision"])
        self.assertEqual("RETRY_READY", record(due["state"])["dispatch_execution"]["pre_claim_status"])
        self.assertEqual("PUBLISHING", record(due["state"])["status"])

    def test_auth_failure_is_durably_blocked_without_retry(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "http_status": 401, "error_code": "TOKEN_EXPIRED"},
        )
        self.assertEqual("BLOCKED_AUTH", result["decision"])
        self.assertEqual("BLOCKED_AUTH", result["publication_status"])
        self.assertIsNone(result["record"]["next_attempt_at"])

    def test_permanent_failure_is_terminal(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "http_status": 400},
        )
        self.assertEqual("FAILED_TERMINAL", result["decision"])
        self.assertEqual("FAILED_TERMINAL", result["publication_status"])

    def test_wrong_claim_token_cannot_reconcile_result(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], "claim:wrong", "2026-08-16T03:00:10Z",
            {"success": True, "remote_publication_id": "fb_1"},
        )
        self.assertTrue(result["blocked"])
        self.assertIn("CLAIM_TOKEN_MISMATCH", result["hard_blocks"])

    def test_adapter_result_cannot_switch_adapter_or_publication(self) -> None:
        first = claimed("instagram")
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {
                "success": True,
                "remote_publication_id": "ig_1",
                "adapter": "valcea-clar/social/facebook_publish.py",
                "publication_id": "publication:other",
            },
        )
        self.assertTrue(result["blocked"])
        self.assertIn("ADAPTER_RESULT_ADAPTER_MISMATCH", result["hard_blocks"])
        self.assertIn("ADAPTER_RESULT_PUBLICATION_MISMATCH", result["hard_blocks"])

    def test_secret_or_raw_provider_fields_are_rejected(self) -> None:
        first = claimed()
        result = executor.reconcile_adapter_result(
            first["state"], first["claim_token"], "2026-08-16T03:00:10Z",
            {"success": False, "access_token": "EAA_NOT_ALLOWED"},
        )
        self.assertTrue(result["blocked"])
        self.assertIn("ADAPTER_RESULT_SECRET_OR_RAW_FIELD", result["hard_blocks"])

    def test_expired_claim_remote_found_is_published_without_adapter_reinvoke(self) -> None:
        first = claimed()
        result = executor.recover_stale_claim(
            first["state"], "2026-08-16T03:01:01Z", remote_publication_id="fb_found_remote"
        )
        self.assertEqual("PUBLISHED_AFTER_CRASH_RECONCILIATION", result["decision"])
        self.assertEqual("PUBLISHED", result["publication_status"])
        self.assertEqual("fb_found_remote", record(result["state"])["remote_publication_id"])
        self.assertFalse(result["adapter_invoked"])

    def test_expired_claim_confirmed_remote_absent_can_be_safely_requeued(self) -> None:
        first = claimed()
        recovered = executor.recover_stale_claim(
            first["state"], "2026-08-16T03:01:01Z", remote_absent_confirmed=True
        )
        self.assertEqual("REQUEUED_AFTER_REMOTE_ABSENT", recovered["decision"])
        self.assertEqual("RETRY_READY", recovered["publication_status"])
        again = executor.claim_dispatch(recovered["state"], "2026-08-16T03:01:02Z", "worker-b", lease_seconds=60)
        self.assertEqual("CLAIMED", again["decision"])

    def test_expired_claim_without_remote_evidence_remains_ambiguous(self) -> None:
        first = claimed()
        result = executor.recover_stale_claim(first["state"], "2026-08-16T03:01:01Z")
        self.assertEqual("RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])

    def test_result_persist_conflict_after_network_never_blindly_retries(self) -> None:
        calls = {"adapter": 0}

        def invoke(_: dict) -> dict:
            calls["adapter"] += 1
            return {"success": True, "remote_publication_id": "fb_remote_9"}

        result = executor.execute_dispatch(
            initialized(),
            "2026-08-16T03:00:00Z",
            "worker-a",
            persist_claim=lambda expected, state: True,
            invoke_adapter=invoke,
            persist_result=lambda expected, state: False,
            lease_seconds=60,
        )
        self.assertEqual("RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual(1, calls["adapter"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertTrue(result["adapter_invoked"])

    def test_zero_paid_dependency_guard_is_fail_closed(self) -> None:
        state = initialized()
        state["guards"]["zero_paid_dependency"] = False
        state = executor._seal_state(state)
        result = executor.claim_dispatch(state, "2026-08-16T03:00:00Z", "worker-a")
        self.assertTrue(result["blocked"])
        self.assertIn("ZERO_PAID_DEPENDENCY_VIOLATION", result["hard_blocks"])

    def test_state_fingerprint_detects_post_persist_tampering(self) -> None:
        state = initialized()
        record(state)["story_id"] = "changed-after-seal"
        result = executor.claim_dispatch(state, "2026-08-16T03:00:00Z", "worker-a")
        self.assertTrue(result["blocked"])
        self.assertIn("STATE_FINGERPRINT_INVALID", result["hard_blocks"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
