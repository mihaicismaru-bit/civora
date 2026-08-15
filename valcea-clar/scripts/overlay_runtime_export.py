#!/usr/bin/env python3
"""Overlay the rendered frontpage into the deterministic site export."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "site" / "runtime"
DIST = ROOT / "dist" / "chatgpt-sites"
MANIFEST = DIST / "manifest.json"


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
    manifest["schema_version"] = "1.4"
    manifest["target"]["autonomous_frontpage"] = True
    manifest["target"]["frontpage_source"] = "site/runtime/index.html"
    routes = manifest.setdefault("routes", [])
    routes = [route for route in routes if route.get("path") != "/"]
    routes.insert(0, {
        "path": "/",
        "source": "index.html",
        "title": "VÂLCEA CLAR — Ediția curentă",
        "update_mode": "replace_frontpage",
        "homepage_role": "primary_frontpage",
    })
    manifest["routes"] = routes
    manifest.setdefault("counts", {})["routes"] = len(routes)
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
        "frontpage": "index.html",
        "routes": len(routes),
        "files": len(files),
        "autonomous_frontpage": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
