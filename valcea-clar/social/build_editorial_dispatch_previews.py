#!/usr/bin/env python3
"""Build adapter-ready Facebook/Instagram editorial dispatch contracts.

Preview-only: creates rendered products, provenance-linked composite assets and
platform-specific dispatch JSON. It never contacts Meta and never mutates live
publication state/outboxes.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import editorial_asset_contract as asset_contract
import facebook_editorial_preview_v1_1 as fb_patch
import instagram_editorial_v1_2 as ig_patch

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
VISUALS = VC / "social" / "story_visuals.json"
OUT = VC / "social" / "previews" / "dispatch-contracts"
PUBLIC_BASE = "https://valceaclar.ro/media/social/editorial/"

fb = fb_patch.impl
ig = ig_patch.impl


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def instagram_caption(story: dict[str, Any], plan: dict[str, Any], visual: dict[str, Any]) -> str:
    parts = [str(plan.get("hook") or "").strip()]
    subline = str(plan.get("subline") or "").strip()
    if subline:
        parts.append(subline)
    dek = str(story.get("dek") or "").strip()
    if dek and dek.lower() not in " ".join(parts).lower():
        parts.append(dek)
    image = visual.get("image") if isinstance(visual.get("image"), dict) else {}
    note = str(image.get("editorial_note") or "").strip()
    if note:
        parts.append(note)
    parts.append("Contextul complet și sursele verificate: valceaclar.ro")
    return "\n\n".join(part for part in parts if part)


def story_map() -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for story in ig.stories():
        result[str(story["id"])] = story
    return result


def render_platform_products() -> tuple[dict[str, Any], dict[str, Any]]:
    # The imported patch modules have already installed corrected entity-name
    # normalization into their underlying preview implementations.
    ig_summary = ig_patch.impl.build()
    fb_summary = fb_patch.impl.build()
    return ig_summary, fb_summary


def make_instagram_dispatch(
    summary: dict[str, Any],
    stories: dict[str, dict[str, Any]],
    visuals: dict[str, Any],
) -> dict[str, Any]:
    products = []
    holds = []
    root = VC / "social" / "previews" / "instagram-v1-1"
    for plan in summary.get("plans", []):
        story_id = str(plan.get("story_id") or "")
        if plan.get("status") != "READY":
            holds.append({"story_id": story_id, "reason": plan.get("reason")})
            continue
        story = stories[story_id]
        visual = visuals.get("stories", {}).get(story_id)
        if not isinstance(visual, dict):
            raise ValueError(f"Instagram dispatch missing source visual for {story_id}")
        assets = []
        for filename in plan.get("preview_files", []):
            rendered = root / str(filename)
            asset = asset_contract.build_asset(
                story_id=story_id,
                platform="instagram",
                renderer="instagram-editorial-v1.1",
                rendered_path=rendered,
                source_visual=visual,
                product_fingerprint=str(plan["product_fingerprint_sha256"]),
                public_url=PUBLIC_BASE + rendered.name,
            )
            asset_contract.validate_asset(asset)
            assets.append(asset)
        if not assets:
            raise ValueError(f"Instagram READY product has no rendered assets: {story_id}")
        expected = 1 if plan.get("native_format") == "single_photo" else 1 + len(plan.get("detail_slides") or [])
        if len(assets) != expected:
            raise ValueError(f"Instagram asset count mismatch for {story_id}")
        product = {
            "story_id": story_id,
            "platform": "instagram",
            "publication_mode": "editorial_visual_product",
            "native_format": plan["native_format"],
            "template_id": plan["template_id"],
            "hook": plan["hook"],
            "caption": instagram_caption(story, plan, visual),
            "canonical_url": f"https://valceaclar.ro/stiri/{story_id}/",
            "product_fingerprint_sha256": plan["product_fingerprint_sha256"],
            "assets": assets,
            "requires_public_media_preflight": True,
            "verbatim_facebook_reuse_allowed": False,
            "meta_calls_performed": False,
        }
        product["dispatch_fingerprint_sha256"] = asset_contract.canonical_digest(product)
        products.append(product)
    return {
        "schema_version": "1.0-preview",
        "platform": "instagram",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "products": products,
        "holds": holds,
    }


def make_facebook_dispatch(
    summary: dict[str, Any],
    stories: dict[str, dict[str, Any]],
    visuals: dict[str, Any],
) -> dict[str, Any]:
    products = []
    holds = []
    root = VC / "social" / "previews" / "facebook"
    for plan in summary.get("plans", []):
        story_id = str(plan.get("story_id") or "")
        if plan.get("status") != "READY":
            holds.append({"story_id": story_id, "reason": plan.get("reason")})
            continue
        visual = visuals.get("stories", {}).get(story_id)
        if not isinstance(visual, dict):
            raise ValueError(f"Facebook dispatch missing source visual for {story_id}")
        filename = str(plan.get("preview_file") or "")
        rendered = root / filename
        asset = asset_contract.build_asset(
            story_id=story_id,
            platform="facebook",
            renderer="facebook-editorial-v1.0",
            rendered_path=rendered,
            source_visual=visual,
            product_fingerprint=str(plan["product_fingerprint_sha256"]),
            public_url=None,
        )
        asset_contract.validate_asset(asset)
        product = {
            "story_id": story_id,
            "platform": "facebook",
            "publication_mode": "editorial_photo_upload",
            "template_id": plan["template_id"],
            "hook": plan["hook"],
            "body": plan["body"],
            "canonical_url": plan["canonical_link"],
            "product_fingerprint_sha256": plan["product_fingerprint_sha256"],
            "asset": asset,
            "binary_upload_required": True,
            "verbatim_instagram_reuse_allowed": False,
            "meta_calls_performed": False,
        }
        product["dispatch_fingerprint_sha256"] = asset_contract.canonical_digest(product)
        products.append(product)
    return {
        "schema_version": "1.0-preview",
        "platform": "facebook",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "products": products,
        "holds": holds,
    }


def copy_assets(doc: dict[str, Any], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for old in destination.glob("*.jpg"):
        old.unlink()
    for product in doc.get("products", []):
        candidates = product.get("assets") if isinstance(product.get("assets"), list) else [product.get("asset")]
        for raw in candidates:
            if not isinstance(raw, dict):
                continue
            source = ROOT / str(raw["rendered_path"])
            shutil.copyfile(source, destination / source.name)


def validate_cross_platform(ig_doc: dict[str, Any], fb_doc: dict[str, Any]) -> None:
    ig_by = {row["story_id"]: row for row in ig_doc.get("products", [])}
    fb_by = {row["story_id"]: row for row in fb_doc.get("products", [])}
    for story_id in sorted(set(ig_by) & set(fb_by)):
        ig_product = ig_by[story_id]
        fb_product = fb_by[story_id]
        if str(ig_product.get("caption") or "").strip() == str(fb_product.get("body") or "").strip():
            raise ValueError(f"verbatim Instagram/Facebook copy detected: {story_id}")
        if ig_product.get("publication_mode") == fb_product.get("publication_mode"):
            raise ValueError(f"platform-native publication mode collision: {story_id}")


def build() -> dict[str, Any]:
    OUT.mkdir(parents=True, exist_ok=True)
    visuals = load(VISUALS)
    stories = story_map()
    ig_summary, fb_summary = render_platform_products()
    ig_doc = make_instagram_dispatch(ig_summary, stories, visuals)
    fb_doc = make_facebook_dispatch(fb_summary, stories, visuals)
    validate_cross_platform(ig_doc, fb_doc)
    copy_assets(ig_doc, OUT / "instagram")
    copy_assets(fb_doc, OUT / "facebook")
    (OUT / "instagram-dispatch.json").write_text(json.dumps(ig_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUT / "facebook-dispatch.json").write_text(json.dumps(fb_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result = {
        "status": "PASS",
        "execution_mode": "PREVIEW_ONLY_NO_META_CALLS",
        "instagram_products": len(ig_doc["products"]),
        "instagram_holds": len(ig_doc["holds"]),
        "facebook_products": len(fb_doc["products"]),
        "facebook_holds": len(fb_doc["holds"]),
    }
    (OUT / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def self_test() -> int:
    assert PUBLIC_BASE.startswith("https://valceaclar.ro/")
    assert fb_patch.contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    assert ig_patch.contractor_pair("asocierii Ralunic SRL — Dimex-2000 Company SRL, cu subcontractanți") == "Ralunic + Dimex-2000 Company"
    print("VÂLCEA CLAR editorial dispatch preview self-test: PASS")
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
