#!/usr/bin/env python3
"""Validate platform-native VÂLCEA CLAR profile presence copy and featured roles."""
from __future__ import annotations

import argparse
import difflib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
PRESENCE = SOCIAL / "profile_presence_system.json"
PROFILE = SOCIAL / "profile_identity_system.json"
BRAND = SOCIAL / "social_brand_system.json"
NATIVE = SOCIAL / "native_platform_identity_system.json"
DEPLOYMENT = SOCIAL / "profile_identity_deployment.json"
REQUIRED = ("facebook", "instagram", "x", "threads", "tiktok", "youtube", "linkedin", "telegram", "whatsapp")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def normalize(text: str) -> str:
    value = str(text).lower()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"[^a-z0-9ăâîșț]+", " ", value)
    return " ".join(value.split())


def similarity(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize(a), normalize(b)).ratio()


def validate(
    presence: dict[str, Any],
    profile: dict[str, Any],
    brand: dict[str, Any],
    native: dict[str, Any],
    deployment: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    platforms = presence.get("platforms") if isinstance(presence.get("platforms"), dict) else {}
    profile_platforms = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}
    deployment_platforms = deployment.get("platforms") if isinstance(deployment.get("platforms"), dict) else {}
    native_platforms = native.get("platforms") if isinstance(native.get("platforms"), dict) else {}
    master_brand = brand.get("brand") if isinstance(brand.get("brand"), dict) else {}

    if tuple(platforms) != REQUIRED:
        errors.append("presence_platform_order_or_set_drift")
    if set(profile_platforms) != set(REQUIRED):
        errors.append("profile_platform_set_drift")
    if set(deployment_platforms) != set(REQUIRED):
        errors.append("deployment_platform_set_drift")
    if presence.get("identity_source") != "valcea-clar/social/profile_identity_system.json":
        errors.append("presence_identity_source_drift")
    if presence.get("brand_source") != "valcea-clar/social/social_brand_system.json":
        errors.append("presence_brand_source_drift")
    if presence.get("native_identity_source") != "valcea-clar/social/native_platform_identity_system.json":
        errors.append("presence_native_identity_source_drift")
    if presence.get("canonical_domain") != master_brand.get("canonical_domain"):
        errors.append("presence_domain_drift")

    rules = presence.get("global_rules") if isinstance(presence.get("global_rules"), dict) else {}
    for key in (
        "mission_first",
        "canonical_link_required_where_platform_supports_it",
        "no_generic_ai_language",
        "no_engagement_bait",
        "no_hashtag_block_in_profile_copy",
        "no_emoji_wall",
        "no_marketing_superlatives",
        "no_cross_platform_verbatim_bio",
        "no_fake_breaking_language",
        "profile_copy_must_read_as_newsroom",
        "featured_content_must_have_editorial_role",
    ):
        if rules.get(key) is not True:
            errors.append(f"global_rule_disabled:{key}")
    if rules.get("display_name") != master_brand.get("display_name"):
        errors.append("presence_display_name_drift")
    if rules.get("site_url") != "https://valceaclar.ro/":
        errors.append("presence_site_url_drift")

    roles: set[str] = set()
    bios: dict[str, str] = {}
    forbidden = (
        "cel mai bun", "numărul 1", "nr. 1", "lider incontestabil", "revoluționar",
        "powered by ai", "generat de ai", "like și share", "dă share", "urmărește-ne acum",
        "breaking!!!", "senzațional", "șocant",
    )
    for platform in REQUIRED:
        cfg = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        role = str(cfg.get("role") or "").strip()
        bio = str(cfg.get("short_bio") or "").strip()
        about = str(cfg.get("about") or "").strip()
        featured = str(cfg.get("featured_strategy") or "").strip()
        asset = str(cfg.get("profile_asset") or "").strip()
        header = str(cfg.get("header_asset") or "").strip()
        link_label = str(cfg.get("link_label") or "").strip()

        if not role:
            errors.append(f"{platform}:role_missing")
        elif role in roles:
            errors.append(f"{platform}:role_not_unique:{role}")
        roles.add(role)
        if not bio or len(bio) > 180:
            errors.append(f"{platform}:short_bio_missing_or_over_internal_budget")
        bios[platform] = bio
        combined = f"{bio} {about}".lower()
        if any(term in combined for term in forbidden):
            errors.append(f"{platform}:marketing_or_engagement_language_detected")
        if "###" in combined or combined.count("#") >= 2:
            errors.append(f"{platform}:profile_hashtag_block_detected")
        if not featured:
            errors.append(f"{platform}:featured_strategy_missing")
        if not link_label or "valceaclar.ro" not in link_label.lower():
            errors.append(f"{platform}:canonical_link_label_missing")
        if asset != f"{platform}-avatar.png":
            errors.append(f"{platform}:avatar_asset_drift")

        p_cfg = profile_platforms.get(platform) if isinstance(profile_platforms.get(platform), dict) else {}
        if p_cfg.get("display_name") != master_brand.get("display_name"):
            errors.append(f"{platform}:profile_display_name_drift")
        expects_header = isinstance(p_cfg.get("header_export"), dict)
        if expects_header and header != f"{platform}-header.jpg":
            errors.append(f"{platform}:header_asset_missing")
        if not expects_header and header:
            errors.append(f"{platform}:unexpected_header_asset")

        d_cfg = deployment_platforms.get(platform) if isinstance(deployment_platforms.get(platform), dict) else {}
        if d_cfg.get("avatar_asset") != asset:
            errors.append(f"{platform}:deployment_avatar_drift")
        if header and d_cfg.get("header_asset") != header:
            errors.append(f"{platform}:deployment_header_drift")

        native_cfg = native_platforms.get(platform) if isinstance(native_platforms.get(platform), dict) else {}
        native_role = str(native_cfg.get("product_role") or "").strip()
        if native_role and native_role != role:
            errors.append(f"{platform}:native_role_drift:{native_role}!={role}")

    for index, a in enumerate(REQUIRED):
        for b in REQUIRED[index + 1:]:
            if bios.get(a) == bios.get(b):
                errors.append(f"verbatim_bio_duplicate:{a}:{b}")
            elif similarity(bios.get(a, ""), bios.get(b, "")) >= 0.92:
                errors.append(f"bio_too_similar:{a}:{b}")

    instagram = platforms.get("instagram") if isinstance(platforms.get("instagram"), dict) else {}
    highlights = instagram.get("highlight_desks") if isinstance(instagram.get("highlight_desks"), list) else []
    if highlights != ["ACUM", "BANI PUBLICI", "INVESTIGAȚII", "UNDE IEȘIM", "GHIDURI"]:
        errors.append("instagram:editorial_highlight_desks_drift")

    youtube = platforms.get("youtube") if isinstance(platforms.get("youtube"), dict) else {}
    playlists = youtube.get("playlist_desks") if isinstance(youtube.get("playlist_desks"), list) else []
    if playlists != ["ȘTIRI EXPLICATE", "BANI PUBLICI", "INVESTIGAȚII", "VÂLCEA ÎN 60 DE SECUNDE"]:
        errors.append("youtube:editorial_playlist_desks_drift")

    whatsapp = platforms.get("whatsapp") if isinstance(platforms.get("whatsapp"), dict) else {}
    wa_copy = f"{whatsapp.get('short_bio','')} {whatsapp.get('about','')}".lower()
    if "doar" not in wa_copy or "esențial" not in wa_copy or "fără spam" not in wa_copy:
        errors.append("whatsapp:low_frequency_profile_promise_missing")

    telegram = platforms.get("telegram") if isinstance(platforms.get("telegram"), dict) else {}
    if similarity(
        str(telegram.get("short_bio") or "") + " " + str(telegram.get("about") or ""),
        str(whatsapp.get("short_bio") or "") + " " + str(whatsapp.get("about") or ""),
    ) >= 0.82:
        errors.append("telegram_whatsapp_profile_copy_not_distinct_enough")

    acceptance = presence.get("acceptance") if isinstance(presence.get("acceptance"), dict) else {}
    for key, value in acceptance.items():
        if value is not True:
            errors.append(f"acceptance_disabled:{key}")
    return errors


def self_test() -> int:
    presence = load(PRESENCE)
    profile = load(PROFILE)
    brand = load(BRAND)
    native = load(NATIVE)
    deployment = load(DEPLOYMENT)
    assert validate(presence, profile, brand, native, deployment) == []
    broken = json.loads(json.dumps(presence))
    broken["platforms"]["whatsapp"]["short_bio"] = broken["platforms"]["telegram"]["short_bio"]
    errors = validate(broken, profile, brand, native, deployment)
    assert any(error.startswith("verbatim_bio_duplicate:telegram:whatsapp") for error in errors)
    broken = json.loads(json.dumps(presence))
    broken["platforms"]["instagram"]["short_bio"] = "Cel mai bun ziar! Like și share ###"
    errors = validate(broken, profile, brand, native, deployment)
    assert "instagram:marketing_or_engagement_language_detected" in errors
    assert "instagram:profile_hashtag_block_detected" in errors
    print("VÂLCEA CLAR profile presence validator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    errors = validate(load(PRESENCE), load(PROFILE), load(BRAND), load(NATIVE), load(DEPLOYMENT))
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("VÂLCEA CLAR profile presence: PASS (9 distinct premium platform-native profiles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
