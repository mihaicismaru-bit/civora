#!/usr/bin/env python3
"""Publish a text+link Facebook fallback when a live story has no approved photo.

The canonical visual publisher remains preferred. This adapter is deliberately
narrow: it only sees new story IDs from the latest durable publication event,
only accepts items whose sole Facebook blocker is the missing story-specific
photo, preserves publication holds, and shares the canonical `story-<id>` state
key so a later visual workflow cannot duplicate the post.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import facebook_publish as legacy
from social_common import is_socially_held

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "facebook_outbox.json"
STATE = VC / "social" / "facebook_state.json"
EVENT = VC / "site" / "story_publication_event.json"
DECISION = VC / "site" / "newsroom_decision.json"
DEFAULT_GRAPH_VERSION = "v26.0"
ADAPTER = "facebook-text-fallback-v1"
MISSING_PHOTO_REASON = "story_specific_approved_photo_required"
CANONICAL_HOSTS = {"valceaclar.ro", "www.valceaclar.ro"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.is_file():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def latest_new_story_ids() -> list[str]:
    event = load(EVENT, {})
    ids = [str(value) for value in event.get("new_story_ids") or [] if str(value)]
    if ids:
        return ids
    decision = load(DECISION, {})
    return [str(value) for value in decision.get("new_story_ids") or [] if str(value)]


def canonical_link_ok(value: str) -> bool:
    parsed = urllib.parse.urlparse(str(value or "").strip())
    return parsed.scheme == "https" and parsed.hostname in CANONICAL_HOSTS and parsed.path.startswith("/stiri/")


def eligible_items(outbox: dict[str, Any], state: dict[str, Any], new_story_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(new_story_ids)
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    result: list[dict[str, Any]] = []
    for item in outbox.get("items") or []:
        if not isinstance(item, dict):
            continue
        story_id = str(item.get("source_story_id") or "").strip()
        item_id = str(item.get("id") or "").strip()
        if not story_id or story_id not in wanted or not item_id:
            continue
        if item_id in published or is_socially_held(story_id):
            continue
        if item.get("status") != "hold" or item.get("hold_reason") != MISSING_PHOTO_REASON:
            continue
        platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
        facebook = platforms.get("facebook") if isinstance(platforms.get("facebook"), dict) else {}
        if facebook.get("status") != "hold" or facebook.get("reason") != MISSING_PHOTO_REASON:
            continue
        message = str(item.get("message") or "").strip()
        link = str(item.get("link") or "").strip()
        if not message or not canonical_link_ok(link):
            continue
        result.append(item)
    return result


def graph_feed_post(*, page_id: str, token: str, version: str, item: dict[str, Any], request_fn: Callable[..., Any] = urllib.request.urlopen) -> str:
    payload = urllib.parse.urlencode({
        "message": str(item["message"]).strip(),
        "link": str(item["link"]).strip(),
        "access_token": token,
    }).encode("utf-8")
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{page_id}/feed",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ValceaClar-Facebook-Text-Fallback/1.0"},
    )
    try:
        with request_fn(request, timeout=45) as response:
            value = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta text-link POST HTTP {exc.code}: {detail[:1000]}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("Meta text-link POST returned unexpected payload")
    post_id = str(value.get("id") or value.get("post_id") or "").strip()
    if not post_id:
        raise RuntimeError(f"Meta text-link POST returned no post id: {value}")
    return post_id


def record_publication(state: dict[str, Any], item: dict[str, Any], post_id: str) -> None:
    published = state.setdefault("published", {})
    if not isinstance(published, dict):
        raise ValueError("facebook_state.published must be an object")
    item_id = str(item["id"])
    story_id = str(item["source_story_id"])
    published[item_id] = {
        "facebook_post_id": post_id,
        "published_at": utc_now(),
        "link": str(item["link"]),
        "publication_product": ADAPTER,
        "native_format": "text_link",
        "visual_used": False,
        "synthetic_media_used": False,
        "source_story_id": story_id,
        "fallback_reason": MISSING_PHOTO_REASON,
        "replacement_cleanup": {},
    }
    state["last_text_fallback_attempt"] = {
        "at": utc_now(), "status": "published", "story_id": story_id,
        "state_key": item_id, "publication_product": ADAPTER,
    }


def credentials() -> tuple[str, str, str]:
    page_id = str(os.getenv("VALCEA_FB_PAGE_ID") or "1234360446430980").strip()
    token = str(os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN") or os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN") or "").strip()
    version = str(os.getenv("VALCEA_FB_GRAPH_VERSION") or DEFAULT_GRAPH_VERSION).strip()
    return page_id, token, version


def self_test() -> int:
    sample = {
        "id": "story-test-new", "source_story_id": "test-new", "status": "hold",
        "hold_reason": MISSING_PHOTO_REASON,
        "message": "ȘTIRI | VÂLCEA CLAR\n\nInformare verificată.",
        "link": "https://valceaclar.ro/stiri/test-new/",
        "platforms": {"facebook": {"status": "hold", "reason": MISSING_PHOTO_REASON}},
    }
    assert eligible_items({"items": [sample]}, {"published": {}}, ["test-new"])[0]["id"] == sample["id"]
    assert eligible_items({"items": [sample]}, {"published": {sample["id"]: {}}}, ["test-new"]) == []
    assert eligible_items({"items": [sample]}, {"published": {}}, ["another-story"]) == []
    assert canonical_link_ok(sample["link"])
    assert not canonical_link_ok("https://example.com/stiri/test/")

    captured: dict[str, Any] = {}
    class FakeResponse:
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self): return b'{"id":"123_page_456"}'
    def fake_open(request, timeout=0):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["data"] = urllib.parse.parse_qs(request.data.decode("utf-8"))
        return FakeResponse()
    post_id = graph_feed_post(page_id="123", token="fixture-token", version="v26.0", item=sample, request_fn=fake_open)
    assert post_id == "123_page_456"
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/v26.0/123/feed")
    assert captured["data"]["link"] == [sample["link"]]
    state = {"published": {}}
    record_publication(state, sample, post_id)
    assert state["published"][sample["id"]]["visual_used"] is False
    assert state["published"][sample["id"]]["publication_product"] == ADAPTER
    print("VÂLCEA CLAR Facebook text fallback self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    outbox = load(OUTBOX, {"schema_version": "4.0", "items": []})
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    new_ids = latest_new_story_ids()
    plan = eligible_items(outbox, state, new_ids)
    max_per_run = max(1, min(int(os.getenv("VALCEA_FB_TEXT_FALLBACK_MAX_PER_RUN") or "2"), 4))
    plan = plan[:max_per_run]

    if not args.apply:
        print(json.dumps({
            "status": "DRY_RUN", "adapter": ADAPTER, "new_story_ids": new_ids,
            "eligible": [{"id": item.get("id"), "source_story_id": item.get("source_story_id"), "link": item.get("link")} for item in plan],
        }, ensure_ascii=False, indent=2))
        return 0
    if not plan:
        print(json.dumps({"status": "NO_ELIGIBLE_TEXT_FALLBACK", "adapter": ADAPTER, "new_story_ids": new_ids}, ensure_ascii=False))
        return 0

    page_id, supplied_token, version = credentials()
    if not supplied_token:
        state["last_text_fallback_attempt"] = {"at": utc_now(), "status": "blocked_missing_meta_token", "publication_product": ADAPTER}
        write(STATE, state)
        print(json.dumps({"status": "BLOCKED_MISSING_META_TOKEN", "adapter": ADAPTER}, ensure_ascii=False))
        return 2
    try:
        page_token, identity = legacy.resolve_page_token(page_id, supplied_token, version)
    except Exception as exc:
        reason = legacy.classify_auth_error(exc)
        state["last_text_fallback_attempt"] = {"at": utc_now(), "status": "blocked_meta_auth", "publication_product": ADAPTER, "reason": reason}
        write(STATE, state)
        print(json.dumps({"status": "BLOCKED_META_AUTH", "reason": reason}, ensure_ascii=False))
        return 2

    published_now: list[dict[str, str]] = []
    for item in plan:
        post_id = graph_feed_post(page_id=page_id, token=page_token, version=version, item=item)
        record_publication(state, item, post_id)
        write(STATE, state)
        published_now.append({"story_id": str(item["source_story_id"]), "state_key": str(item["id"]), "facebook_post_id": post_id})

    state["last_text_fallback_identity"] = {
        "verified_at": utc_now(), "page_id": page_id, "page_name": identity.get("page_name"),
        "token_source": identity.get("source"), "token_value_logged": False,
    }
    write(STATE, state)
    print(json.dumps({"status": "PUBLISHED", "adapter": ADAPTER, "published": published_now}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
