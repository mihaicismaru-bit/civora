#!/usr/bin/env python3
"""Project structured editorial fields into already-rendered story pages.

`render_story_pages.py` owns canonical routing, provenance-backed photographs,
JSON-LD, related links and the global story shell.  This narrow postprocessor
only upgrades the article body when a verified story carries structured
`factbox` / `article_sections` fields.  It is idempotent and skips bespoke
pages that already declare their own editorial product presentation.
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
RUNTIME = ROOT / "site" / "runtime" / "stiri"
MARKER = 'data-rich-structured-story="v1"'


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def render_factbox(rows: list[dict[str, Any]]) -> str:
    cells = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip()
        value = str(row.get("value") or "").strip()
        if label and value:
            cells.append(f'<div class="rich-fact"><b>{esc(value)}</b><span>{esc(label)}</span></div>')
    if not cells:
        return ""
    return '<div class="rich-factbox" aria-label="Cifre și repere cheie">' + "".join(cells) + "</div>"


def render_sections(rows: list[dict[str, Any]]) -> str:
    sections = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        paragraphs = [str(value).strip() for value in row.get("paragraphs") or [] if str(value).strip()]
        bullets = [str(value).strip() for value in row.get("bullets") or [] if str(value).strip()]
        if not title or (not paragraphs and not bullets):
            continue
        body = "".join(f"<p>{esc(value)}</p>" for value in paragraphs)
        if bullets:
            body += "<ul>" + "".join(f"<li>{esc(value)}</li>" for value in bullets) + "</ul>"
        sections.append(f'<section class="rich-story-section"><h2>{esc(title)}</h2>{body}</section>')
    return "".join(sections)


def transform_page(text: str, item: dict[str, Any]) -> str:
    if MARKER in text:
        return text
    # The gambling dossier has its own richer, hand-shaped presentation contract.
    if 'data-editorial-product="gambling-dossier-explainer"' in text:
        return text
    factbox = render_factbox(item.get("factbox") or [])
    sections = render_sections(item.get("article_sections") or [])
    if not factbox and not sections:
        return text

    structured = f'<article class="rich-structured-story" {MARKER}>{factbox}{sections}</article>'
    replaced, count = re.subn(r"<article(?:\s[^>]*)?>.*?</article>", structured, text, count=1, flags=re.S | re.I)
    if count != 1:
        raise ValueError(f"article_body_not_found:{item.get('id')}")

    css = r'''
.rich-structured-story{margin-top:26px}.rich-factbox{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:3px solid #101828;border-bottom:1px solid #d0d5dd;margin:0 0 34px}.rich-fact{padding:17px 13px;border-right:1px solid #d0d5dd}.rich-fact:last-child{border-right:0}.rich-fact b{display:block;color:#d71920;font:800 25px/1.05 Georgia,serif;margin-bottom:7px}.rich-fact span{display:block;color:#667085;font-size:11px;line-height:1.35;text-transform:uppercase;letter-spacing:.035em}.rich-story-section{padding-bottom:24px;margin-bottom:27px;border-bottom:1px solid #e4e7ec}.rich-story-section:last-child{border-bottom:0}.rich-story-section h2{font:800 29px/1.15 Georgia,serif;letter-spacing:-.015em;margin:0 0 14px}.rich-story-section p{font:18px/1.68 Georgia,serif;margin:0 0 17px}.rich-story-section li{font:17px/1.55 Georgia,serif;margin:7px 0}@media(max-width:680px){.rich-factbox{grid-template-columns:1fr 1fr}.rich-fact:nth-child(2n){border-right:0}.rich-story-section h2{font-size:25px}}
'''
    if "</style>" not in replaced:
        raise ValueError(f"style_boundary_not_found:{item.get('id')}")
    return replaced.replace("</style>", css + "</style>", 1)


def apply() -> dict[str, Any]:
    facts = load(FACTS)
    changed = []
    skipped_missing = []
    for item in facts.get("facts") or []:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        if not item.get("factbox") and not item.get("article_sections"):
            continue
        story_id = re.sub(r"[^a-z0-9-]+", "-", str(item["id"]).lower()).strip("-")
        path = RUNTIME / story_id / "index.html"
        if not path.is_file():
            skipped_missing.append(story_id)
            continue
        original = path.read_text(encoding="utf-8")
        updated = transform_page(original, item)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed.append(story_id)
    return {"status":"PASS","changed":len(changed),"story_ids":changed,"missing_runtime":skipped_missing}


def self_test() -> int:
    sample = "<html><head><style>p{}</style></head><body><article><p>old</p></article></body></html>"
    item={"id":"hcl-test","factbox":[{"label":"Vot","value":"20–0–0"}],"article_sections":[{"title":"Ce s-a decis","paragraphs":["Consiliul aprobă măsura."]}]}
    out=transform_page(sample,item)
    assert MARKER in out and "Ce s-a decis" in out and "20–0–0" in out and "<p>old</p>" not in out
    assert transform_page(out,item)==out
    print("VÂLCEA CLAR rich story section renderer self-test: PASS")
    return 0


def main() -> int:
    parser=argparse.ArgumentParser()
    parser.add_argument("--self-test",action="store_true")
    args=parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(apply(),ensure_ascii=False))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
