#!/usr/bin/env python3
"""Build deterministic public media assets for site-engine social adapters.

Raw approved photographs remain available for platforms whose native product
uses them directly. TikTok editorial READY photo stories receive a separate
1080x1920 newsroom composite; TikTok HOLD/HOLD_MEDIA stories never receive a
premium publication asset.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import tiktok_editorial_v1 as tiktok_editorial
from social_common import (
    OUTBOX,
    load_json,
    local_image_path,
    photo_metadata,
    platform_ready,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
CURRENT = VC / "site" / "current_edition.json"
DESTINATIONS = [
    VC / "site" / "runtime" / "media" / "social",
    VC / "dist" / "chatgpt-sites" / "media" / "social",
]
MANIFEST = VC / "social" / "social_media_manifest.json"
PUBLIC_BASE = "https://valceaclar.ro/media/social/"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def current_stories() -> dict[str, dict[str, Any]]:
    pointer = load_json(CURRENT)
    snapshot = load_json(VC / str(pointer["json_source"]))
    return {
        str(story.get("id")): story
        for story in snapshot.get("items", [])
        if isinstance(story, dict) and story.get("id")
    }


def tiktok_config(item: dict[str, Any]) -> dict[str, Any] | None:
    platforms = item.get("platforms") if isinstance(item.get("platforms"), dict) else {}
    value = platforms.get("tiktok")
    return value if isinstance(value, dict) else None


def premium_tiktok_asset(
    *,
    item: dict[str, Any],
    story: dict[str, Any],
    source: Path,
    metadata: dict[str, Any],
    destination: Path,
) -> tuple[str, dict[str, Any]]:
    visual = {
        "image_path": str(item.get("image_path") or ""),
        "image": item.get("image") if isinstance(item.get("image"), dict) else {},
    }
    product = tiktok_editorial.package(story, visual)
    if product.get("status") != "READY" or product.get("native_format") != "single_photo":
        raise ValueError("TikTok premium asset requested for non-READY editorial product")
    config = tiktok_config(item) or {}
    expected_fp = str(config.get("editorial_product_fingerprint_sha256") or "")
    supplied_fp = str(product.get("product_fingerprint_sha256") or "")
    if not expected_fp or expected_fp != supplied_fp:
        raise ValueError("TikTok active outbox/editorial product fingerprint drift")
    filename = f"{story['id']}-tiktok-v1-1-{supplied_fp[:12]}.jpg"
    rendered = destination / filename
    tiktok_editorial.render_photo_story(product, source, rendered)
    rendered_sha = sha256(rendered)
    source_sha = sha256(source)
    public_url = PUBLIC_BASE + filename
    asset = {
        "kind": "editorial_composite",
        "synthetic": False,
        "platform": "tiktok",
        "story_id": str(story["id"]),
        "renderer": "tiktok-editorial-v1.1",
        "filename": filename,
        "public_url": public_url,
        "sha256": rendered_sha,
        "source_photo_sha256": source_sha,
        "product_fingerprint_sha256": supplied_fp,
        "credit": metadata["credit"],
        "rights_basis": metadata["rights_basis"],
        "source_url": metadata.get("source_url"),
        "source_photo_path": str(item.get("image_path") or ""),
        "source_fact_kernel": "canonical_verified_story",
        "archive_as_current_forbidden": True,
    }
    asset["asset_fingerprint_sha256"] = tiktok_editorial.digest(asset)
    return filename, asset


def build() -> dict[str, Any]:
    outbox = load_json(OUTBOX, {"schema_version": "4.0", "items": []})
    stories = current_stories()
    records: dict[str, dict[str, Any]] = {}
    sources: dict[str, Path] = {}

    for item in outbox.get("items", []):
        if not isinstance(item, dict):
            continue
        # HOLD_MEDIA is a valid story-first state: the site story may already be
        # live while a visual channel waits for its own approved native asset.
        # Never dereference image metadata until at least one visual platform is
        # actually ready. Instagram readiness keeps its source photo available;
        # TikTok gets a separate composite below only if editorially READY.
        if not (
            platform_ready(item, "instagram")
            or platform_ready(item, "tiktok")
        ):
            continue
        source = local_image_path(item)
        metadata = photo_metadata(item)
        filename = source.name
        source_digest = sha256(source)
        existing = records.get(filename)
        if existing and existing["sha256"] != source_digest:
            raise RuntimeError(
                f"social asset filename collision with different bytes: {filename}"
            )
        sources[filename] = source
        records[filename] = {
            "filename": filename,
            "kind": "source_photograph",
            "synthetic": False,
            "sha256": source_digest,
            "bytes": source.stat().st_size,
            # Raw source asset location is independent from any platform-specific
            # URL override such as TikTok's premium editorial composite.
            "public_url": PUBLIC_BASE + filename,
            "credit": metadata["credit"],
            "rights_basis": metadata["rights_basis"],
            "source_url": metadata.get("source_url"),
        }

    for destination in DESTINATIONS:
        destination.mkdir(parents=True, exist_ok=True)
        for path in destination.iterdir():
            if path.is_file() and path.name != "manifest.json":
                path.unlink()
        for filename, source in sorted(sources.items()):
            shutil.copyfile(source, destination / filename)

    # Render TikTok's platform-native photo products after the underlying source
    # photos have been staged. An editorial READY state is not the same as
    # consent/network readiness; platform status remains HOLD until those gates
    # are satisfied, but any future Direct Post URL must point to this composite.
    first_destination = DESTINATIONS[0]
    premium_count = 0
    for item in outbox.get("items", []):
        if not isinstance(item, dict):
            continue
        config = tiktok_config(item)
        if not config or config.get("editorial_product_status") != "READY":
            if config:
                config.pop("editorial_asset", None)
            continue
        story_id = str(item.get("source_story_id") or "")
        story = stories.get(story_id)
        if not isinstance(story, dict):
            raise RuntimeError(f"TikTok READY story missing from current edition: {story_id}")
        source = local_image_path(item)
        metadata = photo_metadata(item)
        filename, asset = premium_tiktok_asset(
            item=item,
            story=story,
            source=source,
            metadata=metadata,
            destination=first_destination,
        )
        for destination in DESTINATIONS[1:]:
            shutil.copyfile(first_destination / filename, destination / filename)
        config["photo_url"] = asset["public_url"]
        config["editorial_asset"] = asset
        config["premium_asset_required"] = True
        records[filename] = {
            **asset,
            "bytes": (first_destination / filename).stat().st_size,
        }
        premium_count += 1

    write_json(OUTBOX, outbox)
    manifest = {
        "schema_version": "1.2",
        "generation": "deterministic_native_social_assets_v1_2",
        "execution_owner": "civora_site_engine",
        "publication_model": "continuous_story_first",
        "held_channels_are_not_asset_errors": True,
        "canonical_base_url": PUBLIC_BASE,
        "tiktok_editorial_product_version": "tiktok-editorial-v1.1",
        "tiktok_premium_assets": premium_count,
        "assets": [records[key] for key in sorted(records)],
    }
    write_json(MANIFEST, manifest)
    for destination in DESTINATIONS:
        write_json(destination / "manifest.json", manifest)
    return manifest


def self_test() -> int:
    assert str(VC).endswith("valcea-clar")
    assert len(DESTINATIONS) == 2
    assert PUBLIC_BASE == "https://valceaclar.ro/media/social/"
    assert tiktok_editorial.product_identity("tiktok")["visual"]["brand_mark"] == "VC."
    print("VÂLCEA CLAR social media asset builder v1.2 self-test: PASS")
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
