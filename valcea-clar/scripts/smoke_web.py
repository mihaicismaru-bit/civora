#!/usr/bin/env python3
"""Static smoke checks for the Unde ieșim public projection."""
from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


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
print(f"Web smoke: PASS ({len(places)} localuri publice; candidații sunt ascunși)")
