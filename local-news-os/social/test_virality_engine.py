#!/usr/bin/env python3
"""Acceptance tests for the LOCAL NEWS OS deterministic Virality Engine."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("virality_engine", HERE / "virality_engine.py")
assert SPEC and SPEC.loader
virality_engine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(virality_engine)
score_virality = virality_engine.score_virality


def channel(**overrides) -> dict:
    value = {
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "status": "active",
        "editorial_mix": {
            "priorities": ["service_journalism", "local_events"],
            "exclusions": ["rage_bait", "fake_urgency", "fake_exclusivity", "verbatim_cross_posting"],
        },
    }
    value.update(overrides)
    return value


def story(**overrides) -> dict:
    value = {
        "story_id": "story-1",
        "instance_id": "alpha",
        "material_fact_gate": "PASS",
        "risk_flags": [],
        "locality": 1.0,
        "utility": 0.95,
        "share_value": 0.90,
        "save_value": 0.85,
        "conversation_value": 0.80,
        "lifecycle_stage": "baseline",
    }
    value.update(overrides)
    return value


def fit(**overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "story_id": "story-1",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "score": 90.0,
        "recommendation": "primary",
        "blocked": False,
        "hard_blocks": [],
    }
    value.update(overrides)
    return value


def hook(**overrides) -> dict:
    payload = {
        "hook_id": "hook-1",
        "text": "Pe scurt — Se redeschide drumul local.",
        "source_atom_id": "atom-1",
        "source_atom_type": "headline",
        "source_preserving": True,
        "clickbait_guard": "PASS",
        "invented_claims_allowed": False,
    }
    payload.update(overrides.pop("hook_payload", {}))
    value = {
        "schema_version": "1.0",
        "story_id": "story-1",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "blocked": False,
        "hard_blocks": [],
        "hook": payload,
    }
    value.update(overrides)
    return value


def format_result(*, media_required: bool = False, **overrides) -> dict:
    product = {
        "product_id": "social-product-1",
        "native_format": "single_photo" if media_required else "text",
        "format_status": "FORMAT_READY",
        "cross_post_policy": "NATIVE_PRODUCT_ONLY",
        "verbatim_cross_platform_reuse_allowed": False,
        "invented_claims_allowed": False,
        "visual_requirement": {
            "required": media_required,
            "minimum_assets": 1 if media_required else 0,
            "binding_status": "PENDING_VISUAL_ROUTER" if media_required else "NOT_REQUIRED",
        },
    }
    value = {
        "schema_version": "1.0",
        "story_id": "story-1",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "blocked": False,
        "hard_blocks": [],
        "product": product,
    }
    value.update(overrides)
    return value


def cadence(*, eligible: bool = True, **overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "story_id": "story-1",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "eligible": eligible,
        "decision": "PUBLISH_NOW" if eligible else "HOLD_CADENCE",
        "hard_blocks": [],
        "cadence_blocks": [] if eligible else ["QUIET_HOURS"],
    }
    value.update(overrides)
    return value


def series(*, selected: bool = True, **overrides) -> dict:
    value = {
        "schema_version": "1.0",
        "instance_id": "alpha",
        "channel_id": "alpha-facebook",
        "eligible": selected,
        "decision": "SERIES_READY" if selected else "HOLD_NO_OPEN_SLOT",
        "hard_blocks": [],
        "occurrence": {
            "series_id": "editia-de-dimineata",
            "selected_story_ids": ["story-1"] if selected else [],
        } if selected else None,
    }
    value.update(overrides)
    return value


def visual_ready() -> dict:
    return {
        "schema_version": "1.0",
        "story_id": "story-1",
        "channel_id": "alpha-facebook",
        "instance_id": "alpha",
        "platform": "facebook",
        "blocked": False,
        "hard_blocks": [],
        "binding": {
            "status": "VISUAL_READY",
            "selected_asset_ids": ["photo-1"],
            "synthetic_media_used": False,
            "provenance_complete": True,
            "reuse_rights_complete": True,
        },
    }


def run(**kwargs) -> dict:
    return score_virality(
        kwargs.pop("story_value", story()),
        kwargs.pop("channel_value", channel()),
        kwargs.pop("fit_value", fit()),
        kwargs.pop("hook_value", hook()),
        kwargs.pop("format_value", format_result()),
        visual=kwargs.pop("visual_value", None),
        cadence=kwargs.pop("cadence_value", cadence()),
        series=kwargs.pop("series_value", series()),
    )


def test_strong_native_local_story_is_prioritized() -> None:
    result = run()
    assert not result["blocked"], result
    assert result["score"] >= 85.0, result
    assert result["band"] == "strong", result
    assert result["publication_action"] == "PRIORITIZE", result
    assert result["analytics"]["predictive_analytics_used"] is False, result
    assert result["guards"]["zero_paid_dependency"] is True, result


def test_channel_fit_changes_rank_without_cross_post_copy() -> None:
    strong = run(fit_value=fit(score=95.0))
    weaker = run(fit_value=fit(score=50.0, recommendation="low_fit"))
    assert strong["components"]["channel_fit"] > weaker["components"]["channel_fit"], (strong, weaker)
    assert strong["score"] > weaker["score"], (strong, weaker)
    assert strong["cross_channel_handoff"]["verbatim_reuse_allowed"] is False, strong
    assert strong["cross_channel_handoff"]["requires_independent_hook_and_format"] is True, strong


def test_clickbait_hook_fails_closed() -> None:
    bad = hook(hook_payload={"clickbait_guard": "FAIL"})
    result = run(hook_value=bad)
    assert result["blocked"], result
    assert "HOOK_CLICKBAIT_GUARD" in result["hard_blocks"], result
    assert result["publication_action"] == "BLOCKED", result


def test_forbidden_tactic_fails_closed() -> None:
    result = run(story_value=story(risk_flags=["rage_bait"]))
    assert result["blocked"], result
    assert any(block.startswith("FORBIDDEN_TACTIC") for block in result["hard_blocks"]), result


def test_unverified_breaking_cannot_gain_urgency() -> None:
    result = run(story_value=story(lifecycle_stage="breaking", verified_breaking=False))
    assert result["blocked"], result
    assert "UNVERIFIED_BREAKING_STAGE" in result["hard_blocks"], result


def test_verified_breaking_has_explicit_lifecycle_not_fake_urgency() -> None:
    result = run(story_value=story(lifecycle_stage="breaking", verified_breaking=True))
    assert not result["blocked"], result
    assert result["lifecycle"]["action"] == "publish_or_update", result
    assert result["components"]["lifecycle"] == 4.0, result
    assert result["guards"]["fake_urgency_allowed"] is False, result


def test_visual_required_without_provenance_binding_blocks() -> None:
    missing = run(format_value=format_result(media_required=True), visual_value=None)
    assert missing["blocked"], missing
    assert "VISUAL_BINDING_REQUIRED" in missing["hard_blocks"], missing
    ready = run(format_value=format_result(media_required=True), visual_value=visual_ready())
    assert not ready["blocked"], ready


def test_cadence_hold_is_timing_hold_not_editorial_failure() -> None:
    allowed = run(cadence_value=cadence(eligible=True))
    held = run(cadence_value=cadence(eligible=False))
    assert not held["blocked"], held
    assert held["publication_action"] == "HOLD_TIMING", held
    assert allowed["components"]["timing"] == 5.0, allowed
    assert held["components"]["timing"] == 0.0, held
    assert allowed["score"] == held["score"] + 5.0, (allowed, held)


def test_recurring_series_is_bounded_bonus() -> None:
    with_series = run(series_value=series(selected=True))
    without_series = run(series_value=series(selected=False))
    assert with_series["components"]["recurring_series"] == 3.0, with_series
    assert without_series["components"]["recurring_series"] == 0.0, without_series
    assert with_series["score"] == without_series["score"] + 3.0, (with_series, without_series)


def test_follow_up_needs_material_update_for_lifecycle_bonus() -> None:
    weak = run(story_value=story(lifecycle_stage="follow_up", material_update=False))
    strong = run(story_value=story(lifecycle_stage="follow_up", material_update=True))
    assert not weak["blocked"], weak
    assert weak["components"]["lifecycle"] == 0.0, weak
    assert "FOLLOW_UP_NOT_MATERIAL" in weak["reasons"], weak
    assert strong["components"]["lifecycle"] == 4.0, strong
    assert strong["lifecycle"]["action"] == "follow_up", strong


def test_predictive_analytics_are_ignored_not_rewarded() -> None:
    base = run(story_value=story())
    injected = run(story_value=story(predicted_views=9999999, virality_probability=1.0, predicted_engagement=1.0))
    assert base["score"] == injected["score"], (base, injected)
    ignored = injected["analytics"]["ignored_predictive_fields"]
    assert "predicted_views" in ignored and "virality_probability" in ignored, injected
    assert any(reason.startswith("PREDICTIVE_ANALYTICS_IGNORED") for reason in injected["reasons"]), injected


def test_instance_and_channel_isolation_fail_closed() -> None:
    wrong_instance = run(fit_value=fit(instance_id="beta"))
    assert wrong_instance["blocked"], wrong_instance
    assert "INSTANCE_MISMATCH" in wrong_instance["hard_blocks"], wrong_instance
    wrong_channel = run(hook_value=hook(channel_id="alpha-instagram"))
    assert wrong_channel["blocked"], wrong_channel
    assert "CHANNEL_MISMATCH" in wrong_channel["hard_blocks"], wrong_channel


def test_correction_propagation_is_explicit() -> None:
    result = run(story_value=story(correction=True, lifecycle_stage="correction"))
    assert not result["blocked"], result
    assert result["lifecycle"]["action"] == "correction_propagation", result
    assert result["components"]["lifecycle"] == 4.0, result
    assert "CORRECTION_PROPAGATION_PRIORITY" in result["reasons"], result


def test_cross_channel_handoff_reatomizes_from_fact_kernel() -> None:
    result = run(story_value=story(handoff_channel_ids=["alpha-tiktok", "alpha-instagram", "alpha-tiktok"]))
    handoff = result["cross_channel_handoff"]
    assert handoff["policy"] == "RE_ATOMIZE_FROM_SHARED_FACT_KERNEL", result
    assert handoff["candidate_channel_ids"] == ["alpha-instagram", "alpha-tiktok"], result
    assert handoff["reuse_current_social_copy"] is False, result


def test_outbox_only_channel_never_claims_native_publish() -> None:
    result = run(channel_value=channel(status="outbox_only"))
    assert not result["blocked"], result
    assert result["publication_action"] == "OUTBOX_ONLY", result


def test_deterministic_fingerprint() -> None:
    first = run()
    second = run()
    assert first == second, (first, second)
    assert len(first["decision_fingerprint_sha256"]) == 64, first


def main() -> int:
    tests = [
        test_strong_native_local_story_is_prioritized,
        test_channel_fit_changes_rank_without_cross_post_copy,
        test_clickbait_hook_fails_closed,
        test_forbidden_tactic_fails_closed,
        test_unverified_breaking_cannot_gain_urgency,
        test_verified_breaking_has_explicit_lifecycle_not_fake_urgency,
        test_visual_required_without_provenance_binding_blocks,
        test_cadence_hold_is_timing_hold_not_editorial_failure,
        test_recurring_series_is_bounded_bonus,
        test_follow_up_needs_material_update_for_lifecycle_bonus,
        test_predictive_analytics_are_ignored_not_rewarded,
        test_instance_and_channel_isolation_fail_closed,
        test_correction_propagation_is_explicit,
        test_cross_channel_handoff_reatomizes_from_fact_kernel,
        test_outbox_only_channel_never_claims_native_publish,
        test_deterministic_fingerprint,
    ]
    for test in tests:
        test()
    print(f"VIRALITY_ENGINE_TESTS_PASS count={len(tests)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
