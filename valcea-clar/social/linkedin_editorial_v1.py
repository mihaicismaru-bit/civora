#!/usr/bin/env python3
"""Preview-only LinkedIn editorial packaging v1 for VÂLCEA CLAR.

LinkedIn is treated as a professional/local-decision-maker publication. It
selects stories for business, investment, institutions, public money,
procurement and infrastructure relevance, then packages them as concise
professional explainers. No network calls are made here.
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
PREVIEW = VC / "social" / "previews" / "linkedin-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def compact(text: str, limit: int = 650) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[:limit - 1].rsplit(" ", 1)[0]
    return (cut or value[:limit - 1]).rstrip(" ,.;:") + "…"


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


def relevance_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "linkedin_professional_gate_thin_story"
    professional_markers = (
        "contract", "licita", "achizi", "buget", "finanț", "investi", "smis",
        "proiect", "infrastruct", "companie", "srl", "lei", "consiliul local",
        "consiliul județean", "primăria", "minister", "fonduri", "operator",
        "proprietar", "angaja", "economie", "business",
    )
    if not any(marker in corpus for marker in professional_markers):
        return False, "linkedin_professional_gate_no_decision_maker_relevance"
    if len(corpus) < 150:
        return False, "linkedin_professional_gate_insufficient_context"
    return True, None


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason = relevance_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "linkedin-editorial-v1.0",
        }

    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = money_values(corpus)
    pair = contractor_pair(corpus)
    hook_family = "professional_consequence"
    format_family = "professional_update"
    blocks: list[str] = []

    if "olănești" in lower and money:
        hook = f"{money[0]} pentru proiectul de pe Olănești: ce arată documentele publice"
        blocks.append("Documentația SMIS 334436 include, în zona Omniasig, un pod nou exclusiv pietonal și ciclist, ca parte a proiectului mai larg de mobilitate urbană.")
        actor = pair or "asocierea câștigătoare"
        if len(money) > 1:
            blocks.append(f"Contractul principal a fost atribuit {actor}, la {money[1]} fără TVA. Valoarea totală aprobată a proiectului este {money[0]} cu TVA.")
        else:
            blocks.append(f"Contractul principal a fost atribuit {actor}.")
        blocks.append("Limită de atribuire: documentele consultate nu permit identificarea firmei care execută exact lucrările vizibile în fotografiile actuale. VÂLCEA CLAR nu formulează în acest moment o acuzație de neregulă.")
        hook_family = "investment_number"
        format_family = "document_explainer"
    elif money:
        hook = f"{money[0]} — miza locală din spatele deciziei"
        blocks.append(compact(dek or headline, 520))
        if paragraphs:
            blocks.append(compact(paragraphs[0], 520))
        hook_family = "public_money"
        format_family = "document_explainer"
    else:
        hook = headline
        blocks.append(compact(dek or (paragraphs[0] if paragraphs else headline), 520))

    body = "\n\n".join([hook, *blocks, "Documente și context: " + base.canonical(story)])
    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "durable_outbox_only",
        "native_format": "text",
        "format_family": format_family,
        "hook_family": hook_family,
        "hook": hook,
        "body": body,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "professional_context": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "rendering_version": "linkedin-editorial-v1.0",
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
        "platform": "linkedin",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    lifestyle = {
        "id": "event",
        "headline": "Concert în parc",
        "dek": "Intrarea este liberă.",
        "paragraphs": ["Program de familie."],
        "material_fact_gate": "PASS",
    }
    assert package(lifestyle)["status"] == "HOLD"
    sample = {
        "id": "olanesti-test",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436 de infrastructură.",
        "paragraphs": [
            "Documentația include un pod exclusiv pietonal și ciclist.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul principal a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
        "material_fact_gate": "PASS",
    }
    product = package(sample)
    assert product["status"] == "READY"
    assert product["format_family"] == "document_explainer"
    assert "Ralunic + Dimex-2000 Company" in product["body"]
    assert "44,37 mil. lei" in product["hook"]
    assert "#" not in product["body"]
    print("VÂLCEA CLAR LinkedIn editorial v1 self-test: PASS")
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
