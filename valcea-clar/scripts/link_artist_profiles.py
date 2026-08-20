#!/usr/bin/env python3
"""Attach verified VÂLCEA CLAR artist profiles to festival and performing-arts stories.

The script enriches the public live feed and canonical static story pages. It
never creates an artist identity; it only links profiles already admitted by
Artist Intelligence from a verified festival lineup or performing-arts programme.

UI contract: when a verified profile name is mentioned in the story body, the
visible mention is linked directly to the canonical /artisti/<slug>/ profile.
The complete artist/creator index remains visible below the body as a fallback
and discovery surface.
"""
from __future__ import annotations

import html
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
ARTISTS = RUNTIME / "artists.json"
FEED = RUNTIME / "live-feed.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
MARKER_START = '<section class="artist-profiles" data-artist-intelligence="verified">'
MARKER_END = '</section><!-- /artist-profiles -->'
PUBLIC_ARTIST_PATH = re.compile(r"^/artisti/[a-z0-9]+(?:-[a-z0-9]+)*/$")
ARTICLE_PATTERN = re.compile(r"(<article\b[^>]*>)(.*?)(</article>)", re.I | re.S)
ARTICLE_BODY_PATTERN = re.compile(
    r"(<div\b[^>]*\bclass=(?P<quote>['\"])(?P<classes>[^'\"]*\barticle-body\b[^'\"]*)(?P=quote)[^>]*>)(.*?)(</div>)",
    re.I | re.S,
)
SECTION_OPEN_PATTERN = re.compile(
    r"<section\b[^>]*\bclass=(?P<quote>['\"])(?P<classes>[^'\"]*)(?P=quote)[^>]*>",
    re.I,
)
GENERATED_INLINE_LINK_PATTERN = re.compile(
    r'<a\b[^>]*\bclass="[^"]*\bartist-inline-link\b[^"]*"[^>]*>(.*?)</a>',
    re.I | re.S,
)


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
        if not name or not PUBLIC_ARTIST_PATH.fullmatch(path):
            continue
        public = {
            "id": str(profile.get("id") or ""),
            "name": name,
            "path": path,
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
        + '<h2>Artiști și creatori din acest material</h2>'
        + '<p>Profiluri VÂLCEA CLAR construite din line-up, distribuții și programe verificate; conturile externe apar numai după rezolvarea identității.</p>'
        + f'<ul>{links}</ul>'
        + MARKER_END
    )


def inline_link_text_nodes(fragment: str, rows: list[dict]) -> str:
    """Link exact visible profile names without touching tags or existing links."""
    candidates = [
        row for row in rows
        if str(row.get("name") or "").strip()
        and PUBLIC_ARTIST_PATH.fullmatch(str(row.get("path") or ""))
    ]
    if not candidates:
        return fragment

    # Longest first avoids linking a shorter name inside a longer act/person name.
    candidates.sort(key=lambda row: (-len(str(row["name"])), str(row["name"]).casefold()))
    by_escaped_name = {esc(row["name"]): row for row in candidates}
    pattern = re.compile("|".join(re.escape(name) for name in by_escaped_name), re.UNICODE)

    parts = re.split(r"(<[^>]+>)", fragment)
    anchor_depth = 0
    for index, part in enumerate(parts):
        if index % 2:
            if re.match(r"<a\b", part, re.I):
                anchor_depth += 1
            elif re.match(r"</a\b", part, re.I) and anchor_depth:
                anchor_depth -= 1
            continue
        if not part or anchor_depth:
            continue

        def replace(match: re.Match[str]) -> str:
            token = match.group(0)
            row = by_escaped_name[token]
            return f'<a class="artist-inline-link" href="{esc(row["path"])}" data-artist-profile="{esc(row["id"])}">{token}</a>'

        parts[index] = pattern.sub(replace, part)
    return "".join(parts)


def strip_generated_inline_links(fragment: str) -> str:
    """Unwrap only links generated by this script before deterministic relinking."""
    return GENERATED_INLINE_LINK_PATTERN.sub(r"\1", fragment)


def link_article_body(document: str, rows: list[dict]) -> str:
    """Relink the current story body while preserving legacy and current shells."""
    article_match = ARTICLE_PATTERN.search(document)
    if not article_match:
        return document

    article_inner = article_match.group(2)
    body_match = ARTICLE_BODY_PATTERN.search(article_inner)
    if body_match:
        plain_body = strip_generated_inline_links(body_match.group(4))
        linked_body = inline_link_text_nodes(plain_body, rows) if rows else plain_body
        article_inner = (
            article_inner[:body_match.start()]
            + body_match.group(1)
            + linked_body
            + body_match.group(5)
            + article_inner[body_match.end():]
        )
    else:
        plain_article = strip_generated_inline_links(article_inner)
        article_inner = inline_link_text_nodes(plain_article, rows) if rows else plain_article

    replacement = article_match.group(1) + article_inner + article_match.group(3)
    return document[:article_match.start()] + replacement + document[article_match.end():]


def source_section_offset(document: str) -> int | None:
    """Return the canonical source-section offset for either supported shell."""
    for match in SECTION_OPEN_PATTERN.finditer(document):
        classes = set(match.group("classes").split())
        if classes.intersection({"sources", "article-sources"}):
            return match.start()
    return None


def replace_static_story(path: Path, rows: list[dict]) -> bool:
    if not path.is_file():
        return False
    before = path.read_text(encoding="utf-8")
    text = before

    # Remove the generated profile block before modifying the body, so repeated
    # runs are deterministic and never wrap links inside links.
    block_pattern = re.compile(
        r"\s*" + re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END) + r"\s*",
        re.S,
    )
    text = block_pattern.sub("", text)

    text = link_article_body(text, rows)

    block = section_html(rows)
    if block:
        offset = source_section_offset(text)
        if offset is None:
            raise RuntimeError(f"story source anchor missing: {path}")
        text = text[:offset] + block + "\n" + text[offset:]

    if text == before:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def self_test() -> int:
    rows = [{"id": "delia", "name": "Delia", "path": "/artisti/delia/", "external_identity_verified": True}]
    fixtures = {
        "current": (
            '<main><article class="article"><h1>Festival</h1><div class="article-body">'
            '<p>Delia cântă.</p><p><a href="https://example.invalid">Delia extern</a></p>'
            '</div><section class="article-sources"><h2>Surse</h2></section></article></main>'
        ),
        "legacy": (
            '<main><article><p>Delia cântă.</p><section class="sources">'
            '<h2>Surse</h2></section></article></main>'
        ),
    }
    with tempfile.TemporaryDirectory() as directory:
        for name, fixture in fixtures.items():
            path = Path(directory) / f"{name}.html"
            path.write_text(fixture, encoding="utf-8")
            assert replace_static_story(path, rows) is True
            first = path.read_text(encoding="utf-8")
            assert first.count(MARKER_START) == 1
            assert first.count('class="artist-inline-link"') == 1
            if name == "current":
                assert '<a href="https://example.invalid">Delia extern</a>' in first
            assert replace_static_story(path, rows) is False
            assert path.read_text(encoding="utf-8") == first
    assert PUBLIC_ARTIST_PATH.fullmatch("/artisti/delia/")
    assert not PUBLIC_ARTIST_PATH.fullmatch("/artisti/delia/bio/")
    print("VÂLCEA CLAR artist story linker self-test: PASS")
    return 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()
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
        if replace_static_story(static_path, rows):
            static_changed += 1

    feed.setdefault("extensions", {})["artist_intelligence"] = {
        "enabled": True,
        "profile_directory": "/artisti/",
        "story_links_bidirectional": True,
        "inline_story_mentions_linked": True,
        "complete_story_profile_index": True,
        "verified_sources": ["festival_lineup", "performing_arts_programme"],
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
                row["artist_inline_links"] = True
            else:
                row.pop("artist_profile_ids", None)
                row.pop("artist_profile_paths", None)
                row.pop("artist_inline_links", None)
        manifest.setdefault("cross_linking", {})["artist_intelligence"] = "verified_programme_profiles_inline_and_index"
        STORY_MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "status": "PASS",
        "stories_with_profiles": sum(1 for rows in grouped.values() if rows),
        "linked_profiles": linked_profiles,
        "feed_stories_changed": touched_feed,
        "static_story_pages_changed": static_changed,
        "inline_story_mentions": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
