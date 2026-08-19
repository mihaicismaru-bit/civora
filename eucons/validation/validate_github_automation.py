#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "eucons" / "ops" / "github_automation_contract.json"

FORBIDDEN_WRITE_MARKERS = [
    "contents: write",
    "actions: write",
    "checks: write",
    "deployments: write",
    "id-token: write",
    "issues: write",
    "pages: write",
    "pull-requests: write",
]
FORBIDDEN_SIDE_EFFECT_MARKERS = [
    "git push",
    "gh pr ",
    "gh api ",
    "deploy-pages",
    "pages deploy",
    "facebook.com/",
    "graph.facebook.com",
    "api.linkedin.com",
    "smtp",
    "sendmail",
]


def fail(message: str) -> None:
    raise SystemExit(message)


def has_trigger(text: str, trigger: str) -> bool:
    if trigger == "schedule":
        return bool(re.search(r"(?m)^\s{2}schedule:\s*$", text))
    return bool(re.search(rf"(?m)^\s{{2}}{re.escape(trigger)}:\s*$", text))


def main() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    if contract["engine_id"] != "EUCONS_E22_GITHUB_AUTOMATION":
        fail("E22 engine id drift")
    if contract["production_side_effects_enabled"] is not False:
        fail("E22 must remain side-effect free")
    policy = contract["execution_policy"]
    if policy["permissions"] != {"contents": "read"} or not policy["write_permissions_forbidden"]:
        fail("E22 permissions contract must remain read-only")

    workflows: dict[str, str] = {}
    for workflow_id, spec in contract["workflows"].items():
        path = ROOT / spec["path"]
        if not path.is_file():
            fail(f"{workflow_id}: workflow missing: {spec['path']}")
        text = path.read_text(encoding="utf-8")
        workflows[workflow_id] = text
        for trigger in spec["required_triggers"]:
            if not has_trigger(text, trigger):
                fail(f"{workflow_id}: missing trigger {trigger}")
        if "permissions:\n  contents: read" not in text:
            fail(f"{workflow_id}: explicit contents:read permission missing")
        if "concurrency:" not in text or "cancel-in-progress: true" not in text:
            fail(f"{workflow_id}: concurrency cancellation boundary missing")
        lowered = text.lower()
        for marker in FORBIDDEN_WRITE_MARKERS:
            if marker in lowered:
                fail(f"{workflow_id}: forbidden write permission {marker}")
        for marker in FORBIDDEN_SIDE_EFFECT_MARKERS:
            if marker in lowered:
                fail(f"{workflow_id}: forbidden E22 side-effect marker {marker}")

    expected_actions = contract["official_actions"]
    for workflow_id in ["build", "scheduler", "reconciliation", "health"]:
        text = workflows[workflow_id]
        if expected_actions["checkout"] not in text:
            fail(f"{workflow_id}: checkout action version drift")
        if expected_actions["setup_python"] not in text:
            fail(f"{workflow_id}: setup-python action version drift")
        if expected_actions["upload_artifact"] not in text:
            fail(f"{workflow_id}: upload-artifact action version drift")
        if "retention-days: 14" not in text or "if-no-files-found: error" not in text:
            fail(f"{workflow_id}: artifact retention/fail-closed upload policy missing")

    quality = workflows["quality"]
    if "Validate EUCONS GitHub automation" not in quality or "validate_github_automation.py" not in quality:
        fail("quality: E22 validator is not wired into canonical quality gate")
    if "'.github/workflows/eucons-*.yml'" not in quality:
        fail("quality: EUCONS workflow changes do not trigger the quality gate")

    build = workflows["build"]
    if "build_public_site.py --target /tmp/eucons-site" not in build or "github_automation.py build-receipt" not in build:
        fail("build: deterministic static build/receipt contract missing")
    if "deploy" in re.sub(r"deployment_performed|production_deployment", "", build.lower()):
        fail("build: deployment behavior must not be introduced in E22")

    scheduler = workflows["scheduler"]
    if f"cron: '{contract['scheduler']['cadence']}'" not in scheduler:
        fail("scheduler: cadence drift")
    required_scheduler_checks = [
        "validate_opportunity_bridge.py",
        "validate_editorial_loop.py",
        "validate_email_engine.py",
        "validate_analytics_engine.py",
        "validate_privacy_security.py",
        "github_automation.py schedule",
    ]
    for marker in required_scheduler_checks:
        if marker not in scheduler:
            fail(f"scheduler: missing safe dry-run check {marker}")
    if contract["scheduler"]["development_reference_time"] not in scheduler:
        fail("scheduler: deterministic development reference time missing")

    reconciliation = workflows["reconciliation"]
    if f"cron: '{contract['reconciliation']['cadence']}'" not in reconciliation:
        fail("reconciliation: cadence drift")
    if "github_automation.py reconcile" not in reconciliation:
        fail("reconciliation: read-only reconciler missing")

    health = workflows["health"]
    if f"cron: '{contract['health']['cadence']}'" not in health:
        fail("health: cadence drift")
    if "github_automation.py health" not in health:
        fail("health: closed-gate health check missing")

    helper = (ROOT / "eucons" / "ops" / "github_automation.py").read_text(encoding="utf-8")
    if "canonical_state_mutated\": False" not in helper and '"canonical_state_mutated": False' not in helper:
        fail("E22 helper does not explicitly report read-only reconciliation")
    if "external_side_effects\": False" not in helper and '"external_side_effects": False' not in helper:
        fail("E22 helper does not explicitly report side-effect-free execution")

    print("EUCONS E22 GitHub Automation: PASS (quality/build/scheduler/reconciliation/health are read-only and fail-closed)")


if __name__ == "__main__":
    main()
