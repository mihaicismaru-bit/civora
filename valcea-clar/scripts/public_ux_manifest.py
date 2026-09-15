#!/usr/bin/env python3
"""Clean non-news routes without erasing already-published full articles.

The Public UX projector is a derived presentation writer. It may decide which
stories belong in the current reader set, but falling out of that set is not a
retraction. An existing route that still proves the complete NewsArticle
contract is therefore preserved unless an explicit current publication hold
suppresses it. The projector never resurrects deleted Git history and never
adds preserved archive-only routes back into the current manifest.
"""
from __future__ import annotations

import html
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
STATE = SITE / "public_ux_state.json"
HOLDS = ROOT / "editorial" / "publication_holds.json"
STORY_ROOT = RUNTIME / "stiri"
MANIFEST = STORY_ROOT / "manifest.json"
BASE = "https://valceaclar.ro"

LEGACY_NON_NEWS_REDIRECTS = {
    "/stiri/ansambluri-rezidentiale-ramnicu-valcea/": "/stiri/",
}


def load(path: Path, default=None) -> dict:
    if not path.is_file():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def redirect_html(target: str) -> str:
    return f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,follow"><link rel="canonical" href="{BASE}{target}"><meta http-equiv="refresh" content="0; url={target}"><title>Material mutat — VÂLCEA CLAR</title></head><body><p>Acest material nu mai este clasificat ca știre. <a href="{target}">Vezi știrile VÂLCEA CLAR</a>.</p></body></html>'''


def held_ids() -> set[str]:
    doc = load(HOLDS, {"holds": []})
    return {
        str(row.get("story_id"))
        for row in doc.get("holds") or []
        if isinstance(row, dict)
        and row.get("story_id")
        and row.get("public_projection") is False
    }


def text_only(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def published_route_contract(story_id: str, raw: str) -> bool:
    """Prove that an existing route is a complete previously published article."""
    canonical = f"{BASE}/stiri/{story_id}/"
    if f'<link rel="canonical" href="{canonical}">' not in raw:
        return False

    article = None
    for match in re.findall(r'<script type="application/ld\+json">(.*?)</script>', raw, flags=re.S):
        try:
            value = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("@type") == "NewsArticle":
            article = value
            break
    if not isinstance(article, dict) or str(article.get("url") or "") != canonical:
        return False

    headline = str(article.get("headline") or "").strip()
    published_at = str(article.get("datePublished") or "").strip()
    if not headline or not published_at:
        return False

    h1 = re.search(r"<h1>(.*?)</h1>", raw, flags=re.S)
    body = re.search(r'<div class="article-body">(.*?)</div>', raw, flags=re.S)
    sources = re.search(r'<section class="article-sources">(.*?)</section>', raw, flags=re.S)
    if not h1 or text_only(h1.group(1)) != headline:
        return False
    if not body or not re.findall(r"<p>.*?</p>", body.group(1), flags=re.S):
        return False
    if not sources or not re.findall(r'<a href="https?://', sources.group(1)):
        return False
    return True


def build() -> dict:
    state = load(STATE)
    manifest = load(MANIFEST)
    safe_ids = {str(value) for value in state.get("story_ids") or []}
    manifest_ids = {str(row.get("id")) for row in manifest.get("stories") or [] if row.get("id")}
    if not safe_ids or safe_ids != manifest_ids:
        raise SystemExit("Public UX cleanup requires the integrity manifest to match the safe story set")

    held = held_ids()
    preserved: list[str] = []
    removed: list[str] = []
    STORY_ROOT.mkdir(parents=True, exist_ok=True)
    for child in STORY_ROOT.iterdir():
        if not child.is_dir() or child.name in safe_ids:
            continue
        route = f"/stiri/{child.name}/"
        if route in LEGACY_NON_NEWS_REDIRECTS:
            continue

        page = child / "index.html"
        raw = page.read_text(encoding="utf-8") if page.is_file() else ""
        # Explicit current holds are authoritative. Otherwise a fully formed
        # NewsArticle is durable publication evidence and must not be pruned by
        # this derived reader-set projector merely because it aged out of feed.
        if child.name not in held and raw and published_route_contract(child.name, raw):
            preserved.append(child.name)
            continue
        shutil.rmtree(child)
        removed.append(child.name)

    redirects = []
    for source, target in LEGACY_NON_NEWS_REDIRECTS.items():
        page = RUNTIME / source.strip("/") / "index.html"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(redirect_html(target), encoding="utf-8")
        redirects.append({"path": source, "target": target, "robots": "noindex,follow"})

    state["legacy_non_news_redirects"] = redirects
    state["published_route_durability"] = {
        "policy": "preserve_existing_complete_newsarticle_unless_explicitly_held",
        "current_manifest_unchanged": True,
        "preserved_archive_only_story_ids": sorted(preserved),
        "removed_non_news_or_held_story_ids": sorted(removed),
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "safe_story_routes": len(manifest_ids),
        "preserved_archive_only_routes": len(preserved),
        "removed_non_news_or_held_routes": len(removed),
        "legacy_redirects": len(redirects),
    }, ensure_ascii=False))
    return state


def check() -> None:
    state = load(STATE)
    manifest = load(MANIFEST)
    ids = {str(row.get("id")) for row in manifest.get("stories") or [] if row.get("id")}
    if ids != {str(value) for value in state.get("story_ids") or []}:
        raise SystemExit("Public UX story manifest drift")
    for row in manifest.get("stories") or []:
        page = RUNTIME / str(row["path"]).strip("/") / "index.html"
        if not page.is_file():
            raise SystemExit(f"Missing safe story route: {row['path']}")
        if not row.get("published_at") or not row.get("related_story_ids"):
            raise SystemExit(f"Story integrity metadata missing: {row['id']}")

    held = held_ids()
    durability = state.get("published_route_durability") or {}
    for story_id in durability.get("preserved_archive_only_story_ids") or []:
        if story_id in held:
            raise SystemExit(f"Held story survived Public UX cleanup: {story_id}")
        page = STORY_ROOT / str(story_id) / "index.html"
        if not page.is_file() or not published_route_contract(str(story_id), page.read_text(encoding="utf-8")):
            raise SystemExit(f"Preserved route lost durable NewsArticle contract: {story_id}")

    for row in state.get("legacy_non_news_redirects") or []:
        text = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if 'noindex,follow' not in text or str(row["target"]) not in text:
            raise SystemExit(f"Legacy redirect invalid: {row['path']}")
    print("VÂLCEA CLAR public UX cleanup + durable published-route validation: PASS")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        check()
    else:
        build()
