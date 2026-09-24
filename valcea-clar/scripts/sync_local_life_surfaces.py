#!/usr/bin/env python3
from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "editorial" / "local_life_surface_registry.json"
RUNTIME = ROOT / "site" / "runtime" / "unde-iesim"
TZ = ZoneInfo("Europe/Bucharest")


def load() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def esc(value) -> str:
    return html.escape(str(value or ""))


def same_local_date(value: str, today: str) -> bool:
    return str(value or "")[:10] == today


def shell(title: str, eyebrow: str, intro: str, body: str, slug: str) -> str:
    canonical = f"https://valceaclar.ro/unde-iesim/{slug}/"
    return f"""<!doctype html>
<html lang='ro'>
<head>
<meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{esc(title)} — VÂLCEA CLAR</title>
<meta name='description' content='{esc(intro)}'>
<link rel='canonical' href='{canonical}'>
<meta property='og:title' content='{esc(title)} — VÂLCEA CLAR'>
<meta property='og:description' content='{esc(intro)}'>
<meta property='og:url' content='{canonical}'>
<meta name='twitter:card' content='summary'>
<style>
body{{font:16px/1.55 system-ui,-apple-system,sans-serif;margin:0;color:#101828;background:#fff}}
main{{max-width:980px;margin:auto;padding:28px 22px 60px}}
a{{color:#175cd3}}.eyebrow{{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#667085}}
h1{{font:700 42px/1.05 Georgia,serif;margin:.15em 0 .25em}}h2{{font:700 25px/1.15 Georgia,serif;margin:.2em 0}}
.card{{border-top:1px solid #e4e7ec;padding:18px 0}}.meta{{color:#475467}}.src{{font-size:12px;color:#667085}}.notice{{padding:16px;border:1px solid #d0d5dd;background:#f9fafb}}
nav{{display:flex;gap:12px;flex-wrap:wrap;margin:18px 0 28px}}nav a{{font-weight:650}}
</style>
</head>
<body><main>
<p><a href='/'>← Acasă</a></p>
<div class='eyebrow'>{esc(eyebrow)}</div><h1>{esc(title)}</h1><p>{esc(intro)}</p>
<nav><a href='/unde-iesim/'>Evenimente</a><a href='/unde-iesim/sport/'>Sport</a><a href='/unde-iesim/cinema/'>Cinema</a><a href='/unde-iesim/restaurante/'>Restaurante</a><a href='/unde-iesim/meniul-zilei/'>Meniul zilei</a><a href='/unde-iesim/fitness/'>Fitness</a></nav>
{body}
<p class='src'>VÂLCEA CLAR afișează numai informații cu proveniență verificabilă. Rândurile stale sau contradictorii sunt retrase până la reverificare.</p>
</main></body></html>"""


def sport_body(doc: dict, today: str) -> str:
    rows=[]
    for e in doc.get("sport",{}).get("entries",[]):
        if str(e.get("date") or "") < today or e.get("status") in {"cancelled","past"}:
            continue
        note=f"<p class='meta'>{esc(e.get('note'))}</p>" if e.get("note") else ""
        rows.append(f"""<article class='card'><h2>{esc(e.get('home'))} – {esc(e.get('away'))}</h2><p><strong>{esc(e.get('date'))} · {esc(e.get('time') or 'ora de verificat')}</strong></p><p>{esc(e.get('competition'))} · {esc(e.get('venue'))} · {esc(e.get('locality'))}</p>{note}<p class='src'><a href='{esc(e.get('source_url'))}' rel='nofollow noopener'>Sursă</a> · {esc(e.get('source_tier'))} · verificat {esc(e.get('checked_at'))}</p></article>""")
    return "".join(rows) or "<div class='notice'>Nu există în acest moment un meci viitor suficient de proaspăt verificat pentru afișare. Programul revine automat după reconciliere.</div>"


def cinema_body(doc: dict, today: str) -> str:
    rows=[]
    for e in doc.get("cinema",{}).get("entries",[]):
        if doc.get("cinema",{}).get("date") != today or not same_local_date(e.get("checked_at"), today):
            continue
        rows.append(f"""<article class='card'><h2>{esc(e.get('film'))}</h2><p><strong>{esc(e.get('time'))}</strong> · {esc(e.get('cinema'))}</p><p>{esc(e.get('format'))} · {esc(e.get('locality'))}</p><p class='src'><a href='{esc(e.get('source_url'))}' rel='nofollow noopener'>Program oficial</a> · verificat {esc(e.get('checked_at'))}</p></article>""")
    return "".join(rows) or "<div class='notice'>Nu există proiecții pentru astăzi cu dată și oră explicit verificate în registrul curent.</div>"


def menu_body(doc: dict, today: str) -> str:
    section=doc.get("menu",{})
    rows=[]
    for e in section.get("entries",[]):
        if e.get("date") != today or not same_local_date(e.get("checked_at"), today):
            continue
        dishes=" · ".join(esc(x) for x in e.get("dishes",[]) if x)
        rows.append(f"""<article class='card'><h2>{esc(e.get('restaurant'))}</h2><p><strong>{esc(e.get('price'))}</strong>{' · '+esc(e.get('service_window')) if e.get('service_window') else ''}</p><p>{dishes}</p><p class='src'><a href='{esc(e.get('source_url'))}' rel='nofollow noopener'>Sursă</a> · verificat {esc(e.get('checked_at'))}</p></article>""")
    if rows:
        return "".join(rows)
    reason=section.get("empty_reason") or "Nu există meniuri verificate în aceeași zi."
    return f"<div class='notice'>{esc(reason)}</div>"


def fitness_body(doc: dict) -> str:
    rows=[]
    for e in doc.get("fitness",{}).get("entries",[]):
        acts=" · ".join(esc(x) for x in e.get("activities",[]) if x)
        note=f"<p class='meta'>{esc(e.get('note'))}</p>" if e.get("note") else ""
        rows.append(f"""<article class='card'><div class='eyebrow'>{esc(e.get('locality'))}</div><h2>{esc(e.get('name'))}</h2><p><strong>{esc(e.get('address'))}</strong></p><p>{acts}</p>{note}<p class='src'><a href='{esc(e.get('source_url'))}' rel='nofollow noopener'>Sursă</a> · {esc(e.get('source_tier'))} · verificat {esc(e.get('checked_at'))}</p></article>""")
    return "".join(rows) or "<div class='notice'>Registrul sălilor este în reverificare. Nu afișăm adrese neverificate.</div>"


def main() -> int:
    doc=load()
    today=datetime.now(TZ).date().isoformat()
    pages={
        "sport": shell("SPORT", "Local Life", "Meciuri și competiții cu interes local, afișate numai după verificarea datei, orei și adversarului.", sport_body(doc,today), "sport"),
        "cinema": shell("CINEMA AZI", "Local Life", "Proiecții pentru ziua curentă, separate pe film și oră. Programul expirat este retras automat.", cinema_body(doc,today), "cinema"),
        "meniul-zilei": shell("MENIUL ZILEI", "Local Life", "Meniuri afișate numai când au fost verificate în aceeași zi. O ofertă veche nu este tratată drept meniul de astăzi.", menu_body(doc,today), "meniul-zilei"),
        "fitness": shell("FITNESS", "Local Life", "Săli și adrese curente. Directoarele vechi nu prevalează asupra unei locații actuale corroborate.", fitness_body(doc), "fitness"),
    }
    for slug,content in pages.items():
        target=RUNTIME/slug/"index.html"
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(content,encoding="utf-8")
    print(json.dumps({"status":"UPDATED","date":today,"routes":sorted(pages)},ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
