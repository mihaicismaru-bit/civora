#!/usr/bin/env python3
"""TikTok editorial packaging v1.1 for VÂLCEA CLAR.

TikTok is an audiovisual/vertical explainer publication, not a photo mirror. A
story can be editorially strong and still HOLD when current real media is
missing. When a current editor-approved story photograph exists, this module can
render a native 1080x1920 editorial photo product without fabricating motion or
obscuring the underlying evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageEnhance, ImageFont

import build_outbox_only_story_products as base
from native_identity import load_system, product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
VISUALS = VC / "social" / "story_visuals.json"
PREVIEW = VC / "social" / "previews" / "tiktok-v1"

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


def visual_for(story_id: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    value = registry.get("stories", {}).get(story_id)
    return value if isinstance(value, dict) else None


def utility_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "tiktok_motion_value_gate_thin_story"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    if len(headline) + len(dek) + sum(len(p) for p in paragraphs[:2]) < 140:
        return False, "tiktok_motion_value_gate_insufficient_context"
    return True, None


def media_gate(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(visual, dict):
        return False, "story_specific_real_media_required"
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    if image.get("synthetic") is not False or image.get("editor_approved") is not True:
        return False, "approved_real_media_required"
    if image.get("subject_match") is not True:
        return False, "story_subject_match_required"
    if image.get("contextual_archive") is True:
        corpus = " ".join([
            str(story.get("headline") or ""),
            str(story.get("dek") or ""),
            *[str(p) for p in story.get("paragraphs", [])],
        ]).lower()
        if "olănești" in corpus:
            return False, "current_site_photo_or_video_required"
        return False, "current_event_or_subject_media_required"
    if not str(visual.get("image_path") or "").strip():
        return False, "current_story_media_path_required"
    # Current real photography is acceptable for a native TikTok photo story.
    # We never manufacture motion from a still image.
    return True, "current_real_photo_available"


def package(story: dict[str, Any], visual: dict[str, Any] | None) -> dict[str, Any]:
    story_id = str(story["id"])
    useful, utility_reason = utility_gate(story)
    media_ok, media_reason = media_gate(story, visual)
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()

    hook = headline
    if "luminos" in corpus and "zăvoi" in corpus and "intrarea este liberă" in corpus:
        hook = "Azi în Zăvoi: intrarea este liberă"
    elif "olănești" in corpus:
        hook = "44,37 mil. lei. Ce se construiește pe Olănești?"

    storyboard = [
        {"beat": "0-2s", "purpose": "hook", "on_screen": hook},
        {"beat": "2-7s", "purpose": "verified_fact", "on_screen": dek or headline},
    ]
    if paragraphs:
        storyboard.append({"beat": "7-14s", "purpose": "context", "on_screen": paragraphs[0]})
    if "olănești" in corpus:
        storyboard.extend([
            {"beat": "14-20s", "purpose": "document_fact", "on_screen": "SMIS 334436: pod nou pietonal + ciclist în zona Omniasig"},
            {"beat": "20-27s", "purpose": "attribution_boundary", "on_screen": "Nu atribuim lucrările vizibile unei firme fără documente suficiente"},
        ])
    storyboard.append({"beat": "final", "purpose": "source", "on_screen": "VÂLCEA CLAR · valceaclar.ro"})

    status = "READY" if useful and media_ok else "HOLD_MEDIA" if useful else "HOLD"
    reason = None if status == "READY" else (media_reason if useful else utility_reason)
    product = {
        "story_id": story_id,
        "status": status,
        "hold_reason": reason,
        "publication_mode": "preview_only",
        "native_format": "single_photo" if status == "READY" else "short",
        "format_family": "photo_explainer" if status == "READY" else "visual_explainer",
        "section": section,
        "hook": hook,
        "storyboard": storyboard,
        "source_image_path": visual.get("image_path") if isinstance(visual, dict) else None,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "first_seconds_hook_required": True,
        "subtitles_required": True,
        "real_footage_preferred": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "music_dependency_required": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "identity": product_identity("tiktok"),
        "rendering_version": "tiktok-editorial-v1.1",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported TikTok editorial font found")


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


def _cover_crop(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    image = image.convert("RGB")
    target = size[0] / size[1]
    source = image.width / image.height
    if source > target:
        width = int(image.height * target)
        left = max(0, (image.width - width) // 2)
        image = image.crop((left, 0, left + width, image.height))
    else:
        height = int(image.width / target)
        top = max(0, (image.height - height) // 2)
        image = image.crop((0, top, image.width, top + height))
    return image.resize(size, Image.Resampling.LANCZOS)


def _draw_vc(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, ink: tuple[int, ...], accent: tuple[int, ...]) -> None:
    fnt = _font(SERIF_BOLD, size)
    draw.text((x, y), "VC", font=fnt, fill=ink)
    advance = int(draw.textlength("VC", font=fnt))
    draw.text((x + advance, y), ".", font=fnt, fill=accent)


def render_photo_story(product: dict[str, Any], source: Path, output: Path) -> None:
    if product.get("status") != "READY" or product.get("native_format") != "single_photo":
        raise ValueError("TikTok premium photo renderer requires READY single_photo product")
    identity = product_identity("tiktok")
    canvas = tuple(int(v) for v in identity["visual"]["master_canvas"])
    common = load_system()["common"]
    paper = tuple(int(v) for v in common["paper_rgb"])
    ink = tuple(int(v) for v in common["ink_rgb"])
    accent = tuple(int(v) for v in common["accent_rgb"])
    white = tuple(int(v) for v in common["white_rgb"])
    photo_h = 1180
    photo = ImageEnhance.Contrast(_cover_crop(Image.open(source), (canvas[0], photo_h))).enhance(1.03)
    image = Image.new("RGB", canvas, paper)
    image.paste(photo, (0, 0))

    # Quiet readability field for the newsroom mark only; story text stays off
    # the photograph so the primary evidence is not obscured.
    overlay = Image.new("RGBA", (canvas[0], photo_h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(0, 220):
        alpha = max(0, 90 - int(y * 0.35))
        od.line((0, y, canvas[0], y), fill=(0, 0, 0, alpha))
    top = Image.alpha_composite(photo.convert("RGBA"), overlay).convert("RGB")
    image.paste(top, (0, 0))
    draw = ImageDraw.Draw(image)
    margin = 74

    _draw_vc(draw, margin, 88, 46, white, accent)
    section_font = _font(SANS_BOLD, 23)
    section = str(product.get("section") or "ȘTIRI")
    section_w = draw.textbbox((0, 0), section, font=section_font)[2]
    draw.text((canvas[0] - margin - section_w, 102), section, font=section_font, fill=white)

    y = photo_h + 72
    draw.rounded_rectangle((margin, y, margin + 104, y + 8), radius=4, fill=accent)
    y += 48
    max_text_width = canvas[0] - margin - 160  # reserve right-side platform UI
    hook = str(product.get("hook") or "").strip()
    hook_font = None
    hook_lines: list[str] = []
    for size in range(76, 55, -2):
        candidate = _font(SERIF_BOLD, size)
        lines = _wrap(draw, hook, candidate, max_text_width, 2)
        if lines and "…" not in lines[-1]:
            hook_font = candidate
            hook_lines = lines
            break
    if hook_font is None:
        hook_font = _font(SERIF_BOLD, 56)
        hook_lines = _wrap(draw, hook, hook_font, max_text_width, 2)
    for line in hook_lines:
        draw.text((margin, y), line, font=hook_font, fill=ink)
        y += int(hook_font.size * 1.15)

    verified = ""
    for beat in product.get("storyboard", []) if isinstance(product.get("storyboard"), list) else []:
        if isinstance(beat, dict) and beat.get("purpose") == "verified_fact":
            verified = str(beat.get("on_screen") or "").strip()
            break
    if verified:
        y += 20
        sub_font = _font(SANS_REGULAR, 30)
        for line in _wrap(draw, verified, sub_font, max_text_width, 2):
            draw.text((margin, y), line, font=sub_font, fill=(55, 55, 55))
            y += 43

    footer_y = 1670
    draw.rectangle((margin, footer_y - 28, canvas[0] - 160, footer_y - 27), fill=(205, 203, 198))
    footer_font = _font(SANS_BOLD, 22)
    draw.text((margin, footer_y), "VÂLCEA CLAR · valceaclar.ro", font=footer_font, fill=(72, 72, 72))
    # Bottom ~190 px remain intentionally quiet for TikTok UI/caption overlap.
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


def build() -> dict[str, Any]:
    pointer = base.load(base.POINTER)
    snapshot = base.load(base.VC / str(pointer["json_source"]))
    decision = base.load(base.DECISION, {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"story_ids": []})
    registry = base.load(VISUALS, {"stories": {}})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [
        item for item in snapshot.get("items", [])
        if item.get("id") in allowed and base.story_ready(item)[0]
    ]
    products = [package(story, visual_for(str(story["id"]), registry)) for story in stories]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    for product in products:
        if product.get("status") != "READY":
            continue
        source_raw = str(product.get("source_image_path") or "")
        source = ROOT / source_raw
        if not source.is_file():
            product["status"] = "HOLD_MEDIA"
            product["hold_reason"] = "approved_current_photo_not_downloaded"
            continue
        filename = f"{product['story_id']}-tiktok-v1-1-photo.jpg"
        render_photo_story(product, source, PREVIEW / filename)
        product["preview_file"] = filename
    manifest = {
        "schema_version": "1.1-preview",
        "platform": "tiktok",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "rendering_version": "tiktok-editorial-v1.1",
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") != "READY"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    story = {
        "id": "test",
        "section": "INFRASTRUCTURĂ",
        "headline": "Lucrări locale importante",
        "dek": "O schimbare verificată pentru comunitate, explicată direct din documentele publice.",
        "paragraphs": [
            "Documentația publică explică proiectul, valoarea intervenției, calendarul și impactul local pentru locuitori."
        ],
        "material_fact_gate": "PASS",
    }
    with tempfile.TemporaryDirectory() as raw:
        source = Path(raw) / "current-photo.jpg"
        Image.new("RGB", (1500, 1100), (95, 120, 135)).save(source, "JPEG")
        current_visual = {
            "image_path": str(source),
            "image": {
                "synthetic": False,
                "editor_approved": True,
                "subject_match": True,
                "contextual_archive": False,
            },
        }
        product = package(story, current_visual)
        assert product["status"] == "READY"
        assert product["native_format"] == "single_photo"
        assert product["identity"]["channel_id"] == "valcea-tiktok"
        assert product["identity"]["visual"]["brand_mark"] == "VC."
        output = Path(raw) / "tiktok.jpg"
        render_photo_story(product, source, output)
        with Image.open(output) as rendered:
            assert rendered.size == (1080, 1920)
        assert output.stat().st_size > 30000
        archived = json.loads(json.dumps(current_visual))
        archived["image_path"] = "archive.jpg"
        archived["image"]["contextual_archive"] = True
        assert package(story, archived)["status"] == "HOLD_MEDIA"
        no_match = json.loads(json.dumps(current_visual))
        no_match["image"]["subject_match"] = False
        assert package(story, no_match)["hold_reason"] == "story_subject_match_required"
        thin = dict(story)
        thin["material_fact_gate"] = "PASS_DATE_ONLY"
        assert package(thin, current_visual)["status"] == "HOLD"
    print("VÂLCEA CLAR TikTok editorial v1.1 self-test: PASS")
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
