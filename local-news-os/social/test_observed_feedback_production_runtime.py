#!/usr/bin/env python3
"""Production-runtime integration tests for bounded observed feedback."""
from __future__ import annotations

import copy

import observed_metrics
import production_runtime
import test_production_runtime as runtime_fixture


def _observation(channel: dict, idx: int, *, topic: str, native_format: str, published_at: str, end_at: str, observed_at: str, actions: int) -> dict:
    source = channel["metrics"]["sources"][0]
    return {
        "schema_version": "1.0",
        "instance_id": channel["instance_id"],
        "channel_id": channel["channel_id"],
        "platform": channel["platform"],
        "publication_id": f"runtime-feedback-publication:{idx}",
        "remote_publication_id": f"remote-runtime-feedback-{idx}",
        "story_id": f"historical-story-{idx}",
        "product_id": f"historical-product-{idx}",
        "source": source,
        "observed_at": observed_at,
        "window": {"kind": "cumulative", "start_at": published_at, "end_at": end_at},
        "publication_context": {
            "status": "PUBLISHED",
            "published_at": published_at,
            "native_format": native_format,
            "topic_keys": [topic],
            "series_id": None,
        },
        "metrics": {
            "reach": 1000,
            "reactions": 999999 if actions > 10 else 1,
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


def _feedback(channel: dict) -> dict:
    observations = []
    for idx in range(1, 4):
        observations.append(_observation(
            channel,
            idx,
            topic="service_journalism",
            native_format="single_photo",
            published_at="2026-08-15T09:00:00Z",
            end_at="2026-08-15T10:00:00Z",
            observed_at="2026-08-15T10:05:00Z",
            actions=30,
        ))
    for idx in range(4, 7):
        observations.append(_observation(
            channel,
            idx,
            topic="public_money",
            native_format="text",
            published_at="2026-08-15T12:00:00Z",
            end_at="2026-08-15T13:00:00Z",
            observed_at="2026-08-15T13:05:00Z",
            actions=1,
        ))
    return observed_metrics.build_feedback(channel, observations, min_samples=3)


def _run(feedback: dict | None) -> dict:
    channel = runtime_fixture._load_channel("facebook")
    story = runtime_fixture._story()
    return production_runtime.orchestrate_channel(
        copy.deepcopy(story),
        copy.deepcopy(channel),
        runtime_fixture._inventory(story["story_id"]),
        runtime_fixture._history(channel),
        now=runtime_fixture.READY_NOW,
        human_approved=True,
        canonical_url=runtime_fixture.CANONICAL_URL,
        observed_feedback=copy.deepcopy(feedback) if feedback is not None else None,
    )


def test_absent_feedback_preserves_existing_runtime_behavior() -> None:
    baseline = runtime_fixture._run("facebook")
    candidate = _run(None)
    assert candidate == baseline, (candidate, baseline)


def test_valid_observed_feedback_changes_only_bounded_virality_rank() -> None:
    channel = runtime_fixture._load_channel("facebook")
    baseline = _run(None)
    adjusted = _run(_feedback(channel))
    assert not adjusted["blocked"], adjusted
    assert adjusted["disposition"] == baseline["disposition"] == "READY", (adjusted, baseline)
    assert adjusted["artifacts"]["format"]["product"]["product_id"] == baseline["artifacts"]["format"]["product"]["product_id"], adjusted
    delta = adjusted["artifacts"]["virality"]["score"] - baseline["artifacts"]["virality"]["score"]
    assert 0.0 < delta <= 5.0, adjusted
    assert adjusted["artifacts"]["observed_feedback"]["status"] == "APPLIED", adjusted
    assert adjusted["artifacts"]["virality"]["analytics"]["observed_metrics_used"] is True, adjusted
    assert adjusted["guards"]["editorial_gates_weakened"] is False, adjusted
    assert adjusted["guards"]["predictive_analytics_used"] is False, adjusted
    assert adjusted["guards"]["zero_paid_dependency"] is True, adjusted


def test_invalid_feedback_is_audited_but_does_not_churn_publication_decision() -> None:
    channel = runtime_fixture._load_channel("facebook")
    feedback = _feedback(channel)
    feedback["platform"] = "instagram"
    baseline = _run(None)
    candidate = _run(feedback)
    assert not candidate["blocked"], candidate
    assert candidate["artifacts"]["virality"] == baseline["artifacts"]["virality"], candidate
    assert candidate["artifacts"]["publication"]["record"] == baseline["artifacts"]["publication"]["record"], candidate
    assert candidate["artifacts"]["observed_feedback"]["status"] == "IGNORED_INVALID", candidate
    stage = next(row for row in candidate["stages"] if row["name"] == "observed_feedback")
    assert stage["status"] == "IGNORED", candidate


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS observed feedback production runtime integration ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
