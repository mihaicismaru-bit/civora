#!/usr/bin/env python3
"""Fail-closed validation for the VÂLCEA CLAR cross-platform profile identity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
PROFILE = VC / "social" / "profile_identity_system.json"
BRAND = VC / "social" / "social_brand_system.json"
CHANNELS = VC / "social" / "channels"
REQUIRED = {"facebook", "instagram", "x", "threads", "tiktok", "youtube", "linkedin", "telegram", "whatsapp"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def configured_platforms() -> set[str]:
    result: set[str] = set()
    for path in CHANNELS.glob("*.json"):
        platform = str(load(path).get("platform") or "").strip()
        if platform:
            result.add(platform)
    return result


def validate(profile: dict[str, Any], brand: dict[str, Any], configured: set[str]) -> list[str]:
    errors: list[str] = []
    b = brand.get("brand") if isinstance(brand.get("brand"), dict) else {}
    mast = profile.get("masthead") if isinstance(profile.get("masthead"), dict) else {}
    avatar = profile.get("avatar") if isinstance(profile.get("avatar"), dict) else {}
    platforms = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}

    if profile.get("brand_source") != "valcea-clar/social/social_brand_system.json":
        errors.append("brand_source_must_be_canonical")
    if mast.get("wordmark") != b.get("display_name"):
        errors.append("masthead_wordmark_must_match_brand")
    if mast.get("tagline") != b.get("tagline"):
        errors.append("tagline_must_match_brand")
    if mast.get("domain") != b.get("canonical_domain"):
        errors.append("domain_must_match_brand")
    if avatar.get("mark") != "VC.":
        errors.append("master_avatar_mark_must_be_VC_period")
    master = avatar.get("master") if isinstance(avatar.get("master"), dict) else {}
    if master.get("width") != master.get("height") or int(master.get("width") or 0) < 1024:
        errors.append("master_avatar_contract_failed")

    missing = sorted(configured - set(platforms))
    if missing:
        errors.append("configured_channels_missing_identity:" + ",".join(missing))
    missing_required = sorted(REQUIRED - set(platforms))
    if missing_required:
        errors.append("required_platforms_missing:" + ",".join(missing_required))

    seen_bios: dict[str, str] = {}
    for name, cfg in sorted(platforms.items()):
        if not isinstance(cfg, dict):
            errors.append(f"{name}:profile_config_not_object")
            continue
        if cfg.get("display_name") != b.get("display_name"):
            errors.append(f"{name}:display_name_mismatch")
        bio = " ".join(str(cfg.get("bio") or "").split())
        if len(bio) < 25:
            errors.append(f"{name}:bio_too_thin")
        key = bio.casefold()
        if key in seen_bios:
            errors.append(f"{name}:bio_not_platform_specific_same_as_{seen_bios[key]}")
        else:
            seen_bios[key] = name

        av = cfg.get("avatar_export")
        if not isinstance(av, dict) or av.get("source") != "avatar-master":
            errors.append(f"{name}:avatar_not_from_master")
        elif int(av.get("width") or 0) <= 0 or int(av.get("height") or 0) <= 0:
            errors.append(f"{name}:invalid_avatar_dimensions")

        header = cfg.get("header_export")
        if header is None:
            continue
        if not isinstance(header, dict):
            errors.append(f"{name}:header_export_not_object")
            continue
        width, height = int(header.get("width") or 0), int(header.get("height") or 0)
        safe = header.get("safe_zone")
        if width <= 0 or height <= 0:
            errors.append(f"{name}:invalid_header_dimensions")
        if not isinstance(safe, dict):
            errors.append(f"{name}:header_safe_zone_missing")
            continue
        x, y = int(safe.get("x") or 0), int(safe.get("y") or 0)
        sw, sh = int(safe.get("width") or 0), int(safe.get("height") or 0)
        if min(x, y, sw, sh) < 0 or sw <= 0 or sh <= 0:
            errors.append(f"{name}:invalid_header_safe_zone")
        elif x + sw > width or y + sh > height:
            errors.append(f"{name}:header_safe_zone_outside_canvas")
        if not str(header.get("spec_source") or "").startswith("https://"):
            errors.append(f"{name}:header_spec_source_missing")

    principles = set(profile.get("identity_principles") or [])
    for rule in (
        "one_master_avatar_across_platforms",
        "masthead_not_marketing_banner",
        "limited_text_in_headers",
        "center_critical_information_for_responsive_crops",
        "no_platform_logo_inside_brand_assets",
    ):
        if rule not in principles:
            errors.append(f"identity_principle_missing:{rule}")
    gate = profile.get("quality_gate") if isinstance(profile.get("quality_gate"), dict) else {}
    for key in (
        "all_configured_channels_must_be_covered",
        "all_avatar_exports_must_share_master_mark",
        "header_safe_zones_must_fit_canvas",
        "headers_must_not_use_photography",
        "profile_assets_must_be_deterministic",
    ):
        if gate.get(key) is not True:
            errors.append(f"quality_gate_not_enabled:{key}")
    return errors


def self_test() -> int:
    brand = {"brand": {"display_name": "VÂLCEA CLAR", "tagline": "Ce se întâmplă. Ce știm. Ce contează.", "canonical_domain": "valceaclar.ro"}}
    profile = {
        "brand_source": "valcea-clar/social/social_brand_system.json",
        "masthead": {"wordmark": "VÂLCEA CLAR", "tagline": "Ce se întâmplă. Ce știm. Ce contează.", "domain": "valceaclar.ro"},
        "avatar": {"mark": "VC.", "master": {"width": 1024, "height": 1024}},
        "identity_principles": ["one_master_avatar_across_platforms", "masthead_not_marketing_banner", "limited_text_in_headers", "center_critical_information_for_responsive_crops", "no_platform_logo_inside_brand_assets"],
        "quality_gate": {"all_configured_channels_must_be_covered": True, "all_avatar_exports_must_share_master_mark": True, "header_safe_zones_must_fit_canvas": True, "headers_must_not_use_photography": True, "profile_assets_must_be_deterministic": True},
        "platforms": {},
    }
    for name in REQUIRED:
        profile["platforms"][name] = {"display_name": "VÂLCEA CLAR", "bio": f"{name}: Știri locale verificate din Vâlcea, cu surse și context editorial.", "avatar_export": {"width": 400, "height": 400, "source": "avatar-master"}}
    profile["platforms"]["x"]["header_export"] = {"width": 1500, "height": 500, "safe_zone": {"x": 180, "y": 70, "width": 1140, "height": 360}, "spec_source": "https://help.x.com/"}
    assert validate(profile, brand, REQUIRED) == []
    profile["platforms"]["x"]["header_export"]["safe_zone"]["width"] = 2000
    assert "x:header_safe_zone_outside_canvas" in validate(profile, brand, REQUIRED)
    print("VÂLCEA CLAR profile identity validator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    profile, brand = load(PROFILE), load(BRAND)
    configured = configured_platforms()
    errors = validate(profile, brand, configured)
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print(f"VÂLCEA CLAR profile identity: PASS ({len(configured)} configured channels, {len(profile['platforms'])} identity profiles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
