#!/usr/bin/env python3
"""Deterministic related-story ranking for LOCAL NEWS OS.

This module never decides whether a story is publishable. Callers must pass only
stories that already cleared their editorial publication gate. The helper only
orders eligible internal links using stable metadata so cross-linking cannot
promote hidden candidates or invent semantic relationships.
"""
from __future__ import annotations

import argparse


def _priority(story: dict) -> int:
    try:
        return int(story.get("priority") or 0)
    except (TypeError, ValueError):
        return 0


def _section(story: dict) -> str:
    return str(story.get("section") or "").strip().casefold()


def rank_related(current: dict, candidates: list[dict], limit: int = 3) -> list[dict]:
    """Return deterministic internal-link candidates.

    Same-section stories are preferred, then higher editorial priority, then a
    stable story id. No content inference is performed.
    """
    if limit <= 0:
        return []

    current_id = str(current.get("id") or "").strip()
    current_section = _section(current)
    ranked: list[tuple[int, int, str, dict]] = []

    for story in candidates:
        story_id = str(story.get("id") or "").strip()
        headline = str(story.get("headline") or "").strip()
        if not story_id or story_id == current_id or not headline:
            continue
        same_section = 1 if current_section and _section(story) == current_section else 0
        ranked.append((-same_section, -_priority(story), story_id, story))

    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in ranked[:limit]]


def self_test() -> None:
    current = {"id": "a", "section": "CULTURA", "priority": 100, "headline": "A"}
    candidates = [
        current,
        {"id": "b", "section": "SPORT", "priority": 99, "headline": "B"},
        {"id": "c", "section": "CULTURA", "priority": 10, "headline": "C"},
        {"id": "d", "section": "SPORT", "priority": 80, "headline": "D"},
        {"id": "missing-headline", "section": "CULTURA", "priority": 999},
    ]
    assert [row["id"] for row in rank_related(current, candidates, limit=3)] == ["c", "b", "d"]
    assert rank_related(current, candidates, limit=0) == []
    assert all(row["id"] != "a" for row in rank_related(current, candidates, limit=10))
    print("Related-story ranking self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    parser.error("Use --self-test; this module is imported by instance renderers.")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
