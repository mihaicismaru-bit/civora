#!/usr/bin/env python3
"""Acceptance tests for bounded observed-feedback application in LOCAL NEWS OS."""
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


observed_metrics = _load("observed_metrics", "observed_metrics.py")
feedback_app = _load("observed_feedback_application", "observed_feedback_application.py")
validate_feedback = feedback_app.validate_feedback
apply_observed_feedback = feedback_app.apply_observed_feedback
apply_to_virality = feedback_app.apply_to_virality


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


def observation(
    idx: int,
    *,
    topic: str,
    native_format: str,
    series_id: str,
    published_at: str,
    end_at: str,
    observed_at: str,
    actions: int,
) -> dict:
    publication_id = f"publication:{idx}"
    return {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "publication_id": publication_id,
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
            "reactions": 999999 if topic == "service_journalism" else 1,
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


def clean_feedback() -> dict:
    observations = []
    for idx in range(1, 4):
        observations.append(observation(
            idx,
            topic="service_journalism",
            native_format="text",
            series_id="morning-brief",
            published_at="2026-08-15T07:00:00Z",
            end_at="2026-08-15T10:00:00Z",
            observed_at="2026-08-15T10:05:00Z",
            actions=30,
        ))
    for idx in range(4, 7):
        observations.append(observation(
            idx,
            topic="local_events",
            native_format="single_photo",
            series_id="evening-brief",
            published_at="2026-08-15T12:00:00Z",
            end_at="2026-08-15T15:00:00Z",
            observed_at="2026-08-15T15:05:00Z",
            actions=1,
        ))
    return observed_metrics.build_feedback(channel(), observations, min_samples=3)


def story(**overrides) -> dict:
    value = {
        "story_id": "story-current",
        "instance_id": "alpha",
        "topics": ["service_journalism"],
    }
    value.update(overrides)
    return value


def format_result(native_format: str = "text") -> dict:
    return {
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "product": {
            "product_id": "product-current",
            "native_format": native_format,
        },
    }


def cadence(evaluated_at: str = "2026-08-16T07:30:00Z", eligible: bool = True) -> dict:
    return {
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "story_id": "story-current",
        "evaluated_at": evaluated_at,
        "eligible": eligible,
        "decision": "PUBLISH_NOW" if eligible else "HOLD_CADENCE",
        "hard_blocks": [],
    }


def series(series_id: str = "morning-brief") -> dict:
    return {
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "eligible": True,
        "decision": "SERIES_READY",
        "hard_blocks": [],
        "occurrence": {
            "series_id": series_id,
            "selected_story_ids": ["story-current"],
        },
    }


def virality(score: float = 71.0, *, blocked: bool = False) -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "story_id": "story-current",
        "channel_id": "alpha-facebook",
        "platform": "facebook",
        "product_id": "product-current",
        "blocked": blocked,
        "hard_blocks": ["HOOK_CLICKBAIT_GUARD"] if blocked else [],
        "score": score,
        "band": "useful" if score >= 60 else "modest",
        "components": {"channel_fit": score},
        "reasons": [],
        "publication_action": "BLOCKED" if blocked else "ELIGIBLE",
        "analytics": {
            "predictive_analytics_used": False,
            "observed_metrics_used": False,
            "ignored_predictive_fields": [],
        },
        "guards": {
            "editorial_gates_weakened": False,
            "zero_paid_dependency": True,
        },
        "decision_fingerprint_sha256": "a" * 64,
    }


def test_generated_feedback_contract_validates() -> None:
    feedback = clean_feedback()
    result = validate_feedback(channel(), feedback)
    assert result["valid"], result
    assert result["max_adjustment_points"] == 5.0, result


def test_positive_feedback_matches_topic_format_timing_and_series() -> None:
    result = apply_observed_feedback(
        channel(), clean_feedback(), story(), format_result(), cadence=cadence(), series=series()
    )
    assert result["status"] == "APPLIED", result
    assert result["applied"] is True, result
    assert {row["dimension"] for row in result["matched_dimensions"]} == {"topic", "format", "timing", "series"}, result
    assert 1.0 <= result["bounded_adjustment_points"] <= 5.0, result


def test_negative_feedback_can_reduce_rank_without_blocking() -> None:
    result = apply_observed_feedback(
        channel(),
        clean_feedback(),
        story(topics=["local_events"]),
        format_result("single_photo"),
        cadence=cadence("2026-08-16T12:30:00Z"),
        series=series("evening-brief"),
    )
    assert result["applied"] is True, result
    assert -5.0 <= result["bounded_adjustment_points"] <= -1.0, result
    assert result["guards"]["publication_blocked_by_learning"] is False, result


def test_matching_dimensions_are_averaged_not_stacked() -> None:
    result = apply_observed_feedback(
        channel(), clean_feedback(), story(), format_result(), cadence=cadence(), series=series()
    )
    dimension_points = [row["adjustment_points"] for row in result["matched_dimensions"]]
    expected = round(sum(dimension_points) / len(dimension_points), 2)
    assert result["bounded_adjustment_points"] == expected, result
    assert abs(result["bounded_adjustment_points"]) <= 5.0, result


def test_no_matching_hints_has_zero_learning_effect() -> None:
    result = apply_observed_feedback(
        channel(), clean_feedback(), story(topics=["unknown"]), format_result("unknown"), cadence=None, series=None
    )
    assert result["status"] == "NO_MATCHING_HINTS", result
    assert result["applied"] is False, result
    assert result["bounded_adjustment_points"] == 0.0, result


def test_insufficient_observed_data_has_zero_learning_effect() -> None:
    one = observation(
        1,
        topic="service_journalism",
        native_format="text",
        series_id="morning-brief",
        published_at="2026-08-15T07:00:00Z",
        end_at="2026-08-15T10:00:00Z",
        observed_at="2026-08-15T10:05:00Z",
        actions=30,
    )
    feedback = observed_metrics.build_feedback(channel(), [one], min_samples=3)
    result = apply_observed_feedback(channel(), feedback, story(), format_result(), cadence=cadence(), series=series())
    assert result["status"] == "NO_MATCHING_HINTS", result
    assert result["bounded_adjustment_points"] == 0.0, result


def test_cross_instance_feedback_is_ignored_not_applied() -> None:
    feedback = clean_feedback()
    feedback["instance_id"] = "beta"
    result = apply_observed_feedback(channel(), feedback, story(), format_result(), cadence=cadence(), series=series())
    assert result["status"] == "IGNORED_INVALID", result
    assert "INSTANCE_MISMATCH" in result["feedback_blocks"], result
    assert result["bounded_adjustment_points"] == 0.0, result


def test_fingerprint_tampering_is_ignored() -> None:
    feedback = clean_feedback()
    feedback["feedback"]["fit_topic_hints"][0]["bounded_adjustment_points"] = 5.0
    result = apply_observed_feedback(channel(), feedback, story(), format_result())
    assert result["status"] == "IGNORED_INVALID", result
    assert "FEEDBACK_FINGERPRINT_MISMATCH" in result["feedback_blocks"], result


def test_feedback_cannot_weaken_approval_or_editorial_policy() -> None:
    feedback = clean_feedback()
    feedback["application_policy"]["may_weaken_approval_gates"] = True
    result = apply_observed_feedback(channel(), feedback, story(), format_result())
    assert result["status"] == "IGNORED_INVALID", result
    assert "APPROVAL_GATE_WEAKENING_FORBIDDEN" in result["feedback_blocks"], result


def test_raw_reaction_or_cross_channel_optimization_is_rejected() -> None:
    feedback = clean_feedback()
    feedback["baseline"]["reaction_count_used"] = True
    feedback["baseline"]["cross_channel_normalization"] = True
    result = apply_observed_feedback(channel(), feedback, story(), format_result())
    assert result["status"] == "IGNORED_INVALID", result
    assert "REACTION_COUNT_OPTIMIZATION_FORBIDDEN" in result["feedback_blocks"], result
    assert "CROSS_CHANNEL_NORMALIZATION_FORBIDDEN" in result["feedback_blocks"], result


def test_secret_like_fields_are_rejected() -> None:
    feedback = clean_feedback()
    feedback["access_token"] = "never"
    result = apply_observed_feedback(channel(), feedback, story(), format_result())
    assert result["status"] == "IGNORED_INVALID", result
    assert "SECRET_LIKE_FIELD_PRESENT" in result["feedback_blocks"], result


def test_predictive_fields_are_rejected() -> None:
    feedback = clean_feedback()
    feedback["predicted_views"] = 999999
    result = apply_observed_feedback(channel(), feedback, story(), format_result())
    assert result["status"] == "IGNORED_INVALID", result
    assert "PREDICTIVE_OR_ESTIMATED_ANALYTICS_PRESENT" in result["feedback_blocks"], result


def test_rejected_observations_or_provenance_conflicts_are_not_learnable() -> None:
    for key, value, block in (
        ("rejected_observations", [{"index": 0, "hard_blocks": ["BAD"]}], "FEEDBACK_CONTAINS_REJECTED_OBSERVATIONS"),
        ("provenance_conflicts", [{"a": "b"}], "FEEDBACK_PROVENANCE_CONFLICTS"),
    ):
        feedback = clean_feedback()
        feedback[key] = value
        result = apply_observed_feedback(channel(), feedback, story(), format_result())
        assert result["status"] == "IGNORED_INVALID", result
        assert block in result["feedback_blocks"], result


def test_valid_feedback_adjusts_virality_score_and_rank_action_only() -> None:
    base = virality(71.0)
    result = apply_to_virality(
        channel(), clean_feedback(), story(), format_result(), base, cadence=cadence(), series=series()
    )
    adjustment = result["observed_feedback"]["bounded_adjustment_points"]
    assert result["score"] == round(min(100.0, max(0.0, 71.0 + adjustment)), 2), result
    assert result["analytics"]["observed_metrics_used"] is True, result
    assert result["publication_action"] == "PRIORITIZE", result
    assert result["blocked"] is False, result


def test_invalid_feedback_leaves_virality_decision_unblocked_and_score_unchanged() -> None:
    feedback = clean_feedback()
    feedback["platform"] = "instagram"
    base = virality(71.0)
    result = apply_to_virality(channel(), feedback, story(), format_result(), base, cadence=cadence(), series=series())
    assert result["score"] == 71.0, result
    assert result["blocked"] is False, result
    assert result["publication_action"] == "ELIGIBLE", result
    assert result["observed_feedback"]["status"] == "IGNORED_INVALID", result
    assert result["analytics"]["observed_metrics_used"] is False, result


def test_learning_can_never_override_existing_hard_block() -> None:
    result = apply_to_virality(
        channel(), clean_feedback(), story(), format_result(), virality(71.0, blocked=True), cadence=cadence(), series=series()
    )
    assert result["blocked"] is True, result
    assert "HOOK_CLICKBAIT_GUARD" in result["hard_blocks"], result
    assert result["publication_action"] == "BLOCKED", result
    assert result["guards"]["editorial_gates_weakened"] is False, result


def test_outbox_and_timing_gates_are_not_promoted_by_learning() -> None:
    outbox_channel = channel(status="outbox_only")
    outbox_feedback = clean_feedback()
    outbox = apply_to_virality(outbox_channel, outbox_feedback, story(), format_result(), virality(71.0), cadence=cadence(), series=series())
    assert outbox["publication_action"] == "OUTBOX_ONLY", outbox
    held = apply_to_virality(channel(), clean_feedback(), story(), format_result(), virality(71.0), cadence=cadence(eligible=False), series=series())
    assert held["publication_action"] == "HOLD_TIMING", held


def test_deterministic_application_and_fingerprint() -> None:
    args = (channel(), clean_feedback(), story(), format_result(), virality(71.0))
    first = apply_to_virality(*args, cadence=cadence(), series=series())
    second = apply_to_virality(*copy.deepcopy(args), cadence=copy.deepcopy(cadence()), series=copy.deepcopy(series()))
    assert first == second, (first, second)
    assert len(first["decision_fingerprint_sha256"]) == 64, first
    assert first["observed_feedback"]["guards"]["zero_paid_dependency"] is True, first


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS observed feedback application acceptance suite ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
