#!/usr/bin/env python3
"""Regression gate for durable, clickable, fail-closed artist profile links."""
from __future__ import annotations

import json
from pathlib import Path

import link_artist_profiles as links

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
RUNTIME = SITE / "runtime"
ARTISTS = RUNTIME / "artists.json"
FEED = RUNTIME / "live-feed.json"
ARCHIVE = SITE / "story_archive.json"
MANIFEST = RUNTIME / "stiri" / "manifest.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def by_id(rows: list) -> dict[str, dict]:
    return {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }


def validate() -> None:
    artist_doc = load(ARTISTS)
    policy = artist_doc.get("policy") or {}
    assert policy.get("ambiguous_external_identity_fail_closed") is True
    assert policy.get("unverified_social_link_publication") is False

    expected = links.grouped_profiles(artist_doc)
    assert expected, "artist intelligence has no story-linked profiles"

    feed = load(FEED)
    archive = load(ARCHIVE)
    manifest = load(MANIFEST)
    feed_by_id = by_id(feed.get("stories") or [])
    archive_by_id = by_id(archive.get("stories") or [])
    manifest_by_id = by_id(manifest.get("stories") or [])

    stories_checked = 0
    profiles_checked = 0
    verified_checked = 0
    pending_checked = 0

    for story_id, rows in expected.items():
        if story_id not in feed_by_id:
            continue
        stories_checked += 1
        profiles_checked += len(rows)

        assert feed_by_id[story_id].get("artist_profiles") == rows, f"feed artist drift: {story_id}"
        assert archive_by_id.get(story_id, {}).get("artist_profiles") == rows, f"archive artist drift: {story_id}"
        assert manifest_by_id.get(story_id, {}).get("artist_profile_paths") == [row["path"] for row in rows], f"manifest artist drift: {story_id}"

        target = RUNTIME / "stiri" / story_id / "index.html"
        assert target.is_file(), f"artist-linked story page missing: {story_id}"
        text = target.read_text(encoding="utf-8")
        expected_block = links.section_html(rows)
        assert expected_block and expected_block in text, f"clickable artist block missing: {story_id}"

        for row in rows:
            anchor = f'<a href="{links.esc(row["path"])}">{links.esc(row["name"])}</a>'
            assert anchor in expected_block, f"artist profile is not a direct internal link: {story_id}:{row['id']}"
            if row.get("external_identity_verified") is True:
                verified_checked += 1
            else:
                pending_checked += 1

    assert stories_checked > 0, "no public stories exercise artist-profile regression coverage"
    assert profiles_checked > 0
    assert verified_checked > 0, "fixture set does not exercise verified identities"
    assert pending_checked > 0, "fixture set does not exercise fail-closed pending identities"

    extension = (feed.get("extensions") or {}).get("artist_intelligence") or {}
    assert extension.get("unverified_external_identity_links") is False
    assert extension.get("story_links_bidirectional") is True
    print(
        "VÂLCEA CLAR artist profile runtime: PASS "
        f"({stories_checked} stories; {profiles_checked} profiles; "
        f"{verified_checked} verified identities; {pending_checked} pending fail-closed)"
    )


def self_test() -> None:
    links.self_test()
    print("VÂLCEA CLAR artist profile runtime validator self-test: PASS")


if __name__ == "__main__":
    import sys
    if "--self-test" in sys.argv:
        self_test()
    else:
        validate()
