#!/usr/bin/env python3
"""Remote HTTP acceptance probe for the GitHub-first VÂLCEA CLAR site.

CIVORA owns editorial truth. ``mihaicismaru-bit/valcea-clar`` owns the public
projection and GitHub Pages deployment. Acceptance therefore verifies three
independent surfaces and requires them to agree:

1. the canonical CIVORA live feed;
2. the public repository projection (state + ordered articles);
3. the documents actually served from https://valceaclar.ro.

The probe intentionally does not depend on legacy ChatGPT Sites markers, legacy
route inventory, or the raw CIVORA feed order. The public presentation contract
is freshness-first and is recorded by the public projection itself.
"""
from __future__ import annotations

import argparse
import json
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = "https://valceaclar.ro"
EDITORIAL_FEED_URL = (
    "https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/"
    "valcea-clar/site/runtime/live-feed.json"
)
PUBLIC_STATE_URL = (
    "https://raw.githubusercontent.com/mihaicismaru-bit/valcea-clar/main/"
    "sync/civora_state.json"
)
PUBLIC_ARTICLES_URL = (
    "https://raw.githubusercontent.com/mihaicismaru-bit/valcea-clar/main/"
    "content/articles.json"
)
REVALIDATION_TRIGGER = ROOT / "site" / "http_revalidation_trigger.json"
USER_AGENT = "VALCEA-CLAR-Public-Health/2.0 (+https://valceaclar.ro/)"
ARTIST_UI_MARKERS = (
    "/artisti/",
    "artistProfiles",
    "artistLinkedText",
    "data-artist-intelligence",
    "Artiști și creatori din acest material",
    "vc-artistlinks",
    "vc-artist-inline",
)


def fetch(url: str, timeout: int = 20) -> tuple[int | None, str, str | None]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(3_000_000).decode("utf-8", errors="replace")
            return int(response.status), body, None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), body, f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


def fetch_json(url: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    status, body, error = fetch(url)
    check: dict[str, Any] = {
        "path": url,
        "url": url,
        "http_status": status,
        "ok": False,
        "missing_markers": [],
        "forbidden_markers": [],
        "canonical_ok": True,
        "error": error,
    }
    if status != 200:
        return None, check
    try:
        payload = json.loads(body)
    except Exception as exc:
        check["error"] = f"invalid_json: {exc}"
        return None, check
    if not isinstance(payload, dict):
        check["error"] = "invalid_json: top-level object required"
        return None, check
    check["ok"] = True
    return payload, check


def canonical_present(html: str, canonical: str) -> bool:
    return any(
        value in html
        for value in (
            f'href="{canonical}"',
            f"href='{canonical}'",
            f'content="{canonical}"',
            f"content='{canonical}'",
        )
    )


def story_link_sequence(html: str) -> list[str]:
    return re.findall(r'href=["\'](/stiri/[a-z0-9-]+/)["\']', html)


def story_links(html: str) -> set[str]:
    return set(story_link_sequence(html))


def homepage_hero_story_path(html: str) -> str:
    hero = re.search(
        r'<article\s+class=["\'][^"\']*\bhero\b[^"\']*["\'][^>]*>(.*?)</article>',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not hero:
        return ""
    match = re.search(r'href=["\'](/stiri/[a-z0-9-]+/)["\']', hero.group(1))
    return match.group(1) if match else ""


def artist_ui_present(html: str) -> bool:
    return any(marker in html for marker in ARTIST_UI_MARKERS)


def required_revalidation_story_id() -> str:
    if not REVALIDATION_TRIGGER.is_file():
        return ""
    try:
        trigger = json.loads(REVALIDATION_TRIGGER.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if trigger.get("require_current_live_feed") is not True:
        return ""
    return str(trigger.get("expected_story_id") or "").strip()


def _editorial_contract() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    feed, check = fetch_json(EDITORIAL_FEED_URL)
    check["path"] = "__canonical_editorial_feed__"
    if feed is None:
        return None, check

    stories = [row for row in (feed.get("stories") or []) if isinstance(row, dict)]
    ids = [str(row.get("id") or "") for row in stories]
    paths = [str(row.get("path") or "") for row in stories]
    publication_ok = feed.get("publication_model") == "continuous_story_first"
    count_ok = bool(stories) and int(feed.get("story_count") or 0) == len(stories)
    unique_ok = len(ids) == len(set(ids)) and all(ids)
    path_ok = all(path == f"/stiri/{story_id}/" for story_id, path in zip(ids, paths))
    required_id = required_revalidation_story_id()
    required_ok = not required_id or required_id in ids

    missing: list[str] = []
    if not publication_ok:
        missing.append("publication_model=continuous_story_first")
    if not count_ok:
        missing.append("story_count_matches_stories")
    if not unique_ok:
        missing.append("unique_story_ids")
    if not path_ok:
        missing.append("canonical_story_paths")
    if not required_ok:
        missing.append(f"required_story={required_id}")

    check.update(
        {
            "ok": not missing,
            "missing_markers": missing,
            "feed_generated_at": feed.get("generated_at"),
            "feed_story_count": len(stories),
            "artist_profile_story_count": sum(1 for row in stories if row.get("artist_profiles")),
            "required_story_id": required_id or None,
            "required_story_present": required_ok,
        }
    )
    return feed, check


def _public_projection_contract(
    feed: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], dict[str, Any]]:
    state, state_fetch = fetch_json(PUBLIC_STATE_URL)
    articles_doc, articles_fetch = fetch_json(PUBLIC_ARTICLES_URL)
    check: dict[str, Any] = {
        "path": "__public_projection__",
        "url": PUBLIC_STATE_URL,
        "http_status": state_fetch.get("http_status"),
        "ok": False,
        "missing_markers": [],
        "forbidden_markers": [],
        "canonical_ok": True,
        "error": state_fetch.get("error") or articles_fetch.get("error"),
        "articles_url": PUBLIC_ARTICLES_URL,
        "articles_http_status": articles_fetch.get("http_status"),
    }
    if state is None or articles_doc is None:
        return state, [], check

    articles = [row for row in (articles_doc.get("articles") or []) if isinstance(row, dict)]
    public_ids = [str(row.get("id") or "") for row in articles]
    public_paths = [f"/stiri/{story_id}/" for story_id in public_ids if story_id]
    feed_rows = [row for row in ((feed or {}).get("stories") or []) if isinstance(row, dict)]
    feed_ids = [str(row.get("id") or "") for row in feed_rows]

    ownership = state.get("ownership") or {}
    missing: list[str] = []
    if state.get("publication_model") != "continuous_story_first":
        missing.append("state_publication_model")
    if state.get("presentation_order") != "freshness_first_then_source_priority":
        missing.append("freshness_first_presentation_order")
    if ownership.get("editorial_engine") != "mihaicismaru-bit/civora":
        missing.append("editorial_engine=civora")
    if ownership.get("public_projection") != "mihaicismaru-bit/valcea-clar":
        missing.append("public_projection=valcea-clar")
    if ownership.get("hosting") != "GitHub Pages":
        missing.append("hosting=GitHub Pages")
    if articles_doc.get("canonical_source") != EDITORIAL_FEED_URL:
        missing.append("articles_canonical_source")
    if articles_doc.get("presentation_order") != "freshness_first_then_source_priority":
        missing.append("articles_presentation_order")
    if int(state.get("story_count") or 0) != len(articles) or not articles:
        missing.append("state_story_count_matches_articles")
    if not public_ids or state.get("lead_story_id") != public_ids[0]:
        missing.append("state_lead_matches_public_order")
    if len(public_ids) != len(set(public_ids)) or not all(public_ids):
        missing.append("unique_public_story_ids")
    if feed is not None:
        if state.get("source_generated_at") != feed.get("generated_at"):
            missing.append("projection_generated_at_matches_editorial_feed")
        if articles_doc.get("updated_local") != feed.get("generated_at"):
            missing.append("articles_updated_at_matches_editorial_feed")
        if set(public_ids) != set(feed_ids):
            missing.append("public_story_ids_match_editorial_feed")

    required_id = required_revalidation_story_id()
    if required_id and required_id not in public_ids:
        missing.append(f"public_required_story={required_id}")

    check.update(
        {
            "ok": not missing,
            "missing_markers": missing,
            "source_generated_at": state.get("source_generated_at"),
            "public_story_count": len(articles),
            "public_lead_story_id": state.get("lead_story_id"),
            "public_lead_story_path": public_paths[0] if public_paths else None,
            "verified_visual_count": state.get("verified_visual_count"),
        }
    )
    return state, articles, check


def evaluate(base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    checks: list[dict[str, Any]] = []

    feed, feed_check = _editorial_contract()
    checks.append(feed_check)
    state, public_articles, projection_check = _public_projection_contract(feed)
    checks.append(projection_check)

    expected_paths = [f"/stiri/{row['id']}/" for row in public_articles if row.get("id")]
    expected_lead_path = expected_paths[0] if expected_paths else ""
    expected_story_count = len(expected_paths)
    raw_rows = {
        str(row.get("id") or ""): row
        for row in ((feed or {}).get("stories") or [])
        if isinstance(row, dict) and row.get("id")
    }

    status, homepage, error = fetch(base + "/")
    found_links = story_links(homepage)
    hero_path = homepage_hero_story_path(homepage)
    expected_set = set(expected_paths)
    projection_ids_ok = found_links == expected_set
    lead_ok = bool(expected_lead_path) and hero_path == expected_lead_path
    home_missing = [marker for marker in ("VÂLCEA CLAR", "Ediție continuă") if marker not in homepage]
    if not lead_ok:
        home_missing.append(f"homepage_hero={expected_lead_path or 'missing_public_lead'}")
    if not projection_ids_ok:
        home_missing.append(f"homepage_story_set={expected_story_count}")
    home_canonical_ok = canonical_present(homepage, base + "/")
    checks.append(
        {
            "path": "/",
            "url": base + "/",
            "http_status": status,
            "ok": status == 200 and not home_missing and home_canonical_ok,
            "missing_markers": home_missing,
            "forbidden_markers": [],
            "canonical_ok": home_canonical_ok,
            "error": error,
            "homepage_hero_story_path": hero_path or None,
            "expected_lead_story_path": expected_lead_path or None,
            "visible_unique_story_count": len(found_links),
            "expected_story_count": expected_story_count,
            "homepage_story_set_matches_projection": projection_ids_ok,
        }
    )

    def check(
        path: str,
        required: list[str],
        canonical: str | None = None,
        forbidden: list[str] | None = None,
        require_artist_ui: bool = False,
    ) -> None:
        url = base + path
        code, body, fetch_error = fetch(url)
        missing = [marker for marker in required if marker not in body]
        artist_ok = True
        if require_artist_ui and not artist_ui_present(body):
            artist_ok = False
            missing.append("artist_profile_ui_projection")
        forbidden_found = [marker for marker in (forbidden or []) if marker in body]
        canonical_ok = True if canonical is None else canonical_present(body, canonical)
        checks.append(
            {
                "path": path,
                "url": url,
                "http_status": code,
                "ok": code == 200 and not missing and not forbidden_found and canonical_ok and artist_ok,
                "missing_markers": missing,
                "forbidden_markers": forbidden_found,
                "canonical_ok": canonical_ok,
                "artist_ui_required": require_artist_ui,
                "artist_ui_ok": artist_ok,
                "error": fetch_error,
            }
        )

    check("/robots.txt", ["Sitemap:", "valceaclar.ro/sitemap.xml"])
    check("/sitemap.xml", ["<urlset", "valceaclar.ro"])
    check(
        "/stiri/",
        ["Ultimele știri", "Flux editorial"],
        canonical="https://valceaclar.ro/stiri/",
    )
    check(
        "/despre/",
        ["Principiul editorial", "Publicare continuă", "VÂLCEA CLAR"],
        canonical="https://valceaclar.ro/despre/",
    )
    check(
        "/termeni/",
        ["Termeni și condiții", "redactie@valceaclar.ro"],
        canonical="https://valceaclar.ro/termeni/",
        forbidden=["noindex"],
    )
    check(
        "/confidentialitate/",
        ["Politica de confidențialitate", "redactie@valceaclar.ro"],
        canonical="https://valceaclar.ro/confidentialitate/",
        forbidden=["noindex"],
    )

    route_rows = list(public_articles[:5])
    required_id = required_revalidation_story_id()
    if required_id and all(str(row.get("id") or "") != required_id for row in route_rows):
        required_row = next((row for row in public_articles if str(row.get("id") or "") == required_id), None)
        if required_row is not None:
            route_rows.append(required_row)
        else:
            route_rows.append({"id": required_id, "headline": ""})

    if route_rows:
        for row in route_rows:
            story_id = str(row.get("id") or "")
            if not story_id:
                continue
            path = f"/stiri/{story_id}/"
            canonical = f"https://valceaclar.ro{path}"
            editorial_row = raw_rows.get(story_id) or {}
            required = ["VÂLCEA CLAR"]
            headline = str(row.get("headline") or "").strip()
            if headline:
                required.append(headline)
            check(
                path,
                required,
                canonical=canonical,
                require_artist_ui=bool(editorial_row.get("artist_profiles")),
            )
    else:
        checks.append(
            {
                "path": "/stiri/<story-id>/",
                "url": None,
                "http_status": None,
                "ok": False,
                "missing_markers": ["public_projection_story"],
                "forbidden_markers": [],
                "canonical_ok": False,
                "artist_ui_required": False,
                "artist_ui_ok": True,
                "error": "No public projection stories available",
            }
        )

    blockers = [item["path"] for item in checks if not item["ok"]]
    return {
        "schema_version": "2.0",
        "product": "VÂLCEA CLAR public HTTP acceptance",
        "base_url": base,
        "status": "READY" if not blockers else "BLOCKED",
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "publication_model": "continuous_story_first",
        "presentation_order": (state or {}).get("presentation_order"),
        "expected_story_count": expected_story_count,
        "expected_lead_story_id": (state or {}).get("lead_story_id"),
        "required_revalidation_story_id": required_revalidation_story_id() or None,
        "homepage_collapse_guard": True,
        "homepage_freshness_guard": True,
        "public_projection_agreement_required": True,
        "artist_profile_ui_guard": True,
        "repository_is_not_publication_proof": True,
    }


def self_test() -> None:
    assert canonical_present(
        '<link rel="canonical" href="https://valceaclar.ro/termeni/">',
        "https://valceaclar.ro/termeni/",
    )
    assert not canonical_present(
        '<link rel="canonical" href="https://example.com/">',
        "https://valceaclar.ro/termeni/",
    )
    sample = (
        '<article class="hero"><h1><a href="/stiri/lead-story/">Lead</a></h1></article>'
        '<a href="/stiri/other-story/">Other</a>'
    )
    assert story_links(sample) == {"/stiri/lead-story/", "/stiri/other-story/"}
    assert homepage_hero_story_path(sample) == "/stiri/lead-story/"
    assert homepage_hero_story_path('<a href="/stiri/no-hero/">x</a>') == ""
    assert artist_ui_present('<a class="vc-artist-inline" href="/artisti/analia-selis/">Analia Selis</a>')
    assert not artist_ui_present('<p>Analia Selis</p>')
    print("VÂLCEA CLAR public-site probe self-test: PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=DEFAULT_BASE)
    parser.add_argument("--output", default="/tmp/valcea-clar-public-health.json")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    result = evaluate(args.base_url)
    Path(args.output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.require_ready and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
