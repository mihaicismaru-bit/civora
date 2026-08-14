#!/usr/bin/env python3
"""Create a deterministic synchronization payload for the existing ChatGPT Site."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EDITORIAL = ROOT / "editorial"
DIST = ROOT / "dist" / "chatgpt-sites"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def main() -> int:
    places_doc = json.loads((WEB / "data" / "places.json").read_text(encoding="utf-8"))
    creators_doc = json.loads((WEB / "data" / "creators.json").read_text(encoding="utf-8"))
    meta = json.loads((WEB / "data" / "meta.json").read_text(encoding="utf-8"))

    if any(place.get("publication_status") != "public" for place in places_doc.get("places", [])):
        raise SystemExit("Refusing export: non-public place detected in public projection")
    if len(places_doc.get("places", [])) != meta.get("place_count"):
        raise SystemExit("Refusing export: place count mismatch")
    if len(creators_doc.get("creators", [])) != meta.get("creator_count"):
        raise SystemExit("Refusing export: creator count mismatch")

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "unde-iesim" / "data").mkdir(parents=True, exist_ok=True)
    (DIST / "editorial").mkdir(parents=True, exist_ok=True)

    for filename in ("index.html", "styles.css", "app.js"):
        copy_file(WEB / filename, DIST / "unde-iesim" / filename)
    for filename in ("places.json", "creators.json", "meta.json"):
        copy_file(WEB / "data" / filename, DIST / "unde-iesim" / "data" / filename)
    for article in sorted(EDITORIAL.glob("*.md")):
        copy_file(article, DIST / "editorial" / article.name)

    routes = [
        {
            "path": "/unde-iesim/",
            "source": "unde-iesim/index.html",
            "title": "Unde ieșim — VÂLCEA CLAR",
            "update_mode": "upsert_by_path",
        },
        {
            "path": "/unde-iesim/metodologie/",
            "source": "unde-iesim/index.html#transparenta",
            "title": "Cum verificăm — VÂLCEA CLAR",
            "update_mode": "upsert_by_path",
        },
    ]
    for place in places_doc.get("places", []):
        routes.append(
            {
                "path": f"/unde-iesim/local/{place['slug']}/",
                "record_id": place["id"],
                "title": place["name"],
                "update_mode": "upsert_by_slug",
            }
        )
        story = place.get("editorial", {}).get("story_path")
        if story:
            routes.append(
                {
                    "path": f"/unde-iesim/nou-deschis/{place['slug']}/",
                    "source": story,
                    "record_id": place["id"],
                    "title": place["name"],
                    "update_mode": "upsert_by_slug",
                }
            )

    files = []
    for path in sorted(p for p in DIST.rglob("*") if p.is_file()):
        files.append(
            {
                "path": path.relative_to(DIST).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256(path),
            }
        )

    manifest = {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR — Unde ieșim",
        "target": {
            "canonical_domain": "valceaclar.ro",
            "platform": "ChatGPT Sites",
            "create_parallel_site": False,
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_generated_at": meta.get("generated_at"),
        "counts": {
            "public_places": len(places_doc.get("places", [])),
            "public_creators": len(creators_doc.get("creators", [])),
            "hidden_candidates": meta.get("candidate_count", 0),
            "routes": len(routes),
        },
        "policy": {
            "candidate_records_are_hidden": True,
            "material_facts_autopublish": False,
            "sponsored_rankings": False,
        },
        "routes": routes,
        "files": files,
    }
    (DIST / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    # Recompute file list once the manifest exists, but do not self-hash the manifest.
    print(
        f"ChatGPT Sites export: PASS ({manifest['counts']['public_places']} places, "
        f"{manifest['counts']['routes']} routes, {len(files)} payload files)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
