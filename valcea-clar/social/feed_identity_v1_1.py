#!/usr/bin/env python3
"""Shared premium feed identity renderer for VÂLCEA CLAR Facebook + Instagram.

This module is deliberately presentation-only. It consumes the already verified
editorial plan and approved source media; it never selects stories, changes
facts, calls a network, or publishes. Facebook and Instagram share one newsroom
signature while retaining different native compositions.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

ROOT = Path(__file__).resolve().parents[2]
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


def font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported VÂLCEA CLAR feed font found")


def _rgb(value: Any) -> tuple[int, int, int]:
    if not isinstance(value, list) or len(value) != 3:
        raise ValueError(f"invalid RGB value: {value!r}")
    return tuple(int(v) for v in value)


def palette(system: dict[str, Any]) -> dict[str, tuple[int, int, int]]:
    brand = system["brand"]
    return {
        "accent": _rgb(brand["accent_rgb"]),
        "paper": _rgb(brand["paper_rgb"]),
        "ink": _rgb(brand["ink_rgb"]),
        "white": _rgb(brand["white_rgb"]),
    }


def crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    target = size[0] / size[1]
    source = image.width / image.height
    if source > target:
        width = int(image.height * target)
        left = (image.width - width) // 2
        image = image.crop((left, 0, left + width, image.height))
    else:
        height = int(image.width / target)
        top = (image.height - height) // 2
        image = image.crop((0, top, image.width, top + height))
    return image.resize(size, Image.Resampling.LANCZOS)


def wrap(
    draw: ImageDraw.ImageDraw,
    text: str,
    fnt: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    words = str(text).split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    index = 0
    while index < len(words):
        word = words[index]
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= max_width:
            current = candidate
            index += 1
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines - 1:
                break
            continue
        # A single long token: trim it rather than overflowing the canvas.
        trimmed = word
        while draw.textbbox((0, 0), trimmed + "…", font=fnt)[2] > max_width and len(trimmed) > 4:
            trimmed = trimmed[:-1]
        lines.append(trimmed.rstrip() + "…")
        index += 1
        if len(lines) >= max_lines:
            return lines[:max_lines]

    if len(lines) < max_lines:
        remainder = ([current] if current else []) + words[index:]
        last = " ".join(remainder).strip()
        if last:
            overflowed = False
            while draw.textbbox((0, 0), last, font=fnt)[2] > max_width and len(last) > 8:
                overflowed = True
                last = last[:-1].rstrip()
            if overflowed:
                last = last.rstrip(" ,.;:") + "…"
            lines.append(last)
    return lines[:max_lines]


def fit_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    max_width: int,
    max_lines: int,
    max_size: int,
    min_size: int,
    candidates: list[str] = SERIF_BOLD,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    for size in range(max_size, min_size - 1, -2):
        fnt = font(candidates, size)
        lines = wrap(draw, text, fnt, max_width, max_lines)
        if lines and "…" not in lines[-1]:
            return fnt, lines
    fnt = font(candidates, min_size)
    return fnt, wrap(draw, text, fnt, max_width, max_lines)


def draw_vc_mark(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    *,
    size: int,
    foreground: tuple[int, int, int] | str,
    accent: tuple[int, int, int],
) -> int:
    """Draw `VC.` with a typographic red period on the same baseline."""
    fnt = font(SERIF_BOLD, size)
    x, y = xy
    draw.text((x, y), "VC", font=fnt, fill=foreground)
    advance = int(round(float(draw.textlength("VC", font=fnt))))
    draw.text((x + advance, y), ".", font=fnt, fill=accent)
    return int(round(float(draw.textlength("VC.", font=fnt))))


def _archive_disclosure(
    draw: ImageDraw.ImageDraw,
    marker: str,
    *,
    x: int,
    y: int,
    foreground: tuple[int, int, int],
    background: tuple[int, int, int],
) -> None:
    fnt = font(SANS_BOLD, 22)
    box = draw.textbbox((0, 0), marker, font=fnt)
    width = box[2] - box[0]
    draw.rectangle((x, y, x + width + 28, y + 42), fill=background)
    draw.text((x + 14, y + 7), marker, font=fnt, fill=foreground)


def render_facebook(plan: dict[str, Any], output: Path, system: dict[str, Any]) -> None:
    """Facebook: contextual photo + spacious paper news brief."""
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    colors = palette(system)
    safe = int(system["brand"]["safe_margin_px"])
    source = ROOT / str(plan["source_image_path"])
    if not source.is_file():
        raise RuntimeError(f"approved photograph missing: {source}")

    photo_h = int(round(canvas[1] * 0.55))
    photo = ImageEnhance.Contrast(crop(Image.open(source), (canvas[0], photo_h))).enhance(1.03)
    image = Image.new("RGB", canvas, colors["paper"])
    image.paste(photo, (0, 0))
    draw = ImageDraw.Draw(image)

    if plan.get("archive_marker"):
        _archive_disclosure(
            draw,
            str(plan["archive_marker"]),
            x=safe,
            y=photo_h - 62,
            foreground=colors["ink"],
            background=colors["white"],
        )

    # The paper band mirrors the profile masthead grammar: short red locator,
    # typographic VC., a restrained section label and an editorial hairline.
    locator_y = photo_h + 44
    draw.rectangle((safe, locator_y, safe + 74, locator_y + 5), fill=colors["accent"])
    row_y = locator_y + 24
    mark_w = draw_vc_mark(draw, (safe, row_y), size=31, foreground=colors["ink"], accent=colors["accent"])
    section_font = font(SANS_BOLD, 24)
    section = str(plan.get("section") or "ȘTIRI")
    draw.text((safe + mark_w + 28, row_y + 7), section, font=section_font, fill=colors["ink"])
    domain_font = font(SANS_BOLD, 22)
    domain = "valceaclar.ro"
    domain_w = draw.textbbox((0, 0), domain, font=domain_font)[2]
    draw.text((canvas[0] - safe - domain_w, row_y + 9), domain, font=domain_font, fill=(82, 82, 82))

    hairline_y = row_y + 58
    draw.rectangle((safe, hairline_y, canvas[0] - safe, hairline_y + 1), fill=(96, 96, 96))

    max_width = canvas[0] - 2 * safe
    typo = system["typography"]
    hook_font, hook_lines = fit_lines(
        draw,
        str(plan.get("hook") or ""),
        max_width=max_width,
        max_lines=int(typo["hook_max_lines"]),
        max_size=int(typo["hook_size_max"]),
        min_size=int(typo["hook_size_min"]),
    )
    y = hairline_y + 40
    line_height = int(hook_font.size * 1.12)
    for line in hook_lines:
        draw.text((safe, y), line, font=hook_font, fill=colors["ink"])
        y += line_height

    subline = str(plan.get("visual_subline") or "").strip()
    if subline:
        y += 16
        sub_font = font(SANS_REGULAR, int(typo["subline_size"]))
        sub_lines = wrap(draw, subline, sub_font, max_width, 2)
        for line in sub_lines:
            draw.text((safe, y), line, font=sub_font, fill=(66, 66, 66))
            y += int(sub_font.size * 1.32)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


def _bottom_readability_overlay(canvas: tuple[int, int]) -> Image.Image:
    overlay = Image.new("RGBA", canvas, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    start = int(canvas[1] * 0.48)
    for y in range(start, canvas[1]):
        progress = (y - start) / max(1, canvas[1] - start)
        alpha = int(8 + 215 * (progress ** 1.35))
        draw.line((0, y, canvas[0], y), fill=(0, 0, 0, alpha))
    # Small top veil only to keep the newsroom locator legible over bright sky.
    top_end = int(canvas[1] * 0.14)
    for y in range(top_end):
        progress = 1 - (y / max(1, top_end))
        alpha = int(72 * progress)
        draw.line((0, y, canvas[0], y), fill=(0, 0, 0, alpha))
    return overlay


def render_instagram_cover(plan: dict[str, Any], output: Path, system: dict[str, Any]) -> None:
    """Instagram: image-dominant cover with a quiet newsroom locator."""
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    colors = palette(system)
    safe = int(system["brand"]["safe_margin_px"])
    source = ROOT / str(plan["source_image_path"])
    if not source.is_file():
        raise RuntimeError(f"approved photograph missing: {source}")

    photo = ImageEnhance.Contrast(crop(Image.open(source), canvas)).enhance(1.03)
    image = Image.alpha_composite(photo.convert("RGBA"), _bottom_readability_overlay(canvas))
    draw = ImageDraw.Draw(image)

    top = int(system["brand"].get("top_margin_px", 64))
    draw_vc_mark(draw, (safe, top), size=30, foreground=colors["white"], accent=colors["accent"])
    section_font = font(SANS_BOLD, 24)
    section = str(plan.get("section") or "ȘTIRI")
    section_w = draw.textbbox((0, 0), section, font=section_font)[2]
    draw.text((canvas[0] - safe - section_w, top + 6), section, font=section_font, fill=colors["white"])

    max_width = canvas[0] - 2 * safe
    typo = system["typography"]
    headline_font, headline_lines = fit_lines(
        draw,
        str(plan.get("hook") or ""),
        max_width=max_width,
        max_lines=int(typo["headline_max_lines"]),
        max_size=int(typo["headline_size_max"]),
        min_size=int(typo["headline_size_min"]),
    )
    sub_font = font(SANS_REGULAR, int(typo["subline_size"]))
    sub_lines = wrap(draw, str(plan.get("subline") or ""), sub_font, max_width, 2)
    line_h = int(headline_font.size * 1.10)
    sub_h = int(sub_font.size * 1.28)
    block_h = len(headline_lines) * line_h + (18 + len(sub_lines) * sub_h if sub_lines else 0)
    bottom = int(system["brand"].get("bottom_margin_px", 72))
    y = canvas[1] - bottom - block_h - 24

    # One short locator rule, not a badge or template chip.
    draw.rectangle((safe, y - 30, safe + 70, y - 25), fill=colors["accent"])
    for line in headline_lines:
        draw.text((safe, y), line, font=headline_font, fill=colors["white"])
        y += line_h
    if sub_lines:
        y += 12
        for line in sub_lines:
            draw.text((safe, y), line, font=sub_font, fill=(242, 242, 242))
            y += sub_h

    if plan.get("archive_marker"):
        _archive_disclosure(
            draw,
            str(plan["archive_marker"]),
            x=safe,
            y=top + 54,
            foreground=colors["ink"],
            background=colors["white"],
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


def render_instagram_text_slide(
    slide: dict[str, str],
    index: int,
    output: Path,
    system: dict[str, Any],
) -> None:
    """Instagram carousel text card aligned to the v1.1 profile masthead grid."""
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    colors = palette(system)
    safe = int(system["brand"]["safe_margin_px"])
    image = Image.new("RGB", canvas, colors["paper"])
    draw = ImageDraw.Draw(image)

    top = 82
    mark_w = draw_vc_mark(draw, (safe, top), size=31, foreground=colors["ink"], accent=colors["accent"])
    kicker_font = font(SANS_BOLD, 25)
    kicker = str(slide.get("kicker") or "PE SCURT")
    kicker_w = draw.textbbox((0, 0), kicker, font=kicker_font)[2]
    draw.text((canvas[0] - safe - kicker_w, top + 8), kicker, font=kicker_font, fill=colors["ink"])

    hairline_y = top + 62
    draw.rectangle((safe, hairline_y, canvas[0] - safe, hairline_y + 1), fill=(96, 96, 96))
    draw.rectangle((safe, hairline_y - 1, safe + min(72, mark_w), hairline_y + 4), fill=colors["accent"])

    lead = str(slide.get("lead") or "").strip()
    lead_font, lead_lines = fit_lines(
        draw,
        lead,
        max_width=canvas[0] - 2 * safe,
        max_lines=3,
        max_size=70,
        min_size=54,
    )
    y = hairline_y + 82
    for line in lead_lines:
        draw.text((safe, y), line, font=lead_font, fill=colors["ink"])
        y += int(lead_font.size * 1.14)

    y += 46
    body_font = font(SANS_REGULAR, 37)
    body_lines = wrap(draw, str(slide.get("body") or ""), body_font, canvas[0] - 2 * safe, 8)
    for line in body_lines:
        draw.text((safe, y), line, font=body_font, fill=(47, 47, 47))
        y += int(body_font.size * 1.42)

    footer_font = font(SANS_REGULAR, 22)
    page = f"{index}"
    domain = "valceaclar.ro"
    domain_w = draw.textbbox((0, 0), domain, font=footer_font)[2]
    footer_y = canvas[1] - 82
    draw.text((safe, footer_y), page, font=footer_font, fill=(92, 92, 92))
    draw.text((canvas[0] - safe - domain_w, footer_y), domain, font=footer_font, fill=(92, 92, 92))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


def self_test() -> int:
    system_fb = {
        "canvas": {"width": 1200, "height": 1500},
        "brand": {
            "safe_margin_px": 76,
            "accent_rgb": [196, 27, 35],
            "paper_rgb": [247, 246, 243],
            "ink_rgb": [20, 20, 20],
            "white_rgb": [255, 255, 255],
        },
        "typography": {
            "hook_max_lines": 3,
            "hook_size_max": 68,
            "hook_size_min": 52,
            "subline_size": 32,
        },
    }
    system_ig = {
        "canvas": {"width": 1080, "height": 1350},
        "brand": {
            "safe_margin_px": 72,
            "top_margin_px": 64,
            "bottom_margin_px": 72,
            "accent_rgb": [196, 27, 35],
            "paper_rgb": [247, 246, 243],
            "ink_rgb": [20, 20, 20],
            "white_rgb": [255, 255, 255],
        },
        "typography": {
            "headline_max_lines": 3,
            "headline_size_max": 78,
            "headline_size_min": 60,
            "subline_size": 34,
        },
    }
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        photo = tmp / "photo.jpg"
        Image.new("RGB", (1600, 1200), (135, 150, 160)).save(photo, "JPEG")
        relative = photo.relative_to(Path(raw))
        # Render functions resolve source paths against repo root, so exercise
        # the purely typographic carousel directly and the shared mark here.
        card = tmp / "card.jpg"
        render_instagram_text_slide(
            {"kicker": "CE ȘTIM", "lead": "Un fapt local verificat", "body": "Contextul rămâne scurt, clar și atribuit."},
            2,
            card,
            system_ig,
        )
        assert card.is_file() and card.stat().st_size > 10_000
        mark = Image.new("RGB", (300, 120), (247, 246, 243))
        draw = ImageDraw.Draw(mark)
        assert draw_vc_mark(draw, (20, 20), size=44, foreground=(20, 20, 20), accent=(196, 27, 35)) > 50
        assert palette(system_fb)["accent"] == (196, 27, 35)
        assert str(relative) == "photo.jpg"
    print("VÂLCEA CLAR premium feed identity v1.1 self-test: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
