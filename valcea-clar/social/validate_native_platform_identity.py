#!/usr/bin/env python3
"""Fail-closed identity contract for VÂLCEA CLAR secondary social products."""
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


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validate(brand_doc: dict[str, Any], profile: dict[str, Any], doctrine: dict[str, Any], native: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    brand = brand_doc.get("brand") if isinstance(brand_doc.get("brand"), dict) else {}
    palette = brand.get("palette") if isinstance(brand.get("palette"), dict) else {}
    common = native.get("common") if isinstance(native.get("common"), dict) else {}
    platforms = native.get("platforms") if isinstance(native.get("platforms"), dict) else {}
    profiles = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}
    doctrine_channels = doctrine.get("channels") if isinstance(doctrine.get("channels"), dict) else {}

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

    if set(platforms) != SECONDARY:
        errors.append("native:secondary_platform_set_drift")

    for platform in sorted(SECONDARY):
        cfg = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        pprofile = profiles.get(platform) if isinstance(profiles.get(platform), dict) else {}
        pdoctrine = doctrine_channels.get(platform) if isinstance(doctrine_channels.get(platform), dict) else {}
        channel_id = f"valcea-{platform}"
        if cfg.get("channel_id") != channel_id:
            errors.append(f"{platform}:native_channel_id_drift")
        if pprofile.get("channel_id") != channel_id:
            errors.append(f"{platform}:profile_channel_id_drift")
        if pdoctrine.get("channel_id") != channel_id:
            errors.append(f"{platform}:doctrine_channel_id_drift")
        if pprofile.get("display_name") != brand.get("display_name"):
            errors.append(f"{platform}:profile_display_name_drift")
        avatar = pprofile.get("avatar_export") if isinstance(pprofile.get("avatar_export"), dict) else {}
        if avatar.get("source") != "avatar-master":
            errors.append(f"{platform}:avatar_not_from_master")
        if not str(cfg.get("identity_mode") or "").strip():
            errors.append(f"{platform}:identity_mode_missing")
        if not str(cfg.get("product_role") or "").strip():
            errors.append(f"{platform}:product_role_missing")
        if pdoctrine.get("final_copy_cross_platform_reuse") is not False:
            errors.append(f"{platform}:cross_platform_final_reuse_not_forbidden")

    x = platforms.get("x", {})
    x_presentation = x.get("presentation") if isinstance(x.get("presentation"), dict) else {}
    if x_presentation.get("text_first") is not True or x_presentation.get("brand_prefix_each_post") is not False:
        errors.append("x:newswire_identity_contract_failed")
    if x_presentation.get("hashtags_default") is not False:
        errors.append("x:hashtags_must_not_be_brand_device")

    li = platforms.get("linkedin", {})
    li_presentation = li.get("presentation") if isinstance(li.get("presentation"), dict) else {}
    li_visual = li.get("visual") if isinstance(li.get("visual"), dict) else {}
    if li_presentation.get("document_or_data_visual_preferred_over_decorative_photo") is not True:
        errors.append("linkedin:evidence_led_visual_contract_failed")
    if li_visual.get("marketing_badge_forbidden") is not True or li_visual.get("photo_collage_forbidden") is not True:
        errors.append("linkedin:premium_visual_restraint_failed")

    for platform in ("tiktok", "youtube"):
        cfg = platforms.get(platform, {})
        visual = cfg.get("visual") if isinstance(cfg.get("visual"), dict) else {}
        thumb = cfg.get("thumbnail") if isinstance(cfg.get("thumbnail"), dict) else {}
        branded = visual.get("brand_mark") == "VC." or thumb.get("brand_mark") == "VC."
        if not branded:
            errors.append(f"{platform}:on_screen_brand_mark_missing")
        video = cfg.get("video") if isinstance(cfg.get("video"), dict) else visual
        if video.get("synthetic_filler_forbidden") is not True:
            errors.append(f"{platform}:synthetic_filler_gate_disabled")
        if video.get("archive_as_current_forbidden") is not True:
            errors.append(f"{platform}:archive_as_current_gate_disabled")
        slate = str(video.get("source_end_slate") or visual.get("source_end_slate") or "")
        if "VÂLCEA CLAR" not in slate or "valceaclar.ro" not in slate:
            errors.append(f"{platform}:source_end_slate_drift")

    for platform in ("telegram", "whatsapp"):
        presentation = platforms.get(platform, {}).get("presentation", {})
        if not isinstance(presentation, dict) or presentation.get("text_first") is not True:
            errors.append(f"{platform}:message_first_identity_failed")
        if isinstance(presentation, dict) and presentation.get("brand_prefix_each_message") is not False:
            errors.append(f"{platform}:repeated_brand_prefix_forbidden")

    gate = native.get("quality_gate") if isinstance(native.get("quality_gate"), dict) else {}
    for key in (
        "all_secondary_channels_must_match_profile_channel_ids",
        "all_secondary_channels_must_match_doctrine_channel_ids",
        "all_products_must_declare_identity_lineage",
        "video_products_must_declare_on_screen_branding",
        "x_must_remain_text_first",
        "linkedin_must_remain_professional_evidence_led",
        "message_channels_must_not_become_visual_template_feeds",
    ):
        if gate.get(key) is not True:
            errors.append(f"native:quality_gate_not_enabled:{key}")
    return errors


def self_test() -> int:
    brand = {
        "brand": {
            "display_name": "VÂLCEA CLAR", "editorial_lockup": "VÂLCEA. CLAR.",
            "canonical_domain": "valceaclar.ro",
            "palette": {"accent_rgb": [196,27,35], "paper_rgb": [247,246,243], "ink_rgb": [20,20,20], "white_rgb": [255,255,255]},
        }
    }
    profiles = {}
    doctrine_channels = {}
    platforms = {}
    for p in SECONDARY:
        profiles[p] = {"channel_id": f"valcea-{p}", "display_name": "VÂLCEA CLAR", "avatar_export": {"source": "avatar-master"}}
        doctrine_channels[p] = {"channel_id": f"valcea-{p}", "final_copy_cross_platform_reuse": False}
        platforms[p] = {"channel_id": f"valcea-{p}", "identity_mode": "native", "product_role": "test", "presentation": {}}
    platforms["x"]["presentation"] = {"text_first": True, "brand_prefix_each_post": False, "hashtags_default": False}
    platforms["linkedin"]["presentation"] = {"document_or_data_visual_preferred_over_decorative_photo": True}
    platforms["linkedin"]["visual"] = {"marketing_badge_forbidden": True, "photo_collage_forbidden": True}
    platforms["tiktok"]["visual"] = {"brand_mark": "VC.", "synthetic_filler_forbidden": True, "archive_as_current_forbidden": True, "source_end_slate": "VÂLCEA CLAR · valceaclar.ro"}
    platforms["youtube"]["thumbnail"] = {"brand_mark": "VC."}
    platforms["youtube"]["video"] = {"synthetic_filler_forbidden": True, "archive_as_current_forbidden": True, "source_end_slate": "VÂLCEA CLAR · valceaclar.ro"}
    for p in ("telegram", "whatsapp"):
        platforms[p]["presentation"] = {"text_first": True, "brand_prefix_each_message": False}
    native = {
        "brand_source": "valcea-clar/social/social_brand_system.json",
        "profile_source": "valcea-clar/social/profile_identity_system.json",
        "doctrine_source": "valcea-clar/social/social_network_doctrine.json",
        "common": {"display_name":"VÂLCEA CLAR","editorial_lockup":"VÂLCEA. CLAR.","canonical_domain":"valceaclar.ro","accent_rgb":[196,27,35],"paper_rgb":[247,246,243],"ink_rgb":[20,20,20],"white_rgb":[255,255,255]},
        "platforms": platforms,
        "quality_gate": {key: True for key in (
            "all_secondary_channels_must_match_profile_channel_ids","all_secondary_channels_must_match_doctrine_channel_ids","all_products_must_declare_identity_lineage","video_products_must_declare_on_screen_branding","x_must_remain_text_first","linkedin_must_remain_professional_evidence_led","message_channels_must_not_become_visual_template_feeds"
        )},
    }
    assert validate(brand, {"platforms": profiles}, {"channels": doctrine_channels}, native) == []
    native["platforms"]["x"]["presentation"]["text_first"] = False
    assert "x:newswire_identity_contract_failed" in validate(brand, {"platforms": profiles}, {"channels": doctrine_channels}, native)
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
    print("VÂLCEA CLAR native platform identity: PASS (7 secondary channels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
