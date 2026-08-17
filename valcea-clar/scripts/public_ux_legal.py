#!/usr/bin/env python3
"""Render legal pages with the same public navigation and masthead."""
from __future__ import annotations

import shutil
from pathlib import Path

import public_ux_reset as ux

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
DIST = ROOT / "dist" / "chatgpt-sites"
LEGAL = SITE / "legal" / "legal_pages.json"
NAV = SITE / "navigation.json"
BASE = "https://valceaclar.ro"


def render(nav: dict, doc: dict, slug: str) -> str:
    page = (doc.get("pages") or {})[slug]
    sections = "".join(
        f'<section class="rich"><h2>{ux.esc(section.get("title"))}</h2>' + "".join(f'<p>{ux.esc(p)}</p>' for p in section.get("paragraphs") or []) + '</section>'
        for section in page.get("sections") or []
    )
    body = f'''<main><article class="article"><div class="kicker">DOCUMENT PUBLIC</div><h1>{ux.esc(page.get('title'))}</h1><p class="dek">{ux.esc(page.get('intro'))}</p><div class="story-date">În vigoare din {ux.esc(doc.get('effective_date'))}</div>{sections}<section class="article-sources"><h2>Contact</h2><p><a href="mailto:{ux.esc(doc.get('contact_email'))}">{ux.esc(doc.get('contact_email'))}</a></p></section></article></main>'''
    return ux.shell(nav, title=f"{page.get('title')} — VÂLCEA CLAR", description=str(page.get("description") or page.get("intro") or ""), canonical=BASE + str(page.get("path")), body=body, robots="index,follow")


def main() -> int:
    nav = ux.load(NAV)
    doc = ux.load(LEGAL)
    for slug in ("termeni", "confidentialitate"):
        if slug not in (doc.get("pages") or {}):
            raise SystemExit(f"Legal page missing: {slug}")
        html = render(nav, doc, slug)
        runtime = RUNTIME / slug / "index.html"
        runtime.parent.mkdir(parents=True, exist_ok=True)
        runtime.write_text(html, encoding="utf-8")
        dist = DIST / slug / "index.html"
        dist.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(runtime, dist)
    print("VÂLCEA CLAR public UX legal shell: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
