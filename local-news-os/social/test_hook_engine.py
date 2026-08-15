#!/usr/bin/env python3
"""Acceptance tests for the dependency-free LOCAL NEWS OS Hook Engine."""
from __future__ import annotations

import copy

from content_atomizer import atomize_story
from hook_engine import build_hook


def story() -> dict:
    return {
        "instance_id": "valcea",
        "story_id": "story-hook-1",
        "material_fact_gate": "PASS",
        "headline": "Primăria publică programul pentru weekend",
        "dek": "Programul include două evenimente cu acces liber.",
        "paragraphs": ["Primul eveniment începe sâmbătă la ora 18:00."],
        "facts": [{"fact_id": "f1", "text": "Accesul este liber."}],
        "quotes": [{"quote_id": "q1", "text": "Programul rămâne neschimbat."}],
        "topics": ["service_journalism", "local_events"],
        "risk_flags": [],
    }


def channel(platform: str = "facebook") -> dict:
    return {
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "platform": platform,
        "status": "active",
        "editorial_mix": {"priorities": ["service_journalism"], "exclusions": ["rage_bait", "fake_urgency"]},
    }


def fit(platform: str = "facebook", recommendation: str = "primary") -> dict:
    return {
        "story_id": "story-hook-1",
        "channel_id": f"valcea-{platform}",
        "instance_id": "valcea",
        "blocked": False,
        "recommendation": recommendation,
    }


def atoms(source: dict | None = None) -> dict:
    return atomize_story(source or story())


def test_facebook_uses_neutral_frame_and_exact_source() -> None:
    result = build_hook(atoms(), channel("facebook"), fit("facebook"))
    assert result["blocked"] is False
    hook = result["hook"]
    assert hook["text"] == "Pe scurt — Primăria publică programul pentru weekend"
    assert hook["source_text"] == story()["headline"]
    assert hook["generated_frame"] == "Pe scurt — "
    assert hook["invented_claims_allowed"] is False


def test_platform_profiles_are_native_not_verbatim_crosspost() -> None:
    facebook = build_hook(atoms(), channel("facebook"), fit("facebook"))["hook"]["text"]
    instagram = build_hook(atoms(), channel("instagram"), fit("instagram"))["hook"]["text"]
    tiktok = build_hook(atoms(), channel("tiktok"), fit("tiktok"))["hook"]["text"]
    assert facebook != instagram
    assert instagram != tiktok
    assert tiktok == story()["headline"]


def test_clickbait_headline_falls_back_to_safe_dek() -> None:
    source = story()
    source["headline"] = "ȘOCANT: nu o să crezi ce se întâmplă în weekend!!"
    result = build_hook(atoms(source), channel("facebook"))
    assert result["blocked"] is False
    assert result["hook"]["source_atom_type"] == "dek"
    assert result["hook"]["source_text"] == source["dek"]
    assert any("CLICKBAIT_PHRASE" in item["reasons"] for item in result["rejected_candidates"])


def test_all_unsafe_text_fails_closed() -> None:
    source = story()
    source["headline"] = "ȘOCANT: nu o să crezi!!"
    source["dek"] = "Senzațional: trebuie să vezi!!"
    source["paragraphs"] = ["Nu rata: toată lumea vorbește despre asta!!"]
    source["facts"] = []
    source["quotes"] = []
    result = build_hook(atoms(source), channel("facebook"))
    assert result["blocked"] is True
    assert "NO_SAFE_HOOK_ATOM" in result["hard_blocks"]
    assert result["hook"] is None


def test_all_caps_headline_is_not_amplified() -> None:
    source = story()
    source["headline"] = "DEPISTAT DE POLIȚIȘTII SERVICIULUI RUTIER"
    result = build_hook(atoms(source), channel("facebook"))
    assert result["hook"]["source_atom_type"] == "dek"
    assert any("EXCESSIVE_ALL_CAPS" in item["reasons"] for item in result["rejected_candidates"])


def test_correction_gets_explicit_neutral_priority_frame() -> None:
    source = story()
    source["correction"] = True
    result = build_hook(atoms(source), channel("instagram"), fit("instagram"))
    assert result["blocked"] is False
    assert result["hook"]["text"].startswith("Corecție — ")
    assert result["hook"]["strategy"] == "correction_source_atom"


def test_instance_mismatch_fails_closed() -> None:
    foreign = channel("facebook")
    foreign["instance_id"] = "cluj"
    result = build_hook(atoms(), foreign)
    assert result["blocked"] is True
    assert "INSTANCE_MISMATCH" in result["hard_blocks"]


def test_blocked_atom_bundle_fails_closed() -> None:
    source = story()
    source["material_fact_gate"] = "HOLD_REVIEW"
    result = build_hook(atoms(source), channel("facebook"))
    assert result["blocked"] is True
    assert "ATOM_BUNDLE_BLOCKED" in result["hard_blocks"]


def test_channel_fit_skip_is_respected() -> None:
    result = build_hook(atoms(), channel("facebook"), fit("facebook", "skip"))
    assert result["blocked"] is True
    assert "CHANNEL_FIT_SKIP" in result["hard_blocks"]


def test_long_preferred_atom_falls_back_without_truncation() -> None:
    source = story()
    source["headline"] = ("Program local confirmat pentru weekend și pentru toate zonele municipiului. " * 7).strip()
    source["dek"] = "Program confirmat pentru weekend."
    result = build_hook(atoms(source), channel("facebook"))
    assert result["blocked"] is False
    assert result["hook"]["source_text"] == source["dek"]
    assert "…" not in result["hook"]["text"]
    assert any("HOOK_TOO_LONG" in item["reasons"] for item in result["rejected_candidates"])


def test_deterministic_output() -> None:
    bundle = atoms()
    first = build_hook(bundle, channel("facebook"), fit("facebook"))
    second = build_hook(copy.deepcopy(bundle), copy.deepcopy(channel("facebook")), copy.deepcopy(fit("facebook")))
    assert first == second


def test_unknown_poison_field_cannot_enter_hook() -> None:
    bundle = atoms()
    bundle["raw_story"] = "URGENT! Invented claim 999999"
    result = build_hook(bundle, channel("facebook"))
    assert "999999" not in str(result["hook"])
    assert result["hook"]["source_atom_id"]


def main() -> int:
    tests = [
        test_facebook_uses_neutral_frame_and_exact_source,
        test_platform_profiles_are_native_not_verbatim_crosspost,
        test_clickbait_headline_falls_back_to_safe_dek,
        test_all_unsafe_text_fails_closed,
        test_all_caps_headline_is_not_amplified,
        test_correction_gets_explicit_neutral_priority_frame,
        test_instance_mismatch_fails_closed,
        test_blocked_atom_bundle_fails_closed,
        test_channel_fit_skip_is_respected,
        test_long_preferred_atom_falls_back_without_truncation,
        test_deterministic_output,
        test_unknown_poison_field_cannot_enter_hook,
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"Hook Engine acceptance: PASS ({len(tests)}/{len(tests)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
