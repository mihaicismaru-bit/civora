#!/usr/bin/env python3
"""Fail-closed temporal gate for ETA Vâlcea service journalism.

The gate reconciles two already-bounded first-party ETA evidence layers:
- current communications detail evidence; and
- historical detail evidence with current-index reconciliation.

It gives newsroom tooling an explicit temporal vocabulary without granting new
publication authority. HISTORICAL_CONTEXT may only support date-bounded context.
CURRENT_ANNOUNCEMENT means ETA published a recent first-party communication; it
does not mean the described service is operational now. CURRENT_OPERATIONAL_STATUS
is intentionally unavailable from these inputs and requires a separate live,
first-party operational attestation.
"""
from __future__ import annotations

import argparse
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from eta_valcea_transport_detail_evidence import (
    _sha256_text,
    build_live_receipt as build_current_detail_receipt,
)
from eta_valcea_transport_historical_detail_reconciliation import (
    build_live_receipt as build_historical_detail_receipt,
)

SCHEMA = "ETA_VALCEA_SERVICE_NEWS_TEMPORAL_GATE_V1"
PARSER_VERSION = "ETA_VALCEA_SERVICE_NEWS_TEMPORAL_GATE_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_TRANSPORT_EVIDENCE_TEMPORAL_RECONCILIATION"
OBSERVATION_STATE = "EDITORIAL_TEMPORAL_RECONCILIATION_NON_AUTHORIZING"
ANNOUNCEMENT_MAX_AGE_DAYS = 7

TEMPORAL_LANES = {
    "HISTORICAL_CONTEXT",
    "CURRENT_ANNOUNCEMENT",
    "CURRENT_OPERATIONAL_STATUS",
    "UNRESOLVED_TEMPORAL_REFERENCE",
}

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "current_index_presence_proves_currentness": False,
    "announcement_equals_operational_status": False,
    "historical_state_promoted_to_current": False,
    "current_operational_status_authorized": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "passenger_entitlement_current_authorized": False,
    "service_disruption_current_authorized": False,
    "event_service_current_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}

MONTHS = {
    "ian": 1,
    "ianuarie": 1,
    "feb": 2,
    "februarie": 2,
    "mar": 3,
    "martie": 3,
    "apr": 4,
    "aprilie": 4,
    "mai": 5,
    "iun": 6,
    "iunie": 6,
    "iul": 7,
    "iulie": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "septembrie": 9,
    "oct": 10,
    "octombrie": 10,
    "nov": 11,
    "noiembrie": 11,
    "dec": 12,
    "decembrie": 12,
}


def _publication_date(value: str | None) -> date | None:
    if not value:
        return None
    numeric = re.search(r"\b(0?[1-9]|[12]\d|3[01])[.\-/](0?[1-9]|1[0-2])[.\-/](20\d{2})\b", value)
    if numeric:
        try:
            return date(int(numeric.group(3)), int(numeric.group(2)), int(numeric.group(1)))
        except ValueError:
            return None
    textual = re.search(r"\b(0?[1-9]|[12]\d|3[01])\s+([A-Za-zĂÂÎȘŞȚŢăâîșşțţ]+)\s+(20\d{2})\b", value)
    if not textual:
        return None
    token = textual.group(2).casefold().rstrip(".")
    month = MONTHS.get(token)
    if month is None:
        return None
    try:
        return date(int(textual.group(3)), month, int(textual.group(1)))
    except ValueError:
        return None


def _temporal_hash(item: dict[str, Any]) -> str:
    basis = json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(basis)


def _historical_record(item: dict[str, Any]) -> dict[str, Any]:
    source_date = item.get("publication_date_text") or f"ARCHIVE_YEAR:{item.get('archive_year', 'UNKNOWN')}"
    record = {
        "temporal_lane": "HISTORICAL_CONTEXT",
        "origin": "ETA_HISTORICAL_DETAIL",
        "topic_class": str(item.get("topic_class") or ""),
        "title": str(item.get("visible_title") or item.get("index_title") or ""),
        "detail_url": str(item.get("detail_url") or ""),
        "detail_sha256": str(item.get("detail_sha256") or ""),
        "source_date": source_date,
        "historical_archive_year": item.get("archive_year"),
        "current_reconciliation_state": str(
            (item.get("current_reconciliation") or {}).get("reconciliation_state") or "UNRESOLVED"
        ),
        "current_operational_status": "UNRESOLVED_REQUIRES_SEPARATE_FIRST_PARTY_OPERATIONAL_VERIFICATION",
        "editorial_instruction": (
            "CONTEXT_ONLY_ATTRIBUTE_TO_ETA_WITH_EXPLICIT_SOURCE_DATE;"
            "DO_NOT_USE_PRESENT_TENSE_FOR_SERVICE_STATUS"
        ),
        "reader_service_status_use": False,
    }
    record["temporal_evidence_sha256"] = _temporal_hash(record)
    return record


def _current_record(item: dict[str, Any], observed_date: date) -> dict[str, Any]:
    parsed = _publication_date(item.get("publication_date_text"))
    if parsed is None:
        lane = "UNRESOLVED_TEMPORAL_REFERENCE"
        age_days: int | None = None
        instruction = "DO_NOT_USE_AS_CURRENT_OR_HISTORICAL_FACT_UNTIL_PUBLICATION_DATE_IS_RESOLVED"
    else:
        age_days = (observed_date - parsed).days
        if age_days < 0:
            lane = "UNRESOLVED_TEMPORAL_REFERENCE"
            instruction = "FUTURE_DATED_SOURCE_HOLD_FOR_DATE_REVIEW"
        elif age_days <= ANNOUNCEMENT_MAX_AGE_DAYS:
            lane = "CURRENT_ANNOUNCEMENT"
            instruction = (
                "ATTRIBUTE_AS_RECENT_ETA_ANNOUNCEMENT_WITH_EXPLICIT_PUBLICATION_DATE;"
                "DO_NOT_EQUATE_ANNOUNCEMENT_WITH_LIVE_SERVICE_STATUS"
            )
        else:
            lane = "HISTORICAL_CONTEXT"
            instruction = (
                "CURRENT_INDEX_REFERENCE_IS_OLDER_THAN_ANNOUNCEMENT_WINDOW;"
                "USE_ONLY_AS_DATE_BOUND_CONTEXT_UNLESS_SEPARATELY_REVERIFIED"
            )
    record = {
        "temporal_lane": lane,
        "origin": "ETA_CURRENT_COMMUNICATIONS_DETAIL",
        "topic_class": str(item.get("topic_class") or ""),
        "title": str(item.get("visible_title") or item.get("index_title") or ""),
        "detail_url": str(item.get("detail_url") or ""),
        "detail_sha256": str(item.get("detail_sha256") or ""),
        "publication_date_text": item.get("publication_date_text"),
        "effective_date_text": item.get("effective_date_text"),
        "announcement_age_days": age_days,
        "current_operational_status": "UNRESOLVED_REQUIRES_SEPARATE_FIRST_PARTY_OPERATIONAL_VERIFICATION",
        "editorial_instruction": instruction,
        "reader_service_status_use": False,
    }
    record["temporal_evidence_sha256"] = _temporal_hash(record)
    return record


def _base_payload(status: str, observed_at: datetime) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "status": status,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "observed_at": observed_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "announcement_max_age_days": ANNOUNCEMENT_MAX_AGE_DAYS,
        "temporal_lanes": sorted(TEMPORAL_LANES),
        "historical_context_count": 0,
        "current_announcement_count": 0,
        "current_operational_status_count": 0,
        "unresolved_temporal_reference_count": 0,
        "records": [],
        "holds": [],
        "limitations": {
            "current_index_presence_does_not_prove_currentness": True,
            "recent_publication_does_not_prove_service_is_operational_now": True,
            "effective_date_text_alone_does_not_prove_live_status": True,
            "historical_context_requires_explicit_date_attribution": True,
            "current_operational_status_requires_separate_live_first_party_attestation": True,
            "writer_and_fact_kernel_remain_downstream_and_unauthorized": True,
        },
        "interpretation": (
            "HISTORICAL_CONTEXT_AND_CURRENT_ANNOUNCEMENT_ARE_EDITORIAL_TEMPORAL_CLASSES_ONLY;"
            "CURRENT_OPERATIONAL_STATUS_REMAINS_UNAVAILABLE_WITHOUT_SEPARATE_LIVE_ATTESTATION"
        ),
        **NON_AUTHORIZING_FLAGS,
    }


def build_receipt(
    *,
    observed_at: datetime | None = None,
    current_receipt: dict[str, Any] | None = None,
    historical_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("observed_at_must_be_timezone_aware")

    current = current_receipt if current_receipt is not None else build_current_detail_receipt()
    historical = historical_receipt if historical_receipt is not None else build_historical_detail_receipt()
    if current.get("status") != "PASS" or historical.get("status") != "PASS":
        payload = _base_payload("HOLD_UPSTREAM_ETA_EVIDENCE_NOT_PASS_NON_AUTHORIZING", now)
        payload["holds"] = [{
            "state": "HOLD_UPSTREAM_ETA_EVIDENCE_NOT_PASS_NON_AUTHORIZING",
            "reason": f"current={current.get('status')};historical={historical.get('status')}",
        }]
        payload["current_detail_run_id"] = current.get("run_id")
        payload["historical_detail_run_id"] = historical.get("run_id")
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    records = [_historical_record(item) for item in historical.get("details", [])]
    records.extend(_current_record(item, now.date()) for item in current.get("details", []))
    records.sort(key=lambda item: (item["temporal_lane"], item["detail_url"], item["title"].casefold()))

    payload = _base_payload("PASS" if records else "HOLD_NO_TEMPORAL_EVIDENCE", now)
    payload["current_detail_run_id"] = current.get("run_id")
    payload["historical_detail_run_id"] = historical.get("run_id")
    payload["records"] = records
    payload["historical_context_count"] = sum(item["temporal_lane"] == "HISTORICAL_CONTEXT" for item in records)
    payload["current_announcement_count"] = sum(item["temporal_lane"] == "CURRENT_ANNOUNCEMENT" for item in records)
    payload["current_operational_status_count"] = sum(
        item["temporal_lane"] == "CURRENT_OPERATIONAL_STATUS" for item in records
    )
    payload["unresolved_temporal_reference_count"] = sum(
        item["temporal_lane"] == "UNRESOLVED_TEMPORAL_REFERENCE" for item in records
    )
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    assert _publication_date("Publicat la: 30 Ian 2026") == date(2026, 1, 30)
    assert _publication_date("Publicat la: 02.09.2026") == date(2026, 9, 2)
    assert _publication_date("missing") is None

    observed = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    current = {
        "status": "PASS",
        "run_id": "c" * 24,
        "details": [
            {
                "topic_class": "ROUTE_CHANGE",
                "visible_title": "Deviere recentă",
                "detail_url": "https://eta-bus.ro/comunicate/deviere-recenta",
                "detail_sha256": "a" * 64,
                "publication_date_text": "Publicat la: 01 Sep 2026",
                "effective_date_text": "începând cu data de 02/09/2026",
            },
            {
                "topic_class": "FARE_TICKETING",
                "visible_title": "Tarife vechi",
                "detail_url": "https://eta-bus.ro/comunicate/tarife-vechi",
                "detail_sha256": "b" * 64,
                "publication_date_text": "Publicat la: 30 Ian 2026",
                "effective_date_text": "începând cu data de 01/02/2026",
            },
            {
                "topic_class": "SERVICE_DISRUPTION",
                "visible_title": "Fără dată",
                "detail_url": "https://eta-bus.ro/comunicate/fara-data",
                "detail_sha256": "d" * 64,
                "publication_date_text": None,
                "effective_date_text": None,
            },
        ],
    }
    historical = {
        "status": "PASS",
        "run_id": "h" * 24,
        "details": [
            {
                "topic_class": "EVENT_TRANSPORT",
                "visible_title": "Deep Forest Fest 2025",
                "detail_url": "https://eta-bus.ro/comunicate/deep-forest-fest-2025",
                "detail_sha256": "e" * 64,
                "publication_date_text": "Publicat la: 1 Aug 2025",
                "archive_year": 2025,
                "current_reconciliation": {
                    "reconciliation_state": "NO_CURRENT_INDEX_MATCH_HISTORICAL_ONLY"
                },
            }
        ],
    }
    payload = build_receipt(observed_at=observed, current_receipt=current, historical_receipt=historical)
    assert payload["status"] == "PASS"
    assert payload["current_announcement_count"] == 1
    assert payload["historical_context_count"] == 2
    assert payload["unresolved_temporal_reference_count"] == 1
    assert payload["current_operational_status_count"] == 0
    assert all(item["reader_service_status_use"] is False for item in payload["records"])
    assert all(item["current_operational_status"].startswith("UNRESOLVED_") for item in payload["records"])
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["temporal_evidence_sha256"]) for item in payload["records"])
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())
    print("ETA Vâlcea service-news temporal gate self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="ETA Vâlcea service-news temporal gate")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")
    payload = build_receipt()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
