#!/usr/bin/env python3
"""Deterministic ingestion for VÂLCEA CLAR — UNDE IEȘIM.

The curated seed is the fact layer. Network probes refresh source health and
semantic hashes; they never promote discovery-only data or infer ownership.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "valcea-clar" / "ingest"
SEEDS = INGEST / "seed_catalog.json"
REGISTRY = INGEST / "source_registry.json"
STATE_DIR = INGEST / "state"
STATE = STATE_DIR / "venues.json"
HEALTH = STATE_DIR / "source_health.json"
WEB = ROOT / "valcea-clar" / "web" / "unde-iesim.json"

ELIGIBLE = {"DRAFT_ELIGIBLE", "DRAFT_REVIEW_REQUIRED"}


class TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.in_title = False
        self.suppressed = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = True
        if tag in {"script", "style", "noscript", "svg"}:
            self.suppressed += 1

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "title":
            self.in_title = False
        if tag in {"script", "style", "noscript", "svg"} and self.suppressed:
            self.suppressed -= 1

    def handle_data(self, data: str) -> None:
        if self.suppressed:
            return
        cleaned = re.sub(r"\s+", " ", data).strip()
        if not cleaned:
            return
        self.parts.append(cleaned)
        if self.in_title:
            self.title_parts.append(cleaned)


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        parts = sorted(path.parent.glob(path.name + ".part-*"))
        if parts:
            payload = "".join(part.read_text(encoding="utf-8") for part in parts)
            return json.loads(payload)
        if default is not None:
            return default
        raise


def dump_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def probe_source(source: dict[str, Any], timeout: float) -> dict[str, Any]:
    observed = utcnow()
    request = urllib.request.Request(
        source["url"],
        headers={
            "User-Agent": "ValceaClar-UndeIesim/1.0 (+editorial source monitor)",
            "Accept-Language": "ro-RO,ro;q=0.9,en;q=0.5",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.4",
        },
    )
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            raw = response.read(800_000)
            content_type = response.headers.get("content-type", "")
            status = getattr(response, "status", 200)
            final_url = response.geturl()
        text = raw.decode("utf-8", "replace")
        title = ""
        normalized = text
        if "html" in content_type.lower() or "<html" in text[:1000].lower():
            parser = TextExtractor()
            parser.feed(text)
            normalized = re.sub(r"\s+", " ", " ".join(parser.parts)).strip()
            title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
        semantic = hashlib.sha256(normalized[:500_000].encode("utf-8")).hexdigest()
        if status >= 400 or len(normalized) < 40:
            raise RuntimeError(f"invalid response status={status} text_length={len(normalized)}")
        return {
            "id": source["id"],
            "tier": source["tier"],
            "url": source["url"],
            "observedAt": observed,
            "health": "OK",
            "httpStatus": status,
            "finalUrl": final_url,
            "contentType": content_type,
            "title": title[:300] or None,
            "semanticSha256": semantic,
            "textLength": len(normalized),
            "lastKnownGoodPreserved": True,
        }
    except Exception as exc:  # network failures must preserve the fact layer
        return {
            "id": source["id"],
            "tier": source["tier"],
            "url": source["url"],
            "observedAt": observed,
            "health": "FAILED",
            "error": f"{type(exc).__name__}: {exc}",
            "lastKnownGoodPreserved": True,
        }


def merge_health(
    source: dict[str, Any],
    probe: dict[str, Any] | None,
    previous: dict[str, Any] | None,
    no_network: bool,
) -> dict[str, Any]:
    if no_network:
        result = {
            "id": source["id"],
            "tier": source["tier"],
            "url": source["url"],
            "observedAt": utcnow(),
            "health": "SKIPPED_NO_NETWORK",
            "registryStatus": source["status"],
            "lastKnownGoodPreserved": True,
        }
        if previous and previous.get("semanticSha256"):
            result["semanticSha256"] = previous["semanticSha256"]
            result["lastSuccessfulAt"] = previous.get("lastSuccessfulAt") or previous.get("observedAt")
        return result

    assert probe is not None
    result = dict(probe)
    result["registryStatus"] = source["status"]
    previous_hash = (previous or {}).get("semanticSha256")
    current_hash = result.get("semanticSha256")
    result["semanticHashChanged"] = bool(previous_hash and current_hash and previous_hash != current_hash)
    if result["health"] == "OK":
        result["lastSuccessfulAt"] = result["observedAt"]
    elif previous:
        for key in ("semanticSha256", "lastSuccessfulAt", "title", "finalUrl"):
            if previous.get(key) is not None and result.get(key) is None:
                result[key] = previous[key]
    return result


def canonical_venue(seed: dict[str, Any], previous: dict[str, Any] | None, health_by_id: dict[str, dict[str, Any]], observed: str) -> dict[str, Any]:
    item = json.loads(json.dumps(seed, ensure_ascii=False))
    evidence_ids = [entry["sourceId"] for entry in item.get("evidence", [])]
    healthy = [health_by_id[sid] for sid in evidence_ids if health_by_id.get(sid, {}).get("health") == "OK"]
    strong_healthy = [h for h in healthy if h.get("tier") in {"T1", "T1B", "T2"}]

    if strong_healthy:
        item["lastVerifiedAt"] = observed
    elif previous and previous.get("lastVerifiedAt"):
        item["lastVerifiedAt"] = previous["lastVerifiedAt"]
    else:
        item["lastVerifiedAt"] = seed.get("generatedAt") or observed

    item["evidenceHealth"] = {
        "registered": len(evidence_ids),
        "healthyNow": len(healthy),
        "strongHealthyNow": len(strong_healthy),
        "sourceIds": evidence_ids,
    }
    item["canonicalHash"] = stable_hash(seed)
    return item


def make_web_dataset(items: list[dict[str, Any]], observed: str, status: str) -> dict[str, Any]:
    public_items: list[dict[str, Any]] = []
    allowed_fields = {
        "id", "name", "locality", "county", "address", "categories", "status",
        "opening", "contacts", "hours", "menu", "operator", "publicConnections",
        "services", "verification", "editorialEligibility", "editorialAngle",
        "lastVerifiedAt", "canonicalHash",
    }
    for item in items:
        if item.get("editorialEligibility") not in ELIGIBLE:
            continue
        public_items.append({key: item[key] for key in allowed_fields if key in item})

    return {
        "schemaVersion": "1.0",
        "generatedAt": observed,
        "status": status,
        "disclaimer": (
            "Datele sunt pentru verificare editorială. Prețurile și programul au "
            "data verificării; verifică înainte de deplasare."
        ),
        "summary": {
            "draftEligible": sum(i.get("editorialEligibility") == "DRAFT_ELIGIBLE" for i in items),
            "reviewRequired": sum(i.get("editorialEligibility") == "DRAFT_REVIEW_REQUIRED" for i in items),
            "discoveryOnly": sum(i.get("editorialEligibility") == "NOT_ELIGIBLE_DISCOVERY_ONLY" for i in items),
        },
        "venues": public_items,
        "newOpenings": [
            {
                "id": item["id"],
                "name": item["name"],
                "opening": item.get("opening", {}),
                "locality": item["locality"],
                "verification": item["verification"],
            }
            for item in items
            if item.get("editorialAngle") == "NOU_DESCHIS"
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-network", action="store_true", help="rebuild canonical output without HTTP probes")
    parser.add_argument("--timeout", type=float, default=12.0)
    args = parser.parse_args()

    seed_catalog = load_json(SEEDS)
    registry = load_json(REGISTRY)
    previous_state = load_json(STATE, {"items": [], "creatorCandidates": []})
    previous_health = load_json(HEALTH, {"sources": []})
    previous_items = {item["id"]: item for item in previous_state.get("items", [])}
    previous_health_by_id = {item["id"]: item for item in previous_health.get("sources", [])}
    observed = utcnow()

    merged_health: list[dict[str, Any]] = []
    for source in registry["sources"]:
        probe = None if args.no_network else probe_source(source, args.timeout)
        merged_health.append(
            merge_health(source, probe, previous_health_by_id.get(source["id"]), args.no_network)
        )

    health_by_id = {item["id"]: item for item in merged_health}
    items = [
        canonical_venue(seed, previous_items.get(seed["id"]), health_by_id, observed)
        for seed in seed_catalog["venues"]
    ]

    ok_count = sum(item["health"] == "OK" for item in merged_health)
    failed_count = sum(item["health"] == "FAILED" for item in merged_health)
    changed_sources = [item["id"] for item in merged_health if item.get("semanticHashChanged")]
    if args.no_network:
        run_status = "OK_NO_NETWORK_SEED_PRESERVED"
    elif ok_count:
        run_status = "OK" if failed_count == 0 else "DEGRADED_PARTIAL_SOURCE_SUCCESS"
    else:
        run_status = "SOURCE_UNAVAILABLE_LAST_KNOWN_GOOD_PRESERVED"

    by_verification: dict[str, int] = {}
    for item in items:
        key = item.get("verification", "UNKNOWN")
        by_verification[key] = by_verification.get(key, 0) + 1

    run = {
        "runId": f"VC-UI-{observed.replace(':', '').replace('-', '')}",
        "observedAt": observed,
        "mode": "NO_NETWORK" if args.no_network else "NETWORK_PROBE",
        "status": run_status,
        "sourceCount": len(merged_health),
        "sourceOk": ok_count,
        "sourceFailed": failed_count,
        "semanticChangeCandidates": changed_sources,
        "venueCount": len(items),
        "creatorCandidateCount": len(seed_catalog.get("creatorCandidates", [])),
        "policy": "SOURCE_CHANGES_REQUIRE_EDITORIAL_REVIEW; NO_AUTO_PROMOTION",
    }
    state = {
        "schemaVersion": "1.0",
        "status": run_status,
        "lastRun": run,
        "summary": {
            "venues": len(items),
            "creatorCandidates": len(seed_catalog.get("creatorCandidates", [])),
            "byVerification": by_verification,
        },
        "items": items,
        "creatorCandidates": seed_catalog.get("creatorCandidates", []),
    }
    health = {
        "schemaVersion": "1.0",
        "status": run_status,
        "observedAt": observed,
        "summary": {
            "registered": len(merged_health),
            "ok": ok_count,
            "failed": failed_count,
            "skipped": sum(item["health"] == "SKIPPED_NO_NETWORK" for item in merged_health),
            "semanticChangeCandidates": len(changed_sources),
        },
        "sources": merged_health,
    }

    dump_json(STATE, state)
    dump_json(HEALTH, health)
    dump_json(WEB, make_web_dataset(items, observed, "EDITORIAL_DRAFT_DATASET"))
    print(json.dumps(run, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
