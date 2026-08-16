#!/usr/bin/env python3
"""Re-render premium story pages while preserving the canonical story integrity contract."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import premium_presentation as pp

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
FEED = RUNTIME / "live-feed.json"
MANIFEST = RUNTIME / "stiri" / "manifest.json"
NAVIGATION = ROOT / "site" / "navigation.json"
BASE = "https://valceaclar.ro"


def newsarticle(story: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    canonical = str(row.get("canonical") or story.get("canonical_url") or BASE + pp.story_path(story))
    published_at = str(row.get("published_at") or story.get("first_published_at") or "")
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    doc: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": story.get("headline"),
        "description": story.get("dek"),
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "datePublished": published_at,
        "inLanguage": "ro-RO",
        "articleSection": section,
        "author": {"@type": "Organization", "name": "VÂLCEA CLAR", "url": BASE + "/"},
        "publisher": {"@type": "Organization", "name": "VÂLCEA CLAR", "url": BASE + "/"},
    }
    image = row.get("image") if isinstance(row.get("image"), dict) else None
    if image and image.get("public_url"):
        doc["image"] = [str(image["public_url"])]
    return doc


def image_figure(story: dict[str, Any], row: dict[str, Any]) -> tuple[str, str]:
    image = row.get("image") if isinstance(row.get("image"), dict) else None
    if not image or not image.get("public_url"):
        return "", ""
    public_url = str(image["public_url"])
    relative_url = urlparse(public_url).path
    source_url = str(image.get("source_url") or "")
    credit = str(image.get("credit") or "Sursă foto verificată")
    note = ""
    if image.get("contextual_archive") is True:
        captured = str(image.get("captured_at") or "").strip()
        note = f'<span>Imagine de arhivă{(" · " + pp.esc(captured)) if captured else ""}</span> '
    source = (
        f'<a href="{pp.esc(source_url)}" rel="nofollow noopener">{pp.esc(credit)}</a>'
        if source_url else pp.esc(credit)
    )
    figure = (
        '<figure class="hero-photo" data-photo-provenance="verified">'
        f'<img src="{pp.esc(relative_url)}" alt="{pp.esc(story.get("headline"))}" loading="eager" decoding="async">'
        f'<figcaption>{note}Foto: {source}</figcaption></figure>'
    )
    meta = (
        f'<meta property="og:image" content="{pp.esc(public_url)}">'
        f'<meta property="og:image:alt" content="{pp.esc(story.get("headline"))}">'
    )
    return figure, meta


def related_block(row: dict[str, Any], stories_by_id: dict[str, dict[str, Any]], routes_by_id: dict[str, str]) -> str:
    ids = [str(value) for value in row.get("related_story_ids") or []]
    cards: list[str] = []
    for story_id in ids:
        story = stories_by_id.get(story_id)
        route = routes_by_id.get(story_id)
        if not story or not route:
            raise SystemExit(f"Missing related-story target {story_id}")
        section = str(story.get("section") or "ȘTIRI").replace("_", " ")
        cards.append(
            f'<a href="{pp.esc(route)}"><span>{pp.esc(section)}</span><strong>{pp.esc(story.get("headline"))}</strong></a>'
        )
    if not cards:
        return ""
    return (
        '<section class="related" data-crosslink-scope="publishable_full_story_only">'
        '<h2>Mai citește</h2><div class="related-grid">' + "".join(cards) + '</div></section>'
    )


def render_story(nav: dict[str, Any], story: dict[str, Any], row: dict[str, Any], stories_by_id: dict[str, dict[str, Any]], routes_by_id: dict[str, str]) -> str:
    canonical = str(row.get("canonical") or story.get("canonical_url") or BASE + pp.story_path(story))
    published_at = str(row.get("published_at") or story.get("first_published_at") or "")
    if not published_at:
        raise SystemExit(f"Missing stable datePublished for {story.get('id')}")
    figure, image_meta = image_figure(story, row)
    jsonld = json.dumps(newsarticle(story, row), ensure_ascii=False, separators=(",", ":"))
    extra_head = image_meta + f'<script type="application/ld+json">{jsonld}</script>'
    body_paras = "".join(f'<p>{pp.esc(p)}</p>' for p in story.get("paragraphs") or [] if str(p).strip())
    related = related_block(row, stories_by_id, routes_by_id)
    section = str(story.get("section") or "ȘTIRI").replace("_", " ")
    body = f'''<main><article class="article"><div class="kicker">{pp.esc(section)}</div><div class="story-meta">{pp.archive_label(story)}</div><h1>{pp.esc(story.get('headline'))}</h1><p class="dek">{pp.esc(story.get('dek'))}</p><div class="status">Publicat {pp.esc(published_at)} · informație locală verificată</div>{figure}{pp.factbox(story)}<div class="article-body">{body_paras}</div>{pp.rich_sections(story)}<section class="article-sources"><h2>Surse</h2><ul>{pp.source_links(story,list_mode=True)}</ul></section>{related}<a class="back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>'''
    return pp.shell(
        nav,
        title=f"{story.get('headline')} — VÂLCEA CLAR",
        description=str(story.get("dek") or ""),
        canonical=canonical,
        body=body,
        og_type="article",
        extra_head=extra_head,
    )


def rebuild() -> dict[str, Any]:
    nav = pp.load(NAVIGATION)
    feed = pp.load(FEED)
    manifest = pp.load(MANIFEST)
    stories = [item for item in feed.get("stories") or [] if isinstance(item, dict) and item.get("id")]
    stories_by_id = {str(item["id"]): item for item in stories}
    rows = [item for item in manifest.get("stories") or [] if isinstance(item, dict) and item.get("id")]
    routes_by_id = {str(row["id"]): str(row.get("path") or "") for row in rows}
    if set(stories_by_id) != set(routes_by_id):
        raise SystemExit("Premium story integrity: feed/manifest story IDs differ")
    for row in rows:
        story_id = str(row["id"])
        story = stories_by_id[story_id]
        target = RUNTIME / str(row.get("path") or pp.story_path(story)).strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_story(nav, story, row, stories_by_id, routes_by_id), encoding="utf-8")
    result = {"status":"PASS","stories":len(rows),"contract":"NewsArticle+verified-photo+manifest-crosslinks"}
    print(json.dumps(result, ensure_ascii=False))
    return result


def self_test() -> None:
    story = {"id":"a","headline":"Titlu","dek":"Descriere","section":"EVENIMENTE","first_published_at":"2026-08-15T10:00:00+03:00"}
    row = {"id":"a","canonical":"https://valceaclar.ro/stiri/a/","published_at":"2026-08-15T10:00:00+03:00","related_story_ids":[]}
    doc = newsarticle(story,row)
    assert doc["@type"] == "NewsArticle"
    assert doc["datePublished"] == row["published_at"]
    assert doc["mainEntityOfPage"]["@id"] == row["canonical"]
    assert "image" not in doc
    print("VÂLCEA CLAR premium story integrity self-test: PASS")


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args=parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    rebuild()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
