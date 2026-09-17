#!/usr/bin/env python3
"""Fetch approved, rights-documented real photographs for VÂLCEA CLAR.

Static editorial assets remain supported, while story-specific media is loaded
from story_visuals.json so a newly approved visual does not require a second
hard-coded downloader edit. Every remote image must have explicit provenance
and rights metadata in the registry. Rights/provenance and local-path errors
remain fail-closed. Remote fetch failures are isolated per asset so one
rate-limited or unavailable image cannot suppress distribution for unrelated
stories; the affected story remains without that photo and downstream media
eligibility/fallback rules decide its channel treatment.

For registry-backed story photographs, a transient remote failure may reuse the
last-known-good public runtime bytes only when the previous manifest and current
registry prove the exact same rights/provenance contract and the bytes match the
previous manifest SHA-256. This preserves a verified real photo without turning
stale or unverified media into a publication fallback.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEST = (ROOT / "valcea-clar" / "social" / "photos" / "approved").resolve()
REGISTRY = ROOT / "valcea-clar" / "social" / "story_visuals.json"
RUNTIME_MEDIA = ROOT / "valcea-clar" / "site" / "runtime" / "media" / "social"
RUNTIME_MANIFEST = RUNTIME_MEDIA / "manifest.json"
PUBLIC_BASE = "https://valceaclar.ro/media/social/"

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


class AssetFetchUnavailable(RuntimeError):
    """A rights-approved remote asset could not be fetched in this run."""


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


def registry_photo_contract(filename: str) -> dict[str, str] | None:
    """Return the unique current rights/provenance contract for a story photo.

    Static assets intentionally do not use LKG reuse. A runtime asset may only be
    recovered when the filename is still referenced by the current story visual
    registry and every referencing story agrees on the same rights contract.
    """
    contracts: set[tuple[str, str, str]] = set()
    for story_id, visual in load_registry().get("stories", {}).items():
        if not isinstance(visual, dict):
            continue
        raw_path = str(visual.get("image_path") or "").strip()
        if not raw_path:
            continue
        target = (ROOT / raw_path).resolve()
        if target.name != filename:
            continue
        if target != DEST and DEST not in target.parents:
            raise RuntimeError(f"story visual must be under approved photo root: {story_id}: {raw_path}")
        image = visual.get("image")
        if not isinstance(image, dict):
            raise RuntimeError(f"visual registry entry is incomplete: {story_id}")
        if image.get("kind") != "photograph" or image.get("synthetic") is not False:
            raise RuntimeError(f"story visual is not a verified real photograph: {story_id}")
        if image.get("subject_match") is not True or image.get("editor_approved") is not True:
            raise RuntimeError(f"story visual lacks subject/editor approval: {story_id}")
        contract = (
            str(image.get("credit") or "").strip(),
            str(image.get("rights_basis") or "").strip(),
            str(image.get("source_url") or "").strip(),
        )
        if not all(contract):
            raise RuntimeError(f"story visual LKG contract incomplete: {story_id}")
        contracts.add(contract)
    if not contracts:
        return None
    if len(contracts) != 1:
        raise RuntimeError(f"conflicting LKG rights/provenance contracts for {filename}")
    credit, rights_basis, source_url = next(iter(contracts))
    return {
        "credit": credit,
        "rights_basis": rights_basis,
        "source_url": source_url,
    }


def last_known_good_bytes(filename: str) -> bytes | None:
    """Return previously published bytes only when truth-bound to current approval.

    The runtime manifest is the durable proof of what was previously published.
    Reuse is rejected unless identity, rights/provenance, public URL and SHA-256
    all match the still-current story visual registry. Missing/invalid evidence is
    treated as no fallback, never as permission to publish an unverified image.
    """
    contract = registry_photo_contract(filename)
    if contract is None or not RUNTIME_MANIFEST.is_file():
        return None
    try:
        manifest = json.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    except Exception:
        return None
    if manifest.get("execution_owner") != "civora_site_engine":
        return None
    if manifest.get("canonical_base_url") != PUBLIC_BASE:
        return None
    rows = manifest.get("assets")
    if not isinstance(rows, list):
        return None
    matching = [row for row in rows if isinstance(row, dict) and row.get("filename") == filename]
    if len(matching) != 1:
        return None
    asset = matching[0]
    if asset.get("kind") != "source_photograph" or asset.get("synthetic") is not False:
        return None
    if asset.get("public_url") != PUBLIC_BASE + filename:
        return None
    for key in ("credit", "rights_basis", "source_url"):
        if str(asset.get(key) or "").strip() != contract[key]:
            return None
    expected_sha = str(asset.get("sha256") or "").strip().lower()
    if len(expected_sha) != 64:
        return None
    candidate = RUNTIME_MEDIA / filename
    if not candidate.is_file():
        return None
    data = candidate.read_bytes()
    if not valid_jpeg(data):
        return None
    if hashlib.sha256(data).hexdigest() != expected_sha:
        return None
    return data


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


def persist_target(target: Path, data: bytes) -> str:
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, target)
    return hashlib.sha256(data).hexdigest()


def fetch_one(filename: str, urls: list[str]) -> None:
    target = (DEST / filename).resolve()
    if target.parent != DEST:
        raise RuntimeError(f"invalid approved photo filename: {filename}")

    errors: list[str] = []
    for attempt, url in enumerate(urls, start=1):
        try:
            data = download(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, RuntimeError) as exc:
            errors.append(f"{url}: {exc}")
            time.sleep(min(attempt * 2, 6))
            continue

        digest = persist_target(target, data)
        print(f"PHOTO_READY {filename} bytes={len(data)} sha256={digest} source={url}")
        return

    lkg = last_known_good_bytes(filename)
    if lkg is not None:
        digest = persist_target(target, lkg)
        print(
            f"PHOTO_LKG_REUSED {filename} bytes={len(lkg)} sha256={digest} "
            "source=truth_bound_previous_runtime"
        )
        return

    raise AssetFetchUnavailable(f"unable to fetch {filename}: " + " | ".join(errors))


def self_test_lkg_contract() -> None:
    """Deterministically prove the LKG fallback accepts only exact current evidence."""
    global ROOT, DEST, REGISTRY, RUNTIME_MEDIA, RUNTIME_MANIFEST
    original = (ROOT, DEST, REGISTRY, RUNTIME_MEDIA, RUNTIME_MANIFEST)
    try:
        with tempfile.TemporaryDirectory() as raw_tmp:
            tmp = Path(raw_tmp).resolve()
            ROOT = tmp
            DEST = (tmp / "valcea-clar" / "social" / "photos" / "approved").resolve()
            REGISTRY = tmp / "valcea-clar" / "social" / "story_visuals.json"
            RUNTIME_MEDIA = tmp / "valcea-clar" / "site" / "runtime" / "media" / "social"
            RUNTIME_MANIFEST = RUNTIME_MEDIA / "manifest.json"
            DEST.mkdir(parents=True, exist_ok=True)
            REGISTRY.parent.mkdir(parents=True, exist_ok=True)
            RUNTIME_MEDIA.mkdir(parents=True, exist_ok=True)

            filename = "truth-bound-lkg.jpg"
            image_path = f"valcea-clar/social/photos/approved/{filename}"
            credit = "Example Photographer / Commons — CC BY 4.0"
            rights = "creative_commons"
            source_url = "https://commons.wikimedia.org/wiki/File:Example.jpg"
            registry = {
                "stories": {
                    "example-story": {
                        "image_path": image_path,
                        "image": {
                            "kind": "photograph",
                            "synthetic": False,
                            "subject_match": True,
                            "editor_approved": True,
                            "source_type": "wikimedia_commons",
                            "source_url": source_url,
                            "direct_source_url": "https://upload.wikimedia.org/example.jpg",
                            "credit": credit,
                            "rights_basis": rights,
                            "alt_text": "Verified example photograph",
                        },
                    }
                }
            }
            REGISTRY.write_text(json.dumps(registry), encoding="utf-8")
            data = b"\xff\xd8\xff" + (b"L" * 50_000) + b"\xff\xd9"
            digest = hashlib.sha256(data).hexdigest()
            (RUNTIME_MEDIA / filename).write_bytes(data)
            manifest = {
                "execution_owner": "civora_site_engine",
                "canonical_base_url": PUBLIC_BASE,
                "assets": [
                    {
                        "filename": filename,
                        "kind": "source_photograph",
                        "synthetic": False,
                        "sha256": digest,
                        "public_url": PUBLIC_BASE + filename,
                        "credit": credit,
                        "rights_basis": rights,
                        "source_url": source_url,
                    }
                ],
            }
            RUNTIME_MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")
            assert last_known_good_bytes(filename) == data

            changed = json.loads(json.dumps(manifest))
            changed["assets"][0]["credit"] = "Different credit"
            RUNTIME_MANIFEST.write_text(json.dumps(changed), encoding="utf-8")
            assert last_known_good_bytes(filename) is None

            RUNTIME_MANIFEST.write_text(json.dumps(manifest), encoding="utf-8")
            (RUNTIME_MEDIA / filename).write_bytes(data[:-3] + b"BAD")
            assert last_known_good_bytes(filename) is None

            (RUNTIME_MEDIA / filename).write_bytes(data)
            REGISTRY.write_text(json.dumps({"stories": {}}), encoding="utf-8")
            assert last_known_good_bytes(filename) is None
    finally:
        ROOT, DEST, REGISTRY, RUNTIME_MEDIA, RUNTIME_MANIFEST = original
    print("PHOTO_LKG_SELF_TEST PASS")


def main() -> int:
    # This is a safety invariant, not a network smoke test. It runs on every
    # invocation so the existing Social Publication Engine exercises the exact
    # LKG accept/reject path without adding another workflow or lane.
    self_test_lkg_contract()
    DEST.mkdir(parents=True, exist_ok=True)
    assets = all_assets()
    unavailable: list[tuple[str, str]] = []
    for filename, urls in assets.items():
        try:
            fetch_one(filename, urls)
        except AssetFetchUnavailable as exc:
            unavailable.append((filename, str(exc)))
            print(f"PHOTO_UNAVAILABLE {filename} reason={exc}")

    story_asset_count = len(registry_assets())
    print(
        f"PHOTO_REGISTRY_READY assets={len(assets)} story_assets={story_asset_count} "
        f"unavailable={len(unavailable)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
