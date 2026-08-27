#!/usr/bin/env python3
"""Unified structured-primary-alert runtime with pluggable evidence parsers.

This entrypoint keeps source-specific evidence extraction behind generic parser
contracts. It reuses the established traffic/water collectors and adds the
instance-agnostic district-heat interruption parser without granting reader-copy
or publication authority. The electricity schedule parser is validated here but
is deliberately not routed until its official weekly-document fetch/extraction
adapter passes live acceptance. Disabled sources remain disabled and are never
fetched.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

CORE = Path(__file__).resolve().parent
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

import primary_signal_verifier as primary  # noqa: E402
import signal_radar as radar  # noqa: E402
import structured_alert_ingest as base  # noqa: E402
import structured_electricity_interruption_parser as electricity  # noqa: E402
import structured_heat_interruption_parser as heat  # noqa: E402


def normalize_heat_events(
    events: list[dict[str, Any]],
    source: dict[str, Any],
    listing_url: str,
) -> list[dict[str, Any]]:
    """Attach source provenance to already-validated evidence-only heat events."""
    rows: list[dict[str, Any]] = []
    for event in events:
        event_key = str(event.get("event_key") or "").strip()
        if not event_key:
            continue
        structured = event.get("structured") or {}
        if structured.get("utility") != "district_heat":
            continue
        row = {
            "event_id": event_key,
            "source_id": source["id"],
            "source_name": source["name"],
            "source_tier": source["source_tier"],
            "source_url": listing_url,
            "parser": heat.PARSER_ID,
            "event_start": event["event_start"],
            "event_end": event["event_end"],
            "source_time_basis": event["source_time_basis"],
            "body_sha256": event["body_sha256"],
            "structured": structured,
            "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
            "reader_copy_generated": False,
        }
        rows.append(row)
    rows.sort(key=lambda row: row["event_start"])
    return rows


def collect_heat_interruption_source(
    source: dict[str, Any],
    tz: ZoneInfo,
    now: datetime,
) -> dict[str, Any]:
    try:
        listing_html, listing_url = radar.fetch(str(source["url"]), max_bytes=2_500_000, timeout=16)
    except Exception as exc:
        return {
            "source_id": source.get("id"),
            "status": "DEGRADED",
            "error": f"{type(exc).__name__}: {exc}",
            "events": [],
        }

    plain = primary.extract_text(listing_html)
    parsed, candidates = heat.parse_heat_interruption_listing(
        plain,
        tz,
        now,
        planning_horizon_hours=int(source.get("planning_horizon_hours") or 336),
        expiry_grace_hours=int(source.get("expiry_grace_hours") or 1),
        max_candidates=int(source.get("max_listing_candidates") or 40),
    )
    return {
        "source_id": source["id"],
        "status": "PASS",
        "listing_url": listing_url,
        "candidates": candidates,
        "events": normalize_heat_events(parsed, source, listing_url),
    }


def collect_source(
    instance: dict[str, Any],
    source: dict[str, Any],
    tz: ZoneInfo,
    now: datetime,
) -> dict[str, Any]:
    # Preserve the existing fail-closed disabled-source contract before routing.
    if source.get("enabled") is not True:
        return {"source_id": source.get("id"), "status": "DISABLED", "events": []}
    if source.get("parser") == heat.PARSER_ID:
        return collect_heat_interruption_source(source, tz, now)
    # Electricity sources stay disabled until the weekly-document adapter is
    # present. If one is enabled prematurely, base.collect_source fails closed on
    # the unsupported parser instead of interpreting a listing page as evidence.
    return base.collect_source(instance, source, tz, now)


def run(instance_id: str, output: Path) -> dict[str, Any]:
    instance, pack, tz = base.instance_and_pack(instance_id)
    now = datetime.now(tz)
    observations = [collect_source(instance, source, tz, now) for source in pack.get("sources") or []]
    events = [event for row in observations for event in row.get("events") or []]
    doc = {
        "schema_version": "1.0",
        "contract": "LOCAL_NEWS_OS_STRUCTURED_ALERT_EVENTS_V1",
        "instance_id": instance_id,
        "generated_at": now.isoformat(timespec="seconds"),
        "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
        "events_are_reader_stories": False,
        "event_count": len(events),
        "events": events,
        "sources": observations,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return doc


def self_test() -> int:
    # Existing traffic/water contracts must remain green under the unified runtime.
    assert base.self_test() == 0
    assert heat.self_test() == 0
    assert electricity.self_test() == 0

    tz = ZoneInfo("Europe/Bucharest")
    sample = """
    Anunt public. Operatorul anunta intreruperea furnizarii agentului termic
    sub forma de apa fierbinte si apa calda de consum, din data de 29.08.2026,
    ora 0900 pana in data de 30.08.2026, ora 1800, pentru lucrari programate.
    Consumatorii racordati si afectati de aceasta oprire sunt: PT 1; PT 2.
    Ne cerem scuze pentru disconfort.
    """
    parsed, candidates = heat.parse_heat_interruption_listing(
        sample,
        tz,
        datetime(2026, 8, 27, 19, 0, tzinfo=tz),
    )
    assert candidates == 1 and len(parsed) == 1
    source = {
        "id": "heat-test",
        "name": "Operator termic test",
        "source_tier": "T1",
        "parser": heat.PARSER_ID,
    }
    rows = normalize_heat_events(parsed, source, "https://heat.example/anunturi")
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"] == "heat-test"
    assert row["source_url"] == "https://heat.example/anunturi"
    assert row["source_time_basis"] == "official_service_window"
    assert row["structured"]["utility"] == "district_heat"
    assert row["reader_copy_generated"] is False
    assert row["publication_authority"] == "PRIMARY_STRUCTURED_EVENT_ONLY"
    print("LOCAL NEWS OS structured alert runtime self-test: PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if not args.instance or not args.output:
        parser.error("--instance and --output are required")
    doc = run(args.instance, Path(args.output))
    print(json.dumps({
        "status": "PASS",
        "event_count": doc["event_count"],
        "publication_authority": doc["publication_authority"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
