#!/usr/bin/env python3
"""Build public, deterministic social-media assets for site-engine publishers."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from social_common import (
    OUTBOX,
    canonical_photo_url,
    load_json,
    local_image_path,
    photo_metadata,
    platform_selected,
    write_json,
)

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
DESTINATIONS = [
    VC / "site" / "runtime" / "media" / "social",
    VC / "dist" / "chatgpt-sites" / "media" / "social",
]
MANIFEST = VC / "social" / "social_media_manifest.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build() -> dict[str, Any]:
    outbox = load_json(OUTBOX, {"schema_version": "4.0", "items": []})
    records: dict[str, dict[str, Any]] = {}

    for item in outbox.get("items", []):
        if not isinstance(item, dict):
            continue
        if not (
            platform_selected(item, "instagram")
            or platform_selected(item, "tiktok")
        ):
            continue
        source = local_image_path(item)
        metadata = photo_metadata(item)
        filename = source.name
        digest = sha256(source)
        existing = records.get(filename)
        if existing and existing["sha256"] != digest:
            raise RuntimeError(
                f"social asset filename collision with different bytes: {filename}"
            )
        records[filename] = {
            "filename": filename,
            "sha256": digest,
            "bytes": source.stat().st_size,
            "public_url": canonical_photo_url(item),
            "credit": metadata["credit"],
            "rights_basis": metadata["rights_basis"],
            "source_url": metadata.get("source_url"),
        }

    for destination in DESTINATIONS:
        destination.mkdir(parents=True, exist_ok=True)
        for path in destination.iterdir():
            if path.is_file() and path.name != "manifest.json":
                path.unlink()
        for filename in sorted(records):
            source = next(
                local_image_path(item)
                for item in outbox.get("items", [])
                if isinstance(item, dict)
                and Path(str(item.get("image_path", ""))).name == filename
                and (
                    platform_selected(item, "instagram")
                    or platform_selected(item, "tiktok")
                )
            )
            shutil.copyfile(source, destination / filename)

    manifest = {
        "schema_version": "1.0",
        "generation": "deterministic_from_social_outbox_v1",
        "execution_owner": "civora_site_engine",
        "canonical_base_url": "https://valceaclar.ro/media/social/",
        "assets": [records[key] for key in sorted(records)],
    }
    write_json(MANIFEST, manifest)
    for destination in DESTINATIONS:
        write_json(destination / "manifest.json", manifest)
    return manifest


def self_test() -> int:
    assert str(VC).endswith("valcea-clar")
    assert len(DESTINATIONS) == 2
    print("VÂLCEA CLAR social-media asset builder self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    manifest = build()
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
