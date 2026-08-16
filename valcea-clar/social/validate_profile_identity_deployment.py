#!/usr/bin/env python3
"""Validate fail-closed profile identity deployment state."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
PROFILE = SOCIAL / "profile_identity_system.json"
DEPLOYMENT = SOCIAL / "profile_identity_deployment.json"
REQUIRED_PLATFORMS = {"facebook", "instagram", "x", "threads", "tiktok", "youtube", "linkedin", "telegram", "whatsapp"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def validate(profile: dict[str, Any], deployment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    profile_platforms = profile.get("platforms") if isinstance(profile.get("platforms"), dict) else {}
    platforms = deployment.get("platforms") if isinstance(deployment.get("platforms"), dict) else {}
    if set(profile_platforms) != REQUIRED_PLATFORMS:
        errors.append("profile_platform_set_drift")
    if set(platforms) != REQUIRED_PLATFORMS:
        errors.append("deployment_platform_set_drift")
    if deployment.get("identity_source") != "valcea-clar/social/profile_identity_system.json":
        errors.append("deployment_identity_source_drift")
    if deployment.get("asset_generator") != "valcea-clar/social/build_profile_identity_assets.py":
        errors.append("deployment_asset_generator_drift")

    policy = deployment.get("policy") if isinstance(deployment.get("policy"), dict) else {}
    for key in (
        "asset_ready_does_not_mean_live",
        "never_claim_live_without_remote_ack_or_readback",
        "profile_mutation_must_be_separate_from_story_publication",
        "live_apply_requires_explicit_runtime_enable",
        "credential_values_must_never_be_persisted",
        "unsupported_or_unverified_mutation_paths_fail_closed",
    ):
        if policy.get(key) is not True:
            errors.append(f"policy_not_enabled:{key}")

    for platform in sorted(REQUIRED_PLATFORMS):
        cfg = platforms.get(platform) if isinstance(platforms.get(platform), dict) else {}
        pcfg = profile_platforms.get(platform) if isinstance(profile_platforms.get(platform), dict) else {}
        if cfg.get("asset_status") != "READY":
            errors.append(f"{platform}:asset_not_ready")
        if cfg.get("live_status") not in {"UNCONFIRMED", "CONFIRMED_REMOTE"}:
            errors.append(f"{platform}:invalid_live_status")
        if cfg.get("live_status") == "CONFIRMED_REMOTE" and cfg.get("last_remote_readback") in (None, ""):
            errors.append(f"{platform}:confirmed_without_readback")
        avatar = str(cfg.get("avatar_asset") or "")
        expected_avatar = f"{platform}-avatar.png"
        if avatar != expected_avatar:
            errors.append(f"{platform}:avatar_asset_drift")
        header_cfg = pcfg.get("header_export")
        expected_header = f"{platform}-header.jpg" if isinstance(header_cfg, dict) else None
        actual_header = cfg.get("header_asset")
        if expected_header and actual_header != expected_header:
            errors.append(f"{platform}:header_asset_drift")
        if not expected_header and actual_header:
            errors.append(f"{platform}:unexpected_header_asset")
        mode = str(cfg.get("deployment_mode") or "")
        api_status = str(cfg.get("api_capability_status") or "")
        if mode == "NOT_AUTOMATED" and "VERIFIED" in api_status and "NOT_VERIFIED" not in api_status:
            errors.append(f"{platform}:verified_api_but_not_automated_requires_review")

    youtube = platforms.get("youtube") if isinstance(platforms.get("youtube"), dict) else {}
    if youtube.get("deployment_mode") != "API_GATED_BANNER_ONLY":
        errors.append("youtube:deployment_mode_drift")
    if youtube.get("api_capability_status") != "OFFICIAL_BANNER_API_VERIFIED":
        errors.append("youtube:api_capability_not_verified")
    api = youtube.get("banner_api") if isinstance(youtube.get("banner_api"), dict) else {}
    if api.get("upload_method") != "channelBanners.insert" or api.get("apply_method") != "channels.update":
        errors.append("youtube:official_banner_flow_drift")
    if api.get("readback_method") != "channels.list":
        errors.append("youtube:readback_method_missing")
    if (api.get("recommended_width"), api.get("recommended_height")) != (2560, 1440):
        errors.append("youtube:recommended_banner_dimensions_drift")
    if int(api.get("max_bytes") or 0) != 6 * 1024 * 1024:
        errors.append("youtube:max_banner_bytes_drift")
    runtime = youtube.get("runtime") if isinstance(youtube.get("runtime"), dict) else {}
    if runtime.get("enable_env") != "VALCEA_YOUTUBE_PROFILE_LIVE_ENABLED":
        errors.append("youtube:live_enable_env_drift")
    if runtime.get("oauth_env") != "VALCEA_YOUTUBE_OAUTH_ACCESS_TOKEN":
        errors.append("youtube:oauth_env_drift")

    gate = deployment.get("quality_gate") if isinstance(deployment.get("quality_gate"), dict) else {}
    for key in (
        "all_identity_platforms_must_have_deployment_state",
        "all_ready_assets_must_be_generated_by_canonical_builder",
        "live_status_cannot_be_true_from_local_generation",
        "youtube_banner_apply_requires_explicit_enable_and_oauth",
        "youtube_banner_apply_requires_remote_readback",
    ):
        if gate.get(key) is not True:
            errors.append(f"quality_gate_not_enabled:{key}")
    return errors


def self_test() -> int:
    profile = {"platforms": {p: {"avatar_export": {}} for p in REQUIRED_PLATFORMS}}
    for p in ("facebook", "x", "youtube", "linkedin"):
        profile["platforms"][p]["header_export"] = {}
    deployment = {
        "identity_source": "valcea-clar/social/profile_identity_system.json",
        "asset_generator": "valcea-clar/social/build_profile_identity_assets.py",
        "policy": {key: True for key in (
            "asset_ready_does_not_mean_live","never_claim_live_without_remote_ack_or_readback","profile_mutation_must_be_separate_from_story_publication","live_apply_requires_explicit_runtime_enable","credential_values_must_never_be_persisted","unsupported_or_unverified_mutation_paths_fail_closed"
        )},
        "platforms": {},
        "quality_gate": {key: True for key in (
            "all_identity_platforms_must_have_deployment_state","all_ready_assets_must_be_generated_by_canonical_builder","live_status_cannot_be_true_from_local_generation","youtube_banner_apply_requires_explicit_enable_and_oauth","youtube_banner_apply_requires_remote_readback"
        )},
    }
    for p in REQUIRED_PLATFORMS:
        cfg = {"asset_status":"READY","avatar_asset":f"{p}-avatar.png","deployment_mode":"NOT_AUTOMATED","api_capability_status":"PROFILE_MUTATION_ACCESS_NOT_CONFIGURED","live_status":"UNCONFIRMED"}
        if p in ("facebook", "x", "youtube", "linkedin"):
            cfg["header_asset"] = f"{p}-header.jpg"
        deployment["platforms"][p] = cfg
    deployment["platforms"]["facebook"]["api_capability_status"] = "PROFILE_MUTATION_PATH_NOT_VERIFIED"
    deployment["platforms"]["instagram"]["api_capability_status"] = "PROFILE_MUTATION_PATH_NOT_VERIFIED"
    deployment["platforms"]["threads"]["api_capability_status"] = "PROFILE_MUTATION_PATH_NOT_VERIFIED"
    deployment["platforms"]["youtube"].update({
        "deployment_mode":"API_GATED_BANNER_ONLY","api_capability_status":"OFFICIAL_BANNER_API_VERIFIED",
        "banner_api":{"upload_method":"channelBanners.insert","apply_method":"channels.update","readback_method":"channels.list","recommended_width":2560,"recommended_height":1440,"max_bytes":6291456},
        "runtime":{"enable_env":"VALCEA_YOUTUBE_PROFILE_LIVE_ENABLED","oauth_env":"VALCEA_YOUTUBE_OAUTH_ACCESS_TOKEN"},
    })
    assert validate(profile, deployment) == []
    deployment["platforms"]["youtube"]["live_status"] = "CONFIRMED_REMOTE"
    assert "youtube:confirmed_without_readback" in validate(profile, deployment)
    print("VÂLCEA CLAR profile deployment validator self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    errors = validate(load(PROFILE), load(DEPLOYMENT))
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    print("VÂLCEA CLAR profile deployment control: PASS (9 platforms; YouTube banner API gated)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
