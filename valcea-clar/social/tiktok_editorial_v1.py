#!/usr/bin/env python3
"""Preview-only TikTok editorial packaging v1 for VÂLCEA CLAR.

TikTok is treated as an audiovisual explainer publication, not a photo mirror.
A story can be editorially strong and still HOLD on TikTok when current real
motion/visual evidence is missing. This module creates source-preserving
storyboards only; it never synthesizes footage or makes network calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import build_outbox_only_story_products as base

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
VISUALS = VC / "social" / "story_visuals.json"
PREVIEW = VC / "social" / "previews" / "tiktok-v1"


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
    if image.get("contextual_archive") is True:
        corpus = " ".join([
            str(story.get("headline") or ""),
            str(story.get("dek") or ""),
            *[str(p) for p in story.get("paragraphs", [])],
        ]).lower()
        if "olănești" in corpus:
            return False, "current_site_photo_or_video_required"
        return False, "current_event_or_subject_media_required"
    # A current real photograph may support a TikTok photo story, while actual
    # real video is preferred for motion-first products. We never manufacture
    # motion from unrelated/archival images.
    return True, "current_real_photo_available"


def package(story: dict[str, Any], visual: dict[str, Any] | None) -> dict[str, Any]:
    story_id = str(story["id"])
    useful, utility_reason = utility_gate(story)
    media_ok, media_reason = media_gate(story, visual)
    headline = str(story.get("headline") or "").strip()
    dek = str(story.get("dek") or "").strip()
    paragraphs = [str(p).strip() for p in story.get("paragraphs", []) if str(p).strip()]
    corpus = " ".join([headline, dek, *paragraphs]).lower()

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
    storyboard.append({"beat": "final", "purpose": "source", "on_screen": "Surse și context: valceaclar.ro"})

    status = "READY" if useful and media_ok else "HOLD_MEDIA" if useful else "HOLD"
    reason = None if status == "READY" else (media_reason if useful else utility_reason)
    product = {
        "story_id": story_id,
        "status": status,
        "hold_reason": reason,
        "publication_mode": "preview_only",
        "native_format": "photo_post" if status == "READY" else "short",
        "format_family": "visual_explainer",
        "hook": hook,
        "storyboard": storyboard,
        "canonical_url": base.canonical(story),
        "source_preserving": True,
        "first_seconds_hook_required": True,
        "subtitles_required": True,
        "real_footage_preferred": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "music_dependency_required": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "rendering_version": "tiktok-editorial-v1.0",
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
    stories = [
        item for item in snapshot.get("items", [])
        if item.get("id") in allowed and base.story_ready(item)[0]
    ]
    products = [package(story, visual_for(str(story["id"]), registry)) for story in stories]
    PREVIEW.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0-preview",
        "platform": "tiktok",
        "execution_mode": "PREVIEW_ONLY_NO_NETWORK_CALLS",
        "products": products,
        "ready": sum(1 for p in products if p.get("status") == "READY"),
        "held": sum(1 for p in products if p.get("status") != "READY"),
    }
    (PREVIEW / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def self_test() -> int:
    story = {
        "id": "test",
        "headline": "Lucrări locale importante",
        "dek": "O schimbare verificată pentru comunitate.",
        "paragraphs": ["Documentația publică explică proiectul și impactul."],
        "material_fact_gate": "PASS",
    }
    current_visual = {
        "image_path": "x.jpg",
        "image": {"synthetic": False, "editor_approved": True, "contextual_archive": False},
    }
    assert package(story, current_visual)["status"] == "READY"
    archived = json.loads(json.dumps(current_visual))
    archived["image"]["contextual_archive"] = True
    assert package(story, archived)["status"] == "HOLD_MEDIA"
    thin = dict(story)
    thin["material_fact_gate"] = "PASS_DATE_ONLY"
    assert package(thin, current_visual)["status"] == "HOLD"
    print("VÂLCEA CLAR TikTok editorial v1 self-test: PASS")
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
