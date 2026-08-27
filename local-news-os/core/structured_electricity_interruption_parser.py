#!/usr/bin/env python3
"""Parse explicit planned electricity interruption schedules into evidence-only events.

The parser is instance-agnostic and publication-neutral. It consumes plain text
extracted from an official operator schedule and admits only rows that expose an
explicit calendar date, numeric interruption window, locality and affected
scope. A year may be inherited only from an explicit weekly range printed in
the source document; crawl time is never used as source freshness.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARSER_ID = "RO_UTILITY_ELECTRICITY_INTERRUPTION_LISTING_V1"


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _explicit_schedule_range(text: str) -> tuple[int, int, int, int, int] | None:
    """Return start day/month, end day/month and explicit end year."""
    match = re.search(
        r"\b(\d{1,2})[./](\d{1,2})\s*[-–—]\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})\b",
        text,
    )
    if not match:
        return None
    return tuple(int(match.group(i)) for i in range(1, 6))  # type: ignore[return-value]


def _year_for_row(month: int, explicit_year: str | None, text: str) -> int | None:
    if explicit_year:
        return int(explicit_year)
    window = _explicit_schedule_range(text)
    if not window:
        return None
    _, start_month, _, end_month, end_year = window
    if start_month > end_month and month >= start_month:
        return end_year - 1
    return end_year


def _clock(hour: str, minute: str, *, day: int, month: int, year: int, tz: ZoneInfo) -> datetime | None:
    try:
        h = int(hour)
        m = int(minute)
        if h > 23 or m > 59:
            return None
        return datetime(year, month, day, h, m, tzinfo=tz)
    except ValueError:
        return None


def _split_fields(value: str) -> list[str]:
    """Split only on table-like separators; prose is deliberately rejected."""
    fields = [clean(part).strip(" |;,-") for part in re.split(r"\s*\|\s*|\t+|\s{2,}", value)]
    return [field for field in fields if field]


def _candidate_lines(text: str) -> list[str]:
    # Preserve row boundaries from PDF/HTML text extraction. Wrapped prose that
    # loses table structure must fail closed rather than invent locality/scope.
    return [line.strip() for line in str(text or "").replace("\r", "\n").split("\n") if line.strip()]


def parse_electricity_interruption_text(
    text: str,
    tz: ZoneInfo,
    now: datetime,
    *,
    planning_horizon_hours: int = 336,
    expiry_grace_hours: int = 1,
    max_candidates: int = 120,
) -> tuple[list[dict[str, Any]], int]:
    """Return evidence-only planned-electricity-interruption rows."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    horizon = timedelta(hours=int(planning_horizon_hours))
    grace = timedelta(hours=int(expiry_grace_hours))
    events: list[dict[str, Any]] = []
    candidates = 0
    seen: set[str] = set()

    row_pattern = re.compile(
        r"(?:^|\b)(\d{1,2})[./](\d{1,2})(?:[./](20\d{2}))?\b\s*(?:\||\t|\s{2,})+"
        r"([0-2]?\d)\s*[:.]\s*([0-5]\d)\s*[-–—]\s*([0-2]?\d)\s*[:.]\s*([0-5]\d)"
        r"(?:\s*(?:\||\t|\s{2,})+)(.+)$"
    )

    for line in _candidate_lines(text):
        if candidates >= int(max_candidates):
            break
        match = row_pattern.search(line)
        if not match:
            continue
        candidates += 1

        day = int(match.group(1))
        month = int(match.group(2))
        year = _year_for_row(month, match.group(3), text)
        if year is None:
            continue
        start = _clock(match.group(4), match.group(5), day=day, month=month, year=year, tz=tz)
        end = _clock(match.group(6), match.group(7), day=day, month=month, year=year, tz=tz)
        if not start or not end or end <= start:
            continue
        if end < now - grace or start > now + horizon:
            continue

        fields = _split_fields(match.group(8))
        if len(fields) < 2:
            continue
        locality, affected_scope = fields[0], " | ".join(fields[1:])
        if len(locality) < 2 or len(affected_scope) < 2:
            continue

        raw_row = clean(line)
        fingerprint = hashlib.sha256(
            "\n".join([start.isoformat(), end.isoformat(), locality, affected_scope, raw_row]).encode("utf-8")
        ).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)

        events.append(
            {
                "event_key": "utility-electricity-" + fingerprint[:20],
                "parser": PARSER_ID,
                "event_start": start.isoformat(timespec="minutes"),
                "event_end": end.isoformat(timespec="minutes"),
                "source_time_basis": "official_service_window",
                "body_sha256": hashlib.sha256(raw_row.encode("utf-8")).hexdigest(),
                "structured": {
                    "utility": "electricity",
                    "service_state": "scheduled_interruption",
                    "affected_locality": locality,
                    "affected_scope": affected_scope,
                },
                "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
                "reader_copy_generated": False,
            }
        )

    events.sort(key=lambda row: (row["event_start"], row["structured"]["affected_locality"]))
    return events, candidates


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    now = datetime(2026, 8, 27, 18, 0, tzinfo=tz)
    sample = """Valcea - Intreruperi 31.08 - 06.09.2026
Data  Interval orar de intrerupere  Localitatea  Zona de intrerupere
31.08  09:00 - 17:00  Ramnicu Valcea  PTAB 17, strada Exemplu
01.09  08:30 - 16:30  Bujoreni  sat Gura Vaii, PTA 3
20.08  09:00 - 12:00  Valcea  expirat
02.09  anunt fara interval  Localitate  zona
"""
    events, candidates = parse_electricity_interruption_text(sample, tz, now)
    assert candidates == 3
    assert len(events) == 2
    assert events[0]["event_start"] == "2026-08-31T09:00+03:00"
    assert events[0]["event_end"] == "2026-08-31T17:00+03:00"
    assert events[0]["structured"]["utility"] == "electricity"
    assert events[0]["structured"]["affected_locality"] == "Ramnicu Valcea"
    assert events[0]["structured"]["affected_scope"] == "PTAB 17, strada Exemplu"
    assert events[0]["reader_copy_generated"] is False

    year_rollover = """Valcea - Intreruperi 29.12 - 04.01.2026
29.12  09:00 - 11:00  Test  PTA 1
02.01  10:00 - 12:00  Test  PTA 2
"""
    rollover_now = datetime(2025, 12, 28, 12, 0, tzinfo=tz)
    rollover, _ = parse_electricity_interruption_text(year_rollover, tz, rollover_now, planning_horizon_hours=240)
    assert rollover[0]["event_start"].startswith("2025-12-29T09:00")
    assert rollover[1]["event_start"].startswith("2026-01-02T10:00")

    # No explicit year anywhere means no event: crawl time must never fill it.
    no_year, _ = parse_electricity_interruption_text(
        "31.08  09:00 - 17:00  Test  PTA 1", tz, now
    )
    assert no_year == []
    print("STRUCTURED_ELECTRICITY_INTERRUPTION_SELF_TEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
