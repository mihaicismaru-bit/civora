#!/usr/bin/env python3
"""Acceptance tests for the dependency-free LOCAL NEWS OS channel fit scorer."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("channel_fit", HERE / "channel_fit.py")
assert SPEC and SPEC.loader
channel_fit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(channel_fit)
score_story = channel_fit.score_story


def channel(platform: str, priorities: list[str], formats: list[str], exclusions: list[str] | None = None) -> dict:
    return {
        "channel_id": f"test-{platform}",
        "instance_id": "alpha",
        "platform": platform,
        "status": "active",
        "editorial_mix": {
            "priorities": priorities,
            "exclusions": exclusions or ["rage_bait", "fake_urgency", "unverified_accusations"],
        },
        "native_formats": formats,
        "approval_gates": {
            "low_risk_auto": True,
            "reputational_human": True,
            "corrections_priority": True,
        },
    }


def story(**overrides) -> dict:
    value = {
        "story_id": "story-1",
        "instance_id": "alpha",
        "topics": ["service_journalism", "local_events"],
        "risk_flags": [],
        "available_formats": ["text", "single_photo"],
        "confidence": 96,
        "locality": 1.0,
        "utility": 0.9,
        "share_value": 0.75,
        "urgency": 0.6,
        "material_fact_gate": "PASS",
    }
    value.update(overrides)
    return value


def test_high_fit() -> None:
    cfg = channel("facebook", ["service_journalism", "local_events", "public_money"], ["text", "single_photo"])
    result = score_story(story(), cfg)
    assert not result["blocked"], result
    assert result["score"] >= 70, result
    assert result["recommendation"] == "primary", result
    assert "service_journalism" in result["matched_topics"], result
    assert "text" in result["matched_formats"], result


def test_native_format_matters() -> None:
    cfg = channel("instagram", ["local_events", "service_journalism"], ["single_photo", "carousel"])
    with_photo = score_story(story(available_formats=["single_photo"]), cfg)
    text_only = score_story(story(available_formats=["text"]), cfg)
    assert with_photo["components"]["native_format_ready"] == 15.0, with_photo
    assert text_only["components"]["native_format_ready"] == 0.0, text_only
    assert with_photo["score"] > text_only["score"], (with_photo, text_only)


def test_channel_exclusion_blocks() -> None:
    cfg = channel("tiktok", ["local_events"], ["short"], ["rage_bait", "unconsented_direct_post"])
    result = score_story(story(risk_flags=["unconsented_direct_post"], available_formats=["short"]), cfg)
    assert result["blocked"], result
    assert result["recommendation"] == "blocked", result
    assert any(item.startswith("CHANNEL_EXCLUSION") for item in result["hard_blocks"]), result


def test_instance_isolation_blocks() -> None:
    cfg = channel("facebook", ["service_journalism"], ["text"])
    result = score_story(story(instance_id="beta"), cfg)
    assert result["blocked"], result
    assert "INSTANCE_MISMATCH" in result["hard_blocks"], result


def test_material_gate_blocks() -> None:
    cfg = channel("facebook", ["service_journalism"], ["text"])
    result = score_story(story(material_fact_gate="HOLD_REVIEW"), cfg)
    assert result["blocked"], result
    assert "MATERIAL_FACT_GATE" in result["hard_blocks"], result


def test_reputational_requires_human_approval() -> None:
    cfg = channel("facebook", ["public_money"], ["text"])
    result = score_story(
        story(topics=["public_money"], risk_flags=["reputational"], human_approved=False),
        cfg,
    )
    assert result["blocked"], result
    assert "HUMAN_APPROVAL_REQUIRED" in result["hard_blocks"], result
    approved = score_story(
        story(topics=["public_money"], risk_flags=["reputational"], human_approved=True),
        cfg,
    )
    assert not approved["blocked"], approved


def test_priority_rank_is_auditable() -> None:
    cfg = channel("facebook", ["service_journalism", "local_events", "public_money"], ["text"])
    first = score_story(story(topics=["service_journalism"], available_formats=["text"]), cfg)
    last = score_story(story(topics=["public_money"], available_formats=["text"]), cfg)
    assert first["components"]["topic_alignment"] > last["components"]["topic_alignment"], (first, last)


def test_correction_priority_is_reason_not_fake_score() -> None:
    cfg = channel("facebook", ["service_journalism"], ["text"])
    normal = score_story(story(available_formats=["text"], correction=False), cfg)
    correction = score_story(story(available_formats=["text"], correction=True), cfg)
    assert normal["score"] == correction["score"], (normal, correction)
    assert "CORRECTION_PRIORITY" in correction["reasons"], correction


def main() -> int:
    tests = [
        test_high_fit,
        test_native_format_matters,
        test_channel_exclusion_blocks,
        test_instance_isolation_blocks,
        test_material_gate_blocks,
        test_reputational_requires_human_approval,
        test_priority_rank_is_auditable,
        test_correction_priority_is_reason_not_fake_score,
    ]
    for test in tests:
        test()
    print(f"CHANNEL_FIT_TESTS_PASS count={len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
