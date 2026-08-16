#!/usr/bin/env python3
"""VÂLCEA CLAR outbox-only product builder v1.1.

This incremental wrapper upgrades only X packaging while preserving the existing
independent products for Threads, LinkedIn, Telegram, WhatsApp and YouTube.
"""
from __future__ import annotations

import json
import re

import build_outbox_only_story_products as base


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


def money_values(text: str) -> list[str]:
    values: list[str] = []
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        if number >= 1_000_000:
            shown = f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mil. lei"
        else:
            shown = f"{int(round(number)):,}".replace(",", ".") + " lei"
        if shown not in values:
            values.append(shown)
    return values


def x_interest_gate(story: dict) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "x_interest_gate_thin_title_date_source_only"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    useful = len(headline) + len(dek) + sum(len(p) for p in paragraphs[:2])
    if useful < 110:
        return False, "x_interest_gate_insufficient_context"
    return True, None


def x_product(story: dict) -> dict:
    """Build a compact X-native update/thread with a real interest gate.

    X should feel like a live news wire, not a second Threads account. Lead with
    the change/number/utility, put one concrete fact per post, then link to the
    canonical source. Thin event stubs stay HOLD even though the site may be live.
    """
    story_id = str(story["id"])
    ok, reason = x_interest_gate(story)
    if not ok:
        return {
            "id": f"x-story-{story_id}",
            "story_id": story_id,
            "status": "hold",
            "publication_mode": "durable_outbox_only",
            "native_format": "text",
            "format_family": "x_hold",
            "hold_reason": reason,
            "canonical_url": base.canonical(story),
            "source_preserving": True,
            "fake_urgency_forbidden": True,
            "engagement_bait_forbidden": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "direct_publication_enabled": False,
            "direct_publication_blocker": "x_api_pay_per_use_conflicts_zero_paid_dependency",
            "edition_gate": False,
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    section = str(story.get("section") or "").upper()
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    correction = story.get("correction") is True

    posts: list[str] = []
    hook_family = "what_changed"

    if correction:
        posts.append(base.compact(f"Corecție: {headline}"))
        hook_family = "correction"
    elif "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        posts.append("Azi în Zăvoi: intrarea este liberă la Luminos Fest.")
        posts.append("Evenimentul are loc în 15–16 august. Lampioanele plutitoare se rezervă separat, online.")
        hook_family = "local_utility"
    elif "olănești" in lower and money:
        posts.append(f"{money[0]} pentru proiectul de pe Olănești.")
        posts.append("Documentația SMIS 334436 include, în zona Omniasig, un pod nou exclusiv pietonal și ciclist.")
        contract = money[1] if len(money) > 1 else None
        actor = pair or "asocierea câștigătoare"
        detail = f"Contractul principal: {actor}"
        if contract:
            detail += f", {contract} fără TVA"
        detail += ". Nu atribuim lucrările vizibile unei firme fără documente suficiente."
        posts.append(base.compact(detail))
        hook_family = "key_number"
    elif money and (section == "INVESTIGAȚII" or any(token in lower for token in ("contract", "buget", "finanț", "smis"))):
        posts.append(base.compact(f"{money[0]}: {headline}"))
        if dek:
            posts.append(base.compact(dek))
        hook_family = "key_number"
    else:
        posts.append(base.compact(headline))
        if dek:
            posts.append(base.compact(dek))
        elif paragraphs:
            posts.append(base.compact(paragraphs[0]))

    # Keep source post last and total thread compact. No generic CTA or hashtags.
    posts = [post for post in posts if post][:3]
    posts.append(base.compact(f"Documente și context: {base.canonical(story)}"))

    return {
        "id": f"x-story-{story_id}",
        "story_id": story_id,
        "status": "outbox_ready",
        "publication_mode": "durable_outbox_only",
        "native_format": "thread" if len(posts) > 2 else "text",
        "format_family": "x_live_thread" if len(posts) > 2 else "x_update",
        "hook_family": hook_family,
        "posts": posts,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "max_post_chars_internal": 260,
        "hashtags_default": False,
        "fake_urgency_forbidden": True,
        "engagement_bait_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "quote_post_dependency_forbidden": True,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "x_api_pay_per_use_conflicts_zero_paid_dependency",
        "official_api_reference": "https://docs.x.com/x-api/posts/create-post",
        "official_pricing_reference": "https://docs.x.com/x-api/getting-started/pricing",
        "edition_gate": False,
    }


base.x_product = x_product


def self_test() -> int:
    assert contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    thin = {
        "id": "thin",
        "headline": "Eveniment local",
        "dek": "15–16 august",
        "paragraphs": [],
        "material_fact_gate": "PASS_DATE_ONLY",
    }
    held = x_product(thin)
    assert held["status"] == "hold" and held["hold_reason"].startswith("x_interest_gate_")
    sample = {
        "id": "olanesti-test",
        "section": "INVESTIGAȚII",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436.",
        "paragraphs": [
            "Documentația include un pod nou exclusiv pietonal și ciclist în zona Omniasig.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
    }
    product = x_product(sample)
    assert product["status"] == "outbox_ready"
    assert product["posts"][0] == "44,37 mil. lei pentru proiectul de pe Olănești."
    assert "Ralunic + Dimex-2000 Company" in product["posts"][2]
    assert all(len(post) <= 260 for post in product["posts"])
    assert not any("#" in post for post in product["posts"])
    print("VÂLCEA CLAR X editorial gate v1.1 self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in __import__("sys").argv:
        return self_test()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
