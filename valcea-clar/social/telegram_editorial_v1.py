#!/usr/bin/env python3
"""Preview-only Telegram editorial packaging v1 for VÂLCEA CLAR.

Telegram is a high-signal, opt-in local news channel: compact utility, corrections,
public-interest facts and developing updates. It does not inherit generic alert
prefixes or copy from Facebook/X/Threads. No network calls are made here.
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
PREVIEW = VC / "social" / "previews" / "telegram-v1"
MAX_MESSAGE_CHARS = 1050


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def compact(text: str, limit: int) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return (cut or value[: limit - 1]).rstrip(" ,.;:") + "…"


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


def signal_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "telegram_signal_gate_thin_title_date_source_only"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    if len(headline) + len(dek) + sum(len(p) for p in paragraphs[:2]) < 105:
        return False, "telegram_signal_gate_insufficient_context"
    return True, None


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason = signal_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "telegram-editorial-v1.0",
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    correction = story.get("correction") is True
    format_family = "signal_update"
    title = headline
    bullets: list[str] = []

    if correction:
        title = f"CORECȚIE — {headline}"
        format_family = "correction"
        if dek:
            bullets.append(dek)
    elif "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        title = "Zăvoi, azi: intrare liberă la Luminos Fest"
        bullets = [
            "15–16 august, Parcul Zăvoi.",
            "Lampioanele plutitoare se rezervă separat, online.",
        ]
        format_family = "event_utility"
    elif "olănești" in lower and money:
        title = f"{money[0]} pentru proiectul de pe Olănești"
        bullets.append("SMIS 334436 include, în zona Omniasig, un pod nou exclusiv pietonal și ciclist.")
        if pair:
            contract = money[1] if len(money) > 1 else None
            bullets.append(f"Contract principal: {pair}" + (f", {contract} fără TVA." if contract else "."))
        bullets.append("Documentele publice nu permit încă atribuirea lucrărilor vizibile unei firme anume din asociere/subcontractanților.")
        format_family = "public_interest_update"
    else:
        if dek:
            bullets.append(dek)
        if paragraphs:
            bullets.append(paragraphs[0])
        if money:
            format_family = "public_money_update"

    lines = [title]
    lines.extend(f"• {compact(item, 300)}" for item in bullets[:3] if item)
    lines.append("Detalii și surse: " + base.canonical(story))
    message = "\n\n".join(lines)
    if len(message) > MAX_MESSAGE_CHARS:
        message = compact(message, MAX_MESSAGE_CHARS)
    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "durable_outbox_only",
        "native_format": "alert" if correction else "text",
        "format_family": format_family,
        "message": message,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "high_signal": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "max_message_chars": MAX_MESSAGE_CHARS,
        "rendering_version": "telegram-editorial-v1.0",
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
        "platform": "telegram",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    thin = {"id":"thin","headline":"Eveniment","dek":"15 august","paragraphs":[],"material_fact_gate":"PASS_DATE_ONLY"}
    assert package(thin)["status"] == "HOLD"
    sample = {
        "id":"olanesti-test",
        "headline":"Pod peste Olănești",
        "dek":"Proiect SMIS 334436.",
        "paragraphs":[
            "Documentația include un pod exclusiv pietonal și ciclist.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA."
        ],
        "material_fact_gate":"PASS",
    }
    product=package(sample)
    assert product["status"]=="READY"
    assert product["format_family"]=="public_interest_update"
    assert "44,37 mil. lei" in product["message"]
    assert "Ralunic + Dimex-2000 Company" in product["message"]
    assert len(product["message"]) <= MAX_MESSAGE_CHARS
    assert "#" not in product["message"]
    print("VÂLCEA CLAR Telegram editorial v1 self-test: PASS")
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(),ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
