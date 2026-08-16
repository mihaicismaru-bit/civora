#!/usr/bin/env python3
"""Acceptance tests for crash-safe recurring-series dispatch execution."""
from __future__ import annotations

import copy

import series_durable_dispatch_executor as series_executor
import test_series_adapter_dispatch_handoff as handoff_fixture

NOW = "2026-08-16T12:00:00Z"


def initialized(platform: str = "facebook") -> tuple[dict, dict]:
    handoff = handoff_fixture.handoff(platform)
    assert handoff["blocked"] is False
    assert handoff["dispatch_disposition"] == "DIRECT_READY"
    result = series_executor.initialize_series_dispatch_state(copy.deepcopy(handoff))
    assert result["blocked"] is False, result
    return result["state"], handoff


def series_record(state: dict) -> dict:
    return state["series_publication_state"]["records"][state["publication_id"]]


def series_item(state: dict) -> dict:
    return next(item for item in state["series_publication_outbox"]["items"] if item["publication_id"] == state["publication_id"])


def success_result(invocation: dict, remote_id: str = "remote:series:123") -> dict:
    return {
        "success": True,
        "remote_publication_id": remote_id,
        "adapter": invocation["adapter"],
        "handoff_id": invocation["handoff_id"],
        "publication_id": invocation["publication_id"],
        "http_status": 200,
    }


def test_direct_ready_series_initializes_generic_executor_without_rewriting_native_product() -> None:
    state, handoff = initialized("facebook")
    item = next(iter(handoff["commit_bundle"]["dispatch_handoff_outbox"]["items"].values()))
    assert state["publication_kind"] == "recurring_series"
    assert series_record(state)["status"] == "READY"
    assert series_item(state)["product"] == item["adapter_payload"]["native_product"]
    assert item["adapter_payload"]["source_story_ids"] == ["story-a", "story-b"]
    assert state["guards"]["native_multi_story_product_preserved"] is True
    assert state["guards"]["zero_paid_dependency"] is True


def test_outbox_only_series_cannot_initialize_dispatch_executor() -> None:
    handoff = handoff_fixture.handoff("telegram")
    assert handoff["dispatch_disposition"] == "HOLD_UPSTREAM"
    result = series_executor.initialize_series_dispatch_state(handoff)
    assert result["blocked"] is True
    assert "HANDOFF_NOT_DIRECT_READY" in result["hard_blocks"]


def test_claim_persists_publishing_state_before_adapter_and_preserves_story_identity() -> None:
    state, _ = initialized()
    result = series_executor.claim_series_dispatch(state, NOW, "worker-a", lease_seconds=60)
    assert result["blocked"] is False
    assert result["decision"] == "CLAIMED"
    assert result["persist_before_adapter_required"] is True
    assert result["adapter_invoked"] is False
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert series_item(result["state"])["status"] == "PUBLISHING"
    assert result["adapter_invocation"]["source_story_ids"] == ["story-a", "story-b"]
    assert result["adapter_invocation"]["publication_kind"] == "recurring_series"


def test_concurrent_second_worker_observes_active_lease_and_cannot_dispatch() -> None:
    state, _ = initialized()
    first = series_executor.claim_series_dispatch(state, NOW, "worker-a", lease_seconds=60)
    second = series_executor.claim_series_dispatch(first["state"], "2026-08-16T12:00:30Z", "worker-b", lease_seconds=60)
    assert second["blocked"] is False
    assert second["decision"] == "LEASE_HELD"
    assert second["adapter_invoked"] is False


def test_confirmed_remote_id_marks_series_published_atomically() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    done = series_executor.reconcile_series_adapter_result(
        claim["state"], claim["claim_token"], NOW, success_result(claim["adapter_invocation"])
    )
    assert done["blocked"] is False
    assert done["decision"] == "PUBLISHED"
    assert done["publication_status"] == "PUBLISHED"
    assert series_record(done["state"])["remote_publication_id"] == "remote:series:123"
    assert series_item(done["state"])["dispatch"]["remote_publication_id"] == "remote:series:123"
    assert series_item(done["state"])["product"] == series_item(state)["product"]


def test_success_without_remote_proof_requires_reconciliation_not_false_publish() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    ambiguous = success_result(claim["adapter_invocation"])
    ambiguous.pop("remote_publication_id")
    result = series_executor.reconcile_series_adapter_result(claim["state"], claim["claim_token"], NOW, ambiguous)
    assert result["blocked"] is False
    assert result["decision"] == "RECONCILIATION_REQUIRED"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert series_record(result["state"])["remote_publication_id"] is None


def test_transient_failure_schedules_retry_and_never_rewrites_product() -> None:
    state, _ = initialized()
    original_product = copy.deepcopy(series_item(state)["product"])
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    result = series_executor.reconcile_series_adapter_result(
        claim["state"], claim["claim_token"], NOW,
        {"success": False, "http_status": 503, "error_class": "server_error", "error_code": "UPSTREAM_503"},
        base_delay_seconds=60,
    )
    assert result["decision"] == "RETRY_SCHEDULED"
    assert result["publication_status"] == "RETRY_WAIT"
    assert series_record(result["state"])["next_attempt_at"] == "2026-08-16T12:01:00Z"
    assert series_item(result["state"])["product"] == original_product
    early = series_executor.claim_series_dispatch(result["state"], "2026-08-16T12:00:30Z", "worker-b")
    assert early["decision"] == "RETRY_NOT_DUE"
    due = series_executor.claim_series_dispatch(result["state"], "2026-08-16T12:01:00Z", "worker-b")
    assert due["decision"] == "CLAIMED"


def test_auth_failure_blocks_without_automatic_retry() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    result = series_executor.reconcile_series_adapter_result(
        claim["state"], claim["claim_token"], NOW,
        {"success": False, "http_status": 401, "error_class": "auth", "error_code": "TOKEN_EXPIRED"},
    )
    assert result["decision"] == "BLOCKED_AUTH"
    assert result["publication_status"] == "BLOCKED_AUTH"
    assert series_record(result["state"])["next_attempt_at"] is None


def test_permanent_failure_is_terminal() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    result = series_executor.reconcile_series_adapter_result(
        claim["state"], claim["claim_token"], NOW,
        {"success": False, "http_status": 400, "error_class": "permanent", "error_code": "INVALID_NATIVE_PAYLOAD"},
    )
    assert result["decision"] == "FAILED_TERMINAL"
    assert result["publication_status"] == "FAILED_TERMINAL"


def test_expired_claim_never_blind_retries_without_remote_evidence() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a", lease_seconds=30)
    result = series_executor.recover_stale_series_claim(claim["state"], "2026-08-16T12:01:00Z")
    assert result["blocked"] is False
    assert result["decision"] == "RECONCILIATION_REQUIRED"
    assert series_record(result["state"])["status"] == "PUBLISHING"


def test_crash_reconciliation_with_remote_proof_marks_published_without_resend() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a", lease_seconds=30)
    result = series_executor.recover_stale_series_claim(
        claim["state"], "2026-08-16T12:01:00Z", remote_publication_id="remote:found-after-crash"
    )
    assert result["decision"] == "PUBLISHED_AFTER_CRASH_RECONCILIATION"
    assert result["publication_status"] == "PUBLISHED"
    assert series_record(result["state"])["remote_publication_id"] == "remote:found-after-crash"
    again = series_executor.claim_series_dispatch(result["state"], "2026-08-16T12:02:00Z", "worker-b")
    assert again["decision"] == "ALREADY_PUBLISHED"


def test_crash_reconciliation_confirmed_absent_requeues_safely() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a", lease_seconds=30)
    result = series_executor.recover_stale_series_claim(
        claim["state"], "2026-08-16T12:01:00Z", remote_absent_confirmed=True
    )
    assert result["decision"] == "REQUEUED_AFTER_REMOTE_ABSENT"
    assert result["publication_status"] == "RETRY_READY"
    retry_claim = series_executor.claim_series_dispatch(result["state"], "2026-08-16T12:01:01Z", "worker-b")
    assert retry_claim["decision"] == "CLAIMED"


def test_execute_never_invokes_adapter_when_claim_persistence_conflicts() -> None:
    state, _ = initialized()
    calls: list[str] = []

    def persist_claim(expected: str, candidate: dict) -> bool:
        calls.append("claim")
        assert expected == state["state_fingerprint_sha256"]
        assert series_record(candidate)["status"] == "PUBLISHING"
        return False

    def invoke_adapter(invocation: dict) -> dict:
        calls.append("adapter")
        return success_result(invocation)

    result = series_executor.execute_series_dispatch(
        state, NOW, "worker-a", persist_claim=persist_claim, invoke_adapter=invoke_adapter
    )
    assert result["decision"] == "CLAIM_PERSIST_CONFLICT"
    assert result["adapter_invoked"] is False
    assert calls == ["claim"]


def test_execute_orders_claim_adapter_and_result_persistence() -> None:
    state, _ = initialized("instagram")
    calls: list[str] = []
    stored_claim: dict = {}

    def persist_claim(expected: str, candidate: dict) -> bool:
        calls.append("claim")
        stored_claim.update(copy.deepcopy(candidate))
        return expected == state["state_fingerprint_sha256"]

    def invoke_adapter(invocation: dict) -> dict:
        calls.append("adapter")
        assert stored_claim and series_record(stored_claim)["status"] == "PUBLISHING"
        assert invocation["source_story_ids"] == ["story-a", "story-b"]
        return success_result(invocation, "ig:carousel:42")

    def persist_result(expected: str, candidate: dict) -> bool:
        calls.append("result")
        assert expected == stored_claim["state_fingerprint_sha256"]
        assert series_record(candidate)["status"] == "PUBLISHED"
        return True

    result = series_executor.execute_series_dispatch(
        state, NOW, "worker-a", persist_claim=persist_claim, invoke_adapter=invoke_adapter, persist_result=persist_result
    )
    assert result["decision"] == "PUBLISHED"
    assert result["claim_persisted_before_adapter"] is True
    assert result["result_persisted"] is True
    assert calls == ["claim", "adapter", "result"]


def test_result_persistence_conflict_leaves_durable_state_publishing_for_reconciliation() -> None:
    state, _ = initialized()
    result = series_executor.execute_series_dispatch(
        state, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=lambda invocation: success_result(invocation),
        persist_result=lambda expected, candidate: False,
    )
    assert result["decision"] == "RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED"
    assert result["adapter_invoked"] is True
    assert series_record(result["state"])["status"] == "PUBLISHING"


def test_native_product_tamper_is_fail_closed_even_with_resealed_outer_state() -> None:
    state, _ = initialized()
    tampered = copy.deepcopy(state)
    series_item(tampered)["product"]["items"][0]["hook"]["text"] = "TAMPERED COPY"
    tampered = series_executor._seal(tampered)
    result = series_executor.claim_series_dispatch(tampered, NOW, "worker-a")
    assert result["blocked"] is True
    assert any(reason in result["hard_blocks"] for reason in ("NATIVE_SERIES_PRODUCT_MUTATED_AFTER_HANDOFF", "SERIES_OUTBOX_ITEM_FINGERPRINT_INVALID"))


def test_instance_isolation_and_zero_paid_guards_are_fail_closed() -> None:
    state, _ = initialized()
    tampered = copy.deepcopy(state)
    tampered["instance_id"] = "cluj"
    tampered["guards"]["zero_paid_dependency"] = False
    tampered = series_executor._seal(tampered)
    result = series_executor.claim_series_dispatch(tampered, NOW, "worker-a")
    assert result["blocked"] is True
    assert "EXECUTOR_INSTANCE_MISMATCH" in result["hard_blocks"]
    assert "STATE_GUARD_INVALID:zero_paid_dependency" in result["hard_blocks"]


def test_secret_bearing_adapter_result_is_rejected_without_leaking_into_state() -> None:
    state, _ = initialized()
    claim = series_executor.claim_series_dispatch(state, NOW, "worker-a")
    result = series_executor.reconcile_series_adapter_result(
        claim["state"], claim["claim_token"], NOW,
        {"success": False, "access_token": "DO-NOT-PERSIST", "error_class": "transient"},
    )
    assert result["blocked"] is True
    assert "DO-NOT-PERSIST" not in str(result["state"])
    assert series_record(result["state"])["status"] == "PUBLISHING"


def main() -> int:
    tests = [
        test_direct_ready_series_initializes_generic_executor_without_rewriting_native_product,
        test_outbox_only_series_cannot_initialize_dispatch_executor,
        test_claim_persists_publishing_state_before_adapter_and_preserves_story_identity,
        test_concurrent_second_worker_observes_active_lease_and_cannot_dispatch,
        test_confirmed_remote_id_marks_series_published_atomically,
        test_success_without_remote_proof_requires_reconciliation_not_false_publish,
        test_transient_failure_schedules_retry_and_never_rewrites_product,
        test_auth_failure_blocks_without_automatic_retry,
        test_permanent_failure_is_terminal,
        test_expired_claim_never_blind_retries_without_remote_evidence,
        test_crash_reconciliation_with_remote_proof_marks_published_without_resend,
        test_crash_reconciliation_confirmed_absent_requeues_safely,
        test_execute_never_invokes_adapter_when_claim_persistence_conflicts,
        test_execute_orders_claim_adapter_and_result_persistence,
        test_result_persistence_conflict_leaves_durable_state_publishing_for_reconciliation,
        test_native_product_tamper_is_fail_closed_even_with_resealed_outer_state,
        test_instance_isolation_and_zero_paid_guards_are_fail_closed,
        test_secret_bearing_adapter_result_is_rejected_without_leaking_into_state,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Series Durable Dispatch Executor acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
