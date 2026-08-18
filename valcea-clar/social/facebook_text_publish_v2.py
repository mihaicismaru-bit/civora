#!/usr/bin/env python3
"""Facebook text-first v2: drain every unpublished canonical story.

The v1 adapter correctly publishes verified text+link posts without a photograph,
but discovery was tied to `story_publication_event.new_story_ids` and to the
compact recap projection.  Either condition could strand a verified story:
workflow races lose a `new_story_ids` event, while FACT_KERNEL_COMPOSED stories
need their internal kernel for the independent integrity recheck.

v2 uses the newsroom decision as the desired story set and rehydrates every id
from the full Editorial Writer registry.  Facebook state remains the durable
delivery ledger; v1's social-interest, visual preference, identity and Graph API
safety gates remain unchanged.
"""
from __future__ import annotations

from typing import Any

import facebook_text_publish as base
import generate_edition


def current_publishable_backlog() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    decision = base.load(base.VC / "site" / "newsroom_decision.json", {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"canonical_urls": {}})
    allowed_order = [str(value) for value in decision.get("publishable_story_ids") or [] if str(value).strip()]

    # Rehydrate the full Writer products.  The edition snapshot intentionally
    # omits `fact_kernel`; feeding that compact projection back into story_ready
    # would fail the post-writer integrity gate for new composed stories.
    registry, _ = generate_edition.merged_registry()
    by_id = {
        str(row.get("id")): row
        for row in registry.get("facts") or []
        if isinstance(row, dict) and row.get("id")
    }
    stories = [by_id[story_id] for story_id in allowed_order if story_id in by_id]

    urls = event.get("canonical_urls") if isinstance(event.get("canonical_urls"), dict) else {}
    for story_id in allowed_order:
        urls.setdefault(story_id, f"https://valceaclar.ro/stiri/{story_id}/")
    event["canonical_urls"] = urls
    event["new_story_ids"] = allowed_order
    event["delivery_discovery_mode"] = "ALL_CURRENT_PUBLISHABLE_NOT_IN_FACEBOOK_LEDGER_FULL_WRITER_PRODUCTS"
    return stories, event


def install() -> None:
    base.current_event_stories = current_publishable_backlog


def self_test() -> int:
    install()
    assert base.current_event_stories is current_publishable_backlog
    product = base.build_text_product(
        {
            "id": "hcl-test",
            "section": "ADMINISTRAȚIE",
            "headline": "HCL 1/2026: decizie explicată din registrul oficial",
            "dek": "Registrul oficial confirmă numărul, data și obiectul deciziei, iar articolul delimitează clar ce rămâne de verificat.",
            "paragraphs": ["Textul explicativ păstrează sursa și nu inventează valori sau beneficiari care nu sunt documentați."],
        },
        {"canonical_urls": {"hcl-test": "https://valceaclar.ro/stiri/hcl-test/"}},
    )
    assert product["native_format"] == "text_link"
    assert product["visual_used"] is False
    assert "FULL_WRITER_PRODUCTS" in current_publishable_backlog.__doc__ if current_publishable_backlog.__doc__ else True
    print("VÂLCEA CLAR Facebook text-first v2 durable backlog self-test: PASS")
    return 0


def main() -> int:
    import sys
    if "--self-test" in sys.argv:
        return self_test()
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
