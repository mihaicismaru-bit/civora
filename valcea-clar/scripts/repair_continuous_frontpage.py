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


def self_test() -> int:
    safe = {
        "id": "archive-safe",
        "headline": "Evenimentul a avut loc în 15 august 2026",
        "dek": "Documentele confirmă programul din 15 august 2026 și păstrează data explicită.",
        "paragraphs": [
            "Acest material de test folosește o dată calendaristică absolută și rămâne corect când este citit ulterior."
        ],
        "sources": [{"name": "Sursă", "url": "https://example.invalid/document", "tier": "T1"}],
    }
    stale = {**safe, "id": "archive-stale", "headline": "Azi are loc evenimentul local"}
    assert legacy.story_ready(safe)[0] is True
    assert legacy.story_ready(stale)[0] is False
    assert _is_newer("2026-08-17T10:00:00+03:00", "2026-08-16T10:00:00+03:00") is True
    assert _is_newer("2026-08-15T10:00:00+03:00", "2026-08-16T10:00:00+03:00") is False
    print("Archive-preserving continuous frontpage wrapper self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()
    return legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())
