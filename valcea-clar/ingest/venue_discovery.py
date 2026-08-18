#!/usr/bin/env python3
"""Zero-cost dynamic discovery for VÂLCEA CLAR — UNDE IEȘIM.

The static curated registry remains the durable editorial baseline. This module
adds an *ephemeral* overlay before every venue-ingest run:

1. discover hospitality/leisure entities from OpenStreetMap/Overpass;
2. treat OSM only as a discovery hint, never as publication evidence;
3. follow an OSM-provided website candidate;
4. require the candidate website itself to confirm the venue name and locality;
5. require the official page to confirm the street before granting
   ``VERIFIED_OFFICIAL + DRAFT_ELIGIBLE``;
6. keep weaker matches in ``DRAFT_REVIEW_REQUIRED``;
7. persist only the discovered overlay/frontier state, not mutations to the
   static source registry or seed catalogue.

The existing promotion gate still decides publication and re-probes every
source in the same production run. Discovery therefore cannot bypass identity,
source-health, semantic-change, address-collision, or operator/ownership gates.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import ssl
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "valcea-clar"
INGEST = BASE / "ingest"
STATE = INGEST / "state"
SEED_PATH = INGEST / "seed_catalog.json"
REGISTRY_PATH = INGEST / "source_registry.json"
CANONICAL_PATH = BASE / "data" / "places.json"
DISCOVERY_STATE = STATE / "venue_discovery_state.json"
DISCOVERED_VENUES = STATE / "discovered_venues.json"
DISCOVERED_SOURCES = STATE / "discovered_sources.json"
FRONTIER_PATH = STATE / "venue_discovery_frontier.json"
RECEIPT_PATH = BASE / "ops" / "venue_discovery_receipt.json"

OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)
OVERPASS_QUERY = """[out:json][timeout:25];
area[\"name\"=\"Râmnicu Vâlcea\"][\"boundary\"=\"administrative\"]->.searchArea;
(
  nwr[\"amenity\"~\"^(restaurant|cafe|fast_food|bar|pub|ice_cream|nightclub|cinema|theatre)$\"](area.searchArea);
  nwr[\"leisure\"~\"^(spa|fitness_centre|swimming_pool|bowling_alley|water_park|amusement_arcade)$\"](area.searchArea);
);
out center tags;"""

GENERIC_NAME_TOKENS = {
    "restaurant", "ristorante", "restaurante", "cafe", "coffee", "bar", "pub",
    "terasa", "bistro", "grill", "food", "fast", "club", "the", "and", "la",
}
GENERIC_STREET_TOKENS = {
    "strada", "str", "calea", "bulevard", "bulevardul", "bd", "nr", "numarul",
    "general", "loc", "ramnicu", "valcea",
}


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        parts = sorted(path.parent.glob(path.name + ".part-*"))
        if parts:
            return json.loads("".join(part.read_text(encoding="utf-8") for part in parts))
        if default is not None:
            return default
        raise


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(value: object | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def slugify(value: object | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", normalize(value)).strip("-")
    return slug[:72] or "venue"


def stable_id(name: str, website: str) -> str:
    host = urllib.parse.urlparse(website).netloc.lower().removeprefix("www.")
    digest = hashlib.sha256(host.encode("utf-8")).hexdigest()[:8]
    return f"auto-{slugify(name)}-{digest}"


def website_candidate(tags: dict[str, Any]) -> str | None:
    raw = tags.get("website") or tags.get("contact:website") or tags.get("url")
    if not raw:
        return None
    value = str(raw).strip()
    if not re.match(r"^https?://", value, re.I):
        value = "https://" + value.lstrip("/")
    parsed = urllib.parse.urlparse(value)
    if not parsed.hostname:
        return None
    scheme = "https"
    path = parsed.path or "/"
    rebuilt = urllib.parse.urlunparse((scheme, parsed.netloc, path, "", parsed.query, ""))
    return rebuilt


def address_from_tags(tags: dict[str, Any]) -> dict[str, Any]:
    street = tags.get("addr:street") or tags.get("addr:place")
    number = tags.get("addr:housenumber")
    city = tags.get("addr:city") or "Râmnicu Vâlcea"
    parts = []
    if street:
        parts.append(str(street))
    if number:
        parts.append(f"nr. {number}")
    display = ", ".join(parts)
    if display:
        display += f", {city}"
    return {
        "display": display or None,
        "street": str(street) if street else None,
        "housenumber": str(number) if number else None,
        "city": str(city),
    }


def category_for(tags: dict[str, Any]) -> list[str]:
    amenity = str(tags.get("amenity") or "").lower()
    leisure = str(tags.get("leisure") or "").lower()
    mapping = {
        "restaurant": ["RESTAURANT"],
        "cafe": ["CAFE", "COFFEE"],
        "fast_food": ["FAST_CASUAL"],
        "bar": ["PUB"],
        "pub": ["PUB", "RESTAURANT"],
        "ice_cream": ["CAFE", "DESSERT"],
        "nightclub": ["LEISURE", "NIGHTLIFE"],
        "cinema": ["LEISURE", "CINEMA"],
        "theatre": ["LEISURE", "THEATRE"],
    }
    if amenity in mapping:
        return mapping[amenity]
    if leisure:
        return ["LEISURE", leisure.upper()]
    return ["LEISURE"]


class PageExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.text: list[str] = []
        self.links: list[str] = []
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self.suppressed += 1
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if self.suppressed:
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if cleaned:
            self.text.append(cleaned)


def fetch_page(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ValceaClar-UndeIesimDiscovery/1.0 (+editorial source discovery)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.4",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.4",
        },
    )
    with urllib.request.urlopen(request, timeout=timeout, context=ssl.create_default_context()) as response:
        raw = response.read(650_000)
        status = getattr(response, "status", 200)
        final_url = response.geturl()
        content_type = response.headers.get("content-type", "")
    if status >= 400:
        raise RuntimeError(f"HTTP status {status}")
    text = raw.decode("utf-8", "replace")
    extractor = PageExtractor()
    extractor.feed(text)
    visible = re.sub(r"\s+", " ", " ".join(extractor.text)).strip()
    return {
        "url": final_url,
        "content_type": content_type,
        "text": visible,
        "links": extractor.links,
        "status": status,
    }


def same_host_links(base_url: str, links: list[str]) -> list[str]:
    host = urllib.parse.urlparse(base_url).netloc.lower().removeprefix("www.")
    ranked: list[tuple[int, str]] = []
    for href in links:
        absolute = urllib.parse.urljoin(base_url, href)
        parsed = urllib.parse.urlparse(absolute)
        if parsed.scheme not in {"http", "https"}:
            continue
        other = parsed.netloc.lower().removeprefix("www.")
        if other != host:
            continue
        path = normalize(parsed.path)
        score = 0
        for token, weight in (
            ("contact", 10), ("contacte", 10), ("locatie", 9), ("location", 9),
            ("despre", 6), ("about", 6), ("restaurant", 4), ("meniu", 3), ("menu", 3),
        ):
            if token in path:
                score = max(score, weight)
        if score:
            clean = urllib.parse.urlunparse(("https", parsed.netloc, parsed.path or "/", "", parsed.query, ""))
            ranked.append((score, clean))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    result: list[str] = []
    for _, url in ranked:
        if url not in result:
            result.append(url)
    return result[:3]


def meaningful_tokens(value: str, generic: set[str]) -> list[str]:
    return [tok for tok in normalize(value).split() if len(tok) >= 3 and tok not in generic]


def name_matches(name: str, text: str) -> bool:
    haystack = f" {normalize(text)} "
    tokens = meaningful_tokens(name, GENERIC_NAME_TOKENS)
    if not tokens:
        candidate = normalize(name)
        return bool(candidate and f" {candidate} " in haystack)
    required = 1 if len(tokens) == 1 else min(2, len(tokens))
    return sum(f" {token} " in haystack for token in tokens) >= required


def locality_matches(text: str) -> bool:
    normalized = normalize(text)
    return "ramnicu valcea" in normalized or "rm valcea" in normalized


def street_matches(address: dict[str, Any], text: str) -> bool:
    street = str(address.get("street") or "")
    if not street:
        return False
    haystack = f" {normalize(text)} "
    tokens = meaningful_tokens(street, GENERIC_STREET_TOKENS)
    if not tokens:
        return False
    distinctive = sum(f" {token} " in haystack for token in tokens)
    if distinctive < 1:
        return False
    number = normalize(address.get("housenumber"))
    if number:
        return f" {number} " in haystack or re.search(rf"\b{re.escape(number)}\b", haystack) is not None
    return True


def verify_website(name: str, website: str, address: dict[str, Any], timeout: float) -> dict[str, Any]:
    observed = utcnow()
    try:
        first = fetch_page(website, timeout)
        pages = [first]
        for link in same_host_links(first["url"], first["links"]):
            try:
                pages.append(fetch_page(link, timeout))
            except Exception:
                continue
        combined = " ".join(page["text"] for page in pages)
        final_url = first["url"]
        parsed = urllib.parse.urlparse(final_url)
        https_ok = parsed.scheme.lower() == "https"
        nmatch = name_matches(name, combined)
        lmatch = locality_matches(combined)
        smatch = street_matches(address, combined)
        return {
            "observedAt": observed,
            "health": "OK",
            "website": final_url,
            "https": https_ok,
            "nameMatch": nmatch,
            "localityMatch": lmatch,
            "streetMatch": smatch,
            "pagesChecked": len(pages),
            "textLength": len(combined),
            "verifiedOfficialIdentity": bool(https_ok and nmatch and lmatch),
            "verifiedOfficialAddress": bool(https_ok and nmatch and lmatch and smatch),
        }
    except Exception as exc:
        return {
            "observedAt": observed,
            "health": "FAILED",
            "website": website,
            "error": f"{type(exc).__name__}: {exc}",
            "verifiedOfficialIdentity": False,
            "verifiedOfficialAddress": False,
        }


def query_overpass(timeout: float) -> tuple[list[dict[str, Any]], str | None, list[str]]:
    errors: list[str] = []
    body = urllib.parse.urlencode({"data": OVERPASS_QUERY}).encode("utf-8")
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            request = urllib.request.Request(
                endpoint,
                data=body,
                headers={
                    "User-Agent": "ValceaClar-UndeIesimDiscovery/1.0",
                    "Content-Type": "application/x-www-form-urlencoded; charset=utf-8",
                    "Accept": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=max(timeout, 20.0), context=ssl.create_default_context()) as response:
                payload = json.loads(response.read(4_000_000).decode("utf-8", "replace"))
            elements = payload.get("elements", [])
            if isinstance(elements, list):
                return elements, endpoint, errors
            errors.append(f"{endpoint}: invalid elements payload")
        except Exception as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    return [], None, errors


def osm_frontier(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for element in elements:
        tags = element.get("tags") or {}
        name = str(tags.get("name") or "").strip()
        website = website_candidate(tags)
        if not name:
            continue
        address = address_from_tags(tags)
        key = (normalize(name), normalize(address.get("display")))
        if key in seen:
            continue
        seen.add(key)
        osm_type = str(element.get("type") or "")
        osm_id = str(element.get("id") or "")
        rows.append({
            "discoveryId": f"osm-{osm_type}-{osm_id}",
            "name": name,
            "websiteCandidate": website,
            "address": address,
            "categories": category_for(tags),
            "osm": {
                "type": osm_type,
                "id": osm_id,
                "sourceUrl": f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_type and osm_id else None,
            },
        })
    rows.sort(key=lambda row: (row["websiteCandidate"] is None, normalize(row["name"]), row["discoveryId"]))
    return rows


def known_names(seed: dict[str, Any], canonical: dict[str, Any]) -> set[str]:
    values = {normalize(row.get("name")) for row in seed.get("venues", [])}
    values.update(normalize(row.get("name")) for row in canonical.get("places", []))
    return {value for value in values if value}


def source_from_verification(venue_id: str, name: str, verification: dict[str, Any]) -> dict[str, Any]:
    url = str(verification["website"])
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    source_id = f"AUTO-T1-{hashlib.sha256(host.encode('utf-8')).hexdigest()[:12]}"
    scopes = ["CONTACT"]
    if verification.get("verifiedOfficialAddress"):
        scopes.append("ADDRESS")
    return {
        "id": source_id,
        "name": f"{name} — site oficial descoperit automat",
        "url": url,
        "tier": "T1",
        "type": "AUTO_DISCOVERED_OFFICIAL_WEBSITE",
        "status": "ACTIVE",
        "authorityScopes": scopes,
        "discovery": {
            "venueId": venue_id,
            "method": "OSM_WEBSITE_POINTER_THEN_OFFICIAL_PAGE_CONFIRMATION",
            "osm_is_publication_evidence": False,
            "verifiedAt": verification.get("observedAt"),
        },
    }


def venue_from_verification(row: dict[str, Any], verification: dict[str, Any], source_id: str) -> dict[str, Any]:
    address = row["address"]
    address_ok = bool(verification.get("verifiedOfficialAddress") and address.get("display"))
    identity_ok = bool(verification.get("verifiedOfficialIdentity"))
    eligibility = "DRAFT_ELIGIBLE" if address_ok else "DRAFT_REVIEW_REQUIRED"
    level = "VERIFIED_OFFICIAL" if address_ok else "PARTIALLY_VERIFIED"
    venue_id = stable_id(row["name"], str(verification["website"]))
    return {
        "id": venue_id,
        "name": row["name"],
        "locality": "Râmnicu Vâlcea",
        "county": "Vâlcea",
        "address": {
            "display": address.get("display") if address_ok else None,
            "precision": "OFFICIAL_PAGE_MATCHED_OSM_DISCOVERY_ADDRESS" if address_ok else "NEEDS_OFFICIAL_ADDRESS_CONFIRMATION",
        },
        "categories": row.get("categories", ["LEISURE"]),
        "status": "ACTIVE_WEB_PRESENCE" if identity_ok else "DISCOVERY_ONLY",
        "opening": {"status": "NOT_RESEARCHED"},
        "contacts": {
            "website": verification.get("website"),
            "phones": [],
            "social": [],
        },
        "hours": {"status": "NOT_RESEARCHED"},
        "menu": {
            "status": "NOT_RESEARCHED",
            "prices": [],
            "highlights": [],
        },
        "operator": {
            "displayName": None,
            "legalName": None,
            "cui": None,
            "people": [],
            "verification": "NOT_RESEARCHED",
        },
        "publicConnections": {"status": "NOT_RESEARCHED", "items": []},
        "verification": level,
        "editorialEligibility": eligibility,
        "publicationReady": False,
        "editorialAngle": "PROFIL_LOCAL",
        "evidence": [{"sourceId": source_id, "observedAt": verification.get("observedAt")}],
        "discoveryProvenance": {
            "method": "OSM_TO_OFFICIAL_WEBSITE",
            "discoveryId": row.get("discoveryId"),
            "osmSourceUrl": (row.get("osm") or {}).get("sourceUrl"),
            "osmPublicationEvidence": False,
            "officialIdentityConfirmed": identity_ok,
            "officialAddressConfirmed": address_ok,
        },
    }


def merge_overlay(base: dict[str, Any], key: str, overlay: list[dict[str, Any]]) -> dict[str, Any]:
    result = json.loads(json.dumps(base, ensure_ascii=False))
    rows = list(result.get(key, []))
    by_id = {str(row.get("id")): row for row in rows if row.get("id")}
    for row in overlay:
        rid = str(row.get("id") or "")
        if not rid:
            continue
        by_id[rid] = row
    result[key] = list(by_id.values())
    return result


def rotate(rows: list[dict[str, Any]], cursor: int, limit: int) -> tuple[list[dict[str, Any]], int]:
    eligible = [row for row in rows if row.get("websiteCandidate")]
    if not eligible or limit <= 0:
        return [], 0
    cursor %= len(eligible)
    count = min(limit, len(eligible))
    selected = [eligible[(cursor + offset) % len(eligible)] for offset in range(count)]
    return selected, (cursor + count) % len(eligible)


def run_discovery(timeout: float, max_websites: int, no_network: bool = False) -> dict[str, Any]:
    observed = utcnow()
    static_seed = load_json(SEED_PATH)
    static_registry = load_json(REGISTRY_PATH)
    canonical = load_json(CANONICAL_PATH, {"places": []})
    previous_state = load_json(DISCOVERY_STATE, {"cursor": 0})
    previous_venues_doc = load_json(DISCOVERED_VENUES, {"venues": []})
    previous_sources_doc = load_json(DISCOVERED_SOURCES, {"sources": []})
    previous_frontier = load_json(FRONTIER_PATH, {"items": []})

    canonical_names = {normalize(row.get("name")) for row in canonical.get("places", []) if row.get("name")}
    previous_venues = [row for row in previous_venues_doc.get("venues", []) if normalize(row.get("name")) not in canonical_names]
    keep_source_ids = {e.get("sourceId") for row in previous_venues for e in row.get("evidence", [])}
    previous_sources = [row for row in previous_sources_doc.get("sources", []) if row.get("id") in keep_source_ids]

    if no_network:
        frontier = previous_frontier.get("items", [])
        provider = previous_state.get("provider")
        provider_errors: list[str] = []
        status = "OK_NO_NETWORK_LAST_KNOWN_GOOD"
    else:
        elements, provider, provider_errors = query_overpass(timeout)
        if provider:
            frontier = osm_frontier(elements)
            status = "OK"
        else:
            frontier = previous_frontier.get("items", [])
            status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"

    known = known_names(static_seed, canonical)
    known.update(normalize(row.get("name")) for row in previous_venues)
    cursor = int(previous_state.get("cursor") or 0)
    selected, next_cursor = rotate(frontier, cursor, max_websites)
    verifications: list[dict[str, Any]] = []
    new_venues: list[dict[str, Any]] = []
    new_sources: list[dict[str, Any]] = []

    if not no_network:
        for row in selected:
            name_key = normalize(row.get("name"))
            if not name_key or name_key in known:
                continue
            verification = verify_website(row["name"], row["websiteCandidate"], row["address"], timeout)
            verification_row = {
                "discoveryId": row.get("discoveryId"),
                "name": row.get("name"),
                **verification,
            }
            verifications.append(verification_row)
            if not verification.get("verifiedOfficialIdentity"):
                continue
            venue_id = stable_id(row["name"], str(verification["website"]))
            source = source_from_verification(venue_id, row["name"], verification)
            venue = venue_from_verification(row, verification, source["id"])
            new_sources.append(source)
            new_venues.append(venue)
            known.add(name_key)

    source_map = {str(row["id"]): row for row in previous_sources if row.get("id")}
    for row in new_sources:
        source_map[str(row["id"])] = row
    venue_map = {str(row["id"]): row for row in previous_venues if row.get("id")}
    for row in new_venues:
        venue_map[str(row["id"])] = row
    overlay_sources = list(source_map.values())
    overlay_venues = list(venue_map.values())

    # Ephemeral working-tree overlays consumed by venue_ingest.py, validator,
    # collision guard and promotion gate in the same workflow run. The workflow
    # deliberately does not persist these static baseline files.
    merged_registry = merge_overlay(static_registry, "sources", overlay_sources)
    merged_seed = merge_overlay(static_seed, "venues", overlay_venues)
    dump_json(REGISTRY_PATH, merged_registry)
    dump_json(SEED_PATH, merged_seed)

    dump_json(DISCOVERED_SOURCES, {"schemaVersion": "1.0", "generatedAt": observed, "sources": overlay_sources})
    dump_json(DISCOVERED_VENUES, {"schemaVersion": "1.0", "generatedAt": observed, "venues": overlay_venues})
    dump_json(FRONTIER_PATH, {
        "schemaVersion": "1.0",
        "generatedAt": observed,
        "status": status,
        "provider": provider,
        "providerErrors": provider_errors,
        "items": frontier,
    })
    dump_json(DISCOVERY_STATE, {
        "schemaVersion": "1.0",
        "observedAt": observed,
        "status": status,
        "provider": provider,
        "cursor": next_cursor,
        "frontierCount": len(frontier),
        "websiteCandidates": sum(bool(row.get("websiteCandidate")) for row in frontier),
        "checkedThisRun": len(verifications),
        "durableDiscoveredVenues": len(overlay_venues),
        "durableDiscoveredSources": len(overlay_sources),
    })
    receipt = {
        "schema_version": "1.0",
        "generated_at": observed,
        "status": status,
        "policy": {
            "osm_is_discovery_only": True,
            "official_website_required_for_seed_overlay": True,
            "official_name_and_locality_required": True,
            "official_street_confirmation_required_for_auto_eligibility": True,
            "operator_ownership_inference": False,
            "publication_effect": "NONE",
        },
        "frontier_count": len(frontier),
        "website_candidates": sum(bool(row.get("websiteCandidate")) for row in frontier),
        "websites_checked": len(verifications),
        "official_identity_matches": sum(bool(row.get("verifiedOfficialIdentity")) for row in verifications),
        "official_address_matches": sum(bool(row.get("verifiedOfficialAddress")) for row in verifications),
        "new_overlay_venues": [row["id"] for row in new_venues],
        "new_auto_eligible": [row["id"] for row in new_venues if row.get("editorialEligibility") == "DRAFT_ELIGIBLE"],
        "new_review_required": [row["id"] for row in new_venues if row.get("editorialEligibility") == "DRAFT_REVIEW_REQUIRED"],
        "verifications": verifications,
        "provider_errors": provider_errors,
    }
    dump_json(RECEIPT_PATH, receipt)
    return receipt


def self_test() -> int:
    text = "Restaurant Luna, Râmnicu Vâlcea, Strada Republicii 12. Contact și rezervări."
    address = {"street": "Strada Republicii", "housenumber": "12"}
    assert name_matches("Restaurant Luna", text)
    assert locality_matches(text)
    assert street_matches(address, text)
    assert not name_matches("Restaurant Soare", text)
    assert not street_matches({"street": "Calea lui Traian", "housenumber": "9"}, text)

    rows = [
        {"discoveryId": "1", "name": "A", "websiteCandidate": "https://a.example/"},
        {"discoveryId": "2", "name": "B", "websiteCandidate": "https://b.example/"},
        {"discoveryId": "3", "name": "C", "websiteCandidate": "https://c.example/"},
    ]
    selected, cursor = rotate(rows, 1, 2)
    assert [row["name"] for row in selected] == ["B", "C"] and cursor == 0

    verification = {
        "observedAt": "2026-08-18T20:00:00+00:00",
        "website": "https://luna.example/",
        "verifiedOfficialIdentity": True,
        "verifiedOfficialAddress": True,
    }
    row = {
        "discoveryId": "osm-node-1",
        "name": "Restaurant Luna",
        "address": {"display": "Strada Republicii nr. 12, Râmnicu Vâlcea", "street": "Strada Republicii", "housenumber": "12"},
        "categories": ["RESTAURANT"],
        "osm": {"sourceUrl": "https://www.openstreetmap.org/node/1"},
    }
    vid = stable_id(row["name"], verification["website"])
    source = source_from_verification(vid, row["name"], verification)
    venue = venue_from_verification(row, verification, source["id"])
    assert source["tier"] == "T1" and "ADDRESS" in source["authorityScopes"]
    assert venue["verification"] == "VERIFIED_OFFICIAL"
    assert venue["editorialEligibility"] == "DRAFT_ELIGIBLE"
    assert venue["discoveryProvenance"]["osmPublicationEvidence"] is False

    weaker = dict(verification)
    weaker["verifiedOfficialAddress"] = False
    venue = venue_from_verification(row, weaker, source["id"])
    assert venue["verification"] == "PARTIALLY_VERIFIED"
    assert venue["editorialEligibility"] == "DRAFT_REVIEW_REQUIRED"
    print("Dynamic venue discovery self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=7.0)
    parser.add_argument("--max-websites", type=int, default=18)
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    receipt = run_discovery(args.timeout, max(0, args.max_websites), args.no_network)
    print(json.dumps({
        "status": "PASS",
        "discovery_status": receipt["status"],
        "frontier_count": receipt["frontier_count"],
        "website_candidates": receipt["website_candidates"],
        "websites_checked": receipt["websites_checked"],
        "new_overlay_venues": receipt["new_overlay_venues"],
        "new_auto_eligible": receipt["new_auto_eligible"],
        "new_review_required": receipt["new_review_required"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
