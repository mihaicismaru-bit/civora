#!/usr/bin/env python3
"""Static smoke checks for the Unde ieșim projection and continuous story runtime."""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RUNTIME = ROOT / "site" / "runtime"
ARCHIVE = ROOT / "site" / "story_archive.json"


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
assert not {"restaurant-bulevard", "sempre-buono-ramnicu-valcea"} & {p["id"] for p in places}
assert meta["place_count"] == len(places)
assert meta["candidate_count"] >= 1
assert "fetch('data/places.json')" in (WEB / "app.js").read_text(encoding="utf-8")

# The public story set is the durable continuous archive. The current edition is
# recap/compatibility metadata and may legitimately contain fewer active items.
if ARCHIVE.is_file():
    story_source = json.loads(ARCHIVE.read_text(encoding="utf-8"))
    assert story_source.get("publication_model") == "continuous_story_first"
    assert story_source.get("recap_editions_may_delete_published_stories") is False
    items_by_id = {
        str(item.get("id")): item
        for item in story_source.get("stories", [])
        if isinstance(item, dict) and item.get("id")
    }
else:
    pointer = json.loads((ROOT / "site" / "current_edition.json").read_text(encoding="utf-8"))
    edition = json.loads((ROOT / pointer["json_source"]).read_text(encoding="utf-8"))
    items_by_id = {str(item.get("id")): item for item in edition.get("items", []) if item.get("id")}

manifest_path = RUNTIME / "stiri" / "manifest.json"
assert manifest_path.is_file(), "Lipsește manifestul rutelor de știri"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
assert manifest.get("publication_model") == "continuous_story_first"
rows = manifest.get("stories") or []

# Older manifests advertised cross-linking/structured-data policy as metadata;
# the continuous archive validates the actual behavior below. If policy blocks
# are present, they must remain truthful.
cross = manifest.get("cross_linking") or {}
if cross:
    assert cross.get("enabled") is True, "Cross-linking intern dezactivat"
    assert cross.get("eligible_scope") == "publishable_full_story_only"
structured = manifest.get("structured_data") or {}
if structured:
    assert structured.get("enabled") is True, "NewsArticle structured data dezactivat"
    assert structured.get("type") == "NewsArticle"
    assert structured.get("eligible_scope") == "publishable_full_story_only"
    assert structured.get("date_published_policy") == "stable_publication_ledger_only"
    assert structured.get("verified_image_policy") == "provenance_backed_real_photograph_only"
    assert structured.get("unverified_image_policy") == "omit"

routes_by_id = {str(row.get("id")): str(row.get("path")) for row in rows if row.get("id") and row.get("path")}
known_routes = set(routes_by_id.values())
assert set(routes_by_id) == set(items_by_id), "Manifestul public nu este aliniat cu arhiva continuă"
verified_images = 0
cross_links_seen = 0
for row in rows:
    story_id = str(row.get("id") or "")
    route = str(row.get("path") or "")
    canonical = str(row.get("canonical") or "")
    published_at = str(row.get("published_at") or "")
    assert story_id in items_by_id, f"Pagină fără material editorial public: {story_id}"
    item = items_by_id[story_id]
    assert route in known_routes and route.startswith("/stiri/") and route.endswith("/")
    assert canonical == f"https://valceaclar.ro{route}"
    assert published_at, f"Lipsește ledger-ul datePublished pentru {story_id}"
    target = RUNTIME / route.strip("/") / "index.html"
    assert target.is_file(), f"Pagina canonică lipsește: {route}"
    text = target.read_text(encoding="utf-8")

    jsonld_matches = re.findall(r'<script type="application/ld\+json">(.*?)</script>', text, flags=re.S)
    assert len(jsonld_matches) == 1, f"NewsArticle JSON-LD invalid ca număr pentru {story_id}"
    news = json.loads(jsonld_matches[0])
    assert news.get("@context") == "https://schema.org"
    assert news.get("@type") == "NewsArticle"
    assert news.get("headline") == item.get("headline")
    assert news.get("description") == item.get("dek")
    assert news.get("articleSection") == str(item.get("section") or "ȘTIRI").replace("_", " ")
    assert news.get("url") == canonical
    assert (news.get("mainEntityOfPage") or {}).get("@id") == canonical
    assert news.get("datePublished") == published_at
    assert f"Publicat {published_at}" in text, f"Data publicării nu este vizibilă pentru {story_id}"
    assert news.get("inLanguage") == "ro-RO"
    assert (news.get("publisher") or {}).get("name") == "VÂLCEA CLAR"
    assert (news.get("publisher") or {}).get("url") == "https://valceaclar.ro/"
    assert (news.get("author") or {}).get("name") == "VÂLCEA CLAR"

    image = row.get("image")
    if image:
        verified_images += 1
        public_url = str(image.get("public_url") or "")
        source_url = str(image.get("source_url") or "")
        assert image.get("synthetic") is False, f"Imagine sintetică admisă pentru {story_id}"
        assert image.get("provenance_status") == "VERIFIED", f"Provenance neverificată pentru {story_id}"
        assert public_url.startswith("https://valceaclar.ro/media/social/")
        assert source_url.startswith("https://")
        assert image.get("credit") and image.get("rights_basis")
        if image.get("contextual_archive") is True:
            assert image.get("captured_at"), f"Foto de arhivă fără captured_at pentru {story_id}"
        filename = Path(urlparse(public_url).path).name
        assert filename and (RUNTIME / "media" / "social" / filename).is_file(), f"Asset foto lipsă pentru {story_id}"
        assert news.get("image") == [public_url], f"NewsArticle image nealiniată pentru {story_id}"
        assert f'<meta property="og:image" content="{public_url}">' in text
        assert 'data-photo-provenance="verified"' in text
        assert f'src="{urlparse(public_url).path}"' in text
        assert source_url in text and "Foto:" in text, f"Credit foto nevizibil pentru {story_id}"
    else:
        assert "image" not in news, f"Imagine fără provenance introdusă în JSON-LD pentru {story_id}"
        assert '<meta property="og:image"' not in text, f"OG image fără provenance pentru {story_id}"
        assert 'data-photo-provenance="verified"' not in text

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
        cross_links_seen += len(links)
    else:
        assert not match, f"Bloc related neașteptat pentru {story_id}"

assert rows, "Arhiva continuă nu are pagini canonice"
assert cross_links_seen >= 1 if len(rows) > 1 else True, "Cross-linking intern nu funcționează pe arhiva multi-story"
print(
    f"Web smoke: PASS ({len(places)} localuri publice; candidații sunt ascunși; "
    f"{len(rows)} pagini canonice persistente cu NewsArticle JSON-LD; "
    f"{cross_links_seen} cross-link-uri; {verified_images} fotografii reale cu provenance verificată)"
)
