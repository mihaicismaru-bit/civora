#!/usr/bin/env python3
"""Validate fail-closed ownership of the VÂLCEA CLAR social engine."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FORBIDDEN_MARKERS = {
    "OPENAI_API_KEY": "OpenAI API secret",
    "api.openai.com": "OpenAI API endpoint",
    "chat.openai.com": "ChatGPT web runtime",
    "chatgpt.com/backend-api": "ChatGPT private runtime endpoint",
    "ANTHROPIC_API_KEY": "Anthropic API secret",
    "api.anthropic.com": "Anthropic API endpoint",
    "GEMINI_API_KEY": "Gemini API secret",
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def cron_declared(workflow_text: str, cron: str) -> bool:
    return any(
        candidate in workflow_text
        for candidate in (
            f'cron: "{cron}"',
            f"cron: '{cron}'",
            f"cron: {cron}",
        )
    )


def validate(repo_root: Path) -> dict[str, Any]:
    social_root = repo_root / "valcea-clar" / "social"
    registry_path = social_root / "channel_registry.json"
    automation_path = repo_root / "valcea-clar" / "engine" / "automation_registry.json"
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    if not registry_path.is_file():
        return {
            "checked_at": utc_now(),
            "status": "FAIL",
            "errors": ["Missing valcea-clar/social/channel_registry.json"],
            "checks": [],
        }

    registry = load_json(registry_path)
    chatgpt = registry.get("chatgpt", {})
    policy = registry.get("policy", {})
    ownership = {
        "execution_owner": registry.get("execution_owner") == "civora_site_engine",
        "scheduler": registry.get("scheduler") == "github_actions",
        "state_owner": registry.get("state_owner") == "repository",
        "chatgpt_scheduled_publication_disabled": chatgpt.get("scheduled_publication_allowed") is False,
        "chatgpt_direct_publication_disabled": chatgpt.get("direct_publication_allowed") is False,
        "chatgpt_credential_access_disabled": chatgpt.get("credential_access_allowed") is False,
        "chatgpt_state_ownership_disabled": chatgpt.get("state_ownership_allowed") is False,
        "local_runner_disabled": policy.get("local_runner_allowed") is False,
        "self_hosted_runner_disabled": policy.get("self_hosted_runner_allowed") is False,
        "paid_llm_api_not_required": policy.get("paid_llm_api_required") is False,
        "missing_credentials_fail_closed": policy.get("fail_closed_on_missing_credentials") is True,
        "missing_adapter_fail_closed": policy.get("fail_closed_on_missing_adapter") is True,
        "legacy_items_stay_facebook_only": policy.get("legacy_items_without_platform_routing_are_facebook_only") is True,
    }
    for name, passed in ownership.items():
        checks.append({"check": name, "passed": passed})
        if not passed:
            errors.append(f"Social ownership policy failed: {name}")

    workflow_rel = str(registry.get("workflow", "")).strip()
    workflow_path = repo_root / workflow_rel
    if not workflow_rel or not workflow_path.is_file():
        errors.append(f"Missing registered social workflow: {workflow_rel!r}")
        workflow_text = ""
    else:
        workflow_text = workflow_path.read_text(encoding="utf-8")
        lowered = workflow_text.lower()
        if "runs-on: ubuntu-latest" not in workflow_text:
            errors.append("Social workflow must run on GitHub-hosted ubuntu-latest")
        if "runs-on: self-hosted" in lowered or "[self-hosted" in lowered:
            errors.append("Social workflow may not use a self-hosted/local runner")
        if "actions/checkout@" not in workflow_text:
            errors.append("Social workflow must check out the canonical repository")
        if "validate_social_engine.py" not in workflow_text:
            errors.append("Social workflow does not execute the ownership validator")
        cron = str(registry.get("cadence", {}).get("cron", "")).strip()
        if not cron or not cron_declared(workflow_text, cron):
            errors.append(f"Registered social cron is missing from workflow: {cron!r}")
        if "github.event_name != 'pull_request'" not in workflow_text:
            errors.append("Social workflow does not explicitly block publication in PRs")

    if automation_path.is_file():
        automation = load_json(automation_path)
        matching = [
            job
            for job in automation.get("jobs", [])
            if job.get("kind") == "multi_channel_social_distribution"
        ]
        if len(matching) != 1:
            errors.append("Automation registry must contain exactly one multi-channel social job")
        elif matching[0].get("workflow") != workflow_rel:
            errors.append("Automation registry social workflow does not match channel registry")
    else:
        errors.append("Missing valcea-clar/engine/automation_registry.json")

    channels = registry.get("channels", [])
    if not isinstance(channels, list) or not channels:
        errors.append("Social channel registry has no channels")
        channels = []

    expected_active = registry.get("required_active_direct_channels", [])
    if not isinstance(expected_active, list) or not expected_active:
        errors.append("required_active_direct_channels must be a non-empty array")
        expected_active = []
    expected_active = [str(value) for value in expected_active]

    seen: set[str] = set()
    active: list[str] = []
    scan_paths: list[Path] = [registry_path, workflow_path]
    for channel in channels:
        channel_id = str(channel.get("channel_id", "")).strip()
        if not channel_id or channel_id in seen:
            errors.append(f"Invalid or duplicate channel_id: {channel_id!r}")
            continue
        seen.add(channel_id)

        status = str(channel.get("status", "")).strip()
        direct = channel.get("direct_publication_enabled") is True
        adapter = channel.get("adapter")
        config_rel = str(channel.get("config", "")).strip()

        if status == "active":
            active.append(channel_id)
            if not direct:
                errors.append(f"Active channel {channel_id} must enable direct publication")
            if not isinstance(adapter, str) or not adapter.strip():
                errors.append(f"Active channel {channel_id} has no adapter")
                continue
            adapter_path = repo_root / adapter
            scan_paths.append(adapter_path)
            if not adapter_path.is_file():
                errors.append(f"Active channel {channel_id} adapter is missing: {adapter}")
            elif social_root not in adapter_path.resolve().parents:
                errors.append(f"Active channel {channel_id} adapter must live in valcea-clar/social")
            elif adapter_path.name not in workflow_text:
                errors.append(f"Social workflow does not execute {channel_id} adapter {adapter_path.name}")

            if not config_rel:
                errors.append(f"Active channel {channel_id} has no CHANNEL_CONFIG")
            else:
                config_path = repo_root / config_rel
                scan_paths.append(config_path)
                if not config_path.is_file():
                    errors.append(f"Active channel {channel_id} config is missing: {config_rel}")
                elif config_path.name not in workflow_text:
                    errors.append(f"Social workflow does not validate {channel_id} config {config_path.name}")

            for field in ("outbox", "state"):
                rel = str(channel.get(field, "")).strip()
                if not rel or not (repo_root / rel).is_file():
                    errors.append(f"Active channel {channel_id} missing {field}: {rel!r}")

            credentials = channel.get("credentials")
            if not isinstance(credentials, dict) or not credentials:
                errors.append(f"Active channel {channel_id} must reference runtime credentials")
            else:
                for key, value in credentials.items():
                    text = str(value or "").strip()
                    if key.endswith("secret") and not text:
                        errors.append(f"Active channel {channel_id} has an empty secret reference")
                    if key.endswith("token") and text:
                        errors.append(f"Raw token field is forbidden for active channel {channel_id}")
                    if any(marker in text.upper() for marker in ("BEARER ", "ACCESS_TOKEN=")):
                        errors.append(f"Credential reference for {channel_id} appears to contain a raw token")

            for prepare in channel.get("prepare", []):
                rel = str(prepare).strip()
                if not rel or not (repo_root / rel).is_file():
                    errors.append(f"Active channel {channel_id} missing prepare step: {rel!r}")
        else:
            if direct:
                errors.append(f"Inactive channel {channel_id} may not enable direct publication")
            if adapter not in (None, ""):
                errors.append(f"Inactive channel {channel_id} may not declare an unverified adapter")

        checks.append(
            {
                "check": f"channel:{channel_id}",
                "status": status,
                "direct_publication_enabled": direct,
            }
        )

    if active != expected_active:
        errors.append(
            f"Active direct channels must be {expected_active!r}; found {active!r}"
        )
    if expected_active != ["facebook", "instagram", "tiktok"]:
        errors.append(
            "Current required direct-adapter set must be exactly "
            "['facebook', 'instagram', 'tiktok']"
        )

    for path in sorted(set(scan_paths)):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker, label in FORBIDDEN_MARKERS.items():
            if marker.lower() in text.lower():
                errors.append(
                    f"Forbidden social runtime dependency ({label}) in "
                    f"{path.relative_to(repo_root).as_posix()}"
                )

    return {
        "checked_at": utc_now(),
        "status": "PASS" if not errors else "FAIL",
        "execution_owner": registry.get("execution_owner"),
        "workflow": workflow_rel,
        "registered_channels": len(channels),
        "active_direct_channels": active,
        "chatgpt_direct_publication_allowed": chatgpt.get("direct_publication_allowed"),
        "errors": errors,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that social publishing is owned only by CIVORA."
    )
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    report = validate(repo_root)
    if args.report:
        target = args.report if args.report.is_absolute() else repo_root / args.report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
