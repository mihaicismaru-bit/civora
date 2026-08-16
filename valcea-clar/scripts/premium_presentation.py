#!/usr/bin/env python3
"""Finalize VÂLCEA CLAR public presentation without changing editorial authorization.

The upstream newsroom decides what is publishable. This layer only:
- applies explicitly sourced story enrichments to already-publishable stories;
- prevents recap/presentation rebuilds from dropping those verified details;
- renders one canonical masthead/navigation/footer across homepage, stories,
  legal pages and Unde ieșim;
- marks archived material clearly instead of presenting expired events as live;
- keeps held investigations out because it consumes only the authorized live feed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
ARCHIVE = SITE / "story_archive.json"
FEED = RUNTIME / "live-feed.json"
MANIFEST = RUNTIME / "stiri" / "manifest.json"
NAVIGATION = SITE / "navigation.json"
ENRICHMENT = ROOT / "editorial" / "story_enrichment.json"
HOLDS = ROOT / "editorial" / "publication_holds.json"
LEGAL = SITE / "legal" / "legal_pages.json"
STATE = SITE / "presentation_state.json"
BASE = "https://valceaclar.ro"


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return copy.deepcopy(default)
        raise SystemExit(f"Missing required presentation input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def merge_sources(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for group in groups:
        for source in group or []:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            rows.append({
                "name": source.get("name") or "Sursă",
                "url": url,
                "tier": source.get("tier"),
            })
    return rows


def apply_enrichment(story: dict[str, Any], enrichment: dict[str, Any] | None) -> dict[str, Any]:
    row = copy.deepcopy(story)
    if not enrichment:
        row.setdefault("content_fidelity", "canonical_story_payload")
        return row
    if row.get("active_now") is False:
        if enrichment.get("archive_headline"):
            row["headline"] = enrichment["archive_headline"]
        if enrichment.get("archive_dek"):
            row["dek"] = enrichment["archive_dek"]
    for key in ("factbox", "article_sections"):
        if enrichment.get(key):
            row[key] = copy.deepcopy(enrichment[key])
    row["sources"] = merge_sources(row.get("sources") or [], enrichment.get("sources") or [])
    row["content_fidelity"] = "verified_enrichment_preserved"
    row["content_enrichment_fingerprint_sha256"] = fingerprint(enrichment)
    return row


def section_key(section: Any) -> str:
    value = str(section or "").upper().replace("_", " ")
    if "ADMIN" in value:
        return "administratie"
    if "SĂNĂ" in value or "SANAT" in value:
        return "sanatate"
    if "INFRA" in value or "MOBIL" in value:
        return "infrastructura"
    if "SPORT" in value:
        return "sport"
    if "CULT" in value or "EVEN" in value:
        return "cultura-evenimente"
    return "stiri"


def nav_html(nav: dict[str, Any]) -> str:
    return "".join(
        f'<a href="{esc(item.get("href"))}">{esc(item.get("label"))}</a>'
        for item in nav.get("items") or []
    )


def footer_links(nav: dict[str, Any]) -> str:
    links = nav.get("footer", {}).get("links") or []
    return '<span aria-hidden="true">·</span>'.join(
        f'<a href="{esc(item.get("href"))}">{esc(item.get("label"))}</a>' for item in links
    )


CSS = r"""
:root{--navy:#071a3d;--navy2:#102a56;--red:#d71920;--ink:#101828;--muted:#667085;--line:#e4e7ec;--soft:#f6f7f9;--paper:#fff}
*{box-sizing:border-box}html{scroll-behavior:smooth;background:var(--paper)}body{margin:0;color:var(--ink);background:var(--paper);font:16px/1.58 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}a{color:inherit}
.top{background:var(--navy);color:#fff}.mast{max-width:1240px;margin:auto;padding:20px 22px 17px;display:flex;align-items:flex-start;justify-content:space-between;gap:24px}.brand{font:700 clamp(30px,4vw,48px)/1 Georgia,serif;letter-spacing:.035em}.brand a{text-decoration:none}.brand span{border-bottom:3px solid var(--red);padding-bottom:7px}.tag{font-family:Georgia,serif;opacity:.84;margin-top:10px}.domain{font-size:13px;opacity:.76;padding-top:5px}.nav{max-width:1240px;margin:auto;padding:0 22px;border-top:1px solid rgba(255,255,255,.14);display:flex;gap:23px;overflow-x:auto;white-space:nowrap;scrollbar-width:thin}.nav a{padding:12px 0;text-decoration:none;font-size:12px;font-weight:850;letter-spacing:.025em;text-transform:uppercase}.nav a:hover{text-decoration:underline;text-underline-offset:4px}
main{max-width:1240px;margin:auto;padding:25px 22px 58px}.livebar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:22px}.pill{background:var(--red);color:#fff;padding:7px 11px;border-radius:4px;font-size:11px;font-weight:900;letter-spacing:.045em}.time,.status{font-size:13px;color:var(--muted)}.anchor{scroll-margin-top:20px}
.grid{display:grid;grid-template-columns:minmax(0,1.86fr) minmax(285px,.72fr);gap:36px}.kicker{color:var(--red);font-size:12px;font-weight:900;letter-spacing:.075em;text-transform:uppercase}.hero h1{font:800 clamp(38px,5.4vw,66px)/1.03 Georgia,serif;letter-spacing:-.03em;margin:8px 0 14px}.hero h1 a{text-decoration:none}.hero h1 a:hover{text-decoration:underline;text-decoration-thickness:1px;text-underline-offset:6px}.dek{font-size:20px;line-height:1.45;color:#344054;max-width:900px}.hero-copy{font:18px/1.68 Georgia,serif;max-width:900px}.hero-copy p{margin:13px 0}.story-meta{display:flex;gap:8px;align-items:center;flex-wrap:wrap;color:var(--muted);font-size:12px;margin:10px 0}.archive{font-weight:850;color:#475467;background:#f2f4f7;padding:4px 7px;border-radius:999px}.live{font-weight:900;color:#067647;background:#ecfdf3;padding:4px 7px;border-radius:999px}.sources{font-size:12px;color:var(--muted);margin-top:14px}.sources a{color:#475467}.sources a:hover{text-decoration:underline}
.section-title{font-size:13px;letter-spacing:.07em;text-transform:uppercase;border-bottom:2px solid var(--ink);padding-bottom:8px;margin:30px 0 15px}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}.card{border-top:3px solid var(--navy);padding-top:12px}.card h3{font:700 22px/1.15 Georgia,serif;margin:7px 0}.card h3 a{text-decoration:none}.card h3 a:hover{text-decoration:underline}.card p{color:#475467;margin:0}.side{border-left:1px solid var(--line);padding-left:28px}.side>h2{font-size:14px;text-transform:uppercase;letter-spacing:.07em;border-bottom:2px solid var(--red);padding-bottom:9px;margin:0}.side-story{padding:13px 0;border-bottom:1px solid var(--line)}.side-story strong{display:block;font:700 18px/1.2 Georgia,serif}.side-story a{text-decoration:none}.side-story a:hover{text-decoration:underline}
.venues{background:var(--navy);color:#fff;border-radius:10px;padding:18px;margin-top:28px}.venues-head{display:flex;justify-content:space-between;gap:12px;align-items:center}.venues h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;margin:0}.venues .cta{font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,.35);border-radius:999px;padding:5px 8px}.venue{display:block;text-decoration:none;padding:12px 0;border-top:1px solid rgba(255,255,255,.14)}.venue:first-of-type{margin-top:10px}.venue span{display:block;color:#d0d5dd;font-size:13px;margin-top:3px}.venue-badges{font-size:11px;color:#f2f4f7;margin-top:4px}.note{margin-top:34px;background:var(--soft);border-left:4px solid var(--red);padding:15px 18px;color:#475467;font-size:13px}
.article{max-width:860px;margin:0 auto;padding:18px 0 18px}.article h1{font:800 clamp(39px,6vw,65px)/1.04 Georgia,serif;letter-spacing:-.03em;margin:8px 0 15px}.article-body{font:18px/1.72 Georgia,serif;margin-top:26px}.article-body p{margin:0 0 20px}.hero-photo{margin:25px 0 28px}.hero-photo img{display:block;width:100%;max-height:570px;object-fit:cover;border-radius:5px}.hero-photo figcaption{font-size:12px;color:var(--muted);margin-top:7px}.factbox{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:26px 0}.fact{background:#fff;padding:13px 15px}.fact b{display:block;text-transform:uppercase;font-size:10px;letter-spacing:.08em;color:var(--muted);margin-bottom:3px}.fact span{font-weight:750}.rich-section{border-top:1px solid var(--line);padding-top:24px;margin-top:28px}.rich-section h2{font:800 26px/1.16 Georgia,serif;margin:0 0 13px}.rich-section p{font:17px/1.7 Georgia,serif;color:#344054}.rich-section ul{padding-left:22px}.rich-section li{margin:8px 0;line-height:1.55}.article-sources{margin-top:38px;border-top:2px solid var(--ink);padding-top:15px}.article-sources h2{font-size:13px;text-transform:uppercase;letter-spacing:.07em}.article-sources li{margin:7px 0}.article-sources a{color:#344054}.related{margin-top:35px;border-top:1px solid var(--line);padding-top:20px}.related h2{font:800 20px/1.2 Georgia,serif}.related-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.related-card{border:1px solid var(--line);border-radius:10px;padding:14px;text-decoration:none}.related-card span{display:block;color:var(--red);font-size:10px;font-weight:900;text-transform:uppercase;letter-spacing:.06em}.related-card strong{font:700 17px/1.25 Georgia,serif}.back{display:inline-block;margin-top:30px;color:var(--navy);font-weight:800}
.legal{max-width:860px;margin:0 auto}.legal h1,.venues-page h1{font:800 clamp(39px,6vw,62px)/1.04 Georgia,serif;letter-spacing:-.025em;margin:8px 0 15px}.legal-section{padding:3px 0 20px;border-bottom:1px solid var(--line)}.legal-section h2{font:700 25px/1.2 Georgia,serif;margin:28px 0 10px}.legal-section p{color:#344054}.contact{margin-top:30px;background:var(--soft);border-left:4px solid var(--red);padding:16px 18px}.venue-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px;margin-top:24px}.venue-card{border:1px solid var(--line);border-radius:12px;padding:17px;text-decoration:none}.venue-card h2{font:700 22px/1.2 Georgia,serif;margin:4px 0 8px}.venue-card p{color:#475467}.venue-card .city{font-size:11px;color:var(--red);font-weight:900;text-transform:uppercase;letter-spacing:.06em}
footer{background:var(--navy);color:#d0d5dd;padding:22px;text-align:center;font-size:13px}.footer-links{display:flex;justify-content:center;gap:9px;margin-top:7px}.footer-links a{color:#fff}
@media(max-width:900px){.grid{grid-template-columns:1fr}.side{border-left:0;padding-left:0;border-top:1px solid var(--line);padding-top:24px}.cards,.venue-grid{grid-template-columns:1fr}.tag{display:none}.hero h1{font-size:43px}}@media(max-width:560px){main{padding:20px 16px 48px}.mast{padding-left:16px;padding-right:16px}.nav{padding-left:16px;padding-right:16px}.article h1{font-size:39px}.factbox{grid-template-columns:1fr}.related-grid{grid-template-columns:1fr}.hero-photo{margin-left:-16px;margin-right:-16px}.hero-photo img{border-radius:0}.hero-photo figcaption{padding:0 16px}}
"""


def shell(nav: dict[str, Any], *, title: str, description: str, canonical: str, body: str, og_type: str = "website", robots: str | None = None, extra_head: str = "") -> str:
    robots_meta = f'<meta name="robots" content="{esc(robots)}">' if robots else ""
    return f'''<!doctype html><html lang="ro"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}">{robots_meta}
<meta property="og:site_name" content="VÂLCEA CLAR"><meta property="og:type" content="{esc(og_type)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}">{extra_head}
<style>{CSS}</style></head><body data-nav-contract="{esc(nav.get('contract_id'))}">
<header class="top"><div class="mast"><div><div class="brand"><a href="/"><span>{esc(nav.get('brand'))}</span></a></div><div class="tag">{esc(nav.get('tagline'))}</div></div><div class="domain">{esc(nav.get('domain_label'))}</div></div><nav class="nav" aria-label="Navigație principală">{nav_html(nav)}</nav></header>
{body}
<footer><div>{esc(nav.get('footer',{}).get('line'))}</div><div class="footer-links">{footer_links(nav)}</div></footer>
</body></html>'''


def source_links(story: dict[str, Any], *, list_mode: bool = False) -> str:
    rows = []
    for src in story.get("sources") or []:
        url = str(src.get("url") or "").strip()
        if not url:
            continue
        link = f'<a href="{esc(url)}" rel="nofollow noopener">{esc(src.get("name") or "Sursă")}</a>'
        rows.append(f"<li>{link}</li>" if list_mode else link)
    return "".join(rows) if list_mode else " · ".join(rows[:4])


def archive_label(story: dict[str, Any]) -> str:
    if story.get("active_now"):
        return '<span class="live">ACTIV ACUM</span>'
    date = str(story.get("first_published_at") or story.get("last_seen_at") or "")[:10]
    return f'<span class="archive">ARHIVĂ{(" · " + esc(date)) if date else ""}</span>'


def factbox(story: dict[str, Any]) -> str:
    rows = story.get("factbox") or []
    if not rows:
        return ""
    return '<section class="factbox" aria-label="Date esențiale">' + "".join(
        f'<div class="fact"><b>{esc(item.get("label"))}</b><span>{esc(item.get("value"))}</span></div>'
        for item in rows if isinstance(item, dict)
    ) + "</section>"


def rich_sections(story: dict[str, Any]) -> str:
    parts = []
    for section in story.get("article_sections") or []:
        if not isinstance(section, dict) or not section.get("title"):
            continue
        paragraphs = "".join(f'<p>{esc(p)}</p>' for p in section.get("paragraphs") or [] if str(p).strip())
        bullets = [str(x).strip() for x in section.get("bullets") or [] if str(x).strip()]
        ul = "<ul>" + "".join(f'<li>{esc(item)}</li>' for item in bullets) + "</ul>" if bullets else ""
        parts.append(f'<section class="rich-section"><h2>{esc(section.get("title"))}</h2>{paragraphs}{ul}</section>')
    return "".join(parts)


def story_path(story: dict[str, Any]) -> str:
    return str(story.get("path") or f"/stiri/{story.get('id')}/")


def render_home(nav: dict[str, Any], feed: dict[str, Any]) -> str:
    stories = [x for x in feed.get("stories") or [] if isinstance(x, dict)]
    if not stories:
        raise SystemExit("Refusing premium homepage: no authorized stories")
    active = [x for x in stories if x.get("active_now")]
    lead = active[0] if active else stories[0]
    others = [x for x in stories if x.get("id") != lead.get("id")]
    secondary = others[:3]
    top = (others + [lead])[:5]
    anchors = ''.join(f'<span id="{name}" class="anchor"></span>' for name in ("stiri","administratie","sanatate","infrastructura","cultura-evenimente","sport"))
    paras = "".join(f'<p>{esc(p)}</p>' for p in (lead.get("paragraphs") or [])[:2])
    cards = "".join(
        f'''<article class="card" data-section="{esc(section_key(item.get('section')))}"><div class="kicker">{esc(str(item.get('section') or 'ȘTIRI').replace('_',' '))}</div><div class="story-meta">{archive_label(item)}</div><h3><a href="{esc(story_path(item))}">{esc(item.get('headline'))}</a></h3><p>{esc(item.get('dek'))}</p></article>'''
        for item in secondary
    )
    side = "".join(
        f'<div class="side-story"><div class="kicker">{esc(str(item.get("section") or "ȘTIRI").replace("_"," "))}</div><strong><a href="{esc(story_path(item))}">{esc(item.get("headline"))}</a></strong></div>'
        for item in top
    )
    venue_rows = feed.get("unde_iesim") or []
    venues = "".join(
        f'<a class="venue" href="/unde-iesim/local/{esc(place.get("slug") or place.get("id"))}/"><strong>{esc(place.get("name"))}</strong><span>{esc(place.get("summary") or "Fișă verificată editorial.")}</span></a>'
        for place in venue_rows[:4]
    )
    live_note = "Materialele active sunt ordonate primele." if active else "Nu există în acest moment un material activ; afișăm clar cele mai recente materiale din arhivă."
    body = f'''<main>{anchors}<div class="livebar"><span class="pill">ACTUALIZAT LIVE</span><span class="time">{esc(feed.get('generated_at'))}</span><span class="status">{esc(live_note)}</span></div>
<div class="grid"><section><article class="hero"><div class="kicker">{esc(str(lead.get('section') or 'ȘTIRI').replace('_',' '))}</div><div class="story-meta">{archive_label(lead)}</div><h1><a href="{esc(story_path(lead))}">{esc(lead.get('headline'))}</a></h1><p class="dek">{esc(lead.get('dek'))}</p><div class="hero-copy">{paras}</div><div class="sources">{source_links(lead)}</div></article>
<h2 class="section-title" id="stiri-list">Ultimele materiale publicate</h2><div class="cards">{cards}</div></section><aside class="side"><h2>De citit</h2>{side}<section class="venues"><div class="venues-head"><h2>Unde ieșim</h2><a class="cta" href="/unde-iesim/">Vezi ghidul</a></div>{venues}</section></aside></div>
<div class="note">VÂLCEA CLAR păstrează distinct știrile active și materialele de arhivă. Un monitor intern sau o anchetă incompletă nu intră aici până nu devine un articol verificat și complet.</div></main>'''
    return shell(nav, title="VÂLCEA CLAR — Știri din Vâlcea", description="Știri locale verificate din Vâlcea, publicate continuu și arhivate clar.", canonical=BASE+"/", body=body)


def related(story: dict[str, Any], stories: list[dict[str, Any]], limit: int = 4) -> list[dict[str, Any]]:
    sid = story.get("id")
    section = story.get("section")
    rows = [x for x in stories if x.get("id") != sid]
    rows.sort(key=lambda x: (0 if x.get("section") == section else 1, -int(x.get("priority") or 0), str(x.get("id") or "")))
    return rows[:limit]


def render_story(nav: dict[str, Any], story: dict[str, Any], stories: list[dict[str, Any]], manifest_row: dict[str, Any] | None) -> str:
    canonical = str(story.get("canonical_url") or manifest_row.get("canonical") if manifest_row else story.get("canonical_url") or BASE+story_path(story))
    image = (manifest_row or {}).get("image") if isinstance(manifest_row, dict) else None
    figure = ""
    extra_head = ""
    if isinstance(image, dict) and image.get("public_url"):
        image_url = str(image["public_url"])
        extra_head = f'<meta property="og:image" content="{esc(image_url)}">'
        credit = image.get("credit") or "Sursă foto verificată"
        source = image.get("source_url")
        caption = f'<a href="{esc(source)}" rel="nofollow noopener">{esc(credit)}</a>' if source else esc(credit)
        figure = f'<figure class="hero-photo"><img src="{esc(image_url)}" alt="{esc(story.get("headline"))}" loading="eager"><figcaption>{caption}</figcaption></figure>'
    body_paras = "".join(f'<p>{esc(p)}</p>' for p in story.get("paragraphs") or [] if str(p).strip())
    rel = related(story, stories)
    rel_html = ""
    if rel:
        rel_html = '<section class="related"><h2>Mai citește</h2><div class="related-grid">' + "".join(
            f'<a class="related-card" href="{esc(story_path(item))}"><span>{esc(str(item.get("section") or "ȘTIRI").replace("_"," "))}</span><strong>{esc(item.get("headline"))}</strong></a>' for item in rel
        ) + '</div></section>'
    body = f'''<main><article class="article"><div class="kicker">{esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}</div><div class="story-meta">{archive_label(story)}</div><h1>{esc(story.get('headline'))}</h1><p class="dek">{esc(story.get('dek'))}</p><div class="status">Publicat {esc(story.get('first_published_at') or '')} · informație locală verificată</div>{figure}{factbox(story)}<div class="article-body">{body_paras}</div>{rich_sections(story)}<section class="article-sources"><h2>Surse</h2><ul>{source_links(story,list_mode=True)}</ul></section>{rel_html}<a class="back" href="/">← Înapoi la VÂLCEA CLAR</a></article></main>'''
    return shell(nav, title=f"{story.get('headline')} — VÂLCEA CLAR", description=str(story.get("dek") or ""), canonical=canonical, body=body, og_type="article", extra_head=extra_head)


def render_venues(nav: dict[str, Any], feed: dict[str, Any]) -> str:
    rows = feed.get("unde_iesim") or []
    cards = "".join(
        f'''<a class="venue-card" href="/unde-iesim/local/{esc(place.get('slug') or place.get('id'))}/"><div class="city">{esc(place.get('city') or 'Vâlcea')}</div><h2>{esc(place.get('name'))}</h2><p>{esc(place.get('summary') or 'Fișă verificată editorial.')}</p><div class="venue-badges">{esc(' · '.join(str(x) for x in (place.get('badges') or [])))}</div></a>'''
        for place in rows
    )
    body = f'''<main class="venues-page"><div class="kicker">GHID LOCAL</div><h1>Unde ieșim</h1><p class="dek">Restaurante, cafenele și locuri de ieșit verificate editorial. Candidații incompleți rămân ascunși până la verificare.</p><div class="venue-grid">{cards}</div></main>'''
    return shell(nav, title="Unde ieșim — VÂLCEA CLAR", description="Ghid local VÂLCEA CLAR pentru restaurante, cafenele și locuri de ieșit.", canonical=BASE+"/unde-iesim/", body=body)


def render_legal(nav: dict[str, Any], doc: dict[str, Any], slug: str) -> str:
    page = doc["pages"][slug]
    sections = "".join(
        f'<section class="legal-section"><h2>{esc(section.get("title"))}</h2>' + "".join(f'<p>{esc(p)}</p>' for p in section.get("paragraphs") or []) + "</section>"
        for section in page.get("sections") or []
    )
    body = f'''<main><article class="legal"><div class="kicker">DOCUMENT PUBLIC</div><h1>{esc(page.get('title'))}</h1><div class="status">În vigoare din {esc(doc.get('effective_date'))} · VÂLCEA CLAR / valceaclar.ro</div><p class="dek">{esc(page.get('intro'))}</p>{sections}<div class="contact"><strong>Contact</strong><br><a href="mailto:{esc(doc.get('contact_email'))}">{esc(doc.get('contact_email'))}</a></div></article></main>'''
    return shell(nav, title=f"{page.get('title')} — VÂLCEA CLAR", description=str(page.get("description") or page.get("intro") or ""), canonical=BASE+str(page.get("path")), body=body, robots="index,follow")


def add_sitemap_routes(paths: list[str]) -> None:
    sitemap = RUNTIME / "sitemap.xml"
    if not sitemap.is_file():
        return
    text = sitemap.read_text(encoding="utf-8")
    additions = []
    for path in paths:
        url = BASE + path
        if f"<loc>{url}</loc>" not in text:
            additions.append(f"  <url><loc>{esc(url)}</loc></url>\n")
    if additions and "</urlset>" in text:
        text = text.replace("</urlset>", "".join(additions) + "</urlset>")
        sitemap.write_text(text, encoding="utf-8")


def finalize() -> dict[str, Any]:
    nav = load(NAVIGATION)
    enrich_doc = load(ENRICHMENT, {"stories": {}})
    enrichments = enrich_doc.get("stories") or {}
    archive = load(ARCHIVE)
    feed = load(FEED)
    manifest = load(MANIFEST, {"stories": []})
    archive_by_id = {str(x.get("id")): x for x in archive.get("stories") or [] if isinstance(x, dict) and x.get("id")}

    enriched_archive = []
    for story in archive.get("stories") or []:
        sid = str(story.get("id") or "")
        enriched_archive.append(apply_enrichment(story, enrichments.get(sid)))
    archive["stories"] = enriched_archive
    archive["story_count"] = len(enriched_archive)
    archive["content_fidelity_policy"] = "verified_enrichment_survives_recap_compression"
    write(ARCHIVE, archive)
    archive_by_id = {str(x.get("id")): x for x in enriched_archive}

    enriched_feed = []
    for story in feed.get("stories") or []:
        sid = str(story.get("id") or "")
        merged = copy.deepcopy(story)
        archived = archive_by_id.get(sid) or {}
        for key in ("first_published_at", "last_seen_at", "archive_status", "active_now", "factbox", "article_sections", "content_fidelity", "content_enrichment_fingerprint_sha256"):
            if key in archived:
                merged[key] = copy.deepcopy(archived[key])
        if archived.get("headline"):
            merged["headline"] = archived["headline"]
        if archived.get("dek"):
            merged["dek"] = archived["dek"]
        merged["sources"] = merge_sources(merged.get("sources") or [], archived.get("sources") or [])
        enriched_feed.append(merged)
    feed["stories"] = enriched_feed
    feed["story_count"] = len(enriched_feed)
    feed.setdefault("policy", {})["content_fidelity_preserved"] = True
    feed["navigation_contract"] = nav.get("contract_id")
    write(FEED, feed)

    manifest_rows = {str(x.get("id")): x for x in manifest.get("stories") or [] if isinstance(x, dict)}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "index.html").write_text(render_home(nav, feed), encoding="utf-8")
    story_root = RUNTIME / "stiri"
    story_root.mkdir(parents=True, exist_ok=True)
    for story in enriched_feed:
        sid = str(story.get("id") or "")
        target = RUNTIME / story_path(story).strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_story(nav, story, enriched_feed, manifest_rows.get(sid)), encoding="utf-8")

    venue_target = RUNTIME / "unde-iesim" / "index.html"
    venue_target.parent.mkdir(parents=True, exist_ok=True)
    venue_target.write_text(render_venues(nav, feed), encoding="utf-8")

    if LEGAL.is_file():
        legal_doc = load(LEGAL)
        for slug in ("termeni", "confidentialitate"):
            if slug in (legal_doc.get("pages") or {}):
                target = RUNTIME / slug / "index.html"
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(render_legal(nav, legal_doc, slug), encoding="utf-8")

    add_sitemap_routes(["/unde-iesim/", "/termeni/", "/confidentialitate/"])

    state = {
        "schema_version": "1.0",
        "contract_id": "valcea-clar-premium-presentation-v1",
        "source_feed_generated_at": feed.get("generated_at"),
        "navigation_contract": nav.get("contract_id"),
        "story_count": len(enriched_feed),
        "enriched_story_ids": sorted([sid for sid in archive_by_id if sid in enrichments]),
        "routes": ["/", "/unde-iesim/", "/termeni/", "/confidentialitate/"] + [story_path(x) for x in enriched_feed],
        "policy": {
            "single_public_shell": True,
            "same_navigation_everywhere": True,
            "archived_story_label_required": True,
            "verified_rich_content_preserved": True,
            "held_story_public_projection": False
        }
    }
    state["presentation_fingerprint_sha256"] = fingerprint(state)
    write(STATE, state)
    validate(nav, feed, archive)
    return state


def validate(nav: dict[str, Any] | None = None, feed: dict[str, Any] | None = None, archive: dict[str, Any] | None = None) -> None:
    nav = nav or load(NAVIGATION)
    feed = feed or load(FEED)
    archive = archive or load(ARCHIVE)
    required_nav = [(str(x.get("label")), str(x.get("href"))) for x in nav.get("items") or []]
    pages = [RUNTIME / "index.html", RUNTIME / "unde-iesim" / "index.html"]
    pages += [RUNTIME / "stiri" / str(x.get("id")) / "index.html" for x in feed.get("stories") or []]
    if LEGAL.is_file():
        pages += [RUNTIME / "termeni" / "index.html", RUNTIME / "confidentialitate" / "index.html"]
    for path in pages:
        if not path.is_file():
            raise SystemExit(f"Premium presentation missing public page: {path}")
        text = path.read_text(encoding="utf-8")
        if f'data-nav-contract="{nav.get("contract_id")}"' not in text:
            raise SystemExit(f"Navigation contract missing from {path}")
        for label, href in required_nav:
            marker = f'<a href="{esc(href)}">{esc(label)}</a>'
            if marker not in text:
                raise SystemExit(f"Navigation drift in {path}: missing {label} -> {href}")
        if 'name="viewport"' not in text:
            raise SystemExit(f"Mobile viewport missing from {path}")

    ids = {str(x.get("id")) for x in feed.get("stories") or []}
    archive_ids = {str(x.get("id")) for x in archive.get("stories") or []}
    if ids != archive_ids:
        raise SystemExit("Premium presentation feed/archive ids drifted")
    holds = load(HOLDS, {"holds": []})
    held = {str(x.get("story_id")) for x in holds.get("holds") or [] if x.get("public_projection") is False}
    if ids & held:
        raise SystemExit("Held story leaked into premium presentation")

    music = RUNTIME / "stiri" / "musiclover-green-day-20260815" / "index.html"
    if music.is_file():
        text = music.read_text(encoding="utf-8")
        for value in ("Puya", "Johny Romano", "Badd G", "Connect-R", "Delia", "Urban Lăutăresque", "Leo de la Roșiori", "Marcel Ștefăneț", "Ethno Republic"):
            if value not in text:
                raise SystemExit(f"Musiclover content-fidelity regression: missing {value}")
    luminos = RUNTIME / "stiri" / "luminos-fest-zavoi-20260815" / "index.html"
    if luminos.is_file():
        text = luminos.read_text(encoding="utf-8")
        for value in ("Flower Bar", "ROvederea", "Aleea Creatorilor", "Bebe Cros", "Intrare"):
            if value not in text:
                raise SystemExit(f"Luminos content-fidelity regression: missing {value}")


def self_test() -> None:
    sample = {"id":"x","headline":"Azi: exemplu","dek":"D","sources":[{"name":"A","url":"https://a.test"}],"active_now":False}
    enrichment = {"archive_headline":"Exemplu arhivat","article_sections":[{"title":"Program","bullets":["A"]}],"sources":[{"name":"B","url":"https://b.test"}]}
    row = apply_enrichment(sample, enrichment)
    assert row["headline"] == "Exemplu arhivat"
    assert len(row["sources"]) == 2
    assert row["article_sections"][0]["title"] == "Program"
    assert section_key("EVENIMENTE") == "cultura-evenimente"
    assert section_key("SPORT") == "sport"
    print("VÂLCEA CLAR premium presentation self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.check:
        validate()
        print("VÂLCEA CLAR premium presentation validation: PASS")
        return 0
    state = finalize()
    print(json.dumps({"status":"PASS","stories":state["story_count"],"enriched":state["enriched_story_ids"],"navigation":state["navigation_contract"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
