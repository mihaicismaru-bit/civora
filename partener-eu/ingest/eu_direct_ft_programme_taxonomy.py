#!/usr/bin/env python3
"""Normalize official F&T programme labels into PARTENER market-intelligence taxonomy.

The source watch remains acquisition-only. This deterministic PARTENER Engine
handoff binds to that immutable watch and normalizes programme families without
turning discovery rows into call facts. Unknown official programme labels are
preserved as a research watchlist instead of being invented into known families.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
from collections import Counter
from typing import Any, Mapping

WATCH_SCHEMA = "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1"
SCHEMA = "PARTENER_EU_FT_PROGRAMME_TAXONOMY_V1"
PARSER_VERSION = "EU_DIRECT_FT_PROGRAMME_TAXONOMY_V1"


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def normalize_programme_family(label: str) -> str:
    token = _token(label)
    rules = (
        ("HORIZON_EUROPE", ("horizon europe",)),
        ("DIGITAL_EUROPE", ("digital europe",)),
        ("LIFE", (
            "programme for the environment and climate action",
            "programme for environment and climate action",
            "life programme",
        )),
        ("CERV", ("citizens equality rights and values", "rights and values programme")),
        ("SINGLE_MARKET_PROGRAMME", ("single market programme",)),
        ("CEF", ("connecting europe facility",)),
        ("INNOVATION_FUND", ("innovation fund",)),
        ("EU4HEALTH", ("eu4health",)),
        ("CREATIVE_EUROPE", ("creative europe",)),
        ("ERASMUS_PLUS", ("erasmus",)),
        ("EUROPEAN_SOLIDARITY_CORPS", ("european solidarity corps",)),
        ("JUSTICE_PROGRAMME", ("justice programme",)),
    )
    for family, needles in rules:
        if any(needle in token for needle in needles):
            return family
    return "OTHER_EU_DIRECT"


def normalize_instrument_family(identifier: str, programme_family: str) -> str | None:
    # Instrument taxonomy is market intelligence only; programme authority remains
    # the official frameworkProgramme Facet evidence bound in the source watch.
    upper = identifier.upper()
    if programme_family == "HORIZON_EUROPE" and upper.startswith("HORIZON-EIC-"):
        return "EIC"
    return None


def build_taxonomy_receipt(watch: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(watch, Mapping) or watch.get("schema") != WATCH_SCHEMA:
        raise ValueError(f"watch schema must be {WATCH_SCHEMA}")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        if watch.get(key) is not False:
            raise ValueError(f"unsafe upstream watch authorization: {key}")
    if watch.get("market_intelligence_only") is not True or watch.get("publication_effect") != "NONE":
        raise ValueError("upstream watch is not market-intelligence-only")

    source_records = watch.get("records")
    if not isinstance(source_records, list):
        raise ValueError("watch records must be a list")

    normalized_records: list[dict[str, Any]] = []
    family_counts: Counter[str] = Counter()
    instrument_counts: Counter[str] = Counter()
    unmapped_counts: Counter[str] = Counter()
    for row in source_records:
        if not isinstance(row, Mapping):
            raise ValueError("watch record must be an object")
        identifier = str(row.get("identifier") or "").strip()
        label = str(row.get("programme_label") or "").strip()
        if not identifier or not label:
            raise ValueError("watch record lacks identifier or official programme label")
        family = normalize_programme_family(label)
        instrument = normalize_instrument_family(identifier, family)
        family_counts[family] += 1
        if instrument:
            instrument_counts[instrument] += 1
        if family == "OTHER_EU_DIRECT":
            unmapped_counts[label] += 1
        normalized_records.append({
            "identifier": identifier,
            "call_identifier": row.get("call_identifier"),
            "programme_reference": row.get("programme_reference"),
            "programme_label_official": label,
            "programme_family_normalized": family,
            "instrument_family_normalized": instrument,
            "status_label_candidate": row.get("status_label_candidate"),
            "authority_url_candidate": row.get("authority_url_candidate"),
            "source_semantic_fingerprint": row.get("semantic_fingerprint"),
            "source_dedup_key": row.get("dedup_key"),
            "taxonomy_fingerprint": sha256_json({
                "identifier": identifier,
                "programme_reference": row.get("programme_reference"),
                "programme_label_official": label,
                "programme_family_normalized": family,
                "instrument_family_normalized": instrument,
            }),
            "observation_state": "PROGRAMME_TAXONOMY_MARKET_INTELLIGENCE_NON_AUTHORIZING",
            "market_intelligence_only": True,
            "material_fact_use": False,
            "open_call_authorized": False,
            "deadline_authorized": False,
            "budget_authorized": False,
            "eligibility_authorized": False,
            "publish_authorized": False,
            "distribution_authorized": False,
            "call_alert_authorized": False,
        })

    research_watchlist = [
        {
            "official_programme_label": label,
            "observed_candidate_count": count,
            "state": "PROGRAMME_FIT_RESEARCH_WATCH_NON_AUTHORIZING",
            "reason": "OFFICIAL_FT_PROGRAMME_OBSERVED_BUT_NOT_YET_MAPPED_TO_CANONICAL_PRIORITY_FAMILY",
            "material_fact_use": False,
            "open_call_authorized": False,
        }
        for label, count in sorted(unmapped_counts.items(), key=lambda item: (-item[1], item[0]))
    ]

    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_watch_schema": WATCH_SCHEMA,
        "source_watch_sha256": sha256_json(watch),
        "source_family": watch.get("source_family"),
        "programme_family": watch.get("programme_family"),
        "authority_class": watch.get("authority_class"),
        "fetched_at": watch.get("fetched_at"),
        "run_id": watch.get("run_id"),
        "records": normalized_records,
        "programme_family_counts": dict(sorted(family_counts.items())),
        "instrument_family_counts": dict(sorted(instrument_counts.items())),
        "research_watchlist": research_watchlist,
        "stats": {
            "source_records": len(source_records),
            "normalized_records": len(normalized_records),
            "canonical_priority_family_count": sum(count for family, count in family_counts.items() if family != "OTHER_EU_DIRECT"),
            "other_eu_direct_count": family_counts.get("OTHER_EU_DIRECT", 0),
            "unmapped_official_programme_labels": len(unmapped_counts),
        },
        "market_intelligence_only": True,
        "material_fact_use": False,
        "open_call_authorized": False,
        "deadline_authorized": False,
        "budget_authorized": False,
        "eligibility_authorized": False,
        "publish_authorized": False,
        "distribution_authorized": False,
        "call_alert_authorized": False,
        "canonical_corpus_mutation": False,
        "publication_effect": "NONE",
        "rollback": "Discard this taxonomy receipt; source evidence and canonical/public state remain unchanged.",
    }


def validate_taxonomy_receipt(receipt: Mapping[str, Any], watch: Mapping[str, Any]) -> None:
    if receipt.get("schema") != SCHEMA:
        raise ValueError("taxonomy receipt schema mismatch")
    if receipt.get("source_watch_sha256") != sha256_json(watch):
        raise ValueError("taxonomy receipt is not bound to supplied watch")
    if (receipt.get("stats") or {}).get("source_records") != (receipt.get("stats") or {}).get("normalized_records"):
        raise ValueError("taxonomy dropped or multiplied source records")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        if receipt.get(key) is not False:
            raise ValueError(f"taxonomy receipt attempted authorization: {key}")
    if receipt.get("market_intelligence_only") is not True or receipt.get("publication_effect") != "NONE":
        raise ValueError("taxonomy receipt crossed non-authorizing boundary")
    for row in receipt.get("records") or []:
        if row.get("market_intelligence_only") is not True or row.get("material_fact_use") is not False:
            raise ValueError(f"unsafe taxonomy record: {row.get('identifier')}")
        if row.get("open_call_authorized") is not False or row.get("publish_authorized") is not False:
            raise ValueError(f"taxonomy record self-authorized: {row.get('identifier')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("watch", type=pathlib.Path)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    watch = json.loads(args.watch.read_text(encoding="utf-8"))
    receipt = build_taxonomy_receipt(watch)
    validate_taxonomy_receipt(receipt, watch)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "stats": receipt["stats"],
        "programme_family_counts": receipt["programme_family_counts"],
        "instrument_family_counts": receipt["instrument_family_counts"],
        "research_watchlist": receipt["research_watchlist"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
