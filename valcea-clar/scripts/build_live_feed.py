#!/usr/bin/env python3
"""Build the public live feed consumed by the autonomous frontpage bridge."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POINTER = ROOT / "site" / "current_edition.json"
PLACES = ROOT / "web" / "data" / "places.json"
OUT = ROOT / "site" / "runtime" / "live-feed.json"
PUBLISHABLE = {"auto_approved", "editor_approved"}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    pointer = load(POINTER)
    if pointer.get("status") not in PUBLISHABLE or pointer.get("publication_intent") != "publish":
        raise SystemExit("Refusing live feed: no publishable edition pointer")
    edition = load(ROOT / pointer["json_source"])
    if edition.get("edition_id") != pointer.get("edition_id"):
        raise SystemExit("Refusing live feed: pointer mismatch")
    places = load(PLACES).get("places", [])
    payload = {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "canonical_domain": "valceaclar.ro",
        "edition": edition,
        "pointer": pointer,
        "unde_iesim": [
            {
                "id": p.get("id"),
                "slug": p.get("slug"),
                "name": p.get("name"),
                "type": p.get("type"),
                "city": (p.get("location") or {}).get("city"),
                "summary": (p.get("editorial") or {}).get("dek") or (p.get("offer") or {}).get("summary"),
                "badges": p.get("badges", [])[:2],
            }
            for p in places[:8]
        ],
        "policy": {
            "verified_facts_only": True,
            "candidate_records_hidden": True,
            "paid_llm_api_required": False,
            "refresh_strategy": "consumer_can_poll_public_feed",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "edition_id": edition["edition_id"], "feed": str(OUT.relative_to(ROOT))}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
