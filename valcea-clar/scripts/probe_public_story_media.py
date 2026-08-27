#!/usr/bin/env python3
"""Public photo acceptance probe for VÂLCEA CLAR story pages.

The canonical live feed may carry a verified ``visual`` for a story. That media
is considered publicly projected only when the fetched story HTML contains a
real ``<img>`` whose bytes are publicly readable and whose public delivery can
be traced back to the exact canonical CIVORA visual.

Two delivery forms are accepted:
1. the visible ``img.src`` is the canonical ``visual.public_url`` itself; or
2. the visible ``img.src`` is a local ``/media/...`` mirror and the *deployed*
   ``/media/provenance.json`` maps that local asset to the exact canonical
   ``visual.public_url``. Repository manifests and metadata alone are never
   publication proof.
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "site" / "runtime" / "live-feed.json"
DEFAULT_BASE = "https://valceaclar.ro"
USER_AGENT = "VALCEA-CLAR-Public-Media/1.1 (+https://valceaclar.ro/)"
MAX_HTML_BYTES = 2_000_000
MAX_MEDIA_BYTES = 12 * 1024 * 1024


class ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        row = {str(k).lower(): str(v or "") for k, v in attrs}
        self.images.append(row)


def fetch_bytes(url: str, timeout: int = 20, limit: int = MAX_MEDIA_BYTES) -> tuple[int | None, bytes, str, str | None]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(limit + 1)
            if len(body) > limit:
                return int(response.status), body[:limit], str(response.headers.get("content-type") or "").lower(), "body_too_large"
            return int(response.status), body, str(response.headers.get("content-type") or "").lower(), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(min(limit, 200_000))
        except Exception:
            body = b""
        return int(exc.code), body, str(exc.headers.get("content-type") or "").lower(), f"HTTP {exc.code}"
    except Exception as exc:
        return None, b"", "", f"{type(exc).__name__}: {exc}"


def fetch(url: str, timeout: int = 20) -> tuple[int | None, str, str | None]:
    status, body, _content_type, error = fetch_bytes(url, timeout=timeout, limit=MAX_HTML_BYTES)
    return status, body.decode("utf-8", errors="replace"), error


def fetch_public_provenance(base_url: str) -> tuple[dict[str, Any], str | None]:
    url = base_url.rstrip("/") + "/media/provenance.json"
    status, body, content_type, error = fetch_bytes(url, limit=2_000_000)
    if status != 200:
        return {}, error or f"HTTP {status}"
    if "json" not in content_type:
        return {}, f"unexpected provenance content-type: {content_type or 'missing'}"
    try:
        doc = json.loads(body.decode("utf-8"))
    except Exception as exc:
        return {}, f"invalid provenance JSON: {type(exc).__name__}: {exc}"
    if not isinstance(doc, dict):
        return {}, "invalid provenance root"
    if doc.get("mirror_failures"):
        return {}, f"deployed mirror failures: {doc.get('mirror_failures')}"
    assets = doc.get("assets")
    if not isinstance(assets, dict):
        return {}, "deployed provenance assets missing"
    return assets, None


def eligible_visual(story: dict[str, Any]) -> dict[str, Any] | None:
    visual = story.get("visual")
    if not isinstance(visual, dict):
        return None
    if visual.get("provenance_status") != "VERIFIED":
        return None
    if visual.get("synthetic") is True:
        return None
    public_url = str(visual.get("public_url") or "").strip()
    if not public_url.startswith(("https://", "http://")):
        return None
    if visual.get("contextual_archive") is True and not str(visual.get("editorial_note") or "").strip():
        return None
    return visual


def image_sources(document: str) -> list[str]:
    parser = ImageParser()
    try:
        parser.feed(document)
    except Exception:
        return []
    return [html_lib.unescape(row.get("src", "")).strip() for row in parser.images if row.get("src")]


def visible_image_match(document: str, expected_url: str) -> tuple[bool, list[str]]:
    """Legacy/exact public URL match, preserved as the strict first acceptance path."""
    expected = html_lib.unescape(expected_url).strip()
    sources = image_sources(document)
    return expected in sources, sources


def _local_media_name(base_url: str, src: str) -> str | None:
    absolute = urljoin(base_url.rstrip("/") + "/", src)
    base = urlparse(base_url.rstrip("/"))
    parsed = urlparse(absolute)
    if parsed.scheme not in {"http", "https"} or parsed.netloc != base.netloc:
        return None
    if not parsed.path.startswith("/media/") or parsed.path == "/media/provenance.json":
        return None
    name = Path(parsed.path).name
    return name or None


def _looks_like_image(body: bytes) -> bool:
    return (
        body.startswith(b"\xff\xd8\xff")
        or body.startswith(b"\x89PNG\r\n\x1a\n")
        or (len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP")
    )


def verified_visible_delivery(
    base_url: str,
    sources: list[str],
    expected_url: str,
    provenance_assets: dict[str, Any],
) -> tuple[bool, str | None, str | None]:
    expected = html_lib.unescape(expected_url).strip()
    for src in sources:
        src = html_lib.unescape(src).strip()
        if not src:
            continue
        absolute = urljoin(base_url.rstrip("/") + "/", src)
        if src == expected or absolute == expected:
            status, body, content_type, error = fetch_bytes(absolute)
            if status == 200 and _looks_like_image(body) and (content_type.startswith("image/") or _looks_like_image(body)):
                return True, src, "canonical_public_url"
            continue

        name = _local_media_name(base_url, src)
        if not name:
            continue
        asset = provenance_assets.get(name)
        if not isinstance(asset, dict):
            continue
        if str(asset.get("origin_url") or "").strip() != expected:
            continue
        provenance_status = str(asset.get("provenance_status") or "").strip()
        if provenance_status and provenance_status != "VERIFIED":
            continue
        status, body, content_type, error = fetch_bytes(absolute)
        if status != 200 or error:
            continue
        if not _looks_like_image(body):
            continue
        if content_type and not content_type.startswith("image/"):
            continue
        return True, src, "verified_local_mirror"
    return False, None, None


def evaluate(base_url: str, limit: int | None = None) -> dict[str, Any]:
    feed = json.loads(FEED.read_text(encoding="utf-8"))
    stories = [row for row in (feed.get("stories") or []) if isinstance(row, dict)]
    eligible: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for story in stories:
        visual = eligible_visual(story)
        path = str(story.get("path") or "")
        if visual and path.startswith("/stiri/") and path.endswith("/"):
            eligible.append((story, visual))
    if limit is not None:
        eligible = eligible[: max(0, limit)]

    provenance_assets, provenance_error = fetch_public_provenance(base_url)
    checks: list[dict[str, Any]] = []
    for story, visual in eligible:
        path = str(story["path"])
        expected_url = str(visual["public_url"])
        status, document, error = fetch(base_url.rstrip("/") + path)
        sources = image_sources(document) if status == 200 else []
        matched, matched_src, delivery = (
            verified_visible_delivery(base_url, sources, expected_url, provenance_assets)
            if status == 200
            else (False, None, None)
        )
        provenance_marker = (
            'data-photo-provenance="verified"' in document
            or "data-media-contract=" in document
            or f'data-story-image="{story.get("id", "")}"' in document
        )
        ok = status == 200 and matched
        checks.append(
            {
                "story_id": story.get("id"),
                "path": path,
                "http_status": status,
                "expected_public_url": expected_url,
                "visible_img_match": matched,
                "matched_img_src": matched_src,
                "delivery_mode": delivery,
                "media_marker_present": provenance_marker,
                "img_sources_found": sources[:12],
                "ok": ok,
                "error": error,
            }
        )

    blockers = [str(row["path"]) for row in checks if not row["ok"]]
    if provenance_error and eligible:
        blockers.insert(0, "__public_media_provenance__")
    return {
        "schema_version": "1.1",
        "product": "VÂLCEA CLAR public story media acceptance",
        "base_url": base_url.rstrip("/"),
        "canonical_feed_generated_at": feed.get("generated_at"),
        "eligible_verified_visual_count": len(eligible),
        "checked_count": len(checks),
        "public_provenance_assets": len(provenance_assets),
        "public_provenance_error": provenance_error,
        "ready": bool(checks) and not blockers,
        "status": "READY" if checks and not blockers else "BLOCKED",
        "checks": checks,
        "blockers": blockers or ([] if checks else ["__no_verified_visuals_checked__"]),
        "visible_img_required": True,
        "visible_image_bytes_required": True,
        "local_mirror_requires_exact_public_provenance_origin": True,
        "metadata_only_is_not_publication_proof": True,
        "repository_is_not_publication_proof": True,
    }


def self_test() -> None:
    story = {
        "visual": {
            "public_url": "https://example.test/photo.jpg",
            "provenance_status": "VERIFIED",
            "synthetic": False,
        }
    }
    assert eligible_visual(story)
    ok, _ = visible_image_match('<meta property="og:image" content="https://example.test/photo.jpg">', "https://example.test/photo.jpg")
    assert not ok
    ok, sources = visible_image_match('<img src="https://example.test/photo.jpg" alt="x">', "https://example.test/photo.jpg")
    assert ok and sources
    assert _local_media_name("https://valceaclar.ro", "/media/example.jpg") == "example.jpg"
    assert _local_media_name("https://valceaclar.ro", "https://other.example/media/example.jpg") is None
    contextual = {
        "visual": {
            "public_url": "https://example.test/photo.jpg",
            "provenance_status": "VERIFIED",
            "contextual_archive": True,
            "editorial_note": "",
        }
    }
    assert eligible_visual(contextual) is None
    print("public story media self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    report = evaluate(args.base_url, limit=args.limit)
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
