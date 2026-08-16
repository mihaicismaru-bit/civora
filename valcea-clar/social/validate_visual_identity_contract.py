#!/usr/bin/env python3
"""Fail-closed contract tying VÂLCEA CLAR profile identity to feed renderers."""
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
FEED_RENDERER = SOCIAL / "feed_identity_v1_1.py"
FACEBOOK_WRAPPER = SOCIAL / "facebook_editorial_preview_v1_1.py"
INSTAGRAM_WRAPPER = SOCIAL / "instagram_editorial_v1_2.py"

CANONICAL_BRAND_REF = "valcea-clar/social/social_brand_system.json"
CANONICAL_PROFILE_REF = "valcea-clar/social/profile_identity_system.json"
CANONICAL_FEED_RENDERER = "valcea-clar/social/feed_identity_v1_1.py"

COMMON_QA = (
    "profile_and_post_identity_must_match",
    "shared_feed_signature_required",
    "decorative_badges_forbidden",
    "decorative_gradients_forbidden",
    "debug_or_status_metadata_in_artwork_forbidden",
    "must_not_look_like_local_marketing_page",
    "must_not_look_ai_generated",
    "must_not_repeat_identical_layout_for_every_story",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def canonical_palette(master: dict[str, Any]) -> dict[str, list[int]]:
    palette = obj(obj(master.get("brand")).get("palette"))
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
    feed_renderer_text: str,
    facebook_wrapper_text: str,
    instagram_wrapper_text: str,
) -> list[str]:
    errors: list[str] = []
    brand = obj(master.get("brand"))
    masthead = obj(profile.get("masthead"))
    platforms = obj(profile.get("platforms"))
    palette = canonical_palette(master)

    if profile.get("schema_version") != "1.1":
        errors.append("profile:schema_must_be_1.1")
    if profile.get("brand_source") != CANONICAL_BRAND_REF:
        errors.append("profile:canonical_brand_lineage_missing")
    if masthead.get("wordmark") != brand.get("display_name"):
        errors.append("profile:wordmark_drift")
    if masthead.get("tagline") != brand.get("tagline"):
        errors.append("profile:tagline_drift")
    if masthead.get("domain") != brand.get("canonical_domain"):
        errors.append("profile:domain_drift")
    avatar = obj(profile.get("avatar"))
    if avatar.get("mark") != "VC." or avatar.get("accent") != "red_typographic_period":
        errors.append("profile:typographic_VC_mark_drift")

    for platform, system in (("facebook", facebook), ("instagram", instagram)):
        prefix = f"{platform}:"
        if system.get("schema_version") != "1.1":
            errors.append(prefix + "schema_must_be_1.1")
        if system.get("master_identity_system") != CANONICAL_BRAND_REF:
            errors.append(prefix + "canonical_brand_lineage_missing")
        if system.get("profile_identity_system") != CANONICAL_PROFILE_REF:
            errors.append(prefix + "canonical_profile_lineage_missing")
        if system.get("feed_renderer") != CANONICAL_FEED_RENDERER:
            errors.append(prefix + "canonical_feed_renderer_missing")

        system_brand = obj(system.get("brand"))
        if system_brand.get("name") != brand.get("display_name"):
            errors.append(prefix + "brand_name_drift")
        if system_brand.get("editorial_lockup") != brand.get("editorial_lockup"):
            errors.append(prefix + "editorial_lockup_drift")
        for key, expected in palette.items():
            if system_brand.get(key) != expected:
                errors.append(prefix + f"{key}_drift")

        qa = obj(system.get("qa"))
        for key in COMMON_QA:
            if qa.get(key) is not True:
                errors.append(prefix + f"qa_not_enabled:{key}")

        profile_cfg = obj(platforms.get(platform))
        if profile_cfg.get("channel_id") != system.get("channel_id"):
            errors.append(prefix + "channel_id_drift")
        if profile_cfg.get("display_name") != system_brand.get("name"):
            errors.append(prefix + "profile_display_name_drift")

        canvas = obj(system.get("canvas"))
        width = int(canvas.get("width") or 0)
        height = int(canvas.get("height") or 0)
        if width <= 0 or height <= 0 or canvas.get("aspect_ratio") != "4:5":
            errors.append(prefix + "invalid_feed_canvas")
        elif width * 5 != height * 4:
            errors.append(prefix + "feed_canvas_ratio_drift")

        signature = obj(system.get("feed_visual_signature"))
        if signature.get("brand_mark") != "VC.":
            errors.append(prefix + "feed_brand_mark_drift")
        if signature.get("brand_mark_period") != "typographic_red_same_baseline":
            errors.append(prefix + "typographic_red_period_drift")
        if signature.get("headline_family") != "serif_bold":
            errors.append(prefix + "headline_family_drift")
        if signature.get("supporting_family") != "sans":
            errors.append(prefix + "supporting_family_drift")
        for key in ("decorative_badges", "drop_shadows", "debug_or_status_metadata_in_artwork"):
            if signature.get(key) is not False:
                errors.append(prefix + f"premium_restraint_disabled:{key}")

    fb_sig = obj(facebook.get("feed_visual_signature"))
    if fb_sig.get("composition") != "contextual_photo_plus_spacious_paper_news_brief":
        errors.append("facebook:composition_drift")
    if fb_sig.get("accent_rule") != "short_horizontal_red_locator":
        errors.append("facebook:horizontal_locator_drift")
    if fb_sig.get("divider") != "thin_editorial_hairline":
        errors.append("facebook:hairline_drift")
    if fb_sig.get("vertical_accent_bar") is not False:
        errors.append("facebook:vertical_accent_bar_must_remain_forbidden")
    if fb_sig.get("decorative_gradients") is not False:
        errors.append("facebook:decorative_gradient_must_remain_forbidden")
    if obj(facebook.get("qa")).get("vertical_accent_bar_forbidden") is not True:
        errors.append("facebook:vertical_accent_bar_gate_disabled")

    ig_sig = obj(instagram.get("feed_visual_signature"))
    if ig_sig.get("composition") != "image_dominant_full_bleed_editorial_cover":
        errors.append("instagram:composition_drift")
    if ig_sig.get("accent_rule") != "single_short_red_locator_near_headline":
        errors.append("instagram:headline_locator_drift")
    if ig_sig.get("readability_gradient") != "allowed_only_to_protect_text_over_real_photo":
        errors.append("instagram:readability_gradient_contract_drift")
    if ig_sig.get("decorative_gradient") is not False:
        errors.append("instagram:decorative_gradient_must_remain_forbidden")
    if ig_sig.get("primary_subject_protection") is not True:
        errors.append("instagram:primary_subject_protection_disabled")
    if ig_sig.get("text_slide_grid") != "VC_mark_hairline_kicker_large_lead_body_split_footer":
        errors.append("instagram:text_slide_grid_drift")
    if obj(instagram.get("qa")).get("readability_gradient_must_be_functional_only") is not True:
        errors.append("instagram:functional_gradient_gate_disabled")

    master_gate = obj(master.get("quality_gate"))
    profile_gate = obj(profile.get("quality_gate"))
    if master_gate.get("profile_and_post_identity_must_match") is not True:
        errors.append("master:profile_post_identity_gate_disabled")
    if profile_gate.get("profile_assets_must_be_deterministic") is not True:
        errors.append("profile:deterministic_assets_gate_disabled")

    # One renderer, two native compositions. The shared source must consume the
    # JSON palette and expose all three presentation functions; wrappers must
    # bind those functions into the already-established publication stacks.
    required_feed_tokens = (
        "def draw_vc_mark(",
        "def render_facebook(",
        "def render_instagram_cover(",
        "def render_instagram_text_slide(",
        '_rgb(brand["paper_rgb"])',
        '_rgb(brand["ink_rgb"])',
        '_rgb(brand["accent_rgb"])',
    )
    for token in required_feed_tokens:
        if token not in feed_renderer_text:
            errors.append("feed_renderer:missing_contract_token:" + token)
    if 'Image.new("RGB", canvas, (247, 246, 243))' in feed_renderer_text:
        errors.append("feed_renderer:hardcoded_canonical_paper_forbidden")

    for token in (
        "impl.render = feed_identity.render_facebook",
        "feed_identity.self_test()",
    ):
        if token not in facebook_wrapper_text:
            errors.append("facebook:wrapper_not_bound_to_premium_renderer:" + token)
    for token in (
        "impl.base.render_cover = feed_identity.render_instagram_cover",
        "impl.render_text_slide = feed_identity.render_instagram_text_slide",
        "feed_identity.self_test()",
    ):
        if token not in instagram_wrapper_text:
            errors.append("instagram:wrapper_not_bound_to_premium_renderer:" + token)

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
        "schema_version": "1.1",
        "brand_source": CANONICAL_BRAND_REF,
        "masthead": {
            "wordmark": "VÂLCEA CLAR",
            "tagline": "Ce se întâmplă. Ce știm. Ce contează.",
            "domain": "valceaclar.ro",
        },
        "avatar": {"mark": "VC.", "accent": "red_typographic_period"},
        "platforms": {
            "facebook": {"channel_id": "valcea-facebook", "display_name": "VÂLCEA CLAR"},
            "instagram": {"channel_id": "valcea-instagram", "display_name": "VÂLCEA CLAR"},
        },
        "quality_gate": {"profile_assets_must_be_deterministic": True},
    }
    base_brand = {
        "name": "VÂLCEA CLAR",
        "editorial_lockup": "VÂLCEA. CLAR.",
        "accent_rgb": [196, 27, 35],
        "paper_rgb": [247, 246, 243],
        "ink_rgb": [20, 20, 20],
        "white_rgb": [255, 255, 255],
    }
    base_qa = {key: True for key in COMMON_QA}
    common = {
        "schema_version": "1.1",
        "master_identity_system": CANONICAL_BRAND_REF,
        "profile_identity_system": CANONICAL_PROFILE_REF,
        "feed_renderer": CANONICAL_FEED_RENDERER,
        "canvas": {"width": 1080, "height": 1350, "aspect_ratio": "4:5"},
        "brand": base_brand,
        "qa": base_qa,
    }
    facebook = {
        **common,
        "channel_id": "valcea-facebook",
        "feed_visual_signature": {
            "composition": "contextual_photo_plus_spacious_paper_news_brief",
            "brand_mark": "VC.",
            "brand_mark_period": "typographic_red_same_baseline",
            "accent_rule": "short_horizontal_red_locator",
            "divider": "thin_editorial_hairline",
            "vertical_accent_bar": False,
            "headline_family": "serif_bold",
            "supporting_family": "sans",
            "decorative_badges": False,
            "decorative_gradients": False,
            "drop_shadows": False,
            "debug_or_status_metadata_in_artwork": False,
        },
        "qa": {**base_qa, "vertical_accent_bar_forbidden": True},
    }
    instagram = {
        **common,
        "channel_id": "valcea-instagram",
        "feed_visual_signature": {
            "composition": "image_dominant_full_bleed_editorial_cover",
            "brand_mark": "VC.",
            "brand_mark_period": "typographic_red_same_baseline",
            "accent_rule": "single_short_red_locator_near_headline",
            "readability_gradient": "allowed_only_to_protect_text_over_real_photo",
            "decorative_gradient": False,
            "primary_subject_protection": True,
            "text_slide_grid": "VC_mark_hairline_kicker_large_lead_body_split_footer",
            "headline_family": "serif_bold",
            "supporting_family": "sans",
            "decorative_badges": False,
            "drop_shadows": False,
            "debug_or_status_metadata_in_artwork": False,
        },
        "qa": {**base_qa, "readability_gradient_must_be_functional_only": True},
    }
    feed = '\n'.join([
        'def draw_vc_mark(', 'def render_facebook(', 'def render_instagram_cover(',
        'def render_instagram_text_slide(', '_rgb(brand["paper_rgb"])',
        '_rgb(brand["ink_rgb"])', '_rgb(brand["accent_rgb"])',
    ])
    fb_wrapper = "impl.render = feed_identity.render_facebook\nfeed_identity.self_test()"
    ig_wrapper = "impl.base.render_cover = feed_identity.render_instagram_cover\nimpl.render_text_slide = feed_identity.render_instagram_text_slide\nfeed_identity.self_test()"
    assert validate(master, profile, facebook, instagram, feed, fb_wrapper, ig_wrapper) == []
    facebook["feed_visual_signature"]["vertical_accent_bar"] = True
    assert "facebook:vertical_accent_bar_must_remain_forbidden" in validate(
        master, profile, facebook, instagram, feed, fb_wrapper, ig_wrapper
    )
    print("VÂLCEA CLAR visual identity contract v1.1 self-test: PASS")
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
        FEED_RENDERER.read_text(encoding="utf-8"),
        FACEBOOK_WRAPPER.read_text(encoding="utf-8"),
        INSTAGRAM_WRAPPER.read_text(encoding="utf-8"),
    )
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("VÂLCEA CLAR visual identity contract: PASS (profile v1.1 ↔ Facebook v1.1 ↔ Instagram v1.1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
