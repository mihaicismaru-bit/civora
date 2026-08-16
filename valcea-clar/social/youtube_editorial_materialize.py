#!/usr/bin/env python3
"""Materialize VÂLCEA CLAR YouTube editorial v1.1 into canonical outbox/state.

Outbox-only. A truthful thumbnail asset is produced only for a READY real-video
package. No upload credentials or network calls are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image

import youtube_editorial_v1 as editorial
from native_identity import product_identity

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
OUTBOX = VC / "social" / "youtube_outbox.json"
STATE = VC / "social" / "youtube_state.json"
RUNTIME = VC / "site" / "runtime" / "media" / "social" / "editorial" / "youtube"


def load(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def ready_video_source(product: dict[str, Any]) -> dict[str, Any]:
    if product.get("status") != "READY":
        raise ValueError("YouTube video source requested for non-READY product")
    metadata = product.get("video_metadata") if isinstance(product.get("video_metadata"), dict) else {}
    video = ROOT / str(product.get("source_video_path") or "")
    poster = ROOT / str(product.get("poster_image_path") or "")
    if not video.is_file() or not poster.is_file():
        raise ValueError("YouTube READY product video/poster bytes are unavailable")
    source = {
        "kind": "video",
        "synthetic": False,
        "story_id": str(product["story_id"]),
        "video_path": str(product.get("source_video_path")),
        "poster_image_path": str(product.get("poster_image_path")),
        "video_sha256": sha256(video),
        "poster_sha256": sha256(poster),
        "video_bytes": video.stat().st_size,
        "credit": str(metadata.get("credit") or ""),
        "rights_basis": str(metadata.get("rights_basis") or ""),
        "source_type": str(metadata.get("source_type") or ""),
        "source_url": metadata.get("source_url"),
        "alt_text": str(metadata.get("alt_text") or ""),
        "source_fact_kernel": "canonical_verified_story",
    }
    source["source_fingerprint_sha256"] = editorial.digest(source)
    return source


def thumbnail_asset(
    product: dict[str, Any],
    video_source: dict[str, Any],
    runtime: Path = RUNTIME,
) -> dict[str, Any]:
    if product.get("status") != "READY":
        raise ValueError("YouTube thumbnail may only materialize for READY product")
    runtime.mkdir(parents=True, exist_ok=True)
    poster = ROOT / str(product.get("poster_image_path") or "")
    fp = str(product.get("product_fingerprint_sha256") or "")
    if len(fp) != 64:
        raise ValueError("YouTube product fingerprint missing")
    rendered = runtime / f"{product['story_id']}-youtube-{fp[:12]}-thumb.jpg"
    editorial.render_thumbnail(product, poster, rendered)
    asset = {
        "kind": "editorial_thumbnail",
        "synthetic": False,
        "story_id": str(product["story_id"]),
        "platform": "youtube",
        "renderer": "youtube-editorial-v1.1",
        "rendered_path": str(rendered.relative_to(ROOT)),
        "sha256": sha256(rendered),
        "poster_source_sha256": video_source["poster_sha256"],
        "source_video_sha256": video_source["video_sha256"],
        "product_fingerprint_sha256": fp,
        "rights_basis": "original_editorial_layout_over_real_video_frame",
        "source_fact_kernel": "canonical_verified_story",
        "truthful_thumbnail_required": True,
        "thumbnail_requires_ready_video": True,
        "title": str(product.get("title") or ""),
        "thumbnail_text": str(product.get("thumbnail_text") or ""),
        "alt_text": f"VÂLCEA CLAR: {str(product.get('thumbnail_text') or product.get('title') or '').strip()}",
    }
    asset["asset_fingerprint_sha256"] = editorial.digest(asset)
    validate_thumbnail(asset, video_source)
    return asset


def validate_thumbnail(asset: dict[str, Any], video_source: dict[str, Any]) -> None:
    if asset.get("kind") != "editorial_thumbnail" or asset.get("synthetic") is not False:
        raise ValueError("invalid YouTube editorial thumbnail")
    if asset.get("renderer") != "youtube-editorial-v1.1":
        raise ValueError("YouTube thumbnail renderer lineage drift")
    if asset.get("thumbnail_requires_ready_video") is not True or asset.get("truthful_thumbnail_required") is not True:
        raise ValueError("YouTube truthful-thumbnail gate missing")
    if asset.get("source_fact_kernel") != "canonical_verified_story":
        raise ValueError("YouTube thumbnail fact-kernel lineage missing")
    if asset.get("source_video_sha256") != video_source.get("video_sha256"):
        raise ValueError("YouTube thumbnail/video source mismatch")
    if asset.get("poster_source_sha256") != video_source.get("poster_sha256"):
        raise ValueError("YouTube thumbnail/poster source mismatch")
    candidate = dict(asset)
    supplied = str(candidate.pop("asset_fingerprint_sha256", ""))
    if supplied != editorial.digest(candidate):
        raise ValueError("YouTube thumbnail fingerprint mismatch")
    path = ROOT / str(asset.get("rendered_path") or "")
    if not path.is_file() or sha256(path) != str(asset.get("sha256") or ""):
        raise ValueError("YouTube thumbnail bytes/hash mismatch")
    with Image.open(path) as image:
        if image.size != (1280, 720):
            raise ValueError(f"YouTube thumbnail dimensions drifted: {image.size}")


def canonical_item(
    product: dict[str, Any],
    video_source: dict[str, Any] | None = None,
    thumbnail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    sid = str(product["story_id"])
    common = {
        "id": f"youtube-story-{sid}",
        "story_id": sid,
        "publication_mode": "durable_outbox_only",
        "canonical_url": product["canonical_url"],
        "source_preserving": True,
        "real_video_required": True,
        "synthetic_filler_forbidden": True,
        "archive_as_current_forbidden": True,
        "verbatim_cross_platform_reuse_allowed": False,
        "direct_publication_enabled": False,
        "direct_publication_blocker": "youtube_verified_upload_access_not_configured",
        "generation_mode": "youtube_editorial_v1_1",
        "identity": product_identity("youtube"),
        "edition_gate": False,
    }
    if product.get("status") == "HOLD":
        if video_source is not None or thumbnail is not None:
            raise ValueError("YouTube HOLD product must not carry media assets")
        return {
            **common,
            "status": "hold",
            "native_format": "short",
            "format_family": "youtube_hold",
            "hold_reason": product.get("hold_reason"),
        }
    if product.get("status") == "HOLD_MEDIA":
        if video_source is not None or thumbnail is not None:
            raise ValueError("YouTube HOLD_MEDIA product must not carry thumbnail/video assets")
        return {
            **common,
            "status": "hold_media",
            "native_format": product["native_format"],
            "format_family": product["format_family"],
            "hold_reason": product.get("hold_reason"),
            "title": product["title"],
            "thumbnail_text": product["thumbnail_text"],
            "chapters": product["chapters"],
            "title_thumbnail_pair_required": True,
            "thumbnail_requires_ready_video": True,
            "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        }
    if video_source is None or thumbnail is None:
        raise ValueError("YouTube READY product requires real video source and truthful thumbnail")
    validate_thumbnail(thumbnail, video_source)
    return {
        **common,
        "status": "outbox_ready",
        "native_format": product["native_format"],
        "format_family": product["format_family"],
        "title": product["title"],
        "thumbnail_text": product["thumbnail_text"],
        "chapters": product["chapters"],
        "title_thumbnail_pair_required": True,
        "thumbnail_requires_ready_video": True,
        "truthful_thumbnail_required": True,
        "product_fingerprint_sha256": product["product_fingerprint_sha256"],
        "video_source": video_source,
        "thumbnail_asset": thumbnail,
    }


def build() -> dict[str, Any]:
    preview = editorial.build()
    products: list[dict[str, Any]] = []
    for product in preview.get("products", []):
        if not isinstance(product, dict):
            continue
        if product.get("status") == "READY":
            source = ready_video_source(product)
            thumb = thumbnail_asset(product, source)
            products.append(canonical_item(product, source, thumb))
        else:
            products.append(canonical_item(product))

    outbox = load(OUTBOX, {"schema_version": "1.0", "platform": "youtube", "items": []})
    existing = {
        str(i.get("id")): i
        for i in outbox.get("items", [])
        if isinstance(i, dict) and i.get("id")
    }
    for product in products:
        existing[product["id"]] = product
    outbox.update({
        "schema_version": "1.2",
        "platform": "youtube",
        "publication_model": "continuous_story_first",
        "editorial_product_version": "youtube-editorial-v1.1",
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "edition_recaps_are_publication_gates": False,
        "items": list(existing.values()),
    })
    write(OUTBOX, outbox)

    state = load(STATE, {
        "schema_version": "1.0",
        "platform": "youtube",
        "execution_owner": "civora_site_engine",
        "published": {},
        "failures": {},
    })
    state.update({
        "schema_version": "1.2",
        "platform": "youtube",
        "execution_owner": "civora_site_engine",
        "publication_model": "continuous_story_first",
        "editorial_product_version": "youtube-editorial-v1.1",
        "identity_source": "valcea-clar/social/native_platform_identity_system.json",
        "direct_publication_enabled": False,
        "direct_publication_blocker": "youtube_verified_upload_access_not_configured",
    })
    state.setdefault("published", {})
    state.setdefault("failures", {})
    write(STATE, state)
    return {
        "status": "PASS",
        "platform": "youtube",
        "editorial_product_version": "youtube-editorial-v1.1",
        "products": len(products),
        "ready": sum(p.get("status") == "outbox_ready" for p in products),
        "held": sum(p.get("status") != "outbox_ready" for p in products),
        "thumbnail_assets": sum(isinstance(p.get("thumbnail_asset"), dict) for p in products),
        "direct_publication_enabled": False,
    }


def self_test() -> int:
    story = {
        "id":"x",
        "section":"INFRASTRUCTURĂ",
        "headline":"Investiție locală documentată cu impact public clar",
        "dek":"Un proiect important, verificat în documente, cu efect direct asupra comunității și infrastructurii locale.",
        "paragraphs":[
            "Documentația publică descrie investiția, calendarul, obiectivele și principalele lucrări care trebuie realizate.",
            "Contractul și finanțarea sunt publice, iar valoarea și responsabilitățile actorilor pot fi explicate cititorilor.",
            "Impactul local justifică un explainer video numai dacă există video real adecvat și verificabil.",
        ],
        "material_fact_gate":"PASS",
    }
    hold = editorial.package(story, {"image":{"synthetic":False,"editor_approved":True,"subject_match":True,"contextual_archive":False}})
    held_item = canonical_item(hold)
    assert held_item["status"] == "hold_media"
    assert "thumbnail_asset" not in held_item

    with tempfile.TemporaryDirectory(dir=ROOT) as raw:
        work = Path(raw)
        poster = work / "poster.jpg"
        video = work / "video.mp4"
        Image.new("RGB", (1600,900), (85,108,126)).save(poster, "JPEG", quality=92)
        video.write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 4096)
        visual = {
            "video": {
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
        product = editorial.package(story, visual)
        assert product["status"] == "READY"
        source = ready_video_source(product)
        thumb = thumbnail_asset(product, source, work)
        item = canonical_item(product, source, thumb)
        assert item["status"] == "outbox_ready"
        assert item["direct_publication_enabled"] is False
        assert item["generation_mode"] == "youtube_editorial_v1_1"
        assert item["identity"]["channel_id"] == "valcea-youtube"
        assert item["identity"]["thumbnail"]["brand_mark"] == "VC."
        assert item["thumbnail_asset"]["kind"] == "editorial_thumbnail"
        assert item["thumbnail_asset"]["source_video_sha256"] == item["video_source"]["video_sha256"]
        assert item["thumbnail_asset"]["poster_source_sha256"] == item["video_source"]["poster_sha256"]
    print("VÂLCEA CLAR YouTube editorial materializer v1.1 self-test: PASS")
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
