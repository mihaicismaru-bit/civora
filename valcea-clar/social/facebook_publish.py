#!/usr/bin/env python3
"""Fail-closed Facebook Page distributor for VÂLCEA CLAR.

Only curated items with status=ready and a rendered, story-specific image are
eligible. New photo posts are published first; superseded wrong-image posts are
then removed. State is persisted for idempotent retries.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTBOX = ROOT / "valcea-clar" / "social" / "facebook_outbox.json"
STATE = ROOT / "valcea-clar" / "social" / "facebook_state.json"
GENERATED = (ROOT / "valcea-clar" / "social" / "generated").resolve()
DEFAULT_GRAPH_VERSION = "v26.0"
CANONICAL_HOSTS = {"valceaclar.ro", "www.valceaclar.ro"}


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def image_file(item: dict[str, Any]) -> Path:
    raw = str(item.get("image_path", "")).strip()
    if not raw:
        raise ValueError(f"ready Facebook item {item['id']} has no image_path")
    path = (ROOT / raw).resolve()
    if path != GENERATED and GENERATED not in path.parents:
        raise ValueError(f"Facebook image must be rendered under {GENERATED}: {raw}")
    if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
        raise ValueError(f"Facebook image does not exist or is unsupported: {raw}")
    return path


def validate_item(item: dict[str, Any]) -> None:
    required = ("id", "status", "message", "link")
    missing = [key for key in required if not str(item.get(key, "")).strip()]
    if missing:
        raise ValueError(f"outbox item missing fields: {', '.join(missing)}")
    if item["status"] not in {"hold", "ready", "disabled"}:
        raise ValueError(f"invalid status for {item['id']}: {item['status']}")
    parsed = urllib.parse.urlparse(str(item["link"]).strip())
    if parsed.scheme != "https" or parsed.hostname not in CANONICAL_HOSTS:
        raise ValueError(f"non-canonical link for {item['id']}: {item['link']}")


def eligible(items: list[dict[str, Any]], published: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    now = dt.datetime.now(dt.timezone.utc)
    for item in items:
        validate_item(item)
        if item["status"] != "ready" or item["id"] in published:
            continue
        image_file(item)
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
    endpoint += ("&" if "?" in endpoint else "?") + "access_token=" + urllib.parse.quote(token, safe="")
    request = urllib.request.Request(endpoint, method="GET", headers={"User-Agent": "ValceaClar-Facebook/2.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta GET HTTP {exc.code}: {detail[:800]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Meta GET returned unexpected payload: {payload!r}")
    return payload


def resolve_page_token(page_id: str, supplied_token: str, version: str) -> tuple[str, dict[str, Any]]:
    identity = graph_get("me?fields=id,name", supplied_token, version)
    identity_id = str(identity.get("id", ""))
    if identity_id == page_id:
        return supplied_token, {"source": "page_token", "page_id": page_id, "page_name": identity.get("name")}
    page = graph_get(f"{page_id}?fields=id,name,access_token", supplied_token, version)
    derived = str(page.get("access_token", "")).strip()
    if str(page.get("id", "")) != page_id or not derived:
        raise RuntimeError("Meta did not return a Page Access Token for VÂLCEA CLAR")
    check = graph_get("me?fields=id,name", derived, version)
    if str(check.get("id", "")) != page_id:
        raise RuntimeError(f"Derived token identifies {check.get('id')}, not {page_id}")
    return derived, {
        "source": "derived_from_user_token",
        "user_id": identity_id,
        "page_id": page_id,
        "page_name": check.get("name"),
    }


def multipart(fields: dict[str, str], file_path: Path) -> tuple[bytes, str]:
    boundary = f"----ValceaClar{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for key, value in fields.items():
        chunks.extend([
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            value.encode("utf-8"),
            b"\r\n",
        ])
    mime = mimetypes.guess_type(file_path.name)[0] or "image/jpeg"
    chunks.extend([
        f"--{boundary}\r\n".encode(),
        f'Content-Disposition: form-data; name="source"; filename="{file_path.name}"\r\n'.encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        file_path.read_bytes(),
        b"\r\n",
        f"--{boundary}--\r\n".encode(),
    ])
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def graph_photo_post(page_id: str, token: str, version: str, item: dict[str, Any]) -> str:
    path = image_file(item)
    caption = f"{str(item['message']).strip()}\n\n{str(item['link']).strip()}"
    body, content_type = multipart({"caption": caption, "published": "true", "access_token": token}, path)
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{page_id}/photos",
        data=body,
        method="POST",
        headers={"Content-Type": content_type, "User-Agent": "ValceaClar-Facebook/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta photo POST HTTP {exc.code}: {detail[:1000]}") from exc
    post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
    if not post_id:
        raise RuntimeError(f"Meta returned no post id: {payload}")
    return post_id


def graph_delete(object_id: str, token: str, version: str) -> dict[str, Any]:
    body = urllib.parse.urlencode({"access_token": token}).encode()
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{urllib.parse.quote(object_id, safe='')}",
        data=body,
        method="DELETE",
        headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "ValceaClar-Facebook/2.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return {"status": "deleted", "response": payload}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        if exc.code == 400 and ("Unsupported get request" in detail or "does not exist" in detail):
            return {"status": "already_absent"}
        return {"status": "error", "http": exc.code, "detail": detail[:500]}


def write_state(state: dict[str, Any]) -> None:
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cleanup_replacements(state: dict[str, Any], token: str, version: str) -> None:
    changed = False
    for entry in state.get("published", {}).values():
        replacements = entry.get("replaces") or []
        cleanup = entry.setdefault("replacement_cleanup", {})
        for old_id in replacements:
            if cleanup.get(old_id, {}).get("status") in {"deleted", "already_absent"}:
                continue
            cleanup[old_id] = graph_delete(str(old_id), token, version)
            changed = True
    if changed:
        write_state(state)


def self_test() -> int:
    sample = {
        "id": "a",
        "status": "ready",
        "message": "Test",
        "link": "https://valceaclar.ro/",
        "image_path": "valcea-clar/social/generated/launch-valcea-clar.jpg",
    }
    validate_item(sample)
    assert str(image_file(sample)).endswith("launch-valcea-clar.jpg")
    assert eligible([sample], {})[0]["id"] == "a"
    assert eligible([sample], {"a": {}}) == []
    print("VÂLCEA CLAR Facebook distributor self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    outbox = load_json(OUTBOX, {"schema_version": "2.0", "items": []})
    items = outbox.get("items", [])
    state = load_json(STATE, {"schema_version": "2.0", "published": {}})
    published = state.setdefault("published", {})
    if not isinstance(items, list) or not isinstance(published, dict):
        raise ValueError("invalid Facebook outbox/state structure")

    plan = eligible(items, published)
    if not args.apply:
        print(json.dumps({"status": "DRY_RUN", "eligible": plan}, ensure_ascii=False, indent=2))
        return 0

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    supplied_token = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    if not page_id or not supplied_token:
        raise RuntimeError("Missing VALCEA_FB_PAGE_ID or VALCEA_FB_PAGE_ACCESS_TOKEN")
    page_token, resolution = resolve_page_token(page_id, supplied_token, version)
    print(json.dumps({"status": "FACEBOOK_TOKEN_RESOLVED", **resolution}, ensure_ascii=False))

    cleanup_replacements(state, page_token, version)
    results = []
    for item in plan:
        post_id = graph_photo_post(page_id, page_token, version, item)
        entry = {
            "facebook_post_id": post_id,
            "published_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "link": item["link"],
            "image_path": item["image_path"],
            "replaces": list(item.get("replace_post_ids") or []),
            "replacement_cleanup": {},
        }
        published[item["id"]] = entry
        write_state(state)
        cleanup_replacements(state, page_token, version)
        results.append({"id": item["id"], "facebook_post_id": post_id})
    print(json.dumps({"status": "PUBLISHED", "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
