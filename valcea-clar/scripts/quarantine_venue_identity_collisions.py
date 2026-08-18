#!/usr/bin/env python3
"""Quarantine ambiguous new venue identities before autonomous promotion.

A verified source can prove that a venue exists without proving that a newly
observed name is a distinct canonical business. When an otherwise auto-eligible
unmatched ingest venue resolves to an address already used by another canonical
venue, this guard downgrades it to editorial review instead of guessing.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "ingest" / "state" / "venues.json"
PLACES_PATH = ROOT / "data" / "places.json"
ALIASES_PATH = ROOT / "ops" / "ingest_aliases.json"
RECEIPT_PATH = ROOT / "ops" / "venue_identity_collision_holds.json"


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def dump_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(value: object | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_address(value: object | None) -> str:
    text = f" {normalize(value)} "
    for token in (" strada ", " str ", " bulevardul ", " bulevard ", " bd ", " nr ", " numarul "):
        text = text.replace(token, " ")
    return re.sub(r"\s+", " ", text).strip()


def addresses_equivalent(left: str, right: str) -> bool:
    if not left or not right:
        return False
    return left == right or left in right or right in left


def canonical_match_id(item: dict[str, Any], places: list[dict[str, Any]], aliases: dict[str, str]) -> str | None:
    by_id = {str(row.get("id")): row for row in places if row.get("id")}
    ingest_id = str(item.get("id") or "")
    if ingest_id in aliases and aliases[ingest_id] in by_id:
        return aliases[ingest_id]
    if ingest_id in by_id:
        return ingest_id
    name = normalize(item.get("name"))
    named = [str(row["id"]) for row in places if normalize(row.get("name")) == name]
    return named[0] if len(named) == 1 else None


def build(
    state_doc: dict[str, Any], places_doc: dict[str, Any], aliases_doc: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    out = deepcopy(state_doc)
    places = places_doc.get("places", [])
    aliases = {str(k): str(v) for k, v in aliases_doc.get("aliases", {}).items()}
    canonical_addresses: list[tuple[str, str]] = []
    for row in places:
        address = normalize_address((row.get("location") or {}).get("address"))
        if address and row.get("id"):
            canonical_addresses.append((str(row["id"]), address))

    holds: list[dict[str, str]] = []
    for item in out.get("items", []):
        if item.get("editorialEligibility") != "DRAFT_ELIGIBLE":
            continue
        if item.get("verification") != "VERIFIED_OFFICIAL":
            continue
        matched_id = canonical_match_id(item, places, aliases)
        if matched_id:
            continue
        incoming = normalize_address((item.get("address") or {}).get("display"))
        if not incoming:
            continue
        collisions = [place_id for place_id, address in canonical_addresses if addresses_equivalent(address, incoming)]
        if not collisions:
            continue
        item["editorialEligibility"] = "DRAFT_REVIEW_REQUIRED"
        item["autonomyHold"] = {
            "reason": "CANONICAL_ADDRESS_IDENTITY_COLLISION",
            "canonicalIds": sorted(set(collisions)),
            "publicationEffect": "NONE",
            "requiresIdentityReconciliation": True,
        }
        holds.append({
            "ingest_id": str(item.get("id")),
            "name": str(item.get("name")),
            "reason": "CANONICAL_ADDRESS_IDENTITY_COLLISION",
            "canonical_ids": ",".join(sorted(set(collisions))),
        })

    generated_at = (
        state_doc.get("lastRun", {}).get("observedAt")
        or state_doc.get("generatedAt")
        or places_doc.get("generated_at")
    )
    receipt = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "status": "IDENTITY_REVIEW_REQUIRED" if holds else "CLEAR",
        "policy": {
            "address_collision_autopublish": False,
            "identity_guessing": False,
            "publication_effect": "NONE",
        },
        "holds": holds,
    }
    return out, receipt


def self_test() -> int:
    state = {
        "lastRun": {"observedAt": "2026-08-18T20:00:00+00:00"},
        "items": [
            {
                "id": "new-place",
                "name": "New Place",
                "verification": "VERIFIED_OFFICIAL",
                "editorialEligibility": "DRAFT_ELIGIBLE",
                "address": {"display": "Strada Test nr. 5"},
            },
            {
                "id": "safe-place",
                "name": "Safe Place",
                "verification": "VERIFIED_OFFICIAL",
                "editorialEligibility": "DRAFT_ELIGIBLE",
                "address": {"display": "Strada Nouă nr. 10"},
            },
        ],
    }
    places = {
        "places": [
            {"id": "existing", "name": "Existing", "location": {"address": "Str. Test 5"}},
        ]
    }
    out, receipt = build(state, places, {"aliases": {}})
    by_id = {row["id"]: row for row in out["items"]}
    assert by_id["new-place"]["editorialEligibility"] == "DRAFT_REVIEW_REQUIRED"
    assert by_id["new-place"]["autonomyHold"]["canonicalIds"] == ["existing"]
    assert by_id["safe-place"]["editorialEligibility"] == "DRAFT_ELIGIBLE"
    assert receipt["holds"][0]["ingest_id"] == "new-place"

    aliased = deepcopy(state)
    aliased["items"] = [deepcopy(state["items"][0])]
    out, receipt = build(aliased, places, {"aliases": {"new-place": "existing"}})
    assert out["items"][0]["editorialEligibility"] == "DRAFT_ELIGIBLE"
    assert receipt["holds"] == []
    print("Venue identity collision guard self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true", help="evaluate holds without changing ingest state")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    state = load_json(STATE_PATH)
    places = load_json(PLACES_PATH)
    aliases = load_json(ALIASES_PATH)
    out, receipt = build(state, places, aliases)
    if not args.check:
        dump_json(STATE_PATH, out)
        dump_json(RECEIPT_PATH, receipt)
    print(json.dumps({
        "status": "PASS",
        "identity_holds": len(receipt["holds"]),
        "held_ids": [row["ingest_id"] for row in receipt["holds"]],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
