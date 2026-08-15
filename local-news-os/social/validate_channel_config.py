#!/usr/bin/env python3
"""Dependency-free validator for LOCAL NEWS OS social CHANNEL_CONFIG files.

The JSON Schema is canonical documentation. This validator enforces the critical
runtime and isolation invariants without requiring a paid service or third-party
Python package.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "local-news-os" / "social" / "channel_config.schema.json"


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def validate(config_path: Path, instance_root: str | None = None) -> list[str]:
    cfg = load_object(config_path)
    schema = load_object(SCHEMA)
    errors: list[str] = []

    required = schema.get("required", [])
    require(isinstance(required, list), "schema.required must be an array", errors)
    for key in required if isinstance(required, list) else []:
        require(key in cfg, f"missing required field: {key}", errors)

    allowed_top = set(schema.get("properties", {}))
    unknown = sorted(set(cfg) - allowed_top)
    require(not unknown, f"unknown top-level fields: {', '.join(unknown)}", errors)

    require(cfg.get("schema_version") == "1.0", "schema_version must be 1.0", errors)
    id_pattern = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
    channel_id = str(cfg.get("channel_id", ""))
    instance_id = str(cfg.get("instance_id", ""))
    require(bool(id_pattern.fullmatch(channel_id)), "invalid channel_id", errors)
    require(bool(id_pattern.fullmatch(instance_id)), "invalid instance_id", errors)

    platforms = set(schema["properties"]["platform"]["enum"])
    require(cfg.get("platform") in platforms, f"unsupported platform: {cfg.get('platform')}", errors)
    statuses = set(schema["properties"]["status"]["enum"])
    require(cfg.get("status") in statuses, f"unsupported status: {cfg.get('status')}", errors)
    require(len(str(cfg.get("audience_promise", "")).strip()) >= 12, "audience_promise is too short", errors)

    editorial = cfg.get("editorial_mix")
    require(isinstance(editorial, dict), "editorial_mix must be an object", errors)
    if isinstance(editorial, dict):
        priorities = editorial.get("priorities")
        exclusions = editorial.get("exclusions")
        require(isinstance(priorities, list) and bool(priorities), "editorial_mix.priorities must be non-empty", errors)
        require(isinstance(exclusions, list), "editorial_mix.exclusions must be an array", errors)

    native_formats = cfg.get("native_formats")
    allowed_formats = set(schema["properties"]["native_formats"]["items"]["enum"])
    require(isinstance(native_formats, list) and bool(native_formats), "native_formats must be non-empty", errors)
    if isinstance(native_formats, list):
        invalid = sorted({str(value) for value in native_formats if value not in allowed_formats})
        require(not invalid, f"unsupported native_formats: {', '.join(invalid)}", errors)
        require(len(native_formats) == len(set(native_formats)), "native_formats must be unique", errors)

    cadence = cfg.get("cadence")
    require(isinstance(cadence, dict), "cadence must be an object", errors)
    if isinstance(cadence, dict):
        require(bool(str(cadence.get("timezone", "")).strip()), "cadence.timezone is required", errors)
        max_posts = cadence.get("max_posts_per_day")
        spacing = cadence.get("min_spacing_minutes")
        require(isinstance(max_posts, int) and 1 <= max_posts <= 48, "cadence.max_posts_per_day must be 1..48", errors)
        require(isinstance(spacing, int) and 0 <= spacing <= 1440, "cadence.min_spacing_minutes must be 0..1440", errors)
        quiet = cadence.get("quiet_hours")
        require(isinstance(quiet, dict), "cadence.quiet_hours must be an object", errors)
        if isinstance(quiet, dict):
            time_pattern = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")
            require(bool(time_pattern.fullmatch(str(quiet.get("start", "")))), "invalid quiet_hours.start", errors)
            require(bool(time_pattern.fullmatch(str(quiet.get("end", "")))), "invalid quiet_hours.end", errors)
            require(isinstance(quiet.get("breaking_override"), bool), "quiet_hours.breaking_override must be boolean", errors)

    fatigue = cfg.get("fatigue")
    require(isinstance(fatigue, dict), "fatigue must be an object", errors)
    if isinstance(fatigue, dict):
        cooldown = fatigue.get("same_story_cooldown_hours")
        related = fatigue.get("max_related_posts_24h")
        require(isinstance(cooldown, int) and 0 <= cooldown <= 168, "invalid same_story_cooldown_hours", errors)
        require(isinstance(related, int) and 1 <= related <= 24, "invalid max_related_posts_24h", errors)

    media = cfg.get("media_policy")
    require(isinstance(media, dict), "media_policy must be an object", errors)
    if isinstance(media, dict):
        for key in ("real_media_only", "provenance_required", "reuse_rights_required", "synthetic_real_person_forbidden"):
            require(media.get(key) is True, f"media_policy.{key} must be true", errors)

    links = cfg.get("link_policy")
    require(isinstance(links, dict), "link_policy must be an object", errors)
    if isinstance(links, dict):
        require(links.get("mode") in {"required", "optional", "native_preferred"}, "invalid link_policy.mode", errors)
        hosts = links.get("canonical_hosts")
        require(isinstance(hosts, list), "link_policy.canonical_hosts must be an array", errors)

    gates = cfg.get("approval_gates")
    require(isinstance(gates, dict), "approval_gates must be an object", errors)
    if isinstance(gates, dict):
        require(isinstance(gates.get("low_risk_auto"), bool), "approval_gates.low_risk_auto must be boolean", errors)
        require(gates.get("reputational_human") is True, "approval_gates.reputational_human must be true", errors)
        require(gates.get("corrections_priority") is True, "approval_gates.corrections_priority must be true", errors)

    credential = str(cfg.get("credentials_ref", ""))
    require(credential.startswith(("github-actions-secret:", "connector:", "none:")), "credentials_ref must be a reference, never a raw credential", errors)
    require(not any(marker in credential.upper() for marker in ("EAA", "BEARER ", "ACCESS_TOKEN=")), "credentials_ref appears to contain a raw credential", errors)

    state = cfg.get("publication_state")
    require(isinstance(state, dict), "publication_state must be an object", errors)
    if isinstance(state, dict):
        outbox = str(state.get("outbox_path", ""))
        state_path = str(state.get("state_path", ""))
        require(bool(outbox) and bool(state_path), "publication_state paths are required", errors)
        require(state.get("dedupe_by_id") is True, "publication_state.dedupe_by_id must be true", errors)
        require(state.get("last_known_good") is True, "publication_state.last_known_good must be true", errors)
        if instance_root:
            prefix = instance_root.rstrip("/") + "/"
            require(outbox.startswith(prefix), f"outbox_path escapes instance root {prefix}", errors)
            require(state_path.startswith(prefix), f"state_path escapes instance root {prefix}", errors)

    metrics = cfg.get("metrics")
    require(isinstance(metrics, dict), "metrics must be an object", errors)
    if isinstance(metrics, dict):
        require(metrics.get("observed_only") is True, "metrics.observed_only must be true", errors)
        require(isinstance(metrics.get("sources"), list), "metrics.sources must be an array", errors)

    require(cfg.get("zero_paid_dependency") is True, "zero_paid_dependency must be true", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--instance-root")
    args = parser.parse_args()
    path = args.config if args.config.is_absolute() else ROOT / args.config
    errors = validate(path, args.instance_root)
    if errors:
        print(json.dumps({"status": "FAIL", "config": str(args.config), "errors": errors}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps({"status": "PASS", "config": str(args.config)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
