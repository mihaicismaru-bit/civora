#!/usr/bin/env python3
"""Read-only/dry-run diagnostic for the VÂLCEA CLAR live publication transaction.

Runs the canonical build/render steps in the current checkout, records the first
failing step, and verifies that a requested story reaches the rendered manifest
and live feed. It has no publication authority: it never commits newsroom state,
dispatches social workflows, or pushes repository changes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
TZ = ZoneInfo("Europe/Bucharest")
PUBLICATION_AUTHORITY = "NONE"


def tail(text: str, limit: int = 4000) -> str:
    value = text or ""
    return value[-limit:]


def run_step(name: str, argv: list[str]) -> dict[str, Any]:
    proc = subprocess.run(
        argv,
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    return {
        "name": name,
        "argv": argv,
        "returncode": proc.returncode,
        "ok": proc.returncode == 0,
        "stdout_tail": tail(proc.stdout),
        "stderr_tail": tail(proc.stderr),
    }


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def diagnose(story_id: str | None) -> dict[str, Any]:
    py = sys.executable
    steps: list[dict[str, Any]] = []
    commands = [
        ("newsroom_decide", [py, "valcea-clar/scripts/newsroom_decide.py"]),
        ("build_public_data", [py, "valcea-clar/scripts/build_public_data.py"]),
        ("generate_evening_edition", [py, "valcea-clar/scripts/generate_edition.py", "--slot", "evening"]),
        ("render_frontpage", [py, "valcea-clar/scripts/render_frontpage.py"]),
        ("render_story_pages", [py, "valcea-clar/scripts/render_story_pages.py"]),
        ("build_live_feed", [py, "valcea-clar/scripts/build_live_feed.py"]),
        ("build_sites_export", [py, "valcea-clar/scripts/build_sites_export.py"]),
        ("overlay_runtime_export", [py, "valcea-clar/scripts/overlay_runtime_export.py"]),
    ]
    for name, argv in commands:
        try:
            result = run_step(name, argv)
        except subprocess.TimeoutExpired as exc:
            result = {
                "name": name,
                "argv": argv,
                "returncode": None,
                "ok": False,
                "timeout": True,
                "stdout_tail": tail(exc.stdout if isinstance(exc.stdout, str) else ""),
                "stderr_tail": tail(exc.stderr if isinstance(exc.stderr, str) else ""),
            }
        steps.append(result)
        if not result["ok"]:
            break

    decision = load_json(ROOT / "site" / "newsroom_decision.json")
    manifest = load_json(ROOT / "site" / "runtime" / "stiri" / "manifest.json")
    live_feed = load_json(ROOT / "site" / "runtime" / "live-feed.json")
    manifest_ids = [str(row.get("id")) for row in manifest.get("stories", []) if isinstance(row, dict)]
    feed_ids = [str(row.get("id")) for row in live_feed.get("stories", []) if isinstance(row, dict)]
    requested = str(story_id or "").strip()
    return {
        "schema_version": "1.0",
        "publication_authority": PUBLICATION_AUTHORITY,
        "diagnostic_only": True,
        "evaluated_local": datetime.now(TZ).isoformat(timespec="seconds"),
        "requested_story_id": requested or None,
        "all_steps_ok": len(steps) == len(commands) and all(step["ok"] for step in steps),
        "first_failed_step": next((step["name"] for step in steps if not step["ok"]), None),
        "steps": steps,
        "decision": {
            "evaluated_local": decision.get("evaluated_local"),
            "changed": decision.get("changed"),
            "publishable_story_count": decision.get("publishable_story_count"),
            "new_story_ids": decision.get("new_story_ids"),
            "requested_story_publishable": requested in (decision.get("publishable_story_ids") or []) if requested else None,
        },
        "render": {
            "manifest_story_count": len(manifest_ids),
            "feed_story_count": len(feed_ids),
            "requested_story_in_manifest": requested in manifest_ids if requested else None,
            "requested_story_in_live_feed": requested in feed_ids if requested else None,
        },
    }


def self_test() -> int:
    assert PUBLICATION_AUTHORITY == "NONE"
    assert tail("abcdef", 3) == "def"
    print("VÂLCEA CLAR newsroom transaction diagnostic self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story-id")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    report = diagnose(args.story_id)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
