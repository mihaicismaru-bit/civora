#!/usr/bin/env python3
"""Compliant TikTok photo publisher owned by the CIVORA site engine.

TikTok Direct Post requires fresh creator-info, an allowed privacy choice and
explicit creator consent. The engine therefore never turns an ordinary
editorial-ready item into a TikTok post by itself. Consent must be recorded by
the valceaclar.ro site administration surface, after which this server-side
adapter performs the API publication and status tracking without ChatGPT.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from social_common import (
    OUTBOX,
    canonical_photo_url,
    compact_caption,
    first_line,
    load_json,
    photo_metadata,
    platform_config,
    platform_ready,
    schedule_ready,
    truncate_utf16,
    utc_now,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "valcea-clar" / "social" / "tiktok_state.json"
API_ROOT = "https://open.tiktokapis.com"
ALLOWED_PRIVACY = {
    "PUBLIC_TO_EVERYONE",
    "MUTUAL_FOLLOW_FRIENDS",
    "FOLLOWER_OF_CREATOR",
    "SELF_ONLY",
}
ALLOWED_CONSENT_SOURCES = {
    "valceaclar_site_admin",
    "valceaclar_editorial_console",
}


def request_json(
    path: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 45,
) -> dict[str, Any]:
    url = API_ROOT + path
    data = (
        json.dumps(payload, ensure_ascii=False).encode("utf-8")
        if payload is not None
        else b""
    )
    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "ValceaClar-TikTok/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"TikTok HTTP {exc.code}: {detail[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"TikTok transport error: {exc}") from exc
    if not isinstance(result, dict):
        raise RuntimeError(f"TikTok returned unexpected payload: {result!r}")
    error = result.get("error")
    if isinstance(error, dict) and str(error.get("code", "")).lower() != "ok":
        raise RuntimeError("TikTok API error: " + json.dumps(error, ensure_ascii=False))
    return result


def remote_photo_preflight(url: str) -> None:
    parsed = urllib.parse.urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"valceaclar.ro", "www.valceaclar.ro"}
    ):
        raise ValueError(
            "TikTok PULL_FROM_URL media must use the verified valceaclar.ro domain"
        )
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "ValceaClar-TikTok-Media-Preflight/1.0",
            "Range": "bytes=0-63",
            "Accept": "image/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            head = response.read(64)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(
            f"TikTok photo URL is not publicly reachable: {url}: {exc}"
        ) from exc
    if "image" not in content_type and not (
        head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG")
    ):
        raise RuntimeError(
            f"TikTok media URL returned unsupported content: "
            f"{content_type or 'unknown'}"
        )


def creator_info(token: str) -> dict[str, Any]:
    result = request_json(
        "/v2/post/publish/creator_info/query/",
        token,
        payload={},
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok creator_info missing data: {result}")
    options = data.get("privacy_level_options")
    if not isinstance(options, list) or not options:
        raise RuntimeError("TikTok creator_info returned no privacy options")
    return data


def consent_record(item: dict[str, Any]) -> dict[str, Any]:
    config = platform_config(item, "tiktok") or {}
    value = config.get("consent")
    if not isinstance(value, dict):
        raise ValueError(f"{item.get('id')} has no TikTok consent record")
    if value.get("granted") is not True:
        raise ValueError(f"{item.get('id')} lacks explicit TikTok publish consent")
    if value.get("source") not in ALLOWED_CONSENT_SOURCES:
        raise ValueError(
            f"{item.get('id')} TikTok consent must come from valceaclar.ro site admin"
        )
    if not str(value.get("granted_at", "")).strip():
        raise ValueError(f"{item.get('id')} TikTok consent has no timestamp")
    if not str(value.get("actor", "")).strip():
        raise ValueError(f"{item.get('id')} TikTok consent has no actor")
    return value


def title_for(item: dict[str, Any]) -> str:
    config = platform_config(item, "tiktok") or {}
    value = str(config.get("title") or first_line(str(item.get("message", "")))).strip()
    return truncate_utf16(value, 90)


def description_for(item: dict[str, Any]) -> str:
    config = platform_config(item, "tiktok") or {}
    metadata = photo_metadata(item)
    explicit = str(config.get("description") or "").strip()
    source = explicit or str(item.get("message", "")).strip()
    return compact_caption(
        source,
        str(item.get("link", "")),
        str(metadata.get("credit", "")),
        4000,
    )


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    item_id = str(item.get("id", "")).strip()
    if not item_id:
        raise ValueError("TikTok outbox item has no id")
    if not platform_ready(item, "tiktok"):
        raise ValueError(f"{item_id} is not ready for TikTok")
    config = platform_config(item, "tiktok") or {}
    consent = consent_record(item)
    privacy = str(config.get("privacy_level", "")).strip()
    if privacy not in ALLOWED_PRIVACY:
        raise ValueError(f"{item_id} has no valid TikTok privacy_level")
    photo_metadata(item)
    photo_url = canonical_photo_url(item)
    title = title_for(item)
    description = description_for(item)
    if not title and not description:
        raise ValueError(f"{item_id} has no TikTok copy")
    return {
        "id": item_id,
        "title": title,
        "description": description,
        "privacy_level": privacy,
        "disable_comment": bool(config.get("disable_comment", False)),
        "photo_url": photo_url,
        "consent": consent,
        "source_item": item,
    }


def eligible_items(
    outbox: dict[str, Any],
    state: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    published = state.get("published", {})
    pending = state.get("pending", {})
    eligible: list[dict[str, Any]] = []
    blocked: list[dict[str, str]] = []
    for raw in outbox.get("items", []):
        if not isinstance(raw, dict):
            continue
        config = platform_config(raw, "tiktok")
        if not isinstance(config, dict):
            continue
        item_id = str(raw.get("id", "")).strip()
        if item_id in published or item_id in pending or not schedule_ready(raw):
            continue
        if not platform_ready(raw, "tiktok"):
            reason = str(config.get("reason") or "not_ready")
            blocked.append({"id": item_id or "<missing>", "reason": reason})
            continue
        try:
            eligible.append(validate_item(raw))
        except (ValueError, RuntimeError) as exc:
            blocked.append({"id": item_id or "<missing>", "reason": str(exc)})
    return eligible, blocked


def fetch_status(token: str, publish_id: str) -> dict[str, Any]:
    result = request_json(
        "/v2/post/publish/status/fetch/",
        token,
        payload={"publish_id": publish_id},
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok status response missing data: {result}")
    return data


def refresh_pending(state: dict[str, Any], token: str) -> bool:
    pending = state.setdefault("pending", {})
    published = state.setdefault("published", {})
    failures = state.setdefault("failures", {})
    changed = False
    for item_id, entry in list(pending.items()):
        publish_id = str(entry.get("publish_id", "")).strip()
        if not publish_id:
            failures[item_id] = {
                "failed_at": utc_now(),
                "error": "pending entry has no publish_id",
            }
            pending.pop(item_id, None)
            changed = True
            continue
        status = fetch_status(token, publish_id)
        value = str(status.get("status", "")).upper()
        entry["last_status_at"] = utc_now()
        entry["status"] = value
        entry["status_payload"] = status
        changed = True
        if value == "PUBLISH_COMPLETE":
            ids = (
                status.get("publicaly_available_post_id")
                or status.get("publicly_available_post_id")
                or []
            )
            published[item_id] = {
                **entry,
                "published_at": utc_now(),
                "tiktok_post_ids": ids,
            }
            pending.pop(item_id, None)
            failures.pop(item_id, None)
        elif value == "FAILED":
            failures[item_id] = {
                **entry,
                "failed_at": utc_now(),
                "error": str(status.get("fail_reason", "unknown")),
            }
            pending.pop(item_id, None)
    return changed


def direct_post(
    item: dict[str, Any],
    token: str,
    creator: dict[str, Any],
) -> dict[str, Any]:
    options = [str(value) for value in creator.get("privacy_level_options", [])]
    if item["privacy_level"] not in options:
        raise RuntimeError(
            f"TikTok privacy_level {item['privacy_level']} is not currently allowed; "
            f"available={options}"
        )
    remote_photo_preflight(item["photo_url"])
    payload = {
        "media_type": "PHOTO",
        "post_mode": "DIRECT_POST",
        "post_info": {
            "title": item["title"],
            "description": item["description"],
            "privacy_level": item["privacy_level"],
            "disable_comment": bool(
                item["disable_comment"] or creator.get("comment_disabled", False)
            ),
            "auto_add_music": False,
            "brand_content_toggle": False,
            "brand_organic_toggle": True,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_images": [item["photo_url"]],
            "photo_cover_index": 0,
        },
    }
    result = request_json(
        "/v2/post/publish/content/init/",
        token,
        payload=payload,
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok publish response missing data: {result}")
    publish_id = str(data.get("publish_id", "")).strip()
    if not publish_id:
        raise RuntimeError(f"TikTok returned no publish_id: {result}")
    return {
        "publish_id": publish_id,
        "submitted_at": utc_now(),
        "status": "SUBMITTED",
        "photo_url": item["photo_url"],
        "privacy_level": item["privacy_level"],
        "creator_username": creator.get("creator_username"),
        "creator_nickname": creator.get("creator_nickname"),
        "consent": item["consent"],
    }


def self_test() -> int:
    sample = {
        "id": "tt-test",
        "status": "ready",
        "message": "Știre verificată\n\nDetalii locale.",
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
        },
        "platforms": {
            "tiktok": {
                "status": "ready",
                "mode": "direct_post",
                "photo_url": "https://valceaclar.ro/media/social/test.jpg",
                "privacy_level": "PUBLIC_TO_EVERYONE",
                "consent": {
                    "granted": True,
                    "source": "valceaclar_site_admin",
                    "granted_at": "2026-08-15T10:00:00Z",
                    "actor": "editor-test",
                },
            }
        },
    }
    plan = validate_item(sample)
    assert plan["id"] == "tt-test"
    assert plan["photo_url"].startswith("https://valceaclar.ro/")
    assert plan["privacy_level"] == "PUBLIC_TO_EVERYONE"
    bad = json.loads(json.dumps(sample))
    bad["platforms"]["tiktok"]["consent"]["granted"] = False
    try:
        validate_item(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("TikTok item without consent was not rejected")
    print("VÂLCEA CLAR TikTok adapter self-test: PASS")
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
            "platform": "tiktok",
            "execution_owner": "civora_site_engine",
            "pending": {},
            "published": {},
            "failures": {},
        },
    )
    for key in ("pending", "published", "failures"):
        if not isinstance(state.setdefault(key, {}), dict):
            raise ValueError(f"invalid TikTok state field: {key}")

    plan, blocked = eligible_items(outbox, state)
    preview = {
        "status": "DRY_RUN" if not args.apply else "APPLY",
        "eligible": [
            {
                "id": item["id"],
                "privacy_level": item["privacy_level"],
                "photo_url": item["photo_url"],
            }
            for item in plan
        ],
        "blocked": blocked,
        "pending": list(state["pending"]),
    }
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    token = os.getenv("VALCEA_TIKTOK_ACCESS_TOKEN", "").strip()
    public_approved = (
        os.getenv("VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED", "")
        .strip()
        .lower()
        in {"1", "true", "yes"}
    )

    if state["pending"] and token:
        if refresh_pending(state, token):
            write_json(STATE, state)

    if not plan:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "NO_ELIGIBLE_POSTS",
                    "pending_after_refresh": list(state["pending"]),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not token:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "BLOCKED_MISSING_CREDENTIALS",
                    "required_secret": "VALCEA_TIKTOK_ACCESS_TOKEN",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    if not public_approved:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "BLOCKED_TIKTOK_APP_AUDIT",
                    "required_repository_variable": (
                        "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED=true"
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    creator = creator_info(token)
    max_per_run = max(1, int(os.getenv("VALCEA_TIKTOK_MAX_PER_RUN", "1")))
    results: list[dict[str, Any]] = []
    for item in plan[:max_per_run]:
        try:
            entry = direct_post(item, token, creator)
            state["pending"][item["id"]] = entry
            state["failures"].pop(item["id"], None)
            state["last_attempt"] = {
                "at": utc_now(),
                "status": "submitted",
                "item_id": item["id"],
            }
            write_json(STATE, state)
            status = fetch_status(token, entry["publish_id"])
            entry["status"] = str(status.get("status", "")).upper()
            entry["last_status_at"] = utc_now()
            entry["status_payload"] = status
            if entry["status"] == "PUBLISH_COMPLETE":
                ids = (
                    status.get("publicaly_available_post_id")
                    or status.get("publicly_available_post_id")
                    or []
                )
                state["published"][item["id"]] = {
                    **entry,
                    "published_at": utc_now(),
                    "tiktok_post_ids": ids,
                }
                state["pending"].pop(item["id"], None)
            elif entry["status"] == "FAILED":
                state["failures"][item["id"]] = {
                    **entry,
                    "failed_at": utc_now(),
                    "error": str(status.get("fail_reason", "unknown")),
                }
                state["pending"].pop(item["id"], None)
            write_json(STATE, state)
        except Exception as exc:
            state["failures"][item["id"]] = {
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
        results.append(
            {
                "id": item["id"],
                "publish_id": entry["publish_id"],
                "status": entry["status"],
            }
        )

    print(
        json.dumps(
            {
                "status": "SUBMITTED",
                "platform": "tiktok",
                "creator": {
                    "username": creator.get("creator_username"),
                    "nickname": creator.get("creator_nickname"),
                },
                "results": results,
                "blocked": blocked,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
