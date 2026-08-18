#!/usr/bin/env python3
"""Upgrade the canonical gambling story route from fact stream to reader article.

The factual authority remains facts_registry.json. This presenter only groups
already sourced claims into a readable article, adds a compact key-facts box and
restores the canonical navigation. It adds no new factual claim.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "editorial" / "facts_registry.json"
PAGE = ROOT / "site" / "runtime" / "stiri" / "rm-valcea-gambling-authorizations-20260723" / "index.html"
TARGET_ID = "rm-valcea-gambling-authorizations-20260723"


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def target_fact() -> dict[str, Any]:
    doc = load(FACTS)
    target = next((row for row in doc.get("facts") or [] if row.get("id") == TARGET_ID), None)
    if not isinstance(target, dict):
        raise SystemExit("canonical gambling fact missing")
    return target


def claim_map(target: dict[str, Any]) -> dict[str, str]:
    kernel = target.get("fact_kernel") if isinstance(target.get("fact_kernel"), dict) else {}
    return {
        str(row.get("id")): str(row.get("text") or "").strip()
        for row in kernel.get("claims") or []
        if isinstance(row, dict) and row.get("id") and str(row.get("text") or "").strip()
    }


def section(title: str, paragraphs: list[str]) -> str:
    body = "".join(f"<p>{esc(value)}</p>" for value in paragraphs if value)
    return f'<section class="story-section"><h2>{esc(title)}</h2>{body}</section>'


def build_article(target: dict[str, Any]) -> str:
    claims = claim_map(target)
    required = {
        "july-cluster", "new-local-regime", "local-tax", "locations", "onjn-footprint",
        "operator-scale", "ownership-context", "ownership-unknowns", "what-hcl-does-not-prove",
    }
    missing = sorted(required - set(claims))
    if missing:
        raise SystemExit("missing enriched claims: " + ",".join(missing))

    facts = (
        '<div class="key-facts" aria-label="Cifre cheie">'
        '<div><b>11</b><span>hotărâri în 23 iulie 2026</span></div>'
        '<div><b>4</b><span>operatori nominalizați</span></div>'
        '<div><b>1.000 lei</b><span>taxă locală / m² / an</span></div>'
        '<div><b>1 an</b><span>valabilitatea autorizației emise</span></div>'
        '</div>'
    )
    return (
        '<article class="dossier-article" data-editorial-product="gambling-dossier-explainer">'
        + f'<p class="standfirst">{esc(claims["july-cluster"])}</p>'
        + facts
        + section("De ce apar aceste hotărâri în 2026", [claims["new-local-regime"], claims["local-tax"]])
        + section("Unde sunt punctele din seria din 23 iulie", [claims["locations"]])
        + section("Ce arată registrul ONJN în Râmnicu Vâlcea", [claims["onjn-footprint"]])
        + section("Cine sunt operatorii", [claims["operator-scale"]])
        + section("Cine controlează companiile", [claims["ownership-context"], claims["ownership-unknowns"]])
        + section("Ce nu dovedește încă dosarul", [claims["what-hcl-does-not-prove"]])
        + '</article>'
    )


def canonical_header() -> str:
    return (
        '<header class="story-site-header">'
        '<div class="story-mast"><a class="story-brand" href="/">VÂLCEA CLAR</a>'
        '<span>Știrile Vâlcii, fără zgomot.</span></div>'
        '<nav class="story-nav" aria-label="Navigație principală">'
        '<a href="/">Acasă</a><a href="/stiri/">Ultimele știri</a>'
        '<a href="/stiri/#bani-publici">Bani publici</a><a href="/stiri/#servicii">Servicii</a>'
        '<a href="/stiri/#cultura-evenimente">Cultură &amp; Evenimente</a>'
        '<a href="/stiri/#sport">Sport</a><a href="/unde-iesim/">Unde ieșim</a>'
        '</nav></header>'
    )


EXTRA_CSS = r'''
.story-site-header{background:#071a3d;color:#fff;border-bottom:3px solid #d71920}.story-mast{max-width:1180px;margin:auto;padding:20px 22px 14px;display:flex;align-items:flex-end;justify-content:space-between;gap:20px}.story-brand{color:#fff;text-decoration:none;font:800 36px/1 Georgia,serif;letter-spacing:-.025em}.story-mast span{font:italic 14px/1.2 Georgia,serif}.story-nav{max-width:1180px;margin:auto;padding:0 22px;display:flex;gap:22px;overflow-x:auto;white-space:nowrap;border-top:1px solid rgba(255,255,255,.28)}.story-nav a{color:#fff;text-decoration:none;padding:11px 0;font-size:11px;font-weight:800;text-transform:uppercase;letter-spacing:.04em}.story-nav a:hover{text-decoration:underline;text-decoration-color:#d71920;text-decoration-thickness:2px;text-underline-offset:4px}
.dossier-article{margin-top:28px}.dossier-article .standfirst{font:700 21px/1.48 Georgia,serif;color:#1d2939;border-left:4px solid #d71920;padding-left:18px;margin:0 0 26px}.key-facts{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:3px solid #101828;border-bottom:1px solid #d0d5dd;margin:25px 0 36px}.key-facts div{padding:18px 14px 17px;border-right:1px solid #d0d5dd}.key-facts div:last-child{border-right:0}.key-facts b{display:block;font:800 28px/1 Georgia,serif;color:#d71920;margin-bottom:7px}.key-facts span{display:block;color:#475467;font-size:12px;line-height:1.35}.story-section{padding:0 0 25px;margin:0 0 28px;border-bottom:1px solid #e4e7ec}.story-section h2{font:800 29px/1.15 Georgia,serif;letter-spacing:-.015em;margin:0 0 14px}.story-section p{margin:0 0 17px;font:18px/1.68 Georgia,serif}.story-section:last-child{border-bottom:0}
@media(max-width:680px){.story-mast span{display:none}.key-facts{grid-template-columns:1fr 1fr}.key-facts div:nth-child(2){border-right:0}.story-nav{gap:18px}.story-section h2{font-size:25px}}
'''


def patch() -> dict[str, Any]:
    if not PAGE.is_file():
        return {"status": "WAITING_FOR_CANONICAL_ROUTE", "page": str(PAGE)}
    target = target_fact()
    expected_headline = str(target.get("headline") or "")
    raw = PAGE.read_text(encoding="utf-8")
    if expected_headline not in raw:
        return {"status": "WAITING_FOR_ENRICHED_ROUTE", "headline": expected_headline}

    raw = re.sub(r'<header><a href="/">VÂLCEA CLAR</a></header>', canonical_header(), raw, count=1)
    raw = re.sub(r'<article>.*?</article>', build_article(target), raw, count=1, flags=re.S)
    if "story-section{padding" not in raw:
        raw = raw.replace("</style>", EXTRA_CSS + "\n</style>", 1)
    PAGE.write_text(raw, encoding="utf-8")
    return {
        "status": "UPDATED",
        "story_id": TARGET_ID,
        "sections": 6,
        "key_facts": 4,
        "canonical_nav": True,
        "adds_new_facts": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    result = patch()
    if args.check and result["status"] != "UPDATED":
        raise SystemExit(json.dumps(result, ensure_ascii=False))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
