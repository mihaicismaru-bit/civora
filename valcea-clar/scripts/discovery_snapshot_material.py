#!/usr/bin/env python3
"""Detect material changes in non-publishable VÂLCEA CLAR discovery snapshots.

The Live Newsroom must keep diagnostics current without committing a new
heartbeat every five minutes. This comparator ignores scan-time fields while
preserving candidate, routing, policy and editorial-decision changes.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def scrub_auto(doc: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(doc)
    value.pop("generated_at", None)
    facts = value.get("facts")
    if isinstance(facts, list):
        normalized: list[dict[str, Any]] = []
        for row in facts:
            if not isinstance(row, dict):
                continue
            item = copy.deepcopy(row)
            item.pop("discovered_at", None)
            normalized.append(item)
        normalized.sort(key=lambda row: str(row.get("id") or ""))
        value["facts"] = normalized
    return value


def scrub_decision(doc: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(doc)
    value.pop("evaluated_local", None)
    return value


def material_change(
    current_auto: dict[str, Any],
    previous_auto: dict[str, Any],
    current_decision: dict[str, Any],
    previous_decision: dict[str, Any],
) -> bool:
    return (
        scrub_auto(current_auto) != scrub_auto(previous_auto)
        or scrub_decision(current_decision) != scrub_decision(previous_decision)
    )


def self_test() -> None:
    a = {
        "generated_at": "2026-08-18T15:00:00+03:00",
        "facts": [{"id": "x", "headline": "A", "discovered_at": "2026-08-18T15:00:00+03:00"}],
    }
    b = {
        "generated_at": "2026-08-18T15:05:00+03:00",
        "facts": [{"id": "x", "headline": "A", "discovered_at": "2026-08-18T15:05:00+03:00"}],
    }
    d1 = {"evaluated_local": "2026-08-18T15:00:00+03:00", "changed": False, "rejected": []}
    d2 = {"evaluated_local": "2026-08-18T15:05:00+03:00", "changed": False, "rejected": []}
    assert material_change(a, b, d1, d2) is False
    b["facts"][0]["headline"] = "B"
    assert material_change(a, b, d1, d2) is True
    b["facts"][0]["headline"] = "A"
    d2["rejected"] = [{"id": "y", "reason": "title_date_only"}]
    assert material_change(a, b, d1, d2) is True
    print("DISCOVERY_SNAPSHOT_MATERIAL_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-auto")
    parser.add_argument("--previous-auto")
    parser.add_argument("--current-decision")
    parser.add_argument("--previous-decision")
    parser.add_argument("--changed-exit-code", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    required = [args.current_auto, args.previous_auto, args.current_decision, args.previous_decision]
    if not all(required):
        parser.error("snapshot paths are required unless --self-test is used")
    changed = material_change(
        load(Path(args.current_auto)),
        load(Path(args.previous_auto)),
        load(Path(args.current_decision)),
        load(Path(args.previous_decision)),
    )
    print(json.dumps({"status": "PASS", "material_change": changed}))
    return args.changed_exit_code if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
