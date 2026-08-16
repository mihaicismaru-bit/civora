#!/usr/bin/env python3
"""Acceptance tests for durable observed-feedback snapshot binding."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot_mod = _load("durable_feedback_snapshot", "durable_feedback_snapshot.py")


def channel(**overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "status": "active",
        "cadence": {"timezone": "Europe/Bucharest"},
        "publication_state": {
            "outbox_path": "alpha/social/facebook_outbox.json",
            "state_path": "alpha/social/facebook_state.json",
            "dedupe_by_id": True,
            "last_known_good": True,
        },
        "metrics": {"observed_only": True, "sources": ["meta_graph_api"]},
        "zero_paid_dependency": True,
    }
    value.update(overrides)
    return value


def observation(
    idx: int,
    *,
    topic: str = "service_journalism",
    native_format: str = "text",
    series_id: str = "morning-brief",
    published_at: str = "2026-08-15T07:00:00Z",
    end_at: str = "2026-08-15T10:00:00Z",
    observed_at: str = "2026-08-15T10:05:00Z",
    actions: int = 20,
) -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "publication_id": f"publication:{idx}",
        "remote_publication_id": f"remote-{idx}",
        "story_id": f"story-{idx}",
        "product_id": f"product-{idx}",
        "source": "meta_graph_api",
        "observed_at": observed_at,
        "window": {"kind": "cumulative", "start_at": published_at, "end_at": end_at},
        "publication_context": {
            "status": "PUBLISHED",
            "published_at": published_at,
            "native_format": native_format,
            "topic_keys": [topic],
            "series_id": series_id,
        },
        "metrics": {
            "reach": 1000,
            "reactions": 999999,
            "shares": actions,
            "saves": actions,
            "comments": actions,
            "link_clicks": actions,
        },
        "provenance": {
            "retrieval_method": "native_api",
            "collector": "github_actions",
            "source_payload_sha256": f"{idx:x}" * 64,
            "collected_at": observed_at,
        },
        "guards": {"observed_only": True, "predicted_or_estimated": False},
    }


def observations() -> list[dict]:
    rows: list[dict] = []
    for idx in range(1, 4):
        rows.append(observation(idx, actions=30))
    for idx in range(4, 7):
        rows.append(observation(
            idx,
            topic="local_events",
            native_format="single_photo",
            series_id="evening-brief",
            published_at="2026-08-15T12:00:00Z",
            end_at="2026-08-15T15:00:00Z",
            observed_at="2026-08-15T15:05:00Z",
            actions=1,
        ))
    return rows


def ready_snapshot(*, now: str = "2026-08-16T12:00:00Z", ttl_hours: int = 48) -> dict:
    return snapshot_mod.build_snapshot(channel(), observations(), now=now, ttl_hours=ttl_hours, min_samples=3)


def test_channel_local_storage_path_is_derived_from_publication_state() -> None:
    assert snapshot_mod.expected_snapshot_path(channel()) == "alpha/social/facebook_state_feedback_snapshot.json"


def test_ready_snapshot_is_sealed_and_observed_only() -> None:
    snapshot = ready_snapshot()
    assert snapshot["status"] == "READY", snapshot
    assert snapshot["usable"] is True, snapshot
    assert snapshot["source_observation_count"] == 6, snapshot
    assert snapshot["source_latest_observed_at"] == "2026-08-15T15:05:00Z", snapshot
    assert snapshot["expires_at"] == "2026-08-17T15:05:00Z", snapshot
    assert len(snapshot["snapshot_fingerprint_sha256"]) == 64, snapshot
    assert snapshot["guards"]["observed_metrics_only"] is True, snapshot
    assert snapshot["guards"]["zero_paid_dependency"] is True, snapshot


def test_freshness_is_anchored_to_observation_not_rebuild_time() -> None:
    first = ready_snapshot(now="2026-08-16T12:00:00Z", ttl_hours=48)
    rebuilt = ready_snapshot(now="2026-08-17T12:00:00Z", ttl_hours=48)
    assert first["expires_at"] == rebuilt["expires_at"] == "2026-08-17T15:05:00Z", (first, rebuilt)


def test_stale_snapshot_has_zero_learning_influence() -> None:
    snapshot = ready_snapshot(ttl_hours=24)
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-17T16:00:00Z")
    assert binding["status"] == "IGNORED_STALE", binding
    assert binding["bound"] is False, binding
    assert binding["feedback"] is None, binding
    assert binding["guards"]["publication_blocked"] is False, binding


def test_fresh_ready_snapshot_binds_feedback() -> None:
    snapshot = ready_snapshot()
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "BOUND", binding
    assert binding["bound"] is True, binding
    assert binding["feedback"]["feedback_fingerprint_sha256"] == snapshot["feedback_fingerprint_sha256"], binding


def test_cross_instance_snapshot_is_ignored_fail_closed_for_learning() -> None:
    snapshot = ready_snapshot()
    snapshot["instance_id"] = "beta"
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert "INSTANCE_MISMATCH" in binding["hard_blocks"], binding
    assert binding["feedback"] is None, binding


def test_storage_namespace_tamper_is_rejected() -> None:
    snapshot = ready_snapshot()
    snapshot["storage_path"] = "beta/social/facebook_state_feedback_snapshot.json"
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert "SNAPSHOT_STORAGE_NAMESPACE_MISMATCH" in binding["hard_blocks"], binding


def test_feedback_tamper_or_secret_like_field_is_rejected() -> None:
    snapshot = ready_snapshot()
    snapshot["feedback"]["access_token"] = "never-persist-this"
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert any("SECRET_LIKE_FIELD_PRESENT" in block for block in binding["hard_blocks"]), binding
    assert binding["feedback"] is None, binding


def test_predictive_field_is_rejected() -> None:
    snapshot = ready_snapshot()
    snapshot["feedback"]["predicted_views"] = 999999
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert any("PREDICTIVE_OR_ESTIMATED_ANALYTICS_PRESENT" in block for block in binding["hard_blocks"]), binding


def test_snapshot_fingerprint_tampering_is_rejected() -> None:
    snapshot = ready_snapshot()
    snapshot["ttl_hours"] = 72
    binding = snapshot_mod.resolve_snapshot(channel(), snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert "SNAPSHOT_FINGERPRINT_MISMATCH" in binding["hard_blocks"], binding


def test_future_observation_cannot_become_fresh_feedback() -> None:
    rows = observations()
    rows[-1]["observed_at"] = "2026-08-18T15:05:00Z"
    rows[-1]["provenance"]["collected_at"] = "2026-08-18T15:05:00Z"
    rows[-1]["window"]["end_at"] = "2026-08-18T15:00:00Z"
    snapshot = snapshot_mod.build_snapshot(channel(), rows, now="2026-08-16T12:00:00Z", ttl_hours=48)
    assert snapshot["usable"] is False, snapshot
    assert "OBSERVATION_FROM_FUTURE" in snapshot["hard_blocks"], snapshot


def test_unsafe_ttl_is_rejected_before_snapshot_creation() -> None:
    for ttl in (0, 721):
        try:
            snapshot_mod.build_snapshot(channel(), observations(), now="2026-08-16T12:00:00Z", ttl_hours=ttl)
        except ValueError:
            pass
        else:
            raise AssertionError(f"unsafe ttl accepted: {ttl}")


def test_insufficient_feedback_never_replaces_ready_snapshot() -> None:
    candidate = snapshot_mod.build_snapshot(
        channel(), [observation(1)], now="2026-08-16T12:00:00Z", ttl_hours=48, min_samples=3
    )
    assert candidate["status"] == "READY", candidate
    # A single valid publication can produce a READY report but no learnable hints; it is still
    # safe to persist. Force the explicit insufficient contract by removing action denominator.
    weak = observation(2)
    weak["metrics"] = {"reactions": 3}
    insufficient = snapshot_mod.build_snapshot(
        channel(), [weak], now="2026-08-16T12:00:00Z", ttl_hours=48, min_samples=3
    )
    assert insufficient["status"] == "INSUFFICIENT_OBSERVED_DATA", insufficient
    decision = snapshot_mod.should_replace_snapshot(channel(), ready_snapshot(), insufficient, now="2026-08-16T12:00:00Z")
    assert decision["replace"] is False, decision
    assert decision["reason"] == "CANDIDATE_NOT_READY", decision


def test_rebuild_of_same_observed_watermark_cannot_refresh_or_replace() -> None:
    existing = ready_snapshot(now="2026-08-16T12:00:00Z")
    rebuilt = ready_snapshot(now="2026-08-17T12:00:00Z")
    decision = snapshot_mod.should_replace_snapshot(channel(), existing, rebuilt, now="2026-08-17T12:00:00Z")
    assert decision["replace"] is False, decision
    assert decision["reason"] == "NOT_NEWER_OBSERVED_WATERMARK", decision


def test_newer_observed_watermark_replaces_older_snapshot() -> None:
    existing = ready_snapshot(now="2026-08-16T12:00:00Z")
    newer_rows = observations()
    newer_rows.append(observation(
        7,
        observed_at="2026-08-16T16:05:00Z",
        published_at="2026-08-16T12:00:00Z",
        end_at="2026-08-16T16:00:00Z",
        actions=25,
    ))
    candidate = snapshot_mod.build_snapshot(channel(), newer_rows, now="2026-08-16T17:00:00Z", ttl_hours=48)
    decision = snapshot_mod.should_replace_snapshot(channel(), existing, candidate, now="2026-08-16T17:00:00Z")
    assert decision["replace"] is True, decision
    assert decision["reason"] == "NEWER_OBSERVED_WATERMARK", decision


def test_identical_snapshot_persistence_is_idempotent() -> None:
    snapshot = ready_snapshot()
    decision = snapshot_mod.should_replace_snapshot(channel(), snapshot, copy.deepcopy(snapshot), now="2026-08-16T12:00:00Z")
    assert decision["replace"] is False, decision
    assert decision["reason"] == "IDEMPOTENT_SAME_SNAPSHOT", decision


def test_runtime_wrapper_automatically_injects_only_bound_feedback() -> None:
    original = snapshot_mod.production_runtime.orchestrate_channel
    calls: list[dict] = []

    def fake_runtime(story, ch, media, history, **kwargs):
        calls.append(kwargs)
        return {"blocked": False, "artifacts": {}, "guards": {"zero_paid_dependency": True}}

    snapshot_mod.production_runtime.orchestrate_channel = fake_runtime
    try:
        result = snapshot_mod.orchestrate_with_snapshot(
            {"story_id": "story-current", "instance_id": "alpha"},
            channel(),
            {"instance_id": "alpha", "assets": []},
            {"instance_id": "alpha", "channel_id": "alpha-facebook", "records": []},
            now="2026-08-16T12:00:00Z",
            feedback_snapshot=ready_snapshot(),
        )
    finally:
        snapshot_mod.production_runtime.orchestrate_channel = original
    assert calls and isinstance(calls[0].get("observed_feedback"), dict), calls
    assert result["feedback_snapshot_binding"]["status"] == "BOUND", result
    assert "feedback" not in result["feedback_snapshot_binding"], result


def test_runtime_wrapper_stale_or_invalid_snapshot_is_publication_noop() -> None:
    original = snapshot_mod.production_runtime.orchestrate_channel
    observed_values: list[object] = []

    def fake_runtime(story, ch, media, history, **kwargs):
        observed_values.append(kwargs.get("observed_feedback"))
        return {"blocked": False, "disposition": "READY", "artifacts": {}}

    snapshot_mod.production_runtime.orchestrate_channel = fake_runtime
    try:
        stale = ready_snapshot(ttl_hours=24)
        result = snapshot_mod.orchestrate_with_snapshot(
            {}, channel(), {}, {}, now="2026-08-17T16:00:00Z", feedback_snapshot=stale
        )
    finally:
        snapshot_mod.production_runtime.orchestrate_channel = original
    assert observed_values == [None], observed_values
    assert result["blocked"] is False, result
    assert result["disposition"] == "READY", result
    assert result["feedback_snapshot_binding"]["status"] == "IGNORED_STALE", result


def test_zero_paid_dependency_violation_never_binds() -> None:
    unsafe_channel = channel(zero_paid_dependency=False)
    snapshot = ready_snapshot()
    binding = snapshot_mod.resolve_snapshot(unsafe_channel, snapshot, now="2026-08-16T12:00:00Z")
    assert binding["status"] == "IGNORED_INVALID", binding
    assert "ZERO_PAID_DEPENDENCY_VIOLATION" in binding["hard_blocks"], binding
    assert binding["feedback"] is None, binding


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS durable feedback snapshot acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
