#!/usr/bin/env python3
"""Fail-closed Instagram publisher executed only by the CIVORA site engine.

The legacy VÂLCEA CLAR outbox remains supported. The adapter also exposes a
credential-injected native payload entry point for LOCAL NEWS OS durable dispatch.
Supported direct formats in this revision are single-photo and photo carousel.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import time
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
    compact_caption,
    direct_photo_url,
    load_json,
    photo_metadata,
    platform_config,
    platform_ready,
    schedule_ready,
    utc_now,
    utf16_units,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "valcea-clar" / "social" / "instagram_state.json"
DEFAULT_GRAPH_VERSION = "v26.0"
DEFAULT_GRAPH_HOST = "graph.facebook.com"
NATIVE_ADAPTER_NAME = "valcea-clar/social/instagram_publish.py"
NATIVE_INSTANCE_ID = "valcea"
NATIVE_CHANNEL_ID = "valcea-instagram"
MAX_CAROUSEL_ASSETS = 10
SUPPORTED_NATIVE_FORMATS = {"single_photo", "carousel"}
FORBIDDEN_PAYLOAD_KEY_PARTS = {
    "access_token",
    "client_secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
}


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
        headers={"User-Agent": "ValceaClar-Instagram/1.1", **(headers or {})},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Instagram Graph HTTP {exc.code}: {detail[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Instagram Graph transport error: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Instagram Graph returned unexpected payload: {payload!r}")
    if isinstance(payload.get("error"), dict):
        raise RuntimeError(
            "Instagram Graph error: " + json.dumps(payload["error"], ensure_ascii=False)
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
    query = urllib.parse.urlencode({"access_token": token, **(params or {})})
    return request_json(f"{graph_url(host, version, path)}?{query}")


def graph_post(
    host: str,
    version: str,
    path: str,
    token: str,
    fields: dict[str, str],
) -> dict[str, Any]:
    data = urllib.parse.urlencode({**fields, "access_token": token}).encode("utf-8")
    return request_json(
        graph_url(host, version, path),
        method="POST",
        data=data,
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
            "User-Agent": "ValceaClar-Instagram-Media-Preflight/1.1",
            "Range": "bytes=0-63",
            "Accept": "image/jpeg,image/*;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            head = response.read(64)
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise RuntimeError(f"Instagram image is not publicly reachable: {url}: {exc}") from exc
    if "jpeg" not in content_type and not head.startswith(b"\xff\xd8\xff"):
        raise RuntimeError(
            f"Instagram adapter requires JPEG; got {content_type or 'unknown'} from {url}"
        )


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


def _native_caption(product: dict[str, Any]) -> str:
    hook = product.get("hook") if isinstance(product.get("hook"), dict) else {}
    parts: list[str] = []
    hook_text = str(hook.get("text", "")).strip()
    if hook_text:
        parts.append(hook_text)
    blocks = product.get("content_blocks")
    if isinstance(blocks, list):
        for raw in blocks:
            if not isinstance(raw, dict):
                continue
            text = str(raw.get("text", "")).strip()
            if text:
                parts.append(text)
    caption = "\n\n".join(parts).strip()
    if not caption:
        raise ValueError("Instagram native payload has no source-preserving caption text")
    if utf16_units(caption) > 2200:
        raise ValueError("Instagram native caption exceeds 2200 UTF-16 units")
    return caption


def _validate_native_asset(asset: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(asset, dict):
        raise ValueError(f"Instagram native asset {index} is not a mapping")
    asset_id = str(asset.get("asset_id", "")).strip()
    if not asset_id:
        raise ValueError(f"Instagram native asset {index} has no asset_id")
    if str(asset.get("kind", "")).strip().lower() != "photograph":
        raise ValueError(f"Instagram native asset {asset_id} is not a photograph")
    if asset.get("synthetic") is not False:
        raise ValueError(f"Instagram native asset {asset_id} is synthetic or unverified")
    if asset.get("subject_match") is not True:
        raise ValueError(f"Instagram native asset {asset_id} lacks subject match")
    if asset.get("editor_approved") is not True:
        raise ValueError(f"Instagram native asset {asset_id} lacks editorial approval")
    source_type = str(asset.get("source_type", "")).strip()
    rights_basis = str(asset.get("rights_basis", "")).strip()
    credit = str(asset.get("credit", "")).strip()
    alt_text = str(asset.get("alt_text", "")).strip()
    if source_type not in ALLOWED_SOURCE_TYPES:
        raise ValueError(f"Instagram native asset {asset_id} has invalid source_type")
    if rights_basis not in ALLOWED_RIGHTS:
        raise ValueError(f"Instagram native asset {asset_id} lacks reuse rights")
    if not credit or not alt_text:
        raise ValueError(f"Instagram native asset {asset_id} lacks credit or alt text")
    if source_type not in {"staff", "public_domain"} and not str(asset.get("source_url", "")).strip():
        raise ValueError(f"Instagram native asset {asset_id} lacks provenance source_url")
    sha256 = str(asset.get("sha256", "")).strip().lower()
    if not _is_sha256(sha256):
        raise ValueError(f"Instagram native asset {asset_id} has invalid sha256")
    url = str(asset.get("direct_source_url", "") or asset.get("source_url", "")).strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"Instagram native asset {asset_id} has no public HTTPS media URL")
    return {
        "asset_id": asset_id,
        "image_url": url,
        "alt_text": alt_text,
        "credit": credit,
        "sha256": sha256,
    }


def validate_native_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate one LOCAL NEWS OS adapter payload without reading credentials."""
    if not isinstance(payload, dict):
        raise TypeError("Instagram adapter payload must be a mapping")
    if _contains_secret_field(payload):
        raise ValueError("Instagram adapter payload must not contain credential values")
    if str(payload.get("instance_id", "")).strip() != NATIVE_INSTANCE_ID:
        raise ValueError("Instagram adapter payload instance mismatch")
    if str(payload.get("channel_id", "")).strip() != NATIVE_CHANNEL_ID:
        raise ValueError("Instagram adapter payload channel mismatch")
    if str(payload.get("platform", "")).strip().lower() != "instagram":
        raise ValueError("Instagram adapter payload platform mismatch")

    publication_id = str(payload.get("publication_id", "")).strip()
    dedupe_key = str(payload.get("dedupe_key", "")).strip()
    if not publication_id or not dedupe_key:
        raise ValueError("Instagram adapter payload lacks publication identity")

    product = payload.get("native_product")
    if not isinstance(product, dict):
        raise ValueError("Instagram adapter payload has no native_product")
    if str(product.get("product_id", "")).strip() != str(payload.get("product_id", "")).strip():
        raise ValueError("Instagram native product identity mismatch")
    supplied_product_fp = str(payload.get("product_fingerprint_sha256", "")).strip().lower()
    if not _is_sha256(supplied_product_fp):
        raise ValueError("Instagram adapter payload has invalid product fingerprint")
    if str(product.get("product_fingerprint_sha256", "")).strip().lower() != supplied_product_fp:
        raise ValueError("Instagram native product fingerprint mismatch")
    if not _fingerprint_matches(product, "product_fingerprint_sha256"):
        raise ValueError("Instagram native product fingerprint is not authentic")
    if product.get("cross_post_policy") != "NATIVE_PRODUCT_ONLY":
        raise ValueError("Instagram adapter requires NATIVE_PRODUCT_ONLY")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        raise ValueError("Instagram adapter forbids verbatim cross-platform reuse")
    if product.get("analytics_used") is not False:
        raise ValueError("Instagram adapter forbids predictive/invented analytics")

    native_format = str(product.get("native_format", "")).strip()
    if native_format not in SUPPORTED_NATIVE_FORMATS:
        raise ValueError(f"Instagram native format is unsupported by adapter: {native_format}")
    caption = _native_caption(product)

    binding = payload.get("visual_binding")
    if not isinstance(binding, dict) or binding.get("status") != "VISUAL_READY":
        raise ValueError("Instagram native payload lacks VISUAL_READY binding")
    if binding.get("synthetic_media_used") is not False:
        raise ValueError("Instagram native payload used synthetic media")
    if binding.get("provenance_complete") is not True or binding.get("reuse_rights_complete") is not True:
        raise ValueError("Instagram native payload lacks provenance or reuse rights")
    if not _fingerprint_matches(binding, "binding_fingerprint_sha256"):
        raise ValueError("Instagram visual binding fingerprint is invalid")

    selected = binding.get("selected_assets")
    if not isinstance(selected, list):
        raise ValueError("Instagram visual binding selected_assets is invalid")
    if native_format == "single_photo" and len(selected) != 1:
        raise ValueError("Instagram single_photo requires exactly one approved asset")
    if native_format == "carousel" and not 2 <= len(selected) <= MAX_CAROUSEL_ASSETS:
        raise ValueError(
            f"Instagram carousel requires 2-{MAX_CAROUSEL_ASSETS} approved assets"
        )

    media = [_validate_native_asset(asset, index) for index, asset in enumerate(selected)]
    asset_ids = [asset["asset_id"] for asset in media]
    hashes = [asset["sha256"] for asset in media]
    if len(asset_ids) != len(set(asset_ids)) or len(hashes) != len(set(hashes)):
        raise ValueError("Instagram carousel cannot repeat the same media asset")

    return {
        "publication_id": publication_id,
        "dedupe_key": dedupe_key,
        "product_id": str(payload.get("product_id", "")).strip(),
        "native_format": native_format,
        "caption": caption,
        "media": media,
    }


def validate_item(item: dict[str, Any]) -> dict[str, Any]:
    """Validate the historical shared outbox single-photo shape."""
    item_id = str(item.get("id", "")).strip()
    if not item_id:
        raise ValueError("Instagram item has no id")
    if not platform_ready(item, "instagram"):
        raise ValueError(f"{item_id} is not ready for Instagram")
    link = canonical_link(item)
    metadata = photo_metadata(item)
    config = platform_config(item, "instagram") or {}
    explicit = str(config.get("caption") or "").strip()
    caption = compact_caption(
        explicit or str(item.get("message", "")),
        link,
        str(metadata.get("credit", "")),
        2200,
    )
    if not caption:
        raise ValueError(f"{item_id} has no Instagram caption")
    return {
        "id": item_id,
        "image_url": direct_photo_url(item, "instagram"),
        "caption": caption,
        "alt_text": str(metadata["alt_text"]).strip(),
    }


def eligible_items(
    outbox: dict[str, Any], published: dict[str, Any]
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
    *,
    graph_get_fn: Callable[..., dict[str, Any]] = graph_get,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> str:
    last = "UNKNOWN"
    for attempt in range(10):
        payload = graph_get_fn(
            host, version, container_id, token, {"fields": "status_code"}
        )
        last = str(payload.get("status_code", "") or "UNKNOWN").upper()
        if last in {"FINISHED", "PUBLISHED"}:
            return last
        if last in {"ERROR", "EXPIRED"}:
            raise RuntimeError(f"Instagram container {container_id} entered {last}")
        if attempt < 9:
            sleep_fn(2)
    raise RuntimeError(f"Instagram container {container_id} did not finish; last={last}")


def _publish_container(
    account_id: str,
    token: str,
    version: str,
    host: str,
    container_id: str,
    *,
    graph_post_fn: Callable[..., dict[str, Any]] = graph_post,
) -> str:
    result = graph_post_fn(
        host,
        version,
        f"{account_id}/media_publish",
        token,
        {"creation_id": container_id},
    )
    media_id = str(result.get("id", "")).strip()
    if not media_id:
        raise RuntimeError(f"Instagram returned no media id: {result}")
    return media_id


def publish_native_payload(
    payload: dict[str, Any],
    *,
    account_id: str,
    token: str,
    version: str = DEFAULT_GRAPH_VERSION,
    host: str = DEFAULT_GRAPH_HOST,
    graph_post_fn: Callable[..., dict[str, Any]] = graph_post,
    graph_get_fn: Callable[..., dict[str, Any]] = graph_get,
    preflight_fn: Callable[[str], None] = remote_jpeg_preflight,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Publish a validated LOCAL NEWS OS single photo or photo carousel natively."""
    account_id = str(account_id).strip()
    token = str(token).strip()
    if not account_id or not token:
        raise ValueError("Instagram native publish requires runtime account id and token")
    item = validate_native_payload(payload)

    for asset in item["media"]:
        preflight_fn(asset["image_url"])

    child_ids: list[str] = []
    if item["native_format"] == "carousel":
        for asset in item["media"]:
            child = graph_post_fn(
                host,
                version,
                f"{account_id}/media",
                token,
                {
                    "image_url": asset["image_url"],
                    "is_carousel_item": "true",
                    "alt_text": asset["alt_text"],
                },
            )
            child_id = str(child.get("id", "")).strip()
            if not child_id:
                raise RuntimeError(f"Instagram returned no carousel child id: {child}")
            wait_for_container(
                host,
                version,
                child_id,
                token,
                graph_get_fn=graph_get_fn,
                sleep_fn=sleep_fn,
            )
            child_ids.append(child_id)

        container = graph_post_fn(
            host,
            version,
            f"{account_id}/media",
            token,
            {
                "media_type": "CAROUSEL",
                "children": ",".join(child_ids),
                "caption": item["caption"],
            },
        )
    else:
        asset = item["media"][0]
        container = graph_post_fn(
            host,
            version,
            f"{account_id}/media",
            token,
            {
                "image_url": asset["image_url"],
                "caption": item["caption"],
                "alt_text": asset["alt_text"],
            },
        )

    container_id = str(container.get("id", "")).strip()
    if not container_id:
        raise RuntimeError(f"Instagram returned no container id: {container}")
    container_status = wait_for_container(
        host,
        version,
        container_id,
        token,
        graph_get_fn=graph_get_fn,
        sleep_fn=sleep_fn,
    )
    media_id = _publish_container(
        account_id,
        token,
        version,
        host,
        container_id,
        graph_post_fn=graph_post_fn,
    )
    return {
        "success": True,
        "remote_publication_id": media_id,
        "adapter": NATIVE_ADAPTER_NAME,
        "publication_id": item["publication_id"],
        "instagram_media_id": media_id,
        "container_id": container_id,
        "container_status": container_status,
        "child_container_ids": child_ids,
        "native_format": item["native_format"],
        "published_at": utc_now(),
    }


def publish_one(
    item: dict[str, Any],
    *,
    account_id: str,
    token: str,
    version: str,
    host: str,
) -> dict[str, Any]:
    """Publish one legacy single-photo outbox item without changing old state semantics."""
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
        raise RuntimeError(f"Instagram returned no container id: {container}")
    container_status = wait_for_container(host, version, container_id, token)
    media_id = _publish_container(account_id, token, version, host, container_id)
    return {
        "instagram_media_id": media_id,
        "container_id": container_id,
        "container_status": container_status,
        "published_at": utc_now(),
        "image_url": item["image_url"],
    }


def _test_asset(asset_id: str, suffix: str) -> dict[str, Any]:
    return {
        "asset_id": asset_id,
        "kind": "photograph",
        "sha256": hashlib.sha256(asset_id.encode("utf-8")).hexdigest(),
        "source_type": "staff",
        "source_url": None,
        "direct_source_url": f"https://valceaclar.ro/media/social/{suffix}.jpg",
        "credit": "Vâlcea Clar",
        "rights_basis": "owned",
        "license_url": None,
        "rights_note": None,
        "alt_text": f"Imagine reală {suffix}",
        "subject_match": True,
        "editor_approved": True,
        "synthetic": False,
    }


def _test_native_payload(native_format: str = "carousel") -> dict[str, Any]:
    product = {
        "product_id": "social-product:ig-native-selftest",
        "native_format": native_format,
        "hook": {"text": "Titlu verificat", "source_preserving": True},
        "content_blocks": [
            {"text": "Context verificat.", "source_atom_id": "atom:1"},
        ],
        "cross_post_policy": "NATIVE_PRODUCT_ONLY",
        "verbatim_cross_platform_reuse_allowed": False,
        "analytics_used": False,
    }
    product["product_fingerprint_sha256"] = _digest(product)
    assets = [_test_asset("asset-a", "a")]
    if native_format == "carousel":
        assets.append(_test_asset("asset-b", "b"))
    binding = {
        "status": "VISUAL_READY",
        "selected_assets": assets,
        "selected_asset_ids": [asset["asset_id"] for asset in assets],
        "synthetic_media_used": False,
        "provenance_complete": True,
        "reuse_rights_complete": True,
    }
    binding["binding_fingerprint_sha256"] = _digest(binding)
    return {
        "instance_id": NATIVE_INSTANCE_ID,
        "channel_id": NATIVE_CHANNEL_ID,
        "platform": "instagram",
        "story_id": "story:ig-selftest",
        "publication_id": "publication:ig-selftest",
        "dedupe_key": "dedupe:ig-selftest",
        "product_id": product["product_id"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "native_product": product,
        "visual_binding": binding,
        "link_binding": {"status": "OPTIONAL"},
    }


def self_test() -> int:
    sample = {
        "id": "ig-test",
        "status": "ready",
        "message": "Titlu\n\nText verificat.",
        "link": "https://valceaclar.ro/",
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
        "platforms": {"instagram": {"status": "ready", "mode": "direct_publish"}},
    }
    plan = validate_item(sample)
    assert plan["id"] == "ig-test" and plan["image_url"].endswith("test.jpg")
    bad = json.loads(json.dumps(sample))
    bad["image"]["synthetic"] = True
    try:
        validate_item(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("synthetic image was not rejected")

    carousel = validate_native_payload(_test_native_payload("carousel"))
    assert carousel["native_format"] == "carousel" and len(carousel["media"]) == 2
    print("VÂLCEA CLAR Instagram adapter self-test: PASS (single_photo + native carousel)")
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
            {"id": item["id"], "image_url": item["image_url"]} for item in plan
        ],
        "blocked": blocked,
    }
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    if not plan:
        print(json.dumps({**preview, "status": "NO_ELIGIBLE_POSTS"}, ensure_ascii=False, indent=2))
        return 0

    account_id = os.getenv("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.getenv("VALCEA_IG_ACCESS_TOKEN", "").strip()
    version = os.getenv("VALCEA_IG_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    host = os.getenv("VALCEA_IG_GRAPH_HOST", DEFAULT_GRAPH_HOST).strip() or DEFAULT_GRAPH_HOST
    if not account_id or not token:
        print(
            json.dumps(
                {
                    **preview,
                    "status": "BLOCKED_MISSING_CREDENTIALS",
                    "required_runtime_values": [
                        "VALCEA_IG_ACCOUNT_ID",
                        "VALCEA_IG_ACCESS_TOKEN",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    results: list[dict[str, Any]] = []
    max_per_run = max(1, int(os.getenv("VALCEA_IG_MAX_PER_RUN", "1")))
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
            failures[item["id"]] = {"failed_at": utc_now(), "error": str(exc)}
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
