#!/usr/bin/env python3
"""Static smoke checks for the Unde ieșim public projection and story runtime."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNTIME = ROOT / "site" / "runtime"


class Parser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.scripts: list[str] = []
        self.styles: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            if values["id"] in self.ids:
                raise AssertionError(f"ID HTML duplicat: {values['id']}")
            self.ids.add(values["id"])
        if tag == "script" and values.get("src"):
            self.scripts.append(values["src"])
        if tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.styles.append(values["href"])


html = (WEB / "index.html").read_text(encoding="utf-8")
parser = Parser()
parser.feed(html)
for required in {"main", "place-grid", "place-dialog", "search", "creator-grid"}:
    assert required in parser.ids, f"Lipsește elementul #{required}"
for asset in parser.scripts + parser.styles:
    assert (WEB / asset).is_file(), f"Asset lipsă: {asset}"

places = json.loads((WEB / "data" / "places.json").read_text(encoding="utf-8"))["places"]
meta = json.loads((WEB / "data" / "meta.json").read_text(encoding="utf-8"))
assert places, "Proiecția publică nu are localuri"
assert all(p["publication_status"] == "public" for p in places)
assert not {"restaurant-bulevard", "sempre-buono-ramnicu-valcea", "queens-pub"} & {p["id"] for p in places}
assert meta["place_count"] == len(places)
assert meta["candidate_count"] >= 1
assert "fetch('data/places.json')" in (WEB / "app.js").read_text(encoding="utf-8")

manifest_path = RUNTIME / "stiri" / "manifest.json"
assert manifest_path.is_file(), "Lipsește manifestul rutelor de știri"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
rows = manifest.get("stories") or []
cross = manifest.get("cross_linking") or {}
assert cross.get("enabled") is True, "Cross-linking intern dezactivat"
assert cross.get("eligible_scope") == "publishable_full_story_only"
routes_by_id = {str(row.get("id")): str(row.get("path")) for row in rows if row.get("id") and row.get("path")}
known_routes = set(routes_by_id.values())
for row in rows:
    story_id = str(row.get("id") or "")
    route = str(row.get("path") or "")
    assert route in known_routes and route.startswith("/stiri/") and route.endswith("/")
    target = RUNTIME / route.strip("/") / "index.html"
    assert target.is_file(), f"Pagina canonică lipsește: {route}"
    text = target.read_text(encoding="utf-8")
    expected_ids = [str(value) for value in row.get("related_story_ids") or []]
    expected_routes = [routes_by_id[value] for value in expected_ids]
    assert story_id not in expected_ids, f"Self-link detectat pentru {story_id}"
    match = re.search(
        r'<section class="related" data-crosslink-scope="publishable_full_story_only">(.*?)</section>',
        text,
        flags=re.S,
    )
    if expected_routes:
        assert match, f"Blocul Mai citește lipsește pentru {story_id}"
        links = re.findall(r'<a href="(/stiri/[^"]+/)">', match.group(1))
        assert links == expected_routes, f"Cross-link-uri nealiniate pentru {story_id}: {links} != {expected_routes}"
        assert all(link in known_routes for link in links), f"Cross-link către rută necunoscută în {story_id}"
    else:
        assert not match, f"Bloc related neașteptat pentru {story_id}"

print(
    f"Web smoke: PASS ({len(places)} localuri publice; candidații sunt ascunși; "
    f"{len(rows)} pagini de știri cross-linkate fail-closed)"
)
