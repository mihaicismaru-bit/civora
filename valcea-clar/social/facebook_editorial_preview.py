#!/usr/bin/env python3
"""Preview-only Facebook editorial packaging for VÂLCEA CLAR.

Creates a Facebook-native hook, body and 4:5 visual from the verified story
kernel and approved media. No Meta calls are performed.
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
SYSTEM = VC / "social" / "facebook_visual_system.json"
PREVIEW = VC / "social" / "previews" / "facebook"
BASE = "https://valceaclar.ro"

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


def slug(story_id: str) -> str:
    value = re.sub(r"[^a-z0-9-]+", "-", story_id.lower())
    return re.sub(r"-+", "-", value).strip("-") or "story"


def canonical_link(story: dict[str, Any]) -> str:
    return f"{BASE}/stiri/{slug(str(story['id']))}/"


def interest_gate(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str | None]:
    gate = str(story.get("material_fact_gate") or "")
    if gate in {"PASS_DATE_ONLY", "PASS_TITLE_DATE_ONLY"}:
        return False, "thin_title_date_source_only"
    if not visual:
        return False, "no_approved_story_visual"
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    if image.get("editor_approved") is not True or image.get("subject_match") is not True:
        return False, "visual_not_editorially_ready"
    if image.get("synthetic") is not False:
        return False, "synthetic_visual_forbidden"
    return True, None


def amounts(text: str) -> list[str]:
    values = []
    for match in re.finditer(r"(?<!\d)(\d{1,3}(?:\.\d{3})+(?:,\d+)?)\s+lei\b", text, re.I):
        raw = match.group(1).replace(".", "").replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            continue
        shown = (
            f"{number / 1_000_000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " mil. lei"
            if number >= 1_000_000
            else f"{int(round(number)):,}".replace(",", ".") + " lei"
        )
        if shown not in values:
            values.append(shown)
    return values


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s*[—–-]\s*", " + ", value)
    return re.sub(r"\s+", " ", value).strip(" +") or None


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
    pair = contractor_pair(corpus)

    template = "fb_news_card"
    hook = truncate(headline, 100)
    visual_subline = truncate(dek, 105)
    body_parts = [hook, dek]
    cta = "Detaliile și sursele verificate sunt în articol."

    if section in {"EVENIMENTE", "CULTURĂ", "UNDE IEȘIM"}:
        template = "fb_event_utility"
        if "luminos" in lower and "zăvoi" in lower:
            hook = "Azi în Zăvoi: intrarea este liberă"
            visual_subline = "Luminos Fest · 15–16 august"
            body_parts = [
                hook + " la Luminos Fest.",
                "Evenimentul este dedicat familiilor, cu lampioane pe apă, ateliere creative, muzică și zonă handmade.",
                "Lampioanele plutitoare se rezervă separat, online.",
            ]
        elif "intrarea este liberă" in lower:
            visual_subline = "Intrarea este liberă"

    if section == "INVESTIGAȚII" or any(token in lower for token in ("contract", "atribuit", "execut", "smis")):
        template = "fb_investigation_card"
        if money and "olănești" in lower:
            hook = f"{money[0]} pentru proiectul de pe Olănești"
            visual_subline = "Pod pietonal-ciclist în zona Omniasig"
            actor = pair or "asocierea câștigătoare"
            contract_value = money[1] if len(money) > 1 else None
            body_parts = [
                hook + ".",
                "Documentația SMIS 334436 prevede un nou pod exclusiv pietonal și ciclist în zona de lângă Omniasig.",
                (f"Contractul principal a fost atribuit {actor}; valoarea atribuită este {contract_value} fără TVA." if contract_value else f"Contractul principal a fost atribuit {actor}."),
                "Nu atribuim lucrările vizibile unei anumite firme până când documentele publice nu permit această legătură. Nu există în acest moment o acuzație de neregulă.",
            ]
        elif money:
            hook = f"{money[0]}: {truncate(headline, 75)}"

    if any(token in lower for token in ("consiliul local", "buget", "bani publici", "finanț")) and money:
        template = "fb_public_money_card"
        hook = f"{money[0]}: {truncate(headline, 70)}"
        visual_subline = "Decizia și actorii, pe scurt"

    body = "\n\n".join(part for part in body_parts if part).strip() + "\n\n" + cta + "\n" + canonical_link(story)
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    plan = {
        "status": "READY",
        "story_id": str(story["id"]),
        "template_id": template,
        "section": section,
        "hook": hook,
        "visual_subline": visual_subline,
        "body": body,
        "cta": cta,
        "canonical_link": canonical_link(story),
        "archive_marker": "FOTO DE ARHIVĂ" if image.get("contextual_archive") else None,
        "editorial_note": image.get("editorial_note"),
        "source_image_path": visual.get("image_path"),
        "credit": image.get("credit"),
        "rights_basis": image.get("rights_basis"),
        "rendering_version": "facebook-editorial-v1.0",
    }
    plan["product_fingerprint_sha256"] = digest({k: v for k, v in plan.items() if k != "product_fingerprint_sha256"})
    return plan


def wrap(draw: ImageDraw.ImageDraw, text: str, fnt: ImageFont.FreeTypeFont, width: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines, current = [], ""
    for word in words:
        candidate = word if not current else current + " " + word
        if draw.textbbox((0, 0), candidate, font=fnt)[2] <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if len(lines) >= max_lines - 1:
                break
    used = sum(len(line.split()) for line in lines)
    rest = words[used:]
    if len(lines) < max_lines:
        last = " ".join(rest) if rest else current
        while draw.textbbox((0, 0), last, font=fnt)[2] > width and len(last) > 8:
            last = last[:-2].rstrip() + "…"
        lines.append(last)
    return lines[:max_lines]


def fit_hook(draw: ImageDraw.ImageDraw, text: str, width: int, system: dict[str, Any]) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    typo = system["typography"]
    for size in range(int(typo["hook_size_max"]), int(typo["hook_size_min"]) - 1, -2):
        fnt = font(BOLD, size)
        lines = wrap(draw, text, fnt, width, int(typo["hook_max_lines"]))
        if lines and "…" not in lines[-1]:
            return fnt, lines
    fnt = font(BOLD, int(typo["hook_size_min"]))
    return fnt, wrap(draw, text, fnt, width, int(typo["hook_max_lines"]))


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


def render(plan: dict[str, Any], output: Path, system: dict[str, Any]) -> None:
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    safe = int(system["brand"]["safe_margin_px"])
    accent = tuple(system["brand"]["accent_rgb"])
    paper = tuple(system["brand"]["paper_rgb"])
    photo_h = 850
    source = ROOT / str(plan["source_image_path"])
    if not source.is_file():
        raise RuntimeError(f"approved photograph missing: {source}")
    photo = ImageEnhance.Contrast(crop(Image.open(source), (canvas[0], photo_h))).enhance(1.03)
    image = Image.new("RGB", canvas, paper)
    image.paste(photo, (0, 0))
    draw = ImageDraw.Draw(image)

    if plan.get("archive_marker"):
        mark_font = font(BOLD, 24)
        marker = str(plan["archive_marker"])
        mw = draw.textbbox((0, 0), marker, font=mark_font)[2]
        draw.rounded_rectangle((safe, photo_h - 72, safe + mw + 28, photo_h - 26), radius=8, fill=(255, 255, 255))
        draw.text((safe + 14, photo_h - 65), marker, font=mark_font, fill=(24, 24, 24))

    draw.rectangle((0, photo_h, 14, canvas[1]), fill=accent)
    kicker = font(BOLD, int(system["typography"]["kicker_size"]))
    brand_font = font(BOLD, int(system["typography"]["brand_size"]))
    sub_font = font(REGULAR, int(system["typography"]["subline_size"]))
    draw.text((safe, photo_h + 54), plan["section"], font=kicker, fill=accent)
    brand_text = str(system["brand"]["name"])
    bw = draw.textbbox((0, 0), brand_text, font=brand_font)[2]
    draw.text((canvas[0] - safe - bw, photo_h + 58), brand_text, font=brand_font, fill=(75, 75, 75))

    width = canvas[0] - 2 * safe
    hook_font, hook_lines = fit_hook(draw, str(plan["hook"]), width, system)
    y = photo_h + 126
    for line in hook_lines:
        draw.text((safe, y), line, font=hook_font, fill=(24, 24, 24))
        y += int(hook_font.size * 1.1)
    y += 12
    sub_lines = wrap(draw, str(plan.get("visual_subline") or ""), sub_font, width, 2)
    for line in sub_lines:
        draw.text((safe, y), line, font=sub_font, fill=(67, 67, 67))
        y += 46
    draw.text((safe, canvas[1] - 56), "valceaclar.ro", font=brand_font, fill=(92, 92, 92))

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=93, optimize=True, progressive=True)


def validate(plan: dict[str, Any], system: dict[str, Any]) -> list[str]:
    errors = []
    if len(str(plan.get("hook") or "").split()) > int(system["qa"]["hook_word_target_max"]):
        errors.append("hook_word_target_exceeded")
    if not str(plan.get("canonical_link") or "").startswith("https://valceaclar.ro/stiri/"):
        errors.append("canonical_link_missing")
    if plan.get("editorial_note") and "arhiv" in str(plan.get("editorial_note")).lower() and not plan.get("archive_marker"):
        errors.append("archive_marker_missing")
    if "#" in str(plan.get("body") or ""):
        errors.append("mechanical_hashtag_footer_forbidden")
    return errors


def build() -> dict[str, Any]:
    system = load(SYSTEM)
    registry = load(VISUALS)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    plans = []
    for story in stories():
        story_id = str(story.get("id"))
        visual = visual_for(story_id, registry)
        ok, reason = interest_gate(story, visual)
        if not ok:
            plans.append({"status": "HOLD", "story_id": story_id, "reason": reason, "headline": story.get("headline")})
            continue
        assert visual is not None
        plan = package(story, visual)
        errors = validate(plan, system)
        if errors:
            plan["status"] = "HOLD"
            plan["reason"] = "facebook_qa_failed"
            plan["qa_errors"] = errors
            plans.append(plan)
            continue
        name = f"{story_id}-fb-v1.jpg"
        render(plan, PREVIEW / name, system)
        plan["preview_file"] = name
        plans.append(plan)
    manifest = {
        "schema_version": "1.0-preview",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "rendering_version": "facebook-editorial-v1.0",
        "canvas": system["canvas"],
        "plans": plans,
        "ready": sum(1 for p in plans if p.get("status") == "READY"),
        "held": sum(1 for p in plans if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    assert contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    thin = {"id": "x", "material_fact_gate": "PASS_DATE_ONLY"}
    assert interest_gate(thin, {"image": {"editor_approved": True, "subject_match": True, "synthetic": False}})[0] is False
    sample = {
        "id": "olanesti-test",
        "section": "INVESTIGAȚII",
        "headline": "Pod peste Olănești",
        "dek": "Proiect local.",
        "paragraphs": [
            "Proiectul SMIS 334436 include un pod pietonal-ciclist în zona Omniasig.",
            "Valoarea totală este 44.373.317,87 lei cu TVA. Contractul a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți, la 29.167.613,30 lei fără TVA.",
        ],
    }
    plan = package(sample, {"image_path": "x.jpg", "image": {"contextual_archive": True}})
    assert plan["hook"].startswith("44,37 mil. lei")
    assert "Ralunic + Dimex-2000 Company" in plan["body"]
    assert "#" not in plan["body"]
    print("VÂLCEA CLAR Facebook editorial preview self-test: PASS")
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
