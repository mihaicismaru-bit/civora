#!/usr/bin/env python3
"""Idempotently promote verified supplemental VÂLCEA CLAR stories into the canonical registry."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
FACTS = ROOT / "editorial" / "facts_registry.json"
SUPPLEMENT = ROOT / "editorial" / "supplemental_facts_registry.json"
CORE = REPO_ROOT / "local-news-os" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from temporal_freshness import durable_story_temporal_violations  # noqa: E402


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validate_supplement(document: dict) -> list[dict]:
    rows = document.get("facts") or []
    if not isinstance(rows, list) or not rows:
        raise ValueError("supplemental facts must be a non-empty list")
    seen: set[str] = set()
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("supplemental story must be an object")
        story_id = str(item.get("id") or "").strip()
        if not story_id or story_id in seen:
            raise ValueError(f"invalid or duplicate story id: {story_id!r}")
        seen.add(story_id)
        if item.get("status") != "verified":
            raise ValueError(f"supplemental story must be verified: {story_id}")
        if int(item.get("confidence") or 0) < 90:
            raise ValueError(f"supplemental story confidence below publication floor: {story_id}")
        if not str(item.get("headline") or "").strip() or not str(item.get("dek") or "").strip():
            raise ValueError(f"supplemental headline/dek missing: {story_id}")
        if not [p for p in item.get("paragraphs") or [] if str(p).strip()]:
            raise ValueError(f"supplemental body missing: {story_id}")
        if not [s for s in item.get("sources") or [] if isinstance(s, dict) and str(s.get("url") or "").strip()]:
            raise ValueError(f"supplemental sources missing: {story_id}")
        violations = durable_story_temporal_violations(item, "ro-RO")
        if violations:
            raise ValueError(f"durable temporal language violation in {story_id}: {violations}")
    return rows


def merge(base: dict, supplemental_rows: list[dict]) -> tuple[dict, int, int]:
    rows = base.get("facts") or []
    if not isinstance(rows, list):
        raise ValueError("canonical facts registry has invalid facts field")
    supplemental_by_id = {str(row["id"]): row for row in supplemental_rows}
    replaced = 0
    merged: list[dict] = []
    for row in rows:
        story_id = str(row.get("id") or "") if isinstance(row, dict) else ""
        if story_id in supplemental_by_id:
            merged.append(supplemental_by_id.pop(story_id))
            replaced += 1
        else:
            merged.append(row)
    appended = len(supplemental_by_id)
    merged.extend(supplemental_by_id.values())
    output = dict(base)
    output["facts"] = merged
    return output, replaced, appended


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    base = load(FACTS)
    supplemental_rows = validate_supplement(load(SUPPLEMENT))
    output, replaced, appended = merge(base, supplemental_rows)
    print(json.dumps({
        "status": "PASS",
        "supplemental": len(supplemental_rows),
        "replaced": replaced,
        "appended": appended,
        "canonical_total": len(output.get("facts") or []),
    }, ensure_ascii=False))
    if not args.check:
        FACTS.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
