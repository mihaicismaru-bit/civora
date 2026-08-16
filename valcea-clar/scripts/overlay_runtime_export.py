#!/usr/bin/env python3
"""Overlay the rendered live newsroom runtime into the deterministic site export."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
DIST = ROOT / "dist" / "chatgpt-sites"
MANIFEST = DIST / "manifest.json"
STORY_MANIFEST = RUNTIME / "stiri" / "manifest.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not (RUNTIME / "index.html").is_file():
        raise SystemExit("Refusing runtime overlay: frontpage was not rendered")
    if not MANIFEST.is_file():
        raise SystemExit("Refusing runtime overlay: base manifest missing")

    for source in sorted(RUNTIME.rglob("*")):
        if source.is_dir():
            continue
        target = DIST / source.relative_to(RUNTIME)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["schema_version"] = "1.5"
    manifest["target"]["autonomous_frontpage"] = True
    manifest["target"]["frontpage_source"] = "site/runtime/index.html"
    manifest["target"]["publication_model"] = "continuous_story_first"
    routes = manifest.setdefault("routes", [])
    routes = [
        route for route in routes
        if route.get("path") != "/" and not str(route.get("path", "")).startswith("/stiri/")
    ]
    routes.insert(0, {
        "path": "/",
        "source": "index.html",
        "title": "VÂLCEA CLAR — Redacția live",
        "update_mode": "replace_frontpage",
        "homepage_role": "primary_frontpage",
    })

    story_routes = []
    if STORY_MANIFEST.is_file():
        story_manifest = json.loads(STORY_MANIFEST.read_text(encoding="utf-8"))
        for story in story_manifest.get("stories", []):
            path = str(story.get("path") or "")
            story_id = str(story.get("id") or "")
            if not path.startswith("/stiri/") or not story_id:
                continue
            story_routes.append({
                "path": path,
                "source": path.strip("/") + "/index.html",
                "title": story_id,
                "update_mode": "upsert_story",
                "publication_unit": "individual_story",
                "canonical_url": story.get("canonical"),
            })
    routes[1:1] = story_routes
    manifest["routes"] = routes
    manifest.setdefault("counts", {})["routes"] = len(routes)
    manifest["counts"]["story_routes"] = len(story_routes)

    files = []
    for path in sorted(p for p in DIST.rglob("*") if p.is_file() and p != MANIFEST):
        files.append({
            "path": path.relative_to(DIST).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256(path),
        })
    manifest["files"] = files
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": "PASS",
        "publication_model": "continuous_story_first",
        "frontpage": "index.html",
        "story_routes": len(story_routes),
        "routes": len(routes),
        "files": len(files),
        "autonomous_frontpage": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
