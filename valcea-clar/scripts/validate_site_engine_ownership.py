#!/usr/bin/env python3
"""Fail closed when VÂLCEA CLAR automation escapes the CIVORA site engine."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORBIDDEN_RUNTIME_MARKERS = {
    "OPENAI_API_KEY": "OpenAI API secret",
    "api.openai.com": "OpenAI API endpoint",
    "chat.openai.com": "ChatGPT web runtime",
    "chatgpt.com/backend-api": "ChatGPT private runtime endpoint",
    "ANTHROPIC_API_KEY": "Anthropic API secret",
    "api.anthropic.com": "Anthropic API endpoint",
    "GEMINI_API_KEY": "Gemini API secret",
}

RUNTIME_SUFFIXES = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".sh"}
POLICY_VALIDATORS = {
    "scripts/validate_site_engine_ownership.py",
    "social/validate_social_engine.py",
}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def cron_declared(workflow_text: str, cron: str) -> bool:
    candidates = (
        f'cron: "{cron}"',
        f"cron: '{cron}'",
        f"cron: {cron}",
    )
    return any(candidate in workflow_text for candidate in candidates)


def runtime_files(site_root: Path) -> list[Path]:
    ignored_parts = {"dist", "__pycache__", ".git", "site/runtime"}
    files: list[Path] = []
    for path in site_root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in RUNTIME_SUFFIXES:
            continue
        relative = path.relative_to(site_root).as_posix()
        if relative in POLICY_VALIDATORS:
            continue
        if any(relative == part or relative.startswith(f"{part}/") for part in ignored_parts):
            continue
        files.append(path)
    return sorted(files)


def validate(repo_root: Path) -> dict[str, Any]:
    site_root = repo_root / "valcea-clar"
    registry_path = site_root / "engine" / "automation_registry.json"
    errors: list[str] = []
    checks: list[dict[str, Any]] = []

    if not registry_path.is_file():
        return {
            "checked_at": utc_now(),
            "status": "FAIL",
            "errors": [f"Missing registry: {registry_path.relative_to(repo_root)}"],
            "checks": [],
        }

    registry = load_json(registry_path)
    chatgpt = registry.get("chatgpt", {})

    ownership_checks = {
        "execution_owner": registry.get("execution_owner") == "civora_site_engine",
        "scheduler": registry.get("scheduler") == "github_actions",
        "state_owner": registry.get("state_owner") == "repository",
        "chatgpt_scheduled_tasks_disabled": chatgpt.get("scheduled_tasks_allowed") is False,
        "chatgpt_conversation_runtime_disabled": chatgpt.get("conversation_runtime_allowed") is False,
        "chatgpt_direct_social_publication_disabled": chatgpt.get("direct_social_publication_allowed") is False,
        "chatgpt_social_credential_access_disabled": chatgpt.get("social_credential_access_allowed") is False,
        "paid_llm_api_not_required": registry.get("content_engine", {}).get("paid_llm_api_required") is False,
        "local_agent_runtime_not_required": registry.get("content_engine", {}).get("local_agent_runtime_required") is False,
        "self_hosted_runner_disabled": registry.get("content_engine", {}).get("self_hosted_runner_allowed") is False,
    }
    for name, passed in ownership_checks.items():
        checks.append({"check": name, "passed": passed})
        if not passed:
            errors.append(f"Ownership policy failed: {name}")

    jobs = registry.get("jobs", [])
    if not jobs:
        errors.append("Automation registry has no jobs.")

    seen_ids: set[str] = set()
    seen_workflows: set[str] = set()
    workflow_texts: dict[str, str] = {}

    for job in jobs:
        job_id = str(job.get("id", "")).strip()
        workflow = str(job.get("workflow", "")).strip()
        owner = job.get("owner")
        schedule = job.get("schedule", [])

        if not job_id or job_id in seen_ids:
            errors.append(f"Invalid or duplicate job id: {job_id!r}")
        seen_ids.add(job_id)

        if not workflow or workflow in seen_workflows:
            errors.append(f"Invalid or duplicate workflow for {job_id}: {workflow!r}")
        seen_workflows.add(workflow)

        if owner != "site_engine":
            errors.append(f"{job_id}: owner must be site_engine, got {owner!r}")

        workflow_path = repo_root / workflow
        if not workflow_path.is_file():
            errors.append(f"{job_id}: missing workflow {workflow}")
            continue

        text = workflow_path.read_text(encoding="utf-8")
        workflow_texts[workflow] = text
        lowered = text.lower()

        if "runs-on: ubuntu-latest" not in text:
            errors.append(f"{job_id}: workflow must run on GitHub-hosted ubuntu-latest")
        if "runs-on: self-hosted" in lowered or "[self-hosted" in lowered:
            errors.append(f"{job_id}: self-hosted/local runners are forbidden")
        if "actions/checkout@" not in text:
            errors.append(f"{job_id}: workflow does not check out the canonical repository")

        for cron in schedule:
            if not cron_declared(text, str(cron)):
                errors.append(f"{job_id}: missing registered cron {cron!r}")

        checks.append(
            {
                "check": f"workflow:{job_id}",
                "passed": not any(error.startswith(f"{job_id}:") for error in errors),
                "workflow": workflow,
                "schedule": schedule,
            }
        )

    editions = workflow_texts.get(".github/workflows/valcea-clar-editions.yml", "")
    required_edition_markers = {
        "deterministic_zero_llm_v2": "deterministic zero-LLM generator",
        "llm_required'] is False": "LLM-not-required assertion",
        "external_paid_api_required'] is False": "paid-API-not-required assertion",
    }
    for marker, label in required_edition_markers.items():
        passed = marker in editions
        checks.append({"check": f"editions:{label}", "passed": passed})
        if not passed:
            errors.append(f"Autonomous editions missing {label}.")

    social = workflow_texts.get(".github/workflows/valcea-clar-social-publishing.yml", "")
    required_social_markers = {
        "validate_social_engine.py": "social ownership validator",
        "facebook_publish.py --apply": "native Facebook publishing adapter",
        "VALCEA_FB_PAGE_ACCESS_TOKEN": "runtime secret reference",
        "github.event_name != 'pull_request'": "no publishing from pull requests",
    }
    for marker, label in required_social_markers.items():
        passed = marker in social
        checks.append({"check": f"social:{label}", "passed": passed})
        if not passed:
            errors.append(f"Social publication workflow missing {label}.")

    scan_paths = [repo_root / workflow for workflow in seen_workflows]
    scan_paths.extend(runtime_files(site_root))
    scanned = 0
    for path in sorted(set(scan_paths)):
        if not path.is_file():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="replace")
        for marker, label in FORBIDDEN_RUNTIME_MARKERS.items():
            if marker.lower() in text.lower():
                errors.append(
                    f"Forbidden runtime dependency ({label}) in "
                    f"{path.relative_to(repo_root).as_posix()}"
                )

    retired = registry.get("retired_external_monitors", [])
    for item in retired:
        if item.get("status") != "retired":
            errors.append(
                f"External monitor {item.get('id', '<unknown>')} is not marked retired."
            )

    retired_workflows = registry.get("retired_workflows", [])
    for item in retired_workflows:
        path = str(item.get("path", "")).strip()
        if item.get("status") != "retired":
            errors.append(f"Workflow {path or '<unknown>'} is not marked retired.")
        if path and (repo_root / path).exists():
            errors.append(f"Retired workflow still exists and could execute: {path}")

    status = "PASS" if not errors else "FAIL"
    return {
        "checked_at": utc_now(),
        "status": status,
        "execution_owner": registry.get("execution_owner"),
        "scheduler": registry.get("scheduler"),
        "registered_jobs": len(jobs),
        "runtime_files_scanned": scanned,
        "retired_external_monitors": [item.get("id") for item in retired],
        "retired_workflows": [item.get("path") for item in retired_workflows],
        "errors": errors,
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate that all CIVORA/VÂLCEA CLAR automation is site-engine owned."
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        help="Repository root. Defaults to the root inferred from this script.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON report path. Relative paths are resolved from the repository root.",
    )
    args = parser.parse_args()

    repo_root = args.repo_root.resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    report = validate(repo_root)

    if args.report:
        report_path = args.report
        if not report_path.is_absolute():
            report_path = repo_root / report_path
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
