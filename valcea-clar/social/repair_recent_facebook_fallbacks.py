#!/usr/bin/env python3
"""One-shot repair for recent broken Facebook text-link fallback posts.

Recent fallback posts are either upgraded to a validated real-photo post (when a
current approved photograph exists and the public story URL passes live readback)
or deleted and returned to HOLD until such a photograph exists. The replacement
is created before the old post is deleted so a failed photo upload cannot erase a
valid publication unit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import facebook_publish as legacy
import facebook_text_fallback as fallback

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "facebook_outbox.json"
STATE = VC / "social" / "facebook_state.json"
MAX_AGE_HOURS = 48


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value: Any) -> dt.datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def recent_fallbacks(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    cutoff = now() - dt.timedelta(hours=MAX_AGE_HOURS)
    rows: list[tuple[str, dict[str, Any]]] = []
    for key, entry in published.items():
        if not isinstance(entry, dict) or entry.get("publication_product") != fallback.ADAPTER:
            continue
        when = parse_time(entry.get("published_at"))
        if when is None or when < cutoff:
            continue
        rows.append((str(key), entry))
    return rows


def outbox_by_id(outbox: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in outbox.get("items") or []:
        if isinstance(item, dict) and str(item.get("id") or "").strip():
            result[str(item["id"])] = item
    return result


def has_approved_photo(item: dict[str, Any]) -> bool:
    if item.get("status") != "ready":
        return False
    try:
        legacy.image_file(item)
        legacy.photo_metadata(item)
    except Exception:
        return False
    return True


def credentials() -> tuple[str, str, str]:
    page_id = str(os.getenv("VALCEA_FB_PAGE_ID") or "1234360446430980").strip()
    supplied = str(os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN") or os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN") or "").strip()
    version = str(os.getenv("VALCEA_FB_GRAPH_VERSION") or legacy.DEFAULT_GRAPH_VERSION).strip()
    if not supplied:
        raise RuntimeError("missing Meta Page access token")
    page_token, _identity = legacy.resolve_page_token(page_id, supplied, version)
    return page_id, page_token, version


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    outbox = load(OUTBOX, {"items": []})
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    items = outbox_by_id(outbox)
    candidates = recent_fallbacks(state)
    plan = []
    for key, entry in candidates:
        item = items.get(key)
        plan.append({
            "state_key": key,
            "source_story_id": entry.get("source_story_id") or key.removeprefix("story-"),
            "old_post_id": entry.get("facebook_post_id"),
            "action": "replace_with_photo" if isinstance(item, dict) and has_approved_photo(item) else "delete_and_hold",
        })
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "plan": plan}, ensure_ascii=False, indent=2))
        return 0
    if not candidates:
        print(json.dumps({"status": "NO_RECENT_FALLBACKS"}, ensure_ascii=False))
        return 0

    page_id, token, version = credentials()
    published = state.setdefault("published", {})
    history = state.setdefault("fallback_repair_history", [])
    if not isinstance(published, dict) or not isinstance(history, list):
        raise ValueError("invalid Facebook state structure")
    results: list[dict[str, Any]] = []

    for key, old in candidates:
        item = items.get(key)
        old_post_id = str(old.get("facebook_post_id") or "").strip()
        story_id = str(old.get("source_story_id") or key.removeprefix("story-"))
        if not old_post_id:
            results.append({"state_key": key, "story_id": story_id, "status": "HOLD_MISSING_OLD_POST_ID"})
            continue

        if isinstance(item, dict) and has_approved_photo(item):
            link = str(item.get("link") or "").strip()
            ready, reason = fallback.public_story_ready(link)
            if not ready:
                results.append({"state_key": key, "story_id": story_id, "status": "HOLD_PUBLIC_ROUTE_NOT_READY", "reason": reason})
                continue
            new_post_id = legacy.graph_photo_post(page_id, token, version, item)
            cleanup = legacy.graph_delete(old_post_id, token, version)
            metadata = legacy.photo_metadata(item)
            published[key] = {
                "facebook_post_id": new_post_id,
                "published_at": fallback.utc_now(),
                "link": link,
                "publication_product": "facebook-real-photo-repair-v1",
                "native_format": "photo",
                "visual_used": True,
                "synthetic_media_used": False,
                "source_story_id": story_id,
                "image_path": item.get("image_path"),
                "image": metadata,
                "replaces": [old_post_id],
                "replacement_cleanup": {old_post_id: cleanup},
            }
            result = {
                "state_key": key, "story_id": story_id, "status": "REPLACED_WITH_PHOTO",
                "new_post_id": new_post_id, "old_post_id": old_post_id,
                "old_post_cleanup": cleanup.get("status"),
            }
            history.append({**result, "at": fallback.utc_now()})
            results.append(result)
            write(STATE, state)
            continue

        cleanup = legacy.graph_delete(old_post_id, token, version)
        status = str(cleanup.get("status") or "")
        if status in {"deleted", "already_absent"}:
            published.pop(key, None)
            result = {
                "state_key": key, "story_id": story_id, "status": "DELETED_AND_HELD_FOR_PHOTO",
                "old_post_id": old_post_id, "old_post_cleanup": status,
            }
        else:
            old.setdefault("replacement_cleanup", {})[old_post_id] = cleanup
            result = {
                "state_key": key, "story_id": story_id, "status": "HOLD_DELETE_FAILED",
                "old_post_id": old_post_id, "old_post_cleanup": status or "error",
            }
        history.append({**result, "at": fallback.utc_now()})
        results.append(result)
        write(STATE, state)

    state["last_fallback_repair"] = {
        "at": fallback.utc_now(), "page_id": page_id, "results": results,
        "policy": "photo_first_public_route_readback_required",
    }
    write(STATE, state)
    print(json.dumps({"status": "REPAIR_COMPLETE", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
