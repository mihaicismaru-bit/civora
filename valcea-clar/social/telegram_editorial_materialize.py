#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR Telegram editorial v1 into canonical outbox/state.

Outbox-only: this module performs no Telegram network calls and claims no direct
publishing access. It replaces the generic channel-update product with the
high-signal Telegram editorial product proven in preview CI.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import telegram_editorial_v1 as editorial

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "telegram_outbox.json"
STATE = VC / "social" / "telegram_state.json"


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
    common = {
        "id": f"telegram-story-{story_id}",
        "story_id": story_id,
        "publication_mode": "durable_outbox_only",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "high_signal": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "telegram_direct_access_not_configured",
        "generation_mode": "telegram_editorial_v1",
        "edition_gate": False,
    }
    if product.get("status") == "HOLD":
        return {
            **common,
            "status": "hold",
            "native_format": "text",
            "format_family": "telegram_hold",
            "hold_reason": product.get("reason"),
        }
    return {
        **common,
        "status": "outbox_ready",
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "message": product["message"],
        "max_message_chars": product["max_message_chars"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
    }


def build() -> dict[str, Any]:
    preview = editorial.build()
    products = [canonical_item(product) for product in preview.get("products", [])]
    outbox = load(OUTBOX, {
        "schema_version": "1.0",
        "platform": "telegram",
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
    outbox["schema_version"] = "1.1"
    outbox["platform"] = "telegram"
    outbox["publication_model"] = "continuous_story_first"
    outbox["editorial_product_version"] = "telegram-editorial-v1.0"
    outbox["edition_recaps_are_publication_gates"] = False
    outbox["items"] = list(existing.values())
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "telegram",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state["schema_version"] = "1.1"
    state["platform"] = "telegram"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["editorial_product_version"] = "telegram-editorial-v1.0"
    state["direct_publication_enabled"] = False
    state["direct_publication_blocker"] = "telegram_direct_access_not_configured"
    state.setdefault("published", {})
    state.setdefault("failures", {})
    write(STATE, state)

    return {
        "status": "PASS",
        "platform": "telegram",
        "editorial_product_version": "telegram-editorial-v1.0",
        "products": len(products),
        "ready": sum(1 for item in products if item.get("status") == "outbox_ready"),
        "held": sum(1 for item in products if item.get("status") == "hold"),
        "direct_publication_enabled": False,
    }


def self_test() -> int:
    ready = canonical_item({
        "story_id": "x",
        "status": "READY",
        "native_format": "text",
        "format_family": "public_interest_update",
        "message": "44,37 mil. lei pentru un proiect local.\n\n• Context verificat.",
        "canonical_url": "https://valceaclar.ro/stiri/x/",
        "max_message_chars": 1050,
        "product_fingerprint_sha256": "a" * 64,
    })
    assert ready["status"] == "outbox_ready"
    assert ready["direct_publication_enabled"] is False
    assert ready["generation_mode"] == "telegram_editorial_v1"
    held = canonical_item({
        "story_id": "y",
        "status": "HOLD",
        "reason": "thin",
        "canonical_url": "https://valceaclar.ro/stiri/y/",
    })
    assert held["status"] == "hold" and held["hold_reason"] == "thin"
    print("VÂLCEA CLAR Telegram editorial materializer self-test: PASS")
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
