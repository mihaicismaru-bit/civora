#!/usr/bin/env python3
"""Preserve canonical story SEO/cross-linking under the public UX shell.

The durable published story archive is an input to this presentation layer, not
an output. Public UX may decide which archived stories belong in the reader
news surface, but it must never delete or rewrite durable publication history.

Story pages also own the canonical article Open Graph/Twitter contract. The
premium presentation renderer therefore resolves current provenance-backed
photographs directly and must never regress a story URL to homepage-style social
metadata when the public shell is refreshed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import public_ux_reset as ux

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
ARCHIVE = SITE / "story_archive.json"
FEED = RUNTIME / "live-feed.json"
MANIFEST = RUNTIME / "stiri" / "manifest.json"
NAV = SITE / "navigation.json"
VISUALS = ROOT / "social" / "story_visuals.json"
MEDIA_MANIFEST = RUNTIME / "media" / "social" / "manifest.json"
MEDIA_DIR = RUNTIME / "media" / "social"
MEDIA_BASE_URL = "https://valceaclar.ro/media/social/"
BASE = "https://valceaclar.ro"
RELATED_LIMIT = 4

LOCAL_NEWS_CORE = REPO / "local-news-os" / "core"
if str(LOCAL_NEWS_CORE) not in sys.path:
    sys.path.insert(0, str(LOCAL_NEWS_CORE))
from verified_story_media import resolve_verified_story_image  # noqa: E402


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


def verified_image_for_story(story_id: str, visual_registry: dict, asset_manifest: dict) -> dict | None:
    """Resolve current media truth directly; stale manifest image rows are not trusted."""
    return resolve_verified_story_image(
        story_id,
        visual_registry,
        asset_manifest,
        runtime_asset_dir=MEDIA_DIR,
        canonical_media_base_url=MEDIA_BASE_URL,
    )


def image_head_and_figure(image: dict | None, headline: str) -> tuple[str, str]:
    if not isinstance(image, dict) or image.get("provenance_status") != "VERIFIED" or not image.get("public_url"):
        return "", ""
    public_url = str(image["public_url"])
    source_url = str(image.get("source_url") or "")
    credit = str(image.get("credit") or "Sursă foto verificată")
    alt_text = str(image.get("alt_text") or headline)
    path = urlparse(public_url).path
    head = (
        f'<meta property="og:image" content="{ux.esc(public_url)}">'
        f'<meta property="og:image:alt" content="{ux.esc(alt_text)}">'
        f'<meta name="twitter:image" content="{ux.esc(public_url)}">'
        f'<meta name="twitter:image:alt" content="{ux.esc(alt_text)}">'
    )
    disclosure = ""
    if image.get("contextual_archive") is True and image.get("editorial_note"):
        disclosure = f' · {ux.esc(image.get("editorial_note"))}'
    figure = f'''<figure data-photo-provenance="verified"><img src="{ux.esc(path)}" alt="{ux.esc(alt_text)}" loading="eager" style="width:100%;display:block;margin:24px 0 7px"><figcaption style="font-size:11px;color:#6c665c">Foto: <a href="{ux.esc(source_url)}" rel="nofollow noopener">{ux.esc(credit)}</a>{disclosure}</figcaption></figure>'''
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


def article_social_head(story: dict, image: dict | None) -> str:
    headline = str(story.get("headline") or "")
    description = str(story.get("dek") or "")
    card = "summary_large_image" if image else "summary"
    return (
        '<meta property="og:type" content="article">'
        f'<meta name="twitter:card" content="{card}">'
        f'<meta name="twitter:title" content="{ux.esc(headline)}">'
        f'<meta name="twitter:description" content="{ux.esc(description)}">'
    )


def render_story(nav: dict, story: dict, stories: list[dict], published_at: str, image: dict | None) -> str:
    canonical = str(story.get("canonical_url") or BASE + ux.story_path(story))
    headline = str(story.get("headline") or "")
    head_image, figure = image_head_and_figure(image, headline)
    body_ps = "".join(f'<p>{ux.esc(p)}</p>' for p in story.get("paragraphs") or [])
    related = rank_related(story, stories)
    rel_html = ""
    if related:
        rel_html = '<section class="related" data-crosslink-scope="publishable_full_story_only"><h2>Mai citește</h2>' + "".join(
            f'<a href="{ux.esc(ux.story_path(row))}"><strong>{ux.esc(row.get("headline"))}</strong></a>' for row in related
        ) + '</section>'
    body = f'''<main><article class="article"><div class="kicker">{ux.esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}</div><h1>{ux.esc(headline)}</h1><p class="dek">{ux.esc(story.get('dek'))}</p><div class="story-date">Publicat {ux.esc(published_at)}</div>{figure}{ux.factbox(story)}<div class="article-body">{body_ps}</div>{ux.rich_sections(story)}<section class="article-sources"><h2>Surse</h2><ul>{ux.source_links(story, True)}</ul></section>{rel_html}<a class="back" href="/stiri/">← Toate știrile</a></article></main>'''
    document_title = f"{headline} — VÂLCEA CLAR"
    page = ux.shell(nav, title=document_title, description=str(story.get("dek") or ""), canonical=canonical, body=body)

    # The shared shell uses the document title for og:title. Article cards must
    # expose the editorial headline only, otherwise Facebook's cached card does
    # not match the story publication product.
    shell_og_title = f'<meta property="og:title" content="{ux.esc(document_title)}">'
    article_og_title = f'<meta property="og:title" content="{ux.esc(headline)}">'
    if shell_og_title not in page:
        raise SystemExit(f"Shared shell OG title contract changed: {story.get('id')}")
    page = page.replace(shell_og_title, article_og_title, 1)

    extra = article_social_head(story, image) + head_image + jsonld(story, canonical, published_at, image)
    return page.replace("</head>", extra + "</head>", 1)


def reader_stories(feed: dict, archive: dict) -> list[dict]:
    """Return the safe presentation subset without mutating durable inputs."""
    stories, _live_ids = ux.union_stories(feed, archive)
    return stories


def build() -> dict:
    nav = load(NAV)
    feed = load(FEED)
    archive = load(ARCHIVE, {"stories": []})
    previous_manifest = load(MANIFEST, {"stories": []})
    previous = {str(row.get("id")): row for row in previous_manifest.get("stories") or [] if isinstance(row, dict) and row.get("id")}
    visual_registry = load(VISUALS, {"policy": {}, "stories": {}})
    asset_manifest = load(MEDIA_MANIFEST, {"assets": []})
    stories = reader_stories(feed, archive)
    if not stories:
        raise SystemExit("Story integrity has no safe stories")

    rows = []
    for story in stories:
        sid = str(story.get("id"))
        old = previous.get(sid) or {}
        published_at = publication_stamp(story, old, feed)
        image = verified_image_for_story(sid, visual_registry, asset_manifest)
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
            "social_metadata_type": "article",
            "public_ux_authorized": True,
        }
        if image:
            row["image"] = image
        rows.append(row)

    manifest = {
        "schema_version": "2.2",
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
        "social_metadata": {
            "enabled": True,
            "og_type": "article",
            "og_title_policy": "editorial_headline_only",
            "twitter_cards": True,
            "verified_image_policy": "same_provenance_backed_real_photograph_as_article"
        },
        "stories": rows,
    }
    write(MANIFEST, manifest)
    print(json.dumps({"status":"PASS","stories":len(rows),"cross_links":sum(len(row["related_story_ids"]) for row in rows),"verified_images":sum(1 for row in rows if row.get("image"))}, ensure_ascii=False))
    return manifest


def check() -> None:
    feed = load(FEED)
    archive = load(ARCHIVE, {"stories": []})
    manifest = load(MANIFEST)
    expected_ids = {str(row.get("id")) for row in reader_stories(feed, archive) if row.get("id")}
    manifest_ids = {str(row.get("id")) for row in manifest.get("stories") or [] if row.get("id")}
    if expected_ids != manifest_ids:
        raise SystemExit("Story integrity reader-set/manifest drift")
    for row in manifest.get("stories") or []:
        text = (RUNTIME / str(row["path"]).strip("/") / "index.html").read_text(encoding="utf-8")
        if '<script type="application/ld+json">' not in text:
            raise SystemExit(f"NewsArticle JSON-LD missing: {row['id']}")
        if f"Publicat {row['published_at']}" not in text:
            raise SystemExit(f"Visible publication date missing: {row['id']}")
        if row.get("related_story_ids") and 'data-crosslink-scope="publishable_full_story_only"' not in text:
            raise SystemExit(f"Related block missing: {row['id']}")
        if '<meta property="og:type" content="article">' not in text:
            raise SystemExit(f"Article Open Graph type missing: {row['id']}")
        if text.count('<meta property="og:title"') != 1:
            raise SystemExit(f"Article must expose exactly one og:title: {row['id']}")
        if '<meta name="twitter:card"' not in text or '<meta name="twitter:title"' not in text:
            raise SystemExit(f"Twitter card metadata missing: {row['id']}")
        if row.get("image"):
            public_url = str(row["image"].get("public_url") or "")
            if not public_url or f'<meta property="og:image" content="{ux.esc(public_url)}">' not in text:
                raise SystemExit(f"Verified article image missing from Open Graph: {row['id']}")
            if f'<meta name="twitter:image" content="{ux.esc(public_url)}">' not in text:
                raise SystemExit(f"Verified article image missing from Twitter card: {row['id']}")
    print("VÂLCEA CLAR public UX story integrity: PASS")


def self_test() -> None:
    sample = {"id":"a","section":"SPORT","headline":"Titlu","dek":"Descriere","sources":[{"url":"https://example.test","name":"Sursă"}]}
    other = {"id":"b","section":"SPORT","headline":"Altul","dek":"D","sources":[{"url":"https://example.test/b"}]}
    assert rank_related(sample, [sample, other])[0]["id"] == "b"
    assert "NewsArticle" in jsonld(sample, BASE+"/stiri/a/", "2026-08-18T00:00:00+03:00", None)
    archive = {"stories": [dict(sample)]}
    feed = {"stories": [dict(other)]}
    archive_before = json.loads(json.dumps(archive))
    selected = reader_stories(feed, archive)
    assert {row["id"] for row in selected} == {"a", "b"}
    assert archive == archive_before, "reader selection must not mutate durable archive input"

    nav = {"contract_id":"test","brand":"VÂLCEA CLAR","tagline":"Test","items":[],"footer":{"links":[],"line":"Test"}}
    rendered = render_story(nav, sample, [sample, other], "2026-08-18T00:00:00+03:00", None)
    assert '<meta property="og:type" content="article">' in rendered
    assert '<meta property="og:title" content="Titlu">' in rendered
    assert '<meta property="og:title" content="Titlu — VÂLCEA CLAR">' not in rendered
    assert '<meta name="twitter:card" content="summary">' in rendered
    assert rendered.count('<meta property="og:title"') == 1
    print("VÂLCEA CLAR public UX story-integrity self-test: PASS")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    elif "--check" in sys.argv:
        check()
    else:
        build()
