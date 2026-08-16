#!/usr/bin/env python3
"""Fail-closed identity contract for VÂLCEA CLAR native social products."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
BRAND = SOCIAL / "social_brand_system.json"
PROFILE = SOCIAL / "profile_identity_system.json"
DOCTRINE = SOCIAL / "social_network_doctrine.json"
NATIVE = SOCIAL / "native_platform_identity_system.json"
SECONDARY = {"x", "threads", "linkedin", "tiktok", "youtube", "telegram", "whatsapp"}

PREMIUM_CONTRACT_KEYS = (
    "story_function_selects_layout",
    "layout_repetition_default_forbidden",
    "ai_template_aesthetic_forbidden",
    "local_marketing_page_aesthetic_forbidden",
    "brand_recognition_without_logo_required",
    "news_value_before_brand_bumper",
    "real_subject_integrity_required",
    "source_visibility_when_factual_graphics",
    "generic_engagement_bait_forbidden",
    "fake_urgency_forbidden",
)

QUALITY_GATE_KEYS = (
    "all_secondary_channels_must_match_profile_channel_ids",
    "all_secondary_channels_must_match_doctrine_channel_ids",
    "all_products_must_declare_identity_lineage",
    "video_products_must_declare_on_screen_branding",
    "x_must_remain_text_first",
    "linkedin_must_remain_professional_evidence_led",
    "message_channels_must_not_become_visual_template_feeds",
    "premium_design_contract_enforced",
    "video_news_value_must_precede_branding",
    "thumbnails_must_be_truthful",
    "layouts_must_not_repeat_mechanically",
    "source_labels_required_for_evidence_graphics",
)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def validate(
    brand_doc: dict[str, Any],
    profile: dict[str, Any],
    doctrine: dict[str, Any],
    native: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    brand = obj(brand_doc.get("brand"))
    palette = obj(brand.get("palette"))
    common = obj(native.get("common"))
    platforms = obj(native.get("platforms"))
    profiles = obj(profile.get("platforms"))
    doctrine_channels = obj(doctrine.get("channels"))

    if native.get("schema_version") != "1.1":
        errors.append("native:schema_version_must_be_1.1")
    if native.get("principle") != "one_newsroom_distinct_native_products":
        errors.append("native:one_newsroom_distinct_products_principle_drift")

    expected_sources = {
        "brand_source": "valcea-clar/social/social_brand_system.json",
        "profile_source": "valcea-clar/social/profile_identity_system.json",
        "doctrine_source": "valcea-clar/social/social_network_doctrine.json",
    }
    for key, expected in expected_sources.items():
        if native.get(key) != expected:
            errors.append(f"native:{key}_drift")

    if common.get("display_name") != brand.get("display_name"):
        errors.append("native:display_name_drift")
    if common.get("editorial_lockup") != brand.get("editorial_lockup"):
        errors.append("native:editorial_lockup_drift")
    if common.get("canonical_domain") != brand.get("canonical_domain"):
        errors.append("native:canonical_domain_drift")
    for native_key, brand_key in (
        ("accent_rgb", "accent_rgb"),
        ("paper_rgb", "paper_rgb"),
        ("ink_rgb", "ink_rgb"),
        ("white_rgb", "white_rgb"),
    ):
        if common.get(native_key) != palette.get(brand_key):
            errors.append(f"native:{native_key}_drift")

    rules = common.get("rules") if isinstance(common.get("rules"), list) else []
    for required_rule in (
        "brand_recognizable_without_repeating_logo_everywhere",
        "no_social_template_aesthetic",
        "cross_platform_verbatim_reuse_forbidden",
        "story_function_selects_layout",
        "news_value_precedes_branding",
        "primary_evidence_must_not_be_obscured",
    ):
        if required_rule not in rules:
            errors.append(f"native:common_rule_missing:{required_rule}")

    premium = obj(common.get("premium_design_contract"))
    for key in PREMIUM_CONTRACT_KEYS:
        if premium.get(key) is not True:
            errors.append(f"native:premium_contract_not_enabled:{key}")

    if set(platforms) != SECONDARY:
        errors.append("native:secondary_platform_set_drift")

    for platform in sorted(SECONDARY):
        cfg = obj(platforms.get(platform))
        pprofile = obj(profiles.get(platform))
        pdoctrine = obj(doctrine_channels.get(platform))
        channel_id = f"valcea-{platform}"
        if cfg.get("channel_id") != channel_id:
            errors.append(f"{platform}:native_channel_id_drift")
        if pprofile.get("channel_id") != channel_id:
            errors.append(f"{platform}:profile_channel_id_drift")
        if pdoctrine.get("channel_id") != channel_id:
            errors.append(f"{platform}:doctrine_channel_id_drift")
        if pprofile.get("display_name") != brand.get("display_name"):
            errors.append(f"{platform}:profile_display_name_drift")
        avatar = obj(pprofile.get("avatar_export"))
        if avatar.get("source") != "avatar-master":
            errors.append(f"{platform}:avatar_not_from_master")
        if not str(cfg.get("identity_mode") or "").strip():
            errors.append(f"{platform}:identity_mode_missing")
        if not str(cfg.get("product_role") or "").strip():
            errors.append(f"{platform}:product_role_missing")
        if pdoctrine.get("final_copy_cross_platform_reuse") is not False:
            errors.append(f"{platform}:cross_platform_final_reuse_not_forbidden")

    x = obj(platforms.get("x"))
    x_presentation = obj(x.get("presentation"))
    if x_presentation.get("text_first") is not True or x_presentation.get("brand_prefix_each_post") is not False:
        errors.append("x:newswire_identity_contract_failed")
    if x_presentation.get("hashtags_default") is not False:
        errors.append("x:hashtags_must_not_be_brand_device")

    threads = obj(platforms.get("threads"))
    threads_presentation = obj(threads.get("presentation"))
    if threads_presentation.get("text_first") is not True:
        errors.append("threads:text_first_identity_failed")
    if threads_presentation.get("generic_engagement_prompt_forbidden") is not True:
        errors.append("threads:generic_engagement_prompt_gate_disabled")

    li = obj(platforms.get("linkedin"))
    li_presentation = obj(li.get("presentation"))
    li_visual = obj(li.get("visual"))
    if li_presentation.get("document_or_data_visual_preferred_over_decorative_photo") is not True:
        errors.append("linkedin:evidence_led_visual_contract_failed")
    if li_presentation.get("translate_institutional_jargon_into_plain_language") is not True:
        errors.append("linkedin:plain_language_contract_failed")
    if li_visual.get("document_page_canvas") != [1080, 1350]:
        errors.append("linkedin:document_page_canvas_drift")
    if li_visual.get("design_tone") != "newsroom_analysis_not_corporate_marketing":
        errors.append("linkedin:newsroom_design_tone_drift")
    if li_visual.get("source_label_required_on_data_or_document_cards") is not True:
        errors.append("linkedin:source_label_gate_disabled")
    if li_visual.get("number_or_metric_may_be_primary") is not True:
        errors.append("linkedin:number_led_visual_contract_failed")
    for key in ("marketing_badge_forbidden", "photo_collage_forbidden", "consulting_deck_clutter_forbidden"):
        if li_visual.get(key) is not True:
            errors.append(f"linkedin:premium_restraint_disabled:{key}")

    tiktok = obj(platforms.get("tiktok"))
    tt_visual = obj(tiktok.get("visual"))
    tt_audio = obj(tiktok.get("audio"))
    if tt_visual.get("brand_mark") != "VC.":
        errors.append("tiktok:on_screen_brand_mark_missing")
    if tt_visual.get("master_canvas") != [1080, 1920]:
        errors.append("tiktok:master_canvas_drift")
    if tt_visual.get("opening_bumper_before_news") is not False:
        errors.append("tiktok:news_must_precede_brand_bumper")
    if tt_visual.get("burned_in_headline_lines_max") != 2:
        errors.append("tiktok:headline_line_limit_drift")
    if tt_visual.get("all_caps_headline_default") is not False:
        errors.append("tiktok:all_caps_default_forbidden")
    for key in (
        "text_must_not_cover_primary_evidence",
        "platform_ui_safe_zone_required",
        "synthetic_filler_forbidden",
        "archive_as_current_forbidden",
        "real_story_specific_media_required",
    ):
        if tt_visual.get(key) is not True:
            errors.append(f"tiktok:visual_gate_disabled:{key}")
    for key in (
        "natural_sound_preferred_when_editorially_useful",
        "trending_audio_must_not_drive_story_selection",
        "audio_must_not_overstate_evidence",
    ):
        if tt_audio.get(key) is not True:
            errors.append(f"tiktok:audio_gate_disabled:{key}")
    tt_slate = str(tt_visual.get("source_end_slate") or "")
    if "VÂLCEA CLAR" not in tt_slate or "valceaclar.ro" not in tt_slate:
        errors.append("tiktok:source_end_slate_drift")

    youtube = obj(platforms.get("youtube"))
    yt_thumb = obj(youtube.get("thumbnail"))
    yt_video = obj(youtube.get("video"))
    if yt_thumb.get("brand_mark") != "VC.":
        errors.append("youtube:on_screen_brand_mark_missing")
    if yt_thumb.get("canvas") != [1280, 720]:
        errors.append("youtube:thumbnail_canvas_drift")
    for key in (
        "one_dominant_visual_idea",
        "story_specific_visual_required",
        "visual_should_make_sense_without_logo",
        "thumbnail_must_match_video",
        "fake_composite_forbidden",
        "misleading_expression_or_crop_forbidden",
        "sensational_arrows_circles_fake_reactions_forbidden",
        "clickbait_visual_expression_forbidden",
        "marketing_badges_forbidden",
    ):
        if yt_thumb.get(key) is not True:
            errors.append(f"youtube:thumbnail_gate_disabled:{key}")
    if yt_video.get("opening_bumper_before_story_value") is not False:
        errors.append("youtube:story_value_must_precede_brand_bumper")
    for key in (
        "real_video_or_sufficient_visual_sequence_required",
        "synthetic_filler_forbidden",
        "archive_as_current_forbidden",
        "source_or_method_transparency_for_investigations",
    ):
        if yt_video.get(key) is not True:
            errors.append(f"youtube:video_gate_disabled:{key}")
    yt_slate = str(yt_video.get("source_end_slate") or "")
    if "VÂLCEA CLAR" not in yt_slate or "valceaclar.ro" not in yt_slate:
        errors.append("youtube:source_end_slate_drift")

    for platform in ("telegram", "whatsapp"):
        presentation = obj(obj(platforms.get(platform)).get("presentation"))
        if presentation.get("text_first") is not True:
            errors.append(f"{platform}:message_first_identity_failed")
        if presentation.get("brand_prefix_each_message") is not False:
            errors.append(f"{platform}:repeated_brand_prefix_forbidden")
        if presentation.get("fake_urgency_forbidden") is not True:
            errors.append(f"{platform}:fake_urgency_gate_disabled")

    gate = obj(native.get("quality_gate"))
    for key in QUALITY_GATE_KEYS:
        if gate.get(key) is not True:
            errors.append(f"native:quality_gate_not_enabled:{key}")
    return errors


def self_test() -> int:
    brand = {
        "brand": {
            "display_name": "VÂLCEA CLAR",
            "editorial_lockup": "VÂLCEA. CLAR.",
            "canonical_domain": "valceaclar.ro",
            "palette": {
                "accent_rgb": [196, 27, 35],
                "paper_rgb": [247, 246, 243],
                "ink_rgb": [20, 20, 20],
                "white_rgb": [255, 255, 255],
            },
        }
    }
    profiles: dict[str, Any] = {}
    doctrine_channels: dict[str, Any] = {}
    platforms: dict[str, Any] = {}
    for platform in SECONDARY:
        profiles[platform] = {
            "channel_id": f"valcea-{platform}",
            "display_name": "VÂLCEA CLAR",
            "avatar_export": {"source": "avatar-master"},
        }
        doctrine_channels[platform] = {
            "channel_id": f"valcea-{platform}",
            "final_copy_cross_platform_reuse": False,
        }
        platforms[platform] = {
            "channel_id": f"valcea-{platform}",
            "identity_mode": "native",
            "product_role": "test",
            "presentation": {},
        }

    platforms["x"]["presentation"] = {
        "text_first": True,
        "brand_prefix_each_post": False,
        "hashtags_default": False,
    }
    platforms["threads"]["presentation"] = {
        "text_first": True,
        "generic_engagement_prompt_forbidden": True,
    }
    platforms["linkedin"]["presentation"] = {
        "document_or_data_visual_preferred_over_decorative_photo": True,
        "translate_institutional_jargon_into_plain_language": True,
    }
    platforms["linkedin"]["visual"] = {
        "document_page_canvas": [1080, 1350],
        "design_tone": "newsroom_analysis_not_corporate_marketing",
        "source_label_required_on_data_or_document_cards": True,
        "number_or_metric_may_be_primary": True,
        "marketing_badge_forbidden": True,
        "photo_collage_forbidden": True,
        "consulting_deck_clutter_forbidden": True,
    }
    platforms["tiktok"]["visual"] = {
        "brand_mark": "VC.",
        "master_canvas": [1080, 1920],
        "opening_bumper_before_news": False,
        "burned_in_headline_lines_max": 2,
        "all_caps_headline_default": False,
        "text_must_not_cover_primary_evidence": True,
        "platform_ui_safe_zone_required": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "real_story_specific_media_required": True,
        "source_end_slate": "VÂLCEA CLAR · valceaclar.ro",
    }
    platforms["tiktok"]["audio"] = {
        "natural_sound_preferred_when_editorially_useful": True,
        "trending_audio_must_not_drive_story_selection": True,
        "audio_must_not_overstate_evidence": True,
    }
    platforms["youtube"]["thumbnail"] = {
        "brand_mark": "VC.",
        "canvas": [1280, 720],
        "one_dominant_visual_idea": True,
        "story_specific_visual_required": True,
        "visual_should_make_sense_without_logo": True,
        "thumbnail_must_match_video": True,
        "fake_composite_forbidden": True,
        "misleading_expression_or_crop_forbidden": True,
        "sensational_arrows_circles_fake_reactions_forbidden": True,
        "clickbait_visual_expression_forbidden": True,
        "marketing_badges_forbidden": True,
    }
    platforms["youtube"]["video"] = {
        "opening_bumper_before_story_value": False,
        "real_video_or_sufficient_visual_sequence_required": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "source_or_method_transparency_for_investigations": True,
        "source_end_slate": "VÂLCEA CLAR · valceaclar.ro",
    }
    for platform in ("telegram", "whatsapp"):
        platforms[platform]["presentation"] = {
            "text_first": True,
            "brand_prefix_each_message": False,
            "fake_urgency_forbidden": True,
        }

    native = {
        "schema_version": "1.1",
        "principle": "one_newsroom_distinct_native_products",
        "brand_source": "valcea-clar/social/social_brand_system.json",
        "profile_source": "valcea-clar/social/profile_identity_system.json",
        "doctrine_source": "valcea-clar/social/social_network_doctrine.json",
        "common": {
            "display_name": "VÂLCEA CLAR",
            "editorial_lockup": "VÂLCEA. CLAR.",
            "canonical_domain": "valceaclar.ro",
            "accent_rgb": [196, 27, 35],
            "paper_rgb": [247, 246, 243],
            "ink_rgb": [20, 20, 20],
            "white_rgb": [255, 255, 255],
            "rules": [
                "brand_recognizable_without_repeating_logo_everywhere",
                "no_social_template_aesthetic",
                "cross_platform_verbatim_reuse_forbidden",
                "story_function_selects_layout",
                "news_value_precedes_branding",
                "primary_evidence_must_not_be_obscured",
            ],
            "premium_design_contract": {key: True for key in PREMIUM_CONTRACT_KEYS},
        },
        "platforms": platforms,
        "quality_gate": {key: True for key in QUALITY_GATE_KEYS},
    }
    assert validate(brand, {"platforms": profiles}, {"channels": doctrine_channels}, native) == []

    native["platforms"]["youtube"]["thumbnail"]["fake_composite_forbidden"] = False
    assert "youtube:thumbnail_gate_disabled:fake_composite_forbidden" in validate(
        brand, {"platforms": profiles}, {"channels": doctrine_channels}, native
    )
    native["platforms"]["youtube"]["thumbnail"]["fake_composite_forbidden"] = True
    native["platforms"]["tiktok"]["visual"]["opening_bumper_before_news"] = True
    assert "tiktok:news_must_precede_brand_bumper" in validate(
        brand, {"platforms": profiles}, {"channels": doctrine_channels}, native
    )
    print("VÂLCEA CLAR native platform identity validator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    errors = validate(load(BRAND), load(PROFILE), load(DOCTRINE), load(NATIVE))
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("VÂLCEA CLAR native platform identity: PASS (7 secondary channels, premium contract v1.1)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
