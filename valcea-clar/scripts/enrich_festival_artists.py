#!/usr/bin/env python3
"""Build public VÂLCEA CLAR artist profiles from verified festival and performing-arts appearances.

A programme proves an appearance, not an external identity. Musical roles may be
resolved against MusicBrainz when one high-confidence exact match exists. Actors,
directors and other non-musical roles remain minimal verified profiles until a
generic identity resolver can prove their external accounts without ambiguity.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
FESTIVAL_SEEDS = ROOT / "editorial" / "festival_lineups_2026.json"
PERFORMING_SEEDS = ROOT / "editorial" / "performing_arts_people_2026.json"
OUT = ROOT / "site" / "runtime" / "artists.json"
UA = "VÂLCEA-CLAR/1.1 (editorial identity resolver; redactie@valceaclar.ro)"
MB = "https://musicbrainz.org/ws/2"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "artist"


def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").casefold()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def get_json(url: str) -> dict:
    req = Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def merge_seed(by_name: dict[str, dict], *, name: str, appearance: dict, source_url: str, musicbrainz: bool, festival: dict | None = None) -> None:
    name = str(name or "").strip()
    if not name:
        return
    key = norm(name)
    row = by_name.setdefault(key, {
        "name": name,
        "appearances": [],
        "festivals": [],
        "source_urls": [],
        "musicbrainz_eligible": False,
    })
    if appearance not in row["appearances"]:
        row["appearances"].append(appearance)
    if festival and festival not in row["festivals"]:
        row["festivals"].append(festival)
    if source_url and source_url not in row["source_urls"]:
        row["source_urls"].append(source_url)
    row["musicbrainz_eligible"] = bool(row["musicbrainz_eligible"] or musicbrainz)


def flatten_seeds() -> list[dict]:
    by_name: dict[str, dict] = {}
    festival_doc = load(FESTIVAL_SEEDS)
    festivals = festival_doc.get("festivals") or []
    if not isinstance(festivals, list) or not festivals:
        raise ValueError("festival seed registry is empty")
    for festival in festivals:
        story_id = str(festival.get("story_id") or "").strip()
        festival_name = str(festival.get("festival") or "").strip()
        source_url = str(festival.get("source_url") or "").strip()
        if not story_id or not festival_name or not source_url:
            raise ValueError("festival seed row missing identity/source")
        festival_ref = {"story_id": story_id, "name": festival_name}
        for raw_name in festival.get("artists") or []:
            name = str(raw_name or "").strip()
            merge_seed(
                by_name,
                name=name,
                appearance={
                    "kind":"festival",
                    "story_id":story_id,
                    "title":festival_name,
                    "role":"artist / performer",
                    "source_url":source_url,
                },
                source_url=source_url,
                musicbrainz=True,
                festival=festival_ref,
            )

    if PERFORMING_SEEDS.is_file():
        performing_doc = load(PERFORMING_SEEDS)
        events = performing_doc.get("events") or []
        if not isinstance(events, list):
            raise ValueError("performing arts people seed events must be a list")
        for event in events:
            event_id = str(event.get("id") or "").strip()
            title = str(event.get("title") or "").strip()
            date = str(event.get("date") or "").strip()
            institution = str(event.get("institution") or "").strip()
            source_url = str(event.get("source_url") or "").strip()
            story_id = str(event.get("story_id") or "").strip()
            if not event_id or not title or not source_url:
                raise ValueError("performing arts event seed missing identity/source")
            for person in event.get("participants") or []:
                if not isinstance(person, dict):
                    continue
                name = str(person.get("name") or "").strip()
                role = str(person.get("role") or "participant").strip()
                merge_seed(
                    by_name,
                    name=name,
                    appearance={
                        "kind":"performing_arts",
                        "event_id":event_id,
                        "story_id":story_id or None,
                        "title":title,
                        "date":date or None,
                        "institution":institution or None,
                        "role":role,
                        "source_url":source_url,
                    },
                    source_url=source_url,
                    musicbrainz=bool(person.get("musicbrainz")),
                )
    return sorted(by_name.values(), key=lambda row: row["name"].casefold())


def search_musicbrainz(name: str) -> tuple[dict | None, str]:
    query = quote(f'artist:"{name}"')
    doc = get_json(f"{MB}/artist/?query={query}&fmt=json&limit=8")
    candidates = []
    wanted = norm(name)
    for artist in doc.get("artists") or []:
        if norm(str(artist.get("name") or "")) != wanted:
            continue
        score = int(artist.get("score") or 0)
        if score >= 95:
            candidates.append(artist)
    if len(candidates) != 1:
        return None, "no_unique_exact_match" if candidates else "no_exact_match"
    return candidates[0], "exact_musicbrainz_match"


def category(url: str) -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "instagram.com" in host: return "instagram"
    if "facebook.com" in host or "fb.com" in host: return "facebook"
    if "youtube.com" in host or "youtu.be" in host: return "youtube"
    if "spotify.com" in host: return "spotify"
    if "tiktok.com" in host: return "tiktok"
    if "soundcloud.com" in host: return "soundcloud"
    if "bandcamp.com" in host: return "bandcamp"
    if "discogs.com" in host: return "discogs"
    return "official_web"


def relation_links(mbid: str) -> dict[str, list[str]]:
    doc = get_json(f"{MB}/artist/{mbid}?inc=url-rels&fmt=json")
    links: dict[str, list[str]] = {}
    for rel in doc.get("relations") or []:
        resource = str(((rel.get("url") or {}).get("resource")) or "").strip()
        if not resource.startswith(("http://", "https://")):
            continue
        key = category(resource)
        links.setdefault(key, [])
        if resource not in links[key]:
            links[key].append(resource)
    return links


def appearance_summary(seed: dict) -> str:
    values = []
    for row in seed.get("appearances") or []:
        title = str(row.get("title") or "").strip()
        role = str(row.get("role") or "").strip()
        institution = str(row.get("institution") or "").strip()
        label = title
        if institution and row.get("kind") == "performing_arts":
            label += f" ({institution})"
        if role:
            label += f", rol: {role}"
        if label and label not in values:
            values.append(label)
    return "; ".join(values[:5])


def bio_from_mb(seed: dict, artist: dict) -> str:
    name = seed["name"]
    kind = str(artist.get("type") or "act artistic").strip()
    area = str(((artist.get("area") or {}).get("name")) or ((artist.get("begin-area") or {}).get("name")) or "").strip()
    disambiguation = str(artist.get("disambiguation") or "").strip()
    tags = [str(row.get("name") or "").strip() for row in (artist.get("tags") or []) if str(row.get("name") or "").strip()]
    parts = [f"{name} este un artist sau proiect artistic identificat în MusicBrainz ca {kind.lower()}."]
    if area:
        parts.append(f"Identitatea artistică este asociată cu {area}.")
    if tags:
        parts.append("Etichete publice: " + ", ".join(tags[:4]) + ".")
    if disambiguation:
        parts.append(f"MusicBrainz îl diferențiază prin descrierea: {disambiguation}.")
    summary = appearance_summary(seed)
    if summary:
        parts.append(f"În documentarea VÂLCEA CLAR apare în: {summary}.")
    return " ".join(parts)


def minimal_bio(seed: dict) -> str:
    summary = appearance_summary(seed)
    return (
        f"{seed['name']} este un artist sau participant cultural identificat într-un program verificat de VÂLCEA CLAR"
        + (f": {summary}. " if summary else ". ")
        + "Identitatea externă și conturile sociale sunt publicate numai după o potrivire unică și verificabilă; profilul rămâne deschis pentru îmbogățire editorială."
    )


def build(*, network: bool) -> dict:
    seeds = flatten_seeds()
    profiles = []
    for index, seed in enumerate(seeds):
        artist = None
        if seed.get("musicbrainz_eligible"):
            status = "programme_verified_external_identity_pending"
        else:
            status = "programme_verified_generic_identity_resolver_pending"
        links: dict[str, list[str]] = {}
        if network and seed.get("musicbrainz_eligible"):
            try:
                artist, status = search_musicbrainz(seed["name"])
                if artist:
                    time.sleep(0.15)
                    links = relation_links(str(artist["id"]))
            except Exception as exc:
                status = f"resolver_error:{type(exc).__name__}"
        profile = {
            "id": slugify(seed["name"]),
            "name": seed["name"],
            "path": f"/artisti/{slugify(seed['name'])}/",
            "publication_status": "public",
            "resolution_status": status,
            "bio": bio_from_mb(seed, artist) if artist else minimal_bio(seed),
            "festivals": seed.get("festivals") or [],
            "appearances": seed.get("appearances") or [],
            "links": links,
            "source_urls": seed["source_urls"],
            "musicbrainz_eligible": bool(seed.get("musicbrainz_eligible")),
        }
        if artist:
            profile["musicbrainz_id"] = artist.get("id")
            profile["musicbrainz_type"] = artist.get("type")
            profile["musicbrainz_disambiguation"] = artist.get("disambiguation")
        profiles.append(profile)
        if network and seed.get("musicbrainz_eligible") and index + 1 < len(seeds):
            time.sleep(0.9)
    return {
        "schema_version": "1.1",
        "product": "VÂLCEA CLAR Artist Intelligence",
        "generated_from": ["editorial/festival_lineups_2026.json", "editorial/performing_arts_people_2026.json"],
        "profile_count": len(profiles),
        "profiles": profiles,
        "policy": {
            "verified_programme_proves_appearance_not_external_identity": True,
            "ambiguous_external_identity_fail_closed": True,
            "unverified_social_link_publication": False,
            "musicbrainz_only_for_musical_roles": True,
            "generic_actor_director_resolver_pending": True,
            "profiles_remain_public_minimal_when_external_identity_is_pending": True,
        },
    }


def self_test() -> None:
    assert slugify("Ionuț Fulea") == "ionut-fulea"
    assert norm("Connect-R") == "connect r"
    seeds = flatten_seeds()
    assert seeds
    assert any(row.get("appearances") for row in seeds)
    assert category("https://www.instagram.com/test/") == "instagram"
    print("VÂLCEA CLAR artist intelligence self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-network", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test(); return 0
    doc = build(network=not args.no_network and not args.check)
    if args.check:
        assert doc["profile_count"] > 0
        print(json.dumps({"status":"PASS","profiles":doc["profile_count"]}, ensure_ascii=False)); return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status":"PASS","profiles":doc["profile_count"],"output":str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
