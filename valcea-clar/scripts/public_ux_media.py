#!/usr/bin/env python3
"""Add provenance-backed photographs to the derived VÂLCEA CLAR reader UI.

This is a presentation-only adapter. It imports the freshness-first projector,
then decorates already-published stories with either:
1. exact verified story media from the canonical runtime story manifest; or
2. an explicit, rights-checked contextual assignment from
   ``social/contextual_story_media.json``.

No automatic keyword substitution is allowed. Missing media never authorizes,
blocks or alters editorial publication.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import public_ux_fresh_rank as fresh

base = fresh.base
ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
CONTEXT = ROOT / "social" / "contextual_story_media.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return copy.deepcopy(default)
    return json.loads(path.read_text(encoding="utf-8"))


def exact_media_index() -> dict[str, dict[str, Any]]:
    doc = load_json(STORY_MANIFEST, {"stories": []})
    out: dict[str, dict[str, Any]] = {}
    for row in doc.get("stories") or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        image = row.get("image") if isinstance(row.get("image"), dict) else None
        if image and image.get("provenance_status") == "VERIFIED" and image.get("public_url"):
            item = copy.deepcopy(image)
            item["media_role"] = "exact_story_media"
            out[str(row["id"])] = item
    return out


def contextual_index(exact: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    doc = load_json(CONTEXT, {"assignments": {}})
    out: dict[str, dict[str, Any]] = {}
    for sid, raw in (doc.get("assignments") or {}).items():
        if not isinstance(raw, dict):
            continue
        item = copy.deepcopy(raw)
        inherited = str(item.pop("inherit_verified_story_media_from", "") or "")
        if inherited:
            source = exact.get(inherited)
            if not source:
                continue
            note = item.get("editorial_note")
            item = copy.deepcopy(source)
            if note:
                item["editorial_note"] = note
            item["contextual_archive"] = True
        if item.get("provenance_status") != "VERIFIED" or not item.get("public_url"):
            continue
        item["media_role"] = "explicit_contextual_media"
        item["contextual_archive"] = True
        out[str(sid)] = item
    return out


def media_indexes() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    exact = exact_media_index()
    return exact, contextual_index(exact)


def media_for_story(story_id: str) -> dict[str, Any] | None:
    exact, contextual = media_indexes()
    if story_id in exact:
        return exact[story_id]
    return contextual.get(story_id)


def media_caption(media: dict[str, Any]) -> str:
    credit = str(media.get("credit") or "Sursă foto verificată")
    note = str(media.get("editorial_note") or "")
    if media.get("media_role") == "explicit_contextual_media" and not note:
        note = "Foto de context; imaginea nu documentează evenimentul descris."
    return credit + (f" · {note}" if note else "")


def media_image(story: dict[str, Any], *, variant: str, link: bool = True) -> str:
    sid = str(story.get("id") or "")
    media = media_for_story(sid)
    if not media:
        return ""
    url = base.esc(media.get("public_url"))
    alt = base.esc(media.get("alt_text") or story.get("headline") or "Imagine")
    route = base.esc(base.story_path(story))
    context = "contextual" if media.get("media_role") == "explicit_contextual_media" else "exact"
    if variant == "hero":
        image = (
            f'<img data-story-image="{base.esc(sid)}" data-media-context="{context}" '
            f'src="{url}" alt="{alt}" loading="eager" '
            'style="width:100%;height:clamp(280px,43vw,520px);object-fit:cover;display:block">'
        )
        if link:
            image = f'<a href="{route}" aria-label="{base.esc(story.get("headline"))}">{image}</a>'
        return (
            '<figure style="margin:0 0 20px">' + image +
            f'<figcaption style="margin-top:7px;font-size:11px;line-height:1.35;color:#6c665c">{base.esc(media_caption(media))}</figcaption></figure>'
        )
    height = "96px" if variant == "rail" else "170px"
    image = (
        f'<img data-story-image="{base.esc(sid)}" data-media-context="{context}" '
        f'src="{url}" alt="{alt}" loading="lazy" '
        f'style="width:100%;height:{height};object-fit:cover;display:block;margin:0 0 10px">'
    )
    return f'<a href="{route}" aria-label="{base.esc(story.get("headline"))}">{image}</a>' if link else image


def card(story: dict[str, Any], live_ids: set[str]) -> str:
    sid = str(story.get("id") or "")
    archived = sid not in live_ids
    badge = '<span class="archive-label">ARHIVĂ</span>' if archived else ""
    image = media_image(story, variant="card")
    return f'''<article class="card" data-bucket="{base.esc(base.bucket(story))}">{image}<div class="kicker">{base.esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}{badge}</div><h3><a href="{base.esc(base.story_path(story))}">{base.esc(story.get('headline'))}</a></h3><p>{base.esc(story.get('dek'))}</p><div class="story-date">{base.esc(base.date_label(story))}</div></article>'''


def render_home(nav: dict[str, Any], feed: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str]) -> str:
    if not stories:
        raise SystemExit("Refusing public homepage: no reader-facing news")
    lead = stories[0]
    others = [row for row in stories if row.get("id") != lead.get("id")]
    rail_rows = others[:4]
    rail_parts = []
    for row in rail_rows:
        rail_parts.append(
            f'''<article class="rail-story">{media_image(row, variant="rail")}<div class="kicker">{base.esc(str(row.get('section') or 'ȘTIRI').replace('_',' '))}</div><a href="{base.esc(base.story_path(row))}"><strong>{base.esc(row.get('headline'))}</strong></a><div class="meta">{base.esc(base.date_label(row))}{' · arhivă' if str(row.get('id')) not in live_ids else ''}</div></article>'''
        )
    rail = "".join(rail_parts)
    paras = "".join(f'<p>{base.esc(p)}</p>' for p in (lead.get("paragraphs") or [])[:1])
    latest = others[:3]
    groups = {key: [row for row in stories if base.bucket(row) == key] for key in ("bani-publici", "servicii", "cultura-evenimente", "sport")}
    venues = "".join(f'''<a class="venue" href="/unde-iesim/local/{base.esc(place.get('slug') or place.get('id'))}/"><strong>{base.esc(place.get('name'))}</strong><span>{base.esc(place.get('summary') or 'Fișă verificată editorial.')}</span></a>''' for place in (feed.get("unde_iesim") or [])[:4])
    hero_image = media_image(lead, variant="hero")
    hero_media = hero_image or ""
    body = f'''<main><div class="live-strip"><div><strong>Actualizat</strong> <span>{base.esc(feed.get('generated_at'))}</span></div><span>{len(live_ids)} materiale în fluxul curent · arhiva verificată completează contextul</span></div><div class="lead-grid"><section class="hero">{hero_media}<div class="kicker">{base.esc(str(lead.get('section') or 'ȘTIRI').replace('_',' '))}</div><h1><a href="{base.esc(base.story_path(lead))}">{base.esc(lead.get('headline'))}</a></h1><p class="dek">{base.esc(lead.get('dek'))}</p>{paras}<div class="sources">{base.source_links(lead)}</div></section><aside class="rail"><h2>De citit acum</h2>{rail}</aside></div>{base.section_block('Ultimele știri','ultimele',latest,live_ids)}{base.section_block('Bani publici','bani-publici',groups['bani-publici'],live_ids)}{base.section_block('Servicii','servicii',groups['servicii'],live_ids)}{base.section_block('Cultură & Evenimente','cultura-evenimente',groups['cultura-evenimente'],live_ids)}{base.section_block('Sport','sport',groups['sport'],live_ids)}{('<section class="section"><div class="section-head"><h2>Unde ieșim</h2><a href="/unde-iesim/">Vezi ghidul</a></div><div class="venue-grid">'+venues+'</div></section>') if venues else ''}</main>'''
    return base.shell(nav, title="VÂLCEA CLAR — Știri din Vâlcea", description="Știri locale verificate din Vâlcea, ordonate după actualitate și relevanță.", canonical=base.BASE+"/", body=body)


def render_news_index(nav: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str]) -> str:
    rows = []
    for row in stories:
        image = media_image(row, variant="rail")
        rows.append(f'''<article class="list-row"><div>{image}<div class="kicker">{base.esc(str(row.get('section') or 'ȘTIRI').replace('_',' '))}</div><div class="story-date">{base.esc(base.date_label(row))}{' · arhivă' if str(row.get('id')) not in live_ids else ''}</div></div><div><h2><a href="{base.esc(base.story_path(row))}">{base.esc(row.get('headline'))}</a></h2><p>{base.esc(row.get('dek'))}</p></div></article>''')
    groups = {key: [row for row in stories if base.bucket(row) == key] for key in ("bani-publici", "servicii", "cultura-evenimente", "sport")}
    sections = base.section_block('Bani publici','bani-publici',groups['bani-publici'],live_ids,6) + base.section_block('Servicii','servicii',groups['servicii'],live_ids,6) + base.section_block('Cultură & Evenimente','cultura-evenimente',groups['cultura-evenimente'],live_ids,6) + base.section_block('Sport','sport',groups['sport'],live_ids,6)
    body = f'''<main><div class="kicker">ȘTIRI</div><h1 class="index-title">Știrile Vâlcii, puse în ordine.</h1><p class="index-dek">Aici apar numai materiale jurnalistice publicabile. Dosarele de documentare și monitoarele interne nu sunt folosite pentru a umple categorii.</p><section id="ultimele" class="all-list">{''.join(rows)}</section>{sections}</main>'''
    return base.shell(nav, title="Știri — VÂLCEA CLAR", description="Toate știrile VÂLCEA CLAR, cu secțiuni curate pentru bani publici, servicii, cultură și sport.", canonical=base.BASE+"/stiri/", body=body)


base.card = card
base.render_home = render_home
base.render_news_index = render_news_index


def validate_media_projection() -> dict[str, int]:
    home = (RUNTIME / "index.html").read_text(encoding="utf-8")
    news = (RUNTIME / "stiri" / "index.html").read_text(encoding="utf-8")
    feed = load_json(RUNTIME / "live-feed.json", {"stories": []})
    first = next((row for row in feed.get("stories") or [] if isinstance(row, dict) and row.get("id")), None)
    if not first:
        raise SystemExit("Media projection validation requires a live story")
    expected = media_for_story(str(first["id"]))
    if expected and f'data-story-image="{first["id"]}"' not in home:
        raise SystemExit(f"Homepage lead media missing: {first['id']}")
    if 'data-story-image=' not in home:
        raise SystemExit("Homepage contains no story photographs")
    if 'data-story-image=' not in news:
        raise SystemExit("News index contains no story photographs")
    contextual = home.count('data-media-context="contextual"')
    exact = home.count('data-media-context="exact"')
    if contextual == 0 and exact == 0:
        raise SystemExit("Homepage media projection has no provenance role")
    result = {"homepage_images": home.count('data-story-image='), "news_index_images": news.count('data-story-image='), "homepage_contextual": contextual, "homepage_exact": exact}
    print(json.dumps({"status": "PASS", **result}, ensure_ascii=False))
    return result


def self_test() -> int:
    sample = {"id": "x", "headline": "Titlu", "path": "/stiri/x/"}
    assert media_image(sample, variant="card") == ""
    assert "explicit_story_assignment_required" in CONTEXT.read_text(encoding="utf-8")
    print("VÂLCEA CLAR Public UX media adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.check:
        base.validate()
        validate_media_projection()
        return 0
    state = base.build()
    validate_media_projection()
    print(json.dumps({"status": "PASS", "stories": state["safe_story_count"], "live": state["live_story_count"], "media": "verified_exact_or_explicit_contextual"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
