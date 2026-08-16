#!/usr/bin/env python3
"""End-to-end regression for the VÂLCEA CLAR TikTok premium photo path.

Uses a temporary, test-only photograph. No network call or production outbox
mutation occurs. The test proves editorial gating -> 1080x1920 renderer -> asset
lineage -> canonical URL resolution -> historical Direct Post validator.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from PIL import Image

import build_social_media_assets as assets
import social_common
import tiktok_editorial_v1 as editorial
import tiktok_publish


def fixture_story() -> dict:
    return {
        "id": "premium-photo-selftest",
        "section": "INFRASTRUCTURĂ",
        "headline": "Lucrări locale importante, explicate din documente",
        "dek": "O schimbare verificată pentru comunitate, cu efect direct asupra infrastructurii locale.",
        "paragraphs": [
            "Documentația publică explică proiectul, calendarul, finanțarea și impactul local pentru locuitori."
        ],
        "material_fact_gate": "PASS",
    }


def fixture_metadata() -> dict:
    return {
        "kind": "photograph",
        "synthetic": False,
        "subject_match": True,
        "editor_approved": True,
        "contextual_archive": False,
        "source_type": "staff",
        "credit": "VÂLCEA CLAR",
        "rights_basis": "owned",
        "source_url": None,
        "alt_text": "Fotografie actuală de test pentru subiectul local.",
    }


def main() -> int:
    story = fixture_story()
    metadata = fixture_metadata()
    with tempfile.TemporaryDirectory(dir=assets.ROOT) as raw:
        work = Path(raw)
        source = work / "current-real-photo.jpg"
        # Test-only pixels; never exposed as a production story asset.
        Image.new("RGB", (1600, 1200), (112, 126, 135)).save(source, "JPEG", quality=92)
        visual = {"image_path": str(source), "image": metadata}
        product = editorial.package(story, visual)
        if product.get("status") != "READY" or product.get("native_format") != "single_photo":
            raise SystemExit(f"TikTok editorial fixture not READY: {product}")

        config = {
            "status": "ready",
            "mode": "direct_post",
            "reason": None,
            "title": str(product["hook"])[:90],
            "description": "Fapt verificat.\n\nDocumente și context: valceaclar.ro",
            "privacy_level": "PUBLIC_TO_EVERYONE",
            "disable_comment": False,
            "consent": {
                "granted": True,
                "source": "valceaclar_site_admin",
                "granted_at": "2026-08-16T16:00:00Z",
                "actor": "premium-path-selftest",
            },
            "editorial_product_status": "READY",
            "editorial_rendering_version": "tiktok-editorial-v1.1",
            "editorial_product_fingerprint_sha256": product["product_fingerprint_sha256"],
            "editorial_native_format": "single_photo",
            "premium_asset_required": True,
            "synthetic_filler_forbidden": True,
            "archive_as_current_forbidden": True,
            "verbatim_cross_platform_reuse_allowed": False,
        }
        item = {
            "id": "story-premium-photo-selftest",
            "source_story_id": story["id"],
            "status": "ready",
            "message": "Legacy fallback text that must not decide the media URL.",
            "link": "https://valceaclar.ro/stiri/premium-photo-selftest/",
            "image_path": str(source),
            "image": metadata,
            "platforms": {"tiktok": config},
        }
        filename, asset = assets.premium_tiktok_asset(
            item=item,
            story=story,
            source=source,
            metadata=metadata,
            destination=work,
        )
        rendered = work / filename
        with Image.open(rendered) as image:
            if image.size != (1080, 1920):
                raise SystemExit(f"TikTok premium dimensions drifted: {image.size}")
        if rendered.stat().st_size < 30000:
            raise SystemExit("TikTok premium JPEG unexpectedly small")

        config["photo_url"] = asset["public_url"]
        config["editorial_asset"] = asset
        resolved = social_common.canonical_photo_url(item)
        if resolved != asset["public_url"] or resolved.endswith("current-real-photo.jpg"):
            raise SystemExit(f"TikTok premium URL did not override raw source: {resolved}")
        validated = tiktok_publish.validate_item(item)
        if validated["photo_url"] != asset["public_url"]:
            raise SystemExit("TikTok Direct Post validator did not receive premium composite URL")
        if "#" in config["description"]:
            raise SystemExit("TikTok premium copy reintroduced a default hashtag block")

        tampered = json.loads(json.dumps(item))
        tampered["platforms"]["tiktok"]["editorial_asset"]["sha256"] = "0" * 64
        try:
            social_common.canonical_photo_url(tampered)
        except ValueError:
            pass
        else:
            raise AssertionError("tampered TikTok premium asset was accepted")

        missing = json.loads(json.dumps(item))
        missing["platforms"]["tiktok"].pop("editorial_asset", None)
        try:
            social_common.canonical_photo_url(missing)
        except ValueError:
            pass
        else:
            raise AssertionError("missing TikTok premium asset was accepted")

        archived = json.loads(json.dumps(visual))
        archived["image"]["contextual_archive"] = True
        if editorial.package(story, archived).get("status") != "HOLD_MEDIA":
            raise AssertionError("archival TikTok media escaped HOLD_MEDIA")

    print("VÂLCEA CLAR TikTok premium photo path: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
