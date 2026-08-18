#!/usr/bin/env python3
"""Discover real-photo candidates for VÂLCEA CLAR without weakening publication gates.

The resolver is deliberately candidate-first:
- it searches only free/open providers that work without a paid API;
- it records provenance and license metadata;
- it never marks a discovered image as subject-matched or editor-approved;
- it never changes story_visuals.json automatically;
- provider failures never block story/site/social processing.

An image becomes publishable only through the existing story_visuals.json approval
contract, where subject_match=true and editor_approved=true are still mandatory.
"""
from __future__ import annotations

import argparse
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
CURRENT = VC / "site" / "current_edition.json"
VISUALS = SOCIAL / "story_visuals.json"
POLICY = SOCIAL / "photo_source_policy.json"
CANDIDATES = SOCIAL / "story_visual_candidates.json"
REPLACEMENT_QUEUE = SOCIAL / "real_photo_replacement_queue.json"

WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"
OPENVERSE_API = "https://api.openverse.org/v1/images/"
HEADERS = {
    "User-Agent": "ValceaClarRealPhotoResolver/1.0 (+https://valceaclar.ro)",
    "Accept": "application/json",
}
MAX_RESULTS_PER_PROVIDER = 3
ROMANIAN_STOPWORDS = {
    "a", "ai", "ale", "al", "cu", "de", "din", "după", "fără", "în",
    "la", "lui", "o", "pe", "pentru", "prin", "și", "sau", "un", "unei", "unui",
    "vâlcea", "valcea", "clar",
}
KNOWN_LOCAL_PLACES = (
    "Râmnicu Vâlcea",
    "Ramnicu Valcea",
    "Băile Olănești",
    "Baile Olanesti",
    "Băile Govora",
    "Baile Govora",
    "Călimănești",
    "Calimanesti",
    "Brezoi",
    "Drăgășani",
    "Dragasani",
    "Horezu",
    "Voineasa",
    "Vaideeni",
    "Măciuca",
    "Maciuca",
    "Vâlcea",
    "Valcea",
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if not path.exists():
        if default is not None:
            return default
        raise RuntimeError(f"missing required file: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path} must contain a JSON object")
    return value


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


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
    """Return (rights_basis, canonical_license) for reusable licenses only."""
    normalized = " ".join(str(value or "").upper().replace("_", " ").split())
    if not normalized:
        return None
    if "NONCOMMERCIAL" in normalized or "NO DERIV" in normalized:
        return None
    if re.search(r"(^|[-\s])NC($|[-\s])", normalized):
        return None
    if re.search(r"(^|[-\s])ND($|[-\s])", normalized):
        return None
    if "PUBLIC DOMAIN" in normalized or normalized in {"PDM", "PD"}:
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
    mapping = {
        "cc0": ("public_domain", "cc0"),
        "pdm": ("public_domain", "public-domain"),
        "by": ("creative_commons", "cc-by"),
        "by-sa": ("creative_commons", "cc-by-sa"),
    }
    return mapping.get(normalized)


def jpeg_like(url: str, mime: str = "", filetype: str = "") -> bool:
    if str(mime or "").lower() == "image/jpeg":
        return True
    if str(filetype or "").lower().lstrip(".") in {"jpg", "jpeg"}:
        return True
    path = urllib.parse.urlparse(str(url or "")).path.lower()
    return path.endswith(".jpg") or path.endswith(".jpeg")


def http_json(url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers or HEADERS)
    with urllib.request.urlopen(request, timeout=25) as response:
        data = response.read(4_000_000)
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"provider returned non-object JSON: {url}")
    return value


def query_terms(value: str) -> list[str]:
    terms = [
        token.lower()
        for token in re.findall(r"[0-9A-Za-zĂÂÎȘȚăâîșț-]{3,}", value or "")
    ]
    return [term for term in terms if term not in ROMANIAN_STOPWORDS]


def relevance_score(query: str, title: str, provider_priority: int) -> int:
    q = set(query_terms(query))
    t = set(query_terms(title))
    overlap = len(q & t)
    exact = 1 if clean_html(query).lower() in clean_html(title).lower() else 0
    return provider_priority + min(overlap * 7, 35) + exact * 20


def build_queries(story: dict[str, Any]) -> list[str]:
    explicit = story.get("media_request")
    if isinstance(explicit, dict):
        subject = clean_html(explicit.get("subject"))
        if subject:
            return [subject]

    headline = clean_html(story.get("headline") or story.get("required_photo"))
    dek = clean_html(story.get("dek"))
    combined = f"{headline} {dek}"
    queries: list[str] = []

    informative = query_terms(headline)
    if informative:
        queries.append(" ".join(informative[:8]))

    lowered = combined.lower()
    for place in KNOWN_LOCAL_PLACES:
        if place.lower() in lowered and place not in queries:
            queries.append(place)
            break

    sources = story.get("sources")
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            name = clean_html(source.get("name"))
            if any(marker in name.lower() for marker in ("primăria", "primaria", "consili", "prefect", "spital", "teatru")):
                if name and name not in queries:
                    queries.append(name[:120])
                    break

    if not queries and headline:
        queries.append(headline[:120])
    return queries[:3]


def wikimedia_candidates(query: str, limit: int = MAX_RESULTS_PER_PROVIDER) -> list[dict[str, Any]]:
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrsearch": query,
        "gsrnamespace": "6",
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|mime|extmetadata",
        "iiextmetadatalanguage": "en",
        "iiextmetadatafilter": (
            "LicenseShortName|LicenseUrl|Artist|Credit|ImageDescription|"
            "DateTimeOriginal|UsageTerms"
        ),
    }
    url = WIKIMEDIA_API + "?" + urllib.parse.urlencode(params)
    payload = http_json(url)
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
        direct_url = clean_html(info.get("url"))
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
        description = metadata_value(ext, "ImageDescription") or title
        artist = metadata_value(ext, "Artist") or "Wikimedia Commons contributor"
        credit = metadata_value(ext, "Credit") or artist
        license_url = metadata_value(ext, "LicenseUrl")
        source_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            str(page.get("title") or "").replace(" ", "_"),
            safe=":/()_-",
        )
        out.append(
            {
                "provider": "wikimedia_commons",
                "provider_priority": 100,
                "kind": "photograph",
                "synthetic": False,
                "title": title,
                "photo_type": "CONTEXTUAL_CANDIDATE",
                "source_type": rights_basis,
                "source_url": source_url,
                "direct_source_url": direct_url,
                "credit": credit,
                "creator": artist,
                "rights_basis": rights_basis,
                "license": canonical,
                "license_label": raw_license,
                "license_url": license_url,
                "alt_text": clean_html(description)[:300] or title,
                "captured_at": metadata_value(ext, "DateTimeOriginal"),
                "rights_metadata_verified": bool(license_url or canonical == "public-domain"),
                "subject_match": False,
                "editor_approved": False,
                "publication_eligible": False,
                "blockers": [
                    "subject_match_not_verified",
                    "editor_approval_required",
                ],
                "query": query,
                "score": relevance_score(query, title, 100),
            }
        )
    return out


def openverse_candidates(query: str, limit: int = MAX_RESULTS_PER_PROVIDER) -> list[dict[str, Any]]:
    params = {"q": query, "page_size": str(limit)}
    url = OPENVERSE_API + "?" + urllib.parse.urlencode(params)
    payload = http_json(url)
    results = payload.get("results", [])
    if not isinstance(results, list):
        return []
    out: list[dict[str, Any]] = []
    for row in results:
        if not isinstance(row, dict):
            continue
        license_info = openverse_license(str(row.get("license") or ""))
        if not license_info:
            continue
        rights_basis, canonical = license_info
        direct_url = clean_html(row.get("url"))
        if not direct_url or not jpeg_like(
            direct_url,
            filetype=clean_html(row.get("filetype") or row.get("extension")),
        ):
            continue
        title = clean_html(row.get("title")) or "Openverse image"
        creator = clean_html(row.get("creator")) or "Openverse contributor"
        source_url = clean_html(row.get("foreign_landing_url") or row.get("detail_url"))
        license_url = clean_html(row.get("license_url"))
        out.append(
            {
                "provider": "openverse",
                "provider_priority": 80,
                "kind": "photograph",
                "synthetic": False,
                "title": title,
                "photo_type": "CONTEXTUAL_CANDIDATE",
                "source_type": rights_basis,
                "source_url": source_url,
                "direct_source_url": direct_url,
                "credit": creator,
                "creator": creator,
                "rights_basis": rights_basis,
                "license": canonical,
                "license_label": clean_html(row.get("license")) or canonical,
                "license_url": license_url,
                "alt_text": title[:300],
                "captured_at": clean_html(row.get("created_on")),
                "rights_metadata_verified": False,
                "subject_match": False,
                "editor_approved": False,
                "publication_eligible": False,
                "blockers": [
                    "source_license_must_be_verified_at_original_landing_page",
                    "subject_match_not_verified",
                    "editor_approval_required",
                ],
                "query": query,
                "score": relevance_score(query, title, 80),
            }
        )
    return out


def dedupe_and_rank(candidates: list[dict[str, Any]], max_items: int = 8) -> list[dict[str, Any]]:
    seen: set[str] = set()
    ranked: list[dict[str, Any]] = []
    for item in sorted(
        candidates,
        key=lambda row: (int(row.get("score") or 0), str(row.get("provider") or "")),
        reverse=True,
    ):
        key = clean_html(item.get("direct_source_url") or item.get("source_url")).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        item = dict(item)
        item.pop("provider_priority", None)
        ranked.append(item)
        if len(ranked) >= max_items:
            break
    return ranked


def current_stories() -> list[dict[str, Any]]:
    pointer = load_json(CURRENT)
    rel = clean_html(pointer.get("json_source"))
    if not rel:
        raise RuntimeError("current_edition.json lacks json_source")
    edition = load_json(VC / rel)
    items = edition.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("current edition items must be an array")
    return [dict(item) for item in items if isinstance(item, dict) and item.get("id")]


def queued_replacements() -> list[dict[str, Any]]:
    queue = load_json(REPLACEMENT_QUEUE, {"items": []})
    items = queue.get("items", [])
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("story_id"):
            continue
        out.append(
            {
                "id": str(item["story_id"]),
                "headline": clean_html(item.get("required_photo")),
                "required_photo": clean_html(item.get("required_photo")),
                "replacement_queue_status": clean_html(item.get("status")),
                "media_request": {"subject": clean_html(item.get("required_photo"))},
            }
        )
    return out


def existing_approved_story_ids() -> set[str]:
    doc = load_json(VISUALS, {"stories": {}})
    stories = doc.get("stories", {})
    if not isinstance(stories, dict):
        return set()
    return {str(key) for key, value in stories.items() if isinstance(value, dict)}


def material_payload(doc: dict[str, Any]) -> dict[str, Any]:
    copy = dict(doc)
    copy.pop("generated_at_utc", None)
    return copy


def discover_story(
    story: dict[str, Any],
    *,
    approved_ids: set[str],
    existing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    story_id = str(story.get("id") or story.get("story_id") or "").strip()
    headline = clean_html(story.get("headline") or story.get("required_photo"))
    queries = build_queries(story)
    all_candidates: list[dict[str, Any]] = []
    provider_failures: set[str] = set()
    provider_success = 0

    for query in queries:
        for provider, function in (
            ("wikimedia_commons", wikimedia_candidates),
            ("openverse", openverse_candidates),
        ):
            try:
                found = function(query)
                provider_success += 1
                all_candidates.extend(found)
            except (
                urllib.error.URLError,
                urllib.error.HTTPError,
                TimeoutError,
                RuntimeError,
                ValueError,
                json.JSONDecodeError,
            ):
                provider_failures.add(provider)

    ranked = dedupe_and_rank(all_candidates)
    if not ranked and provider_success == 0 and isinstance(existing, dict):
        preserved = dict(existing)
        preserved["discovery_health"] = "STALE_PROVIDER_UNAVAILABLE"
        return preserved

    return {
        "story_id": story_id,
        "headline": headline,
        "already_has_approved_visual": story_id in approved_ids,
        "status": (
            "APPROVED_VISUAL_ALREADY_PRESENT"
            if story_id in approved_ids
            else ("CANDIDATES_READY" if ranked else "NO_SAFE_CANDIDATE")
        ),
        "search_queries": queries,
        "candidate_count": len(ranked),
        "candidates": ranked,
        "discovery_health": "OK" if not provider_failures else "PARTIAL",
        "unavailable_providers": sorted(provider_failures),
        "automatic_promotion": False,
        "publication_gate": (
            "existing_story_visuals_contract"
            if story_id in approved_ids
            else "subject_match_and_editor_approval_required"
        ),
    }


def resolve(*, output: Path = CANDIDATES) -> dict[str, Any]:
    policy = load_json(POLICY)
    previous = load_json(output, {"stories": {}})
    previous_stories = previous.get("stories", {})
    if not isinstance(previous_stories, dict):
        previous_stories = {}

    approved_ids = existing_approved_story_ids()
    combined: dict[str, dict[str, Any]] = {}
    for story in current_stories() + queued_replacements():
        story_id = str(story.get("id") or story.get("story_id") or "").strip()
        if not story_id or story_id in combined:
            continue
        combined[story_id] = story

    stories: dict[str, Any] = {}
    for story_id, story in combined.items():
        previous_story = previous_stories.get(story_id)
        stories[story_id] = discover_story(
            story,
            approved_ids=approved_ids,
            existing=previous_story if isinstance(previous_story, dict) else None,
        )

    doc = {
        "schema_version": "1.0",
        "publication_model": "continuous_story_first",
        "policy_version": policy.get("schema_version", "1.0"),
        "candidate_only": True,
        "automatic_promotion_forbidden": True,
        "rights_cleared_does_not_imply_subject_match": True,
        "no_photo_is_better_than_false_relevance": True,
        "stories": stories,
    }

    if material_payload(previous) == material_payload(doc):
        print(f"REAL_PHOTO_RESOLVER_NO_CHANGE stories={len(stories)}")
        return previous

    doc["generated_at_utc"] = utc_now()
    write_json(output, doc)
    candidate_count = sum(
        int(value.get("candidate_count") or 0)
        for value in stories.values()
        if isinstance(value, dict)
    )
    print(
        f"REAL_PHOTO_RESOLVER_READY stories={len(stories)} "
        f"candidates={candidate_count} approved_existing={len(approved_ids)}"
    )
    return doc


def self_test() -> None:
    assert canonical_license("CC BY-SA 4.0") == ("creative_commons", "cc-by-sa")
    assert canonical_license("CC BY 3.0") == ("creative_commons", "cc-by")
    assert canonical_license("CC BY-NC 4.0") is None
    assert canonical_license("CC BY-ND 4.0") is None
    assert canonical_license("Public domain") == ("public_domain", "public-domain")
    assert openverse_license("by-sa") == ("creative_commons", "cc-by-sa")
    assert openverse_license("by-nc") is None
    assert clean_html("<b>Ion &amp; Ana</b>") == "Ion & Ana"
    assert jpeg_like("https://example.invalid/photo.JPG")
    assert jpeg_like("https://example.invalid/file", mime="image/jpeg")
    assert not jpeg_like("https://example.invalid/photo.png", mime="image/png")
    assert relevance_score("Primaria Ramnicu Valcea", "Primaria Ramnicu Valcea", 100) > 100

    sample = {
        "headline": "Lucrări la pod în Râmnicu Vâlcea",
        "dek": "Intervenția este în municipiu.",
    }
    queries = build_queries(sample)
    assert queries
    assert any("Râmnicu Vâlcea" == query for query in queries)

    ranked = dedupe_and_rank(
        [
            {
                "provider": "openverse",
                "provider_priority": 80,
                "score": 90,
                "direct_source_url": "https://x.invalid/a.jpg",
                "subject_match": False,
                "editor_approved": False,
                "publication_eligible": False,
            },
            {
                "provider": "wikimedia_commons",
                "provider_priority": 100,
                "score": 120,
                "direct_source_url": "https://x.invalid/b.jpg",
                "subject_match": False,
                "editor_approved": False,
                "publication_eligible": False,
            },
        ]
    )
    assert ranked[0]["provider"] == "wikimedia_commons"
    assert all(item["publication_eligible"] is False for item in ranked)
    assert all(item["subject_match"] is False for item in ranked)
    assert all(item["editor_approved"] is False for item in ranked)
    print("REAL_PHOTO_RESOLVER_SELF_TEST PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CANDIDATES)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    resolve(output=args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
