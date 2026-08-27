#!/usr/bin/env python3
"""Finalize the canonical VÂLCEA CLAR runtime after newsroom rendering.

Reader-facing presentation, legal/static route materialization and indexing are
owned here so publication workflows do not need a second presentation writer.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import build_legal_pages
import render_news_index

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CORE = REPO / "local-news-os" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from indexing_assets import write_indexing_assets  # noqa: E402

RUNTIME = ROOT / "site" / "runtime"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
INDEXING_CONTRACT = ROOT / "site" / "indexing_routes.json"
LEGAL_PATHS = {"/termeni/", "/confidentialitate/", "/corectii/"}
BASE_URL = "https://valceaclar.ro"


def run_script(script: str, *args: str) -> None:
    """Run one canonical reader-presentation stage fail-closed."""
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *args],
        cwd=REPO,
        check=True,
        timeout=180,
    )


def apply_reader_presentation() -> None:
    """Fold post-render presentation writers into the canonical runtime."""
    run_script("render_rich_story_sections.py")
    run_script("gambling_story_presentation.py")

    stages = (
        "public_ux_currentness.py",
        "public_ux_story_integrity.py",
        "public_ux_manifest.py",
    )
    for script in stages:
        run_script(script)
    for script in stages:
        run_script(script, "--check")

    run_script("public_ux_legal.py")

    if (RUNTIME / "people.json").is_file():
        run_script("link_person_profiles.py")
    if (RUNTIME / "artists.json").is_file():
        run_script("link_artist_profiles.py")


def route_index(root: Path, route: str) -> Path:
    if route == "/":
        return root / "index.html"
    return root / route.strip("/") / "index.html"


def configured_static_routes() -> list[str]:
    if not INDEXING_CONTRACT.is_file():
        return []
    doc = json.loads(INDEXING_CONTRACT.read_text(encoding="utf-8"))
    routes = doc.get("routes")
    if not isinstance(routes, list):
        raise RuntimeError("indexing route contract requires routes list")
    return [str(route) for route in routes]


def restore_committed_runtime_route(target: Path) -> bool:
    """Restore a committed static runtime product erased by a dynamic renderer."""
    try:
        relative = target.relative_to(REPO).as_posix()
    except ValueError:
        return False
    proc = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=REPO,
        capture_output=True,
        check=False,
        timeout=20,
    )
    if proc.returncode != 0 or not proc.stdout:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(proc.stdout)
    return True


def materialize_static_runtime_routes() -> list[str]:
    """Materialize independent static products before final sitemap validation."""
    materialized: list[str] = []
    for route in configured_static_routes():
        target = route_index(RUNTIME, route)
        if route in LEGAL_PATHS:
            if target.is_file():
                materialized.append(route)
            continue
        if target.is_file() or restore_committed_runtime_route(target):
            materialized.append(route)
    return materialized


def story_paths() -> list[str]:
    if not STORY_MANIFEST.is_file():
        return []
    doc = json.loads(STORY_MANIFEST.read_text(encoding="utf-8"))
    paths: list[str] = []
    for story in doc.get("stories", []):
        path = str(story.get("path") or "")
        if path.startswith("/stiri/"):
            paths.append(path)
    return paths


def main() -> int:
    if not (RUNTIME / "index.html").is_file():
        raise SystemExit("Refusing runtime finalization: frontpage was not rendered")
    if not (RUNTIME / "live-feed.json").is_file():
        raise SystemExit("Refusing runtime finalization: canonical live feed missing")

    news_index_report = render_news_index.build()
    legal_report = build_legal_pages.build()
    static_materialized = materialize_static_runtime_routes()
    apply_reader_presentation()

    routes = ["/"] + story_paths()
    indexing = write_indexing_assets(RUNTIME, BASE_URL, routes)
    if indexing.get("status") != "PASS":
        raise RuntimeError(f"refusing runtime with deferred indexing: {indexing}")

    print(json.dumps({
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "runtime": "site/runtime",
        "news_index_stories": news_index_report.get("story_count"),
        "legal_status": legal_report.get("status"),
        "static_routes_materialized": static_materialized,
        "indexing_status": indexing.get("status"),
        "indexing_routes": indexing.get("route_count"),
        "reader_presentation_owner": "overlay_runtime_export",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
