#!/usr/bin/env python3
"""Programme-wide EU_DIRECT market-intelligence watch over official F&T Search/Facet.

This is an acquisition/discovery layer only. It deliberately does not perform
exact-topic readback and therefore cannot authorize OPEN, deadline, budget,
eligibility, publication, distribution, or canonical corpus mutation.

The watch paginates the existing official EC Search endpoint, resolves programme
and status labels only from the official Facet payload, deduplicates by exact
call/topic identity + programme + authority URL + semantic fingerprint, and
quarantines ambiguous identities fail-closed. It is intended to measure source
coverage and prioritise subsequent exact adapters, not to create call facts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import re
import sys
from collections import defaultdict
from typing import Any, Iterable, Mapping

from funding_tenders_fetch import (
    FACET_ENDPOINT,
    SEARCH_ENDPOINT,
    _safe_json_post,
    default_query,
    flatten_search_payload,
    resolve_reference_label,
    topic_url,
)

SCHEMA = "PARTENER_EU_FT_PROGRAMME_COVERAGE_WATCH_V1"
PARSER_VERSION = "EU_DIRECT_FT_PROGRAMME_WATCH_V1"
SOURCE_FAMILY = "EU_DIRECT"
PROGRAMME_FAMILY = "BRUSSELS"
AUTHORITY_CLASS = "EU_COMMISSION_FUNDING_TENDERS"
DIRECT_CALL_TYPES = {"1", "2"}
PORTAL_ONLY_TYPES = {"8"}
MAX_PAGE_SIZE = 25
MAX_PAGES = 8


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def _scalar(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        value = next((item for item in value if item not in (None, "")), None)
    if isinstance(value, dict):
        for key in ("value", "id", "code", "key", "label", "name"):
            if value.get(key) not in (None, ""):
                return _scalar(value.get(key))
        return None
    text = " ".join(str(value).split()).strip()
    return text or None


def _record_identifier(record: Mapping[str, Any]) -> str | None:
    for key in ("identifier", "topicAbbreviation", "topicIdentifier", "callIdentifier"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_type(record: Mapping[str, Any]) -> str | None:
    return _scalar(record.get("type"))


def _record_programme_reference(record: Mapping[str, Any]) -> str | None:
    for key in ("frameworkProgramme", "programme", "programmeReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_status_code(record: Mapping[str, Any]) -> str | None:
    value = _scalar(record.get("status"))
    return value if value and value.isdigit() else None


def _record_call_identifier(record: Mapping[str, Any]) -> str | None:
    for key in ("callIdentifier", "callId", "callReference"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _record_title(record: Mapping[str, Any]) -> str | None:
    for key in ("title", "content", "topicTitle", "name"):
        value = _scalar(record.get(key))
        if value:
            return value
    return None


def _framework_programme_map(payload: Any) -> dict[str, str]:
    if not isinstance(payload, dict):
        raise ValueError("official Facet response must be an object")
    facets = payload.get("facets")
    if not isinstance(facets, list):
        raise ValueError("official Facet response is missing facets")
    matches = [f for f in facets if isinstance(f, dict) and f.get("name") == "frameworkProgramme"]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one frameworkProgramme facet, found {len(matches)}")
    values = matches[0].get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("frameworkProgramme facet has no values")
    result: dict[str, str] = {}
    for row in values:
        if not isinstance(row, dict):
            continue
        code = _scalar(row.get("rawValue"))
        label = _scalar(row.get("value"))
        if not code or not label or label == code or label.isdigit():
            continue
        previous = result.get(code)
        if previous and previous != label:
            raise ValueError(f"ambiguous official programme label for {code}: {previous!r} vs {label!r}")
        result[code] = label
    if not result:
        raise ValueError("frameworkProgramme facet yielded no human-readable labels")
    return result


def classify_programme_family(label: str) -> str:
    """Non-authorizing taxonomy derived from the official programme label text."""
    token = re.sub(r"[^a-z0-9]+", " ", label.casefold()).strip()
    rules = (
        ("HORIZON_EUROPE", ("horizon europe",)),
        ("DIGITAL_EUROPE", ("digital europe",)),
        ("LIFE", ("life programme", "programme for environment and climate action")),
        ("CERV", ("citizens equality rights and values", "rights and values programme")),
        ("SINGLE_MARKET_PROGRAMME", ("single market programme",)),
        ("CEF", ("connecting europe facility",)),
        ("INNOVATION_FUND", ("innovation fund",)),
        ("EU4HEALTH", ("eu4health",)),
        ("CREATIVE_EUROPE", ("creative europe",)),
        ("ERASMUS_PLUS", ("erasmus",)),
    )
    for family, needles in rules:
        if any(needle in token for needle in needles):
            return family
    return "OTHER_EU_DIRECT"


def _instrument_family(identifier: str, programme_family: str) -> str | None:
    # Discovery taxonomy only. Never authorizes programme identity or material facts.
    if programme_family == "HORIZON_EUROPE" and identifier.upper().startswith("HORIZON-EIC-"):
        return "EIC"
    return None


def _candidate_semantics(record: Mapping[str, Any], programme_label: str, status_label: str) -> dict[str, Any]:
    identifier = _record_identifier(record)
    programme_reference = _record_programme_reference(record)
    if not identifier or not programme_reference:
        raise ValueError("candidate lacks identifier/programme reference")
    authority_url = topic_url(identifier)
    programme_family = classify_programme_family(programme_label)
    semantics = {
        "identifier": identifier,
        "call_identifier": _record_call_identifier(record),
        "record_type": _record_type(record),
        "programme_reference": programme_reference,
        "programme_label": programme_label,
        "programme_family_candidate": programme_family,
        "instrument_family_candidate": _instrument_family(identifier, programme_family),
        "status_code": _record_status_code(record),
        "status_label_candidate": status_label,
        "title_candidate": _record_title(record),
        "authority_url_candidate": authority_url,
    }
    return semantics


def build_watch(
    search_pages: Iterable[Any],
    facet_payload: Any,
    *,
    fetched_at: str,
    run_id: str,
    page_receipts: list[dict[str, Any]],
    facet_receipt: dict[str, Any],
) -> dict[str, Any]:
    programme_labels = _framework_programme_map(facet_payload)
    rows: list[dict[str, Any]] = []
    for payload in search_pages:
        rows.extend(flatten_search_payload(payload))

    candidates: list[dict[str, Any]] = []
    quarantined: list[dict[str, Any]] = []
    for record in rows:
        record_type = _record_type(record)
        identifier = _record_identifier(record)
        if record_type in PORTAL_ONLY_TYPES:
            quarantined.append({
                "identifier_candidate": identifier,
                "record_type": record_type,
                "reason": "PORTAL_OR_CASCADE_TYPE_REQUIRES_DEDICATED_OPPORTUNITY_CLASS",
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        if record_type not in DIRECT_CALL_TYPES:
            quarantined.append({
                "identifier_candidate": identifier,
                "record_type": record_type,
                "reason": "UNSUPPORTED_RECORD_TYPE",
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        programme_reference = _record_programme_reference(record)
        status_code = _record_status_code(record)
        if not identifier or not programme_reference or not status_code:
            quarantined.append({
                "identifier_candidate": identifier,
                "record_type": record_type,
                "reason": "MISSING_IDENTITY_PROGRAMME_OR_STATUS_CODE",
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        programme_label = programme_labels.get(programme_reference)
        if not programme_label:
            quarantined.append({
                "identifier_candidate": identifier,
                "record_type": record_type,
                "programme_reference": programme_reference,
                "reason": "PROGRAMME_REFERENCE_UNRESOLVED_IN_OFFICIAL_FACET",
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        status_label = resolve_reference_label([facet_payload], status_code)
        if not status_label:
            quarantined.append({
                "identifier_candidate": identifier,
                "record_type": record_type,
                "status_code": status_code,
                "reason": "STATUS_REFERENCE_UNRESOLVED_IN_OFFICIAL_FACET",
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        semantics = _candidate_semantics(record, programme_label, status_label)
        fingerprint = sha256_json(semantics)
        candidates.append({
            **semantics,
            "semantic_fingerprint": fingerprint,
            "dedup_key": sha256_json({
                "identifier": semantics["identifier"],
                "programme_reference": semantics["programme_reference"],
                "authority_url": semantics["authority_url_candidate"],
                "semantic_fingerprint": fingerprint,
            }),
        })

    by_identifier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in candidates:
        by_identifier[row["identifier"]].append(row)

    accepted: list[dict[str, Any]] = []
    conflicts: list[dict[str, Any]] = []
    exact_duplicate_count = 0
    for identifier, group in sorted(by_identifier.items()):
        unique: dict[str, dict[str, Any]] = {row["dedup_key"]: row for row in group}
        exact_duplicate_count += len(group) - len(unique)
        variants = list(unique.values())
        semantic_keys = {
            (row["programme_reference"], row["authority_url_candidate"], row["semantic_fingerprint"])
            for row in variants
        }
        if len(semantic_keys) != 1:
            conflicts.append({
                "identifier": identifier,
                "reason": "CROSS_PROGRAMME_OR_SEMANTIC_IDENTITY_CONFLICT",
                "variant_count": len(variants),
                "variant_dedup_keys": sorted(row["dedup_key"] for row in variants),
                "material_fact_use": False,
                "open_call_authorized": False,
            })
            continue
        row = variants[0]
        accepted.append({
            **row,
            "source_family": SOURCE_FAMILY,
            "programme_family": PROGRAMME_FAMILY,
            "authority_class": AUTHORITY_CLASS,
            "observation_state": "PROGRAMME_WATCH_DISCOVERY_NON_AUTHORIZING",
            "authority_url_verified": False,
            "exact_topic_readback_required": True,
            "semantic_reconciliation_required": True,
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

    family_counts: dict[str, int] = defaultdict(int)
    status_counts: dict[str, int] = defaultdict(int)
    for row in accepted:
        family_counts[row["programme_family_candidate"]] += 1
        status_counts[row["status_label_candidate"]] += 1

    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "programme_family": PROGRAMME_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "fetched_at": fetched_at,
        "run_id": run_id,
        "page_receipts": page_receipts,
        "facet_receipt": facet_receipt,
        "records": accepted,
        "conflicts": conflicts,
        "quarantined_records": quarantined,
        "programme_family_counts": dict(sorted(family_counts.items())),
        "status_candidate_counts": dict(sorted(status_counts.items())),
        "stats": {
            "raw_search_records": len(rows),
            "accepted_candidates": len(accepted),
            "exact_duplicates_removed": exact_duplicate_count,
            "conflict_groups_excluded": len(conflicts),
            "quarantined_records": len(quarantined),
            "unique_programme_families": len(family_counts),
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
        "publication_effect": "NONE",
        "canonical_corpus_mutation": False,
        "missing_for_material_call": [
            "EXACT_CURRENT_TOPIC_READBACK",
            "EXACT_CURRENT_AUTHORITY_STATUS",
            "SEMANTIC_RECONCILIATION",
            "FIELD_SCOPED_MATERIAL_ADMISSION",
        ],
        "rollback": "Discard this programme-watch evidence; no canonical/public/distribution state was mutated.",
    }


def validate_watch(watch: Mapping[str, Any]) -> None:
    if watch.get("schema") != SCHEMA:
        raise ValueError("programme watch schema mismatch")
    if watch.get("source_family") != SOURCE_FAMILY or watch.get("programme_family") != PROGRAMME_FAMILY:
        raise ValueError("programme watch source/programme family mismatch")
    for key in (
        "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
        "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        "canonical_corpus_mutation",
    ):
        if watch.get(key) is not False:
            raise ValueError(f"programme watch attempted authorization: {key}")
    if watch.get("publication_effect") != "NONE" or watch.get("market_intelligence_only") is not True:
        raise ValueError("programme watch crossed non-authorizing boundary")
    if not isinstance(watch.get("page_receipts"), list) or not watch.get("page_receipts"):
        raise ValueError("programme watch has no immutable page receipts")
    facet_receipt = watch.get("facet_receipt")
    if not isinstance(facet_receipt, dict) or not facet_receipt.get("sha256"):
        raise ValueError("programme watch has no bound official Facet receipt")
    for row in watch.get("records") or []:
        if row.get("authority_url_verified") is not False:
            raise ValueError(f"watch candidate self-verified authority: {row.get('identifier')}")
        for key in (
            "material_fact_use", "open_call_authorized", "deadline_authorized", "budget_authorized",
            "eligibility_authorized", "publish_authorized", "distribution_authorized", "call_alert_authorized",
        ):
            if row.get(key) is not False:
                raise ValueError(f"watch candidate attempted authorization: {row.get('identifier')} {key}")


def collect_live(*, output_dir: pathlib.Path, page_size: int = MAX_PAGE_SIZE, max_pages: int = MAX_PAGES) -> dict[str, Any]:
    if page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
    if max_pages < 1 or max_pages > MAX_PAGES:
        raise ValueError(f"max_pages must be between 1 and {MAX_PAGES}")
    output_dir.mkdir(parents=True, exist_ok=True)
    fetched_at = utc_now()
    run_id = "EU-DIRECT-FT-WATCH-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    query = default_query()
    common_parts = {
        "query": query,
        "languages": ["en"],
        "sort": {"field": "sortStatus", "order": "ASC"},
    }

    search_pages: list[Any] = []
    page_receipts: list[dict[str, Any]] = []
    seen_page_hashes: set[str] = set()
    stop_reason = "MAX_PAGES_REACHED"
    for page_number in range(1, max_pages + 1):
        payload, raw, receipt = _safe_json_post(
            SEARCH_ENDPOINT,
            text="***",
            page_size=page_size,
            page_number=page_number,
            parts=common_parts,
        )
        page_receipt = {**receipt, "page_number": page_number}
        if receipt["sha256"] in seen_page_hashes:
            stop_reason = "REPEATED_PAGE_SHA_FAIL_SAFE_STOP"
            break
        seen_page_hashes.add(receipt["sha256"])
        search_pages.append(payload)
        page_receipts.append(page_receipt)
        (output_dir / f"search-response-page-{page_number}.json").write_bytes(raw)
        page_rows = flatten_search_payload(payload)
        if not page_rows:
            stop_reason = "EMPTY_PAGE"
            break
        if len(page_rows) < page_size:
            stop_reason = "PARTIAL_LAST_PAGE"
            break

    facet_payload, facet_raw, facet_receipt = _safe_json_post(
        FACET_ENDPOINT,
        text="***",
        page_size=page_size,
        page_number=1,
        parts={"query": query, "languages": ["en"]},
    )
    (output_dir / "facet-response-broad.json").write_bytes(facet_raw)
    facet_receipt = {**facet_receipt, "facet_name_required": "frameworkProgramme"}

    watch = build_watch(
        search_pages,
        facet_payload,
        fetched_at=fetched_at,
        run_id=run_id,
        page_receipts=page_receipts,
        facet_receipt=facet_receipt,
    )
    watch["pagination"] = {
        "page_size": page_size,
        "max_pages": max_pages,
        "pages_captured": len(search_pages),
        "stop_reason": stop_reason,
    }
    validate_watch(watch)
    (output_dir / "programme-watch.json").write_text(
        json.dumps(watch, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return watch


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=pathlib.Path, required=True)
    parser.add_argument("--page-size", type=int, default=MAX_PAGE_SIZE)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    args = parser.parse_args()
    watch = collect_live(output_dir=args.output_dir, page_size=args.page_size, max_pages=args.max_pages)
    print(json.dumps({
        **watch["stats"],
        "programme_family_counts": watch["programme_family_counts"],
        "status_candidate_counts": watch["status_candidate_counts"],
        "pagination": watch["pagination"],
        "open_call_authorized": watch["open_call_authorized"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"FAIL EU direct F&T programme watch: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
