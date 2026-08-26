#!/usr/bin/env python3
"""Public photo acceptance probe for VÂLCEA CLAR story pages.

The canonical live feed may carry a verified ``visual`` for a story. That media
is considered publicly projected only when the fetched story HTML contains an
actual ``<img>`` element whose ``src`` is the expected canonical public URL.
OpenGraph/Twitter/JSON-LD metadata and repository manifests are deliberately
not accepted as proof of a visible article photograph.
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

ROOT = Path(__file__).resolve().parents[1]
FEED = ROOT / "site" / "runtime" / "live-feed.json"
DEFAULT_BASE = "https://valceaclar.ro"
USER_AGENT = "VALCEA-CLAR-Public-Media/1.0 (+https://valceaclar.ro/)"


class ImageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        row = {str(k).lower(): str(v or "") for k, v in attrs}
        self.images.append(row)


def fetch(url: str, timeout: int = 20) -> tuple[int | None, str, str | None]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return int(response.status), response.read(2_000_000).decode("utf-8", errors="replace"), None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), body, f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


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


def visible_image_match(document: str, expected_url: str) -> tuple[bool, list[str]]:
    parser = ImageParser()
    try:
        parser.feed(document)
    except Exception:
        return False, []
    expected = html_lib.unescape(expected_url).strip()
    sources = [html_lib.unescape(row.get("src", "")).strip() for row in parser.images]
    return expected in sources, sources


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

    checks: list[dict[str, Any]] = []
    for story, visual in eligible:
        path = str(story["path"])
        expected_url = str(visual["public_url"])
        status, document, error = fetch(base_url.rstrip("/") + path)
        matched, sources = visible_image_match(document, expected_url) if status == 200 else (False, [])
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
                "media_marker_present": provenance_marker,
                "img_sources_found": sources[:12],
                "ok": ok,
                "error": error,
            }
        )

    blockers = [str(row["path"]) for row in checks if not row["ok"]]
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR public story media acceptance",
        "base_url": base_url.rstrip("/"),
        "canonical_feed_generated_at": feed.get("generated_at"),
        "eligible_verified_visual_count": len(eligible),
        "checked_count": len(checks),
        "ready": bool(checks) and not blockers,
        "status": "READY" if checks and not blockers else "BLOCKED",
        "checks": checks,
        "blockers": blockers or ([] if checks else ["__no_verified_visuals_checked__"]),
        "visible_img_required": True,
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
    ok, _ = visible_image_match('<img src="https://example.test/photo.jpg" alt="x">', "https://example.test/photo.jpg")
    assert ok
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
