#!/usr/bin/env python3
"""Audit the executable VÂLCEA CLAR GitHub Actions surface.

The canonical automation registry is an allow-list for production orchestration.
This auditor does not assume that an unregistered workflow is dead: it classifies
triggers and permissions so cleanup can retire writers safely and gradually.

Default mode is report-only. ``--strict`` fails when an unregistered autonomous
writer/dispatcher remains; strict mode is intended to become the final cleanup
gate after the legacy surface has been reconciled.
"""
from __future__ import annotations

import argparse
import json
import re
import tempfile
from pathlib import Path
from typing import Any

WORKFLOW_GLOB = "valcea-clar-*.yml"
BACKGROUND_TRIGGERS = ("schedule", "workflow_run", "repository_dispatch")
AUTONOMOUS_TRIGGERS = BACKGROUND_TRIGGERS + ("push",)
TRIGGER_NAMES = (
    "workflow_dispatch",
    "pull_request",
    "pull_request_target",
    "schedule",
    "workflow_run",
    "push",
    "repository_dispatch",
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def declared_trigger(text: str, name: str) -> bool:
    return bool(re.search(rf"(?m)^\s{{0,4}}{re.escape(name)}\s*:\s*(?:$|\[|\{{)", text))


def workflow_permissions(text: str) -> dict[str, bool]:
    contents_write = bool(re.search(r"(?m)^\s+contents\s*:\s*write\s*$", text))
    actions_write = bool(re.search(r"(?m)^\s+actions\s*:\s*write\s*$", text))
    statuses_write = bool(re.search(r"(?m)^\s+statuses\s*:\s*write\s*$", text))
    write_all = bool(re.search(r"(?m)^\s*permissions\s*:\s*write-all\s*$", text))
    return {
        "contents_write": contents_write or write_all,
        "actions_write": actions_write or write_all,
        "statuses_write": statuses_write or write_all,
        "write_all": write_all,
    }


def classify(path: Path, registered: set[str], retired: set[str], repo_root: Path) -> dict[str, Any]:
    rel = path.relative_to(repo_root).as_posix()
    text = path.read_text(encoding="utf-8", errors="replace")
    triggers = {name: declared_trigger(text, name) for name in TRIGGER_NAMES}
    permissions = workflow_permissions(text)
    autonomous = any(triggers[name] for name in AUTONOMOUS_TRIGGERS)
    background_autonomous = any(triggers[name] for name in BACKGROUND_TRIGGERS)
    push_only_autonomous = bool(triggers["push"] and not background_autonomous)

    if rel in registered:
        classification = "REGISTERED"
    elif rel in retired:
        classification = "RETIRED_BUT_PRESENT"
    elif autonomous and permissions["contents_write"]:
        classification = "UNREGISTERED_AUTONOMOUS_WRITER"
    elif autonomous and permissions["actions_write"]:
        classification = "UNREGISTERED_AUTONOMOUS_DISPATCHER"
    elif autonomous:
        classification = "UNREGISTERED_AUTONOMOUS_OBSERVER"
    else:
        classification = "UNREGISTERED_MANUAL_OR_PR_ONLY"

    return {
        "path": rel,
        "classification": classification,
        "autonomous": autonomous,
        "background_autonomous": background_autonomous,
        "push_only_autonomous": push_only_autonomous,
        "triggers": [name for name, enabled in triggers.items() if enabled],
        "permissions": permissions,
    }


def audit(repo_root: Path) -> dict[str, Any]:
    registry_path = repo_root / "valcea-clar" / "engine" / "automation_registry.json"
    if not registry_path.is_file():
        raise SystemExit(f"Missing automation registry: {registry_path}")
    registry = load_json(registry_path)
    registered = {
        str(job.get("workflow") or "").strip()
        for job in registry.get("jobs") or []
        if str(job.get("workflow") or "").strip()
    }
    retired = {
        str(row.get("path") or "").strip()
        for row in registry.get("retired_workflows") or []
        if str(row.get("path") or "").strip()
    }

    workflow_root = repo_root / ".github" / "workflows"
    rows = [
        classify(path, registered, retired, repo_root)
        for path in sorted(workflow_root.glob(WORKFLOW_GLOB))
        if path.is_file()
    ]

    by_class: dict[str, list[str]] = {}
    for row in rows:
        by_class.setdefault(str(row["classification"]), []).append(str(row["path"]))

    unregistered_background_writers = sorted(
        str(row["path"])
        for row in rows
        if row["classification"] == "UNREGISTERED_AUTONOMOUS_WRITER" and row["background_autonomous"]
    )
    unregistered_push_only_writers = sorted(
        str(row["path"])
        for row in rows
        if row["classification"] == "UNREGISTERED_AUTONOMOUS_WRITER" and row["push_only_autonomous"]
    )
    unregistered_background_dispatchers = sorted(
        str(row["path"])
        for row in rows
        if row["classification"] == "UNREGISTERED_AUTONOMOUS_DISPATCHER" and row["background_autonomous"]
    )
    unregistered_background_observers = sorted(
        str(row["path"])
        for row in rows
        if row["classification"] == "UNREGISTERED_AUTONOMOUS_OBSERVER" and row["background_autonomous"]
    )

    dangerous = (
        by_class.get("UNREGISTERED_AUTONOMOUS_WRITER", [])
        + by_class.get("UNREGISTERED_AUTONOMOUS_DISPATCHER", [])
        + by_class.get("RETIRED_BUT_PRESENT", [])
    )
    missing_registered = sorted(path for path in registered if not (repo_root / path).is_file())

    return {
        "schema_version": "1.1",
        "status": "WARN" if dangerous or missing_registered else "PASS",
        "workflow_glob": WORKFLOW_GLOB,
        "workflow_count": len(rows),
        "registered_count": len(registered),
        "registered_present_count": sum(1 for row in rows if row["classification"] == "REGISTERED"),
        "unregistered_autonomous_writer_count": len(by_class.get("UNREGISTERED_AUTONOMOUS_WRITER", [])),
        "unregistered_background_writer_count": len(unregistered_background_writers),
        "unregistered_push_only_writer_count": len(unregistered_push_only_writers),
        "unregistered_autonomous_dispatcher_count": len(by_class.get("UNREGISTERED_AUTONOMOUS_DISPATCHER", [])),
        "unregistered_background_dispatcher_count": len(unregistered_background_dispatchers),
        "unregistered_autonomous_observer_count": len(by_class.get("UNREGISTERED_AUTONOMOUS_OBSERVER", [])),
        "unregistered_background_observer_count": len(unregistered_background_observers),
        "unregistered_manual_or_pr_only_count": len(by_class.get("UNREGISTERED_MANUAL_OR_PR_ONLY", [])),
        "retired_but_present_count": len(by_class.get("RETIRED_BUT_PRESENT", [])),
        "missing_registered": missing_registered,
        "by_class": by_class,
        "priority_cleanup": {
            "background_writers": unregistered_background_writers,
            "background_dispatchers": unregistered_background_dispatchers,
            "background_observers": unregistered_background_observers,
            "push_only_writers": unregistered_push_only_writers,
        },
        "workflows": rows,
        "strict_blockers": dangerous + missing_registered,
    }


def self_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "valcea-clar" / "engine").mkdir(parents=True)
        (root / ".github" / "workflows").mkdir(parents=True)
        registry = {
            "jobs": [{"workflow": ".github/workflows/valcea-clar-core.yml"}],
            "retired_workflows": [{"path": ".github/workflows/valcea-clar-retired.yml"}],
        }
        (root / "valcea-clar" / "engine" / "automation_registry.json").write_text(
            json.dumps(registry), encoding="utf-8"
        )
        (root / ".github" / "workflows" / "valcea-clar-core.yml").write_text(
            "on:\n  schedule:\n    - cron: '*/5 * * * *'\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "valcea-clar-extra.yml").write_text(
            "on:\n  workflow_run:\n    workflows: ['x']\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "valcea-clar-push.yml").write_text(
            "on:\n  push:\n    branches: [main]\npermissions:\n  contents: write\n",
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "valcea-clar-manual.yml").write_text(
            "on:\n  workflow_dispatch:\npermissions:\n  contents: read\n",
            encoding="utf-8",
        )
        (root / ".github" / "workflows" / "valcea-clar-retired.yml").write_text(
            "on:\n  workflow_dispatch:\n",
            encoding="utf-8",
        )
        result = audit(root)
        assert result["registered_present_count"] == 1
        assert result["unregistered_autonomous_writer_count"] == 2
        assert result["unregistered_background_writer_count"] == 1
        assert result["unregistered_push_only_writer_count"] == 1
        assert result["unregistered_manual_or_pr_only_count"] == 1
        assert result["retired_but_present_count"] == 1
        assert result["status"] == "WARN"
    print("VÂLCEA CLAR automation surface auditor self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    repo_root = args.repo_root.resolve() if args.repo_root else Path(__file__).resolve().parents[2]
    result = audit(repo_root)
    if args.report:
        target = args.report if args.report.is_absolute() else repo_root / args.report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.strict and result["strict_blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
