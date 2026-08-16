#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR Threads editorial v1 into canonical outbox/state.

The editorial product is platform-native and may be consumed by the verified
Threads direct adapter. When direct publishing is enabled for the first time,
the current durable story-publication event is captured as an activation
baseline so historical outbox items can never be replayed as new posts.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import threads_editorial_v1 as editorial
from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "threads_outbox.json"
STATE = VC / "social" / "threads_state.json"
EVENT = VC / "site" / "story_publication_event.json"


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def canonical_item(product: dict[str, Any]) -> dict[str, Any]:
    story_id = str(product["story_id"])
    identity = product_identity("threads")
    common = {
        "id": f"threads-story-{story_id}",
        "story_id": story_id,
        "publication_mode": "native_api_fail_closed",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "conversation_native": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": True,
        "direct_publication_blocker": None,
        "generation_mode": "threads_editorial_v1",
        "identity": identity,
        "edition_gate": False,
    }
    if product.get("status") == "HOLD":
        return {
            **common,
            "status": "hold",
            "native_format": "text",
            "format_family": "threads_hold",
            "hold_reason": product.get("reason"),
        }
    return {
        **common,
        "status": "outbox_ready",
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "hook_family": product["hook_family"],
        "posts": product["posts"],
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "max_internal_chars_per_post": product["max_internal_chars_per_post"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
    }


def build() -> dict[str, Any]:
    preview = editorial.build()
    products = [canonical_item(product) for product in preview.get("products", [])]
    outbox = load(OUTBOX, {
        "schema_version": "1.0",
        "platform": "threads",
        "publication_model": "continuous_story_first",
        "items": [],
    })
    existing = {
        str(item.get("id")): item
        for item in outbox.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    outbox["schema_version"] = "1.2"
    outbox["platform"] = "threads"
    outbox["publication_model"] = "continuous_story_first"
    outbox["editorial_product_version"] = "threads-editorial-v1.0"
    outbox["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    outbox["edition_recaps_are_publication_gates"] = False
    outbox["direct_publication_enabled"] = True
    outbox["items"] = list(existing.values())
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "threads",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    was_direct = state.get("direct_publication_enabled") is True
    event = load(EVENT, {})
    event_fp = str(event.get("fingerprint") or "").strip()
    state["schema_version"] = "1.2"
    state["platform"] = "threads"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["editorial_product_version"] = "threads-editorial-v1.0"
    state["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    state["identity_channel_id"] = "valcea-threads"
    state["direct_publication_enabled"] = True
    state["direct_publication_blocker"] = None
    state.setdefault("published", {})
    state.setdefault("failures", {})
    if not was_direct and event_fp:
        state["direct_activation_baseline_event_fingerprint"] = event_fp
        state["direct_activation_baseline_source"] = "story_publication_event_at_direct_enable"
    write(STATE, state)

    return {
        "status": "PASS",
        "platform": "threads",
        "editorial_product_version": "threads-editorial-v1.0",
        "products": len(products),
        "ready": sum(1 for item in products if item.get("status") == "outbox_ready"),
        "held": sum(1 for item in products if item.get("status") == "hold"),
        "direct_publication_enabled": True,
        "activation_baseline_present": bool(state.get("direct_activation_baseline_event_fingerprint")),
    }


def self_test() -> int:
    ready = {
        "story_id": "x",
        "status": "READY",
        "native_format": "thread",
        "format_family": "explanatory_thread",
        "hook_family": "short_explainer",
        "posts": ["Un fapt.", "Context."],
        "canonical_url": "https://valceaclar.ro/stiri/x/",
        "max_internal_chars_per_post": 470,
        "product_fingerprint_sha256": "a" * 64,
    }
    item = canonical_item(ready)
    assert item["status"] == "outbox_ready"
    assert item["direct_publication_enabled"] is True
    assert item["publication_mode"] == "native_api_fail_closed"
    assert item["generation_mode"] == "threads_editorial_v1"
    assert item["identity"]["channel_id"] == "valcea-threads"
    assert item["identity"]["profile_source"] == "valcea-clar/social/profile_identity_system.json"
    held = canonical_item({
        "story_id": "y",
        "status": "HOLD",
        "reason": "thin",
        "canonical_url": "https://valceaclar.ro/stiri/y/",
    })
    assert held["status"] == "hold" and held["hold_reason"] == "thin"
    assert held["direct_publication_enabled"] is True
    assert held["identity"]["channel_id"] == "valcea-threads"
    print("VÂLCEA CLAR Threads editorial materializer self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
