#!/usr/bin/env python3
"""Fail-closed contract tying VÂLCEA CLAR profile identity to post renderers.

The publication has one master newsroom identity. Facebook and Instagram may use
platform-native layouts, but their name, lockup, palette and profile lineage may
not drift away from the canonical brand/profile sources.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
BRAND_PATH = SOCIAL / "social_brand_system.json"
PROFILE_PATH = SOCIAL / "profile_identity_system.json"
FACEBOOK_PATH = SOCIAL / "facebook_visual_system.json"
INSTAGRAM_PATH = SOCIAL / "instagram_visual_system.json"
INSTAGRAM_RENDERER = SOCIAL / "instagram_editorial_v1_1.py"

CANONICAL_BRAND_REF = "valcea-clar/social/social_brand_system.json"
CANONICAL_PROFILE_REF = "valcea-clar/social/profile_identity_system.json"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def canonical_palette(master: dict[str, Any]) -> dict[str, list[int]]:
    palette = master.get("brand", {}).get("palette", {})
    if not isinstance(palette, dict):
        return {}
    result: dict[str, list[int]] = {}
    for key in ("accent_rgb", "paper_rgb", "ink_rgb", "white_rgb"):
        value = palette.get(key)
        if isinstance(value, list):
            result[key] = [int(v) for v in value]
    return result


def validate(
    master: dict[str, Any],
    profile: dict[str, Any],
    facebook: dict[str, Any],
    instagram: dict[str, Any],
    renderer_text: str,
) -> list[str]:
    errors: list[str] = []
    brand = master.get("brand") if isinstance(master.get("brand"), dict) else {}
    masthead = profile.get("masthead") if isinstance(profile.get("masthead"), dict) else {}
    platforms = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}
    palette = canonical_palette(master)

    if profile.get("brand_source") != CANONICAL_BRAND_REF:
        errors.append("profile:canonical_brand_lineage_missing")
    if masthead.get("wordmark") != brand.get("display_name"):
        errors.append("profile:wordmark_drift")
    if masthead.get("tagline") != brand.get("tagline"):
        errors.append("profile:tagline_drift")
    if masthead.get("domain") != brand.get("canonical_domain"):
        errors.append("profile:domain_drift")

    for platform, system in (("facebook", facebook), ("instagram", instagram)):
        prefix = f"{platform}:"
        if system.get("master_identity_system") != CANONICAL_BRAND_REF:
            errors.append(prefix + "canonical_brand_lineage_missing")
        if system.get("profile_identity_system") != CANONICAL_PROFILE_REF:
            errors.append(prefix + "canonical_profile_lineage_missing")

        system_brand = system.get("brand") if isinstance(system.get("brand"), dict) else {}
        if system_brand.get("name") != brand.get("display_name"):
            errors.append(prefix + "brand_name_drift")
        if system_brand.get("editorial_lockup") != brand.get("editorial_lockup"):
            errors.append(prefix + "editorial_lockup_drift")
        for key, expected in palette.items():
            if system_brand.get(key) != expected:
                errors.append(prefix + f"{key}_drift")

        qa = system.get("qa") if isinstance(system.get("qa"), dict) else {}
        for key in (
            "profile_and_post_identity_must_match",
            "must_not_look_like_local_marketing_page",
            "must_not_look_ai_generated",
            "must_not_repeat_identical_layout_for_every_story",
        ):
            if qa.get(key) is not True:
                errors.append(prefix + f"qa_not_enabled:{key}")

        profile_cfg = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        if profile_cfg.get("channel_id") != system.get("channel_id"):
            errors.append(prefix + "channel_id_drift")
        if profile_cfg.get("display_name") != system_brand.get("name"):
            errors.append(prefix + "profile_display_name_drift")

        canvas = system.get("canvas") if isinstance(system.get("canvas"), dict) else {}
        width = int(canvas.get("width") or 0)
        height = int(canvas.get("height") or 0)
        if width <= 0 or height <= 0 or canvas.get("aspect_ratio") != "4:5":
            errors.append(prefix + "invalid_feed_canvas")
        elif width * 5 != height * 4:
            errors.append(prefix + "feed_canvas_ratio_drift")

    master_gate = master.get("quality_gate") if isinstance(master.get("quality_gate"), dict) else {}
    profile_gate = profile.get("quality_gate") if isinstance(profile.get("quality_gate"), dict) else {}
    if master_gate.get("profile_and_post_identity_must_match") is not True:
        errors.append("master:profile_post_identity_gate_disabled")
    if profile_gate.get("profile_assets_must_be_deterministic") is not True:
        errors.append("profile:deterministic_assets_gate_disabled")

    # The production Instagram carousel renderer must use the visual-system
    # palette rather than silently forking a second palette in Python constants.
    required_renderer_tokens = (
        'paper = tuple(brand["paper_rgb"])',
        'ink = tuple(brand["ink_rgb"])',
        'Image.new("RGB", canvas, paper)',
    )
    for token in required_renderer_tokens:
        if token not in renderer_text:
            errors.append("instagram:renderer_not_bound_to_palette:" + token)
    if 'Image.new("RGB", canvas, (247, 246, 243))' in renderer_text:
        errors.append("instagram:hardcoded_canonical_paper_forbidden")

    return errors


def self_test() -> int:
    master = {
        "brand": {
            "display_name": "VÂLCEA CLAR",
            "editorial_lockup": "VÂLCEA. CLAR.",
            "tagline": "Ce se întâmplă. Ce știm. Ce contează.",
            "canonical_domain": "valceaclar.ro",
            "palette": {
                "accent_rgb": [196, 27, 35],
                "paper_rgb": [247, 246, 243],
                "ink_rgb": [20, 20, 20],
                "white_rgb": [255, 255, 255],
            },
        },
        "quality_gate": {"profile_and_post_identity_must_match": True},
    }
    profile = {
        "brand_source": CANONICAL_BRAND_REF,
        "masthead": {
            "wordmark": "VÂLCEA CLAR",
            "tagline": "Ce se întâmplă. Ce știm. Ce contează.",
            "domain": "valceaclar.ro",
        },
        "platforms": {
            "facebook": {"channel_id": "valcea-facebook", "display_name": "VÂLCEA CLAR"},
            "instagram": {"channel_id": "valcea-instagram", "display_name": "VÂLCEA CLAR"},
        },
        "quality_gate": {"profile_assets_must_be_deterministic": True},
    }
    common = {
        "master_identity_system": CANONICAL_BRAND_REF,
        "profile_identity_system": CANONICAL_PROFILE_REF,
        "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "brand": {
            "name": "VÂLCEA CLAR",
            "editorial_lockup": "VÂLCEA. CLAR.",
            "accent_rgb": [196, 27, 35],
            "paper_rgb": [247, 246, 243],
            "ink_rgb": [20, 20, 20],
            "white_rgb": [255, 255, 255],
        },
        "qa": {
            "profile_and_post_identity_must_match": True,
            "must_not_look_like_local_marketing_page": True,
            "must_not_look_ai_generated": True,
            "must_not_repeat_identical_layout_for_every_story": True,
        },
    }
    facebook = {**common, "channel_id": "valcea-facebook"}
    instagram = {**common, "channel_id": "valcea-instagram"}
    renderer = 'paper = tuple(brand["paper_rgb"])\nink = tuple(brand["ink_rgb"])\nImage.new("RGB", canvas, paper)\n'
    assert validate(master, profile, facebook, instagram, renderer) == []
    instagram["brand"] = {**instagram["brand"], "accent_rgb": [255, 0, 0]}
    assert "instagram:accent_rgb_drift" in validate(master, profile, facebook, instagram, renderer)
    print("VÂLCEA CLAR visual identity contract self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    errors = validate(
        load(BRAND_PATH),
        load(PROFILE_PATH),
        load(FACEBOOK_PATH),
        load(INSTAGRAM_PATH),
        INSTAGRAM_RENDERER.read_text(encoding="utf-8"),
    )
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("VÂLCEA CLAR visual identity contract: PASS (profile ↔ Facebook ↔ Instagram)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
