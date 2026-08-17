#!/usr/bin/env python3
"""Overlay the rendered live newsroom runtime into the deterministic site export."""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import build_legal_pages

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
CORE = REPO / "local-news-os" / "core"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from indexing_assets import write_indexing_assets  # noqa: E402

RUNTIME = ROOT / "site" / "runtime"
DIST = ROOT / "dist" / "chatgpt-sites"
MANIFEST = DIST / "manifest.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"
INDEXING_CONTRACT = ROOT / "site" / "indexing_routes.json"
LEGAL_PATHS = {"/termeni/", "/confidentialitate/"}
BASE_URL = "https://valceaclar.ro"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def materialize_static_runtime_routes() -> list[str]:
    """Materialize independent static products before final sitemap validation.

    Legal pages are rendered directly into runtime by build_legal_pages. Other
    configured static products are built first in DIST by build_sites_export and
    copied into runtime here. This makes runtime a complete publication snapshot
    before indexing finalization and removes the story-render/static-export race.
    """
    materialized: list[str] = []
    for route in configured_static_routes():
        if route in LEGAL_PATHS:
            target = route_index(RUNTIME, route)
            if target.is_file():
                materialized.append(route)
            continue
        source = route_index(DIST, route)
        if not source.is_file():
            continue
        target = route_index(RUNTIME, route)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        materialized.append(route)
    return materialized


def main() -> int:
    if not (RUNTIME / "index.html").is_file():
        raise SystemExit("Refusing runtime overlay: frontpage was not rendered")
    if not MANIFEST.is_file():
        raise SystemExit("Refusing runtime overlay: base manifest missing")

    legal_report = build_legal_pages.build()
    static_materialized = materialize_static_runtime_routes()

    for source in sorted(RUNTIME.rglob("*")):
        if source.is_dir():
            continue
        target = DIST / source.relative_to(RUNTIME)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.6"
    manifest["target"]["autonomous_frontpage"] = True
    manifest["target"]["frontpage_source"] = "site/runtime/index.html"
    manifest["target"]["publication_model"] = "continuous_story_first"
    manifest["target"]["public_legal_pages"] = True
    routes = manifest.setdefault("routes", [])
    routes = [
        route for route in routes
        if route.get("path") != "/"
        and route.get("path") not in LEGAL_PATHS
        and not str(route.get("path", "")).startswith("/stiri/")
    ]
    routes.insert(0, {
        "path": "/",
        "source": "index.html",
        "title": "VÂLCEA CLAR — Redacția live",
        "update_mode": "replace_frontpage",
        "homepage_role": "primary_frontpage",
    })

    legal_routes = [
        {
            "path": "/termeni/",
            "source": "termeni/index.html",
            "title": "Termeni și condiții — VÂLCEA CLAR",
            "update_mode": "replace_legal_page",
            "publication_unit": "legal_page",
            "canonical_url": "https://valceaclar.ro/termeni/",
        },
        {
            "path": "/confidentialitate/",
            "source": "confidentialitate/index.html",
            "title": "Politica de confidențialitate — VÂLCEA CLAR",
            "update_mode": "replace_legal_page",
            "publication_unit": "legal_page",
            "canonical_url": "https://valceaclar.ro/confidentialitate/",
        },
    ]

    story_routes = []
    story_paths: list[str] = []
    if STORY_MANIFEST.is_file():
        story_manifest = json.loads(STORY_MANIFEST.read_text(encoding="utf-8"))
        for story in story_manifest.get("stories", []):
            path = str(story.get("path") or "")
            story_id = str(story.get("id") or "")
            if not path.startswith("/stiri/") or not story_id:
                continue
            story_paths.append(path)
            story_routes.append({
                "path": path,
                "source": path.strip("/") + "/index.html",
                "title": story_id,
                "update_mode": "upsert_story",
                "publication_unit": "individual_story",
                "canonical_url": story.get("canonical"),
            })
    routes[1:1] = legal_routes + story_routes
    manifest["routes"] = routes
    manifest.setdefault("counts", {})["routes"] = len(routes)
    manifest["counts"]["story_routes"] = len(story_routes)
    manifest["counts"]["legal_routes"] = len(legal_routes)
    manifest["legal_pages"] = {
        "source": "site/legal/legal_pages.json",
        "effective_date": "2026-08-16",
        "contact": "redactie@valceaclar.ro",
        "routes": [route["path"] for route in legal_routes],
        "build_status": legal_report.get("status"),
    }

    # Finalize indexing only after all independently built static products have
    # been materialized into the same runtime snapshot as the story pages.
    indexing = write_indexing_assets(RUNTIME, BASE_URL, ["/"] + story_paths)
    if indexing.get("status") != "PASS":
        raise RuntimeError(f"refusing export with deferred indexing: {indexing}")
    for filename in ("robots.txt", "sitemap.xml"):
        source = RUNTIME / filename
        target = DIST / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    files = []
    for path in sorted(p for p in DIST.rglob("*") if p.is_file() and p != MANIFEST):
        files.append({
            "path": path.relative_to(DIST).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    manifest["files"] = files
    manifest["indexing"] = {
        "status": indexing.get("status"),
        "route_count": indexing.get("route_count"),
        "configured_static_routes": indexing.get("configured_static_routes"),
        "finalized_after_static_materialization": True,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "frontpage": "index.html",
        "story_routes": len(story_routes),
        "legal_routes": len(legal_routes),
        "routes": len(routes),
        "files": len(files),
        "autonomous_frontpage": True,
        "static_routes_materialized": static_materialized,
        "indexing_status": indexing.get("status"),
        "indexing_routes": indexing.get("route_count"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
