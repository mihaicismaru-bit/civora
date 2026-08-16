#!/usr/bin/env python3
"""Preview-only Instagram editorial packaging for VÂLCEA CLAR.

This prototype never calls Meta. It turns verified story + approved visual bindings
into 1080x1350 editorial covers and a machine-readable plan so the design can be
reviewed before any production adapter wiring.
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
CURRENT = VC / "site" / "current_edition.json"
DECISION = VC / "site" / "newsroom_decision.json"
VISUALS = VC / "social" / "story_visuals.json"
APPROVED = VC / "social" / "photos" / "approved"
PREVIEW = VC / "social" / "previews" / "instagram"

CANVAS = (1080, 1350)
SAFE_X = 72
TOP = 68
BOTTOM = 78
MAX_HEADLINE_LINES = 4

FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
FONT_REGULAR_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain an object")
    return value


def choose_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported system TrueType font found")


def story_snapshot() -> list[dict[str, Any]]:
    pointer = load(CURRENT)
    edition = load(VC / str(pointer["json_source"]))
    decision = load(DECISION)
    allowed = set(decision.get("publishable_story_ids") or [])
    return [
        item for item in edition.get("items", [])
        if isinstance(item, dict) and item.get("id") in allowed
    ]


def visual_for(story_id: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    value = registry.get("stories", {}).get(story_id)
    return value if isinstance(value, dict) else None


def utility_gate(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "")
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "thin_title_date_source_only"
    if not visual:
        return False, "no_approved_story_visual"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    substance = len(headline) + len(dek) + sum(len(p) for p in paragraphs)
    if substance < 120:
        return False, "insufficient_instagram_utility"
    return True, None


def normalize_amount(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I)
    if not match:
        return None
    raw = match.group(1).replace(".", "").replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        return None
    if value >= 1_000_000:
        formatted = f"{value / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",")
        return f"{formatted} mil. lei"
    return f"{int(round(value)):,}".replace(",", ".") + " lei"


def package(story: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lowered = corpus.lower()

    template = "breaking_card"
    hook = headline
    subline = dek

    if section in {"EVENIMENTE", "CULTURĂ", "UNDE IEȘIM"}:
        template = "event_utility_card"
        if "intrarea este liberă" in lowered:
            if "zăvoi" in lowered and "luminos" in lowered:
                hook = "Luminos Fest, azi în Zăvoi"
            else:
                hook = headline
            subline = "Intrarea este liberă"
    if section == "INVESTIGAȚII" or any(token in lowered for token in ("contract", "atribuit", "execut", "smis")):
        template = "investigation_card"
        amount = normalize_amount(corpus)
        if amount:
            if "olănești" in lowered:
                hook = f"{amount} pentru proiectul de pe Olănești"
                subline = "Cine a câștigat lucrările și ce se construiește"
            else:
                hook = amount
    if any(token in lowered for token in ("consiliul local", "buget", "bani publici", "finanț")):
        amount = normalize_amount(corpus)
        if amount:
            template = "public_money_card"
            hook = amount
            subline = headline

    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    archive = bool(image.get("contextual_archive"))
    return {
        "status": "READY",
        "story_id": story["id"],
        "template_id": template,
        "section": section,
        "hook": hook,
        "subline": subline,
        "archive_marker": "FOTO DE ARHIVĂ" if archive else None,
        "editorial_note": image.get("editorial_note"),
        "source_image_path": visual.get("image_path"),
        "source_url": image.get("source_url"),
        "credit": image.get("credit"),
        "rights_basis": image.get("rights_basis"),
    }


def cover_crop(image: Image.Image) -> Image.Image:
    image = image.convert("RGB")
    target_ratio = CANVAS[0] / CANVAS[1]
    source_ratio = image.width / image.height
    if source_ratio > target_ratio:
        new_w = int(image.height * target_ratio)
        left = max(0, (image.width - new_w) // 2)
        image = image.crop((left, 0, left + new_w, image.height))
    else:
        new_h = int(image.width / target_ratio)
        top = max(0, (image.height - new_h) // 2)
        image = image.crop((0, top, image.width, top + new_h))
    return image.resize(CANVAS, Image.Resampling.LANCZOS)


def wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = current + " " + word
        if draw.textbbox((0, 0), candidate, font=font)[2] <= width:
            current = candidate
        else:
            lines.append(current)
            current = word
            if len(lines) == max_lines - 1:
                break
    remaining = words[sum(len(line.split()) for line in lines):]
    if len(lines) < max_lines:
        current = " ".join(remaining) if remaining else current
        while draw.textbbox((0, 0), current, font=font)[2] > width and len(current) > 8:
            current = current[:-2].rstrip() + "…"
        lines.append(current)
    return lines[:max_lines]


def render(plan: dict[str, Any], output: Path) -> None:
    source = ROOT / str(plan["source_image_path"])
    if not source.is_file():
        raise RuntimeError(f"missing downloaded approved image: {source}")
    base = cover_crop(Image.open(source))
    base = ImageEnhance.Contrast(base).enhance(1.04)

    overlay = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Dark bottom field with a soft stepped gradient. Keeps the photograph visible
    # while making the news angle readable at phone-feed size.
    start = 560
    for y in range(start, CANVAS[1]):
        progress = (y - start) / max(1, CANVAS[1] - start)
        alpha = int(42 + 186 * min(1.0, progress ** 0.72))
        od.line((0, y, CANVAS[0], y), fill=(0, 0, 0, alpha))
    od.rectangle((0, 0, CANVAS[0], 175), fill=(0, 0, 0, 62))
    composed = Image.alpha_composite(base.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(composed)

    kicker_font = choose_font(FONT_BOLD_CANDIDATES, 34)
    brand_font = choose_font(FONT_BOLD_CANDIDATES, 31)
    headline_font = choose_font(FONT_BOLD_CANDIDATES, 82)
    sub_font = choose_font(FONT_REGULAR_CANDIDATES, 38)
    archive_font = choose_font(FONT_BOLD_CANDIDATES, 26)

    # Brand rail.
    draw.rounded_rectangle((SAFE_X, TOP, SAFE_X + 235, TOP + 58), radius=12, fill=(196, 27, 35, 242))
    draw.text((SAFE_X + 18, TOP + 10), plan["section"], font=kicker_font, fill="white")
    brand = "VÂLCEA CLAR"
    brand_w = draw.textbbox((0, 0), brand, font=brand_font)[2]
    draw.text((CANVAS[0] - SAFE_X - brand_w, TOP + 12), brand, font=brand_font, fill="white")

    max_width = CANVAS[0] - 2 * SAFE_X
    headline_lines = wrap(draw, str(plan["hook"]), headline_font, max_width, MAX_HEADLINE_LINES)
    line_height = 96
    subline = str(plan.get("subline") or "").strip()
    sub_lines = wrap(draw, subline, sub_font, max_width, 2) if subline else []
    block_h = len(headline_lines) * line_height + (28 if sub_lines else 0) + len(sub_lines) * 52
    y = CANVAS[1] - BOTTOM - block_h - (54 if plan.get("archive_marker") else 0)
    y = max(650, y)

    # Small accent line anchors the headline without copying another outlet's trade dress.
    draw.rounded_rectangle((SAFE_X, y - 34, SAFE_X + 118, y - 24), radius=5, fill=(196, 27, 35, 255))
    for line in headline_lines:
        draw.text((SAFE_X, y), line, font=headline_font, fill="white", stroke_width=1, stroke_fill=(0, 0, 0, 120))
        y += line_height
    if sub_lines:
        y += 16
        for line in sub_lines:
            draw.text((SAFE_X, y), line, font=sub_font, fill=(242, 242, 242, 255))
            y += 52

    if plan.get("archive_marker"):
        marker = str(plan["archive_marker"])
        box = draw.textbbox((0, 0), marker, font=archive_font)
        w = box[2] - box[0]
        y = CANVAS[1] - BOTTOM - 36
        draw.rounded_rectangle((SAFE_X, y - 7, SAFE_X + w + 28, y + 35), radius=8, fill=(255, 255, 255, 225))
        draw.text((SAFE_X + 14, y), marker, font=archive_font, fill=(20, 20, 20, 255))

    output.parent.mkdir(parents=True, exist_ok=True)
    composed.convert("RGB").save(output, "JPEG", quality=92, optimize=True, progressive=True)


def build() -> dict[str, Any]:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    registry = load(VISUALS)
    plans: list[dict[str, Any]] = []
    for story in story_snapshot():
        story_id = str(story.get("id"))
        visual = visual_for(story_id, registry)
        allowed, reason = utility_gate(story, visual)
        if not allowed:
            plans.append({
                "status": "HOLD",
                "story_id": story_id,
                "reason": reason,
                "headline": story.get("headline"),
            })
            continue
        assert visual is not None
        plan = package(story, visual)
        filename = f"{story_id}-ig-cover-v0.jpg"
        plan["preview_file"] = filename
        render(plan, PREVIEW / filename)
        plans.append(plan)

    summary = {
        "schema_version": "0.1-preview",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "canvas": {"width": CANVAS[0], "height": CANVAS[1], "aspect_ratio": "4:5"},
        "plans": plans,
        "ready": sum(1 for p in plans if p.get("status") == "READY"),
        "held": sum(1 for p in plans if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def self_test() -> int:
    assert CANVAS == (1080, 1350)
    assert normalize_amount("valoare 44.373.317,87 lei cu TVA") == "44,37 mil. lei"
    thin = {"material_fact_gate": "PASS_DATE_ONLY", "headline": "X", "dek": "Y", "paragraphs": []}
    assert utility_gate(thin, {"image_path": "x"})[0] is False
    sample = {
        "id": "sample",
        "section": "INVESTIGAȚII",
        "headline": "Pod nou peste Olănești",
        "dek": "Urmărim contractul.",
        "paragraphs": ["Proiectul are o valoare totală de 44.373.317,87 lei."],
    }
    plan = package(sample, {"image_path": "x.jpg", "image": {"contextual_archive": True}})
    assert plan["template_id"] == "investigation_card"
    assert "44,37 mil. lei" in plan["hook"]
    assert plan["archive_marker"] == "FOTO DE ARHIVĂ"
    print("VÂLCEA CLAR Instagram editorial preview self-test: PASS")
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
