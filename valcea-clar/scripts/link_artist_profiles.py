#!/usr/bin/env python3
"""Attach verified VÂLCEA CLAR artist profiles to festival stories.

The script enriches the public live feed and canonical static story pages. It
never creates an artist identity; it only links profiles already admitted by
Artist Intelligence.
"""
from __future__ import annotations

import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
ARTISTS = RUNTIME / "artists.json"
FEED = RUNTIME / "live-feed.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
MARKER_START = '<section class="artist-profiles" data-artist-intelligence="verified">'
MARKER_END = '</section><!-- /artist-profiles -->'


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def grouped_profiles(document: dict) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for profile in document.get("profiles") or []:
        if not isinstance(profile, dict) or profile.get("publication_status") != "public":
            continue
        name = str(profile.get("name") or "").strip()
        path = str(profile.get("path") or "").strip()
        if not name or not path.startswith("/artisti/"):
            continue
        public = {
            "id": str(profile.get("id") or ""),
            "name": name,
            "path": path,
            "external_identity_verified": bool(profile.get("musicbrainz_id")),
        }
        for festival in profile.get("festivals") or []:
            if not isinstance(festival, dict):
                continue
            story_id = str(festival.get("story_id") or "").strip()
            if story_id:
                grouped.setdefault(story_id, []).append(public)
    for story_id, rows in grouped.items():
        dedupe = {row["path"]: row for row in rows}
        grouped[story_id] = sorted(dedupe.values(), key=lambda row: row["name"].casefold())
    return grouped


def section_html(rows: list[dict]) -> str:
    if not rows:
        return ""
    links = "".join(
        f'<li><a href="{esc(row["path"])}">{esc(row["name"])}</a>'
        + (' <span title="Identitate externă verificată">✓</span>' if row.get("external_identity_verified") else '')
        + '</li>'
        for row in rows
    )
    return (
        MARKER_START
        + '<h2>Artiști din acest festival</h2>'
        + '<p>Profiluri VÂLCEA CLAR construite din line-up verificat; conturile externe apar numai după rezolvarea identității.</p>'
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


def main() -> int:
    if not ARTISTS.is_file() or not FEED.is_file():
        raise SystemExit("Artist intelligence and live feed are required")
    grouped = grouped_profiles(load(ARTISTS))
    feed = load(FEED)
    stories = feed.get("stories") or []
    touched_feed = 0
    linked_profiles = 0
    static_changed = 0

    for story in stories:
        if not isinstance(story, dict):
            continue
        story_id = str(story.get("id") or "").strip()
        rows = grouped.get(story_id, [])
        previous = story.get("artist_profiles") or []
        if rows:
            story["artist_profiles"] = rows
            linked_profiles += len(rows)
        else:
            story.pop("artist_profiles", None)
        if previous != rows:
            touched_feed += 1
        static_path = RUNTIME / "stiri" / story_id / "index.html"
        if replace_static_section(static_path, rows):
            static_changed += 1

    feed.setdefault("extensions", {})["artist_intelligence"] = {
        "enabled": True,
        "profile_directory": "/artisti/",
        "story_links_bidirectional": True,
        "unverified_external_identity_links": False,
    }
    FEED.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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
        manifest.setdefault("cross_linking", {})["artist_intelligence"] = "verified_lineup_profiles_only"
        STORY_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "festival_stories_with_profiles": sum(1 for rows in grouped.values() if rows),
        "linked_profiles": linked_profiles,
        "feed_stories_changed": touched_feed,
        "static_story_pages_changed": static_changed,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
