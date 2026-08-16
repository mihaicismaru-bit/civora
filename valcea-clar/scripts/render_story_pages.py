#!/usr/bin/env python3
"""Render canonical per-story pages for the continuous VÂLCEA CLAR newsroom.

A story page is created only for items that pass the same full-story gate used
by the live newsroom. Morning/evening recap documents remain compatibility
snapshots and are never the canonical URL of an individual story.
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "local-news-os" / "core"))

from article_structured_data import build_newsarticle, reconcile_publication_dates, serialize_jsonld
from indexing_assets import write_indexing_assets
from related_stories import rank_related
from newsroom_decide import story_ready

ROOT = Path(__file__).resolve().parents[1]
POINTER = ROOT / "site" / "current_edition.json"
RUNTIME = ROOT / "site" / "runtime"
DECISION = ROOT / "site" / "newsroom_decision.json"
PUBLICATION_EVENT = ROOT / "site" / "story_publication_event.json"
BASE = "https://valceaclar.ro"
PUBLISHER_NAME = "VÂLCEA CLAR"
RELATED_LIMIT = 3


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_optional(path: Path) -> dict:
    return load(path) if path.exists() else {}


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def slug_for(item: dict) -> str:
    value = str(item.get("id") or "story").strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "story"


def route_for(item: dict) -> str:
    return f"/stiri/{slug_for(item)}/"


def source_links(item: dict) -> str:
    links = []
    for source in item.get("sources", []):
        url = str(source.get("url") or "").strip()
        if not url:
            continue
        name = esc(source.get("name") or "Sursă")
        links.append(f'<li><a href="{esc(url)}" rel="nofollow noopener">{name}</a></li>')
    return "".join(links)


def related_links(item: dict, stories: list[dict]) -> str:
    related = rank_related(item, stories, limit=RELATED_LIMIT)
    if not related:
        return ""
    cards = []
    for story in related:
        section = str(story.get("section") or "ȘTIRI").replace("_", " ")
        cards.append(
            f'<li><a href="{esc(route_for(story))}">'
            f'<span>{esc(section)}</span><strong>{esc(story.get("headline"))}</strong>'
            "</a></li>"
        )
    return (
        '<section class="related" data-crosslink-scope="publishable_full_story_only">'
        "<h2>Mai citește</h2><ul>"
        + "".join(cards)
        + "</ul></section>"
    )


def structured_data(item: dict, canonical: str, published_at: str | None) -> str:
    section = str(item.get("section") or "ȘTIRI").replace("_", " ")
    document = build_newsarticle(
        headline=item.get("headline"),
        canonical_url=canonical,
        publisher_name=PUBLISHER_NAME,
        publisher_url=BASE + "/",
        description=item.get("dek"),
        article_section=section,
        date_published=published_at,
        language="ro-RO",
        author_name=PUBLISHER_NAME,
        author_url=BASE + "/",
        # Deliberately omit image until a provenance-backed real story image exists.
    )
    return f'<script type="application/ld+json">{serialize_jsonld(document)}</script>'


def page(item: dict, updated_local: str, stories: list[dict], published_at: str | None) -> str:
    route = route_for(item)
    canonical = BASE + route
    title = str(item.get("headline") or "VÂLCEA CLAR")
    dek = str(item.get("dek") or "")
    section = str(item.get("section") or "ȘTIRI").replace("_", " ")
    paragraphs = "".join(f"<p>{esc(p)}</p>" for p in item.get("paragraphs", []) if str(p).strip())
    sources = source_links(item)
    related = related_links(item, stories)
    jsonld = structured_data(item, canonical, published_at)
    return f'''<!doctype html>
<html lang="ro"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — VÂLCEA CLAR</title>
<meta name="description" content="{esc(dek)}">
<link rel="canonical" href="{esc(canonical)}">
<meta property="og:type" content="article"><meta property="og:site_name" content="VÂLCEA CLAR">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(dek)}">
<meta property="og:url" content="{esc(canonical)}">
{jsonld}
<style>
body{{margin:0;color:#101828;background:#fff;font:17px/1.65 system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
header{{background:#071a3d;color:#fff;padding:18px 22px}}header a{{color:#fff;text-decoration:none;font:700 30px Georgia,serif}}
main{{max-width:820px;margin:0 auto;padding:38px 22px 64px}}.k{{color:#d71920;font-size:12px;font-weight:900;letter-spacing:.08em;text-transform:uppercase}}
h1{{font:800 clamp(36px,6vw,62px)/1.06 Georgia,serif;letter-spacing:-.025em;margin:8px 0 15px}}.dek{{font-size:21px;line-height:1.45;color:#475467}}
.meta{{font-size:13px;color:#667085;border-bottom:1px solid #e4e7ec;padding-bottom:16px;margin-bottom:24px}}article p{{margin:0 0 19px}}
.sources{{margin-top:34px;border-top:2px solid #101828;padding-top:14px}}.sources h2{{font-size:14px;text-transform:uppercase;letter-spacing:.05em}}.sources a{{color:#344054}}
.related{{margin-top:34px;border-top:1px solid #d0d5dd;padding-top:20px}}.related h2{{font:800 20px/1.2 Georgia,serif;margin:0 0 14px}}
.related ul{{list-style:none;padding:0;margin:0;display:grid;gap:10px}}.related a{{display:block;border:1px solid #e4e7ec;border-radius:12px;padding:14px 16px;color:#101828;text-decoration:none}}
.related a:hover{{text-decoration:underline}}.related span{{display:block;color:#d71920;font-size:11px;font-weight:900;letter-spacing:.06em;text-transform:uppercase;margin-bottom:4px}}
.related strong{{display:block;font:700 18px/1.25 Georgia,serif}}
.back{{display:inline-block;margin-top:28px;color:#071a3d;font-weight:700}}
</style></head><body>
<header><a href="/">VÂLCEA CLAR</a></header><main>
<div class="k">{esc(section)}</div><h1>{esc(title)}</h1><p class="dek">{esc(dek)}</p>
<div class="meta">{(f"Publicat {esc(published_at)} · " if published_at else "")}Actualizat {esc(updated_local)} · informație locală verificată</div>
<article>{paragraphs}</article>
<section class="sources"><h2>Surse</h2><ul>{sources}</ul></section>
{related}
<a class="back" href="/">← Înapoi la VÂLCEA CLAR</a>
</main></body></html>'''


def normalize_live_frontpage(text: str) -> str:
    # The compatibility snapshot still has a morning/evening slot internally,
    # but the public homepage is a continuous newsroom, not an edition landing page.
    text = text.replace("EDIȚIA DE DIMINEAȚĂ", "ACTUALIZAT LIVE")
    text = text.replace("EDIȚIA DE SEARĂ", "ACTUALIZAT LIVE")
    text = text.replace("VÂLCEA CLAR — Ediția curentă", "VÂLCEA CLAR — Știri live din Vâlcea")
    return text


def link_frontpage(stories: list[dict]) -> None:
    path = RUNTIME / "index.html"
    if not path.exists():
        return
    text = normalize_live_frontpage(path.read_text(encoding="utf-8"))
    for item in stories:
        headline = esc(item.get("headline"))
        route = route_for(item)
        text = text.replace(f"<h1>{headline}</h1>", f'<h1><a href="{route}" style="text-decoration:none">{headline}</a></h1>')
        text = text.replace(f"<h3>{headline}</h3>", f'<h3><a href="{route}" style="text-decoration:none">{headline}</a></h3>')
        text = text.replace(f"<strong>{headline}</strong>", f'<strong><a href="{route}" style="text-decoration:none">{headline}</a></strong>')
    path.write_text(text, encoding="utf-8")


def main() -> int:
    pointer = load(POINTER)
    doc = load(ROOT / pointer["json_source"])
    decision = load_optional(DECISION)
    allowed_ids = set(decision.get("publishable_story_ids") or [])
    stories = []
    for item in doc.get("items", []):
        if allowed_ids and item.get("id") not in allowed_ids:
            continue
        if story_ready(item)[0]:
            stories.append(item)

    story_root = RUNTIME / "stiri"
    story_root.mkdir(parents=True, exist_ok=True)
    previous_manifest = load_optional(story_root / "manifest.json")
    publication_dates = reconcile_publication_dates(
        [item.get("id") for item in stories],
        previous_manifest.get("stories") or [],
        new_story_ids=decision.get("new_story_ids") or [],
        published_at=decision.get("evaluated_local"),
        bootstrap_event=load_optional(PUBLICATION_EVENT),
    )

    routes = []
    cross_link_count = 0
    dated_count = 0
    for item in stories:
        story_id = str(item.get("id") or "")
        route = route_for(item)
        related = rank_related(item, stories, limit=RELATED_LIMIT)
        published_at = publication_dates.get(story_id)
        target = RUNTIME / route.strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(page(item, str(doc.get("updated_local") or ""), stories, published_at), encoding="utf-8")
        row = {
            "id": item.get("id"),
            "path": route,
            "canonical": BASE + route,
            "related_story_ids": [story.get("id") for story in related],
            "structured_data_type": "NewsArticle",
        }
        if published_at:
            row["published_at"] = published_at
            dated_count += 1
        routes.append(row)
        cross_link_count += len(related)

    (story_root / "manifest.json").write_text(
        json.dumps({
            "schema_version": "1.3",
            "publication_model": "continuous_story_first",
            "homepage_presentation": "live_newsroom",
            "edition_is_canonical_story_url": False,
            "structured_data": {
                "enabled": True,
                "type": "NewsArticle",
                "eligible_scope": "publishable_full_story_only",
                "date_published_policy": "stable_publication_ledger_only",
                "unverified_image_policy": "omit",
            },
            "cross_linking": {
                "enabled": True,
                "ranking": "same_section_then_priority",
                "max_links_per_story": RELATED_LIMIT,
                "eligible_scope": "publishable_full_story_only",
            },
            "stories": routes,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    link_frontpage(stories)
    indexing = write_indexing_assets(RUNTIME, BASE, ["/"] + [route["path"] for route in routes])
    print(json.dumps({
        "status": "PASS",
        "story_pages": len(routes),
        "newsarticle_jsonld": len(routes),
        "date_published": dated_count,
        "cross_links": cross_link_count,
        "routes": routes,
        "indexing_routes": indexing["route_count"],
        "sitemap": "site/runtime/sitemap.xml",
        "robots": "site/runtime/robots.txt",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
