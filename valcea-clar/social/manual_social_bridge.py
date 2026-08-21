#!/usr/bin/env python3
"""Bridge verified manual VÂLCEA CLAR publications into canonical social outboxes.

Manual publication is an explicit human-editor path that can materialize a live
story before the continuous newsroom decision registry catches up. This bridge
keeps that path fail-closed: only a queue with publication_intent=publish, a
human editor marker, a story that passes the canonical story_ready gate, and an
approved story-specific visual can become ready on visual channels.

The bridge only materializes canonical outbox products. Network publication is
owned by the GitHub Actions site engine and existing platform adapters.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
SCRIPTS = VC / "scripts"
sys.path.insert(0, str(SOCIAL))
sys.path.insert(0, str(SCRIPTS))

from newsroom_decide import story_ready  # noqa: E402
from build_live_story_outbox import find_visual, story_item  # noqa: E402
from social_common import is_socially_held  # noqa: E402
from threads_editorial_v1 import package as threads_package  # noqa: E402
from threads_editorial_materialize import canonical_item as threads_canonical_item  # noqa: E402

MANUAL = VC / "editorial" / "manual_publish_queue.json"
VISUALS = SOCIAL / "story_visuals.json"
FACEBOOK_OUTBOX = SOCIAL / "facebook_outbox.json"
THREADS_OUTBOX = SOCIAL / "threads_outbox.json"


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def eligible_stories() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    queue = load(MANUAL)
    visuals = load(VISUALS, {"stories": {}})
    if queue.get("publication_intent") != "publish":
        return [], visuals
    if queue.get("requested_by") != "human_editor":
        raise RuntimeError("manual social bridge requires requested_by=human_editor")

    accepted: list[dict[str, Any]] = []
    for story in queue.get("facts") or []:
        if not isinstance(story, dict):
            continue
        story_id = str(story.get("id") or "").strip()
        if not story_id or is_socially_held(story_id):
            continue
        ok, _reason = story_ready(story)
        if ok:
            accepted.append(story)
    return accepted, visuals


def materialize() -> dict[str, Any]:
    stories, visuals = eligible_stories()

    facebook = load(FACEBOOK_OUTBOX, {"schema_version": "4.0", "items": []})
    fb_items = facebook.setdefault("items", [])
    fb_existing = {
        str(item.get("id")): item
        for item in fb_items
        if isinstance(item, dict) and item.get("id")
    }

    threads = load(THREADS_OUTBOX, {
        "schema_version": "1.2",
        "platform": "threads",
        "publication_model": "continuous_story_first",
        "items": [],
    })
    thread_items = threads.setdefault("items", [])
    thread_existing = {
        str(item.get("id")): item
        for item in thread_items
        if isinstance(item, dict) and item.get("id")
    }

    visual_ready: list[str] = []
    visual_held: list[str] = []
    threads_ready: list[str] = []
    threads_held: list[str] = []

    for story in stories:
        story_id = str(story["id"])
        visual = find_visual(story, visuals)

        fb_id = f"story-{story_id}"
        fb_item = story_item(story, visual, fb_existing.get(fb_id))
        fb_item["manual_distribution_source"] = "verified_human_editor_queue"
        if fb_id in fb_existing:
            for index, current in enumerate(fb_items):
                if isinstance(current, dict) and current.get("id") == fb_id:
                    fb_items[index] = fb_item
                    break
        else:
            fb_items.append(fb_item)
        fb_existing[fb_id] = fb_item
        (visual_ready if fb_item.get("status") == "ready" else visual_held).append(story_id)

        product = threads_package(story)
        thread_item = threads_canonical_item(product)
        thread_item["manual_distribution_source"] = "verified_human_editor_queue"
        thread_id = str(thread_item["id"])
        if thread_id in thread_existing:
            for index, current in enumerate(thread_items):
                if isinstance(current, dict) and current.get("id") == thread_id:
                    thread_items[index] = thread_item
                    break
        else:
            thread_items.append(thread_item)
        thread_existing[thread_id] = thread_item
        (threads_ready if thread_item.get("status") == "outbox_ready" else threads_held).append(story_id)

    write(FACEBOOK_OUTBOX, facebook)
    write(THREADS_OUTBOX, threads)

    return {
        "status": "PASS",
        "source": "manual_publish_queue",
        "stories_seen": len(stories),
        "visual_channels_ready": visual_ready,
        "visual_channels_held": visual_held,
        "threads_ready": threads_ready,
        "threads_held": threads_held,
        "network_calls": False,
    }


def check() -> dict[str, Any]:
    stories, visuals = eligible_stories()
    rows = []
    for story in stories:
        story_id = str(story["id"])
        visual = find_visual(story, visuals)
        rows.append({
            "story_id": story_id,
            "story_ready": True,
            "approved_visual_present": bool(visual),
            "threads_status": threads_package(story).get("status"),
        })
    return {"status": "PASS", "eligible": rows, "network_calls": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = check() if args.check else materialize()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
