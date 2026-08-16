#!/usr/bin/env python3
"""Preview-only Threads editorial packaging v1 for VÂLCEA CLAR.

Threads is treated as a conversation-native, text-first sister publication. The
same verified story kernel is rewritten into concise observations/explainers,
not copied from X, Facebook or Instagram. This module makes no network calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import build_outbox_only_story_products as base

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
PREVIEW = VC / "social" / "previews" / "threads-v1"
MAX_INTERNAL_CHARS = 470


def compact(text: str, limit: int = MAX_INTERNAL_CHARS) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return (cut or value[: limit - 1]).rstrip(" ,.;:") + "…"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


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


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s+[—–-]\s+", " + ", value)
    return re.sub(r"\s+", " ", value).strip(" +") or None


def interest_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "threads_conversation_gate_thin_title_date_source_only"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    if len(headline) + len(dek) + sum(len(p) for p in paragraphs[:2]) < 120:
        return False, "threads_conversation_gate_insufficient_context"
    return True, None


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason = interest_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "threads-editorial-v1.0",
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    posts: list[str] = []
    hook_family = "clear_observation"
    format_family = "text_update"

    if "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        posts = [
            "În Zăvoi, azi: Luminos Fest are intrare liberă. Evenimentul se întinde pe 15–16 august și e orientat spre familii și copii.",
            "Util de știut: lampioanele plutitoare se rezervă separat, online. Contextul și sursele verificate sunt în articol: " + base.canonical(story),
        ]
        hook_family = "local_utility"
        format_family = "conversation_update"
    elif "olănești" in lower and money:
        contract = money[1] if len(money) > 1 else None
        actor = pair or "asocierea câștigătoare"
        posts = [
            f"44,37 mil. lei este valoarea totală aprobată pentru proiectul care include un pod nou peste Olănești, în zona Omniasig.",
            "Ce știm: documentația SMIS 334436 descrie un pod exclusiv pietonal și ciclist. "
            + (f"Contractul principal a fost atribuit {actor}, la {contract} fără TVA." if contract else f"Contractul principal a fost atribuit {actor}."),
            "Ce nu știm încă: documentele publice nu ne permit să atribuim lucrările vizibile unei anumite firme din asociere sau unui subcontractant. Nu există, în acest moment, o acuzație de neregulă. Sursele: " + base.canonical(story),
        ]
        hook_family = "short_explainer"
        format_family = "explanatory_thread"
    elif money:
        posts.append(f"Un număr care merită context: {money[0]}. {compact(headline, 300)}")
        if dek:
            posts.append(compact(dek, 360))
        posts.append("Documentele și contextul complet: " + base.canonical(story))
        hook_family = "key_number_context"
        format_family = "explanatory_thread"
    else:
        opening = dek or headline
        posts.append(compact(opening, 390))
        if paragraphs:
            posts.append(compact(paragraphs[0], 390))
        posts.append("Context și surse: " + base.canonical(story))

    posts = [compact(post) for post in posts if str(post).strip()]
    if len(posts) > 4:
        posts = posts[:3] + [posts[-1]]
    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "durable_outbox_only",
        "native_format": "thread" if len(posts) > 1 else "text",
        "format_family": format_family,
        "hook_family": hook_family,
        "posts": posts,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "conversation_native": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "max_internal_chars_per_post": MAX_INTERNAL_CHARS,
        "rendering_version": "threads-editorial-v1.0",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def build() -> dict[str, Any]:
    pointer = base.load(base.POINTER)
    snapshot = base.load(base.VC / str(pointer["json_source"]))
    decision = base.load(base.DECISION, {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"story_ids": []})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [
        item for item in snapshot.get("items", [])
        if item.get("id") in allowed and base.story_ready(item)[0]
    ]
    products = [package(story) for story in stories]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0-preview",
        "platform": "threads",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    thin = {"id": "thin", "headline": "Eveniment", "dek": "15 august", "paragraphs": [], "material_fact_gate": "PASS_DATE_ONLY"}
    assert package(thin)["status"] == "HOLD"
    sample = {
        "id": "olanesti-test",
        "section": "INVESTIGAȚII",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436.",
        "paragraphs": [
            "Documentația include un pod exclusiv pietonal și ciclist.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
    }
    product = package(sample)
    assert product["status"] == "READY"
    assert product["format_family"] == "explanatory_thread"
    assert "Ralunic + Dimex-2000 Company" in " ".join(product["posts"])
    assert all(len(post) <= MAX_INTERNAL_CHARS for post in product["posts"])
    assert not any("#" in post for post in product["posts"])
    print("VÂLCEA CLAR Threads editorial v1 self-test: PASS")
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
