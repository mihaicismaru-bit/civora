#!/usr/bin/env python3
"""Fail-closed quality gate for the VÂLCEA CLAR premium social identity."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
BRAND_PATH = SOCIAL / "social_brand_system.json"
PROFILE_PATH = SOCIAL / "profile_identity_system.json"

VISUAL_SYSTEMS = {
    "facebook": SOCIAL / "facebook_visual_system.json",
    "instagram": SOCIAL / "instagram_visual_system.json",
    "tiktok": SOCIAL / "tiktok_visual_system.json",
    "youtube": SOCIAL / "youtube_visual_system.json",
    "linkedin": SOCIAL / "linkedin_visual_system.json",
}

IDENTITY_REFS = {
    "master_identity_system": "valcea-clar/social/social_brand_system.json",
    "profile_identity_system": "valcea-clar/social/profile_identity_system.json",
}

REQUIRED_QA = (
    "must_not_look_like_local_marketing_page",
    "must_not_look_ai_generated",
    "must_not_repeat_identical_layout_for_every_story",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def palette(brand: dict[str, Any]) -> dict[str, list[int]]:
    values = brand["brand"]["palette"]
    return {
        "ink_rgb": values["ink_rgb"],
        "paper_rgb": values["paper_rgb"],
        "accent_rgb": values["accent_rgb"],
        "white_rgb": values["white_rgb"],
    }


def validate_visual_system(
    platform: str,
    system: dict[str, Any],
    profile: dict[str, Any],
    master_palette: dict[str, list[int]],
    errors: list[str],
) -> None:
    prefix = f"{platform}:"
    platform_profile = profile["platforms"][platform]
    require(
        system.get("channel_id") == platform_profile.get("channel_id"),
        f"{prefix} channel_id must match profile identity",
        errors,
    )
    for key, expected in IDENTITY_REFS.items():
        require(system.get(key) == expected, f"{prefix} {key} drifted", errors)

    system_brand = system.get("brand")
    require(isinstance(system_brand, dict), f"{prefix} missing brand object", errors)
    if isinstance(system_brand, dict):
        for key, expected in master_palette.items():
            if key in system_brand:
                require(
                    system_brand.get(key) == expected,
                    f"{prefix} {key} must match master brand palette",
                    errors,
                )
        require(system_brand.get("name") == "VÂLCEA CLAR", f"{prefix} brand name drifted", errors)
        require(
            system_brand.get("editorial_lockup") == "VÂLCEA. CLAR.",
            f"{prefix} editorial lockup drifted",
            errors,
        )

    qa = system.get("qa")
    require(isinstance(qa, dict), f"{prefix} missing QA contract", errors)
    if isinstance(qa, dict):
        for key in REQUIRED_QA:
            require(qa.get(key) is True, f"{prefix} qa.{key} must be true", errors)

    if platform == "facebook":
        require(system.get("canvas") == {"width": 1200, "height": 1500, "aspect_ratio": "4:5"}, f"{prefix} canonical feed canvas drifted", errors)
        require(qa.get("facebook_copy_must_not_equal_instagram") is True, f"{prefix} must reject Instagram copy reuse", errors)
        require(qa.get("engagement_bait_forbidden") is True, f"{prefix} engagement bait must remain forbidden", errors)
    elif platform == "instagram":
        require(system.get("canvas") == {"width": 1080, "height": 1350, "aspect_ratio": "4:5"}, f"{prefix} canonical feed canvas drifted", errors)
        require(qa.get("naked_photo_default_forbidden") is True, f"{prefix} naked-photo default must stay forbidden", errors)
        require(qa.get("verbatim_facebook_reuse_forbidden") is True, f"{prefix} must reject Facebook copy reuse", errors)
        require(qa.get("text_must_not_cover_primary_subject") is True, f"{prefix} subject-protection rule missing", errors)
    elif platform == "tiktok":
        vertical = system.get("canvas", {}).get("vertical", {})
        require(vertical == {"width": 1080, "height": 1920, "aspect_ratio": "9:16"}, f"{prefix} vertical canvas must be 1080x1920", errors)
        require(system_brand.get("opening_bumper") == "forbidden_before_the_news", f"{prefix} news must precede branding", errors)
        require(qa.get("real_story_specific_media_required") is True, f"{prefix} story-specific media required", errors)
        require(qa.get("verbatim_cross_posting_forbidden") is True, f"{prefix} verbatim cross-posting must be forbidden", errors)
    elif platform == "youtube":
        thumbnail = system.get("canvas", {}).get("thumbnail", {})
        require(thumbnail == {"width": 1280, "height": 720, "aspect_ratio": "16:9"}, f"{prefix} thumbnail canvas drifted", errors)
        thumbs = system.get("thumbnail_system", {})
        require(thumbs.get("fake_composite_forbidden") is True, f"{prefix} fake thumbnail composites must be forbidden", errors)
        require(thumbs.get("misleading_expression_or_crop_forbidden") is True, f"{prefix} misleading thumbnail crops must be forbidden", errors)
        require(qa.get("thumbnail_must_match_video") is True, f"{prefix} thumbnail/video truthfulness gate missing", errors)
        require(qa.get("verbatim_cross_posting_forbidden") is True, f"{prefix} verbatim cross-posting must be forbidden", errors)
    elif platform == "linkedin":
        require(system_brand.get("design_tone") == "newsroom_analysis_not_corporate_marketing", f"{prefix} design tone must remain newsroom-first", errors)
        typography = system.get("typography", {})
        require(typography.get("source_label_required_on_data_or_document_cards") is True, f"{prefix} source label required", errors)
        require(qa.get("source_label_required_for_numbers") is True, f"{prefix} numeric cards require sources", errors)
        require(qa.get("must_not_look_like_corporate_marketing") is True, f"{prefix} corporate-marketing look must be forbidden", errors)
        require(qa.get("verbatim_cross_posting_forbidden") is True, f"{prefix} verbatim cross-posting must be forbidden", errors)


def validate() -> list[str]:
    errors: list[str] = []
    brand = load(BRAND_PATH)
    profile = load(PROFILE_PATH)

    require(brand.get("product") == "VÂLCEA CLAR Social Publisher Identity System", "master brand product identity drifted", errors)
    require(brand.get("brand", {}).get("positioning") == "premium_local_news_publisher", "premium publisher positioning must remain canonical", errors)

    grammar = brand.get("global_visual_grammar", {})
    for key in (
        "platform_native_visual_grammar_required",
        "mobile_first_legibility_required",
        "cross_post_verbatim_forbidden",
        "generic_stock_substitution_forbidden",
        "synthetic_portrayal_of_real_people_forbidden",
    ):
        require(grammar.get(key) is True, f"master global_visual_grammar.{key} must be true", errors)

    master_qa = brand.get("quality_gate", {})
    for key in REQUIRED_QA:
        require(master_qa.get(key) is True, f"master quality_gate.{key} must be true", errors)
    require(master_qa.get("brand_recognition_without_logo_required") is True, "brand must remain recognizable without logo", errors)
    require(master_qa.get("editorial_hierarchy_required") is True, "editorial hierarchy must remain required", errors)
    require(master_qa.get("profile_and_post_identity_must_match") is True, "profile/post identity continuity must remain required", errors)

    profile_platforms = set(profile.get("platforms", {}))
    brand_platforms = set(brand.get("platforms", {}))
    require(profile_platforms == brand_platforms, f"profile/brand platform coverage mismatch: profile={sorted(profile_platforms)} brand={sorted(brand_platforms)}", errors)

    p = palette(brand)
    for platform, path in VISUAL_SYSTEMS.items():
        require(path.is_file(), f"{platform}: missing visual system file {path.name}", errors)
        if path.is_file():
            validate_visual_system(platform, load(path), profile, p, errors)

    return errors


def main() -> int:
    errors = validate()
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({
        "status": "PASS",
        "product": "VÂLCEA CLAR premium social identity",
        "visual_systems": sorted(VISUAL_SYSTEMS),
        "platform_count": len(VISUAL_SYSTEMS),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
