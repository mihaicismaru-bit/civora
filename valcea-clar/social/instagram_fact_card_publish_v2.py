#!/usr/bin/env python3
"""Instagram fact-card v2: drain unpublished canonical story backlog.

v1 renders a safe editorial text card when a verified story has no approved real
photograph.  v2 fixes two delivery gaps: it considers every current publishable
story not just the newest event, and it rehydrates FACT_KERNEL_COMPOSED stories
from the full Editorial Writer registry before the integrity check.
"""
from __future__ import annotations

from typing import Any

import instagram_fact_card_publish as base
import generate_edition


def current_publishable_backlog() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decision = base.load(base.VC / "site" / "newsroom_decision.json", {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"canonical_urls": {}})
    allowed_order = [str(value) for value in decision.get("publishable_story_ids") or [] if str(value).strip()]
    registry, _ = generate_edition.merged_registry()
    by_id = {
        str(row.get("id")): row
        for row in registry.get("facts") or []
        if isinstance(row, dict) and row.get("id")
    }
    stories = [by_id[story_id] for story_id in allowed_order if story_id in by_id]
    urls = event.get("canonical_urls") if isinstance(event.get("canonical_urls"), dict) else {}
    for story_id in allowed_order:
        urls.setdefault(story_id, f"https://valceaclar.ro/stiri/{story_id}/")
    event["canonical_urls"] = urls
    event["new_story_ids"] = allowed_order
    event["delivery_discovery_mode"] = "ALL_CURRENT_PUBLISHABLE_NOT_IN_INSTAGRAM_LEDGER_FULL_WRITER_PRODUCTS"
    return stories, event


def install() -> None:
    base.event_stories = current_publishable_backlog


def self_test() -> int:
    install()
    assert base.event_stories is current_publishable_backlog
    print("VÂLCEA CLAR Instagram fact-card v2 durable backlog self-test: PASS")
    return 0


def main() -> int:
    import sys
    if "--self-test" in sys.argv:
        return self_test()
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
