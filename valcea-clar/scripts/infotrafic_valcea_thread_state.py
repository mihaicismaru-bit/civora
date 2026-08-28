#!/usr/bin/env python3
"""Build non-persistent newsroom thread state from normalized INFOTRAFIC Vâlcea events.

The threader is deliberately internal and deterministic. It deduplicates immutable
normalized events, links only conservative same-corridor updates, and computes source
recheck state from an explicit ``as_of`` timestamp. It never promotes an event into a
reader-facing current-status claim and has no persistence or publication authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-infotrafic-valcea"
SOURCE_KIND = "ROAD_TRAFFIC_ALERTS"
INPUT_LIFECYCLE = "INTERNAL_TRAFFIC_EVENT_NEEDS_SOURCE_RECHECK"
OUTPUT_LIFECYCLE = "INTERNAL_TRAFFIC_THREAD_NEEDS_SOURCE_RECHECK"
NORMALIZATION_ID = "DETERMINISTIC_INTERNAL_EVENT_V1"
MATCH_WINDOW = timedelta(hours=12)
BUCHAREST = ZoneInfo("Europe/Bucharest")
ALLOWED_STATES = {"TRAFFIC_STOPPED", "ALTERNATE", "HEAVY", "RESUMED", "UNKNOWN"}
ROAD_RE = re.compile(r"^(?:DN|DJ|DC|A)\d{1,4}[A-Z]?$", re.IGNORECASE)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", clean_text(value).casefold())
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def parse_timestamp(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def _validate_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"traffic event {field} must be a string or null")
    cleaned = clean_text(value)
    if not cleaned:
        raise ValueError(f"traffic event {field} cannot be blank")
    return cleaned


def validate_document(document: dict[str, Any]) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise ValueError("traffic thread input must be a JSON object")
    events = document.get("events")
    if not isinstance(events, list):
        raise ValueError("traffic thread input requires an events list")
    policy = document.get("policy")
    if not isinstance(policy, dict):
        raise ValueError("traffic thread input requires the normalizer policy")
    expected = {
        "reader_facing_eligible": False,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "source_recheck_required_before_current_status_claim": True,
    }
    for key, value in expected.items():
        if policy.get(key) != value:
            raise ValueError(f"traffic thread refuses input policy drift: {key}")
    return events


def validate_event(event: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("traffic thread input events must be objects")
    if event.get("source_id") != SOURCE_ID or event.get("source_kind") != SOURCE_KIND:
        raise ValueError("traffic thread accepts only canonical Vâlcea INFOTRAFIC events")
    if event.get("lifecycle") != INPUT_LIFECYCLE:
        raise ValueError("traffic thread requires normalized internal-event lifecycle")
    if event.get("publication_authority") != "NONE":
        raise ValueError("traffic thread refuses publication-authorized events")
    if event.get("public_projection") is not False or event.get("auto_publication") is not False:
        raise ValueError("traffic thread refuses reader-facing or auto-publication events")

    event_id = clean_text(str(event.get("event_id") or ""))
    thread_key = clean_text(str(event.get("thread_key") or ""))
    if not event_id.startswith("traffic-event-"):
        raise ValueError("traffic thread requires canonical traffic-event id")
    if not thread_key.startswith("traffic-thread-"):
        raise ValueError("traffic thread requires canonical traffic-thread key")

    road = clean_text(str(event.get("road") or "")).upper()
    if not ROAD_RE.fullmatch(road):
        raise ValueError("traffic thread requires a canonical road identifier")
    state = clean_text(str(event.get("state") or "")).upper()
    if state not in ALLOWED_STATES:
        raise ValueError("traffic thread refuses unknown state vocabulary")

    source_timestamp = parse_timestamp(str(event.get("source_timestamp") or ""), "source_timestamp")
    recheck_after = parse_timestamp(
        str(event.get("refresh_recheck_after") or ""), "refresh_recheck_after"
    )
    if recheck_after < source_timestamp:
        raise ValueError("traffic thread refuses recheck deadline before source timestamp")

    segment = event.get("segment")
    if segment is not None:
        if not isinstance(segment, dict) or set(segment) != {"start", "end"}:
            raise ValueError("traffic event segment must contain exactly start/end")
        start = _validate_optional_text(segment.get("start"), "segment.start")
        end = _validate_optional_text(segment.get("end"), "segment.end")
        if start is None or end is None:
            raise ValueError("traffic event segment endpoints cannot be null")
        segment = {"start": start, "end": end}

    locality = _validate_optional_text(event.get("locality"), "locality")
    direction = _validate_optional_text(event.get("direction"), "direction")
    provenance = event.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("normalization") != NORMALIZATION_ID:
        raise ValueError("traffic thread requires canonical normalizer provenance")

    validated = dict(event)
    validated.update(
        {
            "event_id": event_id,
            "thread_key": thread_key,
            "road": road,
            "state": state,
            "segment": segment,
            "locality": locality,
            "direction": direction,
            "_source_dt": source_timestamp,
            "_recheck_dt": recheck_after,
        }
    )
    return validated


def geography_key(event: dict[str, Any]) -> tuple[str, ...] | None:
    segment = event.get("segment")
    if isinstance(segment, dict):
        endpoints = sorted((fold(str(segment["start"])), fold(str(segment["end"]))))
        return ("SEGMENT", event["road"], endpoints[0], endpoints[1])
    locality = event.get("locality")
    if locality:
        return ("LOCALITY", event["road"], fold(str(locality)))
    return None


def directions_compatible(left: str | None, right: str | None) -> bool:
    return not left or not right or fold(left) == fold(right)


def _canonical_event_payload(event: dict[str, Any]) -> str:
    clean = {key: value for key, value in event.items() if not key.startswith("_")}
    return json.dumps(clean, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _thread_id(first_event_id: str) -> str:
    digest = hashlib.sha256(first_event_id.encode("utf-8")).hexdigest()[:24]
    return "traffic-logical-thread-" + digest


def _can_join(thread: dict[str, Any], event: dict[str, Any]) -> bool:
    latest = thread["events"][-1]
    delta = event["_source_dt"] - latest["_source_dt"]
    if delta < timedelta(0) or delta > MATCH_WINDOW:
        return False
    if latest["state"] == "RESUMED" and event["state"] != "RESUMED":
        return False
    if event["thread_key"] in thread["thread_key_aliases"]:
        return True
    geo = geography_key(event)
    if geo is None or geo not in thread["geography_keys"]:
        return False
    latest_direction = next(
        (
            candidate.get("direction")
            for candidate in reversed(thread["events"])
            if candidate.get("direction")
        ),
        None,
    )
    return directions_compatible(latest_direction, event.get("direction"))


def _append_event(thread: dict[str, Any], event: dict[str, Any]) -> None:
    thread["events"].append(event)
    thread["thread_key_aliases"].add(event["thread_key"])
    geo = geography_key(event)
    if geo is not None:
        thread["geography_keys"].add(geo)


def _new_thread(event: dict[str, Any]) -> dict[str, Any]:
    geo = geography_key(event)
    return {
        "logical_thread_id": _thread_id(event["event_id"]),
        "events": [event],
        "thread_key_aliases": {event["thread_key"]},
        "geography_keys": {geo} if geo is not None else set(),
    }


def _render_thread(thread: dict[str, Any], as_of: datetime) -> dict[str, Any]:
    events = thread["events"]
    latest = events[-1]
    transitions: list[dict[str, str]] = []
    previous_state: str | None = None
    for event in events:
        if event["state"] == previous_state:
            continue
        transitions.append(
            {
                "event_id": event["event_id"],
                "source_timestamp": event["_source_dt"].isoformat(),
                "reported_state": event["state"],
            }
        )
        previous_state = event["state"]

    if latest["state"] == "RESUMED":
        recheck_status = "CLOSED_BY_EXPLICIT_RESUMED_UPDATE"
    elif as_of >= latest["_recheck_dt"]:
        recheck_status = "RECHECK_OVERDUE"
    else:
        recheck_status = "RECHECK_NOT_YET_DUE"

    latest_geo = geography_key(latest)
    return {
        "logical_thread_id": thread["logical_thread_id"],
        "road": latest["road"],
        "latest_segment": latest.get("segment"),
        "latest_locality": latest.get("locality"),
        "latest_direction": latest.get("direction"),
        "geography_basis": latest_geo[0] if latest_geo else "ROAD_ONLY_NO_FALLBACK_LINKING",
        "thread_key_aliases": sorted(thread["thread_key_aliases"]),
        "event_ids": [event["event_id"] for event in events],
        "source_update_count": len(events),
        "first_source_update_at": events[0]["_source_dt"].isoformat(),
        "last_source_update_at": latest["_source_dt"].isoformat(),
        "latest_event_id": latest["event_id"],
        "latest_reported_state": latest["state"],
        "state_transitions": transitions,
        "recheck_due_at": latest["_recheck_dt"].isoformat(),
        "recheck_status": recheck_status,
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "lifecycle": OUTPUT_LIFECYCLE,
    }


def build_threads(document: dict[str, Any], as_of: str) -> dict[str, Any]:
    raw_events = validate_document(document)
    as_of_dt = parse_timestamp(as_of, "as_of")

    unique_events: dict[str, dict[str, Any]] = {}
    duplicate_event_count = 0
    for raw in raw_events:
        event = validate_event(raw)
        existing = unique_events.get(event["event_id"])
        if existing is None:
            unique_events[event["event_id"]] = event
            continue
        if _canonical_event_payload(existing) != _canonical_event_payload(event):
            raise ValueError("traffic thread refuses conflicting reuse of an event_id")
        duplicate_event_count += 1

    events = sorted(
        unique_events.values(),
        key=lambda item: (item["_source_dt"], item["event_id"]),
    )
    threads: list[dict[str, Any]] = []
    for event in events:
        candidates = [thread for thread in threads if _can_join(thread, event)]
        if len(candidates) == 1:
            _append_event(candidates[0], event)
        else:
            # Zero candidates means no safe link. Multiple candidates are deliberately
            # ambiguous and also fail closed into a distinct thread instead of guessing.
            threads.append(_new_thread(event))

    rendered = [_render_thread(thread, as_of_dt) for thread in threads]
    rendered.sort(
        key=lambda item: (item["last_source_update_at"], item["logical_thread_id"]),
        reverse=True,
    )
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal INFOTRAFIC thread state",
        "as_of": as_of_dt.isoformat(),
        "event_count": len(events),
        "duplicate_event_count": duplicate_event_count,
        "thread_count": len(rendered),
        "threads": rendered,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "current_status_claim_allowed": False,
            "source_recheck_required_before_current_status_claim": True,
            "matching_window_hours": int(MATCH_WINDOW.total_seconds() // 3600),
            "matching_semantics": "EXACT_THREAD_KEY_OR_UNAMBIGUOUS_SAME_EXPLICIT_GEOGRAPHY_WITH_COMPATIBLE_DIRECTION",
            "expiry_semantics": "RECHECK_DEADLINE_ONLY_NEVER_AUTOMATIC_CURRENT_STATUS",
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build internal INFOTRAFIC Vâlcea update threads")
    parser.add_argument("input", help="Normalized traffic-event JSON path, or '-' for stdin")
    parser.add_argument(
        "--as-of",
        required=True,
        help="Offset-aware ISO time used only for recheck evaluation",
    )
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout")
    args = parser.parse_args()

    if args.input == "-":
        import sys

        document = json.load(sys.stdin)
    else:
        with open(args.input, "r", encoding="utf-8") as handle:
            document = json.load(handle)

    result = build_threads(document, args.as_of)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)


if __name__ == "__main__":
    main()
