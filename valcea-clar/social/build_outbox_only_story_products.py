#!/usr/bin/env python3
"""Build durable story-first products for VÂLCEA CLAR outbox-only channels.

Threads and YouTube do not have verified direct publishing access yet. They
still consume the same individual story publication identity as the site and
active social adapters, so enabling an adapter later cannot reintroduce edition
windows as publication gates.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
sys.path.insert(0, str(VC / "scripts"))
from newsroom_decide import story_ready  # noqa: E402

POINTER = VC / "site" / "current_edition.json"
DECISION = VC / "site" / "newsroom_decision.json"
EVENT = VC / "site" / "story_publication_event.json"
THREADS_OUTBOX = VC / "social" / "threads_outbox.json"
THREADS_STATE = VC / "social" / "threads_state.json"
YOUTUBE_OUTBOX = VC / "social" / "youtube_outbox.json"
YOUTUBE_STATE = VC / "social" / "youtube_state.json"
BASE = "https://valceaclar.ro"


def load(path: Path, default=None):
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slug(story_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", story_id.lower())
    return re.sub(r"-+", "-", value).strip("-") or "story"


def canonical(story: dict) -> str:
    return f"{BASE}/stiri/{slug(str(story['id']))}/"


def threads_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    sequence = [headline, dek]
    if paragraphs:
        sequence.append(paragraphs[0])
    sequence.append(f"Surse și context complet: {canonical(story)}")
    return {
        "id": f"threads-story-{story['id']}",
        "story_id": story["id"],
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "thread" if len(sequence) > 2 else "text",
        "thread": sequence,
        "canonical_url": canonical(story),
        "source_preserving": True,
        "edition_gate": False,
    }


def youtube_product(story: dict) -> dict:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    script = [headline, dek, *paragraphs[:2], f"Sursele sunt în articol: {canonical(story)}"]
    return {
        "id": f"youtube-story-{story['id']}",
        "story_id": story["id"],
        "status": "hold_media",
        "publication_mode": "durable_outbox_only",
        "native_format": "short",
        "title": headline[:100],
        "script_blocks": script,
        "canonical_url": canonical(story),
        "hold_reason": "real_story_specific_video_and_verified_upload_access_required",
        "real_video_required": True,
        "synthetic_real_person_media_forbidden": True,
        "edition_gate": False,
    }


def upsert(doc: dict, products: list[dict]) -> dict:
    existing = {
        str(item.get("id")): item
        for item in doc.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    doc["items"] = list(existing.values())
    doc["publication_model"] = "continuous_story_first"
    doc["edition_recaps_are_publication_gates"] = False
    return doc


def main() -> int:
    pointer = load(POINTER)
    snapshot = load(VC / str(pointer["json_source"]))
    decision = load(DECISION, {"publishable_story_ids": []})
    event = load(EVENT, {"story_ids": []})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [
        item for item in snapshot.get("items", [])
        if item.get("id") in allowed and story_ready(item)[0]
    ]

    threads = upsert(
        load(THREADS_OUTBOX, {"schema_version": "1.0", "platform": "threads", "items": []}),
        [threads_product(story) for story in stories],
    )
    youtube = upsert(
        load(YOUTUBE_OUTBOX, {"schema_version": "1.0", "platform": "youtube", "items": []}),
        [youtube_product(story) for story in stories],
    )
    write(THREADS_OUTBOX, threads)
    write(YOUTUBE_OUTBOX, youtube)

    for path, platform in ((THREADS_STATE, "threads"), (YOUTUBE_STATE, "youtube")):
        state = load(path, {
            "schema_version": "1.0",
            "platform": platform,
            "execution_owner": "civora_site_engine",
            "published": {},
            "failures": {},
        })
        state["publication_model"] = "continuous_story_first"
        write(path, state)

    print(json.dumps({
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "story_count": len(stories),
        "threads_products": len(stories),
        "youtube_products": len(stories),
        "youtube_state": "HOLD_MEDIA_UNTIL_REAL_VIDEO_AND_ACCESS",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
