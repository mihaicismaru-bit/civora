#!/usr/bin/env python3
"""Render deterministic premium identity proofs for LinkedIn, TikTok and YouTube.

These are DESIGN PREVIEWS, not publishable story media. They prove that the
canonical VÂLCEA CLAR identity can produce platform-native visual products
without fabricating photography or weakening real-media publication gates.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from native_identity import load_system, product_identity

ROOT = Path(__file__).resolve().parents[2]
SOCIAL = ROOT / "valcea-clar" / "social"
OUTPUT = SOCIAL / "previews" / "native-identity-v1"

SERIF_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
SANS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
]
SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]

FIXTURE = {
    "fixture_id": "design-proof-olanesti",
    "publication_allowed": False,
    "kicker": "BANI PUBLICI",
    "amount": "44,37 mil. lei",
    "headline": "Ce se construiește pe Olănești",
    "subline": "Proiectul include un pod nou pietonal și ciclist în zona Omniasig.",
    "fact_1": "SMIS 334436",
    "fact_2": "Contract principal: 29,17 mil. lei fără TVA",
    "fact_3": "Executantul exact al lucrărilor vizibile nu este atribuit fără documente suficiente.",
    "source": "valceaclar.ro",
}


def font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported font found")


def palette() -> dict[str, tuple[int, int, int]]:
    common = load_system()["common"]
    return {
        "accent": tuple(common["accent_rgb"]),
        "paper": tuple(common["paper_rgb"]),
        "ink": tuple(common["ink_rgb"]),
        "white": tuple(common["white_rgb"]),
        "muted": (96, 96, 96),
        "soft": (224, 222, 216),
    }


def text_width(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont) -> int:
    box = draw.textbbox((0, 0), text, font=fnt)
    return box[2] - box[0]


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, max_width: int, max_lines: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if not current or text_width(draw, candidate, fnt) <= max_width:
            current = candidate
            continue
        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    consumed = " ".join(lines)
    if len(consumed.split()) < len(words) and lines:
        while text_width(draw, lines[-1] + "…", fnt) > max_width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] = lines[-1].rstrip(" ,.;:") + "…"
    return lines


def fit_font(draw: ImageDraw.ImageDraw, text: str, candidates: list[str], max_width: int, max_size: int, min_size: int) -> ImageFont.FreeTypeFont:
    for size in range(max_size, min_size - 1, -2):
        fnt = font(candidates, size)
        if text_width(draw, text, fnt) <= max_width:
            return fnt
    return font(candidates, min_size)


def masthead(draw: ImageDraw.ImageDraw, *, x: int, y: int, width: int, height: int, p: dict[str, tuple[int, int, int]], dark: bool = False) -> None:
    ink = p["white"] if dark else p["ink"]
    brand = font(SERIF_BOLD, max(24, round(height * 0.055)))
    draw.rectangle((x, y, x + max(54, round(width * 0.09)), y + max(5, round(height * 0.008))), fill=p["accent"])
    draw.text((x, y + round(height * 0.025)), "VÂLCEA CLAR", font=brand, fill=ink)


def footer(draw: ImageDraw.ImageDraw, *, canvas: tuple[int, int], margin: int, p: dict[str, tuple[int, int, int]], dark: bool = False) -> None:
    ink = p["white"] if dark else p["ink"]
    fnt = font(SANS_BOLD, max(18, round(canvas[1] * 0.025)))
    text = "VÂLCEA CLAR · valceaclar.ro"
    draw.text((margin, canvas[1] - margin - fnt.size), text, font=fnt, fill=ink)


def linkedin_portrait(path: Path) -> None:
    identity = product_identity("linkedin")
    canvas = tuple(identity["visual"]["portrait_card_canvas"])
    p = palette()
    image = Image.new("RGB", canvas, p["paper"])
    draw = ImageDraw.Draw(image)
    margin = 76
    masthead(draw, x=margin, y=margin, width=canvas[0] - 2 * margin, height=canvas[1], p=p)
    kicker = font(SANS_BOLD, 26)
    draw.text((margin, 250), FIXTURE["kicker"], font=kicker, fill=p["accent"])
    amount_font = fit_font(draw, FIXTURE["amount"], SERIF_BOLD, canvas[0] - 2 * margin, 116, 78)
    draw.text((margin, 310), FIXTURE["amount"], font=amount_font, fill=p["ink"])
    headline_font = font(SERIF_BOLD, 58)
    y = 470
    for line in wrap(draw, FIXTURE["headline"], headline_font, canvas[0] - 2 * margin, 3):
        draw.text((margin, y), line, font=headline_font, fill=p["ink"])
        y += 76
    sub_font = font(SANS, 31)
    y += 20
    for line in wrap(draw, FIXTURE["subline"], sub_font, canvas[0] - 2 * margin, 4):
        draw.text((margin, y), line, font=sub_font, fill=(52, 52, 52))
        y += 45
    y += 42
    draw.line((margin, y, canvas[0] - margin, y), fill=p["soft"], width=2)
    y += 36
    fact_font = font(SANS, 25)
    for fact in (FIXTURE["fact_1"], FIXTURE["fact_2"], FIXTURE["fact_3"]):
        draw.ellipse((margin, y + 10, margin + 9, y + 19), fill=p["accent"])
        lines = wrap(draw, fact, fact_font, canvas[0] - 2 * margin - 30, 3)
        for line in lines:
            draw.text((margin + 28, y), line, font=fact_font, fill=p["ink"])
            y += 36
        y += 22
    footer(draw, canvas=canvas, margin=margin, p=p)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=94, optimize=True, progressive=True)


def linkedin_landscape(path: Path) -> None:
    identity = product_identity("linkedin")
    canvas = tuple(identity["visual"]["landscape_card_canvas"])
    p = palette()
    image = Image.new("RGB", canvas, p["paper"])
    draw = ImageDraw.Draw(image)
    margin = 60
    masthead(draw, x=margin, y=42, width=canvas[0] - 2 * margin, height=canvas[1], p=p)
    kicker = font(SANS_BOLD, 22)
    draw.text((margin, 150), FIXTURE["kicker"], font=kicker, fill=p["accent"])
    amount_font = fit_font(draw, FIXTURE["amount"], SERIF_BOLD, 520, 84, 62)
    draw.text((margin, 188), FIXTURE["amount"], font=amount_font, fill=p["ink"])
    headline_font = font(SERIF_BOLD, 42)
    y = 315
    for line in wrap(draw, FIXTURE["headline"], headline_font, 520, 2):
        draw.text((margin, y), line, font=headline_font, fill=p["ink"])
        y += 53
    divider = 655
    draw.line((divider, 142, divider, 510), fill=p["soft"], width=2)
    fact_font = font(SANS, 24)
    y = 170
    for fact in (FIXTURE["fact_1"], FIXTURE["fact_2"], FIXTURE["fact_3"]):
        draw.ellipse((divider + 46, y + 8, divider + 54, y + 16), fill=p["accent"])
        lines = wrap(draw, fact, fact_font, 430, 3)
        for line in lines:
            draw.text((divider + 72, y), line, font=fact_font, fill=p["ink"])
            y += 34
        y += 22
    footer(draw, canvas=canvas, margin=margin, p=p)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=94, optimize=True, progressive=True)


def tiktok_first_frame(path: Path) -> None:
    identity = product_identity("tiktok")
    canvas = tuple(identity["visual"]["master_canvas"])
    p = palette()
    image = Image.new("RGB", canvas, p["ink"])
    draw = ImageDraw.Draw(image)
    margin = 76
    masthead(draw, x=margin, y=100, width=canvas[0] - 2 * margin, height=canvas[1], p=p, dark=True)
    kicker = font(SANS_BOLD, 30)
    draw.text((margin, 420), FIXTURE["kicker"], font=kicker, fill=p["accent"])
    amount_font = fit_font(draw, FIXTURE["amount"], SERIF_BOLD, canvas[0] - 2 * margin, 112, 82)
    draw.text((margin, 500), FIXTURE["amount"], font=amount_font, fill=p["white"])
    question = "Ce se construiește\npe Olănești?"
    q_font = font(SERIF_BOLD, 72)
    y = 680
    for line in question.splitlines():
        draw.text((margin, y), line, font=q_font, fill=p["white"])
        y += 94
    context_font = font(SANS, 31)
    y += 52
    for line in wrap(draw, "În 20 de secunde: proiectul, banii și ce nu putem atribui încă.", context_font, canvas[0] - 2 * margin, 4):
        draw.text((margin, y), line, font=context_font, fill=(220, 220, 220))
        y += 46
    label_font = font(SANS_BOLD, 24)
    draw.rounded_rectangle((margin, 1440, canvas[0] - margin, 1530), radius=16, outline=(92, 92, 92), width=2)
    draw.text((margin + 28, 1468), "INTRO CARD · urmează media reală a subiectului", font=label_font, fill=(180, 180, 180))
    footer(draw, canvas=canvas, margin=margin, p=p, dark=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=94, optimize=True, progressive=True)


def youtube_thumbnail(path: Path) -> None:
    identity = product_identity("youtube")
    canvas = tuple(identity["thumbnail"]["canvas"])
    p = palette()
    image = Image.new("RGB", canvas, p["paper"])
    draw = ImageDraw.Draw(image)
    margin = 56
    masthead(draw, x=margin, y=42, width=canvas[0] - 2 * margin, height=canvas[1], p=p)
    kicker = font(SANS_BOLD, 22)
    draw.text((margin, 165), "DOCUMENTE · BANI PUBLICI", font=kicker, fill=p["accent"])
    amount_font = fit_font(draw, "44,37", SERIF_BOLD, 550, 150, 110)
    draw.text((margin, 205), "44,37", font=amount_font, fill=p["ink"])
    mil = font(SANS_BOLD, 46)
    draw.text((margin + 20, 385), "MIL. LEI", font=mil, fill=p["accent"])
    divider = 650
    draw.line((divider, 165, divider, 570), fill=p["soft"], width=3)
    place = font(SANS_BOLD, 30)
    draw.text((divider + 58, 190), "OLĂNEȘTI", font=place, fill=p["accent"])
    headline_font = font(SERIF_BOLD, 55)
    y = 245
    for line in wrap(draw, "Ce se construiește lângă Omniasig", headline_font, 500, 4):
        draw.text((divider + 58, y), line, font=headline_font, fill=p["ink"])
        y += 68
    source = font(SANS_BOLD, 20)
    draw.text((divider + 58, 565), "VÂLCEA CLAR · valceaclar.ro", font=source, fill=p["ink"])
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "JPEG", quality=95, optimize=True, progressive=True)


def build(output: Path = OUTPUT) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    assets = {
        "linkedin-portrait": output / "linkedin-evidence-portrait-1200x1500.jpg",
        "linkedin-landscape": output / "linkedin-evidence-landscape-1200x627.jpg",
        "tiktok-first-frame": output / "tiktok-first-frame-1080x1920.jpg",
        "youtube-thumbnail": output / "youtube-thumbnail-1280x720.jpg",
    }
    linkedin_portrait(assets["linkedin-portrait"])
    linkedin_landscape(assets["linkedin-landscape"])
    tiktok_first_frame(assets["tiktok-first-frame"])
    youtube_thumbnail(assets["youtube-thumbnail"])
    records = []
    for asset_id, path in assets.items():
        with Image.open(path) as image:
            size = image.size
        records.append({"asset_id": asset_id, "file": path.name, "width": size[0], "height": size[1], "bytes": path.stat().st_size})
    manifest = {
        "schema_version": "1.0-preview",
        "product": "VÂLCEA CLAR Native Visual Identity Proofs",
        "execution_mode": "DESIGN_PREVIEW_ONLY_NOT_FOR_PUBLICATION",
        "fixture": FIXTURE,
        "fixture_publication_allowed": False,
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "media_policy": "no_fabricated_photo_or_video",
        "assets": records,
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    with tempfile.TemporaryDirectory() as raw:
        manifest = build(Path(raw))
        records = {row["asset_id"]: row for row in manifest["assets"]}
        assert manifest["fixture_publication_allowed"] is False
        assert manifest["media_policy"] == "no_fabricated_photo_or_video"
        assert (records["linkedin-portrait"]["width"], records["linkedin-portrait"]["height"]) == (1200, 1500)
        assert (records["linkedin-landscape"]["width"], records["linkedin-landscape"]["height"]) == (1200, 627)
        assert (records["tiktok-first-frame"]["width"], records["tiktok-first-frame"]["height"]) == (1080, 1920)
        assert (records["youtube-thumbnail"]["width"], records["youtube-thumbnail"]["height"]) == (1280, 720)
        assert all(row["bytes"] > 18_000 for row in records.values())
    print("VÂLCEA CLAR native visual identity previews self-test: PASS")
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
