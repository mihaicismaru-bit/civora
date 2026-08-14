#!/usr/bin/env python3
"""Fetch approved, rights-documented real photographs for VÂLCEA CLAR.

The files are downloaded only inside GitHub Actions and are not discovered
algorithmically. Every URL is paired with explicit provenance in the curated
Facebook outbox. Downloads fail closed on HTTP, file type or size errors.
"""
from __future__ import annotations

import hashlib
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEST = ROOT / "valcea-clar" / "social" / "photos" / "approved"

ASSETS: dict[str, list[str]] = {
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
    "User-Agent": "VâlceaClarEditorialPhotoFetcher/1.0 (+https://valceaclar.ro)",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


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
            target = DEST / filename
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
    for filename, urls in ASSETS.items():
        fetch_one(filename, urls)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
