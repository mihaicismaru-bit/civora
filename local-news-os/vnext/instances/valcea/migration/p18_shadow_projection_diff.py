#!/usr/bin/env python3
"""P18 public projection parity for the isolated VÂLCEA CLAR vNext shadow DB."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve()
REPO_ROOT = HERE.parents[5]
VNEXT = REPO_ROOT / "local-news-os" / "vnext"
CORE = VNEXT / "core"
MIGRATION_DIR = HERE.parent
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(MIGRATION_DIR))

from public_route_compat import RouteCompatiblePublicApp  # noqa: E402
from p18_shadow_migration import run_shadow  # noqa: E402

INSTANCE_ID = "valcea"
PACK_PATH = VNEXT / "instances" / INSTANCE_ID / "packs" / "publication.json"
EVENT_PATH = REPO_ROOT / "valcea-clar" / "site" / "story_publication_event.json"
FEED_PATH = REPO_ROOT / "valcea-clar" / "site" / "runtime" / "live-feed.json"
PEOPLE_PATH = REPO_ROOT / "valcea-clar" / "site" / "runtime" / "people.json"
ARTISTS_PATH = REPO_ROOT / "valcea-clar" / "site" / "runtime" / "artists.json"
PLACES_PATH = REPO_ROOT / "valcea-clar" / "data" / "places.json"


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _call(app, path: str) -> tuple[str, dict[str, str], str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status
        captured["headers"] = dict(headers)

    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": ""}
    body = b"".join(app(environ, start_response)).decode("utf-8", errors="replace")
    return str(captured.get("status") or ""), dict(captured.get("headers") or {}), body


def _ok(status: str) -> bool:
    return status.startswith("200")


def run_projection_diff(db: Path) -> dict[str, Any]:
    shadow = run_shadow(db)
    if shadow.get("status") != "SHADOW_MIGRATION_PASS":
        raise RuntimeError("shadow migration must pass before public projection diff")

    pack = _load(PACK_PATH)
    event = _load(EVENT_PATH)
    feed = _load(FEED_PATH)
    people = _load(PEOPLE_PATH)
    artists = _load(ARTISTS_PATH)
    places = _load(PLACES_PATH)
    app = RouteCompatiblePublicApp(db_path=db, instance_id=INSTANCE_ID, publication_pack=pack)

    story_by_id = {str(item["id"]): item for item in feed.get("stories") or []}
    expected_story_ids = [str(v) for v in event.get("story_ids") or []]
    expected_story_paths = {
        sid: str((event.get("canonical_urls") or {})[sid]).split("valceaclar.ro", 1)[-1]
        for sid in expected_story_ids
    }

    root_status, _, root_body = _call(app, "/")
    story_failures: list[dict[str, str]] = []
    for sid in expected_story_ids:
        path = expected_story_paths[sid]
        status, _, body = _call(app, path)
        story = story_by_id[sid]
        if not _ok(status) or str(story.get("headline") or "") not in body or str(story.get("dek") or "") not in body:
            story_failures.append({"story_id": sid, "path": path, "status": status})

    people_failures: list[dict[str, str]] = []
    for profile in people.get("profiles") or []:
        if profile.get("publication_status") != "public":
            continue
        path = str(profile.get("path") or "")
        status, _, body = _call(app, path)
        canonical = f"https://valceaclar.ro{path}"
        if not _ok(status) or str(profile.get("name") or "") not in body or canonical not in body:
            people_failures.append({"id": str(profile.get("id")), "path": path, "status": status})

    artist_failures: list[dict[str, str]] = []
    for profile in artists.get("profiles") or []:
        if profile.get("publication_status") != "public":
            continue
        path = str(profile.get("path") or "")
        status, _, body = _call(app, path)
        canonical = f"https://valceaclar.ro{path}"
        if not _ok(status) or str(profile.get("name") or "") not in body or canonical not in body:
            artist_failures.append({"id": str(profile.get("id")), "path": path, "status": status})

    leisure_status, _, leisure_body = _call(app, "/unde-iesim/")
    expected_public_places = [
        item for item in places.get("places") or []
        if item.get("publication_status") == "public" and item.get("verification_level") == "verified"
    ]
    missing_place_names = [str(item.get("name")) for item in expected_public_places if str(item.get("name")) not in leisure_body]

    sitemap_status, _, sitemap = _call(app, "/sitemap.xml")
    sitemap_required = ["https://valceaclar.ro/"]
    sitemap_required += [str((event.get("canonical_urls") or {})[sid]) for sid in expected_story_ids]
    sitemap_required += [f"https://valceaclar.ro{p['path']}" for p in people.get("profiles") or [] if p.get("publication_status") == "public"]
    sitemap_required += [f"https://valceaclar.ro{p['path']}" for p in artists.get("profiles") or [] if p.get("publication_status") == "public"]
    sitemap_required.append("https://valceaclar.ro/unde-iesim/")
    missing_sitemap_urls = [url for url in sitemap_required if url not in sitemap]

    checks = {
        "shadow_migration_pass": True,
        "homepage_200": _ok(root_status),
        "homepage_contains_all_legacy_story_links": all(path in root_body for path in expected_story_paths.values()),
        "all_legacy_story_routes_200_with_content": not story_failures,
        "all_people_routes_preserved": not people_failures,
        "all_artist_routes_preserved": not artist_failures,
        "leisure_route_200": _ok(leisure_status),
        "leisure_verified_places_projected": not missing_place_names,
        "sitemap_200": _ok(sitemap_status),
        "sitemap_preserves_required_public_urls": not missing_sitemap_urls,
        "network_publication_attempted": False,
        "public_runtime_mutated": False,
    }
    passed = all(value is True for key, value in checks.items() if key not in {"network_publication_attempted", "public_runtime_mutated"}) and not checks["network_publication_attempted"] and not checks["public_runtime_mutated"]
    return {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_VNEXT_VALCEA_P18_SHADOW_PROJECTION_DIFF_V1",
        "status": "SHADOW_PROJECTION_PASS" if passed else "SHADOW_PROJECTION_FAIL",
        "production_cutover": False,
        "checks": checks,
        "counts": {
            "stories_checked": len(expected_story_ids),
            "people_checked": sum(1 for p in people.get("profiles") or [] if p.get("publication_status") == "public"),
            "artists_checked": sum(1 for p in artists.get("profiles") or [] if p.get("publication_status") == "public"),
            "verified_places_checked": len(expected_public_places),
            "sitemap_required_urls": len(sitemap_required),
        },
        "failures": {
            "stories": story_failures,
            "people": people_failures,
            "artists": artist_failures[:20],
            "artists_failure_count": len(artist_failures),
            "missing_place_names": missing_place_names,
            "missing_sitemap_urls": missing_sitemap_urls[:50],
            "missing_sitemap_url_count": len(missing_sitemap_urls),
        },
        "next_gate": "CONTROLLED_LIVE_DEPLOYMENT_PREFLIGHT" if passed else "REPAIR_PUBLIC_PROJECTION",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db")
    parser.add_argument("--report")
    args = parser.parse_args()
    if args.db:
        db = Path(args.db)
        db.parent.mkdir(parents=True, exist_ok=True)
        result = run_projection_diff(db)
    else:
        with tempfile.TemporaryDirectory() as td:
            result = run_projection_diff(Path(td) / "valcea-projection-shadow.sqlite3")
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        out = Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if result["status"] == "SHADOW_PROJECTION_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
