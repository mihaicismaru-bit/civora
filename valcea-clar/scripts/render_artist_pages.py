#!/usr/bin/env python3
"""Render indexable VÂLCEA CLAR artist directory and per-artist pages."""
from __future__ import annotations

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTISTS = ROOT / "site" / "runtime" / "artists.json"
RUNTIME = ROOT / "site" / "runtime"
INDEXING = ROOT / "site" / "indexing_routes.json"
BASE = "https://valceaclar.ro"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def shell(title: str, description: str, body: str, canonical: str) -> str:
    return f'''<!doctype html><html lang="ro"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — VÂLCEA CLAR</title><meta name="description" content="{esc(description)}">
<link rel="canonical" href="{esc(canonical)}"><meta name="robots" content="index,follow">
<meta property="og:type" content="profile"><meta property="og:site_name" content="VÂLCEA CLAR"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}">
<style>
:root{{--navy:#071a3d;--red:#d71920;--ink:#101828;--muted:#667085;--line:#e4e7ec;--soft:#f6f7f9}}*{{box-sizing:border-box}}body{{margin:0;color:var(--ink);font:16px/1.6 system-ui,-apple-system,Segoe UI,Arial,sans-serif}}header{{background:var(--navy);color:white;padding:20px 22px}}header a{{color:white;text-decoration:none;font:700 32px Georgia,serif}}nav{{margin-top:10px;display:flex;gap:18px;flex-wrap:wrap}}nav a{{font:800 12px system-ui;color:#fff;text-transform:uppercase}}main{{max-width:1050px;margin:auto;padding:38px 22px 64px}}.k{{color:var(--red);font-weight:900;font-size:12px;letter-spacing:.08em;text-transform:uppercase}}h1{{font:800 clamp(38px,6vw,66px)/1.04 Georgia,serif;letter-spacing:-.03em;margin:7px 0 14px}}h2{{font:800 25px/1.2 Georgia,serif}}.dek{{font-size:20px;color:#475467;max-width:800px}}.grid{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:15px;margin-top:28px}}.card{{border:1px solid var(--line);border-radius:12px;padding:16px;text-decoration:none;color:inherit}}.card strong{{display:block;font:700 21px Georgia,serif}}.card span{{color:var(--muted);font-size:13px}}.bio{{font:18px/1.72 Georgia,serif;max-width:820px}}.box{{margin-top:28px;border-top:2px solid var(--ink);padding-top:14px}}ul{{padding-left:20px}}li{{margin:8px 0}}.links{{display:flex;gap:9px;flex-wrap:wrap}}.links a{{border:1px solid var(--line);padding:7px 11px;border-radius:999px;text-decoration:none;font-weight:750}}.status{{background:var(--soft);border-left:4px solid var(--red);padding:13px 16px;color:#475467;margin:22px 0}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}main{{padding:28px 16px 52px}}}}
</style></head><body><header><a href="/">VÂLCEA CLAR</a><nav><a href="/stiri/">Știri</a><a href="/artisti/">Artiști</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>{body}</body></html>'''


def label_for_link(kind: str) -> str:
    return {
        "official_web": "Site oficial", "instagram": "Instagram", "facebook": "Facebook",
        "youtube": "YouTube", "spotify": "Spotify", "tiktok": "TikTok", "soundcloud": "SoundCloud",
        "bandcamp": "Bandcamp", "discogs": "Discogs"
    }.get(kind, kind.replace("_", " ").title())


def appearance_label(row: dict) -> str:
    title = str(row.get("title") or row.get("name") or "Apariție documentată").strip()
    date = str(row.get("date") or "").strip()
    role = str(row.get("role") or "").strip()
    institution = str(row.get("institution") or "").strip()
    suffix = " · ".join(value for value in (date, institution, role) if value)
    return title + (f" — {suffix}" if suffix else "")


def render_index(profiles: list[dict]) -> None:
    cards = []
    for p in profiles:
        appearances = p.get("appearances") or []
        labels = [appearance_label(row) for row in appearances[:2] if isinstance(row, dict)]
        if not labels:
            labels = [row.get("name", "") for row in p.get("festivals", [])[:2] if isinstance(row, dict)]
        cards.append(f'<a class="card" href="{esc(p["path"])}"><strong>{esc(p["name"])}</strong><span>{esc(", ".join(labels) or "Profil artistic verificat")}</span></a>')
    description = "Artiști, actori, regizori, dirijori și ansambluri care apar în programele culturale documentate de VÂLCEA CLAR, cu biografii și conturi externe validate când identitatea este univocă."
    body = f'<main><div class="k">ARTIST INTELLIGENCE</div><h1>Artiști</h1><p class="dek">{esc(description)}</p><div class="grid">{"".join(cards)}</div></main>'
    target = RUNTIME / "artisti" / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(shell("Artiști", description, body, BASE + "/artisti/"), encoding="utf-8")


def render_profile(p: dict) -> None:
    appearances = p.get("appearances") or []
    if not appearances:
        appearances = [
            {"kind":"festival","story_id":row.get("story_id"),"title":row.get("name"),"role":"artist / performer"}
            for row in p.get("festivals", []) if isinstance(row, dict)
        ]
    appearance_links = []
    for row in appearances:
        if not isinstance(row, dict):
            continue
        label = appearance_label(row)
        story_id = str(row.get("story_id") or "").strip()
        source_url = str(row.get("source_url") or "").strip()
        if story_id:
            appearance_links.append(f'<li><a href="/stiri/{esc(story_id)}/">{esc(label)}</a></li>')
        elif source_url:
            appearance_links.append(f'<li><a href="{esc(source_url)}" rel="nofollow noopener">{esc(label)}</a></li>')
        else:
            appearance_links.append(f'<li>{esc(label)}</li>')

    external = []
    for kind, urls in (p.get("links") or {}).items():
        for url in urls[:2]:
            external.append(f'<a href="{esc(url)}" rel="nofollow noopener" target="_blank">{esc(label_for_link(kind))}</a>')
    status_text = (
        "Identitatea externă a fost potrivită în registrul muzical; linkurile afișate provin din relații publice asociate acelei identități."
        if p.get("musicbrainz_id") else
        "Apariția în program este verificată, dar identitatea externă nu este încă suficient de univocă pentru a atașa conturi sociale fără risc de confuzie."
    )
    description = str(p.get("bio") or f"Profilul {p.get('name')} în arhiva culturală VÂLCEA CLAR.")
    links = f'<div class="links">{"".join(external)}</div>' if external else '<p>Conturile externe rămân în verificare.</p>'
    body = f'''<main><article><div class="k">ARTIST</div><h1>{esc(p.get("name"))}</h1><p class="dek">Profil verificat în contextul programelor culturale din Vâlcea.</p><div class="status">{esc(status_text)}</div><div class="bio"><p>{esc(description)}</p></div><section class="box"><h2>Apariții documentate de VÂLCEA CLAR</h2><ul>{''.join(appearance_links)}</ul></section><section class="box"><h2>Pagini oficiale și sociale validate</h2>{links}</section><section class="box"><h2>Surse de identificare</h2><ul>{''.join(f'<li><a href="{esc(url)}" rel="nofollow noopener">Sursă program</a></li>' for url in p.get("source_urls", []))}</ul></section><p><a href="/artisti/">← Toți artiștii</a></p></article></main>'''
    target = RUNTIME / p["path"].strip("/") / "index.html"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(shell(str(p.get("name")), description[:280], body, BASE + p["path"]), encoding="utf-8")


def update_indexing(profiles: list[dict]) -> None:
    doc = load(INDEXING)
    base_routes = [str(r) for r in doc.get("routes", []) if not str(r).startswith("/artisti/")]
    artist_routes = ["/artisti/"] + [str(p["path"]) for p in profiles]
    doc["routes"] = list(dict.fromkeys(base_routes + artist_routes))
    policy = doc.setdefault("policy", {})
    policy["artist_routes_owned_by_artist_intelligence"] = True
    policy["artist_external_identity_fail_closed"] = True
    policy["artist_sources_include_performing_arts_programmes"] = True
    INDEXING.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    doc = load(ARTISTS)
    profiles = [p for p in doc.get("profiles", []) if p.get("publication_status") == "public" and p.get("path")]
    profiles.sort(key=lambda p: str(p.get("name") or "").casefold())
    if not profiles:
        raise SystemExit("No public artist profiles to render")
    render_index(profiles)
    for p in profiles:
        render_profile(p)
    update_indexing(profiles)
    print(json.dumps({"status":"PASS","profiles":len(profiles),"routes":len(profiles)+1}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
