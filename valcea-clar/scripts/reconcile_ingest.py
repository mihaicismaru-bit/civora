#!/usr/bin/env python3
"""Reconcile the venue ingestion layer with the curated public catalogue.

The script is intentionally fail-closed: it creates an editorial review queue,
never mutates ``data/places.json`` and never changes publication status.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_PATH = ROOT / "data" / "places.json"
SEED_PATH = ROOT / "ingest" / "seed_catalog.json"
ALIASES_PATH = ROOT / "ops" / "ingest_aliases.json"
REPORT_PATH = ROOT / "ops" / "ingest_reconciliation.json"
QUEUE_PATH = ROOT / "ops" / "ingest_review_queue.json"

ELIGIBLE = {"DRAFT_ELIGIBLE", "DRAFT_REVIEW_REQUIRED"}
DISCOVERY_ONLY = "NOT_ELIGIBLE_DISCOVERY_ONLY"


def load_json(path: Path) -> dict:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    parts = sorted(path.parent.glob(path.name + ".part-*"))
    if not parts:
        raise FileNotFoundError(path)
    return json.loads("".join(part.read_text(encoding="utf-8") for part in parts))


def normalize(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKD", str(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_address(value: object | None) -> str:
    text = f" {normalize(value)} "
    for token in (" strada ", " str ", " bulevardul ", " bulevard ", " bd ", " nr ", " numarul "):
        text = text.replace(token, " ")
    return re.sub(r"\s+", " ", text).strip()


def website_host(value: object | None) -> str:
    if not value:
        return ""
    parsed = urlparse(str(value))
    host = parsed.netloc.lower().split(":", 1)[0]
    return host.removeprefix("www.")


def phone_set(values: object | None) -> set[str]:
    result: set[str] = set()
    for value in values or []:
        digits = re.sub(r"\D", "", str(value))
        if len(digits) >= 9:
            result.add(digits[-9:])
    return result


def clean_cui(value: object | None) -> str:
    return re.sub(r"\D", "", str(value or ""))


def addresses_equivalent(left: str, right: str) -> bool:
    if not left or not right:
        return True
    return left == right or left in right or right in left


def compare_records(canonical: dict, ingest: dict) -> list[dict]:
    differences: list[dict] = []

    c_address = normalize_address(canonical.get("location", {}).get("address"))
    i_address = normalize_address(ingest.get("address", {}).get("display"))
    if not addresses_equivalent(c_address, i_address):
        differences.append({"field": "address", "canonical": c_address, "ingest": i_address})

    c_host = website_host(canonical.get("contact", {}).get("website"))
    i_host = website_host(ingest.get("contacts", {}).get("website"))
    if c_host and i_host and c_host != i_host:
        differences.append({"field": "website", "canonical": c_host, "ingest": i_host})

    c_phones = phone_set(canonical.get("contact", {}).get("phone"))
    i_phones = phone_set(ingest.get("contacts", {}).get("phones"))
    if c_phones and i_phones and c_phones.isdisjoint(i_phones):
        differences.append(
            {"field": "phones", "canonical": sorted(c_phones), "ingest": sorted(i_phones)}
        )

    c_operator = canonical.get("operator", {})
    i_operator = ingest.get("operator", {})
    c_legal = normalize(c_operator.get("legal_name"))
    i_legal = normalize(i_operator.get("legalName") or i_operator.get("displayName"))
    if c_legal and i_legal and c_legal != i_legal:
        differences.append({"field": "operator", "canonical": c_legal, "ingest": i_legal})

    c_cui = clean_cui(c_operator.get("cui"))
    i_cui = clean_cui(i_operator.get("cui"))
    if c_cui and i_cui and c_cui != i_cui:
        differences.append({"field": "cui", "canonical": c_cui, "ingest": i_cui})

    return differences


def priority(action: str, differences: list[dict], canonical: dict | None) -> str:
    critical_fields = {item["field"] for item in differences} & {"operator", "cui", "address"}
    if critical_fields and canonical and canonical.get("publication_status") == "public":
        return "P0"
    if action in {"CREATE_CANONICAL_DRAFT", "COMPLETE_CANONICAL_RECORD", "VERIFY_CONFLICTS"}:
        return "P1"
    if action == "RECONCILE_ENTITY":
        return "P2"
    return "P3"


def build() -> tuple[dict, dict, list[str]]:
    canonical_doc = load_json(CANONICAL_PATH)
    ingest_doc = load_json(SEED_PATH)
    aliases_doc = load_json(ALIASES_PATH)

    canonical_items = canonical_doc.get("places", [])
    ingest_items = ingest_doc.get("venues", [])
    canonical_by_id = {item["id"]: item for item in canonical_items}
    ingest_by_id = {item["id"]: item for item in ingest_items}
    aliases = aliases_doc.get("aliases", {})
    errors: list[str] = []

    if len(canonical_by_id) != len(canonical_items):
        errors.append("duplicate canonical place ids")
    if len(ingest_by_id) != len(ingest_items):
        errors.append("duplicate ingest venue ids")

    for source_id, target_id in aliases.items():
        if source_id not in ingest_by_id:
            errors.append(f"alias source does not exist: {source_id}")
        if target_id not in canonical_by_id:
            errors.append(f"alias target does not exist: {target_id}")

    canonical_names: dict[str, list[str]] = {}
    for item in canonical_items:
        canonical_names.setdefault(normalize(item.get("name")), []).append(item["id"])

    matches: list[dict] = []
    queue_items: list[dict] = []
    matched = 0
    new_candidates = 0
    discovery_count = 0
    conflict_count = 0

    for ingest in sorted(ingest_items, key=lambda item: item["id"]):
        ingest_id = ingest["id"]
        canonical_id = aliases.get(ingest_id)
        match_method = "explicit_alias" if canonical_id else None

        if not canonical_id and ingest_id in canonical_by_id:
            canonical_id = ingest_id
            match_method = "same_id"
        if not canonical_id:
            name_candidates = canonical_names.get(normalize(ingest.get("name")), [])
            if len(name_candidates) == 1:
                canonical_id = name_candidates[0]
                match_method = "unique_normalized_name"

        eligibility = ingest.get("editorialEligibility")
        canonical = canonical_by_id.get(canonical_id) if canonical_id else None
        differences = compare_records(canonical, ingest) if canonical else []

        if canonical:
            matched += 1
            if eligibility == DISCOVERY_ONLY:
                action = "RECONCILE_ENTITY"
                status = "MATCHED_DISCOVERY_ONLY"
            elif differences:
                action = "VERIFY_CONFLICTS"
                status = "MATCH_REVIEW_REQUIRED"
                conflict_count += 1
            elif canonical.get("publication_status") == "candidate":
                action = "COMPLETE_CANONICAL_RECORD"
                status = "MATCHED_CANDIDATE"
            else:
                action = "NO_ACTION"
                status = "MATCHED_PUBLIC"
        elif eligibility in ELIGIBLE:
            action = "CREATE_CANONICAL_DRAFT"
            status = "NEW_EDITORIAL_CANDIDATE"
            new_candidates += 1
        else:
            action = "MONITOR_ONLY"
            status = "DISCOVERY_ONLY"
            discovery_count += 1

        record = {
            "ingest_id": ingest_id,
            "ingest_name": ingest.get("name"),
            "canonical_id": canonical_id,
            "match_method": match_method,
            "status": status,
            "action": action,
            "editorial_eligibility": eligibility,
            "verification": ingest.get("verification"),
            "publication_effect": "NONE",
            "differences": differences,
        }
        matches.append(record)

        if action != "NO_ACTION":
            queue_items.append(
                {
                    "id": f"ingest-review-{ingest_id}",
                    "priority": priority(action, differences, canonical),
                    "action": action,
                    "ingest_id": ingest_id,
                    "canonical_id": canonical_id,
                    "name": ingest.get("name"),
                    "locality": ingest.get("locality"),
                    "differences": differences,
                    "editorial_eligibility": eligibility,
                    "publication_effect": "NONE",
                    "auto_publish": False,
                }
            )

    if any(item.get("auto_publish") for item in queue_items):
        errors.append("review queue contains auto_publish=true")
    leaked = [
        item["ingest_id"]
        for item in matches
        if item["editorial_eligibility"] == DISCOVERY_ONLY
        and item["publication_effect"] != "NONE"
    ]
    if leaked:
        errors.append(f"discovery-only records gained publication effect: {', '.join(leaked)}")

    queue_items.sort(key=lambda item: (item["priority"], item["name"] or item["ingest_id"]))
    generated_at = ingest_doc.get("generatedAt") or canonical_doc.get("generated_at")
    report = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "policy": {
            "canonical_catalogue_mutated": False,
            "auto_publish": False,
            "discovery_only_publication_effect": "NONE",
            "human_review_required": True,
        },
        "summary": {
            "canonical_records": len(canonical_items),
            "ingest_records": len(ingest_items),
            "matched": matched,
            "new_editorial_candidates": new_candidates,
            "unmatched_discovery_only": discovery_count,
            "conflicts": conflict_count,
            "review_queue": len(queue_items),
        },
        "records": matches,
    }
    queue = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "status": "EDITORIAL_REVIEW_REQUIRED" if queue_items else "CLEAR",
        "policy": {"auto_publish": False, "publication_effect": "NONE"},
        "items": queue_items,
    }
    return report, queue, errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate and print without writing files")
    args = parser.parse_args()

    report, queue, errors = build()
    if errors:
        print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
        return 1

    if not args.check:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        QUEUE_PATH.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"status": "PASS", **report["summary"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
