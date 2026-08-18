#!/usr/bin/env python3
"""Validate VÂLCEA CLAR generated runtime outputs against the CIVORA scope contract.

This is instance-scoped acceptance coverage for repository_scope.json. It keeps
frequently regenerated operational evidence out of the structural fingerprint
without broadening the exception to editorial configuration or durable facts.
"""
from __future__ import annotations

import fnmatch
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCOPE = ROOT / "local-news-os/persistence/repository_scope.json"

GENERATED_RUNTIME_OUTPUTS = {
    "valcea-clar/editorial/signal_verification_queue.json": ROOT / ".github/workflows/valcea-clar-signal-radar.yml",
    "valcea-clar/editorial/structured_alert_events.json": ROOT / ".github/workflows/valcea-clar-structured-alerts.yml",
}

STRUCTURAL_GUARDS = (
    "valcea-clar/editorial/signal_radar_config.json",
    "valcea-clar/editorial/news_sources.json",
    "valcea-clar/editorial/facts_registry.json",
    "local-news-os/instances/valcea/source_pack.json",
    "local-news-os/instances/valcea/structured_alert_pack.json",
)


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def main() -> int:
    payload = json.loads(SCOPE.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise SystemExit("repository scope schema mismatch")
    refresh_only = tuple(str(value) for value in payload.get("refresh_only", []))

    for output_path, workflow_path in GENERATED_RUNTIME_OUTPUTS.items():
        if not matches(output_path, refresh_only):
            raise SystemExit(f"generated runtime output is structural: {output_path}")
        workflow = workflow_path.read_text(encoding="utf-8")
        if output_path not in workflow:
            raise SystemExit(f"runtime producer no longer persists expected output: {output_path}")

    for path in STRUCTURAL_GUARDS:
        if matches(path, refresh_only):
            raise SystemExit(f"structural config/content was incorrectly made refresh-only: {path}")

    print(
        "VÂLCEA CLAR persistence-scope runtime-output contract: PASS "
        f"({len(GENERATED_RUNTIME_OUTPUTS)} runtime-only / {len(STRUCTURAL_GUARDS)} structural guards)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
