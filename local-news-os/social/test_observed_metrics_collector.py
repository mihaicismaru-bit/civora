#!/usr/bin/env python3
"""Acceptance tests for observed native-metrics collection and snapshot materialization."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


collector = _load("observed_metrics_collector", "observed_metrics_collector.py")


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


def publication(idx: int = 1, **overrides) -> dict:
    value = {
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "status": "PUBLISHED",
        "publication_id": f"publication:{idx}",
        "remote_publication_id": f"remote:{idx}",
        "story_id": f"story:{idx}",
        "product_id": f"product:{idx}",
        "published_at": "2026-08-16T08:00:00Z",
        "native_format": "single_photo",
        "topic_keys": ["service_journalism"],
        "series_id": None,
    }
    value.update(overrides)
    return value


def payload(actions: int = 5, **extra) -> dict:
    value = {
        "metrics": {
            "reach": 1000,
            "shares": actions,
            "saves": actions,
            "comments": actions,
            "link_clicks": actions,
            "reactions": 999999,
        },
        "provider_request_id": "safe-audit-id",
    }
    value.update(extra)
    return value


def build(idx: int = 1, *, raw: dict | None = None, end_at: str = "2026-08-16T12:00:00Z", observed_at: str = "2026-08-16T12:05:00Z") -> dict:
    return collector.build_observation(
        channel(),
        publication(idx),
        raw or payload(),
        source="meta_graph_api",
        observed_at=observed_at,
        collected_at=observed_at,
        window_start_at="2026-08-16T08:00:00Z",
        window_end_at=end_at,
    )


def test_observation_store_path_is_channel_local() -> None:
    assert collector.expected_observation_store_path(channel()) == "alpha/social/facebook_state_observed_metrics.json"


def test_canonical_provider_metrics_are_normalized_without_inference() -> None:
    result = collector.normalize_provider_metrics(payload(actions=7))
    assert result["reach"] == 1000, result
    assert result["shares"] == 7, result
    assert result["saves"] == 7, result
    assert result["reactions"] == 999999, result
    assert "provider_request_id" not in result, result


def test_graph_style_payload_uses_direct_scalar_values_only() -> None:
    raw = {
        "data": [
            {"name": "reach", "values": [{"value": 800}, {"value": 900}]},
            {"name": "saved", "value": 12},
            {"name": "shares", "value": 9},
            {"name": "post_reactions_by_type_total", "value": {"LIKE": 100, "LOVE": 20}},
        ]
    }
    result = collector.normalize_provider_metrics(raw)
    assert result == {"reach": 900, "saves": 12, "shares": 9}, result


def test_conflicting_aliases_fail_closed_instead_of_picking_a_value() -> None:
    raw = {"metrics": {"reach": 100, "post_impressions_unique": 101}}
    try:
        collector.normalize_provider_metrics(raw)
    except ValueError as exc:
        assert "CONFLICTING_PROVIDER_METRIC:reach" in str(exc), exc
    else:
        raise AssertionError("conflicting aliases were accepted")


def test_only_confirmed_remote_publications_can_be_observed() -> None:
    result = collector.build_observation(
        channel(),
        publication(status="READY"),
        payload(),
        source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z",
        collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z",
        window_end_at="2026-08-16T12:00:00Z",
    )
    assert result["valid"] is False, result
    assert "PUBLICATION_NOT_CONFIRMED" in result["hard_blocks"], result


def test_cross_channel_publication_identity_is_rejected() -> None:
    result = collector.build_observation(
        channel(),
        publication(channel_id="alpha-instagram"),
        payload(),
        source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z",
        collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z",
        window_end_at="2026-08-16T12:00:00Z",
    )
    assert result["valid"] is False, result
    assert "CHANNEL_MISMATCH" in result["hard_blocks"], result


def test_undeclared_native_metric_source_is_rejected() -> None:
    result = collector.build_observation(
        channel(),
        publication(),
        payload(),
        source="unverified_export",
        observed_at="2026-08-16T12:05:00Z",
        collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z",
        window_end_at="2026-08-16T12:00:00Z",
    )
    assert result["valid"] is False, result
    assert "UNDECLARED_METRIC_SOURCE" in result["hard_blocks"], result


def test_predictive_or_estimated_provider_fields_are_rejected_even_if_unused() -> None:
    raw = payload()
    raw["predicted_views"] = 999999
    result = build(raw=raw)
    assert result["valid"] is False, result
    assert any("PREDICTIVE_OR_ESTIMATED_PROVIDER_FIELD" in block for block in result["hard_blocks"]), result


def test_secret_like_provider_fields_are_rejected_and_never_persisted() -> None:
    raw = payload()
    raw["access_token"] = "never-store-me"
    result = build(raw=raw)
    assert result["valid"] is False, result
    assert any("SECRET_LIKE_PROVIDER_FIELD" in block for block in result["hard_blocks"]), result
    assert "never-store-me" not in json.dumps(result, ensure_ascii=False), result


def test_observation_is_source_hashed_and_raw_payload_is_not_retained() -> None:
    raw = payload(actions=11)
    result = build(raw=raw)
    assert result["valid"] is True, result
    observation = result["observation"]
    assert len(observation["provenance"]["source_payload_sha256"]) == 64, observation
    assert observation["metrics"]["shares"] == 11, observation
    encoded = json.dumps(observation, ensure_ascii=False)
    assert "provider_request_id" not in encoded, encoded
    assert "safe-audit-id" not in encoded, encoded


def test_same_provider_evidence_build_is_deterministic() -> None:
    first = build(raw=payload(actions=3))["observation"]
    second = build(raw=copy.deepcopy(payload(actions=3)))["observation"]
    assert first["observation_id"] == second["observation_id"], (first, second)
    assert first["provenance"]["source_payload_sha256"] == second["provenance"]["source_payload_sha256"], (first, second)


def test_store_merge_is_idempotent_for_the_same_observation() -> None:
    observation = build()["observation"]
    first = collector.merge_observation_store(channel(), None, observation)
    assert first["ok"] is True and first["action"] == "APPENDED", first
    second = collector.merge_observation_store(channel(), first["store"], copy.deepcopy(observation))
    assert second["ok"] is True and second["action"] == "IDEMPOTENT", second
    assert len(second["store"]["observations"]) == 1, second


def test_same_publication_window_with_different_payload_is_a_hard_conflict() -> None:
    first_obs = build(raw=payload(actions=2))["observation"]
    first = collector.merge_observation_store(channel(), None, first_obs)
    second_obs = build(raw=payload(actions=20))["observation"]
    conflict = collector.merge_observation_store(channel(), first["store"], second_obs)
    assert conflict["ok"] is False, conflict
    assert conflict["action"] == "HOLD_OBSERVATION_CONFLICT", conflict
    assert "SAME_WINDOW_PROVIDER_EVIDENCE_CONFLICT" in conflict["hard_blocks"], conflict


def test_newer_cumulative_window_is_preserved_as_new_observation() -> None:
    first_obs = build(end_at="2026-08-16T10:00:00Z", observed_at="2026-08-16T10:05:00Z")["observation"]
    first = collector.merge_observation_store(channel(), None, first_obs)
    second_obs = build(end_at="2026-08-16T12:00:00Z", observed_at="2026-08-16T12:05:00Z")["observation"]
    second = collector.merge_observation_store(channel(), first["store"], second_obs)
    assert second["ok"] is True and second["action"] == "APPENDED", second
    assert len(second["store"]["observations"]) == 2, second


def test_store_fingerprint_tamper_is_rejected_before_merge() -> None:
    first = collector.merge_observation_store(channel(), None, build()["observation"])
    tampered = copy.deepcopy(first["store"])
    tampered["channel_id"] = "alpha-instagram"
    result = collector.merge_observation_store(channel(), tampered, build(2)["observation"])
    assert result["ok"] is False, result
    assert result["action"] == "REJECTED_EXISTING_STORE", result
    assert "CHANNEL_MISMATCH" in result["hard_blocks"], result


def test_materialization_advances_store_and_snapshot_without_blocking_publication() -> None:
    bundle = collector.materialize_bundle(
        channel(),
        publication(),
        payload(actions=8),
        source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z",
        collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z",
        window_end_at="2026-08-16T12:00:00Z",
        now="2026-08-16T12:10:00Z",
    )
    assert bundle["status"] == "MATERIALIZED", bundle
    assert bundle["guards"]["publication_blocked"] is False, bundle
    assert bundle["guards"]["raw_provider_payload_persisted"] is False, bundle
    assert bundle["snapshot_to_persist"]["usable"] is True, bundle
    assert [item["kind"] for item in bundle["write_plan"]] == ["OBSERVATION_STORE", "FEEDBACK_SNAPSHOT"], bundle


def test_replay_of_same_payload_is_idempotent_and_does_not_refresh_snapshot() -> None:
    first = collector.materialize_bundle(
        channel(), publication(), payload(), source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z", collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z", window_end_at="2026-08-16T12:00:00Z",
        now="2026-08-16T12:10:00Z",
    )
    second = collector.materialize_bundle(
        channel(), publication(), payload(), source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z", collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z", window_end_at="2026-08-16T12:00:00Z",
        now="2026-08-16T13:10:00Z",
        existing_store=first["observation_store"], existing_snapshot=first["snapshot_to_persist"],
    )
    assert second["status"] == "IDEMPOTENT", second
    assert second["observation_action"] == "IDEMPOTENT", second
    assert second["snapshot_to_persist"] is None, second
    assert second["write_plan"] == [], second


def test_atomic_persistence_writes_only_sanitized_derived_files() -> None:
    bundle = collector.materialize_bundle(
        channel(), publication(), payload(), source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z", collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z", window_end_at="2026-08-16T12:00:00Z",
        now="2026-08-16T12:10:00Z",
    )
    with TemporaryDirectory() as raw_root:
        root = Path(raw_root)
        result = collector.persist_bundle(root, bundle)
        assert result["written"] == [
            "alpha/social/facebook_state_observed_metrics.json",
            "alpha/social/facebook_state_feedback_snapshot.json",
        ], result
        store_text = (root / result["written"][0]).read_text(encoding="utf-8")
        snapshot_text = (root / result["written"][1]).read_text(encoding="utf-8")
        assert "safe-audit-id" not in store_text + snapshot_text
        assert "access_token" not in store_text + snapshot_text
        assert not list(root.rglob("*.tmp")), list(root.rglob("*.tmp"))


def test_zero_paid_dependency_is_mandatory() -> None:
    unsafe = channel(zero_paid_dependency=False)
    result = collector.build_observation(
        unsafe, publication(), payload(), source="meta_graph_api",
        observed_at="2026-08-16T12:05:00Z", collected_at="2026-08-16T12:05:00Z",
        window_start_at="2026-08-16T08:00:00Z", window_end_at="2026-08-16T12:00:00Z",
    )
    assert result["valid"] is False, result
    assert result["hard_blocks"] == ["ZERO_PAID_DEPENDENCY_VIOLATION"], result


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS observed metrics collector acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
