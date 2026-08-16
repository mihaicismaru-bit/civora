#!/usr/bin/env python3
"""VÂLCEA CLAR Instagram editorial packaging v1, preview-only.

Builds platform-native 4:5 covers and compact explainer carousels from the
verified story kernel and the approved visual registry. It never calls Meta.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
CURRENT = VC / "site" / "current_edition.json"
DECISION = VC / "site" / "newsroom_decision.json"
VISUALS = VC / "social" / "story_visuals.json"
SYSTEM = VC / "social" / "instagram_visual_system.json"
PREVIEW = VC / "social" / "previews" / "instagram-v1"

BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]
REGULAR = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported system font found")


def stories() -> list[dict[str, Any]]:
    pointer = load(CURRENT)
    edition = load(VC / str(pointer["json_source"]))
    allowed = set(load(DECISION).get("publishable_story_ids") or [])
    return [row for row in edition.get("items", []) if isinstance(row, dict) and row.get("id") in allowed]


def visual_for(story_id: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    value = registry.get("stories", {}).get(story_id)
    return value if isinstance(value, dict) else None


def approved_for_instagram(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str | None]:
    if str(story.get("material_fact_gate") or "") in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "thin_title_date_source_only"
    if not visual:
        return False, "no_approved_story_visual"
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    if image.get("editor_approved") is not True or image.get("subject_match") is not True:
        return False, "visual_not_editorially_ready"
    if image.get("synthetic") is not False:
        return False, "synthetic_visual_forbidden"
    headline = str(story.get("headline") or "")
    dek = str(story.get("dek") or "")
    paragraphs = [str(v) for v in story.get("paragraphs", []) if str(v).strip()]
    if len(headline) + len(dek) + sum(map(len, paragraphs)) < 120:
        return False, "insufficient_instagram_utility"
    return True, None


def amounts(text: str) -> list[str]:
    values = []
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


def truncate(text: str, limit: int) -> str:
    value = " ".join(str(text).split())
    if len(value) <= limit:
        return value
    cut = value[: limit - 1].rsplit(" ", 1)[0]
    return (cut or value[: limit - 1]).rstrip(" ,.;:") + "…"


def package(story: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    lower = corpus.lower()
    money = amounts(corpus)

    template = "breaking_card"
    hook = truncate(headline, 78)
    subline = truncate(dek, 100)
    native_format = "single_photo"
    slides: list[dict[str, str]] = []

    if section in {"EVENIMENTE", "CULTURĂ", "UNDE IEȘIM"}:
        template = "event_utility_card"
        if "luminos" in lower and "zăvoi" in lower:
            hook = "Luminos Fest în Zăvoi"
            subline = "Azi · intrarea este liberă"
        elif "intrarea este liberă" in lower:
            subline = "Intrarea este liberă"

    if section == "INVESTIGAȚII" or any(token in lower for token in ("contract", "atribuit", "execut", "smis")):
        template = "investigation_card"
        native_format = "carousel" if len(paragraphs) >= 2 else "single_photo"
        if money:
            hook = money[0]
            if "olănești" in lower:
                subline = "Pod pietonal-ciclist peste Olănești"
            else:
                subline = truncate(headline, 90)
        if paragraphs:
            slides.append({"kicker": "CE SE CONSTRUIEȘTE", "body": truncate(paragraphs[0], 260)})
        if len(paragraphs) > 1:
            slides.append({"kicker": "CIFRE ȘI CONTRACT", "body": truncate(paragraphs[1], 310)})
        if len(paragraphs) > 2:
            slides.append({"kicker": "CE NU ATRIBUIM ÎNCĂ", "body": truncate(paragraphs[2], 260)})

    if any(token in lower for token in ("consiliul local", "buget", "bani publici", "finanț")) and money:
        template = "public_money_card"
        hook = money[0]
        subline = truncate(headline, 92)

    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    plan = {
        "status": "READY",
        "story_id": str(story["id"]),
        "template_id": template,
        "native_format": native_format,
        "section": section,
        "hook": hook,
        "subline": subline,
        "detail_slides": slides[:5],
        "archive_marker": "FOTO DE ARHIVĂ" if image.get("contextual_archive") else None,
        "editorial_note": image.get("editorial_note"),
        "source_image_path": visual.get("image_path"),
        "source_url": image.get("source_url"),
        "credit": image.get("credit"),
        "rights_basis": image.get("rights_basis"),
        "rendering_version": "instagram-editorial-v1.0",
    }
    plan["product_fingerprint_sha256"] = digest({k: v for k, v in plan.items() if k != "product_fingerprint_sha256"})
    return plan


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines - 1:
            break
    remaining_count = sum(len(line.split()) for line in lines)
    rest = words[remaining_count:]
    if len(lines) < max_lines:
        last = " ".join(rest) if rest else current
        while draw.textbbox((0, 0), last, font=fnt)[2] > width and len(last) > 8:
            last = last[:-2].rstrip() + "…"
        lines.append(last)
    return lines[:max_lines]


def fit_headline(draw: ImageDraw.ImageDraw, text: str, width: int, system: dict[str, Any]) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    typo = system["typography"]
    max_lines = int(typo["headline_max_lines"])
    for size in range(int(typo["headline_size_max"]), int(typo["headline_size_min"]) - 1, -2):
        fnt = font(BOLD, size)
        lines = wrap(draw, text, fnt, width, max_lines)
        if lines and "…" not in lines[-1]:
            return fnt, lines
    fnt = font(BOLD, int(typo["headline_size_min"]))
    return fnt, wrap(draw, text, fnt, width, max_lines)


def crop(image: Image.Image, canvas: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    target = canvas[0] / canvas[1]
    source = image.width / image.height
    if source > target:
        width = int(image.height * target)
        left = (image.width - width) // 2
        image = image.crop((left, 0, left + width, image.height))
    else:
        height = int(image.width / target)
        top = (image.height - height) // 2
        image = image.crop((0, top, image.width, top + height))
    return image.resize(canvas, Image.Resampling.LANCZOS)


def render_cover(plan: dict[str, Any], output: Path, system: dict[str, Any]) -> None:
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    brand = system["brand"]
    safe = int(brand["safe_margin_px"])
    accent = tuple(brand["accent_rgb"])
    source = ROOT / str(plan["source_image_path"])
    if not source.is_file():
        raise RuntimeError(f"approved photograph missing: {source}")
    base = ImageEnhance.Contrast(crop(Image.open(source), canvas)).enhance(1.03)
    overlay = Image.new("RGBA", canvas, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(500, canvas[1]):
        progress = (y - 500) / max(1, canvas[1] - 500)
        alpha = int(25 + 205 * min(1.0, progress ** 0.7))
        od.line((0, y, canvas[0], y), fill=(0, 0, 0, alpha))
    od.rectangle((0, 0, canvas[0], 150), fill=(0, 0, 0, 52))
    image = Image.alpha_composite(base.convert("RGBA"), overlay)
    draw = ImageDraw.Draw(image)

    kicker = font(BOLD, int(system["typography"]["kicker_size"]))
    brand_font = font(BOLD, int(system["typography"]["brand_size"]))
    sub_font = font(REGULAR, int(system["typography"]["subline_size"]))
    archive_font = font(BOLD, int(system["typography"]["archive_size"]))

    top = int(brand["top_margin_px"])
    draw.text((safe, top), plan["section"], font=kicker, fill="white")
    section_w = draw.textbbox((0, 0), plan["section"], font=kicker)[2]
    draw.rounded_rectangle((safe, top + 43, safe + min(122, section_w), top + 50), radius=3, fill=(*accent, 255))
    brand_text = str(brand["name"])
    bw = draw.textbbox((0, 0), brand_text, font=brand_font)[2]
    draw.text((canvas[0] - safe - bw, top), brand_text, font=brand_font, fill="white")

    max_width = canvas[0] - 2 * safe
    headline_font, lines = fit_headline(draw, str(plan["hook"]), max_width, system)
    line_height = int(headline_font.size * 1.12)
    sub_lines = wrap(draw, str(plan.get("subline") or ""), sub_font, max_width, 2)
    block_h = len(lines) * line_height + (24 if sub_lines else 0) + len(sub_lines) * 48
    archive_h = 55 if plan.get("archive_marker") else 0
    y = canvas[1] - int(brand["bottom_margin_px"]) - block_h - archive_h
    y = max(720, y)

    for line in lines:
        draw.text((safe, y), line, font=headline_font, fill="white", stroke_width=1, stroke_fill=(0, 0, 0, 90))
        y += line_height
    if sub_lines:
        y += 14
        for line in sub_lines:
            draw.text((safe, y), line, font=sub_font, fill=(242, 242, 242, 255))
            y += 48
    if plan.get("archive_marker"):
        marker = str(plan["archive_marker"])
        mw = draw.textbbox((0, 0), marker, font=archive_font)[2]
        yy = canvas[1] - int(brand["bottom_margin_px"]) - 34
        draw.rounded_rectangle((safe, yy - 8, safe + mw + 26, yy + 32), radius=7, fill=(255, 255, 255, 230))
        draw.text((safe + 13, yy), marker, font=archive_font, fill=(20, 20, 20, 255))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "JPEG", quality=93, optimize=True, progressive=True)


def render_text_slide(story_id: str, slide: dict[str, str], index: int, output: Path, system: dict[str, Any]) -> None:
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    brand = system["brand"]
    safe = int(brand["safe_margin_px"])
    accent = tuple(brand["accent_rgb"])
    image = Image.new("RGB", canvas, (247, 246, 243))
    draw = ImageDraw.Draw(image)
    kicker = font(BOLD, 33)
    brand_font = font(BOLD, 27)
    body_font = font(REGULAR, 47)
    small = font(REGULAR, 25)

    draw.rounded_rectangle((safe, 76, safe + 92, 84), radius=4, fill=accent)
    draw.text((safe, 108), slide["kicker"], font=kicker, fill=(25, 25, 25))
    brand_text = str(brand["name"])
    bw = draw.textbbox((0, 0), brand_text, font=brand_font)[2]
    draw.text((canvas[0] - safe - bw, 108), brand_text, font=brand_font, fill=(70, 70, 70))

    lines = wrap(draw, slide["body"], body_font, canvas[0] - 2 * safe, 9)
    y = 300
    for line in lines:
        draw.text((safe, y), line, font=body_font, fill=(28, 28, 28))
        y += 66
    draw.text((safe, canvas[1] - 104), f"{index}  ·  valceaclar.ro", font=small, fill=(95, 95, 95))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=93, optimize=True, progressive=True)


def validate_plan(plan: dict[str, Any], system: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if plan.get("status") != "READY":
        return errors
    if len(str(plan.get("hook") or "").split()) > int(system["qa"]["headline_word_target_max"]):
        errors.append("headline_word_target_exceeded")
    if plan.get("native_format") == "carousel" and not 2 <= 1 + len(plan.get("detail_slides") or []) <= 6:
        errors.append("invalid_carousel_slide_count")
    if plan.get("editorial_note") and "arhiv" in str(plan.get("editorial_note")).lower() and not plan.get("archive_marker"):
        errors.append("archive_marker_missing")
    if not str(plan.get("product_fingerprint_sha256") or ""):
        errors.append("product_fingerprint_missing")
    return errors


def build() -> dict[str, Any]:
    system = load(SYSTEM)
    registry = load(VISUALS)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    plans: list[dict[str, Any]] = []
    for story in stories():
        story_id = str(story.get("id"))
        visual = visual_for(story_id, registry)
        ok, reason = approved_for_instagram(story, visual)
        if not ok:
            plans.append({"status": "HOLD", "story_id": story_id, "reason": reason, "headline": story.get("headline")})
            continue
        assert visual is not None
        plan = package(story, visual)
        errors = validate_plan(plan, system)
        if errors:
            plan["status"] = "HOLD"
            plan["reason"] = "visual_qa_failed"
            plan["qa_errors"] = errors
            plans.append(plan)
            continue
        cover = f"{story_id}-ig-v1-01-cover.jpg"
        render_cover(plan, PREVIEW / cover, system)
        files = [cover]
        for idx, slide in enumerate(plan.get("detail_slides") or [], start=2):
            name = f"{story_id}-ig-v1-{idx:02d}.jpg"
            render_text_slide(story_id, slide, idx, PREVIEW / name, system)
            files.append(name)
        plan["preview_files"] = files
        plan["slide_count"] = len(files)
        plans.append(plan)

    summary = {
        "schema_version": "1.0-preview",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "rendering_version": "instagram-editorial-v1.0",
        "canvas": system["canvas"],
        "plans": plans,
        "ready": sum(1 for p in plans if p.get("status") == "READY"),
        "held": sum(1 for p in plans if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def self_test() -> int:
    system = load(SYSTEM)
    assert system["canvas"] == {"width": 1080, "height": 1350, "aspect_ratio": "4:5"}
    thin = {"material_fact_gate": "PASS_DATE_ONLY", "headline": "X", "dek": "Y", "paragraphs": []}
    assert approved_for_instagram(thin, {"image": {"editor_approved": True, "subject_match": True, "synthetic": False}})[0] is False
    sample = {
        "id": "sample",
        "section": "INVESTIGAȚII",
        "headline": "Pod nou peste Olănești",
        "dek": "Urmărim documentele proiectului.",
        "paragraphs": [
            "Documentația include un nou pod exclusiv pietonal și ciclist.",
            "Proiectul are o valoare totală de 44.373.317,87 lei cu TVA.",
            "Nu atribuim lucrările vizibile unei firme fără documente suficiente.",
        ],
    }
    plan = package(sample, {"image_path": "x.jpg", "image": {"contextual_archive": True}})
    assert plan["native_format"] == "carousel"
    assert plan["hook"] == "44,37 mil. lei"
    assert len(plan["detail_slides"]) == 3
    assert not validate_plan(plan, system)
    print("VÂLCEA CLAR Instagram editorial v1 self-test: PASS")
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
