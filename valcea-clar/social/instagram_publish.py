#!/usr/bin/env python3
"""Fail-closed Instagram publisher owned by the CIVORA site engine."""
from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from social_common import (
    OUTBOX,
    compact_caption,
    direct_photo_url,
    load_json,
    photo_metadata,
    platform_ready,
    schedule_ready,
    utc_now,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "valcea-clar" / "social" / "instagram_state.json"
DEFAULT_GRAPH_VERSION = "v26.0"
DEFAULT_GRAPH_HOST = "graph.facebook.com"


def request_json(
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "User-Agent": "ValceaClar-Instagram/1.0",
            **(headers or {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Instagram Graph HTTP {exc.code}: {detail[:1200]}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram Graph transport error: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Instagram Graph returned unexpected payload: {payload!r}")
    if isinstance(payload.get("error"), dict):
        raise RuntimeError(
            "Instagram Graph error: "
            + json.dumps(payload["error"], ensure_ascii=False)
        )
    return payload


def graph_url(host: str, version: str, path: str) -> str:
    return f"https://{host}/{version}/{path.lstrip('/')}"


def graph_get(
    host: str,
    version: str,
    path: str,
    token: str,
    params: dict[str, str] | None = None,
) -> dict[str, Any]:
    query = {"access_token": token, **(params or {})}
    return request_json(
        graph_url(host, version, path)
        + "?"
        + urllib.parse.urlencode(query)
    )


def graph_post(
    host: str,
    version: str,
    path: str,
    token: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    body = urllib.parse.urlencode({**fields, "access_token": token}).encode("utf-8")
    return request_json(
        graph_url(host, version, path),
        method="POST",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )


def remote_jpeg_preflight(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Instagram image URL is not HTTPS: {url}")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "ValceaClar-Instagram-Media-Preflight/1.0",
            "Range": "bytes=0-63",
            "Accept": "image/jpeg,image/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            head = response.read(64)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(
            f"Instagram image is not publicly reachable: {url}: {exc}"
        ) from exc
    if "jpeg" not in content_type and not head.startswith(b"\xff\xd8\xff"):
        raise RuntimeError(
            f"Instagram only accepts JPEG for this adapter; got "
            f"{content_type or 'unknown'} from {url}"
        )


def caption_for(item: dict[str, Any]) -> str:
    metadata = photo_metadata(item)
    config = item.get("platforms", {}).get("instagram", {})
    explicit = str(config.get("caption") or "").strip()
    if explicit:
        return compact_caption(
            explicit,
            str(item["link"]),
            str(metadata.get("credit", "")),
            2200,
        )
    return compact_caption(
        str(item.get("message", "")),
        str(item["link"]),
        str(metadata.get("credit", "")),
        2200,
    )


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("id", "")).strip()
    if not item_id:
        raise ValueError("Instagram outbox item has no id")
    if not platform_ready(item, "instagram"):
        raise ValueError(f"{item_id} is not ready for Instagram")
    metadata = photo_metadata(item)
    image_url = direct_photo_url(item, "instagram")
    caption = caption_for(item)
    if not caption:
        raise ValueError(f"{item_id} has no Instagram caption")
    if not str(metadata.get("alt_text", "")).strip():
        raise ValueError(f"{item_id} has no Instagram alt text")
    return {
        "id": item_id,
        "image_url": image_url,
        "caption": caption,
        "alt_text": str(metadata["alt_text"]).strip(),
        "source_item": item,
    }


def eligible_items(
    outbox: dict[str, Any],
    published: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for raw in outbox.get("items", []):
        if not isinstance(raw, dict) or not platform_ready(raw, "instagram"):
            continue
        item_id = str(raw.get("id", "")).strip()
        if item_id in published or not schedule_ready(raw):
            continue
        try:
            eligible.append(validate_item(raw))
        except (ValueError, RuntimeError) as exc:
            blocked.append({"id": item_id or "<missing>", "reason": str(exc)})
    return eligible, blocked


def wait_for_container(
    host: str,
    version: str,
    container_id: str,
    token: str,
) -> str:
    last = "UNKNOWN"
    for attempt in range(10):
        payload = graph_get(
            host,
            version,
            container_id,
            token,
            {"fields": "status_code"},
        )
        last = str(payload.get("status_code", "") or "UNKNOWN").upper()
        if last in {"FINISHED", "PUBLISHED"}:
            return last
        if last in {"ERROR", "EXPIRED"}:
            raise RuntimeError(
                f"Instagram media container {container_id} entered {last}"
            )
        if attempt < 9:
            time.sleep(2)
    raise RuntimeError(
        f"Instagram media container {container_id} did not finish; last={last}"
    )


def publish_one(
    item: dict[str, Any],
    *,
    account_id: str,
    token: str,
    version: str,
    host: str,
) -> dict[str, Any]:
    remote_jpeg_preflight(item["image_url"])
    container = graph_post(
        host,
        version,
        f"{account_id}/media",
        token,
        {
            "image_url": item["image_url"],
            "caption": item["caption"],
            "alt_text": item["alt_text"],
        },
    )
    container_id = str(container.get("id", "")).strip()
    if not container_id:
        raise RuntimeError(f"Instagram returned no media container id: {container}")
    status = wait_for_container(host, version, container_id, token)
    published = graph_post(
        host,
        version,
        f"{account_id}/media_publish",
        token,
        {"creation_id": container_id},
    )
    media_id = str(published.get("id", "")).strip()
    if not media_id:
        raise RuntimeError(f"Instagram returned no media id: {published}")
    return {
        "instagram_media_id": media_id,
        "container_id": container_id,
        "container_status": status,
        "published_at": utc_now(),
        "image_url": item["image_url"],
    }


def self_test() -> int:
    sample = {
        "id": "ig-test",
        "status": "ready",
        "message": "Titlu\n\nText verificat.",
        "link": "https://valceaclar.ro/",
        "image_path": "valcea-clar/social/photos/approved/test.jpg",
        "image": {
            "kind": "photograph",
            "synthetic": False,
            "subject_match": True,
            "editor_approved": True,
            "source_type": "staff",
            "credit": "Vâlcea Clar",
            "rights_basis": "owned",
            "alt_text": "Imagine de test",
            "direct_source_url": "https://valceaclar.ro/media/social/test.jpg",
        },
        "platforms": {
            "instagram": {
                "status": "ready",
                "mode": "direct_publish",
            }
        },
    }
    plan = validate_item(sample)
    assert plan["id"] == "ig-test"
    assert plan["image_url"].endswith("test.jpg")
    assert "Vâlcea Clar" in plan["caption"]
    bad = json.loads(json.dumps(sample))
    bad["image"]["synthetic"] = True
    try:
        validate_item(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("synthetic image was not rejected")
    print("VÂLCEA CLAR Instagram adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    outbox = load_json(OUTBOX, {"schema_version": "4.0", "items": []})
    state = load_json(
        STATE,
        {
            "schema_version": "1.0",
            "platform": "instagram",
            "execution_owner": "civora_site_engine",
            "published": {},
            "failures": {},
        },
    )
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    if not isinstance(published, dict) or not isinstance(failures, dict):
        raise ValueError("invalid Instagram state structure")

    plan, blocked = eligible_items(outbox, published)
    preview = {
        "status": "DRY_RUN" if not args.apply else "APPLY",
        "eligible": [
            {
                "id": item["id"],
                "image_url": item["image_url"],
                "caption_chars": len(item["caption"]),
            }
            for item in plan
        ],
        "blocked": blocked,
    }
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    if not plan:
        print(
            json.dumps(
                {**preview, "status": "NO_ELIGIBLE_POSTS"},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    account_id = os.getenv("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.getenv("VALCEA_IG_ACCESS_TOKEN", "").strip()
    version = (
        os.getenv("VALCEA_IG_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip()
        or DEFAULT_GRAPH_VERSION
    )
    host = (
        os.getenv("VALCEA_IG_GRAPH_HOST", DEFAULT_GRAPH_HOST).strip()
        or DEFAULT_GRAPH_HOST
    )
    if not account_id or not token:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "BLOCKED_MISSING_CREDENTIALS",
                    "required_secrets": [
                        "VALCEA_IG_ACCOUNT_ID",
                        "VALCEA_IG_ACCESS_TOKEN",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    max_per_run = max(1, int(os.getenv("VALCEA_IG_MAX_PER_RUN", "1")))
    results: list[dict[str, Any]] = []
    for item in plan[:max_per_run]:
        try:
            result = publish_one(
                item,
                account_id=account_id,
                token=token,
                version=version,
                host=host,
            )
        except Exception as exc:
            failures[item["id"]] = {
                "failed_at": utc_now(),
                "error": str(exc),
            }
            state["last_attempt"] = {
                "at": utc_now(),
                "status": "failed",
                "item_id": item["id"],
            }
            write_json(STATE, state)
            raise
        published[item["id"]] = result
        failures.pop(item["id"], None)
        state["last_attempt"] = {
            "at": utc_now(),
            "status": "published",
            "item_id": item["id"],
        }
        write_json(STATE, state)
        results.append({"id": item["id"], **result})

    print(
        json.dumps(
            {
                "status": "PUBLISHED",
                "platform": "instagram",
                "results": results,
                "remaining": max(0, len(plan) - len(results)),
                "blocked": blocked,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
