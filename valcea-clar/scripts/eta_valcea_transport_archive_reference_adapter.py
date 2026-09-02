#!/usr/bin/env python3
"""Bounded historical ETA Râmnicu Vâlcea transport-reference discovery.

This adapter reads only explicit first-party ETA S.A. annual communication
archives and surfaces high-value historical mobility references. Archive
presence is context/discovery evidence only: it never proves that a route,
timetable, fare, entitlement, disruption or event service is current.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eta_valcea_transport_reference_adapter import (
    ALLOWED_HOSTS,
    _canonical_url,
    _fetch_source,
    _sha256_bytes,
    _sha256_text,
    _validate_final_source_url,
    parse_source_page,
)

SCHEMA = "ETA_VALCEA_TRANSPORT_ARCHIVE_REFERENCE_V1"
PARSER_VERSION = "ETA_VALCEA_TRANSPORT_ARCHIVE_REFERENCE_ADAPTER_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_LOCAL_PUBLIC_TRANSPORT_OPERATOR_ARCHIVE_INDEX"
OBSERVATION_STATE = "HISTORICAL_REFERENCE_ONLY_NON_AUTHORIZING"
SOURCE_KIND = "COMMUNIQUES_ARCHIVE"
ARCHIVE_SOURCES: tuple[tuple[int, str], ...] = (
    (2025, "https://eta-bus.ro/comunicate/2025"),
)
HIGH_VALUE_TOPICS = {
    "ROUTE_CHANGE",
    "SERVICE_DISRUPTION",
    "EVENT_TRANSPORT",
    "FARE_TICKETING",
    "PASSENGER_ENTITLEMENT",
    "ACCESSIBILITY",
}
MAX_REFERENCES = 32
CURRENTNESS_STATE = "HISTORICAL_ARCHIVE_REFERENCE_CURRENTNESS_UNRESOLVED"

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "currentness_inference_authorized": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "ticketing_current_authorized": False,
    "passenger_entitlement_current_authorized": False,
    "service_disruption_current_authorized": False,
    "event_service_current_authorized": False,
    "realtime_arrival_authorized": False,
    "same_event_dedupe_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}


@dataclass(frozen=True)
class ArchiveReference:
    title: str
    target_url: str
    topic_class: str
    source_page_url: str
    source_page_sha256: str
    archive_year: int
    evidence_sha256: str
    source_kind: str = SOURCE_KIND
    historical_reference: bool = True
    currentness_state: str = CURRENTNESS_STATE
    authority_class: str = AUTHORITY_CLASS
    observation_state: str = OBSERVATION_STATE
    parser_version: str = PARSER_VERSION


def _archive_reference(year: int, ref: Any) -> ArchiveReference:
    basis = json.dumps(
        {
            "source_family": SOURCE_FAMILY,
            "source_kind": SOURCE_KIND,
            "archive_year": year,
            "source_page_url": ref.source_page_url,
            "source_page_sha256": ref.source_page_sha256,
            "title": ref.title,
            "target_url": ref.target_url,
            "topic_class": ref.topic_class,
            "currentness_state": CURRENTNESS_STATE,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return ArchiveReference(
        title=ref.title,
        target_url=ref.target_url,
        topic_class=ref.topic_class,
        source_page_url=ref.source_page_url,
        source_page_sha256=ref.source_page_sha256,
        archive_year=year,
        evidence_sha256=_sha256_text(basis),
    )


def _validate_archive_source(year: int, source_url: str) -> None:
    canonical = _canonical_url(source_url)
    expected = f"https://eta-bus.ro/comunicate/{year}"
    if canonical != expected:
        raise ValueError("archive_source_not_exact_first_party_year_index")


def build_receipt(
    fetcher: Callable[[str], tuple[bytes, str]] = _fetch_source,
) -> dict[str, Any]:
    source_pages: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    references_by_target: dict[str, ArchiveReference] = {}

    for year, source_url in ARCHIVE_SOURCES:
        try:
            _validate_archive_source(year, source_url)
            raw, final_url = fetcher(source_url)
            _validate_final_source_url(source_url, final_url)
            page_hash = _sha256_bytes(raw)
            parsed = parse_source_page(source_url, raw)
            high_value = [ref for ref in parsed if ref.topic_class in HIGH_VALUE_TOPICS]
            for ref in high_value:
                candidate = _archive_reference(year, ref)
                current = references_by_target.get(candidate.target_url)
                if current is None or candidate.archive_year > current.archive_year:
                    references_by_target[candidate.target_url] = candidate
            source_pages.append(
                {
                    "source_kind": SOURCE_KIND,
                    "archive_year": year,
                    "source_page_url": source_url,
                    "final_url": _canonical_url(final_url),
                    "source_page_sha256": page_hash,
                    "bytes": len(raw),
                    "high_value_reference_count": len(high_value),
                    "status": "PASS",
                }
            )
        except (TimeoutError, RuntimeError, ValueError, OSError) as exc:
            failures.append(
                {
                    "source_kind": SOURCE_KIND,
                    "archive_year": str(year),
                    "source_page_url": source_url,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    selected = sorted(
        references_by_target.values(),
        key=lambda item: (item.archive_year, item.topic_class, item.title.casefold()),
        reverse=True,
    )[:MAX_REFERENCES]

    if len(source_pages) != len(ARCHIVE_SOURCES):
        status = "HOLD_ARCHIVE_SOURCE_FETCH_FAILED"
    elif not selected:
        status = "HOLD_NO_HIGH_VALUE_ARCHIVE_REFERENCES"
    else:
        status = "PASS"

    topic_counts: dict[str, int] = {}
    year_counts: dict[str, int] = {}
    for ref in selected:
        topic_counts[ref.topic_class] = topic_counts.get(ref.topic_class, 0) + 1
        key = str(ref.archive_year)
        year_counts[key] = year_counts.get(key, 0) + 1

    digest_basis = "|".join(
        f"{page['archive_year']}:{page['source_page_sha256']}" for page in source_pages
    ) + "|" + PARSER_VERSION
    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "coverage_note": "BOUNDED_FIRST_PARTY_ETA_ANNUAL_ARCHIVE_DISCOVERY_HIGH_VALUE_MOBILITY_ONLY",
        "status": status,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_id": _sha256_text(digest_basis)[:24],
        "archive_years": [year for year, _ in ARCHIVE_SOURCES],
        "source_page_count": len(source_pages),
        "reference_count": len(selected),
        "topic_counts": dict(sorted(topic_counts.items())),
        "year_counts": dict(sorted(year_counts.items())),
        "source_pages": source_pages,
        "references": [asdict(ref) for ref in selected],
        "failures": failures,
        "limitations": {
            "archive_reference_is_historical_context_not_current_status": True,
            "archive_publication_date_does_not_prove_current_service_state": True,
            "route_or_stop_change_requires_current_verification_before_use": True,
            "event_transport_schedule_must_not_be_reused_for_future_events": True,
            "fare_or_entitlement_requires_current_policy_reconciliation": True,
            "service_disruption_requires_current_status_verification": True,
            "sample_is_bounded_to_explicit_annual_archives": True,
        },
        **NON_AUTHORIZING_FLAGS,
    }


def self_test() -> int:
    fixture_2025 = b"""
    <html><body>
      <a href="/comunicate/raliul-valcii-2025">Raliul Valcii - program de circulatie</a>
      <a href="/comunicate/deviere-traseu-linia-5-09-09-2025">Deviere traseu - Linia 5</a>
      <a href="/comunicate/elevi-2025">Anunt privind eliberarea abonamentelor pentru elevi</a>
      <a href="/comunicate/deep-forest-fest-2025">Deep Forest Fest 2025</a>
      <a href="/comunicate/anunt-vanzare">Anunt vanzare autovehicul</a>
      <a href="/comunicate/2024">Comunicate 2024</a>
    </body></html>
    """

    def fake_fetch(url: str) -> tuple[bytes, str]:
        if url != "https://eta-bus.ro/comunicate/2025":
            raise AssertionError(url)
        return fixture_2025, url

    receipt = build_receipt(fake_fetch)
    if receipt["status"] != "PASS":
        raise AssertionError(receipt)
    if receipt["source_page_count"] != 1 or receipt["archive_years"] != [2025]:
        raise AssertionError(receipt)
    if receipt["reference_count"] != 4:
        raise AssertionError(receipt)
    topics = {ref["topic_class"] for ref in receipt["references"]}
    if topics != {"ROUTE_CHANGE", "PASSENGER_ENTITLEMENT", "EVENT_TRANSPORT"}:
        raise AssertionError(topics)
    if not all(ref["historical_reference"] is True for ref in receipt["references"]):
        raise AssertionError(receipt)
    if not all(ref["archive_year"] == 2025 for ref in receipt["references"]):
        raise AssertionError(receipt)
    if not all(ref["currentness_state"] == CURRENTNESS_STATE for ref in receipt["references"]):
        raise AssertionError(receipt)
    if any("vanzare" in ref["title"].casefold() for ref in receipt["references"]):
        raise AssertionError("administrative archive noise leaked")
    if receipt["material_fact_use"] or receipt["publication_authorized"]:
        raise AssertionError("non-authorizing boundary weakened")
    if receipt["currentness_inference_authorized"]:
        raise AssertionError("historical currentness boundary weakened")
    if not all(re.fullmatch(r"[0-9a-f]{64}", ref["evidence_sha256"]) for ref in receipt["references"]):
        raise AssertionError("archive evidence hash missing")

    def bad_fetch(_: str) -> tuple[bytes, str]:
        return fixture_2025, "https://example.invalid/comunicate/2025"

    held = build_receipt(bad_fetch)
    if held["status"] != "HOLD_ARCHIVE_SOURCE_FETCH_FAILED":
        raise AssertionError(held)

    print("ETA Vâlcea transport archive reference adapter self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--require-reference", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.self_test:
        return self_test()
    if not args.live_check:
        parser.error("choose --self-test or --live-check")

    receipt = build_receipt()
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)

    if receipt["status"] != "PASS":
        return 2
    if args.require_reference and receipt["reference_count"] < 1:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
