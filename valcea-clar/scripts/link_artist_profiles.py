#!/usr/bin/env python3
"""Attach verified VÂLCEA CLAR artist profiles to festival and performing-arts stories.

The script enriches the durable archive, public live feed and canonical static
story pages. It never creates an artist identity; it only links profiles already
admitted by Artist Intelligence from a verified festival lineup or
performing-arts programme.
"""
from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
ARTISTS = RUNTIME / "artists.json"
FEED = RUNTIME / "live-feed.json"
ARCHIVE = ROOT / "site" / "story_archive.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
MARKER_START = '<section class="artist-profiles" data-artist-intelligence="verified">'
MARKER_END = '</section><!-- /artist-profiles -->'
ARTIST_PATH = re.compile(r"^/artisti/[a-z0-9-]+/$")


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def valid_artist_path(value: object) -> bool:
    return bool(ARTIST_PATH.fullmatch(str(value or "").strip()))


def grouped_profiles(document: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for profile in document.get("profiles") or []:
        if not isinstance(profile, dict) or profile.get("publication_status") != "public":
            continue
        name = str(profile.get("name") or "").strip()
        path = str(profile.get("path") or "").strip()
        if not name or not valid_artist_path(path):
            continue
        public = {
            "id": str(profile.get("id") or ""),
            "name": name,
            "path": path,
            # Only the identity resolver may mint musicbrainz_id. Collapse that
            # evidence to an actual bool before it crosses into public runtime.
            "external_identity_verified": bool(profile.get("musicbrainz_id")),
        }
        story_ids: set[str] = set()
        for festival in profile.get("festivals") or []:
            if isinstance(festival, dict) and str(festival.get("story_id") or "").strip():
                story_ids.add(str(festival.get("story_id")).strip())
        for appearance in profile.get("appearances") or []:
            if isinstance(appearance, dict) and str(appearance.get("story_id") or "").strip():
                story_ids.add(str(appearance.get("story_id")).strip())
        for story_id in story_ids:
            grouped.setdefault(story_id, []).append(public)
    for story_id, rows in grouped.items():
        dedupe = {row["path"]: row for row in rows}
        grouped[story_id] = sorted(dedupe.values(), key=lambda row: row["name"].casefold())
    return grouped


def section_html(rows: list[dict]) -> str:
    safe_rows = [
        row for row in rows
        if isinstance(row, dict)
        and str(row.get("name") or "").strip()
        and valid_artist_path(row.get("path"))
    ]
    if not safe_rows:
        return ""
    links = "".join(
        f'<li><a href="{esc(row["path"])}">{esc(row["name"])}</a>'
        + (' <span title="Identitate externă verificată">✓</span>' if row.get("external_identity_verified") is True else '')
        + '</li>'
        for row in safe_rows
    )
    return (
        MARKER_START
        + '<h2>Artiști și creatori din acest material</h2>'
        + '<p>Profiluri VÂLCEA CLAR construite din line-up, distribuții și programe verificate; conturile externe apar numai după rezolvarea identității.</p>'
        + f'<ul>{links}</ul>'
        + MARKER_END
    )


def replace_static_section(path: Path, rows: list[dict]) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END), re.S)
    text = pattern.sub("", text)
    block = section_html(rows)
    if block:
        anchor = '<section class="sources">'
        if anchor not in text:
            raise RuntimeError(f"story source anchor missing: {path}")
        text = text.replace(anchor, block + "\n" + anchor, 1)
    before = path.read_text(encoding="utf-8")
    if text == before:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def apply_story_profiles(stories: list, grouped: dict[str, list[dict]]) -> int:
    changed = 0
    for story in stories:
        if not isinstance(story, dict):
            continue
        story_id = str(story.get("id") or "").strip()
        rows = grouped.get(story_id, [])
        previous = story.get("artist_profiles") or []
        if rows:
            story["artist_profiles"] = rows
        else:
            story.pop("artist_profiles", None)
        if previous != rows:
            changed += 1
    return changed


def self_test() -> None:
    grouped = grouped_profiles({
        "profiles": [
            {
                "id": "verified",
                "name": "Verified Artist",
                "path": "/artisti/verified-artist/",
                "publication_status": "public",
                "musicbrainz_id": "mbid-1",
                "festivals": [{"story_id": "festival-1"}],
            },
            {
                "id": "pending",
                "name": "Pending Artist",
                "path": "/artisti/pending-artist/",
                "publication_status": "public",
                "festivals": [{"story_id": "festival-1"}],
            },
            {
                "id": "unsafe",
                "name": "Unsafe",
                "path": "https://example.invalid/artist",
                "publication_status": "public",
                "musicbrainz_id": "mbid-unsafe",
                "festivals": [{"story_id": "festival-1"}],
            },
        ]
    })
    rows = grouped["festival-1"]
    assert [row["path"] for row in rows] == [
        "/artisti/pending-artist/",
        "/artisti/verified-artist/",
    ]
    assert next(row for row in rows if row["id"] == "verified")["external_identity_verified"] is True
    assert next(row for row in rows if row["id"] == "pending")["external_identity_verified"] is False
    rendered = section_html(rows)
    assert '<a href="/artisti/verified-artist/">Verified Artist</a>' in rendered
    assert '<a href="/artisti/pending-artist/">Pending Artist</a>' in rendered
    assert rendered.count("Identitate externă verificată") == 1
    forged = section_html([{
        "id": "forged",
        "name": "Forged Flag",
        "path": "/artisti/forged-flag/",
        "external_identity_verified": "false",
    }])
    assert "Identitate externă verificată" not in forged
    print("VÂLCEA CLAR artist story-link contract self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    if not ARTISTS.is_file() or not FEED.is_file():
        raise SystemExit("Artist intelligence and live feed are required")
    grouped = grouped_profiles(load(ARTISTS))
    feed = load(FEED)
    stories = feed.get("stories") or []
    touched_feed = apply_story_profiles(stories, grouped)
    linked_profiles = sum(len(grouped.get(str(story.get("id") or ""), [])) for story in stories if isinstance(story, dict))
    static_changed = 0

    for story in stories:
        if not isinstance(story, dict):
            continue
        story_id = str(story.get("id") or "").strip()
        if replace_static_section(RUNTIME / "stiri" / story_id / "index.html", grouped.get(story_id, [])):
            static_changed += 1

    feed.setdefault("extensions", {})["artist_intelligence"] = {
        "enabled": True,
        "profile_directory": "/artisti/",
        "story_links_bidirectional": True,
        "verified_sources": ["festival_lineup", "performing_arts_programme"],
        "unverified_external_identity_links": False,
    }
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    archive_changed = 0
    if ARCHIVE.is_file():
        archive = load(ARCHIVE)
        archive_changed = apply_story_profiles(archive.get("stories") or [], grouped)
        if archive_changed:
            ARCHIVE.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    if STORY_MANIFEST.is_file():
        manifest = load(STORY_MANIFEST)
        for row in manifest.get("stories") or []:
            story_id = str(row.get("id") or "")
            profiles = grouped.get(story_id, [])
            if profiles:
                row["artist_profile_ids"] = [profile["id"] for profile in profiles]
                row["artist_profile_paths"] = [profile["path"] for profile in profiles]
            else:
                row.pop("artist_profile_ids", None)
                row.pop("artist_profile_paths", None)
        cross_linking = manifest.setdefault("cross_linking", {})
        cross_linking.setdefault("enabled", True)
        cross_linking.setdefault("eligible_scope", "publishable_full_story_only")
        cross_linking["artist_intelligence"] = "verified_programme_profiles_only"
        STORY_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "stories_with_profiles": sum(1 for rows in grouped.values() if rows),
        "linked_profiles": linked_profiles,
        "feed_stories_changed": touched_feed,
        "archive_stories_changed": archive_changed,
        "static_story_pages_changed": static_changed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
