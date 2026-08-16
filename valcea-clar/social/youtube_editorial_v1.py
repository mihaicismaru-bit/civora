#!/usr/bin/env python3
"""Preview-only YouTube/Shorts editorial packaging v1 for VÂLCEA CLAR.

YouTube is treated as a durable explainer publication. A strong story may have a
complete source-preserving script and thumbnail/title package while remaining
HOLD_MEDIA until real story-specific video/visual evidence exists. No network
calls or synthetic footage are produced here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import build_outbox_only_story_products as base
from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
VISUALS = VC / "social" / "story_visuals.json"
PREVIEW = VC / "social" / "previews" / "youtube-v1"


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def visual_for(story_id: str, registry: dict[str, Any]) -> dict[str, Any] | None:
    value = registry.get("stories", {}).get(story_id)
    return value if isinstance(value, dict) else None


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


def media_gate(story: dict[str, Any], visual: dict[str, Any] | None) -> tuple[bool, str]:
    if not isinstance(visual, dict):
        return False, "real_story_specific_video_or_multi_asset_package_required"
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    if image.get("synthetic") is not False or image.get("editor_approved") is not True:
        return False, "approved_real_media_required"
    if image.get("contextual_archive") is True:
        corpus = " ".join([
            str(story.get("headline") or ""), str(story.get("dek") or ""),
            *[str(p) for p in story.get("paragraphs", [])],
        ]).lower()
        if "olănești" in corpus:
            return False, "current_site_video_or_visual_sequence_required"
        return False, "current_subject_video_or_visual_sequence_required"
    return False, "real_video_or_editorially_sufficient_visual_sequence_required"


def package(story: dict[str, Any], visual: dict[str, Any] | None) -> dict[str, Any]:
    story_id = str(story["id"])
    useful, editorial_reason = editorial_gate(story)
    media_ok, media_reason = media_gate(story, visual)
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()

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
        "title": title,
        "thumbnail_text": thumbnail,
        "chapters": chapters,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "real_video_required": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "title_thumbnail_pair_required": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "identity": product_identity("youtube"),
        "rendering_version": "youtube-editorial-v1.0",
    }
    product["product_fingerprint_sha256"] = digest(product)
    return product


def build() -> dict[str, Any]:
    pointer = base.load(base.POINTER)
    snapshot = base.load(base.VC / str(pointer["json_source"]))
    decision = base.load(base.DECISION, {"publishable_story_ids": []})
    event = base.load(base.EVENT, {"story_ids": []})
    registry = base.load(VISUALS, {"stories": {}})
    allowed = set(event.get("story_ids") or decision.get("publishable_story_ids") or [])
    stories = [item for item in snapshot.get("items", []) if item.get("id") in allowed and base.story_ready(item)[0]]
    products = [package(story, visual_for(str(story["id"]), registry)) for story in stories]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0-preview",
        "platform": "youtube",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
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
        "headline":"Investiție locală documentată cu impact public clar",
        "dek":"Un proiect important, verificat în documente, cu efect direct asupra comunității și infrastructurii locale.",
        "paragraphs":[
            "Documentația publică descrie investiția, calendarul, obiectivele și principalele lucrări care trebuie realizate.",
            "Contractul și finanțarea sunt publice, iar valoarea și responsabilitățile actorilor pot fi explicate cititorilor.",
            "Impactul local este suficient de amplu pentru un explainer video, dar publicarea trebuie să aștepte imagini reale adecvate.",
        ],
        "material_fact_gate":"PASS",
    }
    current={"image":{"synthetic":False,"editor_approved":True,"contextual_archive":False}}
    product=package(deep,current)
    assert product["status"]=="HOLD_MEDIA"
    assert product["real_video_required"] is True
    assert product["synthetic_filler_forbidden"] is True
    assert product["identity"]["channel_id"] == "valcea-youtube"
    assert product["identity"]["thumbnail"]["brand_mark"] == "VC."
    print("VÂLCEA CLAR YouTube editorial v1 self-test: PASS")
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
