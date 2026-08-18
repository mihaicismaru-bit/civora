#!/usr/bin/env python3
"""Fail-closed guard for the ephemeral dynamic venue discovery overlay.

`venue_discovery.py` deliberately expands the frontier beyond the curated seed.
Before the expanded data reaches the normal ingest pipeline, this guard rejects
ambiguous or duplicate overlay identities and reconstructs the ephemeral working
seed/registry from the static baseline plus only safe dynamic records.

The guard never grants publication eligibility; it can only remove an overlay
record. The normal validation, address-collision guard and verified-venue
promotion gate remain authoritative afterwards.
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import urllib.parse
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "valcea-clar"
INGEST = BASE / "ingest"
STATE = INGEST / "state"
REGISTRY_PATH = INGEST / "source_registry.json"
SEED_PATH = INGEST / "seed_catalog.json"
DYNAMIC_SOURCES_PATH = STATE / "discovered_sources.json"
DYNAMIC_VENUES_PATH = STATE / "discovered_venues.json"
RECEIPT_PATH = BASE / "ops" / "venue_discovery_overlay_guard.json"


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize(value: object | None) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def canonical_url(value: object | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw.lstrip("/")
    parsed = urllib.parse.urlparse(raw)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if not host:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return f"https://{host}{path}"


def evidence_source_ids(venue: dict[str, Any]) -> list[str]:
    return [str(row.get("sourceId")) for row in venue.get("evidence", []) if row.get("sourceId")]


def derive_baseline(
    combined_registry: dict[str, Any],
    combined_seed: dict[str, Any],
    dynamic_sources: list[dict[str, Any]],
    dynamic_venues: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    dynamic_source_ids = {str(row.get("id")) for row in dynamic_sources if row.get("id")}
    dynamic_venue_ids = {str(row.get("id")) for row in dynamic_venues if row.get("id")}
    baseline_sources = [
        row for row in combined_registry.get("sources", [])
        if str(row.get("id")) not in dynamic_source_ids
    ]
    baseline_venues = [
        row for row in combined_seed.get("venues", [])
        if str(row.get("id")) not in dynamic_venue_ids
    ]
    return baseline_sources, baseline_venues


def build(
    combined_registry: dict[str, Any],
    combined_seed: dict[str, Any],
    dynamic_sources_doc: dict[str, Any],
    dynamic_venues_doc: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    dynamic_sources = list(dynamic_sources_doc.get("sources", []))
    dynamic_venues = list(dynamic_venues_doc.get("venues", []))
    baseline_sources, baseline_venues = derive_baseline(
        combined_registry, combined_seed, dynamic_sources, dynamic_venues
    )

    baseline_source_ids = {str(row.get("id")) for row in baseline_sources if row.get("id")}
    baseline_venue_ids = {str(row.get("id")) for row in baseline_venues if row.get("id")}
    baseline_names = {normalize(row.get("name")) for row in baseline_venues if row.get("name")}
    baseline_urls = {canonical_url(row.get("url")) for row in baseline_sources if row.get("url")}
    baseline_urls.discard("")

    dynamic_source_by_id = {
        str(row.get("id")): row for row in dynamic_sources if row.get("id")
    }
    source_use: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for venue in dynamic_venues:
        for sid in evidence_source_ids(venue):
            source_use[sid].append(venue)

    dynamic_urls: dict[str, list[str]] = defaultdict(list)
    for sid, source in dynamic_source_by_id.items():
        url = canonical_url(source.get("url"))
        if url:
            dynamic_urls[url].append(sid)

    blocked: list[dict[str, Any]] = []
    kept_venues: list[dict[str, Any]] = []

    for venue in dynamic_venues:
        vid = str(venue.get("id") or "")
        name = normalize(venue.get("name"))
        website = canonical_url((venue.get("contacts") or {}).get("website"))
        source_ids = evidence_source_ids(venue)
        reasons: list[str] = []

        if not vid or not name or not website:
            reasons.append("missing_dynamic_identity_fields")
        if vid in baseline_venue_ids:
            reasons.append("venue_id_collides_with_baseline")
        if name in baseline_names:
            reasons.append("venue_name_collides_with_baseline")
        if len(source_ids) != 1:
            reasons.append("dynamic_venue_must_have_exactly_one_identity_source")

        source = dynamic_source_by_id.get(source_ids[0]) if len(source_ids) == 1 else None
        if source is None:
            reasons.append("dynamic_identity_source_missing")
        else:
            source_url = canonical_url(source.get("url"))
            if source_url != website:
                reasons.append("venue_website_source_url_mismatch")
            if source_url in baseline_urls:
                reasons.append("source_url_already_registered_in_baseline")
            if len(dynamic_urls.get(source_url, [])) > 1:
                reasons.append("duplicate_dynamic_source_url")
            users = source_use.get(source_ids[0], [])
            distinct_users = {str(row.get("id")) for row in users if row.get("id")}
            if len(distinct_users) > 1:
                reasons.append("dynamic_source_id_shared_across_venues")
            if source_ids[0] in baseline_source_ids:
                reasons.append("source_id_collides_with_baseline")

        if reasons:
            blocked.append({
                "id": vid,
                "name": str(venue.get("name") or ""),
                "reasons": sorted(set(reasons)),
                "publication_effect": "NONE",
            })
            continue
        kept_venues.append(venue)

    kept_source_ids = {
        sid for venue in kept_venues for sid in evidence_source_ids(venue)
    }
    kept_sources = [
        row for row in dynamic_sources
        if str(row.get("id")) in kept_source_ids
    ]

    registry_out = json.loads(json.dumps(combined_registry, ensure_ascii=False))
    seed_out = json.loads(json.dumps(combined_seed, ensure_ascii=False))
    registry_out["sources"] = baseline_sources + kept_sources
    seed_out["venues"] = baseline_venues + kept_venues

    generated_at = (
        dynamic_venues_doc.get("generatedAt")
        or dynamic_sources_doc.get("generatedAt")
        or combined_seed.get("generatedAt")
    )
    dynamic_sources_out = {
        "schemaVersion": "1.1",
        "generatedAt": generated_at,
        "sources": kept_sources,
    }
    dynamic_venues_out = {
        "schemaVersion": "1.1",
        "generatedAt": generated_at,
        "venues": kept_venues,
    }
    receipt = {
        "schema_version": "1.0",
        "generated_at": generated_at,
        "status": "PASS",
        "policy": {
            "may_grant_publication_eligibility": False,
            "duplicate_baseline_url_allowed": False,
            "shared_dynamic_source_identity_allowed": False,
            "venue_source_url_must_match": True,
            "publication_effect": "NONE",
        },
        "input_dynamic_venues": len(dynamic_venues),
        "kept_dynamic_venues": len(kept_venues),
        "kept_dynamic_sources": len(kept_sources),
        "blocked": blocked,
    }
    return registry_out, seed_out, dynamic_sources_out, dynamic_venues_out, receipt


def self_test() -> int:
    baseline_source = {
        "id": "BASE-T1",
        "name": "Baseline",
        "url": "https://known.example/",
        "tier": "T1",
    }
    baseline_venue = {"id": "known", "name": "Known Place"}
    dynamic_sources = {
        "generatedAt": "2026-08-18T20:00:00+00:00",
        "sources": [
            {"id": "AUTO-A", "url": "https://a.example/"},
            {"id": "AUTO-KNOWN", "url": "https://known.example/"},
            {"id": "AUTO-SHARED", "url": "https://shared.example/"},
        ],
    }
    dynamic_venues = {
        "generatedAt": "2026-08-18T20:00:00+00:00",
        "venues": [
            {
                "id": "safe", "name": "Safe Place",
                "contacts": {"website": "https://a.example/"},
                "evidence": [{"sourceId": "AUTO-A"}],
            },
            {
                "id": "dup-url", "name": "Other Name",
                "contacts": {"website": "https://known.example/"},
                "evidence": [{"sourceId": "AUTO-KNOWN"}],
            },
            {
                "id": "shared-1", "name": "Shared One",
                "contacts": {"website": "https://shared.example/"},
                "evidence": [{"sourceId": "AUTO-SHARED"}],
            },
            {
                "id": "shared-2", "name": "Shared Two",
                "contacts": {"website": "https://shared.example/"},
                "evidence": [{"sourceId": "AUTO-SHARED"}],
            },
        ],
    }
    combined_registry = {
        "sources": [baseline_source] + dynamic_sources["sources"]
    }
    combined_seed = {
        "venues": [baseline_venue] + dynamic_venues["venues"]
    }
    registry, seed, sources, venues, receipt = build(
        combined_registry, combined_seed, dynamic_sources, dynamic_venues
    )
    assert [row["id"] for row in venues["venues"]] == ["safe"]
    assert [row["id"] for row in sources["sources"]] == ["AUTO-A"]
    assert {row["id"] for row in seed["venues"]} == {"known", "safe"}
    assert {row["id"] for row in registry["sources"]} == {"BASE-T1", "AUTO-A"}
    blocked_ids = {row["id"] for row in receipt["blocked"]}
    assert blocked_ids == {"dup-url", "shared-1", "shared-2"}
    print("Dynamic discovery overlay guard self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--check", action="store_true", help="evaluate without rewriting overlay files")
    args = parser.parse_args()
    if args.self_test:
        return self_test()

    combined_registry = load_json(REGISTRY_PATH)
    combined_seed = load_json(SEED_PATH)
    dynamic_sources = load_json(DYNAMIC_SOURCES_PATH, {"sources": []})
    dynamic_venues = load_json(DYNAMIC_VENUES_PATH, {"venues": []})
    registry, seed, sources, venues, receipt = build(
        combined_registry, combined_seed, dynamic_sources, dynamic_venues
    )
    if not args.check:
        dump_json(REGISTRY_PATH, registry)
        dump_json(SEED_PATH, seed)
        dump_json(DYNAMIC_SOURCES_PATH, sources)
        dump_json(DYNAMIC_VENUES_PATH, venues)
        dump_json(RECEIPT_PATH, receipt)
    print(json.dumps({
        "status": "PASS",
        "input_dynamic_venues": receipt["input_dynamic_venues"],
        "kept_dynamic_venues": receipt["kept_dynamic_venues"],
        "blocked_count": len(receipt["blocked"]),
        "blocked_ids": [row["id"] for row in receipt["blocked"]],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
