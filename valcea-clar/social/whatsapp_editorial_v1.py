#!/usr/bin/env python3
"""Preview-only WhatsApp editorial packaging v1 for VÂLCEA CLAR.

WhatsApp is a low-frequency, high-trust sister publication. It only prepares
stories that are materially useful enough to justify an interruption: essential
service utility, meaningful public-interest/infrastructure facts, corrections,
or strong weekend utility. No network calls or recipient assumptions are made.
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
PREVIEW = VC / "social" / "previews" / "whatsapp-v1"
MAX_MESSAGE_CHARS = 900


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


def high_value_gate(story: dict[str, Any]) -> tuple[bool, str | None, str | None]:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()
    gate = str(story.get("material_fact_gate") or "").strip()
    if story.get("correction") is True:
        return True, None, "correction"
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "whatsapp_high_value_gate_thin_title_date_source_only", None
    if "luminos" in corpus and "zăvoi" in corpus and "intrarea este liberă" in corpus:
        return True, None, "weekend_utility"
    public_interest = any(marker in corpus for marker in (
        "contract", "smis", "buget", "consiliul local", "consiliul județean",
        "achizi", "licita", "infrastruct", "pod", "drum", "trafic", "închidere",
        "apă", "curent", "spital", "școal", "finanț", "milioane", "mil. lei",
    ))
    if public_interest and (money_values(" ".join([headline, dek, *paragraphs])) or len(corpus) >= 220):
        return True, None, "essential_public_interest"
    service = any(marker in corpus for marker in (
        "program", "acces", "închis", "deschis", "gratuit", "intrarea", "ora ",
        "trafic", "transport", "alertă meteo", "apă oprită", "energie oprită",
    ))
    if service and len(corpus) >= 150:
        return True, None, "essential_service_utility"
    return False, "whatsapp_high_value_gate_not_essential_enough", None


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason, distribution_class = high_value_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "whatsapp-editorial-v1.0",
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    correction = story.get("correction") is True

    title = headline
    facts: list[str] = []
    priority = 70
    if correction:
        title = f"Corecție — {headline}"
        facts = [dek] if dek else []
        priority = 100
    elif "luminos" in lower and "zăvoi" in lower and "intrarea este liberă" in lower:
        title = "Weekend în Vâlcea: Luminos Fest, azi în Zăvoi"
        facts = [
            "Intrarea este liberă. Evenimentul are loc în 15–16 august.",
            "Lampioanele plutitoare se rezervă separat, online.",
        ]
        priority = 78
    elif "olănești" in lower and money:
        title = f"De urmărit: {money[0]} pentru proiectul de pe Olănești"
        facts = [
            "SMIS 334436 include, în zona Omniasig, un pod nou exclusiv pietonal și ciclist.",
        ]
        if pair:
            contract = money[1] if len(money) > 1 else None
            facts.append(f"Contract principal: {pair}" + (f", {contract} fără TVA." if contract else "."))
        facts.append("Documentele publice nu permit încă atribuirea exactă a lucrărilor vizibile unei firme anume.")
        priority = 90
    else:
        title = headline
        if dek:
            facts.append(dek)
        if paragraphs:
            facts.append(paragraphs[0])
        priority = 82 if distribution_class == "essential_public_interest" else 75

    lines = [title]
    lines.extend(f"• {compact(fact, 260)}" for fact in facts[:3] if fact)
    lines.append("Detalii și surse: " + base.canonical(story))
    message = "\n\n".join(lines)
    if len(message) > MAX_MESSAGE_CHARS:
        message = compact(message, MAX_MESSAGE_CHARS)

    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "durable_outbox_only",
        "native_format": "text",
        "format_family": "high_trust_update",
        "distribution_class": distribution_class,
        "priority": priority,
        "message": message,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "low_frequency": True,
        "recipient_scope_required_before_dispatch": True,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "hashtags_default": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "max_message_chars": MAX_MESSAGE_CHARS,
        "rendering_version": "whatsapp-editorial-v1.0",
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
        "platform": "whatsapp",
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
        "dek":"Proiect SMIS 334436 de infrastructură.",
        "paragraphs":[
            "Documentația include un pod exclusiv pietonal și ciclist.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA."
        ],
        "material_fact_gate":"PASS",
    }
    product=package(sample)
    assert product["status"]=="READY"
    assert product["priority"]==90
    assert "44,37 mil. lei" in product["message"]
    assert "Ralunic + Dimex-2000 Company" in product["message"]
    assert len(product["message"]) <= MAX_MESSAGE_CHARS
    assert "#" not in product["message"]
    print("VÂLCEA CLAR WhatsApp editorial v1 self-test: PASS")
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
