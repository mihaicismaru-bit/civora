#!/usr/bin/env python3
"""Parse explicit district-heating interruption notices into evidence-only events.

This module is deliberately instance-agnostic and publication-neutral. It accepts
plain text extracted from an official operator listing, admits only notices that
contain an explicit thermal-service interruption phrase, a numeric service
window and an explicit affected-consumer list or scope, and returns structured
evidence. Crawl time never becomes source freshness and no reader-facing copy is
emitted.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

PARSER_ID = "RO_UTILITY_HEAT_INTERRUPTION_LISTING_V1"


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def fold(value: object) -> str:
    text = unicodedata.normalize("NFKD", clean(value).casefold())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _service_datetime(day: str, month: str, year: str, hour: str, minute: str, tz: ZoneInfo) -> datetime | None:
    try:
        h = int(hour)
        m = int(minute)
        base = datetime(int(year), int(month), int(day), 0, 0, tzinfo=tz)
        if h == 24 and m == 0:
            return base + timedelta(days=1)
        if h > 23 or m > 59:
            return None
        return base.replace(hour=h, minute=m)
    except ValueError:
        return None


def _clock_parts(token: str) -> tuple[str, str] | None:
    value = re.sub(r"\s+", "", clean(token))
    if not value:
        return None
    punct = re.fullmatch(r"([0-2]?\d)[:.]([0-5]\d)", value)
    if punct:
        return punct.group(1), punct.group(2)
    if value.isdigit():
        if len(value) <= 2:
            return value, "00"
        if len(value) in {3, 4}:
            return value[:-2], value[-2:]
    return None


def _clock_datetime(day: str, month: str, year: str, token: str, tz: ZoneInfo) -> datetime | None:
    parts = _clock_parts(token)
    if not parts:
        return None
    return _service_datetime(day, month, year, parts[0], parts[1], tz)


def _cross_day_window(text: str, tz: ZoneInfo) -> tuple[datetime, datetime, str] | None:
    normalized = clean(text).replace("–", "-").replace("—", "-")
    clock = r"([0-2]?\d(?:\s*[:.]\s*[0-5]\d|\s+[0-5]\d|[0-5]\d)?)"
    patterns = (
        re.compile(
            r"\b(?:din\s+)?data\s+de\s+(\d{1,2})[./](\d{1,2})[./](20\d{2})\s*,?\s*ora\s*"
            + clock
            + r"\s*(?:pana|până)\s+(?:in|în)\s+data\s+de\s+(\d{1,2})[./](\d{1,2})[./](20\d{2})\s*,?\s*ora\s*"
            + clock,
            re.I,
        ),
        re.compile(
            r"\b(?:in|în)\s+perioada\s+(\d{1,2})[./](\d{1,2})[./](20\d{2})\s*-?\s*ora\s*"
            + clock
            + r"\s*-\s*(\d{1,2})[./](\d{1,2})[./](20\d{2})\s*,?\s*ora\s*"
            + clock,
            re.I,
        ),
    )
    for pattern in patterns:
        match = pattern.search(normalized)
        if not match:
            continue
        start = _clock_datetime(match.group(1), match.group(2), match.group(3), match.group(4), tz)
        end = _clock_datetime(match.group(5), match.group(6), match.group(7), match.group(8), tz)
        if start and end and end > start:
            return start, end, clean(match.group(0))
        return None
    return None


def _window_from_tail(tail: str, day: str, month: str, year: str, tz: ZoneInfo) -> tuple[datetime, datetime, str] | None:
    normalized = clean(tail).replace("–", "-").replace("—", "-")
    marker = re.search(r"\b(?:intre|între)\s+orele\b", normalized, re.I)
    if not marker:
        return None
    window_text = normalized[marker.start(): marker.start() + 90]
    body = window_text[marker.end() - marker.start():]

    variants = (
        re.compile(r"\s*([0-2]?\d)\s*[:.]\s*([0-5]\d)\s*(?:-|÷)\s*([0-2]?\d)\s*[:.]\s*([0-5]\d)\b"),
        re.compile(r"\s*([0-2]?\d)\s+([0-5]\d)\s*(?:-|÷)\s*([0-2]?\d)\s+([0-5]\d)\b"),
        re.compile(r"\s*([0-2]?\d)\s*(?:-|÷)\s*([0-2]?\d)\b"),
    )
    match = variants[0].match(body) or variants[1].match(body)
    if match:
        start = _service_datetime(day, month, year, match.group(1), match.group(2), tz)
        end = _service_datetime(day, month, year, match.group(3), match.group(4), tz)
    else:
        simple = variants[2].match(body)
        if not simple:
            return None
        start = _service_datetime(day, month, year, simple.group(1), "00", tz)
        end = _service_datetime(day, month, year, simple.group(2), "00", tz)
    if not start or not end or end <= start:
        return None
    return start, end, clean(window_text[: max(1, (match or simple).end() + marker.end() - marker.start())])


def parse_heat_service_window(text: str, tz: ZoneInfo) -> tuple[datetime, datetime, str] | None:
    """Extract an explicit same-day or cross-day thermal-service window."""
    normalized = clean(text)
    cross = _cross_day_window(normalized, tz)
    if cross:
        return cross
    date_match = re.search(r"\b(\d{1,2})[./](\d{1,2})[./](20\d{2})\b", normalized)
    if not date_match:
        return None
    return _window_from_tail(
        normalized[date_match.end():],
        date_match.group(1),
        date_match.group(2),
        date_match.group(3),
        tz,
    )


def _affected_consumers(block: str) -> list[str]:
    match = re.search(
        r"\bconsumatorii\s+racorda(?:ti|ți)\s+(?:si|și)\s+afecta(?:ti|ți)\s+de\s+aceast(?:a|ă)\s+oprire\s+sunt\s*:\s*(.*?)(?="
        r"\bne\s+cerem\s+scuze\b|\bdirector\s+general\b|$)",
        block,
        re.I | re.S,
    )
    if not match:
        return []
    rows = [clean(row).strip(" .,-") for row in re.split(r"\s*;\s*", match.group(1))]
    return [row for row in rows if row]


def _affected_scope(block: str) -> str | None:
    patterns = (
        re.compile(
            r"\b(?:la|pentru)\s+(to(?:ti|ți)\s+consumatorii\s+[^,.;]+)(?=\s*,?\s*(?:din|in|în)\s+data\s+de\b)",
            re.I | re.S,
        ),
        re.compile(
            r"\b(?:in|în)\s+(tot\s+municipiul\s+[^,.;]+?)(?=\s+pentru\b)",
            re.I | re.S,
        ),
    )
    for pattern in patterns:
        match = pattern.search(block)
        if match:
            return clean(match.group(1)).strip(" .,-")
    return None


def _service_forms(block: str) -> list[str]:
    match = re.search(
        r"\bsub\s+forma\s+de\s+(.*?)(?=\s*,?\s*(?:(?:in|în|din)\s+data\s+de|(?:la|pentru)\s+to(?:ti|ți)\s+consumatorii)\b)",
        block,
        re.I | re.S,
    )
    if not match:
        return []
    text = clean(match.group(1))
    parts = re.split(r"\s*,\s*|\s+(?:si|și)\s+", text, flags=re.I)
    return [clean(part) for part in parts if clean(part)]


def _reason(block: str) -> str | None:
    match = re.search(
        r"\bpentru\s+(.*?)(?=\bconsumatorii\s+racorda(?:ti|ți)\s+(?:si|și)\s+afecta(?:ti|ți)\b|\bne\s+cerem\s+scuze\b|$)",
        block,
        re.I | re.S,
    )
    return clean(match.group(1)).strip(" .,-") if match else None


def _candidate_blocks(text: str) -> list[str]:
    normalized = clean(text)
    folded = fold(normalized)
    needle = "anunta intreruperea furnizarii agentului termic"
    starts = [m.start() for m in re.finditer(re.escape(needle), folded)]
    blocks: list[str] = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(normalized)
        blocks.append(normalized[start:end])
    return blocks


def parse_heat_interruption_listing(
    text: str,
    tz: ZoneInfo,
    now: datetime,
    *,
    planning_horizon_hours: int = 336,
    expiry_grace_hours: int = 1,
    max_candidates: int = 40,
) -> tuple[list[dict[str, Any]], int]:
    """Return evidence-only heat interruption rows and candidate count."""
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    horizon = timedelta(hours=int(planning_horizon_hours))
    grace = timedelta(hours=int(expiry_grace_hours))
    events: list[dict[str, Any]] = []
    candidates = 0
    seen: set[str] = set()

    for block in _candidate_blocks(text):
        if candidates >= int(max_candidates):
            break
        candidates += 1
        window = parse_heat_service_window(block, tz)
        if not window:
            continue
        event_start, event_end, window_text = window
        if event_end < now - grace or event_start > now + horizon:
            continue
        consumers = _affected_consumers(block)
        affected_scope = _affected_scope(block)
        if not consumers and not affected_scope:
            continue
        forms = _service_forms(block)
        fingerprint_input = "\n".join(
            [event_start.isoformat(), event_end.isoformat(), affected_scope or "", *consumers, clean(block)]
        )
        fingerprint = hashlib.sha256(fingerprint_input.encode("utf-8")).hexdigest()
        if fingerprint in seen:
            continue
        seen.add(fingerprint)
        events.append(
            {
                "event_key": "utility-heat-" + fingerprint[:20],
                "parser": PARSER_ID,
                "event_start": event_start.isoformat(timespec="minutes"),
                "event_end": event_end.isoformat(timespec="minutes"),
                "source_time_basis": "official_service_window",
                "body_sha256": hashlib.sha256(clean(block).encode("utf-8")).hexdigest(),
                "structured": {
                    "utility": "district_heat",
                    "service_state": "interruption",
                    "service_forms": forms,
                    "affected_consumers": consumers,
                    "affected_scope": affected_scope,
                    "service_window_text": window_text,
                    "reason": _reason(block),
                },
                "publication_authority": "PRIMARY_STRUCTURED_EVENT_ONLY",
                "reader_copy_generated": False,
            }
        )
    events.sort(key=lambda row: row["event_start"])
    return events, candidates


def self_test() -> int:
    tz = ZoneInfo("Europe/Bucharest")
    now = datetime(2026, 8, 27, 14, 0, tzinfo=tz)
    sample = """
    Anunt public. Operatorul anunta intreruperea furnizarii agentului termic
    sub forma de incalzire, apa fierbinte si apa calda de consum, in data de
    29.08.2026, intre orele 09:00 - 18:00, pentru eliminare avarie conducta
    primara. Consumatorii racordati si afectati de aceasta oprire sunt:
    PT 1 Centru; Spital Municipal; strada Exemplu.
    Ne cerem scuze pentru disconfort.

    Anunt public privind dezbaterea publica pentru un raport de mediu.

    Anunt public. Operatorul anunta intreruperea furnizarii agentului termic
    sub forma de apa fierbinte si apa calda de consum, in data de 20.08.2026,
    intre orele 9 00 ÷ 18 00, pentru lucrari. Consumatorii racordati si afectati
    de aceasta oprire sunt: PT Vechi. Ne cerem scuze pentru disconfort.
    """
    events, candidates = parse_heat_interruption_listing(sample, tz, now)
    assert candidates == 2
    assert len(events) == 1
    row = events[0]
    assert row["event_start"] == "2026-08-29T09:00+03:00"
    assert row["event_end"] == "2026-08-29T18:00+03:00"
    assert row["source_time_basis"] == "official_service_window"
    assert row["reader_copy_generated"] is False
    assert row["structured"]["affected_consumers"] == ["PT 1 Centru", "Spital Municipal", "strada Exemplu"]
    assert row["structured"]["service_forms"] == ["incalzire", "apa fierbinte", "apa calda de consum"]
    assert parse_heat_service_window("intr-o zi neprecizata, intre orele 9-18", tz) is None

    cross = parse_heat_service_window(
        "Operatorul anunta intreruperea din data de 13.07.2026, ora 0100 pana in data de 15.07.2026, ora 2400.",
        tz,
    )
    assert cross is not None
    assert cross[0].isoformat(timespec="minutes") == "2026-07-13T01:00+03:00"
    assert cross[1].isoformat(timespec="minutes") == "2026-07-16T00:00+03:00"

    future_cross = """
    Operatorul anunta intreruperea furnizarii agentului termic sub forma de apa fierbinte
    si apa calda de consum la toti consumatorii Municipiului Test, din data de 30.08.2026,
    ora 22 00 pana in data de 31.08.2026, ora 24 00, pentru lucrari retea primara.
    Ne cerem scuze pentru disconfort.
    """
    future_events, future_candidates = parse_heat_interruption_listing(future_cross, tz, now)
    assert future_candidates == 1 and len(future_events) == 1
    assert future_events[0]["event_start"] == "2026-08-30T22:00+03:00"
    assert future_events[0]["event_end"] == "2026-09-01T00:00+03:00"
    assert future_events[0]["structured"]["affected_scope"] == "toti consumatorii Municipiului Test"

    whole_city = """
    Operatorul anunta intreruperea furnizarii agentului termic sub forma de apa fierbinte
    si apa calda de consum, in data de 04.09.2026, intre orele 01-21, in tot Municipiul
    Ramnicu Valcea pentru racordarea cazanelor de apa fierbinte la reteaua de termoficare.
    Ne cerem scuze pentru disconfort.
    """
    whole_city_events, whole_city_candidates = parse_heat_interruption_listing(whole_city, tz, now)
    assert whole_city_candidates == 1 and len(whole_city_events) == 1
    assert whole_city_events[0]["event_start"] == "2026-09-04T01:00+03:00"
    assert whole_city_events[0]["event_end"] == "2026-09-04T21:00+03:00"
    assert whole_city_events[0]["structured"]["affected_scope"] == "tot Municipiul Ramnicu Valcea"

    missing_consumers = """
    Operatorul anunta intreruperea furnizarii agentului termic in data de
    30.08.2026, intre orele 09-12, pentru lucrari.
    """
    held, held_candidates = parse_heat_interruption_listing(missing_consumers, tz, now)
    assert held_candidates == 1 and held == []
    mixed = "Anunt public privind dezbaterea publica si documentatie de mediu."
    mixed_events, mixed_candidates = parse_heat_interruption_listing(mixed, tz, now)
    assert mixed_candidates == 0 and mixed_events == []
    print("GENERIC_HEAT_INTERRUPTION_PARSER_SELF_TEST_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())