#!/usr/bin/env python3
"""Render VÂLCEA CLAR Public UX with freshness-first live-story ranking.

This module is a derived presentation adapter only. It delegates all filtering,
rendering, taxonomy, holds and validation to ``public_ux_reset`` and changes
only the order of already-published reader-facing stories:

    live publication -> first publication freshness -> editorial priority ->
    current activity -> stable story id

``last_seen_at`` is deliberately a last-resort timestamp because an old story
can be re-seen during a new newsroom transaction without becoming newly
published. This prevents yesterday's still-active dossiers from hiding stories
that were actually first published today.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Any

import public_ux_reset as base

_ORIGINAL_UNION = base.union_stories


def publication_stamp(story: dict[str, Any]) -> float:
    for key in ("first_published_at", "published_at", "last_seen_at"):
        value = str(story.get(key) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def rank_key(story: dict[str, Any], live_ids: set[str]) -> tuple:
    sid = str(story.get("id") or "")
    return (
        0 if sid in live_ids else 1,
        -publication_stamp(story),
        -int(story.get("priority") or 0),
        -int(bool(story.get("active_now"))),
        sid,
    )


def union_stories(feed: dict[str, Any], archive: dict[str, Any]):
    stories, live_ids = _ORIGINAL_UNION(feed, archive)
    stories.sort(key=lambda row: rank_key(row, live_ids))
    return stories, live_ids


base.union_stories = union_stories


def self_test() -> int:
    live = {"fresh", "old-active", "fresh-lower-priority"}
    fresh = {
        "id": "fresh",
        "priority": 100,
        "active_now": False,
        "first_published_at": "2026-08-22T09:32:36+03:00",
        "last_seen_at": "2026-08-22T09:32:40+03:00",
    }
    old_active = {
        "id": "old-active",
        "priority": 100,
        "active_now": True,
        "first_published_at": "2026-08-21T12:27:59+03:00",
        "last_seen_at": "2026-08-22T09:32:40+03:00",
    }
    fresh_lower = {
        "id": "fresh-lower-priority",
        "priority": 99,
        "active_now": True,
        "first_published_at": "2026-08-22T09:32:35+03:00",
    }
    archived_newer = {
        "id": "archived-newer",
        "priority": 100,
        "first_published_at": "2026-08-22T09:33:00+03:00",
    }
    assert rank_key(fresh, live) < rank_key(old_active, live)
    assert rank_key(fresh, live) < rank_key(fresh_lower, live)
    assert rank_key(fresh_lower, live) < rank_key(old_active, live)
    assert rank_key(fresh, live) < rank_key(archived_newer, live)
    print("VÂLCEA CLAR freshness-first Public UX ranking self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.check:
        base.validate()
        return 0
    state = base.build()
    print(json.dumps({
        "status": "PASS",
        "stories": state["safe_story_count"],
        "live": state["live_story_count"],
        "navigation": state["navigation_contract"],
        "ranking": "live_first_publication_freshness_priority_activity",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
