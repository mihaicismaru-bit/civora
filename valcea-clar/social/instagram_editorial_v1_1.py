#!/usr/bin/env python3
"""Instagram editorial v1.1: stronger hierarchy and shorter explainer slides."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

import instagram_editorial_v1 as base

PREVIEW = base.VC / "social" / "previews" / "instagram-v1-1"


def contractor_pair(text: str) -> str | None:
    match = re.search(r"asocierii\s+(.+?)(?:,\s+cu\s+subcontractan|;|\.)", text, re.I)
    if not match:
        return None
    value = " ".join(match.group(1).split())
    value = re.sub(r"\bSRL\b", "", value, flags=re.I)
    value = re.sub(r"\s*[—–-]\s*", " + ", value)
    value = re.sub(r"\s+", " ", value).strip(" +")
    return value or None


def package(story: dict[str, Any], visual: dict[str, Any]) -> dict[str, Any]:
    plan = base.package(story, visual)
    if plan.get("template_id") != "investigation_card":
        plan["rendering_version"] = "instagram-editorial-v1.1"
        plan["product_fingerprint_sha256"] = base.digest({k: v for k, v in plan.items() if k != "product_fingerprint_sha256"})
        return plan

    headline = str(story.get("headline") or "")
    dek = str(story.get("dek") or "")
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs])
    money = base.amounts(corpus)
    pair = contractor_pair(corpus)

    if "olănești" in corpus.lower() and len(paragraphs) >= 3:
        plan["detail_slides"] = [
            {
                "kicker": "CE SE CONSTRUIEȘTE",
                "lead": "Un pod nou",
                "body": "Exclusiv pietonal și ciclist, în zona de lângă Omniasig. Proiectul este parte din SMIS 334436.",
            },
            {
                "kicker": "CINE A CÂȘTIGAT",
                "lead": pair or "Ralunic + Dimex-2000 Company",
                "body": (
                    f"Contract principal: {money[1]} fără TVA. Valoarea totală aprobată a proiectului: {money[0]} cu TVA."
                    if len(money) > 1 else base.truncate(paragraphs[1], 210)
                ),
            },
            {
                "kicker": "CE NU ȘTIM ÎNCĂ",
                "lead": "Cine execută exact lucrările vizibile",
                "body": "Documentele publice nu permit încă atribuirea lor unei anumite firme din asociere sau unui subcontractant. Nu există în acest moment o acuzație de neregulă.",
            },
        ]
    else:
        refined = []
        for slide in plan.get("detail_slides") or []:
            body = str(slide.get("body") or "")
            first = body.split(".", 1)[0].strip()
            refined.append({
                "kicker": str(slide.get("kicker") or "PE SCURT"),
                "lead": base.truncate(first, 82),
                "body": base.truncate(body[len(first):].lstrip(". "), 190) or base.truncate(body, 190),
            })
        plan["detail_slides"] = refined

    plan["rendering_version"] = "instagram-editorial-v1.1"
    plan["product_fingerprint_sha256"] = base.digest({k: v for k, v in plan.items() if k != "product_fingerprint_sha256"})
    return plan


def render_text_slide(slide: dict[str, str], index: int, output: Path, system: dict[str, Any]) -> None:
    canvas = (int(system["canvas"]["width"]), int(system["canvas"]["height"]))
    brand = system["brand"]
    safe = int(brand["safe_margin_px"])
    accent = tuple(brand["accent_rgb"])
    image = Image.new("RGB", canvas, (247, 246, 243))
    draw = ImageDraw.Draw(image)

    kicker_font = base.font(base.BOLD, 31)
    brand_font = base.font(base.BOLD, 27)
    lead_font = base.font(base.BOLD, 70)
    body_font = base.font(base.REGULAR, 39)
    small = base.font(base.REGULAR, 24)

    draw.rounded_rectangle((safe, 76, safe + 96, 84), radius=4, fill=accent)
    draw.text((safe, 108), slide["kicker"], font=kicker_font, fill=(25, 25, 25))
    brand_text = str(brand["name"])
    bw = draw.textbbox((0, 0), brand_text, font=brand_font)[2]
    draw.text((canvas[0] - safe - bw, 108), brand_text, font=brand_font, fill=(70, 70, 70))

    lead = str(slide.get("lead") or "").strip()
    lead_lines = base.wrap(draw, lead, lead_font, canvas[0] - 2 * safe, 3)
    y = 310
    for line in lead_lines:
        draw.text((safe, y), line, font=lead_font, fill=(24, 24, 24))
        y += 88

    y += 34
    draw.rounded_rectangle((safe, y, safe + 62, y + 7), radius=3, fill=accent)
    y += 52
    body_lines = base.wrap(draw, str(slide.get("body") or ""), body_font, canvas[0] - 2 * safe, 7)
    for line in body_lines:
        draw.text((safe, y), line, font=body_font, fill=(47, 47, 47))
        y += 55

    draw.text((safe, canvas[1] - 104), f"{index}  ·  valceaclar.ro", font=small, fill=(95, 95, 95))
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "JPEG", quality=93, optimize=True, progressive=True)


def build() -> dict[str, Any]:
    system = base.load(base.SYSTEM)
    registry = base.load(base.VISUALS)
    PREVIEW.mkdir(parents=True, exist_ok=True)
    for old in PREVIEW.glob("*.jpg"):
        old.unlink()
    plans: list[dict[str, Any]] = []
    for story in base.stories():
        story_id = str(story.get("id"))
        visual = base.visual_for(story_id, registry)
        ok, reason = base.approved_for_instagram(story, visual)
        if not ok:
            plans.append({"status": "HOLD", "story_id": story_id, "reason": reason, "headline": story.get("headline")})
            continue
        assert visual is not None
        plan = package(story, visual)
        errors = base.validate_plan(plan, system)
        if errors:
            plan["status"] = "HOLD"
            plan["reason"] = "visual_qa_failed"
            plan["qa_errors"] = errors
            plans.append(plan)
            continue
        cover = f"{story_id}-ig-v1-1-01-cover.jpg"
        base.render_cover(plan, PREVIEW / cover, system)
        files = [cover]
        for idx, slide in enumerate(plan.get("detail_slides") or [], start=2):
            name = f"{story_id}-ig-v1-1-{idx:02d}.jpg"
            render_text_slide(slide, idx, PREVIEW / name, system)
            files.append(name)
        plan["preview_files"] = files
        plan["slide_count"] = len(files)
        plans.append(plan)

    summary = {
        "schema_version": "1.1-preview",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "rendering_version": "instagram-editorial-v1.1",
        "canvas": system["canvas"],
        "plans": plans,
        "ready": sum(1 for p in plans if p.get("status") == "READY"),
        "held": sum(1 for p in plans if p.get("status") == "HOLD"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def self_test() -> int:
    assert contractor_pair("atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    sample = {
        "id": "sample",
        "section": "INVESTIGAȚII",
        "headline": "Pod peste Olănești",
        "dek": "Proiect SMIS 334436.",
        "paragraphs": [
            "Documentația include un nou pod exclusiv pietonal și ciclist în zona de lângă Omniasig.",
            "Proiectul are o valoare totală aprobată de 44.373.317,87 lei cu TVA. Contractul principal de execuție a fost atribuit asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți; valoarea atribuită este de 29.167.613,30 lei fără TVA.",
            "Nu atribuim lucrările vizibile unei anumite firme până când documentele publice nu permit această legătură. Nu există în acest moment o acuzație de neregulă.",
        ],
    }
    plan = package(sample, {"image_path": "x.jpg", "image": {"contextual_archive": True}})
    assert plan["hook"] == "44,37 mil. lei"
    assert plan["detail_slides"][1]["lead"] == "Ralunic + Dimex-2000 Company"
    assert plan["detail_slides"][2]["kicker"] == "CE NU ȘTIM ÎNCĂ"
    print("VÂLCEA CLAR Instagram editorial v1.1 self-test: PASS")
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
