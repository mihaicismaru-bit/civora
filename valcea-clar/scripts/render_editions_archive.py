#!/usr/bin/env python3
"""Render the public VÂLCEA CLAR editions archive.

Edition JSON files remain compatibility recap snapshots; individual stories are
still the canonical publication unit. This renderer exposes only recap
snapshots that were explicitly publishable and only reader-facing items that
still pass the public UX projection. Legacy duplicate files, held stories and
operational records are never projected into the archive.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import public_ux_reset as ux

ROOT = Path(__file__).resolve().parents[1]
EDITIONS = ROOT / "editions"
POINTER = ROOT / "site" / "current_edition.json"
NAVIGATION = ROOT / "site" / "navigation.json"
RUNTIME = ROOT / "site" / "runtime"
ARCHIVE_ROOT = RUNTIME / "editii"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
MANIFEST = ARCHIVE_ROOT / "manifest.json"
PUBLISHABLE = {"auto_approved", "editor_approved"}
EDITION_ID = re.compile(r"^\d{4}-\d{2}-\d{2}-(morning|evening)$")
MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return default
        raise FileNotFoundError(path)
    return json.loads(path.read_text(encoding="utf-8"))


def edition_route(edition_id: str) -> str:
    return f"/editii/{edition_id}/"


def slot_label(slot: object) -> str:
    return "dimineață" if str(slot) == "morning" else "seară"


def display_date(value: object) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d")
    except ValueError:
        return text
    return f"{parsed.day} {MONTHS[parsed.month - 1]} {parsed.year}"


def edition_sort_key(doc: dict[str, Any]) -> tuple[float, str]:
    raw = str(doc.get("updated_local") or "").strip()
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        date = str(doc.get("edition_date") or "")
        slot_rank = "2" if doc.get("slot") == "evening" else "1"
        raw_fallback = f"{date}T{slot_rank}"
        return (0.0, raw_fallback)
    return (stamp, str(doc.get("edition_id") or ""))


def canonical_story_routes() -> dict[str, str]:
    doc = load_json(STORY_MANIFEST, {"stories": []})
    return {
        str(row.get("id")): str(row.get("path"))
        for row in doc.get("stories") or []
        if isinstance(row, dict) and row.get("id") and str(row.get("path") or "").startswith("/stiri/")
    }


def public_edition(
    doc: dict[str, Any],
    *,
    filename_stem: str,
    held: set[str],
) -> dict[str, Any] | None:
    """Return the sanitized reader-facing edition or None when it is not public."""
    if "legacy" in filename_stem.lower():
        return None
    edition_id = str(doc.get("edition_id") or "").strip()
    if not EDITION_ID.fullmatch(edition_id) or edition_id != filename_stem:
        return None
    if doc.get("status") not in PUBLISHABLE or doc.get("publication_intent") != "publish":
        return None

    items = [
        dict(item)
        for item in doc.get("items") or []
        if isinstance(item, dict) and ux.is_news(item, held)
    ]
    if not items:
        return None

    return {
        "edition_id": edition_id,
        "slot": doc.get("slot"),
        "title": doc.get("title") or "VÂLCEA CLAR",
        "edition_date": doc.get("edition_date") or edition_id[:10],
        "updated_local": doc.get("updated_local"),
        "status": doc.get("status"),
        "publication_intent": doc.get("publication_intent"),
        "items": items,
        "item_count": len(items),
        "route": edition_route(edition_id),
    }


def collect_public_editions() -> list[dict[str, Any]]:
    held = ux.held_ids()
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(EDITIONS.glob("*.json")):
        try:
            raw = load_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(raw, dict):
            continue
        row = public_edition(raw, filename_stem=path.stem, held=held)
        if row is not None:
            rows[str(row["edition_id"])] = row
    result = list(rows.values())
    result.sort(key=edition_sort_key, reverse=True)
    return result


def current_edition_id() -> str | None:
    pointer = load_json(POINTER, {})
    if not isinstance(pointer, dict):
        return None
    if pointer.get("status") not in PUBLISHABLE or pointer.get("publication_intent") != "publish":
        return None
    edition_id = str(pointer.get("edition_id") or "")
    return edition_id if EDITION_ID.fullmatch(edition_id) else None


def edition_row(doc: dict[str, Any], *, current: bool) -> str:
    badge = '<span class="archive-label">CURENTĂ</span>' if current else ""
    slot = slot_label(doc.get("slot"))
    date = display_date(doc.get("edition_date"))
    count = int(doc.get("item_count") or 0)
    noun = "material" if count == 1 else "materiale"
    return (
        '<article class="list-row">'
        f'<div><div class="kicker">EDIȚIA DE {ux.esc(slot.upper())}{badge}</div>'
        f'<div class="story-date">{ux.esc(date)}</div></div>'
        f'<div><h2><a href="{ux.esc(doc.get("route"))}">{ux.esc(doc.get("title"))}</a></h2>'
        f'<p>{count} {noun} publice în această ediție.</p></div>'
        '</article>'
    )


def render_index(nav: dict[str, Any], editions: list[dict[str, Any]], current_id: str | None) -> str:
    current = [row for row in editions if row.get("edition_id") == current_id]
    previous = [row for row in editions if row.get("edition_id") != current_id]
    current_html = "".join(edition_row(row, current=True) for row in current)
    previous_html = "".join(edition_row(row, current=False) for row in previous)
    if not previous_html:
        previous_html = '<p class="empty">Nu există încă ediții anterioare publicabile.</p>'

    current_block = (
        '<section class="section"><div class="section-head"><h2>Ediția curentă</h2></div>'
        f'<div class="all-list">{current_html}</div></section>'
        if current_html
        else ""
    )
    body = (
        '<main><div class="kicker">ARHIVA VÂLCEA CLAR</div>'
        '<h1 class="index-title">Ediții anterioare</h1>'
        '<p class="index-dek">Recapitulările editoriale publicate de VÂLCEA CLAR, păstrate pe URL-uri stabile. '
        'Știrile individuale rămân unitatea canonică de publicare.</p>'
        '<div class="note">Arhiva afișează numai ediții publicabile și materiale reader-facing. '
        'Fișierele legacy, materialele aflate în hold și înregistrările operaționale nu sunt expuse.</div>'
        f'{current_block}'
        '<section class="section"><div class="section-head"><h2>Arhivă</h2></div>'
        f'<div class="all-list">{previous_html}</div></section></main>'
    )
    return ux.shell(
        nav,
        title="Ediții anterioare — VÂLCEA CLAR",
        description="Arhiva edițiilor publicate de VÂLCEA CLAR.",
        canonical=ux.BASE + "/editii/",
        body=body,
    )


def item_block(item: dict[str, Any], story_routes: dict[str, str]) -> str:
    story_id = str(item.get("id") or "")
    path = story_routes.get(story_id)
    canonical = (
        f'<p><a class="back" href="{ux.esc(path)}">Deschide materialul canonic →</a></p>'
        if path
        else ""
    )
    paragraphs = "".join(
        f'<p>{ux.esc(text)}</p>'
        for text in (item.get("paragraphs") or [])[:2]
        if str(text).strip()
    )
    sources = ux.source_links(item, True)
    source_block = (
        f'<section class="article-sources"><h2>Surse</h2><ul>{sources}</ul></section>'
        if sources
        else ""
    )
    return (
        '<article class="article" style="padding:26px 0;border-bottom:1px solid var(--line)">'
        f'<div class="kicker">{ux.esc(str(item.get("section") or "ȘTIRI").replace("_", " "))}</div>'
        f'<h2 style="font:700 34px/1.12 Georgia,serif;margin:7px 0 10px">{ux.esc(item.get("headline"))}</h2>'
        f'<p class="dek">{ux.esc(item.get("dek"))}</p>'
        f'<div class="article-body">{paragraphs}</div>{source_block}{canonical}</article>'
    )


def render_detail(
    nav: dict[str, Any],
    edition: dict[str, Any],
    story_routes: dict[str, str],
    *,
    current: bool,
) -> str:
    slot = slot_label(edition.get("slot"))
    date = display_date(edition.get("edition_date"))
    badge = " · ediția curentă" if current else ""
    articles = "".join(item_block(item, story_routes) for item in edition.get("items") or [])
    body = (
        '<main><div class="kicker">ARHIVA EDIȚIILOR</div>'
        f'<h1 class="index-title">Ediția de {ux.esc(slot)} · {ux.esc(date)}</h1>'
        f'<p class="index-dek">Snapshot editorial publicat {ux.esc(str(edition.get("updated_local") or ""))}{ux.esc(badge)}. '
        'Pentru actualizări ulterioare, materialul individual canonic are prioritate.</p>'
        '<p><a class="back" href="/editii/">← Toate edițiile</a></p>'
        f'{articles}</main>'
    )
    return ux.shell(
        nav,
        title=f"Ediția de {slot} · {date} — VÂLCEA CLAR",
        description=f"Ediția VÂLCEA CLAR de {slot} din {date}.",
        canonical=ux.BASE + str(edition.get("route")),
        body=body,
    )


def clean_stale_routes(public_ids: set[str]) -> None:
    if not ARCHIVE_ROOT.is_dir():
        return
    for child in ARCHIVE_ROOT.iterdir():
        if child.is_dir() and child.name not in public_ids:
            shutil.rmtree(child)


def build() -> dict[str, Any]:
    nav = load_json(NAVIGATION)
    if not isinstance(nav, dict):
        raise SystemExit("Edition archive requires a navigation object")
    editions = collect_public_editions()
    if not editions:
        raise SystemExit("Refusing edition archive render: no publishable reader-facing editions")

    current_id = current_edition_id()
    story_routes = canonical_story_routes()
    public_ids = {str(row["edition_id"]) for row in editions}
    ARCHIVE_ROOT.mkdir(parents=True, exist_ok=True)
    clean_stale_routes(public_ids)

    (ARCHIVE_ROOT / "index.html").write_text(
        render_index(nav, editions, current_id),
        encoding="utf-8",
    )

    routes = ["/editii/"]
    manifest_rows = []
    for edition in editions:
        edition_id = str(edition["edition_id"])
        target = ARCHIVE_ROOT / edition_id / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            render_detail(
                nav,
                edition,
                story_routes,
                current=edition_id == current_id,
            ),
            encoding="utf-8",
        )
        route = str(edition["route"])
        routes.append(route)
        manifest_rows.append({
            "edition_id": edition_id,
            "route": route,
            "edition_date": edition.get("edition_date"),
            "slot": edition.get("slot"),
            "item_count": edition.get("item_count"),
            "current": edition_id == current_id,
        })

    manifest = {
        "schema_version": "1.0",
        "contract_id": "valcea-clar-editions-archive-v1",
        "publication_model": "continuous_story_first",
        "edition_is_canonical_story_url": False,
        "legacy_files_public": False,
        "held_or_operational_items_public": False,
        "current_edition_id": current_id,
        "edition_count": len(editions),
        "routes": routes,
        "editions": manifest_rows,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    required_nav = [
        (str(item.get("label")), str(item.get("href")))
        for item in nav.get("items") or []
    ]
    for route in routes:
        page = RUNTIME / route.strip("/") / "index.html"
        text = page.read_text(encoding="utf-8")
        if f'data-nav-contract="{nav.get("contract_id")}"' not in text:
            raise SystemExit(f"Edition archive navigation contract missing: {route}")
        for label, href in required_nav:
            if f'<a href="{ux.esc(href)}">{ux.esc(label)}</a>' not in text:
                raise SystemExit(f"Edition archive navigation drift at {route}: {label}")

    return {
        "status": "PASS",
        "edition_count": len(editions),
        "current_edition_id": current_id,
        "routes": routes,
        "manifest": "site/runtime/editii/manifest.json",
    }


def self_test() -> int:
    safe = {
        "edition_id": "2026-08-26-morning",
        "slot": "morning",
        "title": "VÂLCEA CLAR — Ediția de dimineață",
        "edition_date": "2026-08-26",
        "updated_local": "2026-08-26T08:00:00+03:00",
        "status": "auto_approved",
        "publication_intent": "publish",
        "items": [{
            "id": "safe-story",
            "section": "SERVICII",
            "headline": "Material verificat",
            "dek": "Context verificat.",
            "paragraphs": ["Paragraf verificat."],
            "sources": [{"name": "Sursă", "url": "https://example.invalid/source"}],
        }],
    }
    row = public_edition(safe, filename_stem="2026-08-26-morning", held=set())
    assert row is not None and row["item_count"] == 1
    assert public_edition(safe, filename_stem="2026-08-26-morning-legacy", held=set()) is None
    assert public_edition({**safe, "publication_intent": "hold"}, filename_stem="2026-08-26-morning", held=set()) is None
    held_row = public_edition(safe, filename_stem="2026-08-26-morning", held={"safe-story"})
    assert held_row is None
    nav = {
        "contract_id": "valcea-clar-primary-v2",
        "brand": "VÂLCEA CLAR",
        "tagline": "Știrile Vâlcii, fără zgomot.",
        "items": [{"label": "Ediții anterioare", "href": "/editii/"}],
        "footer": {"line": "VÂLCEA CLAR", "links": []},
    }
    index = render_index(nav, [row], None)
    assert "Ediții anterioare" in index and "/editii/2026-08-26-morning/" in index
    detail = render_detail(nav, row, {"safe-story": "/stiri/safe-story/"}, current=False)
    assert "Material verificat" in detail and "/stiri/safe-story/" in detail
    print("VÂLCEA CLAR editions archive self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    print(json.dumps(build(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
