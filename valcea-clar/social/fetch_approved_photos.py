#!/usr/bin/env python3
"""Fetch approved, rights-documented real photographs for VÂLCEA CLAR.

Static editorial assets remain supported, while story-specific media is loaded
from story_visuals.json so a newly approved visual does not require a second
hard-coded downloader edit. Every remote image must have explicit provenance
and rights metadata in the registry. Downloads fail closed on path, HTTP, file
type or size errors.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEST = (ROOT / "valcea-clar" / "social" / "photos" / "approved").resolve()
REGISTRY = ROOT / "valcea-clar" / "social" / "story_visuals.json"

STATIC_ASSETS: dict[str, list[str]] = {
    "launch-ramnicu-valcea-panorama.jpg": [
        "https://upload.wikimedia.org/wikipedia/commons/8/8d/Ramnicu_Valcea_panorama.jpg",
    ],
    "spartan-ramnicu-valcea-opening.jpg": [
        "https://cdn.romania-insider.com/sites/default/files/styles/article_large_image/public/2026-05/spartan_rm_valcea_-_photo_pr.jpeg",
        "https://www.forbes.ro/wp-content/uploads/2026/05/Spartan-Rm-Valcea-1-e1778062545547.jpeg",
        "https://media.economedia.ro/5UD8bLA8aurgMSRb3hCTbEv-Qw0=/1320x743/smart/filters:format(jpeg)/https://www.economedia.ro/wp-content/uploads/2024/04/Spartan-Romania-e1778064990205-1024x683.jpeg",
    ],
    "musiclover-festival-archive-2024.jpg": [
        "https://gigxels.com/storage/photos/lupu-sebastian/bibi-ramnicu-valcea-august-2024-709c03129c.jpg",
        "https://gigxels.com/storage/md/photos/lupu-sebastian/bibi-ramnicu-valcea-august-2024-709c03129c.jpg",
    ],
    "primaria-ramnicu-valcea.jpg": [
        "https://upload.wikimedia.org/wikipedia/commons/a/ae/R-Valcea_Primarie_1.JPG",
    ],
}

HEADERS = {
    "User-Agent": "VâlceaClarEditorialPhotoFetcher/1.1 (+https://valceaclar.ro)",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def load_registry() -> dict[str, Any]:
    if not REGISTRY.exists():
        return {"stories": {}}
    value = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("story_visuals.json must contain a JSON object")
    stories = value.get("stories")
    if not isinstance(stories, dict):
        raise RuntimeError("story_visuals.json stories must contain a JSON object")
    return value


def registry_assets() -> dict[str, list[str]]:
    assets: dict[str, list[str]] = {}
    registry = load_registry()
    for story_id, visual in registry.get("stories", {}).items():
        if not isinstance(visual, dict):
            raise RuntimeError(f"visual registry entry is not an object: {story_id}")
        raw_path = str(visual.get("image_path", "")).strip()
        image = visual.get("image")
        if not raw_path or not isinstance(image, dict):
            raise RuntimeError(f"visual registry entry is incomplete: {story_id}")
        target = (ROOT / raw_path).resolve()
        if target != DEST and DEST not in target.parents:
            raise RuntimeError(f"story visual must be under approved photo root: {story_id}: {raw_path}")
        if target.suffix.lower() not in {".jpg", ".jpeg"}:
            raise RuntimeError(f"story visual must be a JPEG: {story_id}: {raw_path}")
        direct_url = str(image.get("direct_source_url", "")).strip()
        parsed = urllib.parse.urlparse(direct_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise RuntimeError(f"story visual lacks an HTTPS direct_source_url: {story_id}")
        required = ("source_type", "source_url", "credit", "rights_basis", "alt_text")
        missing = [key for key in required if not str(image.get(key, "")).strip()]
        if missing:
            raise RuntimeError(
                f"story visual rights/provenance metadata missing for {story_id}: {', '.join(missing)}"
            )
        if image.get("kind") != "photograph" or image.get("synthetic") is not False:
            raise RuntimeError(f"story visual is not a verified real photograph: {story_id}")
        if image.get("subject_match") is not True or image.get("editor_approved") is not True:
            raise RuntimeError(f"story visual lacks subject/editor approval: {story_id}")
        if image.get("contextual_archive") is True and not str(image.get("editorial_note", "")).strip():
            raise RuntimeError(f"archival story visual lacks disclosure note: {story_id}")
        filename = target.name
        if filename in assets and direct_url not in assets[filename]:
            raise RuntimeError(f"conflicting direct URLs for approved photo filename: {filename}")
        assets.setdefault(filename, []).append(direct_url)
    return assets


def all_assets() -> dict[str, list[str]]:
    merged = {filename: list(urls) for filename, urls in STATIC_ASSETS.items()}
    for filename, urls in registry_assets().items():
        bucket = merged.setdefault(filename, [])
        for url in urls:
            if url not in bucket:
                bucket.append(url)
    return merged


def valid_jpeg(data: bytes) -> bool:
    return len(data) >= 50_000 and data.startswith(b"\xff\xd8\xff") and data.rstrip().endswith(b"\xff\xd9")


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = (response.headers.get("Content-Type") or "").lower()
        data = response.read(15_000_000)
    if "image" not in content_type and not data.startswith(b"\xff\xd8\xff"):
        raise RuntimeError(f"not an image response ({content_type or 'unknown'}): {url}")
    if not valid_jpeg(data):
        raise RuntimeError(f"invalid or unexpectedly small JPEG ({len(data)} bytes): {url}")
    return data


def fetch_one(filename: str, urls: list[str]) -> None:
    errors: list[str] = []
    for attempt, url in enumerate(urls, start=1):
        try:
            data = download(url)
            target = (DEST / filename).resolve()
            if target.parent != DEST:
                raise RuntimeError(f"invalid approved photo filename: {filename}")
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, target)
            digest = hashlib.sha256(data).hexdigest()
            print(f"PHOTO_READY {filename} bytes={len(data)} sha256={digest} source={url}")
            return
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as exc:
            errors.append(f"{url}: {exc}")
            time.sleep(min(attempt * 2, 6))
    raise RuntimeError(f"unable to fetch {filename}: " + " | ".join(errors))


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)
    assets = all_assets()
    for filename, urls in assets.items():
        fetch_one(filename, urls)
    print(f"PHOTO_REGISTRY_READY assets={len(assets)} story_assets={len(registry_assets())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
