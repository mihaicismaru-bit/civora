#!/usr/bin/env python3
"""Build public VÂLCEA CLAR legal pages from a canonical structured source.

The renderer is deterministic, dependency-free and deliberately contains no tracking,
credentials or remote calls. It writes only the two legal routes unless export is requested.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import shutil
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
SOURCE = SITE / "legal" / "legal_pages.json"
RUNTIME = SITE / "runtime"
DIST = ROOT / "dist" / "chatgpt-sites"
MANIFEST = DIST / "manifest.json"
EXPECTED = {
    "termeni": "/termeni/",
    "confidentialitate": "/confidentialitate/",
}
LEGAL_LINKS = '<a href="/termeni/">Termeni</a><span aria-hidden="true">·</span><a href="/confidentialitate/">Confidențialitate</a>'


def esc(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_source() -> dict[str, Any]:
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError("legal_pages.json must contain an object")
    if doc.get("canonical_domain") != "valceaclar.ro":
        raise ValueError("legal canonical domain drift")
    if doc.get("contact_email") != "redactie@valceaclar.ro":
        raise ValueError("legal contact email drift")
    pages = doc.get("pages")
    if not isinstance(pages, dict) or set(pages) != set(EXPECTED):
        raise ValueError("legal page set must be exactly termeni + confidentialitate")
    for slug, expected_path in EXPECTED.items():
        page = pages[slug]
        if not isinstance(page, dict):
            raise ValueError(f"legal page {slug} must be an object")
        if page.get("path") != expected_path:
            raise ValueError(f"legal route drift for {slug}")
        if not str(page.get("title") or "").strip() or not str(page.get("intro") or "").strip():
            raise ValueError(f"legal page {slug} missing title/intro")
        sections = page.get("sections")
        if not isinstance(sections, list) or len(sections) < 5:
            raise ValueError(f"legal page {slug} is structurally incomplete")
        for section in sections:
            if not isinstance(section, dict) or not str(section.get("title") or "").strip():
                raise ValueError(f"legal page {slug} contains malformed section")
            paragraphs = section.get("paragraphs")
            if not isinstance(paragraphs, list) or not paragraphs or any(not str(p).strip() for p in paragraphs):
                raise ValueError(f"legal page {slug} contains malformed paragraphs")
    return doc


def render(doc: dict[str, Any], slug: str) -> str:
    page = doc["pages"][slug]
    canonical = f"https://valceaclar.ro{page['path']}"
    sections = []
    for section in page["sections"]:
        paragraphs = "".join(f"<p>{esc(paragraph)}</p>" for paragraph in section["paragraphs"])
        sections.append(f'<section class="legal-section"><h2>{esc(section["title"])}</h2>{paragraphs}</section>')
    return f'''<!doctype html>
<html lang="ro">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(page['title'])} — VÂLCEA CLAR</title>
<meta name="description" content="{esc(page['description'])}">
<link rel="canonical" href="{esc(canonical)}">
<meta name="robots" content="index,follow">
<meta property="og:site_name" content="VÂLCEA CLAR">
<meta property="og:type" content="website">
<meta property="og:title" content="{esc(page['title'])} — VÂLCEA CLAR">
<meta property="og:description" content="{esc(page['description'])}">
<meta property="og:url" content="{esc(canonical)}">
<style>
:root{{--navy:#071a3d;--red:#d71920;--ink:#101828;--muted:#667085;--line:#e4e7ec;--paper:#fff;--soft:#f6f7f9}}
*{{box-sizing:border-box}}html{{background:var(--paper)}}body{{margin:0;color:var(--ink);background:var(--paper);font:16px/1.65 Inter,system-ui,-apple-system,Segoe UI,Arial,sans-serif}}
a{{color:inherit}}.top{{background:var(--navy);color:#fff}}.mast{{max-width:1050px;margin:auto;padding:22px 24px 18px;display:flex;justify-content:space-between;align-items:flex-end;gap:24px}}.brand{{font:700 clamp(28px,5vw,45px)/1 Georgia,serif;letter-spacing:.035em}}.brand span{{border-bottom:3px solid var(--red);padding-bottom:7px}}.tag{{margin-top:10px;opacity:.82;font-family:Georgia,serif}}.nav{{max-width:1050px;margin:auto;padding:0 24px;border-top:1px solid rgba(255,255,255,.13);display:flex;gap:22px;overflow:auto;white-space:nowrap}}.nav a{{padding:12px 0;text-decoration:none;font-size:13px;font-weight:800;text-transform:uppercase}}
main{{max-width:850px;margin:0 auto;padding:50px 24px 70px}}.eyebrow{{color:var(--red);font-size:12px;font-weight:900;letter-spacing:.09em;text-transform:uppercase}}h1{{font:800 clamp(38px,7vw,62px)/1.03 Georgia,serif;letter-spacing:-.025em;margin:10px 0 12px}}.updated{{color:var(--muted);font-size:14px;border-bottom:1px solid var(--line);padding-bottom:22px;margin-bottom:26px}}.intro{{font:20px/1.55 Georgia,serif;color:#344054;margin-bottom:38px}}.legal-section{{padding:2px 0 20px;border-bottom:1px solid var(--line)}}.legal-section:last-of-type{{border-bottom:0}}.legal-section h2{{font:700 25px/1.2 Georgia,serif;margin:28px 0 10px}}.legal-section p{{margin:10px 0;color:#344054}}.contact{{margin-top:34px;background:var(--soft);border-left:4px solid var(--red);padding:17px 19px}}footer{{background:var(--navy);color:#d0d5dd;padding:22px 24px;text-align:center;font-size:13px}}footer .legal-links{{display:flex;justify-content:center;gap:9px;margin-top:7px}}footer a{{color:#fff}}
@media(max-width:650px){{.mast{{align-items:flex-start}}.tag{{display:none}}main{{padding-top:36px}}}}
</style>
</head>
<body>
<header class="top"><div class="mast"><div><div class="brand"><span>VÂLCEA CLAR</span></div><div class="tag">Știrile Vâlcii, fără zgomot.</div></div><div style="font-size:13px;opacity:.8">valceaclar.ro</div></div><nav class="nav"><a href="/">Acasă</a><a href="/#stiri">Știri locale</a><a href="/#investigatii">Investigații</a><a href="/unde-iesim/">Unde ieșim</a></nav></header>
<main>
<div class="eyebrow">Document public</div>
<h1>{esc(page['title'])}</h1>
<div class="updated">În vigoare din {esc(doc['effective_date'])} · VÂLCEA CLAR / valceaclar.ro</div>
<p class="intro">{esc(page['intro'])}</p>
{''.join(sections)}
<div class="contact"><strong>Contact</strong><br><a href="mailto:{esc(doc['contact_email'])}">{esc(doc['contact_email'])}</a></div>
</main>
<footer><div>VÂLCEA CLAR · informație locală verificată</div><div class="legal-links">{LEGAL_LINKS}</div></footer>
</body>
</html>'''


def build() -> dict[str, Any]:
    doc = load_source()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    outputs = []
    for slug in EXPECTED:
        target = RUNTIME / slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(doc, slug), encoding="utf-8")
        outputs.append(str(target.relative_to(ROOT)))
    validate_generated(doc)
    return {"status": "PASS", "pages": outputs, "remote_mutation": False}


def legal_routes() -> list[dict[str, Any]]:
    return [
        {
            "path": "/termeni/",
            "source": "termeni/index.html",
            "title": "Termeni și condiții — VÂLCEA CLAR",
            "update_mode": "replace_legal_page",
            "publication_unit": "legal_page",
            "canonical_url": "https://valceaclar.ro/termeni/",
        },
        {
            "path": "/confidentialitate/",
            "source": "confidentialitate/index.html",
            "title": "Politica de confidențialitate — VÂLCEA CLAR",
            "update_mode": "replace_legal_page",
            "publication_unit": "legal_page",
            "canonical_url": "https://valceaclar.ro/confidentialitate/",
        },
    ]


def export() -> dict[str, Any]:
    report = build()
    DIST.mkdir(parents=True, exist_ok=True)
    for slug in EXPECTED:
        source = RUNTIME / slug / "index.html"
        target = DIST / slug / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    route_report = {"manifest_updated": False, "legal_routes": 2}
    if MANIFEST.is_file():
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        routes = [route for route in manifest.get("routes", []) if route.get("path") not in set(EXPECTED.values())]
        insert_at = 1 if routes and routes[0].get("path") == "/" else 0
        routes[insert_at:insert_at] = legal_routes()
        manifest["routes"] = routes
        manifest["schema_version"] = "1.6"
        manifest.setdefault("target", {})["public_legal_pages"] = True
        manifest.setdefault("counts", {})["routes"] = len(routes)
        manifest["counts"]["legal_routes"] = 2
        manifest["legal_pages"] = {
            "source": "site/legal/legal_pages.json",
            "effective_date": "2026-08-16",
            "contact": "redactie@valceaclar.ro",
            "routes": list(EXPECTED.values()),
        }
        files = []
        for path in sorted(p for p in DIST.rglob("*") if p.is_file() and p != MANIFEST):
            files.append({
                "path": path.relative_to(DIST).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            })
        manifest["files"] = files
        MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        route_report["manifest_updated"] = True
        route_report["routes"] = len(routes)
        route_report["files"] = len(files)
    validate_exported()
    return {**report, **route_report, "exported": True}


def validate_generated(doc: dict[str, Any] | None = None) -> None:
    doc = doc or load_source()
    for slug, route in EXPECTED.items():
        path = RUNTIME / slug / "index.html"
        if not path.is_file():
            raise ValueError(f"missing generated legal page: {path}")
        text = path.read_text(encoding="utf-8")
        required = [
            f"https://valceaclar.ro{route}",
            str(doc["pages"][slug]["title"]),
            "redactie@valceaclar.ro",
            "/termeni/",
            "/confidentialitate/",
            'name="robots" content="index,follow"',
        ]
        missing = [value for value in required if value not in text]
        if missing:
            raise ValueError(f"generated legal page {slug} missing required contract: {missing}")
        forbidden = ["CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "github-actions-secret:"]
        leaked = [value for value in forbidden if value in text]
        if leaked:
            raise ValueError(f"generated legal page {slug} leaks secret marker: {leaked}")


def validate_exported() -> None:
    doc = load_source()
    for slug in EXPECTED:
        runtime = RUNTIME / slug / "index.html"
        exported = DIST / slug / "index.html"
        if not exported.is_file():
            raise ValueError(f"missing exported legal page: {exported}")
        if exported.read_bytes() != runtime.read_bytes():
            raise ValueError(f"exported legal page differs from runtime source: {slug}")
        if doc["pages"][slug]["title"] not in exported.read_text(encoding="utf-8"):
            raise ValueError(f"exported legal title missing: {slug}")


def self_test() -> int:
    doc = load_source()
    for slug in EXPECTED:
        text = render(doc, slug)
        assert f"https://valceaclar.ro{EXPECTED[slug]}" in text
        assert doc["contact_email"] in text
        assert "CLIENT_SECRET" not in text
    assert [row["path"] for row in legal_routes()] == ["/termeni/", "/confidentialitate/"]
    print("VÂLCEA CLAR legal pages self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--export", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.check:
        validate_generated()
        print("VÂLCEA CLAR legal pages validation: PASS")
        return 0
    result = export() if args.export else build()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
