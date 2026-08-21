#!/usr/bin/env python3
"""Replace one already-live Facebook story with its canonical premium product.

Safety contract:
- exact story id only;
- reuse the verified story + approved visual;
- render through the canonical Facebook editorial v1.1 package;
- publish the replacement first;
- delete the previous remote post only after the replacement has a remote id;
- keep both remote ids and cleanup outcome in durable state;
- never log credentials.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import facebook_editorial_publish as editorial
import facebook_publish as legacy

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
FACTS = VC / "editorial" / "facts_registry.json"
VISUALS = VC / "social" / "story_visuals.json"
SYSTEM = VC / "social" / "facebook_visual_system.json"
STATE = VC / "social" / "facebook_state.json"
LIVE_ENABLE_ENV = "VALCEA_FB_EDITORIAL_LIVE_ENABLED"


def load(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def story_by_id(story_id: str) -> dict[str, Any]:
    try:
        for row in editorial.fb.stories():
            if isinstance(row, dict) and str(row.get("id")) == story_id:
                return row
    except Exception:
        pass
    for row in load(FACTS, {"facts": []}).get("facts", []):
        if isinstance(row, dict) and str(row.get("id")) == story_id:
            return row
    raise RuntimeError(f"verified story not found: {story_id}")


def build_product(story_id: str) -> dict[str, Any]:
    story = story_by_id(story_id)
    visuals = load(VISUALS, {"stories": {}})
    visual = editorial.fb.visual_for(story_id, visuals)
    if not isinstance(visual, dict):
        raise RuntimeError(f"approved visual missing: {story_id}")
    ok, reason = editorial.fb.interest_gate(story, visual)
    if not ok:
        raise RuntimeError(f"Facebook interest/visual gate HOLD: {reason}")
    product = editorial.render_product(story, visual, load(SYSTEM))
    if product.get("status") != "READY":
        raise RuntimeError(f"premium render HOLD: {product}")
    return product


def replacement_plan(story_id: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    product = build_product(story_id)
    state = load(STATE, {"schema_version": "3.0", "published": {}})
    published = state.get("published") if isinstance(state.get("published"), dict) else {}
    key = editorial.state_key(story_id)
    previous = published.get(key)
    if not isinstance(previous, dict):
        raise RuntimeError(f"no existing Facebook publication to replace: {key}")
    old_id = str(previous.get("facebook_post_id") or "").strip()
    if not old_id:
        raise RuntimeError(f"existing Facebook publication has no remote id: {key}")
    if (
        previous.get("publication_product") == editorial.ADAPTER_VERSION
        and previous.get("product_fingerprint_sha256") == product.get("product_fingerprint_sha256")
    ):
        return product, state, old_id, {"status": "ALREADY_PREMIUM", "previous": previous}
    return product, state, old_id, {"status": "READY_TO_REPLACE", "previous": previous}


def apply(story_id: str) -> dict[str, Any]:
    product, state, old_id, plan = replacement_plan(story_id)
    if plan["status"] == "ALREADY_PREMIUM":
        return {
            "status": "ALREADY_PREMIUM",
            "story_id": story_id,
            "remote_id": old_id,
            "template_id": product.get("template_id"),
            "hook": product.get("hook"),
        }
    if os.getenv(LIVE_ENABLE_ENV, "").strip().lower() != "true":
        return {
            "status": "BLOCKED_EDITORIAL_LIVE_NOT_ENABLED",
            "story_id": story_id,
            "required_runtime_value": f"{LIVE_ENABLE_ENV}=true",
        }

    page_id = os.getenv("VALCEA_FB_PAGE_ID", "").strip()
    durable = os.getenv("VALCEA_META_PAGE_ACCESS_TOKEN", "").strip()
    legacy_token = os.getenv("VALCEA_FB_PAGE_ACCESS_TOKEN", "").strip()
    supplied = durable or legacy_token
    version = os.getenv("VALCEA_FB_GRAPH_VERSION", editorial.DEFAULT_GRAPH_VERSION).strip() or editorial.DEFAULT_GRAPH_VERSION
    if not page_id or not supplied:
        return {"status": "BLOCKED_MISSING_CREDENTIALS", "story_id": story_id}

    page_token, auth_resolution = legacy.resolve_page_token(page_id, supplied, version)

    # Transaction order is deliberate: never delete the known-good publication
    # until Meta has returned a remote id for the premium replacement.
    new_id = editorial.graph_editorial_photo_post(
        page_id=page_id,
        token=page_token,
        version=version,
        product=product,
    )
    cleanup = legacy.graph_delete(old_id, page_token, version)

    previous = dict(plan["previous"])
    editorial.persist_publication(state, product, new_id)
    current = state["published"][product["state_key"]]
    current["replaces"] = [old_id]
    current["replacement_cleanup"] = {old_id: cleanup}
    current["replacement_reason"] = "premium_canonical_repackage"
    current["previous_publication_product"] = previous.get("publication_product") or "legacy_manual_photo_post"
    current["previous_product_fingerprint_sha256"] = previous.get("product_fingerprint_sha256")
    current["previous_published_at"] = previous.get("published_at")
    state["last_editorial_attempt"] = {
        "at": editorial.utc_now(),
        "status": "premium_replaced",
        "story_id": story_id,
        "state_key": product["state_key"],
        "old_remote_id": old_id,
        "new_remote_id": new_id,
        "cleanup_status": cleanup.get("status"),
    }
    editorial.write(STATE, state)

    return {
        "status": "PREMIUM_REPUBLISHED",
        "story_id": story_id,
        "old_remote_id": old_id,
        "new_remote_id": new_id,
        "old_cleanup": cleanup,
        "template_id": product["template_id"],
        "hook": product["hook"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "editorial_asset_path": product["asset"]["rendered_path"],
        "auth_source": auth_resolution.get("source"),
    }


def self_test() -> int:
    story_id = "cet-govora-cine-a-decis-oprirea-20260821"
    product = build_product(story_id)
    assert product["template_id"] == "fb_investigation_card"
    assert product["hook"] == "Cine a decis, de fapt, oprirea CET Govora?"
    assert product["asset"]["kind"] == "editorial_composite"
    assert product["asset"]["synthetic"] is False
    assert product["asset"]["source_photo"]["kind"] == "photograph"
    assert "31 august 2026" in product["body"]
    print("VÂLCEA CLAR premium Facebook replacement self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--story-id", required=False)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.story_id:
        raise SystemExit("--story-id is required")
    if not args.apply:
        product, _state, old_id, plan = replacement_plan(args.story_id)
        print(json.dumps({
            "status": plan["status"],
            "story_id": args.story_id,
            "old_remote_id": old_id,
            "template_id": product["template_id"],
            "hook": product["hook"],
            "product_fingerprint_sha256": product["product_fingerprint_sha256"],
            "editorial_asset_path": product["asset"]["rendered_path"],
            "network_calls": False,
        }, ensure_ascii=False, indent=2))
        return 0
    print(json.dumps(apply(args.story_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
