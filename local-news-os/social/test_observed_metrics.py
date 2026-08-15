#!/usr/bin/env python3
"""Acceptance tests for LOCAL NEWS OS observed-metrics and feedback learning."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("observed_metrics", HERE / "observed_metrics.py")
assert SPEC and SPEC.loader
observed_metrics = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(observed_metrics)
validate_observation = observed_metrics.validate_observation
build_feedback = observed_metrics.build_feedback

HASH_A = "a" * 64


def channel(**overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "status": "active",
        "cadence": {"timezone": "Europe/Bucharest"},
        "metrics": {"observed_only": True, "sources": ["meta_graph_api"]},
        "zero_paid_dependency": True,
    }
    value.update(overrides)
    return value


def observation(*, publication_id: str = "publication:1", published_at: str = "2026-08-15T07:00:00Z", end_at: str = "2026-08-15T10:00:00Z", source_hash: str = HASH_A, metrics: dict | None = None, topics: list[str] | None = None, native_format: str = "single_photo", series_id: str | None = None, **overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "publication_id": publication_id,
        "remote_publication_id": "remote-" + publication_id.split(":")[-1],
        "story_id": "story-" + publication_id.split(":")[-1],
        "product_id": "product-" + publication_id.split(":")[-1],
        "source": "meta_graph_api",
        "observed_at": "2026-08-15T10:05:00Z",
        "window": {"kind": "cumulative", "start_at": published_at, "end_at": end_at},
        "publication_context": {
            "status": "PUBLISHED",
            "published_at": published_at,
            "native_format": native_format,
            "topic_keys": topics if topics is not None else ["infrastructure"],
            "series_id": series_id,
        },
        "metrics": metrics if metrics is not None else {
            "impressions": 1000,
            "reach": 800,
            "reactions": 30,
            "comments": 8,
            "shares": 12,
            "saves": 4,
            "link_clicks": 16,
        },
        "provenance": {
            "retrieval_method": "native_api",
            "collector": "github_actions",
            "source_payload_sha256": source_hash,
            "collected_at": "2026-08-15T10:06:00Z",
        },
        "guards": {"observed_only": True, "predicted_or_estimated": False},
    }
    value.update(overrides)
    return value


def test_schema_contract_is_strict_and_observed_only() -> None:
    schema = json.loads((HERE / "observed_metrics.schema.json").read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False, schema
    assert schema["properties"]["guards"]["properties"]["observed_only"]["const"] is True, schema
    assert schema["properties"]["guards"]["properties"]["predicted_or_estimated"]["const"] is False, schema
    assert schema["properties"]["window"]["properties"]["kind"]["const"] == "cumulative", schema
    assert "predicted_views" not in schema["properties"]["metrics"]["properties"], schema


def test_valid_observation_is_normalized_and_id_is_deterministic() -> None:
    first = validate_observation(channel(), observation(topics=["roads", "roads", "civic"]))
    second = validate_observation(channel(), observation(topics=["civic", "roads"]))
    assert first["valid"] and second["valid"], (first, second)
    assert first["observation"]["publication_context"]["topic_keys"] == ["civic", "roads"], first
    assert first["observation"]["observation_id"] == second["observation"]["observation_id"], (first, second)


def test_channel_must_be_observed_only() -> None:
    bad_channel = channel(metrics={"observed_only": False, "sources": ["meta_graph_api"]})
    result = validate_observation(bad_channel, observation())
    assert not result["valid"], result
    assert "CHANNEL_METRICS_NOT_OBSERVED_ONLY" in result["hard_blocks"], result


def test_metric_source_must_be_declared_in_channel_config() -> None:
    result = validate_observation(channel(), observation(source="manual_guess"))
    assert not result["valid"], result
    assert "UNDECLARED_METRIC_SOURCE" in result["hard_blocks"], result


def test_predicted_or_estimated_fields_are_rejected_anywhere() -> None:
    bad = observation()
    bad["metrics"]["predicted_shares"] = 50
    result = validate_observation(channel(), bad)
    assert not result["valid"], result
    assert "PREDICTIVE_OR_ESTIMATED_ANALYTICS_PRESENT" in result["hard_blocks"], result


def test_secret_like_fields_are_rejected() -> None:
    bad = observation()
    bad["provenance"]["access_token"] = "must-never-be-here"
    result = validate_observation(channel(), bad)
    assert not result["valid"], result
    assert "SECRET_LIKE_FIELD_PRESENT" in result["hard_blocks"], result


def test_only_confirmed_remote_publications_are_learnable() -> None:
    bad = observation()
    bad["publication_context"]["status"] = "READY"
    bad["remote_publication_id"] = ""
    result = validate_observation(channel(), bad)
    assert not result["valid"], result
    assert "PUBLICATION_NOT_CONFIRMED" in result["hard_blocks"], result
    assert "MISSING_REMOTE_PUBLICATION_ID" in result["hard_blocks"], result


def test_provenance_hash_and_time_window_are_fail_closed() -> None:
    bad = observation(source_hash="xyz")
    bad["window"]["end_at"] = "2026-08-15T11:00:00Z"
    result = validate_observation(channel(), bad)
    assert not result["valid"], result
    assert "INVALID_SOURCE_PAYLOAD_HASH" in result["hard_blocks"], result
    assert "WINDOW_END_AFTER_OBSERVATION" in result["hard_blocks"], result


def test_metric_values_must_be_finite_nonnegative_and_canonical() -> None:
    bad = observation(metrics={"reach": 100, "shares": -1, "mystery_score": 4})
    result = validate_observation(channel(), bad)
    assert not result["valid"], result
    assert any(block.startswith("INVALID_METRIC_VALUE") for block in result["hard_blocks"]), result
    assert any(block.startswith("UNKNOWN_METRIC") for block in result["hard_blocks"]), result


def test_instance_channel_and_platform_are_isolated() -> None:
    for bad in (
        observation(instance_id="beta"),
        observation(channel_id="beta-facebook"),
        observation(platform="instagram"),
    ):
        result = validate_observation(channel(), bad)
        assert not result["valid"], result
    report = build_feedback(channel(), [observation(instance_id="beta")])
    assert report["learning_samples"] == 0, report
    assert report["guards"]["channel_learning_independent"] is True, report


def test_latest_cumulative_snapshot_per_publication_prevents_double_counting() -> None:
    early = observation(publication_id="publication:1", end_at="2026-08-15T09:00:00Z", source_hash="1" * 64, metrics={"reach": 100, "shares": 1, "comments": 1})
    late = observation(publication_id="publication:1", end_at="2026-08-15T10:00:00Z", source_hash="2" * 64, metrics={"reach": 100, "shares": 10, "comments": 5})
    report = build_feedback(channel(), [early, late], min_samples=2)
    assert report["accepted_observations"] == 2, report
    assert report["latest_publication_samples"] == 1, report
    assert report["learning_samples"] == 1, report
    assert report["sample_basis"][0]["observed_action_rate"] == 0.15, report


def test_raw_reactions_do_not_drive_learning() -> None:
    a = observation(publication_id="publication:1", source_hash="1" * 64, metrics={"reach": 1000, "reactions": 1, "shares": 10, "comments": 5})
    b = observation(publication_id="publication:2", source_hash="2" * 64, metrics={"reach": 1000, "reactions": 100000, "shares": 10, "comments": 5})
    report = build_feedback(channel(), [a, b], min_samples=2)
    rates = [row["observed_action_rate"] for row in report["sample_basis"]]
    assert rates == [0.015, 0.015], report
    assert report["baseline"]["reaction_count_used"] is False, report
    assert report["guards"]["raw_reactions_optimized"] is False, report


def test_feedback_is_bounded_advisory_and_never_mutates_gates() -> None:
    observations = []
    for idx, shares in enumerate((1, 2, 3, 30, 40, 50), start=1):
        topic = "low" if idx <= 3 else "high"
        observations.append(observation(
            publication_id=f"publication:{idx}",
            source_hash=f"{idx:x}" * 64,
            metrics={"reach": 1000, "shares": shares, "saves": shares, "comments": shares},
            topics=[topic],
        ))
    report = build_feedback(channel(), observations, min_samples=3)
    hints = report["feedback"]["fit_topic_hints"]
    assert {hint["key"] for hint in hints} == {"high", "low"}, report
    assert all(-5.0 <= hint["bounded_adjustment_points"] <= 5.0 for hint in hints), report
    assert report["application_policy"]["mode"] == "ADVISORY_ONLY", report
    assert report["application_policy"]["auto_mutate_channel_config"] is False, report
    assert report["application_policy"]["may_change_editorial_exclusions"] is False, report
    assert report["application_policy"]["may_weaken_approval_gates"] is False, report


def test_feedback_covers_format_timing_series_and_fit_only_with_enough_samples() -> None:
    observations = []
    for idx in range(1, 4):
        observations.append(observation(
            publication_id=f"publication:{idx}",
            published_at=f"2026-08-15T07:0{idx}:00Z",
            source_hash=str(idx) * 64,
            metrics={"reach": 1000, "shares": 20, "saves": 10, "comments": 5},
            topics=["service_journalism"],
            native_format="single_photo",
            series_id="editia-de-dimineata",
        ))
    report = build_feedback(channel(), observations, min_samples=3)
    assert report["feedback"]["fit_topic_hints"], report
    assert report["feedback"]["format_hints"], report
    assert report["feedback"]["timing_hints"], report
    assert report["feedback"]["series_hints"], report
    assert report["learning_timezone"] == "Europe/Bucharest", report


def test_insufficient_samples_do_not_create_false_learning_hint() -> None:
    report = build_feedback(channel(), [observation(publication_id="publication:1")], min_samples=3)
    assert report["learning_samples"] == 1, report
    assert report["feedback"]["fit_topic_hints"] == [], report
    assert report["feedback"]["timing_hints"] == [], report


def test_records_without_observed_reach_or_impressions_are_stored_but_not_learned() -> None:
    item = observation(metrics={"shares": 10, "comments": 5})
    report = build_feedback(channel(), [item], min_samples=2)
    assert report["accepted_observations"] == 1, report
    assert report["learning_samples"] == 0, report
    assert len(report["excluded_without_observed_denominator_or_actions"]) == 1, report


def test_feedback_report_is_deterministic_and_cross_channel_comparison_is_forbidden() -> None:
    observations = [
        observation(publication_id="publication:1", source_hash="1" * 64),
        observation(publication_id="publication:2", source_hash="2" * 64),
        observation(publication_id="publication:3", source_hash="3" * 64),
    ]
    first = build_feedback(channel(), observations)
    second = build_feedback(channel(), copy.deepcopy(observations))
    assert first == second, (first, second)
    assert first["application_policy"]["may_compare_across_channels_or_platforms"] is False, first
    assert first["guards"]["predicted_or_estimated_analytics_used"] is False, first
    assert first["guards"]["zero_paid_dependency"] is True, first


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS observed metrics acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
