#!/usr/bin/env python3
"""Acceptance tests for the dependency-free cadence/fatigue gate."""
from __future__ import annotations

import copy
import importlib.util
import pathlib
import sys

MODULE_PATH = pathlib.Path(__file__).with_name("cadence_fatigue.py")
spec = importlib.util.spec_from_file_location("cadence_fatigue", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)
evaluate_cadence = module.evaluate_cadence


def channel() -> dict:
    return {
        "schema_version": "1.0",
        "channel_id": "valcea-facebook",
        "instance_id": "valcea",
        "platform": "facebook",
        "status": "active",
        "cadence": {
            "timezone": "Europe/Bucharest",
            "max_posts_per_day": 5,
            "min_spacing_minutes": 30,
            "quiet_hours": {"start": "23:00", "end": "06:00", "breaking_override": True},
        },
        "fatigue": {"same_story_cooldown_hours": 6, "max_related_posts_24h": 2},
        "approval_gates": {
            "low_risk_auto": True,
            "reputational_human": True,
            "corrections_priority": True,
        },
    }


def candidate() -> dict:
    return {
        "instance_id": "valcea",
        "channel_id": "valcea-facebook",
        "story_id": "story-a",
        "related_group_id": "mobility",
        "topic_ids": ["transport", "ramnicu-valcea"],
        "publication_class": "normal",
    }


def history(records: list[dict] | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "instance_id": "valcea",
        "channel_id": "valcea-facebook",
        "records": records or [],
    }


def record(
    published_at: str,
    *,
    story_id: str = "other-story",
    related_group_id: str = "other-group",
    topic_ids: list[str] | None = None,
    status: str = "published",
) -> dict:
    return {
        "publication_id": f"p-{published_at}-{story_id}",
        "published_at": published_at,
        "status": status,
        "story_id": story_id,
        "related_group_id": related_group_id,
        "topic_ids": topic_ids or [],
    }


def test_normal_candidate_is_eligible() -> None:
    result = evaluate_cadence(candidate(), channel(), history(), now="2026-08-15T12:00:00Z")
    assert result["eligible"] is True
    assert result["decision"] == "PUBLISH_NOW"
    assert result["cadence_blocks"] == []


def test_quiet_hours_hold_cross_midnight() -> None:
    # 00:30 UTC = 03:30 Europe/Bucharest in August.
    result = evaluate_cadence(candidate(), channel(), history(), now="2026-08-15T00:30:00Z")
    assert result["eligible"] is False
    assert "QUIET_HOURS" in result["cadence_blocks"]
    assert result["next_eligible_at"] == "2026-08-15T03:00:00Z"


def test_breaking_may_override_quiet_only_when_configured() -> None:
    c = candidate()
    c["publication_class"] = "breaking"
    result = evaluate_cadence(c, channel(), history(), now="2026-08-15T00:30:00Z")
    assert result["eligible"] is True
    assert "BREAKING_OVERRIDES_QUIET_HOURS" in result["overrides"]

    cfg = channel()
    cfg["cadence"]["quiet_hours"]["breaking_override"] = False
    blocked = evaluate_cadence(c, cfg, history(), now="2026-08-15T00:30:00Z")
    assert blocked["eligible"] is False
    assert "QUIET_HOURS" in blocked["cadence_blocks"]


def test_breaking_does_not_bypass_spacing() -> None:
    c = candidate()
    c["publication_class"] = "breaking"
    h = history([record("2026-08-15T11:50:00Z")])
    result = evaluate_cadence(c, channel(), h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "MIN_SPACING" in result["cadence_blocks"]
    assert "BREAKING_OVERRIDES_QUIET_HOURS" not in result["overrides"]


def test_daily_cap_uses_channel_local_date() -> None:
    cfg = channel()
    cfg["cadence"]["max_posts_per_day"] = 2
    h = history([
        record("2026-08-14T22:10:00Z", story_id="x"),  # 15 Aug 01:10 local
        record("2026-08-15T06:00:00Z", story_id="y"),  # 15 Aug 09:00 local
    ])
    result = evaluate_cadence(candidate(), cfg, h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "DAILY_CAP_REACHED" in result["cadence_blocks"]
    assert result["counters"]["published_today"] == 2


def test_min_spacing_produces_exact_next_time() -> None:
    h = history([record("2026-08-15T11:45:00Z")])
    result = evaluate_cadence(candidate(), channel(), h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert result["next_eligible_at"] == "2026-08-15T12:15:00Z"


def test_same_story_cooldown_is_independent() -> None:
    cfg = channel()
    cfg["cadence"]["min_spacing_minutes"] = 0
    h = history([record("2026-08-15T08:00:00Z", story_id="story-a")])
    result = evaluate_cadence(candidate(), cfg, h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "SAME_STORY_COOLDOWN" in result["cadence_blocks"]
    assert result["next_eligible_at"] == "2026-08-15T14:00:00Z"


def test_related_group_fatigue_caps_repetition() -> None:
    cfg = channel()
    cfg["cadence"]["min_spacing_minutes"] = 0
    h = history([
        record("2026-08-14T13:00:00Z", story_id="x", related_group_id="mobility"),
        record("2026-08-15T08:00:00Z", story_id="y", related_group_id="mobility"),
    ])
    result = evaluate_cadence(candidate(), cfg, h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "RELATED_TOPIC_FATIGUE" in result["cadence_blocks"]
    assert result["counters"]["related_last_24h"] == 2
    assert result["next_eligible_at"] == "2026-08-15T13:00:00Z"


def test_topic_overlap_counts_as_related_without_group() -> None:
    cfg = channel()
    cfg["cadence"]["min_spacing_minutes"] = 0
    cfg["fatigue"]["max_related_posts_24h"] = 1
    c = candidate()
    c["related_group_id"] = ""
    h = history([
        record(
            "2026-08-15T08:00:00Z",
            story_id="topic-peer",
            related_group_id="",
            topic_ids=["transport"],
        )
    ])
    result = evaluate_cadence(c, cfg, h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "RELATED_TOPIC_FATIGUE" in result["cadence_blocks"]


def test_unrelated_posts_do_not_trigger_related_fatigue() -> None:
    cfg = channel()
    cfg["cadence"]["min_spacing_minutes"] = 0
    h = history([
        record("2026-08-15T07:00:00Z", story_id="x", related_group_id="culture"),
        record("2026-08-15T08:00:00Z", story_id="y", related_group_id="sport"),
    ])
    result = evaluate_cadence(candidate(), cfg, h, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is True


def test_explicit_correction_bypasses_cadence_and_fatigue() -> None:
    cfg = channel()
    cfg["cadence"]["max_posts_per_day"] = 1
    c = candidate()
    c["publication_class"] = "correction"
    c["correction_of"] = "publication-123"
    h = history([
        record("2026-08-15T00:20:00Z", story_id="story-a", related_group_id="mobility")
    ])
    result = evaluate_cadence(c, cfg, h, now="2026-08-15T00:30:00Z")
    assert result["eligible"] is True
    assert result["decision"] == "PUBLISH_CORRECTION_PRIORITY"
    assert len(result["overrides"]) == 5


def test_fake_correction_without_target_gets_no_override() -> None:
    c = candidate()
    c["publication_class"] = "correction"
    result = evaluate_cadence(c, channel(), history(), now="2026-08-15T00:30:00Z")
    assert result["eligible"] is False
    assert "QUIET_HOURS" in result["cadence_blocks"]
    assert result["overrides"] == []


def test_instance_and_channel_isolation_fail_closed() -> None:
    bad_history = history()
    bad_history["instance_id"] = "other-city"
    result = evaluate_cadence(candidate(), channel(), bad_history, now="2026-08-15T12:00:00Z")
    assert result["eligible"] is False
    assert "INSTANCE_MISMATCH" in result["hard_blocks"]

    bad_candidate = candidate()
    bad_candidate["channel_id"] = "valcea-instagram"
    result2 = evaluate_cadence(bad_candidate, channel(), history(), now="2026-08-15T12:00:00Z")
    assert result2["eligible"] is False
    assert "CHANNEL_MISMATCH" in result2["hard_blocks"]


def test_deterministic_same_inputs_same_fingerprint() -> None:
    c, cfg, h = candidate(), channel(), history()
    first = evaluate_cadence(copy.deepcopy(c), copy.deepcopy(cfg), copy.deepcopy(h), now="2026-08-15T12:00:00Z")
    second = evaluate_cadence(copy.deepcopy(c), copy.deepcopy(cfg), copy.deepcopy(h), now="2026-08-15T12:00:00Z")
    assert first == second
    assert len(first["decision_fingerprint_sha256"]) == 64


def run() -> None:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    failures: list[str] = []
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:  # noqa: BLE001 - tiny dependency-free harness
            failures.append(f"{test.__name__}: {exc}")
            print(f"FAIL {test.__name__}: {exc}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"Cadence/Fatigue acceptance: PASS ({len(tests)} tests)")


if __name__ == "__main__":
    run()
