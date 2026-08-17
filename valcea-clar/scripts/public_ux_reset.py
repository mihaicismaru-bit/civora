#!/usr/bin/env python3
"""Render the canonical VÂLCEA CLAR reader experience.

This presentation layer does not authorize facts. It consumes only the current
public feed plus the durable published archive and enforces reader-facing
structure:
- one masthead/navigation contract everywhere;
- /stiri/ is a real news index, never a legacy passthrough;
- monitoring/investigation/explainer-only records are not news;
- category sections never borrow stories from another category to fill space;
- the homepage stays useful when the live desk has only one or two fresh items
  by clearly separating current stories from verified recent archive material.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
FEED = RUNTIME / "live-feed.json"
ARCHIVE = SITE / "story_archive.json"
NAVIGATION = SITE / "navigation.json"
HOLDS = ROOT / "editorial" / "publication_holds.json"
STATE = SITE / "public_ux_state.json"
BASE = "https://valceaclar.ro"


def load(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return copy.deepcopy(default)
        raise SystemExit(f"Missing public UX input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def story_path(story: dict[str, Any]) -> str:
    path = str(story.get("path") or f"/stiri/{story.get('id')}/")
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def held_ids() -> set[str]:
    doc = load(HOLDS, {"holds": []})
    return {
        str(row.get("story_id"))
        for row in doc.get("holds") or []
        if isinstance(row, dict) and row.get("public_projection") is False and row.get("story_id")
    }


def is_news(story: dict[str, Any], held: set[str]) -> bool:
    sid = str(story.get("id") or "")
    if not sid or sid in held:
        return False
    if story.get("news_eligible") is False or story.get("operational_only") is True:
        return False
    section = str(story.get("section") or "").upper()
    if any(token in section for token in ("INVESTIGA", "MONITOR", "DOSAR", "DOCUMENTARE", "OPERAȚIONAL", "OPERATIONAL")):
        return False
    if str(story.get("material_fact_gate") or "").upper() == "PASS_EXPLAINER_ONLY":
        return False
    product = story.get("editorial_product") or {}
    fmt = str(product.get("format") or "").lower()
    if fmt in {"investigation", "monitoring", "dossier", "explainer_only"}:
        return False
    if not str(story.get("headline") or "").strip() or not (story.get("sources") or []):
        return False
    return True


def bucket(story: dict[str, Any]) -> str:
    value = str(story.get("section") or "").upper().replace("_", " ")
    if any(token in value for token in ("CULT", "EVEN")):
        return "cultura-evenimente"
    if "SPORT" in value:
        return "sport"
    if any(token in value for token in ("BANI", "BUGET", "ACHIZ", "CONSILI", "ADMIN", "FINANȚ", "FINANT")):
        return "bani-publici"
    if any(token in value for token in ("MOBIL", "INFRA", "TRAFIC", "SERVIC", "UTILIT", "SĂNĂ", "SANAT", "EDUCA")):
        return "servicii"
    return "general"


def stamp(story: dict[str, Any]) -> float:
    for key in ("last_seen_at", "first_published_at", "published_at"):
        value = str(story.get(key) or "").strip()
        if not value:
            continue
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return 0.0


def union_stories(feed: dict[str, Any], archive: dict[str, Any]) -> tuple[list[dict[str, Any]], set[str]]:
    rows: dict[str, dict[str, Any]] = {}
    live_ids: set[str] = set()
    for story in archive.get("stories") or []:
        if isinstance(story, dict) and story.get("id"):
            rows[str(story["id"])] = copy.deepcopy(story)
    for story in feed.get("stories") or []:
        if not isinstance(story, dict) or not story.get("id"):
            continue
        sid = str(story["id"])
        live_ids.add(sid)
        previous = rows.get(sid) or {}
        merged = {**previous, **copy.deepcopy(story)}
        for key in ("factbox", "article_sections", "material_fact_gate", "first_published_at", "last_seen_at", "archive_status", "active_now", "editorial_product"):
            if key not in merged and key in previous:
                merged[key] = copy.deepcopy(previous[key])
        rows[sid] = merged
    held = held_ids()
    safe = [row for row in rows.values() if is_news(row, held)]
    safe.sort(key=lambda row: (0 if str(row.get("id")) in live_ids else 1, -int(bool(row.get("active_now"))), -stamp(row), -int(row.get("priority") or 0), str(row.get("id") or "")))
    return safe, live_ids


def nav_html(nav: dict[str, Any]) -> str:
    return "".join(f'<a href="{esc(item.get("href"))}">{esc(item.get("label"))}</a>' for item in nav.get("items") or [])


def footer_html(nav: dict[str, Any]) -> str:
    links = " · ".join(f'<a href="{esc(item.get("href"))}">{esc(item.get("label"))}</a>' for item in nav.get("footer", {}).get("links") or [])
    return f'<footer><div>{esc(nav.get("footer", {}).get("line"))}</div><div class="footer-links">{links}</div></footer>'


CSS = r"""
:root{--paper:#f5f1e8;--ink:#11110f;--red:#e32b23;--muted:#6c665c;--line:#c9c1b4;--soft:#fbf8f1}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 Arial,Helvetica,sans-serif}a{color:inherit}
.site-header{border-bottom:3px solid var(--ink)}.mast{max-width:1180px;margin:auto;padding:25px 18px 17px;display:flex;align-items:flex-end;justify-content:space-between;gap:24px}.brand{font:700 clamp(42px,6vw,72px)/.9 Georgia,serif;letter-spacing:-.045em}.brand a{text-decoration:none}.tag{font:italic 17px/1.25 Georgia,serif;padding-bottom:6px}.nav{border-top:1px solid var(--ink);max-width:1180px;margin:auto;padding:0 18px;display:flex;gap:24px;overflow-x:auto;white-space:nowrap}.nav a{padding:13px 0 11px;text-decoration:none;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:.035em}.nav a:hover{text-decoration:underline;text-decoration-color:var(--red);text-decoration-thickness:2px;text-underline-offset:5px}
main{max-width:1180px;margin:auto;padding:30px 18px 64px}.live-strip{display:flex;gap:14px;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding:10px 0 14px;margin-bottom:25px}.live-strip strong{font-size:11px;letter-spacing:.08em;color:var(--red);text-transform:uppercase}.live-strip span{font-size:12px;color:var(--muted)}
.lead-grid{display:grid;grid-template-columns:minmax(0,2fr) minmax(280px,.82fr);gap:34px;border-bottom:4px solid var(--ink);padding-bottom:28px}.kicker{font-size:11px;font-weight:900;letter-spacing:.075em;color:var(--red);text-transform:uppercase}.hero h1{font:700 clamp(38px,5.1vw,65px)/1.01 Georgia,serif;letter-spacing:-.035em;margin:8px 0 12px;max-width:900px}.hero h1 a{text-decoration:none}.hero .dek{font:22px/1.34 Georgia,serif;color:#38342e;margin:0 0 14px;max-width:850px}.hero p{font:17px/1.55 Georgia,serif;max-width:820px}.sources{font-size:11px;color:var(--muted);margin-top:14px}.sources a{color:var(--muted)}
.rail{border-left:1px solid var(--line);padding-left:24px}.rail h2{font:800 12px/1.2 Arial,sans-serif;text-transform:uppercase;letter-spacing:.08em;margin:0;border-bottom:2px solid var(--ink);padding-bottom:8px}.rail-story{padding:14px 0;border-bottom:1px solid var(--line)}.rail-story a{text-decoration:none}.rail-story strong{display:block;font:700 20px/1.15 Georgia,serif;margin-top:5px}.rail-story .meta{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:5px}
.section{padding:28px 0 6px;border-bottom:1px solid var(--line);scroll-margin-top:20px}.section-head{display:flex;justify-content:space-between;gap:20px;align-items:end;border-bottom:3px solid var(--ink);padding-bottom:8px;margin-bottom:15px}.section-head h2{font:700 30px/1 Georgia,serif;margin:0}.section-head a{font-size:11px;font-weight:800;text-transform:uppercase;text-decoration:none}.cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}.card{padding-right:18px;border-right:1px solid var(--line)}.card:last-child{border-right:0}.card a{text-decoration:none}.card h3{font:700 23px/1.12 Georgia,serif;margin:7px 0}.card p{color:#4e493f;margin:0}.story-date{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-top:8px}.empty{color:var(--muted);font:italic 16px Georgia,serif}.archive-label{display:inline-block;font-size:9px;font-weight:900;letter-spacing:.08em;background:#e6dfd3;padding:3px 5px;margin-left:5px}
.venue-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px}.venue{border-top:2px solid var(--ink);padding-top:10px;text-decoration:none}.venue strong{display:block;font:700 19px/1.15 Georgia,serif}.venue span{display:block;color:var(--muted);margin-top:5px}
.index-title{font:700 clamp(46px,6vw,72px)/1 Georgia,serif;letter-spacing:-.04em;margin:10px 0}.index-dek{font:19px/1.45 Georgia,serif;max-width:780px;color:#413c34}.all-list{border-top:4px solid var(--ink);margin-top:24px}.list-row{display:grid;grid-template-columns:150px 1fr;gap:25px;padding:18px 0;border-bottom:1px solid var(--line)}.list-row h2{font:700 28px/1.1 Georgia,serif;margin:0 0 7px}.list-row h2 a{text-decoration:none}.list-row p{margin:0;color:#4e493f}
.article{max-width:840px}.article h1{font:700 clamp(42px,6vw,70px)/1.02 Georgia,serif;letter-spacing:-.035em;margin:8px 0 14px}.article .dek{font:22px/1.4 Georgia,serif;color:#413c34}.article-body{font:19px/1.7 Georgia,serif;margin-top:25px}.article-body p{margin:0 0 20px}.factbox{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1px;background:var(--line);border:1px solid var(--line);margin:26px 0}.fact{background:var(--soft);padding:13px}.fact b{display:block;font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.07em}.rich{border-top:1px solid var(--line);padding-top:22px;margin-top:25px}.rich h2{font:700 27px Georgia,serif}.article-sources{border-top:3px solid var(--ink);margin-top:35px;padding-top:12px}.article-sources h2{font-size:12px;text-transform:uppercase}.article-sources li{margin:6px 0}.back{display:inline-block;margin-top:28px;font-weight:800}
.about-grid{display:grid;grid-template-columns:repeat(3,1fr);border-top:4px solid var(--ink);border-left:1px solid var(--line);margin-top:35px}.principle{min-height:200px;padding:24px;border-right:1px solid var(--line);border-bottom:1px solid var(--line)}.principle .num{color:var(--red);font:18px Georgia,serif}.principle h2{font:700 25px Georgia,serif;margin:28px 0 7px}.principle p{color:#4e493f}
footer{border-top:3px solid var(--ink);max-width:1180px;margin:20px auto 0;padding:22px 18px 35px;font-size:12px;color:var(--muted)}.footer-links{margin-top:7px}.footer-links a{color:var(--ink)}
@media(max-width:850px){.tag{display:none}.lead-grid{grid-template-columns:1fr}.rail{border-left:0;padding-left:0;border-top:1px solid var(--line);padding-top:20px}.cards{grid-template-columns:1fr 1fr}.venue-grid{grid-template-columns:1fr 1fr}.about-grid{grid-template-columns:1fr 1fr}.list-row{grid-template-columns:110px 1fr}}
@media(max-width:560px){.mast{padding:18px 14px 13px}.brand{font-size:45px}.nav{padding:0 14px;gap:18px}main{padding:22px 14px 50px}.hero h1{font-size:43px}.hero .dek{font-size:19px}.cards,.venue-grid,.about-grid{grid-template-columns:1fr}.card{border-right:0;border-bottom:1px solid var(--line);padding-bottom:14px}.list-row{grid-template-columns:1fr;gap:6px}.article h1{font-size:43px}.factbox{grid-template-columns:1fr}.live-strip{align-items:flex-start;flex-direction:column}}
"""


def shell(nav: dict[str, Any], *, title: str, description: str, canonical: str, body: str, robots: str | None = None) -> str:
    robots_meta = f'<meta name="robots" content="{esc(robots)}">' if robots else ""
    return f'''<!doctype html><html lang="ro"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(title)}</title><meta name="description" content="{esc(description)}"><link rel="canonical" href="{esc(canonical)}">{robots_meta}<meta property="og:site_name" content="VÂLCEA CLAR"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}"><style>{CSS}</style></head><body data-nav-contract="{esc(nav.get('contract_id'))}"><header class="site-header"><div class="mast"><div class="brand"><a href="/">{esc(nav.get('brand'))}</a></div><div class="tag">{esc(nav.get('tagline'))}</div></div><nav class="nav" aria-label="Navigație principală">{nav_html(nav)}</nav></header>{body}{footer_html(nav)}</body></html>'''


def source_links(story: dict[str, Any], list_mode: bool = False) -> str:
    rows = []
    for src in story.get("sources") or []:
        if not isinstance(src, dict) or not src.get("url"):
            continue
        link = f'<a href="{esc(src.get("url"))}" rel="nofollow noopener">{esc(src.get("name") or "Sursă")}</a>'
        rows.append(f'<li>{link}</li>' if list_mode else link)
    return "".join(rows) if list_mode else " · ".join(rows[:3])


def date_label(story: dict[str, Any]) -> str:
    text = str(story.get("first_published_at") or story.get("last_seen_at") or "")[:10]
    return text


def card(story: dict[str, Any], live_ids: set[str]) -> str:
    sid = str(story.get("id") or "")
    archived = sid not in live_ids
    badge = '<span class="archive-label">ARHIVĂ</span>' if archived else ""
    return f'''<article class="card" data-bucket="{esc(bucket(story))}"><div class="kicker">{esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}{badge}</div><h3><a href="{esc(story_path(story))}">{esc(story.get('headline'))}</a></h3><p>{esc(story.get('dek'))}</p><div class="story-date">{esc(date_label(story))}</div></article>'''


def section_block(title: str, section_id: str, stories: list[dict[str, Any]], live_ids: set[str], limit: int = 3) -> str:
    if not stories:
        return ""
    return f'''<section class="section" id="{esc(section_id)}"><div class="section-head"><h2>{esc(title)}</h2><a href="/stiri/#{esc(section_id)}">Vezi secțiunea</a></div><div class="cards">{''.join(card(row, live_ids) for row in stories[:limit])}</div></section>'''


def render_home(nav: dict[str, Any], feed: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str]) -> str:
    if not stories:
        raise SystemExit("Refusing public homepage: no reader-facing news")
    lead = stories[0]
    others = [row for row in stories if row.get("id") != lead.get("id")]
    rail_rows = others[:4]
    rail = "".join(f'''<article class="rail-story"><div class="kicker">{esc(str(row.get('section') or 'ȘTIRI').replace('_',' '))}</div><a href="{esc(story_path(row))}"><strong>{esc(row.get('headline'))}</strong></a><div class="meta">{esc(date_label(row))}{' · arhivă' if str(row.get('id')) not in live_ids else ''}</div></article>''' for row in rail_rows)
    paras = "".join(f'<p>{esc(p)}</p>' for p in (lead.get("paragraphs") or [])[:1])
    latest = others[:3]
    groups = {key: [row for row in stories if bucket(row) == key] for key in ("bani-publici", "servicii", "cultura-evenimente", "sport")}
    venues = "".join(f'''<a class="venue" href="/unde-iesim/local/{esc(place.get('slug') or place.get('id'))}/"><strong>{esc(place.get('name'))}</strong><span>{esc(place.get('summary') or 'Fișă verificată editorial.')}</span></a>''' for place in (feed.get("unde_iesim") or [])[:4])
    body = f'''<main><div class="live-strip"><div><strong>Actualizat</strong> <span>{esc(feed.get('generated_at'))}</span></div><span>{len(live_ids)} materiale în fluxul curent · arhiva verificată completează contextul</span></div><div class="lead-grid"><section class="hero"><div class="kicker">{esc(str(lead.get('section') or 'ȘTIRI').replace('_',' '))}</div><h1><a href="{esc(story_path(lead))}">{esc(lead.get('headline'))}</a></h1><p class="dek">{esc(lead.get('dek'))}</p>{paras}<div class="sources">{source_links(lead)}</div></section><aside class="rail"><h2>De citit acum</h2>{rail}</aside></div>{section_block('Ultimele știri','ultimele',latest,live_ids)}{section_block('Bani publici','bani-publici',groups['bani-publici'],live_ids)}{section_block('Servicii','servicii',groups['servicii'],live_ids)}{section_block('Cultură & Evenimente','cultura-evenimente',groups['cultura-evenimente'],live_ids)}{section_block('Sport','sport',groups['sport'],live_ids)}{('<section class="section"><div class="section-head"><h2>Unde ieșim</h2><a href="/unde-iesim/">Vezi ghidul</a></div><div class="venue-grid">'+venues+'</div></section>') if venues else ''}</main>'''
    return shell(nav, title="VÂLCEA CLAR — Știri din Vâlcea", description="Știri locale verificate din Vâlcea, ordonate după actualitate și relevanță.", canonical=BASE+"/", body=body)


def render_news_index(nav: dict[str, Any], stories: list[dict[str, Any]], live_ids: set[str]) -> str:
    rows = "".join(f'''<article class="list-row"><div><div class="kicker">{esc(str(row.get('section') or 'ȘTIRI').replace('_',' '))}</div><div class="story-date">{esc(date_label(row))}{' · arhivă' if str(row.get('id')) not in live_ids else ''}</div></div><div><h2><a href="{esc(story_path(row))}">{esc(row.get('headline'))}</a></h2><p>{esc(row.get('dek'))}</p></div></article>''' for row in stories)
    groups = {key: [row for row in stories if bucket(row) == key] for key in ("bani-publici", "servicii", "cultura-evenimente", "sport")}
    sections = section_block('Bani publici','bani-publici',groups['bani-publici'],live_ids,6) + section_block('Servicii','servicii',groups['servicii'],live_ids,6) + section_block('Cultură & Evenimente','cultura-evenimente',groups['cultura-evenimente'],live_ids,6) + section_block('Sport','sport',groups['sport'],live_ids,6)
    body = f'''<main><div class="kicker">ȘTIRI</div><h1 class="index-title">Știrile Vâlcii, puse în ordine.</h1><p class="index-dek">Aici apar numai materiale jurnalistice publicabile. Dosarele de documentare și monitoarele interne nu sunt folosite pentru a umple categorii.</p><section id="ultimele" class="all-list">{rows}</section>{sections}</main>'''
    return shell(nav, title="Știri — VÂLCEA CLAR", description="Toate știrile VÂLCEA CLAR, cu secțiuni curate pentru bani publici, servicii, cultură și sport.", canonical=BASE+"/stiri/", body=body)


def factbox(story: dict[str, Any]) -> str:
    rows = story.get("factbox") or []
    if not rows:
        return ""
    return '<section class="factbox">' + "".join(f'<div class="fact"><b>{esc(row.get("label"))}</b><span>{esc(row.get("value"))}</span></div>' for row in rows if isinstance(row, dict)) + '</section>'


def rich_sections(story: dict[str, Any]) -> str:
    parts = []
    for section in story.get("article_sections") or []:
        if not isinstance(section, dict) or not section.get("title"):
            continue
        ps = "".join(f'<p>{esc(p)}</p>' for p in section.get("paragraphs") or [])
        bullets = section.get("bullets") or []
        ul = '<ul>' + ''.join(f'<li>{esc(item)}</li>' for item in bullets) + '</ul>' if bullets else ''
        parts.append(f'<section class="rich"><h2>{esc(section.get("title"))}</h2>{ps}{ul}</section>')
    return "".join(parts)


def render_story(nav: dict[str, Any], story: dict[str, Any]) -> str:
    body_ps = "".join(f'<p>{esc(p)}</p>' for p in story.get("paragraphs") or [])
    body = f'''<main><article class="article"><div class="kicker">{esc(str(story.get('section') or 'ȘTIRI').replace('_',' '))}</div><h1>{esc(story.get('headline'))}</h1><p class="dek">{esc(story.get('dek'))}</p><div class="story-date">Publicat {esc(date_label(story))}</div>{factbox(story)}<div class="article-body">{body_ps}</div>{rich_sections(story)}<section class="article-sources"><h2>Surse</h2><ul>{source_links(story, True)}</ul></section><a class="back" href="/stiri/">← Toate știrile</a></article></main>'''
    return shell(nav, title=f"{story.get('headline')} — VÂLCEA CLAR", description=str(story.get("dek") or ""), canonical=str(story.get("canonical_url") or BASE+story_path(story)), body=body)


def render_about(nav: dict[str, Any]) -> str:
    principles = [
        ("01", "Fapte, nu completări", "Publicăm numai ceea ce poate fi atribuit unei surse identificabile. Necunoscutele rămân marcate ca necunoscute."),
        ("02", "Sursa la final", "Cititorul primește întâi produsul jurnalistic complet. Documentele originale sunt păstrate la finalul fiecărei știri."),
        ("03", "Drept la replică", "Subiectele critice cer poziția persoanei sau instituției vizate și separarea acuzației de faptul demonstrat."),
        ("04", "Corecții vizibile", ""),
        ("05", "Imagini reale", ""),
        ("06", "Distribuție responsabilă", ""),
    ]
    grid = "".join(f'<section class="principle"><div class="num">{num}</div><h2>{esc(title)}</h2>{f"<p>{esc(text)}</p>" if text else ""}</section>' for num, title, text in principles)
    body = f'''<main><div class="kicker">DESPRE PUBLICAȚIE</div><h1 class="index-title">Clar înainte de rapid.</h1><p class="index-dek">VÂLCEA CLAR este o publicație locală construită în jurul documentului, contextului și utilității pentru cititor.</p><div class="about-grid">{grid}</div></main>'''
    return shell(nav, title="Despre VÂLCEA CLAR", description="Principiile editoriale VÂLCEA CLAR.", canonical=BASE+"/despre/", body=body)


def render_venues(nav: dict[str, Any], feed: dict[str, Any]) -> str:
    venues = "".join(f'''<a class="venue" href="/unde-iesim/local/{esc(place.get('slug') or place.get('id'))}/"><strong>{esc(place.get('name'))}</strong><span>{esc(place.get('summary') or 'Fișă verificată editorial.')}</span></a>''' for place in feed.get("unde_iesim") or [])
    body = f'''<main><div class="kicker">GHID LOCAL</div><h1 class="index-title">Unde ieșim</h1><p class="index-dek">Locuri verificate editorial din Vâlcea.</p><div class="venue-grid">{venues}</div></main>'''
    return shell(nav, title="Unde ieșim — VÂLCEA CLAR", description="Ghid local VÂLCEA CLAR.", canonical=BASE+"/unde-iesim/", body=body)


def build() -> dict[str, Any]:
    nav = load(NAVIGATION)
    feed = load(FEED)
    archive = load(ARCHIVE, {"stories": []})
    stories, live_ids = union_stories(feed, archive)
    if not stories:
        raise SystemExit("Public UX reset has no reader-facing stories")
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "index.html").write_text(render_home(nav, feed, stories, live_ids), encoding="utf-8")
    news_index = RUNTIME / "stiri" / "index.html"
    news_index.parent.mkdir(parents=True, exist_ok=True)
    news_index.write_text(render_news_index(nav, stories, live_ids), encoding="utf-8")
    for story in stories:
        target = RUNTIME / story_path(story).strip("/") / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render_story(nav, story), encoding="utf-8")
    about = RUNTIME / "despre" / "index.html"
    about.parent.mkdir(parents=True, exist_ok=True)
    about.write_text(render_about(nav), encoding="utf-8")
    venues = RUNTIME / "unde-iesim" / "index.html"
    venues.parent.mkdir(parents=True, exist_ok=True)
    venues.write_text(render_venues(nav, feed), encoding="utf-8")
    state = {
        "schema_version": "1.0",
        "contract_id": "valcea-clar-public-ux-v1",
        "navigation_contract": nav.get("contract_id"),
        "safe_story_count": len(stories),
        "live_story_count": len([sid for sid in live_ids if sid in {str(row.get('id')) for row in stories}]),
        "story_ids": [str(row.get("id")) for row in stories],
        "routes": ["/", "/stiri/", "/despre/", "/unde-iesim/"] + [story_path(row) for row in stories],
        "policy": {
            "monitoring_is_news": False,
            "investigation_open_is_news": False,
            "cross_category_fill": False,
            "archive_depth_allowed_with_label": True,
            "same_navigation_everywhere": True,
        },
    }
    write_json(STATE, state)
    validate(nav, stories)
    return state


def validate(nav: dict[str, Any] | None = None, stories: list[dict[str, Any]] | None = None) -> None:
    nav = nav or load(NAVIGATION)
    if stories is None:
        feed = load(FEED)
        archive = load(ARCHIVE, {"stories": []})
        stories, _live = union_stories(feed, archive)
    required = [(str(item.get("label")), str(item.get("href"))) for item in nav.get("items") or []]
    pages = [RUNTIME / "index.html", RUNTIME / "stiri" / "index.html", RUNTIME / "despre" / "index.html", RUNTIME / "unde-iesim" / "index.html"]
    pages += [RUNTIME / story_path(row).strip("/") / "index.html" for row in stories]
    for path in pages:
        if not path.is_file():
            raise SystemExit(f"Public UX missing page: {path}")
        text = path.read_text(encoding="utf-8")
        if f'data-nav-contract="{nav.get("contract_id")}"' not in text:
            raise SystemExit(f"Public UX navigation contract missing: {path}")
        for label, href in required:
            if f'<a href="{esc(href)}">{esc(label)}</a>' not in text:
                raise SystemExit(f"Public UX navigation drift in {path}: {label}")
    home = (RUNTIME / "index.html").read_text(encoding="utf-8")
    news = (RUNTIME / "stiri" / "index.html").read_text(encoding="utf-8")
    forbidden = ("REDACTIE STORY-FIRST", "REDAcȚIE STORY-FIRST", "olanesti-bridge-monitor")
    for token in forbidden:
        if token.lower() in home.lower() or token.lower() in news.lower():
            raise SystemExit(f"Public UX forbidden presentation token leaked: {token}")
    if '<div class="cards"></div>' in home or '<div class="cards"></div>' in news:
        raise SystemExit("Public UX emitted an empty category grid")
    held = held_ids()
    for story in stories:
        if not is_news(story, held):
            raise SystemExit(f"Non-news story leaked into public UX: {story.get('id')}")
        key = bucket(story)
        if key == "cultura-evenimente" and not any(token in str(story.get("section") or "").upper() for token in ("CULT", "EVEN")):
            raise SystemExit(f"Culture taxonomy leak: {story.get('id')}")
    print("VÂLCEA CLAR public UX validation: PASS")


def self_test() -> None:
    held = {"held"}
    assert is_news({"id":"held","headline":"x","sources":[{"url":"https://x"}]}, held) is False
    assert is_news({"id":"d","section":"INVESTIGAȚII","headline":"x","sources":[{"url":"https://x"}]}, set()) is False
    assert is_news({"id":"e","section":"MOBILITATE","headline":"x","sources":[{"url":"https://x"}]}, set()) is True
    assert bucket({"section":"CULTURĂ"}) == "cultura-evenimente"
    assert bucket({"section":"MOBILITATE"}) == "servicii"
    assert bucket({"section":"SPORT"}) == "sport"
    print("VÂLCEA CLAR public UX self-test: PASS")


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
        return 0
    state = build()
    print(json.dumps({"status":"PASS","stories":state["safe_story_count"],"live":state["live_story_count"],"navigation":state["navigation_contract"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
