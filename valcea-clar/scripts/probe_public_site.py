#!/usr/bin/env python3
"""Remote HTTP acceptance probe for the public VÂLCEA CLAR presentation layer.

CIVORA owns newsroom state and publication. The public site is accepted only if
critical routes are reachable and the homepage can project the durable
continuous-story feed rather than collapsing to a recap snapshot.
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
USER_AGENT = "VALCEA-CLAR-Public-Health/1.1 (+https://valceaclar.ro/)"
BRIDGE_MARKERS = (
    "chatgpt-sites-live-bridge",
    "data-valcea-clar-live",
    "raw.githubusercontent.com/mihaicismaru-bit/civora/main/valcea-clar/site/runtime/live-feed.json",
    "vc-runtime",
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


def story_contracts(limit: int = 5) -> list[tuple[str, str]]:
    manifest_path = ROOT / "site" / "runtime" / "stiri" / "manifest.json"
    if not manifest_path.is_file():
        return []
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows: list[tuple[str, str]] = []
    for row in manifest.get("stories") or []:
        path = str(row.get("path") or "")
        canonical = str(row.get("canonical") or "")
        if path.startswith("/stiri/") and path.endswith("/") and canonical == f"https://valceaclar.ro{path}":
            rows.append((path, canonical))
        if len(rows) >= limit:
            break
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
    details["feed_story_count"] = len(paths)
    details["feed_story_paths"] = paths[:10]
    details["publication_model"] = feed.get("publication_model")
    details["ok"] = bool(publication_ok and count_ok)
    if not publication_ok:
        details["missing_markers"].append("publication_model=continuous_story_first")
    if not count_ok:
        details["missing_markers"].append(f"at_least_{minimum}_durable_stories")
    return feed, details


def evaluate(base_url: str) -> dict[str, Any]:
    base = base_url.rstrip("/")
    checks: list[dict[str, Any]] = []
    contracts = story_contracts()
    expected_paths = [path for path, _canonical in contracts]

    feed, feed_check = remote_feed_contract()
    checks.append(feed_check)
    remote_paths = {
        str(row.get("path") or "")
        for row in ((feed or {}).get("stories") or [])
        if isinstance(row, dict)
    }

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

    def check(path: str, required: list[str], canonical: str | None = None, forbidden: list[str] | None = None) -> None:
        url = base + path
        code, body, fetch_error = fetch(url)
        missing = [marker for marker in required if marker not in body]
        forbidden_found = [marker for marker in (forbidden or []) if marker in body]
        canonical_ok = True if canonical is None else canonical_present(body, canonical)
        checks.append({
            "path": path,
            "url": url,
            "http_status": code,
            "ok": code == 200 and not missing and not forbidden_found and canonical_ok,
            "missing_markers": missing,
            "forbidden_markers": forbidden_found,
            "canonical_ok": canonical_ok,
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
            check(path, ["VÂLCEA CLAR"], canonical=canonical)
    else:
        checks.append({
            "path": "/stiri/<story-id>/",
            "url": None,
            "http_status": None,
            "ok": False,
            "missing_markers": ["canonical_story_manifest_entry"],
            "forbidden_markers": [],
            "canonical_ok": False,
            "error": "No canonical story route available in repository manifest",
        })

    blockers = [item["path"] for item in checks if not item["ok"]]
    return {
        "schema_version": "1.2",
        "product": "VÂLCEA CLAR public HTTP acceptance",
        "base_url": base,
        "status": "READY" if not blockers else "BLOCKED",
        "ready": not blockers,
        "checks": checks,
        "blockers": blockers,
        "publication_model": "continuous_story_first",
        "expected_story_count": len(expected_paths),
        "homepage_collapse_guard": True,
        "repository_is_not_publication_proof": True,
    }


def self_test() -> None:
    assert canonical_present('<link rel="canonical" href="https://valceaclar.ro/termeni/">', "https://valceaclar.ro/termeni/")
    assert not canonical_present('<link rel="canonical" href="https://example.com/">', "https://valceaclar.ro/termeni/")
    assert story_links('<a href="/stiri/a/"></a><a href="/stiri/b/"></a>') == {"/stiri/a/", "/stiri/b/"}
    assert bridge_present('<script src="/chatgpt-sites-live-bridge.js"></script>')
    contracts = story_contracts()
    assert contracts
    assert all(path.startswith("/stiri/") and canonical == f"https://valceaclar.ro{path}" for path, canonical in contracts)
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
