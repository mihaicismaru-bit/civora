#!/usr/bin/env python3
"""Fail-closed TikTok publisher executed only by the CIVORA site engine.

The historical VÂLCEA CLAR photo outbox remains supported. LOCAL NEWS OS native
adapter payloads can now submit either a single-photo post or a real-video short.
Native submissions are asynchronous: this module returns TikTok's ``publish_id``
as a remote submission identifier and exposes a separate status reconciler. A
caller must not mark a publication PUBLISHED until reconciliation yields remote
publication proof.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from social_common import (
    ALLOWED_RIGHTS,
    ALLOWED_SOURCE_TYPES,
    OUTBOX,
    canonical_link,
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
    utf16_units,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "valcea-clar" / "social" / "tiktok_state.json"
API_ROOT = "https://open.tiktokapis.com"
NATIVE_ADAPTER_NAME = "valcea-clar/social/tiktok_publish.py"
NATIVE_INSTANCE_ID = "valcea"
NATIVE_CHANNEL_ID = "valcea-tiktok"
SUPPORTED_NATIVE_FORMATS = {"single_photo", "short"}
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
FORBIDDEN_PAYLOAD_KEY_PARTS = {
    "access_token",
    "client_secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
}
TERMINAL_PUBLISH_STATUS = {"PUBLISH_COMPLETE", "FAILED"}
PENDING_PUBLISH_STATUS = {
    "PROCESSING_UPLOAD",
    "PROCESSING_DOWNLOAD",
    "SEND_TO_USER_INBOX",
}


def request_json(
    path: str,
    token: str,
    *,
    payload: dict[str, Any],
    timeout: int = 45,
) -> dict[str, Any]:
    request = urllib.request.Request(
        API_ROOT + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "User-Agent": "ValceaClar-TikTok/1.1",
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


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _fingerprint_matches(value: dict[str, Any], field: str) -> bool:
    supplied = str(value.get(field, "")).strip().lower()
    if not _is_sha256(supplied):
        return False
    candidate = copy.deepcopy(value)
    candidate.pop(field, None)
    return supplied == _digest(candidate)


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = str(key).strip().lower()
            if any(part in lowered for part in FORBIDDEN_PAYLOAD_KEY_PARTS):
                return True
            if _contains_secret_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(child) for child in value)
    return False


def _verified_media_url(url: str, *, label: str) -> str:
    value = str(url or "").strip()
    parsed = urllib.parse.urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {"valceaclar.ro", "www.valceaclar.ro"}:
        raise ValueError(f"TikTok {label} URL must use the verified valceaclar.ro domain")
    return value


def remote_photo_preflight(url: str) -> None:
    url = _verified_media_url(url, label="photo")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "ValceaClar-TikTok-Media-Preflight/1.1",
            "Range": "bytes=0-63",
            "Accept": "image/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            head = response.read(64)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"TikTok photo URL is not publicly reachable: {url}: {exc}") from exc
    if final_url != url:
        raise RuntimeError("TikTok PULL_FROM_URL photo must not redirect")
    if "image" not in content_type and not (
        head.startswith(b"\xff\xd8\xff") or head.startswith(b"\x89PNG")
    ):
        raise RuntimeError(
            f"TikTok photo URL returned unsupported content: {content_type or 'unknown'}"
        )


def remote_video_preflight(url: str) -> None:
    url = _verified_media_url(url, label="video")
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "ValceaClar-TikTok-Video-Preflight/1.1",
            "Range": "bytes=0-127",
            "Accept": "video/mp4,video/webm,video/quicktime,video/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            final_url = response.geturl()
            content_type = (response.headers.get("Content-Type") or "").lower()
            head = response.read(128)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"TikTok video URL is not publicly reachable: {url}: {exc}") from exc
    if final_url != url:
        raise RuntimeError("TikTok PULL_FROM_URL video must not redirect")
    signature_ok = b"ftyp" in head[:64] or head.startswith(b"\x1aE\xdf\xa3")
    if not (content_type.startswith("video/") or signature_ok):
        raise RuntimeError(
            f"TikTok video URL returned unsupported content: {content_type or 'unknown'}"
        )


def creator_info(token: str) -> dict[str, Any]:
    result = request_json(
        "/v2/post/publish/creator_info/query/", token, payload={}
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok creator_info missing data: {result}")
    options = data.get("privacy_level_options")
    if not isinstance(options, list) or not options:
        raise RuntimeError("TikTok creator_info returned no privacy options")
    return data


def _consent_record(value: Any, *, item_id: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{item_id} has no TikTok consent record")
    if value.get("granted") is not True:
        raise ValueError(f"{item_id} lacks explicit TikTok publish consent")
    if value.get("source") not in ALLOWED_CONSENT_SOURCES:
        raise ValueError(
            f"{item_id} consent must come from valceaclar.ro administration"
        )
    if not str(value.get("granted_at", "")).strip():
        raise ValueError(f"{item_id} TikTok consent has no timestamp")
    if not str(value.get("actor", "")).strip():
        raise ValueError(f"{item_id} TikTok consent has no actor")
    return copy.deepcopy(value)


def consent_record(item: dict[str, Any]) -> dict[str, Any]:
    config = platform_config(item, "tiktok") or {}
    return _consent_record(config.get("consent"), item_id=str(item.get("id") or "<missing>"))


def _native_text(product: dict[str, Any]) -> tuple[str, str]:
    hook = product.get("hook") if isinstance(product.get("hook"), dict) else {}
    hook_text = str(hook.get("text", "")).strip()
    block_texts: list[str] = []
    blocks = product.get("content_blocks")
    if isinstance(blocks, list):
        for raw in blocks:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text", "")).strip()
            if text:
                block_texts.append(text)
    all_parts = [part for part in [hook_text, *block_texts] if part]
    caption = "\n\n".join(all_parts).strip()
    if not caption:
        raise ValueError("TikTok native payload has no source-preserving copy")
    if utf16_units(caption) > 2200:
        raise ValueError("TikTok native video caption exceeds 2200 UTF-16 units")
    description = "\n\n".join(block_texts).strip()
    if utf16_units(hook_text) > 90:
        raise ValueError("TikTok native photo title exceeds 90 UTF-16 units")
    if utf16_units(description) > 4000:
        raise ValueError("TikTok native photo description exceeds 4000 UTF-16 units")
    return caption, description


def _validate_native_asset(asset: dict[str, Any], expected_kind: str) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise ValueError("TikTok native media asset is not a mapping")
    asset_id = str(asset.get("asset_id", "")).strip()
    if not asset_id:
        raise ValueError("TikTok native media asset has no asset_id")
    kind = str(asset.get("kind", "")).strip().lower()
    aliases = {"photo": "photograph", "photograph": "photograph", "video": "video"}
    kind = aliases.get(kind, kind)
    if kind != expected_kind:
        raise ValueError(f"TikTok native asset {asset_id} must be {expected_kind}")
    if asset.get("synthetic") is not False:
        raise ValueError(f"TikTok native asset {asset_id} is synthetic or unverified")
    if asset.get("subject_match") is not True:
        raise ValueError(f"TikTok native asset {asset_id} lacks subject match")
    if asset.get("editor_approved") is not True:
        raise ValueError(f"TikTok native asset {asset_id} lacks editorial approval")
    source_type = str(asset.get("source_type", "")).strip()
    rights_basis = str(asset.get("rights_basis", "")).strip()
    credit = str(asset.get("credit", "")).strip()
    alt_text = str(asset.get("alt_text", "")).strip()
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"TikTok native asset {asset_id} has invalid source_type")
    if rights_basis not in ALLOWED_RIGHTS:
        raise ValueError(f"TikTok native asset {asset_id} lacks reuse rights")
    if not credit or not alt_text:
        raise ValueError(f"TikTok native asset {asset_id} lacks credit or alt text")
    if source_type not in {"staff", "public_domain"} and not str(asset.get("source_url", "")).strip():
        raise ValueError(f"TikTok native asset {asset_id} lacks provenance source_url")
    sha256 = str(asset.get("sha256", "")).strip().lower()
    if not _is_sha256(sha256):
        raise ValueError(f"TikTok native asset {asset_id} has invalid sha256")
    url = str(asset.get("direct_source_url", "") or asset.get("source_url", "")).strip()
    url = _verified_media_url(url, label=expected_kind)
    return {
        "asset_id": asset_id,
        "kind": expected_kind,
        "media_url": url,
        "alt_text": alt_text,
        "credit": credit,
        "sha256": sha256,
    }


def validate_native_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate one LOCAL NEWS OS TikTok adapter payload without credentials."""
    if not isinstance(payload, dict):
        raise TypeError("TikTok adapter payload must be a mapping")
    if _contains_secret_field(payload):
        raise ValueError("TikTok adapter payload must not contain credential values")
    if str(payload.get("instance_id", "")).strip() != NATIVE_INSTANCE_ID:
        raise ValueError("TikTok adapter payload instance mismatch")
    if str(payload.get("channel_id", "")).strip() != NATIVE_CHANNEL_ID:
        raise ValueError("TikTok adapter payload channel mismatch")
    if str(payload.get("platform", "")).strip().lower() != "tiktok":
        raise ValueError("TikTok adapter payload platform mismatch")

    publication_id = str(payload.get("publication_id", "")).strip()
    dedupe_key = str(payload.get("dedupe_key", "")).strip()
    if not publication_id or not dedupe_key:
        raise ValueError("TikTok adapter payload lacks publication identity")

    product = payload.get("native_product")
    if not isinstance(product, dict):
        raise ValueError("TikTok adapter payload has no native_product")
    if str(product.get("product_id", "")).strip() != str(payload.get("product_id", "")).strip():
        raise ValueError("TikTok native product identity mismatch")
    supplied_product_fp = str(payload.get("product_fingerprint_sha256", "")).strip().lower()
    if not _is_sha256(supplied_product_fp):
        raise ValueError("TikTok adapter payload has invalid product fingerprint")
    if str(product.get("product_fingerprint_sha256", "")).strip().lower() != supplied_product_fp:
        raise ValueError("TikTok native product fingerprint mismatch")
    if not _fingerprint_matches(product, "product_fingerprint_sha256"):
        raise ValueError("TikTok native product fingerprint is not authentic")
    if product.get("cross_post_policy") != "NATIVE_PRODUCT_ONLY":
        raise ValueError("TikTok adapter requires NATIVE_PRODUCT_ONLY")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        raise ValueError("TikTok adapter forbids verbatim cross-platform reuse")
    if product.get("analytics_used") is not False:
        raise ValueError("TikTok adapter forbids predictive/invented analytics")

    native_format = str(product.get("native_format", "")).strip()
    if native_format not in SUPPORTED_NATIVE_FORMATS:
        raise ValueError(f"TikTok native format is unsupported by adapter: {native_format}")
    caption, description = _native_text(product)

    binding = payload.get("visual_binding")
    if not isinstance(binding, dict) or binding.get("status") != "VISUAL_READY":
        raise ValueError("TikTok native payload lacks VISUAL_READY binding")
    if binding.get("synthetic_media_used") is not False:
        raise ValueError("TikTok native payload used synthetic media")
    if binding.get("provenance_complete") is not True or binding.get("reuse_rights_complete") is not True:
        raise ValueError("TikTok native payload lacks provenance or reuse rights")
    if not _fingerprint_matches(binding, "binding_fingerprint_sha256"):
        raise ValueError("TikTok visual binding fingerprint is invalid")
    selected = binding.get("selected_assets")
    if not isinstance(selected, list) or len(selected) != 1:
        raise ValueError("TikTok native post requires exactly one approved media asset")
    expected_kind = "video" if native_format == "short" else "photograph"
    media = _validate_native_asset(selected[0], expected_kind)

    return {
        "publication_id": publication_id,
        "dedupe_key": dedupe_key,
        "product_id": str(payload.get("product_id", "")).strip(),
        "native_format": native_format,
        "caption": caption,
        "photo_title": str((product.get("hook") or {}).get("text", "")).strip(),
        "photo_description": description,
        "media": media,
    }


def validate_publish_settings(settings: dict[str, Any], *, native_format: str) -> dict[str, Any]:
    """Validate explicit creator choices captured by the site administration UI."""
    if not isinstance(settings, dict):
        raise TypeError("TikTok publish settings must be a mapping")
    if _contains_secret_field(settings):
        raise ValueError("TikTok publish settings must not contain credentials")
    privacy = str(settings.get("privacy_level", "")).strip()
    if privacy not in ALLOWED_PRIVACY:
        raise ValueError("TikTok privacy_level must be explicitly selected")
    consent = _consent_record(settings.get("consent"), item_id="native TikTok publication")
    if settings.get("music_usage_confirmed") is not True:
        raise ValueError("TikTok Music Usage Confirmation is required before publish")
    if not str(settings.get("music_usage_confirmed_at", "")).strip():
        raise ValueError("TikTok Music Usage Confirmation requires a timestamp")

    required_interactions = ["allow_comment"]
    if native_format == "short":
        required_interactions.extend(["allow_duet", "allow_stitch"])
    for key in required_interactions:
        if not isinstance(settings.get(key), bool):
            raise ValueError(f"TikTok {key} must be an explicit creator choice")

    cover = settings.get("video_cover_timestamp_ms")
    if cover is not None and (not isinstance(cover, int) or isinstance(cover, bool) or cover < 0):
        raise ValueError("TikTok video_cover_timestamp_ms must be a non-negative integer")
    return {
        "privacy_level": privacy,
        "consent": consent,
        "music_usage_confirmed": True,
        "music_usage_confirmed_at": str(settings.get("music_usage_confirmed_at")).strip(),
        "allow_comment": bool(settings.get("allow_comment")),
        "allow_duet": bool(settings.get("allow_duet", False)),
        "allow_stitch": bool(settings.get("allow_stitch", False)),
        "video_cover_timestamp_ms": cover,
    }


def publish_native_payload(
    payload: dict[str, Any],
    *,
    token: str,
    publish_settings: dict[str, Any],
    creator_query_fn: Callable[[str], dict[str, Any]] = creator_info,
    request_fn: Callable[..., dict[str, Any]] = request_json,
    photo_preflight_fn: Callable[[str], None] = remote_photo_preflight,
    video_preflight_fn: Callable[[str], None] = remote_video_preflight,
) -> dict[str, Any]:
    """Submit one native TikTok product and return an async remote submission id.

    This function intentionally does not claim publication success. The returned
    ``remote_submission_id`` must be reconciled with ``reconcile_native_submission``.
    """
    token = str(token or "").strip()
    if not token:
        raise ValueError("TikTok native publish requires a runtime access token")
    item = validate_native_payload(payload)
    settings = validate_publish_settings(publish_settings, native_format=item["native_format"])
    creator = creator_query_fn(token)
    options = [str(value) for value in creator.get("privacy_level_options", [])]
    if settings["privacy_level"] not in options:
        raise RuntimeError(
            f"TikTok privacy {settings['privacy_level']} is not currently allowed; available={options}"
        )

    disable_comment = (not settings["allow_comment"]) or bool(creator.get("comment_disabled", False))
    if item["native_format"] == "short":
        video_preflight_fn(item["media"]["media_url"])
        post_info: dict[str, Any] = {
            "title": item["caption"],
            "privacy_level": settings["privacy_level"],
            "disable_comment": disable_comment,
            "disable_duet": (not settings["allow_duet"]) or bool(creator.get("duet_disabled", False)),
            "disable_stitch": (not settings["allow_stitch"]) or bool(creator.get("stitch_disabled", False)),
            "brand_content_toggle": False,
            "brand_organic_toggle": False,
            "is_aigc": False,
        }
        if settings["video_cover_timestamp_ms"] is not None:
            post_info["video_cover_timestamp_ms"] = settings["video_cover_timestamp_ms"]
        result = request_fn(
            "/v2/post/publish/video/init/",
            token,
            payload={
                "post_info": post_info,
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "video_url": item["media"]["media_url"],
                },
            },
        )
    else:
        photo_preflight_fn(item["media"]["media_url"])
        result = request_fn(
            "/v2/post/publish/content/init/",
            token,
            payload={
                "media_type": "PHOTO",
                "post_mode": "DIRECT_POST",
                "post_info": {
                    "title": item["photo_title"],
                    "description": item["photo_description"],
                    "privacy_level": settings["privacy_level"],
                    "disable_comment": disable_comment,
                    "auto_add_music": False,
                    "brand_content_toggle": False,
                    "brand_organic_toggle": False,
                },
                "source_info": {
                    "source": "PULL_FROM_URL",
                    "photo_images": [item["media"]["media_url"]],
                    "photo_cover_index": 0,
                },
            },
        )
    data = result.get("data")
    publish_id = str(data.get("publish_id", "")).strip() if isinstance(data, dict) else ""
    if not publish_id:
        raise RuntimeError(f"TikTok returned no publish_id: {result}")
    return {
        "accepted": True,
        "remote_submission_id": publish_id,
        "adapter": NATIVE_ADAPTER_NAME,
        "publication_id": item["publication_id"],
        "native_format": item["native_format"],
        "credential_values_included": False,
        "network_submission_performed": True,
        "publication_confirmed": False,
    }


def reconcile_native_submission(
    token: str,
    publish_id: str,
    *,
    request_fn: Callable[..., dict[str, Any]] = request_json,
) -> dict[str, Any]:
    """Normalize TikTok async status without inventing publication proof."""
    token = str(token or "").strip()
    publish_id = str(publish_id or "").strip()
    if not token or not publish_id:
        raise ValueError("TikTok reconciliation requires token and publish_id")
    result = request_fn(
        "/v2/post/publish/status/fetch/",
        token,
        payload={"publish_id": publish_id},
    )
    data = result.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"TikTok status response missing data: {result}")
    status = str(data.get("status", "")).strip().upper()
    ids = data.get("publicaly_available_post_id") or data.get("publicly_available_post_id") or []
    post_ids = [str(value).strip() for value in ids if str(value).strip()] if isinstance(ids, list) else []
    if status == "PUBLISH_COMPLETE" and post_ids:
        return {
            "state": "PUBLISHED",
            "remote_submission_id": publish_id,
            "remote_publication_id": post_ids[0],
            "provider_status": status,
            "publication_confirmed": True,
        }
    if status == "PUBLISH_COMPLETE":
        return {
            "state": "PENDING_PUBLICATION_PROOF",
            "remote_submission_id": publish_id,
            "remote_publication_id": None,
            "provider_status": status,
            "publication_confirmed": False,
        }
    if status == "FAILED":
        return {
            "state": "FAILED",
            "remote_submission_id": publish_id,
            "remote_publication_id": None,
            "provider_status": status,
            "error_code": str(data.get("fail_reason", "unknown"))[:240],
            "publication_confirmed": False,
        }
    return {
        "state": "PENDING",
        "remote_submission_id": publish_id,
        "remote_publication_id": None,
        "provider_status": status or "UNKNOWN",
        "publication_confirmed": False,
    }


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    """Validate the historical shared outbox single-photo shape."""
    item_id = str(item.get("id", "")).strip()
    if not item_id:
        raise ValueError("TikTok item has no id")
    if not platform_ready(item, "tiktok"):
        raise ValueError(f"{item_id} is not ready for TikTok")
    link = canonical_link(item)
    metadata = photo_metadata(item)
    config = platform_config(item, "tiktok") or {}
    consent = consent_record(item)
    privacy = str(config.get("privacy_level", "")).strip()
    if privacy not in ALLOWED_PRIVACY:
        raise ValueError(f"{item_id} has no valid TikTok privacy_level")
    title = truncate_utf16(
        str(config.get("title") or first_line(str(item.get("message", "")))), 90
    )
    description = compact_caption(
        str(config.get("description") or item.get("message", "")),
        link,
        str(metadata.get("credit", "")),
        4000,
    )
    if not title and not description:
        raise ValueError(f"{item_id} has no TikTok copy")
    return {
        "id": item_id,
        "title": title,
        "description": description,
        "privacy_level": privacy,
        "disable_comment": bool(config.get("disable_comment", False)),
        "photo_url": canonical_photo_url(item),
        "consent": consent,
    }


def eligible_items(
    outbox: dict[str, Any], state: dict[str, Any]
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
            blocked.append(
                {
                    "id": item_id or "<missing>",
                    "reason": str(config.get("reason") or "not_ready"),
                }
            )
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
        entry.update(
            {
                "last_status_at": utc_now(),
                "status": value,
                "status_payload": status,
            }
        )
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
    item: dict[str, Any], token: str, creator: dict[str, Any]
) -> dict[str, Any]:
    """Historical photo Direct Post path retained unchanged in behavior."""
    options = [str(value) for value in creator.get("privacy_level_options", [])]
    if item["privacy_level"] not in options:
        raise RuntimeError(
            f"TikTok privacy {item['privacy_level']} not currently allowed; available={options}"
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
            "brand_organic_toggle": False,
        },
        "source_info": {
            "source": "PULL_FROM_URL",
            "photo_images": [item["photo_url"]],
            "photo_cover_index": 0,
        },
    }
    result = request_json(
        "/v2/post/publish/content/init/", token, payload=payload
    )
    data = result.get("data")
    publish_id = str(data.get("publish_id", "")).strip() if isinstance(data, dict) else ""
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


def _test_asset(kind: str) -> dict[str, Any]:
    suffix = "video" if kind == "video" else "photo"
    return {
        "asset_id": f"asset-{suffix}",
        "kind": kind,
        "sha256": hashlib.sha256(f"asset-{suffix}".encode("utf-8")).hexdigest(),
        "source_type": "staff",
        "source_url": None,
        "direct_source_url": f"https://valceaclar.ro/media/social/native-test.{ 'mp4' if kind == 'video' else 'jpg'}",
        "credit": "Vâlcea Clar",
        "rights_basis": "owned",
        "license_url": None,
        "rights_note": None,
        "alt_text": f"Media reală de test {suffix}",
        "subject_match": True,
        "editor_approved": True,
        "synthetic": False,
    }


def _test_native_payload(native_format: str = "short") -> dict[str, Any]:
    product = {
        "product_id": "social-product:tt-native-selftest",
        "native_format": native_format,
        "hook": {"text": "Trafic restricționat temporar", "source_preserving": True},
        "content_blocks": [
            {"text": "Intervalul verificat este 08:00–18:00.", "source_atom_id": "atom:1"},
        ],
        "cross_post_policy": "NATIVE_PRODUCT_ONLY",
        "verbatim_cross_platform_reuse_allowed": False,
        "analytics_used": False,
    }
    product["product_fingerprint_sha256"] = _digest(product)
    asset = _test_asset("video" if native_format == "short" else "photograph")
    binding = {
        "status": "VISUAL_READY",
        "selected_assets": [asset],
        "selected_asset_ids": [asset["asset_id"]],
        "synthetic_media_used": False,
        "provenance_complete": True,
        "reuse_rights_complete": True,
    }
    binding["binding_fingerprint_sha256"] = _digest(binding)
    return {
        "instance_id": NATIVE_INSTANCE_ID,
        "channel_id": NATIVE_CHANNEL_ID,
        "platform": "tiktok",
        "story_id": "story:tt-selftest",
        "publication_id": "publication:tt-selftest",
        "dedupe_key": "dedupe:tt-selftest",
        "product_id": product["product_id"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "native_product": product,
        "visual_binding": binding,
        "link_binding": {"status": "OPTIONAL"},
    }


def _test_publish_settings(native_format: str = "short") -> dict[str, Any]:
    value = {
        "privacy_level": "PUBLIC_TO_EVERYONE",
        "consent": {
            "granted": True,
            "source": "valceaclar_site_admin",
            "granted_at": "2026-08-16T04:00:00Z",
            "actor": "editor-test",
        },
        "music_usage_confirmed": True,
        "music_usage_confirmed_at": "2026-08-16T04:00:00Z",
        "allow_comment": True,
    }
    if native_format == "short":
        value.update({"allow_duet": False, "allow_stitch": False, "video_cover_timestamp_ms": 0})
    return value


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
    assert plan["id"] == "tt-test" and plan["privacy_level"] == "PUBLIC_TO_EVERYONE"
    bad = json.loads(json.dumps(sample))
    bad["platforms"]["tiktok"]["consent"]["granted"] = False
    try:
        validate_item(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("TikTok item without consent was not rejected")

    native = validate_native_payload(_test_native_payload("short"))
    settings = validate_publish_settings(_test_publish_settings("short"), native_format="short")
    assert native["native_format"] == "short" and native["media"]["kind"] == "video"
    assert settings["music_usage_confirmed"] is True
    print("VÂLCEA CLAR TikTok adapter self-test: PASS (legacy photo + native short/video)")
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
        os.getenv("VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED", "").strip().lower()
        in {"1", "true", "yes"}
    )
    if not token and (plan or state["pending"]):
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

    if token and state["pending"] and refresh_pending(state, token):
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
    if not public_approved:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "BLOCKED_TIKTOK_APP_AUDIT",
                    "required_repository_variable": "VALCEA_TIKTOK_PUBLIC_POSTING_APPROVED=true",
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
            write_json(STATE, state)
            status = fetch_status(token, entry["publish_id"])
            entry.update(
                {
                    "status": str(status.get("status", "")).upper(),
                    "last_status_at": utc_now(),
                    "status_payload": status,
                }
            )
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
            state["last_attempt"] = {
                "at": utc_now(),
                "status": entry["status"].lower(),
                "item_id": item["id"],
            }
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
