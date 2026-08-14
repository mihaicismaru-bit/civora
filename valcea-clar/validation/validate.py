#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "valcea-clar"
REGISTRY = BASE / "ingest" / "source_registry.json"
SEEDS = BASE / "ingest" / "seed_catalog.json"
STATE = BASE / "ingest" / "state" / "venues.json"
WEB = BASE / "web" / "unde-iesim.json"
PUBLISHER = BASE / "ingest" / "wordpress_draft_publish.py"
REPORT = BASE / "validation" / "latest_report.json"


def load(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        parts = sorted(path.parent.glob(path.name + ".part-*"))
        if not parts:
            raise
        payload = "".join(part.read_text(encoding="utf-8") for part in parts)
        return json.loads(payload)


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    registry = load(REGISTRY)
    seeds = load(SEEDS)
    state = load(STATE)
    web = load(WEB)

    sources = registry.get("sources", [])
    source_ids = [source.get("id") for source in sources]
    source_urls = [source.get("url") for source in sources]
    if len(source_ids) != len(set(source_ids)):
        errors.append("duplicate source ids")
    if len(source_urls) != len(set(source_urls)):
        errors.append("duplicate source urls")
    for source in sources:
        if source.get("tier") not in {"T1", "T1B", "T2", "T3"}:
            errors.append(f"invalid tier for {source.get('id')}")
        if not re.match(r"^https://", source.get("url", "")):
            errors.append(f"source must use https: {source.get('id')}")

    source_by_id = {source["id"]: source for source in sources}
    venues = seeds.get("venues", [])
    venue_ids = [venue.get("id") for venue in venues]
    if len(venue_ids) != len(set(venue_ids)):
        errors.append("duplicate venue ids")

    address_index: dict[str, list[str]] = defaultdict(list)
    for venue in venues:
        venue_id = venue.get("id", "<missing>")
        for field in ("id", "name", "locality", "verification", "editorialEligibility", "evidence"):
            if field not in venue:
                errors.append(f"{venue_id}: missing {field}")

        for item in venue.get("evidence", []):
            if item.get("sourceId") not in source_by_id:
                errors.append(f"{venue_id}: unknown source {item.get('sourceId')}")

        if venue.get("verification", "").startswith("DISCOVERY_ONLY") and venue.get("editorialEligibility") != "NOT_ELIGIBLE_DISCOVERY_ONLY":
            errors.append(f"{venue_id}: discovery-only item was promoted")

        operator = venue.get("operator", {})
        if operator.get("cui") or operator.get("legalName"):
            legal_sources = [
                source_by_id[e["sourceId"]]
                for e in venue.get("evidence", [])
                if e["sourceId"] in source_by_id
                and source_by_id[e["sourceId"]]["tier"] in {"T1", "T2"}
                and "LEGAL_ENTITY" in source_by_id[e["sourceId"]].get("authorityScopes", [])
            ]
            if not legal_sources:
                errors.append(f"{venue_id}: legal entity has no qualified evidence")

        if venue.get("editorialEligibility") in {"DRAFT_ELIGIBLE", "DRAFT_REVIEW_REQUIRED"} and operator.get("verification") in {"NOT_RESEARCHED", None}:
            warnings.append(f"{venue_id}: operator research incomplete")

        public_connections = venue.get("publicConnections", {})
        if public_connections.get("items"):
            for connection in public_connections["items"]:
                if not connection.get("sourceId") or not connection.get("relevance"):
                    errors.append(f"{venue_id}: public connection lacks source or relevance")

        for price in venue.get("menu", {}).get("prices", []):
            if not price.get("asOf") or price.get("currency") != "RON":
                errors.append(f"{venue_id}: price missing RON/asOf")

        address = venue.get("address", {}).get("display")
        if address:
            address_index[address.lower()].append(venue_id)

    for address, ids in address_index.items():
        if len(ids) > 1:
            warnings.append(f"address collision: {address} -> {', '.join(ids)}")

    creators = seeds.get("creatorCandidates", [])
    for creator in creators:
        if creator.get("foodCreatorStatus") == "VERIFIED" and creator.get("classification") == "DISCOVERY_ONLY":
            errors.append(f"{creator.get('id')}: creator promoted without verification")
        if creator.get("editorialEligibility") != "MONITOR_ONLY":
            errors.append(f"{creator.get('id')}: creator candidate must remain monitor-only")

    state_ids = {item["id"] for item in state.get("items", [])}
    if state_ids != set(venue_ids):
        errors.append("state items do not match seed venue ids")

    web_ids = {item["id"] for item in web.get("venues", [])}
    forbidden = {
        venue["id"]
        for venue in venues
        if venue.get("editorialEligibility") == "NOT_ELIGIBLE_DISCOVERY_ONLY"
    }
    if web_ids & forbidden:
        errors.append(f"discovery-only items leaked into web dataset: {sorted(web_ids & forbidden)}")

    publisher_text = PUBLISHER.read_text(encoding="utf-8")
    if '"status": "publish"' in publisher_text or "'status': 'publish'" in publisher_text:
        errors.append("publisher contains publish status")
    if '"status": "draft"' not in publisher_text:
        errors.append("publisher does not enforce draft status")

    report = {
        "schemaVersion": "1.0",
        "status": "PASS" if not errors else "FAIL",
        "summary": {
            "sources": len(sources),
            "venues": len(venues),
            "creatorCandidates": len(creators),
            "webDraftProfiles": len(web_ids),
            "errors": len(errors),
            "warnings": len(warnings),
        },
        "errors": errors,
        "warnings": warnings,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
