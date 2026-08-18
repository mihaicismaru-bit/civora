#!/usr/bin/env python3
"""Recover real-photo candidates for every published VÂLCEA CLAR story.

This is an audit-first backfill layer on top of real_photo_resolver.py.

Safety properties:
- published history comes from site/story_archive.json;
- current edition and explicit replacement queue are unioned into the same scope;
- official source pages may contribute real-photo candidates under a documented
  reuse presumption, never as an asserted open license;
- any third-party rights signal disables that presumption;
- every discovered image remains subject_match=false, editor_approved=false and
  publication_eligible=false;
- this script never edits story_visuals.json.

A later autonomous verifier may promote only candidates whose subject identity,
rights basis and provenance all pass its fail-closed contract.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
sys.path.insert(0, str(SOCIAL))

import real_photo_resolver as base  # noqa: E402

ARCHIVE = VC / "site" / "story_archive.json"
REUSE_POLICY = SOCIAL / "photo_reuse_inference_policy.json"
OUTPUT = SOCIAL / "story_visual_candidates.json"

HEADERS = {
    "User-Agent": "ValceaClarPublishedPhotoRecovery/1.0 (+https://valceaclar.ro)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.5",
}
MAX_SOURCE_BYTES = 2_500_000
MAX_OFFICIAL_IMAGES_PER_STORY = 4

IMAGE_META_PATTERNS = (
    re.compile(
        r'<meta[^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image|twitter:image)["\']',
        re.I,
    ),
    re.compile(
        r'<link[^>]+rel=["\']image_src["\'][^>]+href=["\']([^"\']+)["\']',
        re.I,
    ),
)
BAD_IMAGE_MARKERS = (
    "logo", "favicon", "icon", "sprite", "placeholder", "blank.", "default-image",
    "avatar-default", "loading.", "spacer.",
)


def load_policy() -> dict[str, Any]:
    return base.load_json(REUSE_POLICY)


def published_stories() -> list[dict[str, Any]]:
    archive = base.load_json(ARCHIVE, {"stories": []})
    stories = archive.get("stories", [])
    if not isinstance(stories, list):
        raise RuntimeError("story_archive.json stories must be an array")
    return [
        dict(story)
        for story in stories
        if isinstance(story, dict)
        and story.get("id")
        and (story.get("canonical_url") or story.get("path") or story.get("first_published_at"))
    ]


def merge_story(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    out = dict(existing)
    for key, value in incoming.items():
        if value in (None, "", [], {}):
            continue
        if key == "sources" and isinstance(value, list):
            prior = out.get("sources")
            rows = list(prior) if isinstance(prior, list) else []
            seen = {
                str(row.get("url") or "").strip()
                for row in rows
                if isinstance(row, dict)
            }
            for row in value:
                if not isinstance(row, dict):
                    continue
                url = str(row.get("url") or "").strip()
                if url and url in seen:
                    continue
                rows.append(dict(row))
                if url:
                    seen.add(url)
            out["sources"] = rows
            continue
        out[key] = value
    return out


def all_story_scope() -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    archived = published_stories()
    current = base.current_stories()
    queued = base.queued_replacements()
    combined: dict[str, dict[str, Any]] = {}
    for group in (archived, current, queued):
        for story in group:
            story_id = str(story.get("id") or story.get("story_id") or "").strip()
            if not story_id:
                continue
            if story_id in combined:
                combined[story_id] = merge_story(combined[story_id], story)
            else:
                combined[story_id] = dict(story)
    return combined, {
        "archived_published": len(archived),
        "current_edition": len(current),
        "replacement_queue": len(queued),
        "unique_total": len(combined),
    }


def source_name(source: dict[str, Any]) -> str:
    return base.clean_html(source.get("name")).strip()


def source_url(source: dict[str, Any]) -> str:
    return base.clean_html(source.get("url")).strip()


def host_of(url: str) -> str:
    try:
        return (urllib.parse.urlparse(url).hostname or "").lower().lstrip("www.")
    except ValueError:
        return ""


def has_any(text: str, values: list[str] | tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in values)


def classify_official_source(
    story: dict[str, Any],
    source: dict[str, Any],
    policy: dict[str, Any],
) -> str | None:
    name = source_name(source)
    url = source_url(source)
    host = host_of(url)
    if not url.startswith(("http://", "https://")):
        return None

    third_party = tuple(policy.get("third_party_rights_markers") or [])
    if has_any(f"{name} {host}", third_party):
        return None

    classes = policy.get("source_classes", {})
    public = classes.get("public_sector_official", {}) if isinstance(classes, dict) else {}
    promo = classes.get("official_promotional", {}) if isinstance(classes, dict) else {}
    figure = classes.get("public_figure_official", {}) if isinstance(classes, dict) else {}

    public_name_markers = tuple(public.get("name_markers") or [])
    public_host_suffixes = tuple(public.get("host_suffixes") or [])
    public_hosts = tuple(public.get("hosts") or [])
    tier = base.clean_html(source.get("tier")).upper()

    if (
        has_any(name, public_name_markers)
        or host in {h.lower() for h in public_hosts}
        or any(host.endswith(suffix.lower()) for suffix in public_host_suffixes)
    ):
        if tier in {"", "T1"} or public.get("allow_non_t1") is True:
            return "PUBLIC_SECTOR_REUSE_PRESUMPTION"

    promo_markers = tuple(promo.get("name_markers") or [])
    promo_host_markers = tuple(promo.get("host_markers") or [])
    if has_any(name, promo_markers) or has_any(host, promo_host_markers):
        return "OFFICIAL_PROMOTIONAL_PRESUMPTION"

    figure_markers = tuple(figure.get("name_markers") or [])
    figure_hosts = tuple(figure.get("hosts") or [])
    section = base.clean_html(story.get("section")).lower()
    if (
        has_any(name, figure_markers)
        or host in {h.lower() for h in figure_hosts}
    ) and section in {"politic", "politică", "administratie", "administrație", "putere"}:
        return "PUBLIC_FIGURE_OFFICIAL_MEDIA_PRESUMPTION"

    return None


def http_text(url: str) -> str:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read(MAX_SOURCE_BYTES)
        charset = response.headers.get_content_charset() or "utf-8"
    return data.decode(charset, errors="replace")


def normalize_image_url(page_url: str, raw_url: str) -> str:
    value = html.unescape(str(raw_url or "")).strip()
    if not value or value.startswith(("data:", "javascript:")):
        return ""
    absolute = urllib.parse.urljoin(page_url, value)
    parsed = urllib.parse.urlparse(absolute)
    if parsed.scheme not in {"http", "https"}:
        return ""
    return absolute


def looks_photo_like(url: str) -> bool:
    lowered = url.lower()
    if any(marker in lowered for marker in BAD_IMAGE_MARKERS):
        return False
    path = urllib.parse.urlparse(url).path.lower()
    return path.endswith((".jpg", ".jpeg", ".webp"))


def extract_meta_images(page_url: str, page_html: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pattern in IMAGE_META_PATTERNS:
        for match in pattern.finditer(page_html):
            url = normalize_image_url(page_url, match.group(1))
            if not url or not looks_photo_like(url) or url in seen:
                continue
            seen.add(url)
            found.append(url)
    return found


def third_party_rights_detected(page_html: str, policy: dict[str, Any]) -> list[str]:
    lowered = page_html.lower()
    detected = []
    for marker in policy.get("third_party_rights_markers") or []:
        if str(marker).lower() in lowered:
            detected.append(str(marker))
    return sorted(set(detected))


def official_source_candidates(
    story: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    sources = story.get("sources")
    if not isinstance(sources, list):
        return [], []

    candidates: list[dict[str, Any]] = []
    failures: list[str] = []
    headline = base.clean_html(story.get("headline") or story.get("required_photo"))

    for source in sources:
        if not isinstance(source, dict):
            continue
        basis = classify_official_source(story, source, policy)
        if not basis:
            continue
        page_url = source_url(source)
        name = source_name(source) or host_of(page_url)
        try:
            page_html = http_text(page_url)
        except (
            urllib.error.URLError,
            urllib.error.HTTPError,
            TimeoutError,
            ValueError,
            OSError,
        ):
            failures.append(page_url)
            continue

        rights_signals = third_party_rights_detected(page_html, policy)
        if rights_signals:
            continue

        image_urls = extract_meta_images(page_url, page_html)
        for image_url in image_urls[:MAX_OFFICIAL_IMAGES_PER_STORY]:
            score = 150
            if basis == "PUBLIC_SECTOR_REUSE_PRESUMPTION":
                score = 170
            elif basis == "PUBLIC_FIGURE_OFFICIAL_MEDIA_PRESUMPTION":
                score = 165
            candidates.append(
                {
                    "provider": "official_source_page",
                    "provider_priority": score,
                    "kind": "photograph",
                    "synthetic": False,
                    "title": f"{name} — imagine de pe pagina-sursă",
                    "photo_type": "SOURCE_PAGE_CANDIDATE",
                    "source_type": "risk_assessed_editorial_use",
                    "source_url": page_url,
                    "direct_source_url": image_url,
                    "credit": name,
                    "creator": name,
                    "rights_basis": "risk_assessed_editorial_use",
                    "rights_status": "PRESUMED_REUSE",
                    "editorial_use_basis": basis,
                    "license": None,
                    "license_label": "no explicit license; controlled editorial reuse presumption",
                    "license_url": "",
                    "alt_text": headline[:300] or name,
                    "captured_at": "",
                    "rights_metadata_verified": False,
                    "provenance_verified_to_source_page": True,
                    "subject_match": False,
                    "editor_approved": False,
                    "publication_eligible": False,
                    "blockers": [
                        "subject_match_not_verified",
                        "autonomous_rights_verifier_required",
                        "autonomous_promotion_gate_required",
                    ],
                    "query": page_url,
                    "score": score,
                }
            )
    return candidates, sorted(set(failures))


def discover_story(
    story: dict[str, Any],
    *,
    approved_ids: set[str],
    policy: dict[str, Any],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    story_id = str(story.get("id") or story.get("story_id") or "").strip()
    headline = base.clean_html(story.get("headline") or story.get("required_photo"))

    if story_id in approved_ids:
        return {
            "story_id": story_id,
            "headline": headline,
            "already_has_approved_visual": True,
            "status": "APPROVED_VISUAL_ALREADY_PRESENT",
            "search_queries": [],
            "candidate_count": 0,
            "candidates": [],
            "discovery_health": "OK",
            "unavailable_providers": [],
            "automatic_promotion": False,
            "publication_gate": "existing_story_visuals_contract",
        }

    base_row = base.discover_story(
        story,
        approved_ids=approved_ids,
        existing=existing,
    )

    official, official_failures = official_source_candidates(story, policy)
    combined = list(base_row.get("candidates") or []) + official
    ranked = base.dedupe_and_rank(combined)

    unavailable = set(base_row.get("unavailable_providers") or [])
    if official_failures:
        unavailable.add("official_source_page")

    return {
        **base_row,
        "story_id": story_id,
        "headline": headline,
        "already_has_approved_visual": False,
        "status": "CANDIDATES_READY" if ranked else base_row.get("status", "NO_SAFE_CANDIDATE"),
        "candidate_count": len(ranked),
        "candidates": ranked,
        "discovery_health": "OK" if not unavailable else "PARTIAL",
        "unavailable_providers": sorted(unavailable),
        "official_source_failures": official_failures,
        "automatic_promotion": False,
        "publication_gate": "autonomous_subject_rights_provenance_verifier_required",
    }


def resolve(*, output: Path = OUTPUT) -> dict[str, Any]:
    policy = load_policy()
    previous = base.load_json(output, {"stories": {}})
    previous_stories = previous.get("stories", {})
    if not isinstance(previous_stories, dict):
        previous_stories = {}

    approved_ids = base.existing_approved_story_ids()
    scope, counts = all_story_scope()
    stories: dict[str, Any] = {}
    for story_id, story in scope.items():
        old = previous_stories.get(story_id)
        stories[story_id] = discover_story(
            story,
            approved_ids=approved_ids,
            policy=policy,
            existing=old if isinstance(old, dict) else None,
        )

    doc = {
        "schema_version": "1.1",
        "publication_model": "continuous_story_first",
        "recovery_scope": "all_published_stories_plus_current_and_replacement_queue",
        "scope_counts": counts,
        "candidate_only": True,
        "automatic_promotion_forbidden": True,
        "rights_cleared_does_not_imply_subject_match": True,
        "risk_assessed_editorial_use_is_not_open_license": True,
        "no_photo_is_better_than_false_relevance": True,
        "stories": stories,
    }

    if base.material_payload(previous) == base.material_payload(doc):
        print(
            f"PUBLISHED_PHOTO_RECOVERY_NO_CHANGE stories={len(stories)} "
            f"archive={counts['archived_published']}"
        )
        return previous

    doc["generated_at_utc"] = base.utc_now()
    base.write_json(output, doc)
    candidate_count = sum(
        int(row.get("candidate_count") or 0)
        for row in stories.values()
        if isinstance(row, dict)
    )
    print(
        f"PUBLISHED_PHOTO_RECOVERY_READY stories={len(stories)} "
        f"archive={counts['archived_published']} candidates={candidate_count} "
        f"approved_existing={len(approved_ids)}"
    )
    return doc


def self_test() -> None:
    policy = {
        "third_party_rights_markers": ["Getty Images", "AGERPRES"],
        "source_classes": {
            "public_sector_official": {
                "name_markers": ["primăria", "poliția română"],
                "host_suffixes": [".gov.ro"],
                "hosts": ["politiaromana.ro"],
                "allow_non_t1": False,
            },
            "official_promotional": {
                "name_markers": ["festival", "organizator"],
                "host_markers": ["festival"],
            },
            "public_figure_official": {
                "name_markers": ["pagina oficială"],
                "hosts": ["facebook.com"],
            },
        },
    }
    public_story = {"section": "SERVICII"}
    public_source = {
        "name": "Primăria Municipiului Râmnicu Vâlcea",
        "url": "https://example.gov.ro/comunicat",
        "tier": "T1",
    }
    assert classify_official_source(public_story, public_source, policy) == "PUBLIC_SECTOR_REUSE_PRESUMPTION"

    festival_source = {
        "name": "Deep Forest Festival — organizator",
        "url": "https://deepforestfestival.example/news",
        "tier": "T1",
    }
    assert classify_official_source({"section": "CULTURĂ"}, festival_source, policy) == "OFFICIAL_PROMOTIONAL_PRESUMPTION"

    blocked = {
        "name": "AGERPRES",
        "url": "https://agerpres.example/photo",
        "tier": "T1",
    }
    assert classify_official_source(public_story, blocked, policy) is None

    sample_html = """
    <html><head>
      <meta property="og:image" content="/media/event-photo.jpg">
      <meta name="twitter:image" content="https://cdn.example.org/logo.png">
    </head></html>
    """
    assert extract_meta_images("https://official.example/story", sample_html) == [
        "https://official.example/media/event-photo.jpg"
    ]
    assert third_party_rights_detected("<p>Foto: Getty Images</p>", policy) == ["Getty Images"]

    merged = merge_story(
        {"id": "x", "headline": "old", "sources": [{"url": "https://a.example"}]},
        {"id": "x", "headline": "new", "sources": [{"url": "https://b.example"}]},
    )
    assert merged["headline"] == "new"
    assert len(merged["sources"]) == 2
    print("PUBLISHED_PHOTO_RECOVERY_SELF_TEST PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    resolve(output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
