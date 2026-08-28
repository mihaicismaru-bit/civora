#!/usr/bin/env python3
"""Normalize verified INFOTRAFIC Vâlcea signals into internal traffic-event intelligence.

This stage is deliberately non-public. It accepts only records emitted by the canonical
INFOTRAFIC Vâlcea signal adapter and derives conservative routing/status fields from text
that is explicit in the source. Missing fields remain null instead of being inferred.

The output is for newsroom threading/dedupe/refresh decisions only. It carries no
publication authority and must be re-verified against the official source before any
reader-facing current-status claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-infotrafic-valcea"
SOURCE_KIND = "ROAD_TRAFFIC_ALERTS"
OFFICIAL_HOST = "politiaromana.ro"
INPUT_LIFECYCLE = "SIGNAL_ONLY_NEEDS_EDITORIAL_VERIFICATION"
OUTPUT_LIFECYCLE = "INTERNAL_TRAFFIC_EVENT_NEEDS_SOURCE_RECHECK"
REFRESH_TTL = timedelta(hours=6)
BUCHAREST = ZoneInfo("Europe/Bucharest")

ROAD_RE = re.compile(
    r"\b(?P<kind>DN|DJ|DC|A)\s*[- ]?\s*(?P<number>\d{1,4}[A-Z]?)\b",
    re.IGNORECASE,
)
SEGMENT_PATTERNS = [
    re.compile(
        r"\b(?:între|intre)\s+(?P<a>[^,.;:]{2,70}?)\s+(?:și|si)\s+(?P<b>[^,.;:]{2,70}?)(?=,|\.|;|:|\s+(?:pe|din|iar|unde|traficul|circulația|circulatia)\b|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:pe\s+tronsonul|pe\s+sectorul)\s+(?P<a>[^,.;:]{2,70}?)\s*[-–—]\s*(?P<b>[^,.;:]{2,70}?)(?=,|\.|;|:|$)",
        re.IGNORECASE,
    ),
]
LOCALITY_PATTERNS = [
    re.compile(r"\b(?:în|in)\s+(?:localitatea|orașul|orasul|municipiul|zona)\s+(?P<name>[^,.;:]{2,70}?)(?=,|\.|;|:|\s+(?:pe|din|unde|traficul|circulația|circulatia)\b|$)", re.IGNORECASE),
    re.compile(r"\bpe\s+raza\s+localității\s+(?P<name>[^,.;:]{2,70}?)(?=,|\.|;|:|$)", re.IGNORECASE),
]
DIRECTION_PATTERNS = [
    re.compile(r"\b(?:pe\s+)?sensul\s+(?P<direction>[^,.;:]{2,90}?)(?=,|\.|;|:|\s+(?:traficul|circulația|circulatia)\b|$)", re.IGNORECASE),
    re.compile(r"\b(?:în|in)\s+direcția\s+(?P<direction>[^,.;:]{2,90}?)(?=,|\.|;|:|$)", re.IGNORECASE),
]

RESUMED_PHRASES = (
    "traficul a fost reluat",
    "circulatia a fost reluata",
    "traficul s-a reluat",
    "circulatia s-a reluat",
    "se circula normal",
    "traficul se desfasoara normal",
)
STOPPED_PHRASES = (
    "traficul este oprit",
    "circulatia este oprita",
    "traficul este blocat",
    "circulatia este blocata",
    "trafic blocat",
    "circulatie blocata",
    "traficul rutier este oprit",
)
ALTERNATE_PHRASES = (
    "circulatie alternativa",
    "circulatia se desfasoara alternativ",
    "traficul se desfasoara alternativ",
    "trafic alternativ",
    "dirijata alternativ",
    "dirijat alternativ",
)
HEAVY_PHRASES = (
    "trafic intens",
    "valori ridicate de trafic",
    "valori de trafic ridicate",
    "coloana de autovehicule",
    "coloane de autovehicule",
    "trafic ingreunat",
    "circulatie ingreunata",
)

ESTIMATE_RE = re.compile(
    r"\b(?:se\s+estimează|se\s+estimeaza|este\s+estimată|este\s+estimata)"
    r"(?:\s+ca)?(?:\s+reluarea\s+(?:traficului|circulației|circulatiei))?"
    r"[^.;]{0,90}?\b(?:ora|orei|orele)\s+([0-2]?\d):([0-5]\d)\b",
    re.IGNORECASE,
)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except (TypeError, ValueError) as exc:
        raise ValueError("traffic event requires an ISO source_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("traffic event requires an offset-aware source_timestamp")
    return parsed.astimezone(BUCHAREST)


def validate_source_url(value: str) -> str:
    parsed = urlsplit(clean_text(value))
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise ValueError("traffic event requires an HTTPS official article_url")
    if parsed.hostname.casefold() != OFFICIAL_HOST:
        raise ValueError("traffic event refused non-official article_url")
    if parsed.username or parsed.password:
        raise ValueError("traffic event refused credential-bearing article_url")
    if not parsed.path.startswith("/ro/info-trafic/"):
        raise ValueError("traffic event requires a direct INFOTRAFIC article_url")
    return clean_text(value)


def validate_signal(signal: dict[str, Any]) -> tuple[str, datetime]:
    if signal.get("source_id") != SOURCE_ID:
        raise ValueError("traffic event accepts only canonical Vâlcea INFOTRAFIC signals")
    if signal.get("source_kind") != SOURCE_KIND:
        raise ValueError("traffic event requires ROAD_TRAFFIC_ALERTS source_kind")
    if signal.get("lifecycle") != INPUT_LIFECYCLE:
        raise ValueError("traffic event requires the signal-only verification lifecycle")
    if signal.get("publication_authority") != "NONE":
        raise ValueError("traffic event refuses publication-authorized input")
    if signal.get("auto_publication") is not False:
        raise ValueError("traffic event refuses auto-publication input")
    if signal.get("public_projection") is not False:
        raise ValueError("traffic event refuses public-projection input")
    article_url = validate_source_url(str(signal.get("article_url") or ""))
    timestamp = parse_timestamp(str(signal.get("source_timestamp") or ""))
    excerpt = clean_text(str(signal.get("excerpt") or ""))
    title = clean_text(str(signal.get("title") or ""))
    if not excerpt or not title:
        raise ValueError("traffic event requires explicit title and excerpt evidence")
    sha = clean_text(str(signal.get("source_content_sha256") or ""))
    if not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise ValueError("traffic event requires a 64-hex source_content_sha256")
    return article_url, timestamp


def normalize_road(text: str) -> str | None:
    match = ROAD_RE.search(text)
    if not match:
        return None
    return f"{match.group('kind').upper()}{match.group('number').upper()}"


def _bounded_capture(text: str, patterns: list[re.Pattern[str]], field: str) -> str | None:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            value = clean_text(match.group(field)).strip(" -–—")
            if value:
                return value
    return None


def extract_segment(text: str) -> dict[str, str] | None:
    for pattern in SEGMENT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        start = clean_text(match.group("a")).strip(" -–—")
        end = clean_text(match.group("b")).strip(" -–—")
        if start and end:
            return {"start": start, "end": end}
    return None


def extract_locality(text: str) -> str | None:
    return _bounded_capture(text, LOCALITY_PATTERNS, "name")


def extract_direction(text: str) -> str | None:
    return _bounded_capture(text, DIRECTION_PATTERNS, "direction")


def classify_state(text: str) -> str:
    value = fold(text)
    for phrase in RESUMED_PHRASES:
        if phrase in value:
            return "RESUMED"
    for phrase in STOPPED_PHRASES:
        if phrase in value:
            return "TRAFFIC_STOPPED"
    for phrase in ALTERNATE_PHRASES:
        if phrase in value:
            return "ALTERNATE"
    for phrase in HEAVY_PHRASES:
        if phrase in value:
            return "HEAVY"
    return "UNKNOWN"


def extract_estimated_reopen(text: str, source_timestamp: datetime) -> str | None:
    match = ESTIMATE_RE.search(text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    candidate = source_timestamp.replace(hour=hour, minute=minute, second=0, microsecond=0)
    # Do not roll an ambiguous clock time into the next day. The source must say so
    # explicitly; otherwise null is safer than invention.
    if candidate <= source_timestamp:
        return None
    return candidate.isoformat()


def canonical_component(value: str | None) -> str:
    return fold(value or "")


def build_thread_key(
    road: str | None,
    segment: dict[str, str] | None,
    locality: str | None,
    direction: str | None,
) -> str:
    if not road:
        raise ValueError("traffic event cannot thread without an explicit road identifier")
    parts = [
        SOURCE_ID,
        canonical_component(road),
        canonical_component(segment["start"] if segment else locality),
        canonical_component(segment["end"] if segment else ""),
        canonical_component(direction),
    ]
    raw = "\0".join(parts)
    return "traffic-thread-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def build_event_id(signal: dict[str, Any]) -> str:
    raw = "\0".join(
        [
            SOURCE_ID,
            clean_text(str(signal["article_url"])),
            clean_text(str(signal["source_timestamp"])),
            clean_text(str(signal["source_content_sha256"])).lower(),
        ]
    )
    return "traffic-event-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def normalize_signal(signal: dict[str, Any]) -> dict[str, Any]:
    article_url, source_timestamp = validate_signal(signal)
    evidence_text = clean_text(f"{signal['title']} {signal['excerpt']}")
    road = normalize_road(evidence_text)
    if not road:
        raise ValueError("traffic event requires an explicit road identifier in source evidence")
    segment = extract_segment(evidence_text)
    locality = extract_locality(evidence_text)
    direction = extract_direction(evidence_text)
    state = classify_state(evidence_text)
    estimated_reopen_at = extract_estimated_reopen(evidence_text, source_timestamp)
    expiry_hint = source_timestamp + REFRESH_TTL

    return {
        "event_id": build_event_id(signal),
        "thread_key": build_thread_key(road, segment, locality, direction),
        "source_signal_id": clean_text(str(signal.get("signal_id") or "")) or None,
        "source_id": SOURCE_ID,
        "source_kind": SOURCE_KIND,
        "article_url": article_url,
        "source_timestamp": source_timestamp.isoformat(),
        "source_content_sha256": clean_text(str(signal["source_content_sha256"])).lower(),
        "road": road,
        "segment": segment,
        "locality": locality,
        "direction": direction,
        "state": state,
        "estimated_reopen_at": estimated_reopen_at,
        "refresh_recheck_after": expiry_hint.isoformat(),
        "refresh_semantics": "INTERNAL_RECHECK_DEADLINE_NOT_A_CURRENT_STATUS_CLAIM",
        "field_semantics": "EXPLICIT_SOURCE_TEXT_ONLY_NULL_WHEN_NOT_EXPLICIT",
        "lifecycle": OUTPUT_LIFECYCLE,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "provenance": {
            "authority": "POLITIA_ROMANA_INFOTRAFIC",
            "source_signal_lifecycle": INPUT_LIFECYCLE,
            "normalization": "DETERMINISTIC_INTERNAL_EVENT_V1",
            "evidence_fields": ["title", "excerpt", "source_timestamp", "source_content_sha256"],
        },
    }


def normalize_document(document: dict[str, Any]) -> dict[str, Any]:
    signals = document.get("signals")
    if not isinstance(signals, list):
        raise ValueError("traffic event input document requires a signals list")
    events: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in signals:
        if not isinstance(item, dict):
            raise ValueError("traffic event input signals must be objects")
        event = normalize_signal(item)
        if event["event_id"] in seen_ids:
            continue
        seen_ids.add(event["event_id"])
        events.append(event)
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal traffic-event intelligence",
        "event_count": len(events),
        "events": events,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "source_recheck_required_before_current_status_claim": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normalize canonical INFOTRAFIC Vâlcea signals into internal events"
    )
    parser.add_argument("input", help="INFOTRAFIC signal JSON path, or '-' for stdin")
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout")
    args = parser.parse_args()

    if args.input == "-":
        import sys

        document = json.load(sys.stdin)
    else:
        with open(args.input, "r", encoding="utf-8") as handle:
            document = json.load(handle)

    result = normalize_document(document)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)


if __name__ == "__main__":
    main()
