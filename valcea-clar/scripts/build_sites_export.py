#!/usr/bin/env python3
"""Create a deterministic synchronization payload for the existing VÂLCEA CLAR site."""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
EDITORIAL = ROOT / "editorial"
EDITIONS = ROOT / "editions"
SITE = ROOT / "site"
OPS = ROOT / "ops"
DIST = ROOT / "dist" / "chatgpt-sites"
POINTER = SITE / "current_edition.json"
PUBLISHABLE_STATUSES = {"editor_approved", "auto_approved"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _load_edition(edition_id: str) -> tuple[dict, Path]:
    json_path = EDITIONS / f"{edition_id}.json"
    md_path = EDITIONS / f"{edition_id}.md"
    if not json_path.is_file() or not md_path.is_file():
        raise SystemExit(f"Refusing export: edition files missing for {edition_id}")
    edition = json.loads(json_path.read_text(encoding="utf-8"))
    if edition.get("status") not in PUBLISHABLE_STATUSES or edition.get("publication_intent") != "publish":
        raise SystemExit(f"Refusing export: edition {edition_id} is not publishable")
    if edition.get("edition_id") != edition_id:
        raise SystemExit("Refusing export: edition id mismatch")
    return edition, md_path


def latest_publishable_edition() -> tuple[dict | None, Path | None]:
    candidates = []
    for path in EDITIONS.glob("*.json"):
        try:
            edition = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if edition.get("status") not in PUBLISHABLE_STATUSES or edition.get("publication_intent") != "publish":
            continue
        updated = str(edition.get("updated_local") or "")
        if not updated:
            continue
        md_path = EDITIONS / f"{edition.get('edition_id')}.md"
        if not md_path.is_file():
            continue
        candidates.append((updated, edition, md_path))
    if not candidates:
        return None, None
    candidates.sort(key=lambda row: row[0], reverse=True)
    return candidates[0][1], candidates[0][2]


def load_current_edition(integration: dict) -> tuple[dict | None, Path | None, dict]:
    config = integration.get("current_edition", {})
    if not config.get("enabled"):
        return None, None, {}

    if POINTER.is_file():
        pointer = json.loads(POINTER.read_text(encoding="utf-8"))
        if pointer.get("publication_intent") == "publish" and pointer.get("status") in PUBLISHABLE_STATUSES:
            edition, md_path = _load_edition(str(pointer["edition_id"]))
            return edition, md_path, pointer

    if config.get("selection_mode") == "latest_publishable":
        edition, md_path = latest_publishable_edition()
        if edition is None:
            return None, None, {}
        slot = edition.get("slot") or ("morning" if str(edition.get("edition_id", "")).endswith("-morning") else "evening")
        slot_paths = config.get("slot_paths", {})
        pointer = {
            "edition_id": edition["edition_id"],
            "slot": slot,
            "status": edition["status"],
            "publication_intent": edition["publication_intent"],
            "updated_local": edition.get("updated_local"),
            "path": slot_paths.get(slot) or config.get("path") or "/editia-curenta/",
            "homepage_role": "primary_lead",
        }
        return edition, md_path, pointer

    legacy_id = str(config.get("edition_id", "")).strip()
    if legacy_id:
        edition, md_path = _load_edition(legacy_id)
        return edition, md_path, {"edition_id": legacy_id, "path": config.get("path", "/editia-curenta/")}
    return None, None, {}


def main() -> int:
    places_doc = json.loads((WEB / "data" / "places.json").read_text(encoding="utf-8"))
    creators_doc = json.loads((WEB / "data" / "creators.json").read_text(encoding="utf-8"))
    meta = json.loads((WEB / "data" / "meta.json").read_text(encoding="utf-8"))
    integration = json.loads((SITE / "integration.json").read_text(encoding="utf-8"))
    current_edition, current_edition_md, current_pointer = load_current_edition(integration)

    if any(place.get("publication_status") != "public" for place in places_doc.get("places", [])):
        raise SystemExit("Refusing export: non-public place detected in public projection")
    if len(places_doc.get("places", [])) != meta.get("place_count"):
        raise SystemExit("Refusing export: place count mismatch")
    if len(creators_doc.get("creators", [])) != meta.get("creator_count"):
        raise SystemExit("Refusing export: creator count mismatch")
    if integration.get("canonical_domain") != "valceaclar.ro":
        raise SystemExit("Refusing export: incorrect canonical domain")
    if integration.get("section", {}).get("path") != "/unde-iesim/":
        raise SystemExit("Refusing export: incorrect section route")
    if integration.get("publication_policy", {}).get("material_facts_autopublish") is not False:
        raise SystemExit("Refusing export: unsafe site integration policy")

    if DIST.exists():
        shutil.rmtree(DIST)
    (DIST / "unde-iesim" / "data").mkdir(parents=True, exist_ok=True)
    (DIST / "editorial").mkdir(parents=True, exist_ok=True)
    (DIST / "editions").mkdir(parents=True, exist_ok=True)
    (DIST / "site").mkdir(parents=True, exist_ok=True)

    for filename in ("index.html", "styles.css", "app.js"):
        copy_file(WEB / filename, DIST / "unde-iesim" / filename)
    for filename in ("places.json", "creators.json", "meta.json"):
        copy_file(WEB / "data" / filename, DIST / "unde-iesim" / "data" / filename)
    for article in sorted(EDITORIAL.glob("*.md")):
        copy_file(article, DIST / "editorial" / article.name)
    for edition_file in sorted(EDITIONS.glob("*.md")) + sorted(EDITIONS.glob("*.json")):
        copy_file(edition_file, DIST / "editions" / edition_file.name)
    copy_file(SITE / "integration.json", DIST / "site" / "integration.json")
    if POINTER.is_file():
        copy_file(POINTER, DIST / "site" / "current-edition-pointer.json")

    public_places = places_doc.get("places", [])
    max_items = int(integration.get("homepage_module", {}).get("max_items", 4))
    homepage_items = []
    for place in public_places[:max_items]:
        homepage_items.append({
            "id": place["id"],
            "name": place["name"],
            "path": f"/unde-iesim/local/{place['slug']}/",
            "type": place.get("type"),
            "location": place.get("location", {}).get("city"),
            "badges": place.get("badges", [])[:2],
            "summary": place.get("editorial", {}).get("dek") or place.get("offer", {}).get("summary"),
            "last_verified_at": place.get("last_verified_at"),
        })
    (DIST / "site" / "homepage-module.json").write_text(
        json.dumps({"schema_version": "1.0", "module": integration["homepage_module"], "items": homepage_items}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    current_path = None
    if current_edition is not None and current_edition_md is not None:
        current_path = current_pointer.get("path") or integration["current_edition"].get("path") or "/editia-curenta/"
        current_payload = {
            "schema_version": "2.0",
            "module": integration["current_edition"],
            "pointer": current_pointer,
            "edition": {
                "edition_id": current_edition["edition_id"],
                "slot": current_edition.get("slot"),
                "generator": current_edition.get("generator", "human_editorial"),
                "title": current_edition.get("title"),
                "date": current_edition.get("edition_date"),
                "updated_local": current_edition.get("updated_local"),
                "path": current_path,
                "source": f"editions/{current_edition_md.name}",
                "items": current_edition.get("items", []),
            },
        }
        (DIST / "site" / "current-edition.json").write_text(
            json.dumps(current_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    reconciliation_path = OPS / "ingest_reconciliation.json"
    reconciliation_summary = {}
    if reconciliation_path.is_file():
        reconciliation_summary = json.loads(reconciliation_path.read_text(encoding="utf-8")).get("summary", {})

    routes = [
        {"path": "/unde-iesim/", "source": "unde-iesim/index.html", "title": "Unde ieșim — VÂLCEA CLAR", "update_mode": "upsert_by_path"},
        {"path": "/unde-iesim/metodologie/", "source": "unde-iesim/index.html#transparenta", "title": "Cum verificăm — VÂLCEA CLAR", "update_mode": "upsert_by_path"},
    ]
    if current_edition is not None and current_edition_md is not None and current_path:
        routes.insert(0, {
            "path": current_path,
            "source": f"editions/{current_edition_md.name}",
            "record_id": current_edition["edition_id"],
            "title": current_edition.get("title", "VÂLCEA CLAR — Ediția curentă"),
            "update_mode": "upsert_by_path",
            "homepage_role": "primary_lead",
        })
        if current_path != "/editia-curenta/":
            routes.insert(1, {
                "path": "/editia-curenta/",
                "source": f"editions/{current_edition_md.name}",
                "record_id": current_edition["edition_id"],
                "title": current_edition.get("title", "VÂLCEA CLAR — Ediția curentă"),
                "update_mode": "upsert_by_path",
                "homepage_role": "alias",
            })
    for place in public_places:
        routes.append({
            "path": f"/unde-iesim/local/{place['slug']}/", "record_id": place["id"], "title": place["name"], "update_mode": "upsert_by_slug"
        })
        story = place.get("editorial", {}).get("story_path")
        if story:
            routes.append({
                "path": f"/unde-iesim/nou-deschis/{place['slug']}/", "source": story, "record_id": place["id"], "title": place["name"], "update_mode": "upsert_by_slug"
            })

    files = []
    for path in sorted(p for p in DIST.rglob("*") if p.is_file()):
        files.append({"path": path.relative_to(DIST).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})

    manifest = {
        "schema_version": "1.3",
        "product": "VÂLCEA CLAR",
        "target": {"canonical_domain": "valceaclar.ro", "platform": "ChatGPT Sites", "create_parallel_site": False},
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "data_generated_at": meta.get("generated_at"),
        "current_edition_id": current_edition.get("edition_id") if current_edition else None,
        "current_edition_generator": current_edition.get("generator") if current_edition else None,
        "counts": {
            "public_places": len(public_places),
            "public_creators": len(creators_doc.get("creators", [])),
            "hidden_candidates": meta.get("candidate_count", 0),
            "ingest_review_queue": reconciliation_summary.get("review_queue", 0),
            "routes": len(routes),
        },
        "policy": {"candidate_records_are_hidden": True, "material_facts_autopublish": False, "sponsored_rankings": False},
        "site_integration": integration,
        "routes": routes,
        "files": files,
    }
    (DIST / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"VÂLCEA CLAR site export: PASS ({manifest['counts']['public_places']} places, {manifest['counts']['routes']} routes, "
        f"current edition={manifest['current_edition_id']}, generator={manifest['current_edition_generator']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
