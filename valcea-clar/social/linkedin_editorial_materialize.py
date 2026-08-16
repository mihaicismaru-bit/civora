#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR LinkedIn editorial v1 into canonical outbox/state.

Outbox-only: no LinkedIn network access is claimed or used.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import linkedin_editorial_v1 as editorial

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "linkedin_outbox.json"
STATE = VC / "social" / "linkedin_state.json"


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
        "id": f"linkedin-story-{story_id}",
        "story_id": story_id,
        "publication_mode": "durable_outbox_only",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "linkedin_direct_access_not_configured",
        "generation_mode": "linkedin_editorial_v1",
        "edition_gate": False,
    }
    if product.get("status") == "HOLD":
        return {
            **common,
            "status": "hold",
            "native_format": "text",
            "format_family": "linkedin_hold",
            "hold_reason": product.get("reason"),
        }
    return {
        **common,
        "status": "outbox_ready",
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "hook_family": product["hook_family"],
        "hook": product["hook"],
        "body": product["body"],
        "professional_context": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
    }


def build() -> dict[str, Any]:
    preview = editorial.build()
    products = [canonical_item(product) for product in preview.get("products", [])]
    outbox = load(OUTBOX, {
        "schema_version": "1.0",
        "platform": "linkedin",
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
    outbox["platform"] = "linkedin"
    outbox["publication_model"] = "continuous_story_first"
    outbox["editorial_product_version"] = "linkedin-editorial-v1.0"
    outbox["edition_recaps_are_publication_gates"] = False
    outbox["items"] = list(existing.values())
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "linkedin",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state["schema_version"] = "1.1"
    state["platform"] = "linkedin"
    state["execution_owner"] = "civora_site_engine"
    state["publication_model"] = "continuous_story_first"
    state["editorial_product_version"] = "linkedin-editorial-v1.0"
    state["direct_publication_enabled"] = False
    state["direct_publication_blocker"] = "linkedin_direct_access_not_configured"
    state.setdefault("published", {})
    state.setdefault("failures", {})
    write(STATE, state)

    return {
        "status": "PASS",
        "platform": "linkedin",
        "editorial_product_version": "linkedin-editorial-v1.0",
        "products": len(products),
        "ready": sum(1 for item in products if item.get("status") == "outbox_ready"),
        "held": sum(1 for item in products if item.get("status") == "hold"),
        "direct_publication_enabled": False,
    }


def self_test() -> int:
    item = canonical_item({
        "story_id": "x",
        "status": "READY",
        "native_format": "text",
        "format_family": "document_explainer",
        "hook_family": "public_money",
        "hook": "10 mil. lei — miza locală",
        "body": "Context documentat.",
        "canonical_url": "https://valceaclar.ro/stiri/x/",
        "product_fingerprint_sha256": "a" * 64,
    })
    assert item["status"] == "outbox_ready"
    assert item["direct_publication_enabled"] is False
    assert item["generation_mode"] == "linkedin_editorial_v1"
    held = canonical_item({"story_id":"y","status":"HOLD","reason":"thin","canonical_url":"https://valceaclar.ro/stiri/y/"})
    assert held["status"] == "hold" and held["hold_reason"] == "thin"
    print("VÂLCEA CLAR LinkedIn editorial materializer self-test: PASS")
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
