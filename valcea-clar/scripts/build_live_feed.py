#!/usr/bin/env python3
"""Build the public live feed for the continuous VÂLCEA CLAR newsroom.

The current edition document is retained as a compatibility snapshot, but the
public feed exposes individual stories and canonical story URLs as the primary
publication model. Edition windows never authorize or delay story publication.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTER = ROOT / "site" / "current_edition.json"
PLACES = ROOT / "web" / "data" / "places.json"
OUT = ROOT / "site" / "runtime" / "live-feed.json"
STORY_MANIFEST = ROOT / "site" / "runtime" / "stiri" / "manifest.json"
PUBLISHABLE = {"auto_approved", "editor_approved"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def story_feed(snapshot: dict) -> list[dict]:
    routes = {}
    if STORY_MANIFEST.is_file():
        manifest = load(STORY_MANIFEST)
        routes = {
            str(item.get("id")): item
            for item in manifest.get("stories", [])
            if isinstance(item, dict) and item.get("id") and item.get("canonical")
        }
    stories = []
    for item in snapshot.get("items", []):
        story_id = str(item.get("id") or "")
        route = routes.get(story_id)
        if not route:
            continue
        stories.append({
            "id": story_id,
            "section": item.get("section"),
            "priority": item.get("priority"),
            "headline": item.get("headline"),
            "dek": item.get("dek"),
            "path": route.get("path"),
            "canonical_url": route.get("canonical"),
            "sources": item.get("sources", []),
        })
    stories.sort(key=lambda item: (-int(item.get("priority") or 0), item["id"]))
    return stories


def main() -> int:
    pointer = load(POINTER)
    if pointer.get("status") not in PUBLISHABLE or pointer.get("publication_intent") != "publish":
        raise SystemExit("Refusing live feed: no publishable compatibility snapshot")
    snapshot = load(ROOT / pointer["json_source"])
    if snapshot.get("edition_id") != pointer.get("edition_id"):
        raise SystemExit("Refusing live feed: compatibility snapshot pointer mismatch")
    places = load(PLACES).get("places", [])
    stories = story_feed(snapshot)
    payload = {
        "schema_version": "2.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_domain": "valceaclar.ro",
        "publication_model": "continuous_story_first",
        "stories": stories,
        "story_count": len(stories),
        "compatibility_snapshot": snapshot,
        "compatibility_pointer": pointer,
        "unde_iesim": [
            {
                "id": p.get("id"),
                "slug": p.get("slug"),
                "name": p.get("name"),
                "type": p.get("type"),
                "city": (p.get("location") or {}).get("city"),
                "summary": (p.get("editorial") or {}).get("dek") or (p.get("offer") or {}).get("summary"),
                "badges": p.get("badges", [])[:2],
            }
            for p in places[:8]
        ],
        "policy": {
            "verified_facts_only": True,
            "candidate_records_hidden": True,
            "paid_llm_api_required": False,
            "refresh_strategy": "event_first_with_polling_fallback",
            "individual_story_is_publication_unit": True,
            "edition_windows_are_publication_gates": False,
            "canonical_story_urls_required": True,
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "publication_model": payload["publication_model"],
        "stories": len(stories),
        "compatibility_snapshot": snapshot["edition_id"],
        "feed": str(OUT.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
