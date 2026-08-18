#!/usr/bin/env python3
"""Fail-closed current/archive projection for the VÂLCEA CLAR reader UX.

The canonical live feed intentionally retains published archive stories. The
presentation layer must not therefore equate "present in live-feed.json" with
"active now". This adapter keeps the existing renderer and archive union, but
supplies it with a current-story identity set derived only from explicit
runtime evidence.

No fact, headline, story body or publication decision is changed here.
"""
from __future__ import annotations

import sys
from typing import Any

import public_ux_reset as base

_BASE_UNION = base.union_stories


def is_current(story: dict[str, Any]) -> bool:
    """Return currentness only from explicit runtime evidence.

    `active_now` is authoritative when present. Older compatible records may
    fall back to the durable `archive_status=active` marker. Unknown states are
    never promoted to current.
    """
    if "active_now" in story:
        return story.get("active_now") is True
    return str(story.get("archive_status") or "").strip().lower() == "active"


def current_union(
    feed: dict[str, Any], archive: dict[str, Any]
) -> tuple[list[dict[str, Any]], set[str]]:
    stories, _legacy_live_ids = _BASE_UNION(feed, archive)
    current_ids = {
        str(story.get("id"))
        for story in (feed.get("stories") or [])
        if isinstance(story, dict) and story.get("id") and is_current(story)
    }
    return stories, current_ids


def install() -> None:
    base.union_stories = current_union


def self_test() -> None:
    feed = {
        "stories": [
            {
                "id": "active",
                "section": "MOBILITATE",
                "headline": "Active",
                "sources": [{"url": "https://example.test/active"}],
                "active_now": True,
                "archive_status": "active",
            },
            {
                "id": "archive-in-feed",
                "section": "CULTURĂ",
                "headline": "Archive",
                "sources": [{"url": "https://example.test/archive"}],
                "active_now": False,
                "archive_status": "published_archive",
            },
            {
                "id": "legacy-active",
                "section": "SPORT",
                "headline": "Legacy active",
                "sources": [{"url": "https://example.test/legacy"}],
                "archive_status": "active",
            },
        ]
    }
    archive = {"stories": []}
    rows, current_ids = current_union(feed, archive)
    assert {str(row.get("id")) for row in rows} == {
        "active",
        "archive-in-feed",
        "legacy-active",
    }
    assert current_ids == {"active", "legacy-active"}
    assert is_current({"active_now": False, "archive_status": "active"}) is False
    assert is_current({"archive_status": "published_archive"}) is False
    assert is_current({}) is False
    print("VÂLCEA CLAR public UX current/archive projection self-test: PASS")


def main() -> int:
    install()
    if "--self-test" in sys.argv[1:]:
        self_test()
        base.self_test()
        return 0
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
