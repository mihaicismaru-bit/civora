#!/usr/bin/env python3
"""Preview-only LinkedIn editorial packaging v1.1 for VÂLCEA CLAR.

LinkedIn is treated as a professional/local-decision-maker publication. READY
stories receive an original evidence-led editorial card generated only from the
verified story kernel. No decorative photography, synthetic media or network
calls are used here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

import build_outbox_only_story_products as base
from native_identity import load_system, product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
PREVIEW = VC / "social" / "previews" / "linkedin-v1"

SERIF_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
SANS_REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


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


def visual_plan(
    *,
    headline: str,
    dek: str,
    paragraphs: list[str],
    money: list[str],
    pair: str | None,
    lower: str,
) -> dict[str, Any]:
    if "olănești" in lower and money:
        actor = pair or "asocierea câștigătoare"
        contract = f"{actor}"
        if len(money) > 1:
            contract += f" · {money[1]} fără TVA"
        return {
            "kind": "editorial_evidence_card",
            "kicker": "BANI PUBLICI · INFRASTRUCTURĂ",
            "metric": money[0],
            "headline": "Ce se construiește pe Olănești",
            "facts": [
                {"label": "PROIECT", "text": "SMIS 334436 · pod nou exclusiv pietonal și ciclist în zona Omniasig."},
                {"label": "CONTRACT", "text": contract},
                {
                    "label": "LIMITĂ DE ATRIBUIRE",
                    "text": "Documentele consultate nu permit identificarea firmei care execută exact lucrările vizibile.",
                },
            ],
            "source_label": "DOCUMENTE ȘI SURSE · valceaclar.ro",
        }
    facts: list[dict[str, str]] = []
    if dek:
        facts.append({"label": "DECIZIE", "text": compact(dek, 190)})
    if paragraphs:
        facts.append({"label": "CONTEXT", "text": compact(paragraphs[0], 210)})
    if len(paragraphs) > 1:
        facts.append({"label": "CE MAI ȘTIM", "text": compact(paragraphs[1], 210)})
    return {
        "kind": "editorial_evidence_card",
        "kicker": "DECIZIE LOCALĂ · CONTEXT",
        "metric": money[0] if money else None,
        "headline": headline,
        "facts": facts[:3],
        "source_label": "DOCUMENTE ȘI SURSE · valceaclar.ro",
    }


def package(story: dict[str, Any]) -> dict[str, Any]:
    story_id = str(story["id"])
    ok, reason = relevance_gate(story)
    if not ok:
        return {
            "story_id": story_id,
            "status": "HOLD",
            "reason": reason,
            "canonical_url": base.canonical(story),
            "rendering_version": "linkedin-editorial-v1.1",
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
    visual = visual_plan(
        headline=headline,
        dek=dek,
        paragraphs=paragraphs,
        money=money,
        pair=pair,
        lower=lower,
    )
    product = {
        "story_id": story_id,
        "status": "READY",
        "publication_mode": "durable_outbox_only",
        "native_format": "image_plus_text",
        "format_family": format_family,
        "hook_family": hook_family,
        "hook": hook,
        "body": body,
        "visual": visual,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "professional_context": True,
        "hashtags_default": False,
        "generic_engagement_prompt_forbidden": True,
        "fake_urgency_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "rendering_version": "linkedin-editorial-v1.1",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported LinkedIn editorial font found")


def _wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    words = str(text).split()
    lines: list[str] = []
    current = ""
    index = 0
    while index < len(words):
        word = words[index]
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= width:
            current = candidate
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines - 1:
                break
            continue
        index += 1
    if len(lines) < max_lines:
        remainder = ([current] if current else []) + words[index:]
        last = " ".join(remainder).strip()
        if last:
            while draw.textbbox((0, 0), last + "…", font=fnt)[2] > width and " " in last:
                last = last.rsplit(" ", 1)[0]
            if len(" ".join(lines + [last]).split()) < len(words):
                last = last.rstrip(" ,.;:") + "…"
            lines.append(last)
    return lines[:max_lines]


def _draw_vc(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, ink: tuple[int, int, int], accent: tuple[int, int, int]) -> int:
    fnt = _font(SERIF_BOLD, size)
    draw.text((x, y), "VC", font=fnt, fill=ink)
    advance = int(draw.textlength("VC", font=fnt))
    draw.text((x + advance, y), ".", font=fnt, fill=accent)
    return int(draw.textlength("VC.", font=fnt))


def render_card(product: dict[str, Any], output: Path) -> None:
    visual = product.get("visual") if isinstance(product.get("visual"), dict) else None
    if not visual or visual.get("kind") != "editorial_evidence_card":
        raise ValueError("LinkedIn READY product requires editorial_evidence_card visual")
    identity = product_identity("linkedin")
    canvas = tuple(int(v) for v in identity["visual"]["portrait_card_canvas"])
    common = load_system()["common"]
    paper = tuple(int(v) for v in common["paper_rgb"])
    ink = tuple(int(v) for v in common["ink_rgb"])
    accent = tuple(int(v) for v in common["accent_rgb"])
    image = Image.new("RGB", canvas, paper)
    draw = ImageDraw.Draw(image)
    margin = 76

    mark_w = _draw_vc(draw, margin, 72, 36, ink, accent)
    section_font = _font(SANS_BOLD, 24)
    draw.text((margin + mark_w + 26, 82), "VÂLCEA CLAR", font=section_font, fill=ink)
    hairline_y = 137
    draw.rectangle((margin, hairline_y, canvas[0] - margin, hairline_y + 1), fill=(110, 110, 110))
    draw.rectangle((margin, hairline_y - 1, margin + 74, hairline_y + 4), fill=accent)

    kicker_font = _font(SANS_BOLD, 25)
    draw.text((margin, 190), str(visual.get("kicker") or "CONTEXT LOCAL"), font=kicker_font, fill=accent)
    y = 245
    metric = str(visual.get("metric") or "").strip()
    if metric:
        metric_font = _font(SERIF_BOLD, 94)
        for line in _wrap(draw, metric, metric_font, canvas[0] - 2 * margin, 2):
            draw.text((margin, y), line, font=metric_font, fill=ink)
            y += 110
        y += 12

    headline_font = _font(SERIF_BOLD, 57 if metric else 68)
    for line in _wrap(draw, str(visual.get("headline") or product.get("hook") or ""), headline_font, canvas[0] - 2 * margin, 3):
        draw.text((margin, y), line, font=headline_font, fill=ink)
        y += int(headline_font.size * 1.18)
    y += 34

    facts = visual.get("facts") if isinstance(visual.get("facts"), list) else []
    label_font = _font(SANS_BOLD, 21)
    body_font = _font(SANS_REGULAR, 29)
    for fact in facts[:3]:
        if not isinstance(fact, dict):
            continue
        if y > canvas[1] - 300:
            break
        draw.rectangle((margin, y, canvas[0] - margin, y + 1), fill=(205, 203, 198))
        y += 24
        draw.text((margin, y), str(fact.get("label") or "FAPT"), font=label_font, fill=accent)
        y += 38
        for line in _wrap(draw, str(fact.get("text") or ""), body_font, canvas[0] - 2 * margin, 3):
            draw.text((margin, y), line, font=body_font, fill=(45, 45, 45))
            y += 42
        y += 28

    source_font = _font(SANS_BOLD, 20)
    source = str(visual.get("source_label") or "DOCUMENTE ȘI SURSE · valceaclar.ro")
    footer_y = canvas[1] - 92
    draw.rectangle((margin, footer_y - 30, canvas[0] - margin, footer_y - 29), fill=(205, 203, 198))
    draw.text((margin, footer_y), source, font=source_font, fill=(75, 75, 75))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


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
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    for product in products:
        if product.get("status") != "READY":
            continue
        filename = f"{product['story_id']}-linkedin-v1-1-card.jpg"
        render_card(product, PREVIEW / filename)
        product["preview_file"] = filename
    manifest = {
        "schema_version": "1.1-preview",
        "platform": "linkedin",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "rendering_version": "linkedin-editorial-v1.1",
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
    assert product["native_format"] == "image_plus_text"
    assert product["format_family"] == "document_explainer"
    assert "Ralunic + Dimex-2000 Company" in product["body"]
    assert "44,37 mil. lei" in product["hook"]
    assert product["visual"]["metric"] == "44,37 mil. lei"
    assert product["visual"]["facts"][1]["label"] == "CONTRACT"
    assert "#" not in product["body"]
    with tempfile.TemporaryDirectory() as raw:
        rendered = Path(raw) / "linkedin.jpg"
        render_card(product, rendered)
        with Image.open(rendered) as image:
            assert image.size == (1200, 1500)
        assert rendered.stat().st_size > 25_000
    print("VÂLCEA CLAR LinkedIn editorial v1.1 self-test: PASS")
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
