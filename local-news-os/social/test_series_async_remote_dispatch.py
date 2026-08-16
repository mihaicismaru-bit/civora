#!/usr/bin/env python3
"""Acceptance tests for recurring-series asynchronous remote publication."""
from __future__ import annotations

import copy

import content_atomizer
import native_series_compositor
import series_adapter_dispatch_handoff
import series_async_remote_dispatch as series_async
import series_durable_dispatch_executor as series_executor
import series_publication_state_bridge
import series_visual_router
import test_series_adapter_dispatch_handoff as handoff_fixture
import test_series_durable_dispatch_executor as durable_fixture
import test_series_publication_state_bridge as source_fixture

NOW = "2026-08-16T15:00:00Z"
TIKTOK_REFS = {"VALCEA_TIKTOK_ACCESS_TOKEN", "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED"}


def tiktok_channel() -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": "valcea-tiktok",
        "instance_id": "valcea",
        "platform": "tiktok",
        "status": "active",
        "native_formats": ["short"],
        "media_policy": {
            "real_media_only": True,
            "provenance_required": True,
            "reuse_rights_required": True,
            "synthetic_real_person_forbidden": True,
        },
        "link_policy": {"mode": "optional", "canonical_hosts": ["valceaclar.ro"]},
        "cadence": {
            "timezone": "Europe/Bucharest",
            "max_posts_per_day": 8,
            "min_spacing_minutes": 15,
            "quiet_hours": {"start": "23:00", "end": "06:00", "breaking_override": False},
        },
        "fatigue": {"same_story_cooldown_hours": 4, "max_related_posts_24h": 4},
        "series": [{"series_id": "daily-brief", "promise": "Un short local verificat, recompus nativ."}],
        "approval_gates": {
            "low_risk_auto": True,
            "reputational_human": True,
            "corrections_priority": True,
        },
        "metrics": {"observed_only": True},
        "zero_paid_dependency": True,
    }


def tiktok_staged(story: dict) -> dict:
    source_hash = content_atomizer.atomize_story(story)["source_fingerprint_sha256"]
    return {
        "series_execution_id": "series-execution:tiktok-daily-async",
        "occurrence_id": "occurrence:tiktok-daily",
        "instance_id": "valcea",
        "channel_id": "valcea-tiktok",
        "series_id": "daily-brief",
        "series_slot_key": "daily-brief:2026-08-16:0:18:00",
        "status": "SERIES_COMPOSITION_PENDING",
        "publication_mode": "channel_native_series_composition_pending",
        "selected_candidate_ids": ["candidate-a"],
        "selected_story_ids": [story["story_id"]],
        "selected_content_hashes": [source_hash],
        "topic_ids": ["infrastructure"],
        "native_format_candidates": ["short"],
        "replay_policy": "new_story_only",
        "composition_fingerprint_sha256": "d" * 64,
        "native_composition_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "source_story_text_materialized": False,
        "predictive_analytics_used": False,
        "credential_values_read": False,
        "network_dispatch_performed": False,
        "editorial_gates_weakened": False,
        "zero_paid_dependency": True,
    }


def video(story_id: str) -> dict:
    return {
        "asset_id": "video-" + story_id,
        "instance_id": "valcea",
        "kind": "video",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "sha256": "c" * 64,
        "source_type": "official_press",
        "source_url": "https://example.org/source-video",
        "direct_source_url": "https://valceaclar.ro/media/" + story_id + ".mp4",
        "credit": "Instituție / comunicat",
        "rights_basis": "press_use",
        "license_url": None,
        "rights_note": "Utilizare editorială permisă.",
        "alt_text": "Video real relevant pentru subiect.",
        "story_ids": [story_id],
    }


def initialized_tiktok() -> tuple[dict, dict]:
    story = copy.deepcopy(source_fixture.stories()[0])
    channel = tiktok_channel()
    composition = native_series_compositor.compose_staged_series(
        channel,
        tiktok_staged(story),
        {"instance_id": "valcea", "stories": [story]},
    )
    assert composition["blocked"] is False, composition
    visual = series_visual_router.bind_series_visuals(
        composition,
        channel,
        {"schema_version": "1.0", "instance_id": "valcea", "assets": [video(story["story_id"])]},
    )
    assert visual["blocked"] is False, visual
    published = series_publication_state_bridge.bridge_series_publication(
        composition,
        channel,
        source_fixture.history(channel),
        now=NOW,
        visual_result=visual,
    )
    assert published["blocked"] is False, published
    assert published["record"]["status"] == "READY", published
    handoff = series_adapter_dispatch_handoff.bridge_ready_series_handoff(
        published,
        handoff_fixture.registry(),
        handoff_fixture.capabilities(),
        TIKTOK_REFS,
    )
    assert handoff["blocked"] is False, handoff
    assert handoff["dispatch_disposition"] == "DIRECT_READY", handoff
    initialized = series_executor.initialize_series_dispatch_state(handoff)
    assert initialized["blocked"] is False, initialized
    return initialized["state"], handoff_fixture.capabilities()


def series_record(state: dict) -> dict:
    return state["series_publication_state"]["records"][state["publication_id"]]


def series_item(state: dict) -> dict:
    return next(item for item in state["series_publication_outbox"]["items"] if item["publication_id"] == state["publication_id"])


def accepted(invocation: dict, submission_id: str = "v_pub_url~series-123") -> dict:
    assert invocation["publication_kind"] == "recurring_series"
    assert invocation["source_story_ids"]
    return {
        "accepted": True,
        "remote_submission_id": submission_id,
        "adapter": invocation["adapter"],
        "publication_id": invocation["publication_id"],
        "native_format": "short",
        "credential_values_included": False,
        "network_submission_performed": True,
        "publication_confirmed": False,
    }


def begin_tiktok() -> dict:
    state, capabilities = initialized_tiktok()
    result = series_async.begin_series_async_dispatch(
        state,
        capabilities,
        NOW,
        "worker-tiktok-series",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=accepted,
        persist_pending=lambda pending: True,
        lease_seconds=120,
    )
    assert result["decision"] == "SERIES_ASYNC_REMOTE_PENDING", result
    return result


def test_tiktok_series_claim_is_durable_before_submit_and_submission_id_is_not_publication_proof() -> None:
    state, capabilities = initialized_tiktok()
    events: list[str] = []
    stored_claim: dict = {}

    def persist_claim(expected: str, candidate: dict) -> bool:
        events.append("claim")
        stored_claim.update(copy.deepcopy(candidate))
        assert expected == state["state_fingerprint_sha256"]
        assert series_record(candidate)["status"] == "PUBLISHING"
        return True

    def invoke(invocation: dict) -> dict:
        events.append("adapter")
        assert events == ["claim", "adapter"]
        assert stored_claim
        assert invocation["source_story_ids"] == ["story-a"]
        return accepted(invocation)

    def persist_pending(pending: dict) -> bool:
        events.append("pending")
        assert pending["remote_submission_id"] == "v_pub_url~series-123"
        assert pending["publication_confirmed"] is False
        return True

    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=persist_claim, invoke_adapter=invoke, persist_pending=persist_pending,
        lease_seconds=120,
    )
    assert events == ["claim", "adapter", "pending"]
    assert result["decision"] == "SERIES_ASYNC_REMOTE_PENDING"
    assert result["publication_status"] == "PUBLISHING"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert result["publication_confirmed"] is False
    assert result["blind_retry_allowed"] is False
    assert result["pending"]["source_story_ids"] == ["story-a"]
    assert result["pending"]["guards"]["zero_paid_dependency"] is True


def test_non_async_adapter_capability_is_blocked_before_network() -> None:
    state, _ = durable_fixture.initialized("facebook")
    capabilities = handoff_fixture.capabilities()
    calls = {"adapter": 0}

    def invoke(invocation: dict) -> dict:
        calls["adapter"] += 1
        return accepted(invocation)

    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=invoke,
        persist_pending=lambda pending: True,
    )
    assert result["blocked"] is True
    assert "ASYNC_CAPABILITY_COMPLETION_MODEL_MISMATCH" in result["hard_blocks"]
    assert calls["adapter"] == 0


def test_async_capability_requires_remote_reconciliation_support() -> None:
    state, capabilities = initialized_tiktok()
    bad = copy.deepcopy(capabilities)
    row = next(item for item in bad["adapters"] if item["platform"] == "tiktok")
    row["remote_reconciliation_supported"] = False
    calls = {"adapter": 0}
    result = series_async.begin_series_async_dispatch(
        state, bad, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=lambda invocation: calls.__setitem__("adapter", calls["adapter"] + 1) or accepted(invocation),
        persist_pending=lambda pending: True,
    )
    assert result["blocked"] is True
    assert "ASYNC_CAPABILITY_REMOTE_RECONCILIATION_REQUIRED" in result["hard_blocks"]
    assert calls["adapter"] == 0


def test_claim_persistence_conflict_prevents_async_series_submit() -> None:
    state, capabilities = initialized_tiktok()
    calls = {"adapter": 0}
    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=lambda expected, candidate: False,
        invoke_adapter=lambda invocation: calls.__setitem__("adapter", calls["adapter"] + 1) or accepted(invocation),
        persist_pending=lambda pending: True,
    )
    assert result["decision"] == "CLAIM_PERSIST_CONFLICT"
    assert result["adapter_invoked"] is False
    assert calls["adapter"] == 0
    assert series_record(result["state"])["status"] == "READY"


def test_network_exception_is_ambiguous_and_never_blindly_retried() -> None:
    state, capabilities = initialized_tiktok()
    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=lambda invocation: (_ for _ in ()).throw(RuntimeError("transport")),
        persist_pending=lambda pending: True,
    )
    assert result["decision"] == "ASYNC_SUBMISSION_AMBIGUOUS_RECONCILIATION_REQUIRED"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert result["adapter_invoked"] is True
    assert result["blind_retry_allowed"] is False


def test_pending_persistence_conflict_keeps_series_publishing_and_exposes_only_safe_candidate() -> None:
    state, capabilities = initialized_tiktok()
    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=accepted,
        persist_pending=lambda pending: False,
    )
    assert result["decision"] == "PENDING_PERSIST_CONFLICT_RECONCILIATION_REQUIRED"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert result["candidate_pending"]["remote_submission_id"] == "v_pub_url~series-123"
    assert "access_token" not in result["candidate_pending"]
    assert result["blind_retry_allowed"] is False


def test_second_worker_cannot_submit_while_async_series_lease_is_active() -> None:
    first = begin_tiktok()
    _, capabilities = initialized_tiktok()
    calls = {"adapter": 0}
    second = series_async.begin_series_async_dispatch(
        first["state"], capabilities, "2026-08-16T15:00:30Z", "worker-b",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=lambda invocation: calls.__setitem__("adapter", calls["adapter"] + 1) or accepted(invocation),
        persist_pending=lambda pending: True,
        lease_seconds=120,
    )
    assert second["decision"] == "LEASE_HELD"
    assert second["adapter_invoked"] is False
    assert calls["adapter"] == 0


def test_remote_pending_updates_only_sidecar_and_preserves_native_series_product() -> None:
    first = begin_tiktok()
    original_product = copy.deepcopy(series_item(first["state"])["product"])
    result = series_async.reconcile_series_async_dispatch(
        first["state"], first["pending"], "2026-08-16T15:01:00Z",
        fetch_remote_status=lambda pending: {
            "state": "PENDING",
            "remote_submission_id": pending["remote_submission_id"],
            "remote_publication_id": None,
            "provider_status": "PROCESSING_DOWNLOAD",
            "publication_confirmed": False,
        },
        persist_pending=lambda expected, pending: True,
    )
    assert result["decision"] == "REMOTE_STILL_PENDING"
    assert result["publication_status"] == "PUBLISHING"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert result["pending"]["provider_status"] == "PROCESSING_DOWNLOAD"
    assert result["pending"]["source_story_ids"] == ["story-a"]
    assert series_item(result["state"])["product"] == original_product
    assert result["adapter_invoked"] is False
    assert result["blind_retry_allowed"] is False


def test_remote_publication_id_finalizes_series_and_preserves_exact_product() -> None:
    first = begin_tiktok()
    original_product = copy.deepcopy(series_item(first["state"])["product"])
    persisted: list[dict] = []
    result = series_async.reconcile_series_async_dispatch(
        first["state"], first["pending"], "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda pending: {
            "state": "PUBLISHED",
            "remote_submission_id": pending["remote_submission_id"],
            "remote_publication_id": "7499900011223344556",
            "provider_status": "PUBLISH_COMPLETE",
            "publication_confirmed": True,
        },
        persist_result=lambda expected, candidate: persisted.append(copy.deepcopy(candidate)) is None,
    )
    assert result["decision"] == "PUBLISHED"
    assert result["publication_status"] == "PUBLISHED"
    assert result["record"]["remote_publication_id"] == "7499900011223344556"
    assert series_record(result["state"])["remote_publication_id"] == "7499900011223344556"
    assert series_item(result["state"])["product"] == original_product
    assert result["publication_confirmed"] is True
    assert len(persisted) == 1


def test_publish_complete_without_remote_post_id_remains_pending_for_proof() -> None:
    first = begin_tiktok()
    result = series_async.reconcile_series_async_dispatch(
        first["state"], first["pending"], "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda pending: {
            "state": "PENDING_PUBLICATION_PROOF",
            "remote_submission_id": pending["remote_submission_id"],
            "remote_publication_id": None,
            "provider_status": "PUBLISH_COMPLETE",
            "publication_confirmed": False,
        },
    )
    assert result["decision"] == "REMOTE_STILL_PENDING"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert result["publication_confirmed"] is False


def test_explicit_remote_failure_is_terminal_not_invented_success() -> None:
    first = begin_tiktok()
    result = series_async.reconcile_series_async_dispatch(
        first["state"], first["pending"], "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda pending: {
            "state": "FAILED",
            "remote_submission_id": pending["remote_submission_id"],
            "remote_publication_id": None,
            "provider_status": "FAILED",
            "error_code": "video_pull_failed",
            "publication_confirmed": False,
        },
    )
    assert result["decision"] == "FAILED_TERMINAL"
    assert result["publication_status"] == "FAILED_TERMINAL"
    assert series_record(result["state"])["status"] == "FAILED_TERMINAL"
    assert result["publication_confirmed"] is False


def test_tampered_series_pending_fails_closed_before_remote_poll() -> None:
    first = begin_tiktok()
    pending = copy.deepcopy(first["pending"])
    pending["remote_submission_id"] = "tampered"
    calls = {"poll": 0}
    result = series_async.reconcile_series_async_dispatch(
        first["state"], pending, "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda value: calls.__setitem__("poll", calls["poll"] + 1) or {},
    )
    assert result["blocked"] is True
    assert "SERIES_ASYNC_PENDING_FINGERPRINT_INVALID" in result["hard_blocks"]
    assert calls["poll"] == 0


def test_resealed_source_story_tamper_is_still_detected() -> None:
    first = begin_tiktok()
    pending = copy.deepcopy(first["pending"])
    pending["source_story_ids"] = ["story-other"]
    pending = series_async._seal_pending(pending)
    calls = {"poll": 0}
    result = series_async.reconcile_series_async_dispatch(
        first["state"], pending, "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda value: calls.__setitem__("poll", calls["poll"] + 1) or {},
    )
    assert result["blocked"] is True
    assert "SERIES_ASYNC_PENDING_SOURCE_STORY_DIVERGENCE" in result["hard_blocks"]
    assert calls["poll"] == 0


def test_secret_bearing_submission_result_is_rejected_after_network_boundary() -> None:
    state, capabilities = initialized_tiktok()

    def bad(invocation: dict) -> dict:
        result = accepted(invocation)
        result["access_token"] = "DO-NOT-PERSIST"
        return result

    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-a",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=bad,
        persist_pending=lambda pending: True,
    )
    assert result["blocked"] is True
    assert "ASYNC_SUBMISSION_SECRET_OR_RAW_FIELD" in result["hard_blocks"]
    assert "DO-NOT-PERSIST" not in str(result["state"])
    assert result["blind_retry_allowed"] is False


def test_result_persistence_conflict_keeps_durable_outer_series_publishing() -> None:
    first = begin_tiktok()
    result = series_async.reconcile_series_async_dispatch(
        first["state"], first["pending"], "2026-08-16T15:02:00Z",
        fetch_remote_status=lambda pending: {
            "state": "PUBLISHED",
            "remote_submission_id": pending["remote_submission_id"],
            "remote_publication_id": "remote-known-but-cas-lost",
            "provider_status": "PUBLISH_COMPLETE",
            "publication_confirmed": True,
        },
        persist_result=lambda expected, candidate: False,
    )
    assert result["decision"] == "RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED"
    assert series_record(result["state"])["status"] == "PUBLISHING"
    assert series_record(result["state"])["remote_publication_id"] is None
    assert result["blind_retry_allowed"] is False


def test_generic_async_wrapper_preserves_multi_story_identity_for_any_truthfully_async_adapter() -> None:
    state, _ = durable_fixture.initialized("facebook")
    capabilities = handoff_fixture.capabilities()
    fb = next(item for item in capabilities["adapters"] if item["platform"] == "facebook")
    fb["completion_model"] = "async_remote_status"
    fb["remote_reconciliation_supported"] = True
    original_product = copy.deepcopy(series_item(state)["product"])
    seen: list[list[str]] = []

    def accept_simulated_async(invocation: dict) -> dict:
        seen.append(copy.deepcopy(invocation["source_story_ids"]))
        result = accepted(invocation, "simulated-async-series")
        result["native_format"] = original_product["native_format"]
        return result

    result = series_async.begin_series_async_dispatch(
        state, capabilities, NOW, "worker-simulated-async",
        persist_claim=lambda expected, candidate: True,
        invoke_adapter=accept_simulated_async,
        persist_pending=lambda pending: True,
    )
    assert result["decision"] == "SERIES_ASYNC_REMOTE_PENDING"
    assert seen == [["story-a", "story-b"]]
    assert result["pending"]["source_story_ids"] == ["story-a", "story-b"]
    assert series_item(result["state"])["product"] == original_product
    assert result["pending"]["guards"]["native_multi_story_product_preserved"] is True


def main() -> int:
    tests = [
        test_tiktok_series_claim_is_durable_before_submit_and_submission_id_is_not_publication_proof,
        test_non_async_adapter_capability_is_blocked_before_network,
        test_async_capability_requires_remote_reconciliation_support,
        test_claim_persistence_conflict_prevents_async_series_submit,
        test_network_exception_is_ambiguous_and_never_blindly_retried,
        test_pending_persistence_conflict_keeps_series_publishing_and_exposes_only_safe_candidate,
        test_second_worker_cannot_submit_while_async_series_lease_is_active,
        test_remote_pending_updates_only_sidecar_and_preserves_native_series_product,
        test_remote_publication_id_finalizes_series_and_preserves_exact_product,
        test_publish_complete_without_remote_post_id_remains_pending_for_proof,
        test_explicit_remote_failure_is_terminal_not_invented_success,
        test_tampered_series_pending_fails_closed_before_remote_poll,
        test_resealed_source_story_tamper_is_still_detected,
        test_secret_bearing_submission_result_is_rejected_after_network_boundary,
        test_result_persistence_conflict_keeps_durable_outer_series_publishing,
        test_generic_async_wrapper_preserves_multi_story_identity_for_any_truthfully_async_adapter,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Series Async Remote Dispatch acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
