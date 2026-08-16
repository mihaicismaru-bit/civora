#!/usr/bin/env python3
"""Validate VÂLCEA CLAR's platform-native social doctrine.

The doctrine is intentionally stricter than CHANNEL_CONFIG: it ensures every
configured network has a distinct editorial product contract, recent benchmark
research, non-verbatim cross-platform output, and site-independent failure
semantics. It does not authorize publishing or inspect credentials.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DOCTRINE = ROOT / "valcea-clar" / "social" / "social_network_doctrine.json"
CHANNEL_DIR = ROOT / "valcea-clar" / "social" / "channels"
PREMIUM_US = {
    "The New York Times",
    "The Washington Post",
    "The Wall Street Journal",
    "CNN",
    "Associated Press",
    "Reuters",
    "Bloomberg",
    "NBC News",
}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def fail(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def parse_date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError:
        return None


def validate_payload(doc: dict[str, Any], channel_dir: Path, *, today: dt.date | None = None) -> list[str]:
    errors: list[str] = []
    today = today or dt.datetime.now(dt.timezone.utc).date()

    fail(doc.get("schema_version") == "1.0", "schema_version must be 1.0", errors)
    fail(doc.get("instance_id") == "valcea", "instance_id must be valcea", errors)
    fail(doc.get("publication_model") == "continuous_story_first", "publication_model must remain continuous_story_first", errors)
    fail(doc.get("canonical_source") == "site_story", "canonical_source must be site_story", errors)
    fail(doc.get("site_publish_independent") is True, "site publication must remain independent", errors)
    fail(doc.get("cross_platform_final_reuse_default") is False, "cross-platform final reuse must default false", errors)
    fail(doc.get("metrics_observed_only") is True, "metrics must be observed-only", errors)

    max_age = doc.get("benchmark_refresh_max_age_days")
    fail(isinstance(max_age, int) and 30 <= max_age <= 365, "benchmark_refresh_max_age_days must be 30..365", errors)
    max_age = max_age if isinstance(max_age, int) else 180

    invariants = doc.get("shared_invariants")
    required_invariants = {
        "same_verified_facts_different_packaging",
        "no_factual_embellishment_for_reach",
        "no_clickbait_or_fake_urgency",
        "no_engagement_bait",
        "rights_and_provenance_fail_closed",
        "channel_failure_isolated",
        "channel_may_hold_independently",
        "civora_site_engine_owns_automation",
    }
    fail(isinstance(invariants, list), "shared_invariants must be an array", errors)
    if isinstance(invariants, list):
        fail(required_invariants.issubset(set(invariants)), "shared_invariants are incomplete", errors)

    profiles = doc.get("channels")
    fail(isinstance(profiles, dict) and bool(profiles), "channels must be a non-empty object", errors)
    profiles = profiles if isinstance(profiles, dict) else {}

    configured: dict[str, dict[str, Any]] = {}
    for path in sorted(channel_dir.glob("*.json")):
        cfg = load(path)
        platform = str(cfg.get("platform", "")).strip()
        if not platform:
            errors.append(f"{path.name}: missing platform")
            continue
        configured[platform] = cfg

    for platform, cfg in configured.items():
        profile = profiles.get(platform)
        fail(isinstance(profile, dict), f"configured channel {platform} lacks doctrine profile", errors)
        if not isinstance(profile, dict):
            continue
        fail(profile.get("channel_id") == cfg.get("channel_id"), f"{platform}: channel_id mismatch", errors)
        fail(str(profile.get("product_mode", "")).startswith("platform_native"), f"{platform}: product_mode must be platform_native*", errors)
        fail(profile.get("final_copy_cross_platform_reuse") is False, f"{platform}: verbatim cross-platform final reuse must be false", errors)
        fail(len(str(profile.get("audience_role", "")).strip()) >= 12, f"{platform}: audience_role too short", errors)
        fail(len(str(profile.get("interest_gate", "")).strip()) >= 6, f"{platform}: interest_gate missing", errors)
        hooks = profile.get("hook_policy")
        families = profile.get("native_product_families")
        fail(isinstance(hooks, list) and bool(hooks), f"{platform}: hook_policy must be non-empty", errors)
        fail(isinstance(families, list) and bool(families), f"{platform}: native_product_families must be non-empty", errors)
        fail(len(str(profile.get("visual_strategy", "")).strip()) >= 16, f"{platform}: visual_strategy too short", errors)

        benchmark = profile.get("benchmark")
        fail(isinstance(benchmark, dict), f"{platform}: benchmark missing", errors)
        if not isinstance(benchmark, dict):
            continue
        date = parse_date(benchmark.get("research_date"))
        fail(date is not None, f"{platform}: invalid benchmark research_date", errors)
        if date is not None:
            age = (today - date).days
            fail(0 <= age <= max_age, f"{platform}: benchmark research is stale/future ({age} days)", errors)
        outlets = benchmark.get("outlets")
        fail(isinstance(outlets, list) and len(outlets) >= 3, f"{platform}: need at least three benchmark outlets", errors)
        if isinstance(outlets, list):
            us_count = len(set(map(str, outlets)) & PREMIUM_US)
            fail(us_count >= 2, f"{platform}: need at least two premium US/international benchmark outlets", errors)
        fail(benchmark.get("official_platform_guidance_reviewed") is True, f"{platform}: official platform guidance must be reviewed", errors)
        fail(len(str(benchmark.get("platform_owner", "")).strip()) >= 2, f"{platform}: platform_owner missing", errors)

    unknown_profiles = sorted(set(profiles) - set(configured))
    fail(not unknown_profiles, f"doctrine has unconfigured active profiles: {', '.join(unknown_profiles)}", errors)

    planned = doc.get("planned_channels")
    fail(isinstance(planned, dict), "planned_channels must be an object", errors)
    if isinstance(planned, dict):
        for name, profile in planned.items():
            fail(isinstance(profile, dict), f"planned channel {name} must be an object", errors)
            if not isinstance(profile, dict):
                continue
            fail(profile.get("final_copy_cross_platform_reuse") is False, f"planned {name}: cross-platform reuse must be false", errors)
            fail(profile.get("direct_publication_enabled") is False, f"planned {name}: direct publication must remain false until configured", errors)
            fail(profile.get("status") == "planned_unconfigured", f"planned {name}: invalid status", errors)

    return errors


def self_test() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channels = root / "channels"
        channels.mkdir()
        (channels / "facebook.json").write_text(json.dumps({"platform": "facebook", "channel_id": "valcea-facebook"}), encoding="utf-8")
        base = {
            "schema_version": "1.0",
            "instance_id": "valcea",
            "publication_model": "continuous_story_first",
            "canonical_source": "site_story",
            "site_publish_independent": True,
            "cross_platform_final_reuse_default": False,
            "metrics_observed_only": True,
            "benchmark_refresh_max_age_days": 180,
            "shared_invariants": [
                "same_verified_facts_different_packaging",
                "no_factual_embellishment_for_reach",
                "no_clickbait_or_fake_urgency",
                "no_engagement_bait",
                "rights_and_provenance_fail_closed",
                "channel_failure_isolated",
                "channel_may_hold_independently",
                "civora_site_engine_owns_automation",
            ],
            "channels": {
                "facebook": {
                    "channel_id": "valcea-facebook",
                    "product_mode": "platform_native",
                    "audience_role": "useful local community news",
                    "interest_gate": "FB_GATE",
                    "hook_policy": ["local_utility"],
                    "native_product_families": ["fb_news_card"],
                    "visual_strategy": "one strong mobile-first editorial focal point",
                    "final_copy_cross_platform_reuse": False,
                    "benchmark": {
                        "research_date": "2026-08-16",
                        "outlets": ["The New York Times", "The Washington Post", "Associated Press"],
                        "official_platform_guidance_reviewed": True,
                        "platform_owner": "Meta",
                    },
                }
            },
            "planned_channels": {},
        }
        assert not validate_payload(base, channels, today=dt.date(2026, 8, 16))
        bad = json.loads(json.dumps(base))
        bad["channels"]["facebook"]["final_copy_cross_platform_reuse"] = True
        assert any("verbatim cross-platform" in e for e in validate_payload(bad, channels, today=dt.date(2026, 8, 16)))
        stale = json.loads(json.dumps(base))
        stale["channels"]["facebook"]["benchmark"]["research_date"] = "2025-01-01"
        assert any("stale" in e for e in validate_payload(stale, channels, today=dt.date(2026, 8, 16)))
    print("VÂLCEA CLAR social doctrine self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--doctrine", type=Path, default=DOCTRINE)
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    path = args.doctrine if args.doctrine.is_absolute() else ROOT / args.doctrine
    errors = validate_payload(load(path), CHANNEL_DIR)
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "doctrine": str(path.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
