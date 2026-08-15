#!/usr/bin/env python3
"""Render a deployable VÂLCEA CLAR frontpage from the current verified edition.

No LLM is called. The renderer consumes only the publishable edition pointer,
verified edition JSON and the fail-closed public venue projection.
"""
from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
EDITIONS = ROOT / "editions"
PLACES = ROOT / "web" / "data" / "places.json"
POINTER = SITE / "current_edition.json"
RUNTIME = SITE / "runtime"
PUBLISHABLE = {"auto_approved", "editor_approved"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value) -> str:
    return html.escape(str(value or ""), quote=True)


def public_pointer() -> dict:
    pointer = load(POINTER)
    if pointer.get("status") not in PUBLISHABLE or pointer.get("publication_intent") != "publish":
        raise SystemExit("Refusing frontpage render: current pointer is not publishable")
    return pointer


def edition(pointer: dict) -> dict:
    path = ROOT / pointer["json_source"]
    doc = load(path)
    if doc.get("edition_id") != pointer.get("edition_id"):
        raise SystemExit("Refusing frontpage render: edition pointer mismatch")
    if doc.get("status") not in PUBLISHABLE or doc.get("publication_intent") != "publish":
        raise SystemExit("Refusing frontpage render: edition is not publishable")
    return doc


def item_source_links(item: dict) -> str:
    links = []
    for src in item.get("sources", [])[:3]:
        if src.get("url"):
            links.append(f'<a href="{esc(src["url"])}" rel="nofollow noopener">{esc(src.get("name") or "Sursă")}</a>')
    return " · ".join(links)


def visual(item: dict, *, hero=False) -> str:
    v = item.get("visual") or {}
    url = v.get("image_url")
    if not url:
        return ""
    alt = esc(v.get("alt") or item.get("headline"))
    credit = esc(v.get("credit") or "")
    cls = "hero-photo" if hero else "story-photo"
    cap = f'<figcaption>{credit}</figcaption>' if credit else ""
    return f'<figure class="{cls}"><img src="{esc(url)}" alt="{alt}" loading="{"eager" if hero else "lazy"}">{cap}</figure>'


def story_card(item: dict) -> str:
    return f'''<article class="story-card">
      {visual(item)}
      <div class="kicker">{esc(item.get("section", "ȘTIRI").replace("_", " "))}</div>
      <h3>{esc(item.get("headline"))}</h3>
      <p>{esc(item.get("dek"))}</p>
      <div class="sources">{item_source_links(item)}</div>
    </article>'''


def venue_card(place: dict) -> str:
    summary = (place.get("editorial") or {}).get("dek") or (place.get("offer") or {}).get("summary") or "Fișă verificată editorial."
    slug = place.get("slug") or place.get("id")
    return f'''<a class="venue" href="/unde-iesim/local/{esc(slug)}/">
      <strong>{esc(place.get("name"))}</strong>
      <span>{esc(summary)}</span>
    </a>'''


def chrome(title: str, body: str, description: str) -> str:
    return f'''<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(description)}">
<link rel="canonical" href="https://valceaclar.ro/">
<meta property="og:site_name" content="VÂLCEA CLAR">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:url" content="https://valceaclar.ro/">
<style>
:root{{--navy:#071a3d;--navy2:#0d2856;--red:#d71920;--ink:#101828;--muted:#667085;--line:#e4e7ec;--paper:#fff;--soft:#f6f7f9}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.5 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
a{{color:inherit}} .top{{background:var(--navy);color:#fff}} .mast{{max-width:1240px;margin:auto;padding:19px 22px 16px;display:flex;align-items:center;justify-content:space-between;gap:24px}}
.brand{{font:700 clamp(28px,4vw,48px)/1 Georgia,serif;letter-spacing:.035em}} .brand span{{border-bottom:3px solid var(--red);padding-bottom:7px}} .tag{{opacity:.82;font-family:Georgia,serif;margin-top:10px}}
.nav{{border-top:1px solid rgba(255,255,255,.12);max-width:1240px;margin:auto;padding:0 22px;display:flex;gap:24px;overflow:auto;white-space:nowrap}} .nav a{{padding:12px 0;text-decoration:none;font-size:13px;font-weight:800;text-transform:uppercase}}
main{{max-width:1240px;margin:0 auto;padding:26px 22px 54px}} .edition-bar{{display:flex;align-items:center;gap:14px;border-bottom:1px solid var(--line);padding-bottom:12px;margin-bottom:20px;flex-wrap:wrap}} .edition-label{{background:var(--red);color:#fff;padding:7px 11px;border-radius:4px;font-size:12px;font-weight:900;letter-spacing:.04em}} .edition-time{{color:var(--muted);font-size:14px}}
.grid{{display:grid;grid-template-columns:minmax(0,1.9fr) minmax(300px,.75fr);gap:34px}} .hero h1{{font:800 clamp(34px,5vw,64px)/1.04 Georgia,serif;margin:8px 0 14px;letter-spacing:-.025em}} .hero .dek{{font-size:20px;line-height:1.45;color:#344054;max-width:860px}} .kicker{{color:var(--red);font-size:12px;font-weight:900;letter-spacing:.07em;margin-top:10px}} .hero-copy{{font-size:18px;max-width:900px}} .hero-copy p{{margin:13px 0}}
.hero-photo,.story-photo{{margin:18px 0 12px}} figure img{{width:100%;display:block;border-radius:10px;object-fit:cover;max-height:520px}} figcaption{{font-size:12px;color:var(--muted);margin-top:6px}} .sources{{font-size:12px;color:var(--muted);margin-top:12px}} .sources a{{color:#475467}}
.section-title{{font-size:14px;letter-spacing:.055em;text-transform:uppercase;border-bottom:2px solid var(--ink);padding-bottom:7px;margin:28px 0 14px}} .cards{{display:grid;grid-template-columns:repeat(3,1fr);gap:18px}} .story-card{{border-top:3px solid var(--navy);padding-top:12px}} .story-card h3{{font:700 22px/1.15 Georgia,serif;margin:7px 0}} .story-card p{{color:#475467;margin:0}}
.side{{border-left:1px solid var(--line);padding-left:28px}} .side h2{{font:800 15px/1.2 system-ui;text-transform:uppercase;letter-spacing:.06em;border-bottom:2px solid var(--red);padding-bottom:9px;margin:0 0 12px}} .side-story{{padding:13px 0;border-bottom:1px solid var(--line)}} .side-story strong{{display:block;font:700 19px/1.18 Georgia,serif}} .side-story span{{font-size:12px;color:var(--red);font-weight:800}}
.venues{{background:var(--navy);color:#fff;border-radius:10px;padding:18px;margin-top:28px}} .venues .head{{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:8px}} .venues h2{{border:0;margin:0;padding:0;color:#fff}} .venues .cta{{color:#fff;font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,.35);padding:6px 8px;border-radius:999px}} .venue{{display:block;text-decoration:none;padding:12px 0;border-top:1px solid rgba(255,255,255,.14)}} .venue strong{{display:block}} .venue span{{display:block;color:#d0d5dd;font-size:13px;margin-top:3px}}
.note{{margin-top:34px;background:var(--soft);border-left:4px solid var(--red);padding:15px 18px;color:#475467;font-size:13px}} footer{{background:var(--navy);color:#d0d5dd;padding:22px;text-align:center;font-size:13px}}
@media(max-width:900px){{.mast{{align-items:flex-start}} .tag{{display:none}} .grid{{grid-template-columns:1fr}} .side{{border-left:0;padding-left:0;border-top:1px solid var(--line);padding-top:25px}} .cards{{grid-template-columns:1fr}} .hero h1{{font-size:42px}}}}
</style>
</head><body>
<header class="top"><div class="mast"><div><div class="brand"><span>VÂLCEA CLAR</span></div><div class="tag">Știrile Vâlcii, fără zgomot.</div></div><div style="font-size:13px;opacity:.8">valceaclar.ro</div></div>
<nav class="nav"><a href="/">Acasă</a><a href="/#stiri">Știri locale</a><a href="/#administratie">Administrație</a><a href="/#investigatii">Investigații</a><a href="/#sport">Sport</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>
{body}
<footer>VÂLCEA CLAR · informație locală verificată · redactie@valceaclar.ro</footer>
</body></html>'''


def render_home(doc: dict, pointer: dict, places: list[dict]) -> str:
    items = doc.get("items", [])
    editorial = [i for i in items if i.get("section") not in {"UNDE_IEȘIM", "NOTA_REDACTIEI"}]
    if not editorial:
        raise SystemExit("Refusing frontpage render: no editorial lead")
    lead = editorial[0]
    secondary = editorial[1:4]
    rest = editorial[4:]
    slot_label = "EDIȚIA DE DIMINEAȚĂ" if doc.get("slot") == "morning" else "EDIȚIA DE SEARĂ"
    paras = "".join(f'<p>{esc(p)}</p>' for p in lead.get("paragraphs", [])[:2])
    cards = "".join(story_card(i) for i in secondary)
    side_items = "".join(f'<div class="side-story"><span>{esc(i.get("section", "ȘTIRI"))}</span><strong>{esc(i.get("headline"))}</strong></div>' for i in (rest + secondary)[:4])
    venue_html = "".join(venue_card(p) for p in places[:4])
    body = f'''<main>
      <div class="edition-bar"><span class="edition-label">{slot_label}</span><span class="edition-time">{esc(doc.get("edition_date"))} · actualizată automat {esc(doc.get("updated_local"))}</span></div>
      <div class="grid"><section>
        <article class="hero"><div class="kicker">{esc(lead.get("section"))}</div><h1>{esc(lead.get("headline"))}</h1><p class="dek">{esc(lead.get("dek"))}</p>{visual(lead, hero=True)}<div class="hero-copy">{paras}</div><div class="sources">{item_source_links(lead)}</div></article>
        <h2 class="section-title" id="stiri">Alte știri importante</h2><div class="cards">{cards}</div>
      </section><aside class="side"><h2>Top știri</h2>{side_items}
        <section class="venues"><div class="head"><h2>Unde ieșim</h2><a class="cta" href="/unde-iesim/">Vezi ghidul</a></div>{venue_html}</section>
      </aside></div>
      <div class="note">Ediția este generată automat numai din fapte care au trecut pragul de verificare. Informațiile insuficient documentate rămân în coada editorială și nu sunt publicate ca fapte.</div>
    </main>'''
    desc = lead.get("dek") or "Ediția curentă VÂLCEA CLAR — știri locale verificate din Vâlcea."
    return chrome("VÂLCEA CLAR — Ediția curentă", body, desc)


def render_edition_page(doc: dict) -> str:
    articles = []
    for item in doc.get("items", []):
        paras = "".join(f'<p>{esc(p)}</p>' for p in item.get("paragraphs", []))
        articles.append(f'''<article style="max-width:850px;margin:0 auto 38px"><div class="kicker">{esc(item.get("section"))}</div><h2 style="font:700 34px/1.12 Georgia,serif;margin:7px 0 10px">{esc(item.get("headline"))}</h2><p class="dek">{esc(item.get("dek"))}</p>{visual(item)}<div class="hero-copy">{paras}</div><div class="sources">{item_source_links(item)}</div></article>''')
    slot_label = "dimineață" if doc.get("slot") == "morning" else "seară"
    body = f'''<main><div class="edition-bar"><span class="edition-label">EDIȚIA DE {slot_label.upper()}</span><span class="edition-time">{esc(doc.get("updated_local"))}</span></div>{''.join(articles)}</main>'''
    return chrome(doc.get("title") or "VÂLCEA CLAR", body, f"Ediția de {slot_label} VÂLCEA CLAR.")


def main() -> int:
    pointer = public_pointer()
    doc = edition(pointer)
    places_doc = load(PLACES)
    places = places_doc.get("places", [])
    if RUNTIME.exists():
        shutil.rmtree(RUNTIME)
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "index.html").write_text(render_home(doc, pointer, places), encoding="utf-8")

    slot_dir = RUNTIME / ("editia-de-dimineata" if doc.get("slot") == "morning" else "editia-de-seara")
    slot_dir.mkdir(parents=True, exist_ok=True)
    edition_html = render_edition_page(doc)
    (slot_dir / "index.html").write_text(edition_html, encoding="utf-8")
    current_dir = RUNTIME / "editia-curenta"
    current_dir.mkdir(parents=True, exist_ok=True)
    (current_dir / "index.html").write_text(edition_html, encoding="utf-8")

    status = {
        "schema_version": "1.0",
        "edition_id": doc["edition_id"],
        "updated_local": doc.get("updated_local"),
        "frontpage": "site/runtime/index.html",
        "edition_route": pointer.get("path"),
        "generator": doc.get("generator"),
        "paid_llm_api_required": False,
    }
    (RUNTIME / "runtime-status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
