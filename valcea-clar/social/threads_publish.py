#!/usr/bin/env python3
"""Fail-closed direct Threads publisher for VÂLCEA CLAR.

The adapter consumes only the canonical Threads editorial outbox, requires a
verified @valceaclar Threads token at runtime, publishes only story IDs from a
new durable story_publication_event, and never replays the pre-activation
backlog. Partial remote publication is quarantined for manual reconciliation so
an uncertain retry cannot duplicate a thread.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from social_common import utc_now

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "threads_outbox.json"
STATE = VC / "social" / "threads_state.json"
EVENT = VC / "site" / "story_publication_event.json"
API_HOST = "https://graph.threads.net"
EXPECTED_USERNAME = "valceaclar"
MAX_POSTS_PER_THREAD = 4
MAX_CHARS_PER_POST = 470


class ThreadsPublishError(RuntimeError):
    pass


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise ThreadsPublishError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ThreadsPublishError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def token_from_env() -> str:
    token = os.environ.get("VALCEA_THREADS_ACCESS_TOKEN", "").strip()
    if not token:
        raise ThreadsPublishError("VALCEA_THREADS_ACCESS_TOKEN is missing")
    return token


def live_enabled() -> bool:
    return os.environ.get("VALCEA_THREADS_LIVE_ENABLED", "").strip().lower() == "true"


def api_request(method: str, path: str, token: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {key: str(value).lower() if isinstance(value, bool) else str(value) for key, value in (params or {}).items()}
    )
    url = API_HOST + path + ("?" + query if query else "")
    request = urllib.request.Request(
        url,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "User-Agent": "valcea-clar-threads-engine/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:1000]
        raise ThreadsPublishError(f"Threads API HTTP {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise ThreadsPublishError(f"Threads API transport error: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ThreadsPublishError("Threads API returned non-JSON data") from exc
    if not isinstance(value, dict):
        raise ThreadsPublishError("Threads API returned a non-object response")
    if value.get("error"):
        raise ThreadsPublishError(f"Threads API error: {json.dumps(value['error'], ensure_ascii=False)}")
    return value


def verify_identity(token: str) -> dict[str, Any]:
    profile = api_request("GET", "/me", token, {"fields": "id,username,name"})
    username = str(profile.get("username") or "").strip().lstrip("@").lower()
    expected = os.environ.get("VALCEA_THREADS_EXPECTED_USERNAME", EXPECTED_USERNAME).strip().lstrip("@").lower()
    if not expected or username != expected:
        raise ThreadsPublishError(f"Threads token identity mismatch: expected @{expected}, got @{username or '?'}")
    if not str(profile.get("id") or "").strip():
        raise ThreadsPublishError("Threads profile id missing from /me response")
    return {"id": str(profile["id"]), "username": username, "name": str(profile.get("name") or "")}


def validate_item(item: dict[str, Any]) -> list[str]:
    if item.get("status") != "outbox_ready":
        raise ThreadsPublishError("item is not outbox_ready")
    if item.get("direct_publication_enabled") is not True:
        raise ThreadsPublishError("item direct publication is not enabled")
    if item.get("source_preserving") is not True or item.get("conversation_native") is not True:
        raise ThreadsPublishError("Threads editorial provenance/native gate failed")
    if item.get("verbatim_cross_platform_reuse_allowed") is not False:
        raise ThreadsPublishError("verbatim cross-platform reuse guard failed")
    identity = item.get("identity")
    if not isinstance(identity, dict) or identity.get("channel_id") != "valcea-threads":
        raise ThreadsPublishError("Threads canonical identity is missing")
    posts = item.get("posts")
    if not isinstance(posts, list) or not 1 <= len(posts) <= MAX_POSTS_PER_THREAD:
        raise ThreadsPublishError("Threads post sequence must contain 1-4 posts")
    clean: list[str] = []
    for raw in posts:
        text = str(raw).strip()
        if not text or len(text) > MAX_CHARS_PER_POST:
            raise ThreadsPublishError("Threads post is empty or exceeds the internal 470-character budget")
        clean.append(text)
    return clean


def eligible_items(outbox: dict[str, Any], state: dict[str, Any], event: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    if outbox.get("platform") != "threads" or outbox.get("publication_model") != "continuous_story_first":
        raise ThreadsPublishError("Threads outbox identity/publication model mismatch")
    if state.get("direct_publication_enabled") is not True:
        return "DIRECT_DISABLED", []
    event_fp = str(event.get("fingerprint") or "").strip()
    if not event_fp:
        raise ThreadsPublishError("story publication event fingerprint is missing")
    baseline = str(state.get("direct_activation_baseline_event_fingerprint") or "").strip()
    if not baseline:
        return "BASELINE_REQUIRED", []
    if event_fp == baseline:
        return "ACTIVATION_BASELINE", []
    new_ids = event.get("new_story_ids")
    if not isinstance(new_ids, list) or not new_ids:
        return "NO_NEW_STORIES", []
    wanted = {str(value) for value in new_ids if str(value).strip()}
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    failures = state.get("failures") if isinstance(state.get("failures"), dict) else {}
    result: list[dict[str, Any]] = []
    for item in outbox.get("items", []):
        if not isinstance(item, dict) or str(item.get("story_id")) not in wanted:
            continue
        if item.get("status") != "outbox_ready":
            continue
        item_id = str(item.get("id") or "").strip()
        if not item_id or item_id in published:
            continue
        failure = failures.get(item_id)
        if isinstance(failure, dict) and failure.get("manual_reconciliation_required") is True:
            continue
        validate_item(item)
        result.append(item)
    return "READY" if result else "NO_ELIGIBLE_ITEMS", result


def publish_text(token: str, text: str, reply_to_id: str | None = None) -> str:
    params: dict[str, Any] = {
        "media_type": "TEXT",
        "text": text,
        "auto_publish_text": True,
    }
    if reply_to_id:
        params["reply_to_id"] = reply_to_id
    response = api_request("POST", "/me/threads", token, params)
    remote_id = str(response.get("id") or "").strip()
    if not remote_id:
        raise ThreadsPublishError("Threads create/publish response contained no id")
    return remote_id


def preview() -> dict[str, Any]:
    outbox = load(OUTBOX)
    state = load(STATE)
    event = load(EVENT)
    reason, items = eligible_items(outbox, state, event)
    return {
        "status": "PREVIEW",
        "platform": "threads",
        "reason": reason,
        "eligible": [str(item.get("id")) for item in items],
        "network_calls": False,
    }


def health_check() -> dict[str, Any]:
    profile = verify_identity(token_from_env())
    return {
        "status": "PASS",
        "platform": "threads",
        "username": profile["username"],
        "profile_id_present": True,
        "token_value_logged": False,
    }


def apply(max_items: int) -> dict[str, Any]:
    if not live_enabled():
        raise ThreadsPublishError("VALCEA_THREADS_LIVE_ENABLED must be true for --apply")
    token = token_from_env()
    profile = verify_identity(token)
    outbox = load(OUTBOX)
    state = load(STATE)
    event = load(EVENT)
    event_fp = str(event.get("fingerprint") or "").strip()

    baseline = str(state.get("direct_activation_baseline_event_fingerprint") or "").strip()
    if not baseline:
        state["direct_activation_baseline_event_fingerprint"] = event_fp
        state["direct_activation_baselined_at"] = utc_now()
        state["last_verified_username"] = profile["username"]
        write(STATE, state)
        return {"status": "BASELINED", "published": [], "reason": "first direct run never replays backlog"}

    reason, items = eligible_items(outbox, state, event)
    items = items[:max(0, max_items)]
    if not items:
        state["last_verified_username"] = profile["username"]
        state["last_auth_verified_at"] = utc_now()
        write(STATE, state)
        return {"status": "NOOP", "published": [], "reason": reason}

    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    completed: list[dict[str, Any]] = []
    for item in items:
        item_id = str(item["id"])
        posts = validate_item(item)
        remote_ids: list[str] = []
        previous_id: str | None = None
        try:
            for text in posts:
                remote_id = publish_text(token, text, previous_id)
                remote_ids.append(remote_id)
                previous_id = remote_id
        except Exception as exc:
            failures[item_id] = {
                "failed_at": utc_now(),
                "story_id": item.get("story_id"),
                "event_fingerprint": event_fp,
                "product_fingerprint_sha256": item.get("product_fingerprint_sha256"),
                "remote_ids_observed": remote_ids,
                "manual_reconciliation_required": True,
                "reason": str(exc)[:1000],
            }
            state["last_verified_username"] = profile["username"]
            write(STATE, state)
            raise ThreadsPublishError(
                f"Threads item {item_id} entered manual reconciliation after a partial/uncertain publish"
            ) from exc

        published[item_id] = {
            "published_at": utc_now(),
            "story_id": item.get("story_id"),
            "event_fingerprint": event_fp,
            "product_fingerprint_sha256": item.get("product_fingerprint_sha256"),
            "root_remote_id": remote_ids[0],
            "remote_ids": remote_ids,
            "posts": len(posts),
        }
        failures.pop(item_id, None)
        completed.append({"id": item_id, "remote_ids": remote_ids})
        write(STATE, state)

    state["last_verified_username"] = profile["username"]
    state["last_auth_verified_at"] = utc_now()
    state["last_successful_event_fingerprint"] = event_fp
    write(STATE, state)
    return {"status": "PUBLISHED", "published": completed, "username": profile["username"]}


def self_test() -> int:
    item = {
        "id": "threads-story-new",
        "story_id": "new",
        "status": "outbox_ready",
        "direct_publication_enabled": True,
        "source_preserving": True,
        "conversation_native": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "identity": {"channel_id": "valcea-threads"},
        "posts": ["Primul fapt.", "Contextul."],
    }
    outbox = {"platform": "threads", "publication_model": "continuous_story_first", "items": [item]}
    state = {
        "direct_publication_enabled": True,
        "direct_activation_baseline_event_fingerprint": "old",
        "published": {},
        "failures": {},
    }
    reason, items = eligible_items(outbox, state, {"fingerprint": "new", "new_story_ids": ["new"]})
    assert reason == "READY" and [row["id"] for row in items] == ["threads-story-new"]
    reason, items = eligible_items(outbox, state, {"fingerprint": "old", "new_story_ids": ["new"]})
    assert reason == "ACTIVATION_BASELINE" and not items
    state["failures"] = {"threads-story-new": {"manual_reconciliation_required": True}}
    reason, items = eligible_items(outbox, state, {"fingerprint": "new", "new_story_ids": ["new"]})
    assert reason == "NO_ELIGIBLE_ITEMS" and not items
    assert preview is not None
    print("VÂLCEA CLAR Threads direct publisher self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--health-check", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--max-items", type=int, default=int(os.environ.get("VALCEA_THREADS_MAX_PER_RUN", "1")))
    args = parser.parse_args()
    try:
        if args.self_test:
            return self_test()
        if args.health_check:
            result = health_check()
        elif args.apply:
            result = apply(args.max_items)
        else:
            result = preview()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except ThreadsPublishError as exc:
        print(json.dumps({"status": "FAIL", "platform": "threads", "error": str(exc)}, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    sys.exit(main())
