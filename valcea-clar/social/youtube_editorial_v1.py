#!/usr/bin/env python3
"""YouTube/Shorts editorial packaging v1.1 for VÂLCEA CLAR.

YouTube is a durable explainer publication. Strong stories may have a complete
source-preserving script/title package while remaining HOLD_MEDIA. READY is
possible only with a current real story-specific video package and a real poster
frame. A thumbnail is rendered only for READY video, never as a standalone
promise for a video that does not exist.
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
VIDEO_VISUALS = VC / "social" / "story_video_media.json"
PREVIEW = VC / "social" / "previews" / "youtube-v1"

SERIF_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
]
SANS_BOLD = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
]


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def visual_for(
    story_id: str,
    photo_registry: dict[str, Any],
    video_registry: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    merged: dict[str, Any] = {}
    photo_value = photo_registry.get("stories", {}).get(story_id)
    if isinstance(photo_value, dict):
        merged.update(photo_value)
    if isinstance(video_registry, dict):
        video_value = video_registry.get("stories", {}).get(story_id)
        if isinstance(video_value, dict):
            nested = video_value.get("video")
            merged["video"] = nested if isinstance(nested, dict) else video_value
    return merged or None


def editorial_gate(story: dict[str, Any]) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "").strip()
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "youtube_video_value_gate_thin_story"
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    if len(headline) + len(dek) + sum(len(p) for p in paragraphs[:3]) < 180:
        return False, "youtube_video_value_gate_insufficient_depth"
    return True, None


def approved_video(visual: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(visual, dict):
        return None, "real_story_specific_video_package_required"
    video = visual.get("video")
    if not isinstance(video, dict):
        image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
        if image.get("contextual_archive") is True:
            return None, "current_subject_video_or_visual_sequence_required"
        return None, "real_video_or_editorially_sufficient_visual_sequence_required"
    if video.get("kind") != "video" or video.get("synthetic") is not False:
        return None, "approved_real_video_required"
    if video.get("editor_approved") is not True:
        return None, "editor_approved_video_required"
    if video.get("subject_match") is not True:
        return None, "story_subject_match_video_required"
    if video.get("contextual_archive") is True:
        return None, "current_story_video_required"
    required = (
        "video_path", "poster_image_path", "source_type", "rights_basis", "credit", "alt_text"
    )
    missing = [key for key in required if not str(video.get(key) or "").strip()]
    if missing:
        return None, "video_package_metadata_missing:" + ",".join(missing)
    source_type = str(video.get("source_type") or "")
    if source_type not in {"staff", "official_press", "official_institution", "licensed_agency"}:
        return None, "youtube_video_source_type_not_approved"
    rights = str(video.get("rights_basis") or "")
    if rights not in {"owned", "written_permission", "press_use", "licensed", "official_reuse_permission"}:
        return None, "youtube_video_reuse_rights_missing"
    if source_type != "staff" and not str(video.get("source_url") or "").strip():
        return None, "youtube_external_video_source_url_missing"
    return video, None


def media_gate(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str]:
    video, reason = approved_video(visual)
    if video is not None:
        return True, "current_real_video_package_available"
    corpus = " ".join([
        str(story.get("headline") or ""), str(story.get("dek") or ""),
        *[str(p) for p in story.get("paragraphs", [])],
    ]).lower()
    if reason == "current_subject_video_or_visual_sequence_required" and "olănești" in corpus:
        return False, "current_site_video_or_visual_sequence_required"
    return False, str(reason or "real_story_specific_video_or_multi_asset_package_required")


def package(story: dict[str, Any], visual: dict[str, Any] | None) -> dict[str, Any]:
    story_id = str(story["id"])
    useful, editorial_reason = editorial_gate(story)
    media_ok, media_reason = media_gate(story, visual)
    video, _ = approved_video(visual)
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()
    section = str(story.get("section") or "ȘTIRI").replace("_", " ").upper()

    title = headline[:95]
    thumbnail = headline[:48]
    format_family = "short_explainer"
    if "luminos" in corpus and "zăvoi" in corpus:
        title = "Luminos Fest în Zăvoi: ce trebuie să știi înainte să mergi"
        thumbnail = "LUMINOS FEST ÎN ZĂVOI"
        format_family = "service_short"
    elif "olănești" in corpus:
        title = "44,37 mil. lei pe Olănești: ce se construiește lângă Omniasig"
        thumbnail = "44,37 MIL. LEI PE OLĂNEȘTI"
        format_family = "document_explainer"

    chapters = [
        {"role": "hook", "text": title},
        {"role": "what_happened", "text": dek or headline},
    ]
    for paragraph in paragraphs[:3]:
        chapters.append({"role": "verified_context", "text": paragraph})
    if "olănești" in corpus:
        chapters.extend([
            {"role": "document_fact", "text": "SMIS 334436 include un pod nou exclusiv pietonal și ciclist în zona Omniasig."},
            {"role": "uncertainty", "text": "Documentele consultate nu permit atribuirea exactă a lucrărilor vizibile unei firme anume din asociere sau subcontractanților."},
        ])
    chapters.append({"role": "source", "text": "VÂLCEA CLAR · valceaclar.ro — documentele și sursele sunt disponibile în articol."})

    status = "READY" if useful and media_ok else "HOLD_MEDIA" if useful else "HOLD"
    reason = None if status == "READY" else (media_reason if useful else editorial_reason)
    product = {
        "story_id": story_id,
        "status": status,
        "hold_reason": reason,
        "publication_mode": "preview_only",
        "native_format": "short" if format_family != "document_explainer" else "long_video",
        "format_family": format_family,
        "section": section,
        "title": title,
        "thumbnail_text": thumbnail,
        "chapters": chapters,
        "source_video_path": str(video.get("video_path")) if video else None,
        "poster_image_path": str(video.get("poster_image_path")) if video else None,
        "video_metadata": video if video else None,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "real_video_required": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "title_thumbnail_pair_required": True,
        "thumbnail_requires_ready_video": True,
        "truthful_thumbnail_required": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "identity": product_identity("youtube"),
        "rendering_version": "youtube-editorial-v1.1",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for raw in candidates:
        path = Path(raw)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    raise RuntimeError("No supported YouTube editorial font found")


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


def _draw_vc(draw: ImageDraw.ImageDraw, x: int, y: int, size: int, ink: tuple[int, ...], accent: tuple[int, ...]) -> None:
    fnt = _font(SERIF_BOLD, size)
    draw.text((x, y), "VC", font=fnt, fill=ink)
    advance = int(draw.textlength("VC", font=fnt))
    draw.text((x + advance, y), ".", font=fnt, fill=accent)


def render_thumbnail(product: dict[str, Any], poster: Path, output: Path) -> None:
    if product.get("status") != "READY":
        raise ValueError("YouTube thumbnail may only be rendered for READY real-video product")
    identity = product_identity("youtube")
    canvas = tuple(int(v) for v in identity["thumbnail"]["canvas"])
    common = load_system()["common"]
    paper = tuple(int(v) for v in common["paper_rgb"])
    ink = tuple(int(v) for v in common["ink_rgb"])
    accent = tuple(int(v) for v in common["accent_rgb"])
    white = tuple(int(v) for v in common["white_rgb"])

    image_h = 500
    frame = ImageEnhance.Contrast(_cover_crop(Image.open(poster), (canvas[0], image_h))).enhance(1.03)
    image = Image.new("RGB", canvas, paper)
    image.paste(frame, (0, 0))
    draw = ImageDraw.Draw(image)
    margin = 48

    # Quiet newsroom signature over the actual video frame; no badges/circles,
    # fake reactions or decorative arrows.
    shade = Image.new("RGBA", (canvas[0], 130), (0, 0, 0, 72))
    top = image.crop((0, 0, canvas[0], 130)).convert("RGBA")
    top = Image.alpha_composite(top, shade).convert("RGB")
    image.paste(top, (0, 0))
    draw = ImageDraw.Draw(image)
    _draw_vc(draw, margin, 40, 42, white, accent)
    section_font = _font(SANS_BOLD, 24)
    section = str(product.get("section") or "ȘTIRI")
    section_w = draw.textbbox((0, 0), section, font=section_font)[2]
    draw.text((canvas[0] - margin - section_w, 54), section, font=section_font, fill=white)

    band_y = image_h
    draw.rectangle((0, band_y, canvas[0], band_y + 4), fill=accent)
    text = str(product.get("thumbnail_text") or "").strip()
    headline_font = _font(SERIF_BOLD, 54)
    lines = _wrap(draw, text, headline_font, canvas[0] - 2 * margin, 2)
    y = band_y + 32
    for line in lines:
        draw.text((margin, y), line, font=headline_font, fill=ink)
        y += 65
    source_font = _font(SANS_BOLD, 19)
    draw.text((canvas[0] - margin - 265, 690), "valceaclar.ro", font=source_font, fill=(75, 75, 75), anchor="ls")

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=94, optimize=True, progressive=True, subsampling=0)


def build() -> dict[str, Any]:
    pointer = base.load(base.POINTER)
    snapshot = base.load(base.VC / str(pointer["json_source"]))
    decision = base.load(base.DECISION, {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"story_ids": []})
    photo_registry = base.load(VISUALS, {"stories": {}})
    video_registry = base.load(VIDEO_VISUALS, {"stories": {}})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [item for item in snapshot.get("items", []) if item.get("id") in allowed and base.story_ready(item)[0]]
    products = [
        package(story, visual_for(str(story["id"]), photo_registry, video_registry))
        for story in stories
    ]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    for product in products:
        if product.get("status") != "READY":
            continue
        video_path = ROOT / str(product.get("source_video_path") or "")
        poster = ROOT / str(product.get("poster_image_path") or "")
        if not video_path.is_file():
            product["status"] = "HOLD_MEDIA"
            product["hold_reason"] = "approved_video_file_not_available"
            continue
        if not poster.is_file():
            product["status"] = "HOLD_MEDIA"
            product["hold_reason"] = "approved_video_poster_frame_not_available"
            continue
        filename = f"{product['story_id']}-youtube-v1-1-thumb.jpg"
        render_thumbnail(product, poster, PREVIEW / filename)
        product["preview_file"] = filename
    manifest = {
        "schema_version": "1.1-preview",
        "platform": "youtube",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "rendering_version": "youtube-editorial-v1.1",
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "video_registry": "valcea-clar/social/story_video_media.json",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") != "READY"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    thin = {"id":"thin","headline":"Eveniment","dek":"15 august","paragraphs":[],"material_fact_gate":"PASS_DATE_ONLY"}
    assert package(thin, None)["status"] == "HOLD"
    deep = {
        "id":"deep",
        "section":"INFRASTRUCTURĂ",
        "headline":"Investiție locală documentată cu impact public clar",
        "dek":"Un proiect important, verificat în documente, cu efect direct asupra comunității și infrastructurii locale.",
        "paragraphs":[
            "Documentația publică descrie investiția, calendarul, obiectivele și principalele lucrări care trebuie realizate.",
            "Contractul și finanțarea sunt publice, iar valoarea și responsabilitățile actorilor pot fi explicate cititorilor.",
            "Impactul local este suficient de amplu pentru un explainer video, dar publicarea trebuie să aștepte imagini reale adecvate.",
        ],
        "material_fact_gate":"PASS",
    }
    current_image={"image":{"synthetic":False,"editor_approved":True,"subject_match":True,"contextual_archive":False}}
    held=package(deep,current_image)
    assert held["status"]=="HOLD_MEDIA"
    assert visual_for("missing", {"stories":{}}, {"stories":{}}) is None
    with tempfile.TemporaryDirectory() as raw:
        work=Path(raw)
        poster=work/"poster.jpg"
        video=work/"video.mp4"
        Image.new("RGB",(1600,900),(90,112,128)).save(poster,"JPEG",quality=92)
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 128)
        video_record={
            "video":{
                "kind":"video",
                "synthetic":False,
                "subject_match":True,
                "editor_approved":True,
                "contextual_archive":False,
                "video_path":str(video),
                "poster_image_path":str(poster),
                "source_type":"staff",
                "rights_basis":"owned",
                "credit":"VÂLCEA CLAR",
                "alt_text":"Cadru real de test din materialul video al subiectului.",
            }
        }
        merged=visual_for("deep", {"stories":{}}, {"stories":{"deep":video_record}})
        assert isinstance(merged,dict) and isinstance(merged.get("video"),dict)
        ready=package(deep,merged)
        assert ready["status"]=="READY"
        assert ready["thumbnail_requires_ready_video"] is True
        assert ready["identity"]["thumbnail"]["brand_mark"] == "VC."
        output=work/"thumbnail.jpg"
        render_thumbnail(ready,poster,output)
        with Image.open(output) as rendered:
            assert rendered.size==(1280,720)
        assert output.stat().st_size>20000
        archived=json.loads(json.dumps(merged))
        archived["video"]["contextual_archive"]=True
        assert package(deep,archived)["status"]=="HOLD_MEDIA"
        mismatch=json.loads(json.dumps(merged))
        mismatch["video"]["subject_match"]=False
        assert package(deep,mismatch)["status"]=="HOLD_MEDIA"
    print("VÂLCEA CLAR YouTube editorial v1.1 self-test: PASS")
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
