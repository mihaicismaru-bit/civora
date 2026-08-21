#!/usr/bin/env python3
"""Publish only the verified manual VÂLCEA CLAR story to native social channels.

This adapter exists to close the gap between the explicit human-editor manual
publication path and the normal continuous-newsroom event handoff. It never
drains backlog: only story ids currently present in manual_publish_queue.json
with publication_intent=publish are eligible. Platform ledgers remain the
deduplication authority.

Credentials are runtime-only GitHub Actions secrets and are never persisted.
TikTok is deliberately not handled here because its consent/audit gate remains
mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
sys.path.insert(0, str(SOCIAL))

import facebook_publish as fb  # noqa: E402
import instagram_publish as ig  # noqa: E402
import threads_publish as th  # noqa: E402
from social_common import load_json, photo_metadata, utc_now, write_json  # noqa: E402

MANUAL = VC / "editorial" / "manual_publish_queue.json"
OUTBOX = SOCIAL / "facebook_outbox.json"
THREADS_OUTBOX = SOCIAL / "threads_outbox.json"
FB_STATE = SOCIAL / "facebook_state.json"
IG_STATE = SOCIAL / "instagram_state.json"
THREADS_STATE = SOCIAL / "threads_state.json"


def manual_story_ids() -> list[str]:
    queue = load_json(MANUAL)
    if queue.get("publication_intent") != "publish" or queue.get("requested_by") != "human_editor":
        return []
    ids = []
    for fact in queue.get("facts") or []:
        if isinstance(fact, dict) and str(fact.get("id") or "").strip():
            ids.append(str(fact["id"]).strip())
    return ids


def manual_fingerprint() -> str:
    queue = load_json(MANUAL)
    raw = json.dumps(queue, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def shared_item(story_id: str) -> dict[str, Any]:
    outbox = load_json(OUTBOX, {"items": []})
    wanted = f"story-{story_id}"
    for item in outbox.get("items") or []:
        if isinstance(item, dict) and str(item.get("id")) == wanted:
            return item
    raise RuntimeError(f"manual social item missing from shared outbox: {wanted}")


def threads_item(story_id: str) -> dict[str, Any]:
    outbox = load_json(THREADS_OUTBOX, {"items": []})
    wanted = f"threads-story-{story_id}"
    for item in outbox.get("items") or []:
        if isinstance(item, dict) and str(item.get("id")) == wanted:
            return item
    raise RuntimeError(f"manual Threads item missing from outbox: {wanted}")


def apply_facebook(story_id: str) -> dict[str, Any]:
    item = shared_item(story_id)
    state = load_json(FB_STATE, {"schema_version": "3.0", "published": {}})
    published = state.setdefault("published", {})
    key = str(item["id"])
    if key in published:
        return {"status": "ALREADY_PUBLISHED", "platform": "facebook", "story_id": story_id, "remote_id": published[key].get("facebook_post_id")}
    plan = fb.eligible([item], published)
    if len(plan) != 1:
        return {"status": "HOLD", "platform": "facebook", "story_id": story_id, "reason": "manual_story_not_eligible"}

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    durable = os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
    legacy = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    supplied = durable or legacy
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", fb.DEFAULT_GRAPH_VERSION).strip() or fb.DEFAULT_GRAPH_VERSION
    if not page_id or not supplied:
        return {"status": "BLOCKED_MISSING_CREDENTIALS", "platform": "facebook", "story_id": story_id}

    try:
        page_token, resolution = fb.resolve_page_token(page_id, supplied, version)
        post_id = fb.graph_photo_post(page_id, page_token, version, item)
    except Exception as exc:
        state["last_manual_attempt"] = {"at": utc_now(), "status": "failed", "story_id": story_id, "error": str(exc)[:1000]}
        write_json(FB_STATE, state)
        raise

    metadata = photo_metadata(item)
    published[key] = {
        "facebook_post_id": post_id,
        "published_at": utc_now(),
        "link": item["link"],
        "image_path": item["image_path"],
        "image_credit": metadata["credit"],
        "image_rights_basis": metadata["rights_basis"],
        "image_source_url": metadata.get("source_url"),
        "manual_distribution": True,
        "manual_publication_fingerprint": manual_fingerprint(),
        "replaces": list(item.get("replace_post_ids") or []),
        "replacement_cleanup": {},
    }
    state["last_manual_attempt"] = {"at": utc_now(), "status": "published", "story_id": story_id}
    write_json(FB_STATE, state)
    return {"status": "PUBLISHED", "platform": "facebook", "story_id": story_id, "remote_id": post_id, "auth_resolution": resolution}


def apply_instagram(story_id: str) -> dict[str, Any]:
    raw = shared_item(story_id)
    state = load_json(IG_STATE, {"schema_version": "1.0", "platform": "instagram", "published": {}, "failures": {}})
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    key = str(raw["id"])
    if key in published:
        value = published[key]
        return {"status": "ALREADY_PUBLISHED", "platform": "instagram", "story_id": story_id, "remote_id": value.get("instagram_media_id")}

    item = ig.validate_item(raw)
    account_id = os.getenv("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.getenv("VALCEA_IG_ACCESS_TOKEN", "").strip()
    version = os.getenv("VALCEA_IG_GRAPH_VERSION", ig.DEFAULT_GRAPH_VERSION).strip() or ig.DEFAULT_GRAPH_VERSION
    host = os.getenv("VALCEA_IG_GRAPH_HOST", ig.DEFAULT_GRAPH_HOST).strip() or ig.DEFAULT_GRAPH_HOST
    if not account_id or not token:
        return {"status": "BLOCKED_MISSING_CREDENTIALS", "platform": "instagram", "story_id": story_id}
    try:
        result = ig.publish_one(item, account_id=account_id, token=token, version=version, host=host)
    except Exception as exc:
        failures[key] = {"failed_at": utc_now(), "error": str(exc)[:1000], "manual_distribution": True}
        state["last_manual_attempt"] = {"at": utc_now(), "status": "failed", "story_id": story_id}
        write_json(IG_STATE, state)
        raise
    result["manual_distribution"] = True
    result["manual_publication_fingerprint"] = manual_fingerprint()
    published[key] = result
    failures.pop(key, None)
    state["last_manual_attempt"] = {"at": utc_now(), "status": "published", "story_id": story_id}
    write_json(IG_STATE, state)
    return {"status": "PUBLISHED", "platform": "instagram", "story_id": story_id, "remote_id": result.get("instagram_media_id")}


def apply_threads(story_id: str) -> dict[str, Any]:
    item = threads_item(story_id)
    state = load_json(THREADS_STATE, {"schema_version": "1.2", "platform": "threads", "published": {}, "failures": {}})
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    key = str(item["id"])
    if key in published:
        value = published[key]
        return {"status": "ALREADY_PUBLISHED", "platform": "threads", "story_id": story_id, "remote_id": value.get("root_remote_id")}

    posts = th.validate_item(item)
    if not th.live_enabled():
        return {"status": "BLOCKED_LIVE_NOT_ENABLED", "platform": "threads", "story_id": story_id}
    token = th.token_from_env()
    profile = th.verify_identity(token)
    remote_ids: list[str] = []
    previous: str | None = None
    fp = manual_fingerprint()
    try:
        for text in posts:
            remote = th.publish_text(token, text, previous)
            remote_ids.append(remote)
            previous = remote
    except Exception as exc:
        failures[key] = {
            "failed_at": utc_now(),
            "story_id": story_id,
            "manual_publication_fingerprint": fp,
            "product_fingerprint_sha256": item.get("product_fingerprint_sha256"),
            "remote_ids_observed": remote_ids,
            "manual_reconciliation_required": True,
            "reason": str(exc)[:1000],
        }
        state["last_manual_attempt"] = {"at": utc_now(), "status": "failed", "story_id": story_id}
        write_json(THREADS_STATE, state)
        raise

    published[key] = {
        "published_at": utc_now(),
        "story_id": story_id,
        "manual_distribution": True,
        "manual_publication_fingerprint": fp,
        "product_fingerprint_sha256": item.get("product_fingerprint_sha256"),
        "root_remote_id": remote_ids[0],
        "remote_ids": remote_ids,
        "posts": len(posts),
    }
    failures.pop(key, None)
    state["last_verified_username"] = profile["username"]
    state["last_auth_verified_at"] = utc_now()
    state["last_manual_attempt"] = {"at": utc_now(), "status": "published", "story_id": story_id}
    write_json(THREADS_STATE, state)
    return {"status": "PUBLISHED", "platform": "threads", "story_id": story_id, "remote_id": remote_ids[0], "posts": len(posts), "username": profile["username"]}


def run(platform: str) -> dict[str, Any]:
    ids = manual_story_ids()
    if not ids:
        return {"status": "NO_MANUAL_STORIES", "platform": platform}
    results = []
    for story_id in ids:
        if platform == "facebook":
            results.append(apply_facebook(story_id))
        elif platform == "instagram":
            results.append(apply_instagram(story_id))
        elif platform == "threads":
            results.append(apply_threads(story_id))
        else:
            raise ValueError(f"unsupported platform: {platform}")
    return {"status": "PASS", "platform": platform, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=["facebook", "instagram", "threads"], required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.check:
        ids = manual_story_ids()
        print(json.dumps({"status": "PASS", "platform": args.platform, "manual_story_ids": ids, "network_calls": False}, ensure_ascii=False, indent=2))
        return 0
    try:
        print(json.dumps(run(args.platform), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "platform": args.platform, "error": str(exc)[:1200]}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
