#!/usr/bin/env python3
"""Conflict-safe merge of text-first social state after a production run.

Remote publication can happen before `main` advances again. This helper merges
the desired state captured immediately after publishing into the newest main
state so a concurrent photo/social run cannot be overwritten by stale files.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        return {} if default is None else default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def merge_map(current: Any, desired: Any) -> dict[str, Any]:
    left = current if isinstance(current, dict) else {}
    right = desired if isinstance(desired, dict) else {}
    return {**left, **right}


def merge_facebook(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    merged = {**current, **desired}
    merged["published"] = merge_map(current.get("published"), desired.get("published"))
    return merged


def merge_threads_outbox(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    merged = {**current, **desired}
    by_id: dict[str, dict[str, Any]] = {}
    for source in (current.get("items"), desired.get("items")):
        if not isinstance(source, list):
            continue
        for item in source:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            if item_id:
                by_id[item_id] = item
    merged["items"] = list(by_id.values())
    return merged


def merge_threads_state(current: dict[str, Any], desired: dict[str, Any]) -> dict[str, Any]:
    merged = {**current, **desired}
    published = merge_map(current.get("published"), desired.get("published"))
    failures = merge_map(current.get("failures"), desired.get("failures"))
    for item_id in published:
        failures.pop(item_id, None)
    merged["published"] = published
    merged["failures"] = failures
    return merged


def self_test() -> int:
    fb = merge_facebook(
        {"published": {"old": {"id": 1}}, "last": "current"},
        {"published": {"new": {"id": 2}}, "last": "desired"},
    )
    assert set(fb["published"]) == {"old", "new"} and fb["last"] == "desired"

    outbox = merge_threads_outbox(
        {"items": [{"id": "a", "status": "old"}, {"id": "b", "status": "old"}]},
        {"items": [{"id": "b", "status": "new"}, {"id": "c", "status": "new"}]},
    )
    rows = {row["id"]: row for row in outbox["items"]}
    assert rows["b"]["status"] == "new" and set(rows) == {"a", "b", "c"}

    state = merge_threads_state(
        {"published": {"a": {}}, "failures": {"b": {"manual_reconciliation_required": True}}},
        {"published": {"b": {}}, "failures": {}},
    )
    assert set(state["published"]) == {"a", "b"} and "b" not in state["failures"]
    print("VÂLCEA CLAR text-first social state merger self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--desired-facebook", type=Path)
    parser.add_argument("--desired-threads-outbox", type=Path)
    parser.add_argument("--desired-threads-state", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    if not args.desired_facebook or not args.desired_threads_outbox or not args.desired_threads_state:
        raise SystemExit("desired state paths are required")

    fb_path = VC / "social" / "facebook_state.json"
    threads_outbox_path = VC / "social" / "threads_outbox.json"
    threads_state_path = VC / "social" / "threads_state.json"

    write(fb_path, merge_facebook(load(fb_path), load(args.desired_facebook)))
    write(
        threads_outbox_path,
        merge_threads_outbox(load(threads_outbox_path), load(args.desired_threads_outbox)),
    )
    write(
        threads_state_path,
        merge_threads_state(load(threads_state_path), load(args.desired_threads_state)),
    )
    print(json.dumps({"status": "PASS", "merged": [str(fb_path), str(threads_outbox_path), str(threads_state_path)]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
