#!/usr/bin/env python3
"""One-shot premium Instagram republish for the verified CET Govora fact-check.

The old legacy single-photo media is preserved in replacement metadata because
Instagram Graph API does not expose a supported endpoint for deleting published
Instagram media. The new carousel is published first; state changes only after
Meta returns a new media id.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import instagram_editorial_publish as pub

STORY_ID = "cet-govora-cine-a-decis-oprirea-20260821"
STATE_KEY = f"story-{STORY_ID}"
REPO_RAW_BASE = "https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/"


def load_story() -> dict[str, Any]:
    facts = pub.load(pub.FACTS, {"facts": []})
    story = next((row for row in facts.get("facts", []) if str(row.get("id")) == STORY_ID), None)
    if not isinstance(story, dict):
        raise RuntimeError(f"verified story missing: {STORY_ID}")
    return story


def existing_premium_publication() -> dict[str, Any] | None:
    """Return the durable premium CET publication if it already exists.

    This is the idempotency barrier for retries and overlapping workflow
    triggers. Once a premium carousel is recorded, no retry may create a second
    Instagram post for the same story.
    """
    state = pub.load(pub.STATE, {"schema_version": "1.0", "published": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    row = published.get(STATE_KEY) if isinstance(published.get(STATE_KEY), dict) else None
    if not row:
        return None
    media_id = str(row.get("instagram_media_id") or "").strip()
    if (
        media_id
        and row.get("template_id") == "investigation_card"
        and row.get("native_format") == "carousel"
        and row.get("hook") == "31 AUGUST 2026"
    ):
        return row
    return None


def build_product() -> dict[str, Any]:
    story = load_story()
    visuals = pub.load(pub.VISUALS, {"stories": {}})
    visual = pub.ig.base.visual_for(STORY_ID, visuals)
    if not isinstance(visual, dict):
        raise RuntimeError(f"approved Instagram visual missing: {STORY_ID}")
    ok, reason = pub.ig.base.approved_for_instagram(story, visual)
    if not ok:
        raise RuntimeError(f"Instagram editorial gate rejected CET story: {reason}")
    product = pub.render_product(story, visual, pub.load(pub.SYSTEM))
    if product.get("status") != "READY":
        raise RuntimeError(f"premium CET product not ready: {product}")
    if product.get("template_id") != "investigation_card":
        raise RuntimeError(f"wrong premium template: {product.get('template_id')}")
    if product.get("native_format") != "carousel":
        raise RuntimeError(f"wrong Instagram format: {product.get('native_format')}")
    if product.get("hook") != "31 AUGUST 2026":
        raise RuntimeError(f"wrong CET hook: {product.get('hook')}")
    if len(product.get("assets") or []) != 6:
        raise RuntimeError(f"CET premium carousel must contain 6 assets, got {len(product.get('assets') or [])}")
    # Use immutable public repository paths for this one-shot replacement. The
    # bytes are committed to main before the publish phase starts.
    for asset in product["assets"]:
        asset["public_url"] = REPO_RAW_BASE + str(asset["rendered_path"])
    return product


def persist_replacement(product: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    state = pub.load(pub.STATE, {"schema_version": "1.0", "published": {}, "failures": {}})
    published = state.setdefault("published", {})
    previous = published.get(STATE_KEY) if isinstance(published.get(STATE_KEY), dict) else {}
    old_media_id = str(previous.get("instagram_media_id") or "").strip() or None
    new_media_id = str(result.get("instagram_media_id") or "").strip()
    if not new_media_id:
        raise RuntimeError("Meta returned no new Instagram media id")
    if old_media_id and new_media_id == old_media_id:
        raise RuntimeError("replacement media id unexpectedly equals legacy media id")

    published[STATE_KEY] = {
        **result,
        "canonical_url": product["canonical_url"],
        "template_id": product["template_id"],
        "hook": product["hook"],
        "assets": [
            {
                "kind": asset["kind"],
                "sha256": asset["sha256"],
                "asset_fingerprint_sha256": asset["asset_fingerprint_sha256"],
                "public_url": asset["public_url"],
            }
            for asset in product["assets"]
        ],
        "replaces": [old_media_id] if old_media_id else [],
        "replacement_reason": "premium_canonical_repackage",
        "replacement_cleanup": {
            old_media_id: {
                "status": "manual_delete_required",
                "reason": "instagram_graph_api_has_no_supported_delete_for_published_media",
            }
        } if old_media_id else {},
        "previous_publication_product": previous.get("publication_product") or "legacy_single_photo",
        "previous_native_format": previous.get("native_format") or "single_photo",
        "previous_published_at": previous.get("published_at"),
    }
    state.setdefault("failures", {}).pop(STATE_KEY, None)
    state.setdefault("pending_public_media", {}).pop(STATE_KEY, None)
    state["last_attempt"] = {
        "at": pub.utc_now(),
        "status": "premium_republished",
        "item_id": STATE_KEY,
        "old_remote_id": old_media_id,
        "new_remote_id": new_media_id,
        "cleanup_status": "manual_delete_required" if old_media_id else "not_needed",
    }
    pub.write(pub.STATE, state)
    return state["last_attempt"]


def apply(product: dict[str, Any]) -> dict[str, Any]:
    existing = existing_premium_publication()
    if existing:
        return {
            "status": "ALREADY_PREMIUM_REPUBLISHED",
            "instagram_media_id": existing["instagram_media_id"],
            "template_id": existing["template_id"],
            "native_format": existing["native_format"],
            "hook": existing["hook"],
        }
    if os.getenv(pub.LIVE_ENABLE_ENV, "").strip().lower() != "true":
        raise RuntimeError(f"{pub.LIVE_ENABLE_ENV}=true required")
    account_id = os.getenv("VALCEA_IG_ACCOUNT_ID", "").strip()
    token = os.getenv("VALCEA_IG_ACCESS_TOKEN", "").strip()
    if not account_id or not token:
        raise RuntimeError("Instagram account credentials missing")
    version = os.getenv("VALCEA_IG_GRAPH_VERSION", pub.DEFAULT_GRAPH_VERSION).strip() or pub.DEFAULT_GRAPH_VERSION
    host = os.getenv("VALCEA_IG_GRAPH_HOST", pub.DEFAULT_GRAPH_HOST).strip() or pub.DEFAULT_GRAPH_HOST
    result = pub.publish_product(
        product,
        account_id=account_id,
        token=token,
        version=version,
        host=host,
    )
    attempt = persist_replacement(product, result)
    return {"status": "PREMIUM_REPUBLISHED", "result": result, "attempt": attempt}


def self_test() -> int:
    product = build_product()
    assert product["template_id"] == "investigation_card"
    assert product["native_format"] == "carousel"
    assert product["hook"] == "31 AUGUST 2026"
    assert len(product["assets"]) == 6
    assert all(str(a["public_url"]).startswith(REPO_RAW_BASE) for a in product["assets"])
    print("VÂLCEA CLAR CET Instagram premium republish self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    product = build_product()
    if not args.apply:
        print(json.dumps({
            "status": "PREPARED",
            "story_id": STORY_ID,
            "template_id": product["template_id"],
            "native_format": product["native_format"],
            "hook": product["hook"],
            "asset_count": len(product["assets"]),
            "assets": [a["rendered_path"] for a in product["assets"]],
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(apply(product), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
