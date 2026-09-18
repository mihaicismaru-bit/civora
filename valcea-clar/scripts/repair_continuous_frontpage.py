#!/usr/bin/env python3
"""Archive-preserving entrypoint for the continuous story-first repair.

The canonical story archive is durable publication state. Historical recap
snapshots may contribute new safe stories, but must never delete or downgrade a
canonical story merely because old recap copy used now-forbidden relative-time
language such as ``azi``. The legacy renderer remains unchanged; this wrapper
only fixes archive input precedence.
"""
from __future__ import annotations

import sys
from datetime import datetime
from typing import Any

import repair_continuous_frontpage_legacy as legacy

_ORIGINAL_COLLECT_ARCHIVE = legacy.collect_archive


def _is_newer(candidate: object, previous: object) -> bool:
    candidate_dt = legacy.parse_stamp(candidate)
    previous_dt = legacy.parse_stamp(previous)
    if candidate_dt is None:
        return False
    if previous_dt is None:
        return True
    return candidate_dt > previous_dt


def collect_archive(now: datetime | None = None) -> list[dict[str, Any]]:
    """Merge canonical archive first, then newer recap rows that pass current gates."""
    effective_now = now or datetime.now(legacy.TZ)
    rows: dict[str, dict[str, Any]] = {}

    seed = legacy.load(legacy.ARCHIVE, {"stories": []})
    for item in seed.get("stories", []):
        if not isinstance(item, dict) or not legacy.public_reader_item(item):
            continue
        ok, _reason = legacy.story_ready(item)
        if not ok:
            continue
        story_id = str(item.get("id") or "").strip()
        if story_id:
            rows[story_id] = dict(item)

    for item in _ORIGINAL_COLLECT_ARCHIVE(effective_now):
        story_id = str(item.get("id") or "").strip()
        if not story_id:
            continue
        previous = rows.get(story_id)
        if previous is None:
            rows[story_id] = dict(item)
            continue
        if _is_newer(item.get("last_seen_at"), previous.get("last_seen_at")):
            # Keep durable enrichment not carried by the recap row while allowing
            # genuinely newer, current-gate-safe copy to supersede older copy.
            rows[story_id] = {**previous, **item}

    return legacy.sort_stories(legacy.mark_activity(list(rows.values()), effective_now))


legacy.collect_archive = collect_archive


def sync_archive_only(now: datetime | None = None) -> dict[str, Any]:
    """Persist durable published-story history without rewriting live runtime.

    The canonical Live Newsroom owns this write. Presentation projectors keep
    treating story_archive.json as read-only input.
    """
    effective_now = now or datetime.now(legacy.TZ)
    stories = collect_archive(effective_now)
    if not stories:
        raise SystemExit("Refusing archive sync: no previously published full stories")

    candidate = legacy.archive_payload(stories, effective_now)
    previous = legacy.load(legacy.ARCHIVE, {})
    comparable_previous = {k: v for k, v in previous.items() if k != "generated_at"}
    comparable_candidate = {k: v for k, v in candidate.items() if k != "generated_at"}
    changed = comparable_previous != comparable_candidate
    if changed:
        legacy.ARCHIVE.write_text(
            legacy.json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    result = {
        "status": "PASS",
        "changed": changed,
        "story_count": len(stories),
        "active_story_count": sum(1 for item in stories if item.get("active_now")),
        "archived_story_count": sum(1 for item in stories if not item.get("active_now")),
        "archive": "site/story_archive.json",
        "runtime_unchanged": True,
    }
    print(legacy.json.dumps(result, ensure_ascii=False))
    return result


def self_test() -> int:
    safe = {
        "id": "archive-safe",
        "headline": "Evenimentul a avut loc în 15 august 2026",
        "dek": "Documentele confirmă programul din 15 august 2026 și păstrează data explicită.",
        "paragraphs": [
            "Acest material de test folosește o dată calendaristică absolută și rămâne corect când este citit ulterior, deoarece descrierea păstrează explicit contextul verificat, sursa și momentul evenimentului fără termeni temporali relativi."
        ],
        "sources": [{"name": "Sursă", "url": "https://example.invalid/document", "tier": "T1"}],
    }
    stale = {**safe, "id": "archive-stale", "headline": "Azi are loc evenimentul local"}
    assert legacy.story_ready(safe)[0] is True
    assert legacy.story_ready(stale)[0] is False
    assert _is_newer("2026-08-17T10:00:00+03:00", "2026-08-16T10:00:00+03:00") is True
    assert _is_newer("2026-08-15T10:00:00+03:00", "2026-08-16T10:00:00+03:00") is False
    candidate = legacy.archive_payload([safe], datetime(2026, 8, 17, 10, 0, tzinfo=legacy.TZ))
    assert candidate["story_count"] == 1
    assert candidate["recap_editions_may_delete_published_stories"] is False
    print("Archive-preserving continuous frontpage wrapper self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    if "--archive-only" in sys.argv:
        sync_archive_only()
        return 0
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
