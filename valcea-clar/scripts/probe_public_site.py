#!/usr/bin/env python3
"""Remote HTTP acceptance probe for the public VÂLCEA CLAR presentation layer.

CIVORA owns newsroom state and publication. The public site is accepted only if
critical routes are reachable and the homepage can project the durable
continuous-story feed rather than collapsing to a recap snapshot.

When an explicit HTTP revalidation trigger names a story, that exact story must
be present in the canonical feed and its public route must pass HTTP/canonical
checks. This prevents a stale but otherwise healthy site from reporting READY.

When a live-feed story carries verified ``artist_profiles``, its public story
route must also expose the Artist Intelligence UI contract. Repository data is
not sufficient publication proof.
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
FEED_URL = "https://raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json"
REVALIDATION_TRIGGER = ROOT / "site" / "http_revalidation_trigger.json"
USER_AGENT = "VALCEA-CLAR-Public-Health/1.3 (+https://valceaclar.ro/)"
BRIDGE_MARKERS = (
    "chatgpt-sites-live-bridge",
    "data-valcea-clar-live",
    "raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json",
    "vc-runtime",
)
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
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(2_000_000).decode("utf-8", errors="replace")
            return int(response.status), body, None
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read(200_000).decode("utf-8", errors="replace")
        except Exception:
            body = ""
        return int(exc.code), body, f"HTTP {exc.code}"
    except Exception as exc:
        return None, "", f"{type(exc).__name__}: {exc}"


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


def story_links(html: str) -> set[str]:
    return set(re.findall(r'href=["\'](/stiri/[a-z0-9-]+/)["\']', html))


def bridge_present(html: str) -> bool:
    return any(marker in html for marker in BRIDGE_MARKERS)


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


def story_contracts(limit: int = 5) -> list[tuple[str, str]]:
    manifest_path = ROOT / "site" / "runtime" / "stiri" / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    valid: list[tuple[str, str, str]] = []
    for row in manifest.get("stories") or []:
        story_id = str(row.get("id") or "")
        path = str(row.get("path") or "")
        canonical = str(row.get("canonical") or "")
        if story_id and path.startswith("/stiri/") and path.endswith("/") and canonical == f"https://valceaclar.ro{path}":
            valid.append((story_id, path, canonical))

    rows = [(path, canonical) for _story_id, path, canonical in valid[:limit]]
    expected_id = required_revalidation_story_id()
    if expected_id:
        expected = next((row for row in valid if row[0] == expected_id), None)
        if expected is None:
            # Preserve a deliberately impossible contract so acceptance fails
            # instead of silently ignoring a requested publication.
            expected_path = f"/stiri/{expected_id}/"
            expected_contract = (expected_path, f"https://valceaclar.ro{expected_path}")
        else:
            expected_contract = (expected[1], expected[2])
        if expected_contract not in rows:
            rows.append(expected_contract)
    return rows


def remote_feed_contract() -> tuple[dict[str, Any] | None, dict[str, Any]]:
    status, body, error = fetch(FEED_URL)
    details: dict[str, Any] = {
        "path": "__canonical_live_feed__",
        "url": FEED_URL,
        "http_status": status,
        "ok": False,
        "missing_markers": [],
        "forbidden_markers": [],
        "canonical_ok": True,
        "error": error,
    }
    if status != 200:
        return None, details
    try:
        feed = json.loads(body)
    except Exception as exc:
        details["error"] = f"invalid_json: {exc}"
        return None, details
    stories = feed.get("stories") if isinstance(feed, dict) else None
    paths = [str(row.get("path") or "") for row in (stories or []) if isinstance(row, dict)]
    minimum = min(3, len(story_contracts()))
    publication_ok = feed.get("publication_model") == "continuous_story_first"
    count_ok = len(paths) >= minimum and int(feed.get("story_count") or 0) == len(paths)
    expected_id = required_revalidation_story_id()
    expected_path = f"/stiri/{expected_id}/" if expected_id else ""
    expected_ok = not expected_path or expected_path in paths
    artist_story_count = sum(1 for row in (stories or []) if isinstance(row, dict) and row.get("artist_profiles"))
    details["feed_story_count"] = len(paths)
    details["artist_profile_story_count"] = artist_story_count
    details["feed_story_paths"] = paths[:10]
    details["publication_model"] = feed.get("publication_model")
    details["required_story_id"] = expected_id or None
    details["required_story_present"] = expected_ok
    details["ok"] = bool(publication_ok and count_ok and expected_ok)
    if not publication_ok:
        details["missing_markers"].append("publication_model=continuous_story_first")
    if not count_ok:
        details["missing_markers"].append(f"at_least_{minimum}_durable_stories")
    if not expected_ok:
        details["missing_markers"].append(f"required_story={expected_id}")
    return feed, details


def evaluate(base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    checks: list[dict[str, Any]] = []
    contracts = story_contracts()
    expected_paths = [path for path, _canonical in contracts]

    feed, feed_check = remote_feed_contract()
    checks.append(feed_check)
    remote_rows = {
        str(row.get("path") or ""): row
        for row in ((feed or {}).get("stories") or [])
        if isinstance(row, dict)
    }
    remote_paths = set(remote_rows)

    status, homepage, error = fetch(base + "/")
    found_links = story_links(homepage)
    bridge = bridge_present(homepage)
    minimum = min(3, len(expected_paths))
    static_projection_ok = len(found_links.intersection(expected_paths)) >= minimum
    bridge_projection_ok = bridge and feed_check["ok"] and all(path in remote_paths for path in expected_paths)
    projection_ok = static_projection_ok or bridge_projection_ok
    home_missing = [marker for marker in ("VÂLCEA CLAR", "ACTUALIZAT LIVE") if marker not in homepage]
    if not projection_ok:
        home_missing.append("continuous_story_projection")
    checks.append({
        "path": "/",
        "url": base + "/",
        "http_status": status,
        "ok": status == 200 and not home_missing and projection_ok,
        "missing_markers": home_missing,
        "forbidden_markers": [],
        "canonical_ok": True,
        "error": error,
        "expected_story_paths": expected_paths,
        "story_links_found": sorted(found_links),
        "minimum_story_projection": minimum,
        "static_story_projection_ok": static_projection_ok,
        "live_bridge_detected": bridge,
        "live_bridge_projection_ok": bridge_projection_ok,
    })

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
        checks.append({
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
        })

    check("/robots.txt", ["Sitemap:", "valceaclar.ro/sitemap.xml"])
    check("/sitemap.xml", ["<urlset", "valceaclar.ro"])
    check(
        "/stiri/",
        ["Știrile Vâlcii, puse în ordine.", 'data-nav-contract="valcea-clar-primary-v2"'],
        canonical="https://valceaclar.ro/stiri/",
    )
    check(
        "/despre/",
        ["Clar înainte de rapid.", "VÂLCEA CLAR"],
        canonical="https://valceaclar.ro/despre/",
    )
    check(
        "/termeni/",
        ["Termeni și condiții", "redactie@valceaclar.ro", 'name="robots" content="index,follow"'],
        canonical="https://valceaclar.ro/termeni/",
        forbidden=["noindex"],
    )
    check(
        "/confidentialitate/",
        ["Politica de confidențialitate", "redactie@valceaclar.ro", 'name="robots" content="index,follow"'],
        canonical="https://valceaclar.ro/confidentialitate/",
        forbidden=["noindex"],
    )
    check("/unde-iesim/", ["Unde ieșim"])

    if contracts:
        for path, canonical in contracts:
            row = remote_rows.get(path) or {}
            required = ["VÂLCEA CLAR"]
            if path == f"/stiri/{required_revalidation_story_id()}/":
                required.append("Accident mortal în Buila–Vânturarița")
            check(
                path,
                required,
                canonical=canonical,
                require_artist_ui=bool(row.get("artist_profiles")),
            )
    else:
        checks.append({
            "path": "/stiri/<story-id>/",
            "url": None,
            "http_status": None,
            "ok": False,
            "missing_markers": ["canonical_story_manifest_entry"],
            "forbidden_markers": [],
            "canonical_ok": False,
            "artist_ui_required": False,
            "artist_ui_ok": True,
            "error": "No canonical story route available in repository manifest",
        })

    blockers = [item["path"] for item in checks if not item["ok"]]
    return {
        "schema_version": "1.4",
        "product": "VÂLCEA CLAR public HTTP acceptance",
        "base_url": base,
        "status": "READY" if not blockers else "BLOCKED",
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "publication_model": "continuous_story_first",
        "expected_story_count": len(expected_paths),
        "required_revalidation_story_id": required_revalidation_story_id() or None,
        "homepage_collapse_guard": True,
        "artist_profile_ui_guard": True,
        "repository_is_not_publication_proof": True,
    }


def self_test() -> None:
    assert canonical_present('<link rel="canonical" href="https://valceaclar.ro/termeni/">', "https://valceaclar.ro/termeni/")
    assert not canonical_present('<link rel="canonical" href="https://example.com/">', "https://valceaclar.ro/termeni/")
    assert story_links('<a href="/stiri/a/"></a><a href="/stiri/b/"></a>') == {"/stiri/a/", "/stiri/b/"}
    assert bridge_present('<script src="/chatgpt-sites-live-bridge.js"></script>')
    assert artist_ui_present('<a class="vc-artist-inline" href="/artisti/analia-selis/">Analia Selis</a>')
    assert not artist_ui_present('<p>Analia Selis</p>')
    contracts = story_contracts()
    assert contracts
    assert all(path.startswith("/stiri/") and canonical == f"https://valceaclar.ro{path}" for path, canonical in contracts)
    expected = required_revalidation_story_id()
    if expected:
        assert f"/stiri/{expected}/" in {path for path, _canonical in contracts}
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
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if args.require_ready and not result["ready"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
