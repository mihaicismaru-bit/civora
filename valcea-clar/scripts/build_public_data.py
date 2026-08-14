#!/usr/bin/env python3
"""Build a public, fail-closed projection from canonical VÂLCEA CLAR data."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = ROOT / "web" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def dump(name: str, payload: dict) -> None:
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")


sources_doc = load("sources.json")
places_doc = load("places.json")
creators_doc = load("creators.json")
sources = {s["id"]: s for s in sources_doc["sources"]}

public_places = []
for place in places_doc["places"]:
    if place.get("publication_status") != "public":
        continue
    projected = dict(place)
    projected["sources"] = [
        {
            "id": sid,
            "name": sources[sid]["name"],
            "publisher": sources[sid]["publisher"],
            "url": sources[sid]["url"],
            "kind": sources[sid]["kind"],
            "last_checked_at": sources[sid]["last_checked_at"],
        }
        for sid in place.get("source_ids", [])
        if sid in sources and sources[sid].get("status") == "active"
    ]
    public_places.append(projected)

public_places.sort(key=lambda item: (item.get("featured_order", 999), item["name"]))
public_creators = [c for c in creators_doc.get("creators", []) if c.get("publication_status") == "public"]

meta = {
    "product": "VÂLCEA CLAR — Unde ieșim",
    "generated_at": places_doc["generated_at"],
    "place_count": len(public_places),
    "creator_count": len(public_creators),
    "candidate_count": sum(1 for p in places_doc["places"] if p.get("publication_status") == "candidate"),
    "policy": {
        "prices_expire_after_days": 120,
        "candidate_records_are_hidden": True,
        "sponsored_rankings": False,
    },
}

dump("places.json", {"generated_at": places_doc["generated_at"], "places": public_places})
dump("creators.json", {"generated_at": creators_doc["generated_at"], "creators": public_creators})
dump("meta.json", meta)
print(f"Built public projection: {len(public_places)} places, {len(public_creators)} creators.")
