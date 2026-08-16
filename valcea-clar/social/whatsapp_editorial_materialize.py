#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR WhatsApp editorial v1.1 into canonical outbox/state.

Outbox-only. WhatsApp has an executable interruption budget: at most one current
READY product is selected per materialization cycle, ranked by editorial
priority. Other high-value candidates remain inspectable as HOLD_FREQUENCY. No
recipient set or direct WhatsApp access is inferred or used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import whatsapp_editorial_v1 as editorial
from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "whatsapp_outbox.json"
STATE = VC / "social" / "whatsapp_state.json"
INTERRUPTION_BUDGET_PER_CYCLE = 1


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


def ranked_ready(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = [product for product in products if product.get("status") == "READY"]
    return sorted(
        ready,
        key=lambda product: (
            -int(product.get("priority") or 0),
            str(product.get("story_id") or ""),
        ),
    )


def canonical_item(
    product: dict[str, Any],
    *,
    selected: bool = False,
    rank: int | None = None,
) -> dict[str, Any]:
    story_id = str(product["story_id"])
    common = {
        "id": f"whatsapp-story-{story_id}",
        "story_id": story_id,
        "publication_mode": "durable_outbox_only",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "low_frequency": True,
        "interruption_budget_per_cycle": INTERRUPTION_BUDGET_PER_CYCLE,
        "recipient_scope_required_before_dispatch": True,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "hashtags_default": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "whatsapp_verified_access_and_recipient_scope_not_configured",
        "generation_mode": "whatsapp_editorial_v1_1",
        "identity": product_identity("whatsapp"),
        "edition_gate": False,
        "selected_for_cycle": selected,
        "selection_rank": rank,
    }
    if product.get("status") == "HOLD":
        return {
            **common,
            "status": "hold",
            "native_format": "text",
            "format_family": "whatsapp_hold",
            "hold_reason": product.get("reason"),
        }
    payload = {
        **common,
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "distribution_class": product["distribution_class"],
        "priority": product["priority"],
        "message": product["message"],
        "max_message_chars": product["max_message_chars"],
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
    }
    if selected:
        return {
            **payload,
            "status": "outbox_ready",
            "hold_reason": None,
        }
    return {
        **payload,
        "status": "hold_frequency",
        "hold_reason": "whatsapp_interruption_budget_lower_priority_same_cycle",
    }


def demote_previous_ready(item: dict[str, Any]) -> dict[str, Any]:
    if item.get("status") != "outbox_ready":
        return item
    updated = dict(item)
    updated["status"] = "hold_frequency"
    updated["hold_reason"] = "whatsapp_not_selected_in_current_cycle"
    updated["selected_for_cycle"] = False
    updated["selection_rank"] = None
    return updated


def build() -> dict[str, Any]:
    preview = editorial.build()
    source_products = [p for p in preview.get("products", []) if isinstance(p, dict)]
    ranked = ranked_ready(source_products)
    selected_ids = {
        str(product["story_id"])
        for product in ranked[:INTERRUPTION_BUDGET_PER_CYCLE]
    }
    rank_by_story = {
        str(product["story_id"]): index
        for index, product in enumerate(ranked, start=1)
    }
    products = [
        canonical_item(
            product,
            selected=str(product.get("story_id")) in selected_ids,
            rank=rank_by_story.get(str(product.get("story_id"))),
        )
        for product in source_products
    ]

    outbox = load(OUTBOX, {
        "schema_version": "1.0",
        "platform": "whatsapp",
        "publication_model": "continuous_story_first",
        "items": [],
    })
    existing = {
        str(item.get("id")): demote_previous_ready(item)
        for item in outbox.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    outbox["schema_version"] = "1.2"
    outbox["platform"] = "whatsapp"
    outbox["publication_model"] = "continuous_story_first"
    outbox["editorial_product_version"] = "whatsapp-editorial-v1.1"
    outbox["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    outbox["edition_recaps_are_publication_gates"] = False
    outbox["interruption_budget_per_cycle"] = INTERRUPTION_BUDGET_PER_CYCLE
    outbox["selection_policy"] = "highest_editorial_priority_then_story_id"
    outbox["active_selected_story_ids"] = sorted(selected_ids)
    outbox["items"] = list(existing.values())
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "whatsapp",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state["schema_version"] = "1.2"
    state["platform"] = "whatsapp"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["editorial_product_version"] = "whatsapp-editorial-v1.1"
    state["identity_source"] = "valcea-clar/social/native_platform_identity_system.json"
    state["direct_publication_enabled"] = False
    state["direct_publication_blocker"] = "whatsapp_verified_access_and_recipient_scope_not_configured"
    state["interruption_budget_per_cycle"] = INTERRUPTION_BUDGET_PER_CYCLE
    state["selection_policy"] = "highest_editorial_priority_then_story_id"
    state["active_selected_story_ids"] = sorted(selected_ids)
    state.setdefault("published", {})
    state.setdefault("failures", {})
    write(STATE, state)

    return {
        "status": "PASS",
        "platform": "whatsapp",
        "editorial_product_version": "whatsapp-editorial-v1.1",
        "products": len(products),
        "ready": sum(1 for item in products if item.get("status") == "outbox_ready"),
        "held_frequency": sum(1 for item in products if item.get("status") == "hold_frequency"),
        "held": sum(1 for item in products if item.get("status") == "hold"),
        "selected_story_ids": sorted(selected_ids),
        "direct_publication_enabled": False,
    }


def self_test() -> int:
    high = {
        "story_id": "high",
        "status": "READY",
        "native_format": "text",
        "format_family": "direct_high_trust_update",
        "distribution_class": "essential_public_interest",
        "priority": 90,
        "message": "Un proiect public important.\n\nDetalii și surse: https://valceaclar.ro/stiri/high/",
        "canonical_url": "https://valceaclar.ro/stiri/high/",
        "max_message_chars": 700,
        "product_fingerprint_sha256": "a" * 64,
    }
    lower = {
        **high,
        "story_id": "lower",
        "priority": 78,
        "canonical_url": "https://valceaclar.ro/stiri/lower/",
        "product_fingerprint_sha256": "b" * 64,
    }
    ranked = ranked_ready([lower, high])
    assert [p["story_id"] for p in ranked] == ["high", "lower"]
    selected = canonical_item(high, selected=True, rank=1)
    held_frequency = canonical_item(lower, selected=False, rank=2)
    assert selected["status"] == "outbox_ready"
    assert selected["recipient_scope_required_before_dispatch"] is True
    assert selected["direct_publication_enabled"] is False
    assert selected["generation_mode"] == "whatsapp_editorial_v1_1"
    assert selected["identity"]["channel_id"] == "valcea-whatsapp"
    assert selected["interruption_budget_per_cycle"] == 1
    assert held_frequency["status"] == "hold_frequency"
    assert held_frequency["hold_reason"] == "whatsapp_interruption_budget_lower_priority_same_cycle"
    assert demote_previous_ready(selected)["status"] == "hold_frequency"
    held = canonical_item({
        "story_id": "y",
        "status": "HOLD",
        "reason": "not essential",
        "canonical_url": "https://valceaclar.ro/stiri/y/",
    })
    assert held["status"] == "hold"
    assert held["identity"]["product_role"] == "essential_local_update"
    print("VÂLCEA CLAR WhatsApp editorial materializer v1.1 self-test: PASS")
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
