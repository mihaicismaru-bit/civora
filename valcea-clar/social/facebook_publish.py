#!/usr/bin/env python3
"""Fail-closed Facebook Page distributor for VÂLCEA CLAR.

Reads a curated outbox. It never publishes inferred/discovered records directly.
A post is eligible only when status == "ready". Published IDs are persisted in
facebook_state.json so retries are idempotent.
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
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTBOX = ROOT / "valcea-clar" / "social" / "facebook_outbox.json"
STATE = ROOT / "valcea-clar" / "social" / "facebook_state.json"
DEFAULT_GRAPH_VERSION = "v25.0"


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def validate_item(item: dict[str, Any]) -> None:
    required = ("id", "status", "message", "link")
    missing = [key for key in required if not str(item.get(key, "")).strip()]
    if missing:
        raise ValueError(f"outbox item missing fields: {', '.join(missing)}")
    if item["status"] not in {"hold", "ready", "disabled"}:
        raise ValueError(f"invalid status for {item['id']}: {item['status']}")
    link = str(item["link"]).strip()
    parsed = urllib.parse.urlparse(link)
    if parsed.scheme != "https" or parsed.hostname not in {"valceaclar.ro", "www.valceaclar.ro"}:
        raise ValueError(f"non-canonical link for {item['id']}: {link}")


def eligible(items: list[dict[str, Any]], published: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)
    for item in items:
        validate_item(item)
        if item["status"] != "ready" or item["id"] in published:
            continue
        publish_after = item.get("publish_after")
        if publish_after:
            when = dt.datetime.fromisoformat(str(publish_after).replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
            if when > now:
                continue
        result.append(item)
    return result


def graph_get(path: str, token: str, version: str) -> dict[str, Any]:
    endpoint = f"https://graph.facebook.com/{version}/{path.lstrip('/')}"
    separator = "&" if "?" in endpoint else "?"
    endpoint = f"{endpoint}{separator}access_token={urllib.parse.quote(token, safe='')}"
    request = urllib.request.Request(
        endpoint,
        method="GET",
        headers={"User-Agent": "ValceaClar-Facebook-Distributor/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta Graph API GET HTTP {exc.code}: {detail[:600]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Meta Graph API GET returned unexpected payload: {payload!r}")
    return payload


def graph_preflight(page_id: str, token: str, version: str) -> dict[str, Any]:
    result: dict[str, Any] = {"expected_page_id": page_id}
    try:
        identity = graph_get("me?fields=id,name", token, version)
        result["token_identity"] = {"id": identity.get("id"), "name": identity.get("name")}
    except Exception as exc:  # diagnostic only
        result["token_identity_error"] = str(exc)
    try:
        page = graph_get(f"{urllib.parse.quote(page_id, safe='')}?fields=id,name,tasks", token, version)
        result["page"] = {"id": page.get("id"), "name": page.get("name"), "tasks": page.get("tasks")}
    except Exception as exc:  # diagnostic only
        result["page_tasks_error"] = str(exc)
    return result


def graph_post(page_id: str, token: str, version: str, item: dict[str, Any]) -> str:
    endpoint = f"https://graph.facebook.com/{version}/{urllib.parse.quote(page_id, safe='')}/feed"
    body = urllib.parse.urlencode(
        {
            "message": str(item["message"]),
            "link": str(item["link"]),
            "access_token": token,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ValceaClar-Facebook-Distributor/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta Graph API HTTP {exc.code}: {detail[:600]}") from exc
    post_id = str(payload.get("id", "")).strip()
    if not post_id:
        raise RuntimeError(f"Meta Graph API returned no post id: {payload}")
    return post_id


def write_state(state: dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test() -> int:
    sample = [
        {"id": "a", "status": "ready", "message": "Test", "link": "https://valceaclar.ro/"},
        {"id": "b", "status": "hold", "message": "Hold", "link": "https://valceaclar.ro/x"},
    ]
    planned = eligible(sample, {})
    assert [item["id"] for item in planned] == ["a"]
    assert eligible(sample, {"a": {"facebook_post_id": "1"}}) == []
    try:
        validate_item({"id": "x", "status": "ready", "message": "x", "link": "https://example.com/"})
    except ValueError:
        pass
    else:
        raise AssertionError("external URL was not rejected")
    print("VÂLCEA CLAR Facebook distributor self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="publish eligible items")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    outbox = load_json(OUTBOX, {"schema_version": "1.0", "items": []})
    items = outbox.get("items", [])
    if not isinstance(items, list):
        raise ValueError("facebook_outbox.json: items must be a list")
    state = load_json(STATE, {"schema_version": "1.0", "published": {}})
    published = state.setdefault("published", {})
    if not isinstance(published, dict):
        raise ValueError("facebook_state.json: published must be an object")

    plan = eligible(items, published)
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "eligible": plan}, ensure_ascii=False, indent=2))
        return 0

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    token = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    if not (page_id and token):
        print(
            json.dumps(
                {
                    "status": "SKIPPED_MISSING_FACEBOOK_CREDENTIALS",
                    "eligible_count": len(plan),
                    "required": ["VALCEA_FB_PAGE_ID", "VALCEA_FB_PAGE_ACCESS_TOKEN"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    preflight = graph_preflight(page_id, token, version)
    print(json.dumps({"status": "FACEBOOK_PREFLIGHT", **preflight}, ensure_ascii=False, indent=2))

    results = []
    for item in plan:
        post_id = graph_post(page_id, token, version, item)
        published[item["id"]] = {
            "facebook_post_id": post_id,
            "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "link": item["link"],
        }
        write_state(state)
        results.append({"id": item["id"], "facebook_post_id": post_id})

    print(json.dumps({"status": "PUBLISHED", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
