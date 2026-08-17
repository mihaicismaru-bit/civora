#!/usr/bin/env python3
"""Preserve canonical story SEO/cross-linking under the public UX shell."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

import public_ux_reset as ux

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
ARCHIVE = SITE / "story_archive.json"
FEED = RUNTIME / "live-feed.json"
MANIFEST = RUNTIME / "stiri" / "manifest.json"
NAV = SITE / "navigation.json"
BASE = "https://valceaclar.ro"
RELATED_LIMIT = 4


def load(path: Path, default=None):
    if not path.is_file():
        return default if default is not None else {}
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def publication_stamp(story: dict, previous: dict, feed: dict) -> str:
    for value in (
        previous.get("published_at"),
        story.get("first_published_at"),
        story.get("last_seen_at"),
        feed.get("generated_at"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    raise SystemExit(f"Missing publication timestamp: {story.get('id')}")


def rank_related(story: dict, stories: list[dict]) -> list[dict]:
    sid = str(story.get("id"))
    section = str(story.get("section") or "")
    rows = [row for row in stories if str(row.get("id")) != sid]
    rows.sort(key=lambda row: (0 if str(row.get("section") or "") == section else 1, -int(row.get("priority") or 0), str(row.get("id") or "")))
    return rows[:RELATED_LIMIT]


def image_head_and_figure(image: dict | None, headline: str) -> tuple[str, str]:
    if not isinstance(image, dict) or image.get("provenance_status") != "VERIFIED" or not image.get("public_url"):
        return "", ""
    public_url = str(image["public_url"])
    source_url = str(image.get("source_url") or "")
    credit = str(image.get("credit") or "Sursă foto verificată")
    path = urlparse(public_url).path
    head = f'<meta property="og:image" content="{ux.esc(public_url)}">'
    figure = f'''<figure data-photo-provenance="verified"><img src="{ux.esc(path)}" alt="{ux.esc(headline)}" loading="eager" style="width:100%;display:block;margin:24px 0 7px"><figcaption style="font-size:11px;color:#6c665c">Foto: <a href="{ux.esc(source_url)}" rel="nofollow noopener">{ux.esc(credit)}</a></figcaption></figure>'''
    return head, figure


def jsonld(story: dict, canonical: str, published_at: str, image: dict | None) -> str:
    row = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": story.get("headline"),
        "description": story.get("dek"),
        "articleSection": str(story.get("section") or "ȘTIRI").replace("_", " "),
        "url": canonical,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "datePublished": published_at,
        "inLanguage": "ro-RO",
        "publisher": {"@type": "Organization", "name": "VÂLCEA CLAR", "url": BASE + "/"},
        "author": {"@type": "Organization", "name": "VÂLCEA CLAR", "url": BASE + "/"},
    }
    if isinstance(image, dict) and image.get("provenance_status") == "VERIFIED" and image.get("public_url"):
        row["image"] = [str(image["public_url"])]
    return '<script type="application/ld+json">' + json.dumps(row, ensure_ascii=False, separators=(",", ":")) + '</script>'


def render_story(nav: dict, story: dict, stories: list[dict], published_at: str, image: dict | None) -> str:
    canonical = str(story.get("canonical_url") or BASE + ux.story_path(story))
    head_image, figure = image_head_and_figure(image, str(story.get("headline") or ""))
    body_ps = "".join(f'<p>{ux.esc(p)}</p>' for p in story.get("paragraphs") or [])
    related = rank_related(story, stories)
    rel_html = ""
    if related:
        rel_html = '<section class="related" data-crosslink-scope="publishable_full_story_only"><h2>Mai citește</h2>' + "".join(
            f'<a href="{ux.esc(ux.story_path(row))}"><strong>{ux.esc(row.get("headline"))}</strong></a>' for row in related
        ) + '</section>'
    body = f'''<main><article class="article"><div class="kicker">{ux.esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}</div><h1>{ux.esc(story.get('headline'))}</h1><p class="dek">{ux.esc(story.get('dek'))}</p><div class="story-date">Publicat {ux.esc(published_at)}</div>{figure}{ux.factbox(story)}<div class="article-body">{body_ps}</div>{ux.rich_sections(story)}<section class="article-sources"><h2>Surse</h2><ul>{ux.source_links(story, True)}</ul></section>{rel_html}<a class="back" href="/stiri/">← Toate știrile</a></article></main>'''
    page = ux.shell(nav, title=f"{story.get('headline')} — VÂLCEA CLAR", description=str(story.get("dek") or ""), canonical=canonical, body=body)
    extra = head_image + jsonld(story, canonical, published_at, image)
    return page.replace("</head>", extra + "</head>")


def build() -> dict:
    nav = load(NAV)
    feed = load(FEED)
    archive = load(ARCHIVE, {"stories": []})
    previous_manifest = load(MANIFEST, {"stories": []})
    previous = {str(row.get("id")): row for row in previous_manifest.get("stories") or [] if isinstance(row, dict) and row.get("id")}
    stories, _live_ids = ux.union_stories(feed, archive)
    if not stories:
        raise SystemExit("Story integrity has no safe stories")

    archive["publication_model"] = "continuous_story_first"
    archive["recap_editions_may_delete_published_stories"] = False
    archive["operational_records_public"] = False
    archive["retention_policy"] = "published_full_stories_persist_after_recap_or_validity_window_expires"
    archive["story_count"] = len(stories)
    archive["stories"] = stories
    write(ARCHIVE, archive)

    rows = []
    for story in stories:
        sid = str(story.get("id"))
        old = previous.get(sid) or {}
        published_at = publication_stamp(story, old, feed)
        image = old.get("image") if isinstance(old.get("image"), dict) else None
        related = rank_related(story, stories)
        route = ux.story_path(story)
        canonical = BASE + route
        story["first_published_at"] = story.get("first_published_at") or published_at
        story["path"] = route
        story["canonical_url"] = canonical
        target = RUNTIME / route.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_story(nav, story, stories, published_at, image), encoding="utf-8")
        row = {
            "id": sid,
            "path": route,
            "canonical": canonical,
            "published_at": published_at,
            "archive_status": story.get("archive_status") or "published_archive",
            "active_now": bool(story.get("active_now")),
            "related_story_ids": [str(item.get("id")) for item in related],
            "structured_data_type": "NewsArticle",
            "public_ux_authorized": True,
        }
        if image:
            row["image"] = image
        rows.append(row)

    archive["stories"] = stories
    write(ARCHIVE, archive)
    manifest = {
        "schema_version": "2.1",
        "publication_model": "continuous_story_first",
        "homepage_presentation": "reader_newsroom",
        "news_index": "/stiri/",
        "operational_records_public": False,
        "cross_linking": {"enabled": True, "eligible_scope": "publishable_full_story_only"},
        "structured_data": {
            "enabled": True,
            "type": "NewsArticle",
            "eligible_scope": "publishable_full_story_only",
            "date_published_policy": "stable_publication_ledger_only",
            "verified_image_policy": "provenance_backed_real_photograph_only",
            "unverified_image_policy": "omit"
        },
        "stories": rows,
    }
    write(MANIFEST, manifest)
    print(json.dumps({"status":"PASS","stories":len(rows),"cross_links":sum(len(row["related_story_ids"]) for row in rows)}, ensure_ascii=False))
    return manifest


def check() -> None:
    archive = load(ARCHIVE)
    manifest = load(MANIFEST)
    archive_ids = {str(row.get("id")) for row in archive.get("stories") or []}
    manifest_ids = {str(row.get("id")) for row in manifest.get("stories") or []}
    if archive_ids != manifest_ids:
        raise SystemExit("Story integrity archive/manifest drift")
    for row in manifest.get("stories") or []:
        text = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if '<script type="application/ld+json">' not in text:
            raise SystemExit(f"NewsArticle JSON-LD missing: {row['id']}")
        if f"Publicat {row['published_at']}" not in text:
            raise SystemExit(f"Visible publication date missing: {row['id']}")
        if row.get("related_story_ids") and 'data-crosslink-scope="publishable_full_story_only"' not in text:
            raise SystemExit(f"Related block missing: {row['id']}")
    print("VÂLCEA CLAR public UX story integrity: PASS")


def self_test() -> None:
    sample = {"id":"a","section":"SPORT","headline":"Titlu","dek":"Descriere","sources":[{"url":"https://example.test","name":"Sursă"}]}
    other = {"id":"b","section":"SPORT","headline":"Altul","dek":"D","sources":[{"url":"https://example.test/b"}]}
    assert rank_related(sample, [sample, other])[0]["id"] == "b"
    assert "NewsArticle" in jsonld(sample, BASE+"/stiri/a/", "2026-08-18T00:00:00+03:00", None)
    print("VÂLCEA CLAR public UX story-integrity self-test: PASS")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        build()
