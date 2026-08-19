#!/usr/bin/env python3
"""Discover free real-photo candidates without granting publication authority.

VÂLCEA CLAR Photo Atlas is approved-only. This resolver is the separate
candidate layer: it searches Wikimedia Commons and Openverse, keeps only a
strict reusable-license allowlist, and always writes candidates with
`subject_match=false`, `editor_approved=false`, `publication_eligible=false`
and `publication_authority=NONE`.

Provider outages are editorially non-blocking. A discovered candidate can only
move into `story_visuals.json` through a separate subject-match, provenance and
editor-approval decision.
"""
from __future__ import annotations

import argparse
import copy
import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
VC = ROOT / "valcea-clar"
SOCIAL = VC / "social"
ARCHIVE = VC / "site" / "story_archive.json"
VISUALS = SOCIAL / "story_visuals.json"
POLICY = SOCIAL / "photo_candidate_policy.json"
OUTPUT = SOCIAL / "photo_candidate_registry.json"

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
DEFAULT_TIMEOUT = 14
DEFAULT_BATCH = 4
PER_PROVIDER_LIMIT = 3
MAX_CANDIDATES_PER_STORY = 6

HEADERS = {
    "User-Agent": "ValceaClarPhotoCandidateResolver/1.2 (+https://valceaclar.ro)",
    "Accept": "application/json",
}

ROMANIAN_STOPWORDS = {
    "aceasta", "acest", "ale", "al", "a", "ai", "cu", "de", "din", "dupa",
    "după", "fara", "fără", "in", "în", "la", "lui", "o", "pe", "pentru",
    "prin", "si", "și", "sau", "un", "unei", "unui", "valcea", "vâlcea",
    "clar", "2026", "2025", "lei",
}

KNOWN_LOCAL_PLACES = (
    "Râmnicu Vâlcea",
    "Băile Olănești",
    "Băile Govora",
    "Călimănești",
    "Brezoi",
    "Drăgășani",
    "Horezu",
    "Voineasa",
    "Vaideeni",
    "Mălaia",
    "Ocnele Mari",
    "Șuțești",
    "Vâlcea",
)


class CandidateError(ValueError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        if default is not None:
            return copy.deepcopy(default)
        raise CandidateError(f"missing required file: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def clean_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(text.split())


def metadata_value(meta: dict[str, Any], key: str) -> str:
    raw = meta.get(key)
    if isinstance(raw, dict):
        return clean_html(raw.get("value"))
    return clean_html(raw)


def canonical_license(value: str) -> tuple[str, str] | None:
    normalized = " ".join(str(value or "").upper().replace("_", " ").split())
    if not normalized:
        return None
    if "NONCOMMERCIAL" in normalized or "NO DERIV" in normalized:
        return None
    if re.search(r"(^|[-\s])NC($|[-\s])", normalized):
        return None
    if re.search(r"(^|[-\s])ND($|[-\s])", normalized):
        return None
    if "PUBLIC DOMAIN" in normalized or normalized in {"PD", "PDM"}:
        return ("public_domain", "public-domain")
    if "CC0" in normalized:
        return ("public_domain", "cc0")
    if "CC BY-SA" in normalized or normalized in {"BY-SA", "BY SA"}:
        return ("creative_commons", "cc-by-sa")
    if "CC BY" in normalized or normalized == "BY":
        return ("creative_commons", "cc-by")
    return None


def openverse_license(value: str) -> tuple[str, str] | None:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return {
        "cc0": ("public_domain", "cc0"),
        "pdm": ("public_domain", "public-domain"),
        "by": ("creative_commons", "cc-by"),
        "by-sa": ("creative_commons", "cc-by-sa"),
    }.get(normalized)


def jpeg_like(url: str, mime: str = "", filetype: str = "") -> bool:
    if str(mime or "").lower() == "image/jpeg":
        return True
    if str(filetype or "").lower().lstrip(".") in {"jpg", "jpeg"}:
        return True
    path = urllib.parse.urlparse(str(url or "")).path.lower()
    return path.endswith(".jpg") or path.endswith(".jpeg")


def https_url(value: Any) -> str:
    text = clean_html(value)
    return text if text.startswith("https://") else ""


def http_json(url: str, timeout: int) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(4_000_000)
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise CandidateError("provider returned non-object JSON")
    return value


def query_terms(value: str) -> list[str]:
    tokens = re.findall(r"[0-9A-Za-zĂÂÎȘȚăâîșț-]{3,}", value or "")
    return [token.lower() for token in tokens if token.lower() not in ROMANIAN_STOPWORDS]


def relevance_score(query: str, title: str, provider_priority: int) -> int:
    q = set(query_terms(query))
    t = set(query_terms(title))
    overlap = len(q & t)
    exact = int(bool(query and clean_html(query).lower() in clean_html(title).lower()))
    return provider_priority + min(overlap * 7, 35) + exact * 20


def build_queries(story: dict[str, Any]) -> list[str]:
    explicit = story.get("media_request")
    if isinstance(explicit, dict):
        subject = clean_html(explicit.get("subject"))
        if subject:
            return [subject[:140]]

    headline = clean_html(story.get("headline"))
    dek = clean_html(story.get("dek"))
    combined = f"{headline} {dek}".lower()
    queries: list[str] = []

    terms = query_terms(headline)
    if terms:
        queries.append(" ".join(terms[:8]))

    for place in KNOWN_LOCAL_PLACES:
        if place.lower() in combined:
            queries.append(place)
            break

    if not queries and headline:
        queries.append(headline[:140])

    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        key = query.casefold().strip()
        if key and key not in seen:
            seen.add(key)
            unique.append(query)
    return unique[:2]


def wikimedia_candidates(query: str, timeout: int) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": str(PER_PROVIDER_LIMIT),
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiextmetadatalanguage": "en",
        "iiextmetadatafilter": "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|DateTimeOriginal|UsageTerms",
    }
    payload = http_json(WIKIMEDIA_API + "?" + urllib.parse.urlencode(params), timeout)
    pages = payload.get("query", {}).get("pages", [])
    if not isinstance(pages, list):
        return []

    out: list[dict[str, Any]] = []
    for page in pages:
        if not isinstance(page, dict):
            continue
        infos = page.get("imageinfo")
        if not isinstance(infos, list) or not infos or not isinstance(infos[0], dict):
            continue
        info = infos[0]
        direct_url = https_url(info.get("url"))
        if not direct_url or not jpeg_like(direct_url, clean_html(info.get("mime"))):
            continue
        ext = info.get("extmetadata")
        if not isinstance(ext, dict):
            continue
        raw_license = metadata_value(ext, "LicenseShortName") or metadata_value(ext, "UsageTerms")
        license_info = canonical_license(raw_license)
        if not license_info:
            continue
        rights_basis, canonical = license_info
        title = clean_html(page.get("title")).removeprefix("File:")
        creator = metadata_value(ext, "Artist") or "Wikimedia Commons contributor"
        credit = metadata_value(ext, "Credit") or creator
        license_url = https_url(metadata_value(ext, "LicenseUrl"))
        source_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            str(page.get("title") or "").replace(" ", "_"), safe=":/()_-"
        )
        rights_verified = canonical in {"public-domain", "cc0"} or bool(license_url)
        blockers = ["subject_match_not_verified", "editor_approval_required"]
        if not rights_verified:
            blockers.insert(0, "license_metadata_incomplete")
        out.append({
            "provider": "wikimedia_commons",
            "kind": "photograph",
            "synthetic": False,
            "title": title,
            "source_type": rights_basis,
            "source_url": source_url,
            "direct_source_url": direct_url,
            "creator": creator,
            "credit": credit,
            "rights_basis": rights_basis,
            "license": canonical,
            "license_label": raw_license,
            "license_url": license_url,
            "rights_metadata_verified": rights_verified,
            "source_license_reverification_required": not rights_verified,
            "captured_at": metadata_value(ext, "DateTimeOriginal"),
            "alt_text": (metadata_value(ext, "ImageDescription") or title)[:300],
            "query": query,
            "score": relevance_score(query, title, 100),
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "blockers": blockers,
        })
    return out


def openverse_candidates(query: str, timeout: int) -> list[dict[str, Any]]:
    params = {"q": query, "page_size": str(PER_PROVIDER_LIMIT)}
    payload = http_json(OPENVERSE_API + "?" + urllib.parse.urlencode(params), timeout)
    rows = payload.get("results", [])
    if not isinstance(rows, list):
        return []

    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        license_info = openverse_license(str(row.get("license") or ""))
        if not license_info:
            continue
        rights_basis, canonical = license_info
        direct_url = https_url(row.get("url"))
        source_url = https_url(row.get("foreign_landing_url") or row.get("detail_url"))
        if not direct_url or not source_url or not jpeg_like(
            direct_url, filetype=clean_html(row.get("filetype") or row.get("extension"))
        ):
            continue
        title = clean_html(row.get("title")) or "Openverse image"
        creator = clean_html(row.get("creator")) or "Openverse contributor"
        out.append({
            "provider": "openverse",
            "kind": "photograph",
            "synthetic": False,
            "title": title,
            "source_type": rights_basis,
            "source_url": source_url,
            "direct_source_url": direct_url,
            "creator": creator,
            "credit": creator,
            "rights_basis": rights_basis,
            "license": canonical,
            "license_label": clean_html(row.get("license")) or canonical,
            "license_url": https_url(row.get("license_url")),
            "rights_metadata_verified": False,
            "source_license_reverification_required": True,
            "captured_at": clean_html(row.get("created_on")),
            "alt_text": title[:300],
            "query": query,
            "score": relevance_score(query, title, 80),
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "blockers": [
                "source_license_reverification_required",
                "subject_match_not_verified",
                "editor_approval_required",
            ],
        })
    return out


def dedupe_and_rank(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in sorted(items, key=lambda row: (-int(row.get("score") or 0), str(row.get("provider") or ""), str(row.get("direct_source_url") or ""))):
        key = clean_html(item.get("direct_source_url")).casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= MAX_CANDIDATES_PER_STORY:
            break
    return out


def published_stories() -> list[dict[str, Any]]:
    doc = load_json(ARCHIVE, {"stories": []})
    stories = doc.get("stories", [])
    if not isinstance(stories, list):
        raise CandidateError("story_archive stories must be an array")
    return [dict(row) for row in stories if isinstance(row, dict) and row.get("id")]


def approved_story_ids() -> set[str]:
    doc = load_json(VISUALS, {"stories": {}})
    stories = doc.get("stories", {})
    if not isinstance(stories, dict):
        raise CandidateError("story_visuals stories must be an object")
    return {str(key) for key, row in stories.items() if isinstance(row, dict)}


def validate_policy() -> None:
    policy = load_json(POLICY)
    if policy.get("publication_authority") != "NONE":
        raise CandidateError("photo candidate policy must have publication_authority NONE")
    principles = policy.get("principles") or {}
    required_true = (
        "real_photographs_only",
        "synthetic_images_forbidden",
        "generic_stock_substitution_forbidden",
        "candidate_only",
        "rights_cleared_does_not_imply_subject_match",
        "subject_match_required_before_promotion",
        "editor_approval_required_before_promotion",
        "openverse_original_source_reverification_required",
        "provider_failure_must_not_block_news_publication",
        "no_photo_is_better_than_false_relevance",
    )
    for key in required_true:
        if principles.get(key) is not True:
            raise CandidateError(f"unsafe photo candidate policy: {key}")
    if principles.get("automatic_story_assignment_allowed") is not False:
        raise CandidateError("automatic story assignment must remain disabled")


def batch_for(stories: list[dict[str, Any]], approved: set[str], cursor: int, limit: int) -> tuple[list[dict[str, Any]], int, int]:
    eligible = sorted(
        (row for row in stories if str(row.get("id")) not in approved),
        key=lambda row: str(row.get("id")),
    )
    total = len(eligible)
    if total == 0:
        return [], 0, 0
    start = cursor % total
    count = min(max(1, limit), total)
    selected = [eligible[(start + index) % total] for index in range(count)]
    return selected, (start + count) % total, total


def discover_story(story: dict[str, Any], timeout: int, previous: dict[str, Any] | None) -> dict[str, Any]:
    story_id = str(story.get("id"))
    queries = build_queries(story)
    candidates: list[dict[str, Any]] = []
    failures: set[str] = set()
    provider_successes = 0

    for query in queries:
        for provider, resolver in (
            ("wikimedia_commons", wikimedia_candidates),
            ("openverse", openverse_candidates),
        ):
            try:
                candidates.extend(resolver(query, timeout))
                provider_successes += 1
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                CandidateError,
                ValueError,
                json.JSONDecodeError,
            ):
                failures.add(provider)

    ranked = dedupe_and_rank(candidates)
    if provider_successes == 0 and isinstance(previous, dict):
        preserved = copy.deepcopy(previous)
        preserved["discovery_health"] = "STALE_PROVIDER_UNAVAILABLE"
        preserved["unavailable_providers"] = sorted(failures)
        return preserved

    return {
        "story_id": story_id,
        "headline": clean_html(story.get("headline")),
        "status": "CANDIDATES_READY" if ranked else ("PROVIDERS_UNAVAILABLE" if provider_successes == 0 else "NO_SAFE_CANDIDATE"),
        "search_queries": queries,
        "candidate_count": len(ranked),
        "candidates": ranked,
        "discovery_health": "OK" if not failures else "PARTIAL",
        "unavailable_providers": sorted(failures),
        "automatic_promotion": False,
        "publication_authority": "NONE",
        "publication_gate": "subject_match_plus_editor_approval_required",
    }


def enforce_candidate_contract(doc: dict[str, Any]) -> None:
    if doc.get("publication_authority") != "NONE":
        raise CandidateError("candidate registry gained publication authority")
    if doc.get("candidate_only") is not True or doc.get("automatic_promotion_forbidden") is not True:
        raise CandidateError("candidate registry is not fail-closed")
    for story_id, row in (doc.get("stories") or {}).items():
        if not isinstance(row, dict):
            raise CandidateError(f"{story_id}: invalid candidate row")
        if row.get("automatic_promotion") is not False or row.get("publication_authority") != "NONE":
            raise CandidateError(f"{story_id}: story candidate row gained authority")
        for candidate in row.get("candidates") or []:
            if candidate.get("kind") != "photograph" or candidate.get("synthetic") is not False:
                raise CandidateError(f"{story_id}: non-real-photo candidate")
            if candidate.get("subject_match") is not False or candidate.get("editor_approved") is not False:
                raise CandidateError(f"{story_id}: candidate inherited approval")
            if candidate.get("publication_eligible") is not False or candidate.get("publication_authority") != "NONE":
                raise CandidateError(f"{story_id}: candidate gained publication eligibility")
            if candidate.get("license") not in {"public-domain", "cc0", "cc-by", "cc-by-sa"}:
                raise CandidateError(f"{story_id}: disallowed candidate license")
            if candidate.get("provider") == "openverse" and candidate.get("source_license_reverification_required") is not True:
                raise CandidateError(f"{story_id}: Openverse candidate lacks source reverification gate")


def resolve(output: Path, max_stories: int, timeout: int) -> dict[str, Any]:
    validate_policy()
    previous = load_json(output, {
        "schema_version": "1.2",
        "cursor": 0,
        "stories": {},
    })
    previous_rows = previous.get("stories", {}) if isinstance(previous.get("stories"), dict) else {}
    approved = approved_story_ids()
    archive = published_stories()
    selected, next_cursor, eligible_count = batch_for(
        archive,
        approved,
        int(previous.get("cursor") or 0),
        max_stories,
    )

    rows = {
        str(key): copy.deepcopy(value)
        for key, value in previous_rows.items()
        if str(key) not in approved and isinstance(value, dict)
    }

    for story in selected:
        story_id = str(story.get("id"))
        rows[story_id] = discover_story(
            story,
            timeout,
            rows.get(story_id),
        )

    doc = {
        "schema_version": "1.2",
        "product": "VÂLCEA CLAR PHOTO CANDIDATE REGISTRY",
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_promotion_forbidden": True,
        "rights_cleared_does_not_imply_subject_match": True,
        "source_of_truth_for_approved_visuals": "valcea-clar/social/story_visuals.json",
        "approved_atlas": "valcea-clar/social/photo_atlas.json",
        "generated_at_utc": utc_now(),
        "cursor": next_cursor,
        "summary": {
            "published_story_count": len(archive),
            "approved_visual_story_count": len(approved),
            "eligible_story_count": eligible_count,
            "stories_checked_this_run": len(selected),
            "stories_with_candidates": sum(1 for row in rows.values() if row.get("candidate_count", 0) > 0),
            "candidate_count": sum(int(row.get("candidate_count") or 0) for row in rows.values()),
        },
        "stories": dict(sorted(rows.items())),
    }
    enforce_candidate_contract(doc)
    write_json(output, doc)
    print(json.dumps({
        "status": "PASS",
        "checked": len(selected),
        "eligible": eligible_count,
        "candidates": doc["summary"]["candidate_count"],
        "next_cursor": next_cursor,
    }, ensure_ascii=False))
    return doc


def self_test() -> None:
    assert canonical_license("CC BY-SA 4.0") == ("creative_commons", "cc-by-sa")
    assert canonical_license("CC BY 3.0") == ("creative_commons", "cc-by")
    assert canonical_license("CC BY-NC 4.0") is None
    assert canonical_license("CC BY-ND 4.0") is None
    assert canonical_license("Public domain") == ("public_domain", "public-domain")
    assert openverse_license("by-sa") == ("creative_commons", "cc-by-sa")
    assert openverse_license("by-nc") is None
    assert jpeg_like("https://example.test/a.JPG")
    assert not jpeg_like("https://example.test/a.png")

    stories = [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}]
    batch, cursor, total = batch_for(stories, {"b"}, 0, 2)
    assert [row["id"] for row in batch] == ["a", "c"]
    assert cursor == 2 and total == 3
    batch2, cursor2, _ = batch_for(stories, {"b"}, cursor, 2)
    assert [row["id"] for row in batch2] == ["d", "a"]
    assert cursor2 == 1

    ranked = dedupe_and_rank([
        {
            "provider": "openverse",
            "score": 80,
            "direct_source_url": "https://example.test/a.jpg",
            "kind": "photograph",
            "synthetic": False,
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "license": "cc-by",
            "source_license_reverification_required": True,
        },
        {
            "provider": "wikimedia_commons",
            "score": 120,
            "direct_source_url": "https://example.test/b.jpg",
            "kind": "photograph",
            "synthetic": False,
            "subject_match": False,
            "editor_approved": False,
            "publication_eligible": False,
            "publication_authority": "NONE",
            "license": "cc-by-sa",
            "source_license_reverification_required": False,
        },
    ])
    assert ranked[0]["provider"] == "wikimedia_commons"
    fixture = {
        "publication_authority": "NONE",
        "candidate_only": True,
        "automatic_promotion_forbidden": True,
        "stories": {
            "x": {
                "automatic_promotion": False,
                "publication_authority": "NONE",
                "candidates": ranked,
            }
        },
    }
    enforce_candidate_contract(fixture)

    broken = copy.deepcopy(fixture)
    broken["stories"]["x"]["candidates"][0]["subject_match"] = True
    try:
        enforce_candidate_contract(broken)
    except CandidateError:
        pass
    else:
        raise AssertionError("candidate subject match must never auto-promote")

    print("VÂLCEA CLAR Photo Candidate Resolver self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--max-stories", type=int, default=DEFAULT_BATCH)
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    resolve(args.output, max(1, args.max_stories), max(3, args.timeout))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
