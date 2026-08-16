#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS asynchronous remote publication lifecycle."""
from __future__ import annotations

import copy
import unittest

import async_remote_dispatch as async_dispatch
import durable_dispatch_executor as executor
import test_durable_dispatch_executor as fixture

NOW = "2026-08-16T04:30:00Z"


def initialized() -> dict:
    result = executor.initialize_dispatch_state(fixture.bridge_result("tiktok"))
    assert result["blocked"] is False, result
    return result["state"]


def record(state: dict) -> dict:
    handoff = state["outbox"]["items"][state["handoff_id"]]
    return state["ledger"]["records"][handoff["publication_id"]]


def accepted(invocation: dict) -> dict:
    return {
        "accepted": True,
        "remote_submission_id": "v_pub_url~test-123",
        "adapter": invocation["adapter"],
        "publication_id": invocation["publication_id"],
        "native_format": "short",
        "credential_values_included": False,
        "network_submission_performed": True,
        "publication_confirmed": False,
    }


def begin() -> dict:
    result = async_dispatch.begin_async_dispatch(
        initialized(),
        NOW,
        "worker-tiktok",
        persist_claim=lambda expected, state: True,
        invoke_adapter=accepted,
        persist_pending=lambda pending: True,
        lease_seconds=120,
    )
    assert result["decision"] == "ASYNC_REMOTE_PENDING", result
    return result


class AsyncRemoteDispatchAcceptance(unittest.TestCase):
    def test_claim_is_persisted_before_network_and_submission_sidecar_is_durable(self) -> None:
        events: list[str] = []

        def persist_claim(expected: str, state: dict) -> bool:
            events.append("persist_claim")
            self.assertEqual("PUBLISHING", record(state)["status"])
            return True

        def invoke(invocation: dict) -> dict:
            events.append("invoke_adapter")
            self.assertEqual(["persist_claim"], events[:-1])
            return accepted(invocation)

        def persist_pending(pending: dict) -> bool:
            events.append("persist_pending")
            self.assertEqual("v_pub_url~test-123", pending["remote_submission_id"])
            return True

        result = async_dispatch.begin_async_dispatch(
            initialized(), NOW, "worker-tiktok",
            persist_claim=persist_claim,
            invoke_adapter=invoke,
            persist_pending=persist_pending,
            lease_seconds=120,
        )
        self.assertEqual(["persist_claim", "invoke_adapter", "persist_pending"], events)
        self.assertEqual("ASYNC_REMOTE_PENDING", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertFalse(result["publication_confirmed"])
        self.assertFalse(result["blind_retry_allowed"])
        self.assertFalse(result["pending"]["credential_values_included"])
        self.assertNotIn("access_token", result["pending"])

    def test_claim_persist_conflict_prevents_network_submission(self) -> None:
        calls = {"adapter": 0}

        def invoke(invocation: dict) -> dict:
            calls["adapter"] += 1
            return accepted(invocation)

        result = async_dispatch.begin_async_dispatch(
            initialized(), NOW, "worker-tiktok",
            persist_claim=lambda expected, state: False,
            invoke_adapter=invoke,
            persist_pending=lambda pending: True,
        )
        self.assertEqual("CLAIM_PERSIST_CONFLICT", result["decision"])
        self.assertEqual(0, calls["adapter"])
        self.assertFalse(result["adapter_invoked"])

    def test_network_exception_is_ambiguous_and_never_auto_retried(self) -> None:
        result = async_dispatch.begin_async_dispatch(
            initialized(), NOW, "worker-tiktok",
            persist_claim=lambda expected, state: True,
            invoke_adapter=lambda invocation: (_ for _ in ()).throw(RuntimeError("transport")),
            persist_pending=lambda pending: True,
        )
        self.assertEqual("ASYNC_SUBMISSION_AMBIGUOUS_RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertTrue(result["adapter_invoked"])
        self.assertFalse(result["blind_retry_allowed"])

    def test_pending_persist_failure_does_not_blindly_resubmit(self) -> None:
        result = async_dispatch.begin_async_dispatch(
            initialized(), NOW, "worker-tiktok",
            persist_claim=lambda expected, state: True,
            invoke_adapter=accepted,
            persist_pending=lambda pending: False,
        )
        self.assertEqual("PENDING_PERSIST_CONFLICT_RECONCILIATION_REQUIRED", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertEqual("v_pub_url~test-123", result["candidate_pending"]["remote_submission_id"])
        self.assertFalse(result["blind_retry_allowed"])

    def test_second_worker_cannot_submit_while_async_claim_lease_is_active(self) -> None:
        first = begin()
        calls = {"adapter": 0}

        def invoke(invocation: dict) -> dict:
            calls["adapter"] += 1
            return accepted(invocation)

        second = async_dispatch.begin_async_dispatch(
            first["state"], "2026-08-16T04:30:30Z", "worker-second",
            persist_claim=lambda expected, state: True,
            invoke_adapter=invoke,
            persist_pending=lambda pending: True,
            lease_seconds=120,
        )
        self.assertEqual("LEASE_HELD", second["decision"])
        self.assertEqual(0, calls["adapter"])

    def test_remote_pending_status_never_resubmits_and_keeps_generic_publishing(self) -> None:
        first = begin()
        polls = {"count": 0}

        def status(pending: dict) -> dict:
            polls["count"] += 1
            return {
                "state": "PENDING",
                "remote_submission_id": pending["remote_submission_id"],
                "remote_publication_id": None,
                "provider_status": "PROCESSING_DOWNLOAD",
                "publication_confirmed": False,
            }

        result = async_dispatch.reconcile_async_dispatch(
            first["state"], first["pending"], "2026-08-16T04:31:00Z",
            fetch_remote_status=status,
            persist_pending=lambda expected, pending: True,
        )
        self.assertEqual(1, polls["count"])
        self.assertEqual("REMOTE_STILL_PENDING", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertEqual("PROCESSING_DOWNLOAD", result["pending"]["provider_status"])
        self.assertFalse(result["adapter_invoked"])
        self.assertFalse(result["blind_retry_allowed"])

    def test_publish_complete_with_remote_post_id_finalizes_generic_publication(self) -> None:
        first = begin()
        persisted: list[dict] = []

        def status(pending: dict) -> dict:
            return {
                "state": "PUBLISHED",
                "remote_submission_id": pending["remote_submission_id"],
                "remote_publication_id": "7499900011223344556",
                "provider_status": "PUBLISH_COMPLETE",
                "publication_confirmed": True,
            }

        result = async_dispatch.reconcile_async_dispatch(
            first["state"], first["pending"], "2026-08-16T04:32:00Z",
            fetch_remote_status=status,
            persist_result=lambda expected, state: persisted.append(copy.deepcopy(state)) is None,
        )
        # append returns None; expression above intentionally becomes True via `is None`.
        self.assertEqual("PUBLISHED", result["decision"])
        self.assertEqual("PUBLISHED", result["publication_status"])
        self.assertEqual("7499900011223344556", result["record"]["remote_publication_id"])
        self.assertTrue(result["publication_confirmed"])
        self.assertTrue(result["async_reconciliation_completed"])
        self.assertEqual(1, len(persisted))

    def test_publish_complete_without_remote_post_id_stays_pending_for_proof(self) -> None:
        first = begin()
        result = async_dispatch.reconcile_async_dispatch(
            first["state"], first["pending"], "2026-08-16T04:32:00Z",
            fetch_remote_status=lambda pending: {
                "state": "PENDING_PUBLICATION_PROOF",
                "remote_submission_id": pending["remote_submission_id"],
                "remote_publication_id": None,
                "provider_status": "PUBLISH_COMPLETE",
                "publication_confirmed": False,
            },
        )
        self.assertEqual("REMOTE_STILL_PENDING", result["decision"])
        self.assertEqual("PUBLISHING", record(result["state"])["status"])
        self.assertFalse(result["publication_confirmed"])

    def test_explicit_remote_failure_is_terminal_not_an_invented_success(self) -> None:
        first = begin()
        result = async_dispatch.reconcile_async_dispatch(
            first["state"], first["pending"], "2026-08-16T04:32:00Z",
            fetch_remote_status=lambda pending: {
                "state": "FAILED",
                "remote_submission_id": pending["remote_submission_id"],
                "remote_publication_id": None,
                "provider_status": "FAILED",
                "error_code": "video_pull_failed",
                "publication_confirmed": False,
            },
        )
        self.assertEqual("FAILED_TERMINAL", result["decision"])
        self.assertEqual("FAILED_TERMINAL", result["publication_status"])
        self.assertFalse(result["publication_confirmed"])
        self.assertFalse(result["blind_retry_allowed"])

    def test_tampered_pending_sidecar_fails_closed_before_status_poll(self) -> None:
        first = begin()
        pending = copy.deepcopy(first["pending"])
        pending["remote_submission_id"] = "tampered"
        calls = {"status": 0}

        def status(value: dict) -> dict:
            calls["status"] += 1
            return {}

        result = async_dispatch.reconcile_async_dispatch(
            first["state"], pending, "2026-08-16T04:32:00Z",
            fetch_remote_status=status,
        )
        self.assertTrue(result["blocked"])
        self.assertIn("ASYNC_PENDING_FINGERPRINT_INVALID", result["hard_blocks"])
        self.assertEqual(0, calls["status"])

    def test_secret_bearing_submission_result_is_rejected_after_network_boundary(self) -> None:
        def bad(invocation: dict) -> dict:
            result = accepted(invocation)
            result["access_token"] = "secret"
            return result

        result = async_dispatch.begin_async_dispatch(
            initialized(), NOW, "worker-tiktok",
            persist_claim=lambda expected, state: True,
            invoke_adapter=bad,
            persist_pending=lambda pending: True,
        )
        self.assertTrue(result["blocked"])
        self.assertIn("ASYNC_SUBMISSION_SECRET_OR_RAW_FIELD", result["hard_blocks"])
        self.assertTrue(result["adapter_invoked"])
        self.assertFalse(result["blind_retry_allowed"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
