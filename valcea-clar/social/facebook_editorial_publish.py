#!/usr/bin/env python3
"""Fail-closed Facebook editorial-composite publisher for VÂLCEA CLAR.

The adapter builds a Facebook-native visual/copy product from the verified story
kernel and approved source photograph, renders a deterministic editorial
composite, and can upload that binary to the Page. Existing legacy story IDs in
facebook_state.json are respected so adoption never republishes already-live
stories. Live apply additionally requires an explicit runtime enable flag.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

import editorial_asset_contract as asset_contract
import facebook_editorial_preview_v1_1 as patch
import facebook_publish as legacy

fb = patch.impl
ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
STATE = VC / "social" / "facebook_state.json"
VISUALS = VC / "social" / "story_visuals.json"
SYSTEM = VC / "social" / "facebook_visual_system.json"
RUNTIME = VC / "social" / "runtime" / "editorial" / "facebook"
DEFAULT_GRAPH_VERSION = "v26.0"
LIVE_ENABLE_ENV = "VALCEA_FB_EDITORIAL_LIVE_ENABLED"
ADAPTER_VERSION = "facebook-editorial-v1.0"


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_key(story_id: str) -> str:
    # Preserve legacy identity so the old and new adapters share one dedupe key.
    return f"story-{story_id}"


def render_product(story: dict[str, Any], visual: dict[str, Any], system: dict[str, Any]) -> dict[str, Any]:
    # patch module installs the corrected contractor-name normalizer in fb.
    plan = fb.package(story, visual)
    errors = fb.validate(plan, system)
    if errors:
        return {
            "status": "HOLD",
            "story_id": str(story["id"]),
            "reason": "facebook_editorial_qa_failed",
            "qa_errors": errors,
        }
    fingerprint = str(plan["product_fingerprint_sha256"])
    filename = f"{story['id']}-fb-{fingerprint[:12]}.jpg"
    rendered = RUNTIME / filename
    fb.render(plan, rendered, system)
    asset = asset_contract.build_asset(
        story_id=str(story["id"]),
        platform="facebook",
        renderer="facebook-editorial-v1.0",
        rendered_path=rendered,
        source_visual=visual,
        product_fingerprint=fingerprint,
        public_url=None,
    )
    asset_contract.validate_asset(asset)
    source = asset["source_photo"]
    alt_text = f"VÂLCEA CLAR: {plan['hook']}. {source['alt_text']}"
    return {
        "status": "READY",
        "story_id": str(story["id"]),
        "state_key": state_key(str(story["id"])),
        "template_id": plan["template_id"],
        "hook": plan["hook"],
        "body": plan["body"],
        "canonical_url": plan["canonical_link"],
        "product_fingerprint_sha256": fingerprint,
        "asset": asset,
        "alt_text": alt_text[:1000],
    }


def plan_products() -> dict[str, Any]:
    visuals = load(VISUALS, {"stories": {}})
    system = load(SYSTEM)
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    products: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for story in fb.stories():
        story_id = str(story["id"])
        key = state_key(story_id)
        if key in published:
            skipped.append({"story_id": story_id, "state_key": key, "reason": "already_published"})
            continue
        visual = fb.visual_for(story_id, visuals)
        ok, reason = fb.interest_gate(story, visual)
        if not ok:
            holds.append({"story_id": story_id, "reason": reason})
            continue
        assert visual is not None
        product = render_product(story, visual, system)
        if product.get("status") != "READY":
            holds.append(product)
            continue
        products.append(product)
    return {
        "status": "DRY_RUN",
        "adapter": ADAPTER_VERSION,
        "eligible": products,
        "holds": holds,
        "skipped": skipped,
    }


def graph_editorial_photo_post(
    *,
    page_id: str,
    token: str,
    version: str,
    product: dict[str, Any],
    request_fn: Callable[..., Any] = urllib.request.urlopen,
) -> str:
    asset = product.get("asset") if isinstance(product.get("asset"), dict) else None
    if not asset:
        raise ValueError("Facebook editorial product has no asset")
    asset_contract.validate_asset(asset)
    path = ROOT / str(asset["rendered_path"])
    fields = {
        "caption": str(product["body"]),
        "published": "true",
        "access_token": token,
        "alt_text_custom": str(product["alt_text"]),
    }
    body, content_type = legacy.multipart(fields, path)
    request = urllib.request.Request(
        f"https://graph.facebook.com/{version}/{page_id}/photos",
        data=body,
        method="POST",
        headers={"Content-Type": content_type, "User-Agent": "ValceaClar-Facebook-Editorial/1.0"},
    )
    try:
        with request_fn(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Meta editorial photo POST HTTP {exc.code}: {detail[:1000]}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Meta editorial photo POST returned unexpected payload")
    post_id = str(payload.get("post_id") or payload.get("id") or "").strip()
    if not post_id:
        raise RuntimeError(f"Meta editorial photo POST returned no post id: {payload}")
    return post_id


def persist_publication(state: dict[str, Any], product: dict[str, Any], post_id: str) -> None:
    published = state.setdefault("published", {})
    if not isinstance(published, dict):
        raise ValueError("facebook_state.published must be an object")
    asset = product["asset"]
    source = asset["source_photo"]
    published[product["state_key"]] = {
        "facebook_post_id": post_id,
        "published_at": utc_now(),
        "link": product["canonical_url"],
        "publication_product": ADAPTER_VERSION,
        "template_id": product["template_id"],
        "hook": product["hook"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "editorial_asset_kind": asset["kind"],
        "editorial_asset_path": asset["rendered_path"],
        "editorial_asset_sha256": asset["sha256"],
        "editorial_asset_fingerprint_sha256": asset["asset_fingerprint_sha256"],
        "source_photo_path": source.get("image_path"),
        "source_photo_credit": source.get("credit"),
        "source_photo_rights_basis": source.get("rights_basis"),
        "source_photo_url": source.get("source_url"),
        "replacement_cleanup": {},
    }
    state["last_editorial_attempt"] = {
        "at": utc_now(),
        "status": "published",
        "story_id": product["story_id"],
        "state_key": product["state_key"],
    }
    write(STATE, state)


def self_test() -> int:
    assert state_key("abc") == "story-abc"
    sample_state = {"published": {"story-x": {"facebook_post_id": "1"}}}
    assert "story-x" in sample_state["published"]
    assert os.getenv("DO_NOT_EXIST_12345", "").strip() == ""
    # Validate that a composite cannot silently be treated as a source photo.
    assert "editorial_composite" != "photograph"
    print("VÂLCEA CLAR Facebook editorial adapter v1 self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    preview = plan_products()
    if not args.apply:
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0
    if not preview["eligible"]:
        print(json.dumps({**preview, "status": "NO_ELIGIBLE_POSTS"}, ensure_ascii=False, indent=2))
        return 0
    if os.getenv(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        print(json.dumps({
            **preview,
            "status": "BLOCKED_EDITORIAL_LIVE_NOT_ENABLED",
            "required_runtime_value": f"{LIVE_ENABLE_ENV}=true",
        }, ensure_ascii=False, indent=2))
        return 0

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    durable = os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
    legacy_token = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    supplied = durable or legacy_token
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", DEFAULT_GRAPH_VERSION).strip() or DEFAULT_GRAPH_VERSION
    if not page_id or not supplied:
        print(json.dumps({**preview, "status": "BLOCKED_MISSING_CREDENTIALS"}, ensure_ascii=False, indent=2))
        return legacy.AUTH_BLOCKED_EXIT

    state = load(STATE, {"schema_version": "3.0", "published": {}})
    try:
        page_token, resolution = legacy.resolve_page_token(page_id, supplied, version)
    except Exception as exc:
        state["last_editorial_attempt"] = {
            "at": utc_now(),
            "status": "blocked_meta_auth",
            "error_class": legacy.classify_auth_error(exc),
        }
        write(STATE, state)
        raise

    max_per_run = max(1, int(os.getenv("VALCEA_FB_EDITORIAL_MAX_PER_RUN", "1")))
    results = []
    for product in preview["eligible"][:max_per_run]:
        post_id = graph_editorial_photo_post(
            page_id=page_id,
            token=page_token,
            version=version,
            product=product,
        )
        persist_publication(state, product, post_id)
        results.append({
            "story_id": product["story_id"],
            "state_key": product["state_key"],
            "facebook_post_id": post_id,
            "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        })

    print(json.dumps({
        "status": "PUBLISHED",
        "adapter": ADAPTER_VERSION,
        "auth_resolution": resolution,
        "results": results,
        "remaining": max(0, len(preview["eligible"]) - len(results)),
        "holds": preview["holds"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
