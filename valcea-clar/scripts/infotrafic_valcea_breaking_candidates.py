#!/usr/bin/env python3
"""Build internal breaking-news candidates from verified INFOTRAFIC Vâlcea thread state.

This stage is newsroom-only. It joins the bounded thread state back to the normalized
source events so every candidate carries an explicit evidence chain. It can rank work
for human review, but it cannot create a current-status claim, persist state, publish,
or project anything reader-facing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime
from typing import Any
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

SOURCE_ID = "signal-infotrafic-valcea"
SOURCE_KIND = "ROAD_TRAFFIC_ALERTS"
EVENT_LIFECYCLE = "INTERNAL_TRAFFIC_EVENT_NEEDS_SOURCE_RECHECK"
THREAD_LIFECYCLE = "INTERNAL_TRAFFIC_THREAD_NEEDS_SOURCE_RECHECK"
OUTPUT_LIFECYCLE = "INTERNAL_BREAKING_CANDIDATE_REVIEW_REQUIRED"
NORMALIZATION_ID = "DETERMINISTIC_INTERNAL_EVENT_V1"
OFFICIAL_HOST = "politiaromana.ro"
BUCHAREST = ZoneInfo("Europe/Bucharest")
ROAD_RE = re.compile(r"^(?:DN|DJ|DC|A)\d{1,4}[A-Z]?$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_ID_RE = re.compile(r"^traffic-event-[0-9a-f]{24}$", re.IGNORECASE)
THREAD_ID_RE = re.compile(r"^traffic-logical-thread-[0-9a-f]{24}$", re.IGNORECASE)
ALLOWED_STATES = {"TRAFFIC_STOPPED", "ALTERNATE", "HEAVY", "RESUMED", "UNKNOWN"}
ALLOWED_RECHECK = {
    "CLOSED_BY_EXPLICIT_RESUMED_UPDATE",
    "RECHECK_OVERDUE",
    "RECHECK_NOT_YET_DUE",
}
SEVERITY_SCORES = {
    "TRAFFIC_STOPPED": 100,
    "ALTERNATE": 78,
    "HEAVY": 65,
    "UNKNOWN": 20,
    "RESUMED": 0,
}
NETWORK_RELEVANCE_SCORES = {"A": 100, "DN": 90, "DJ": 65, "DC": 45}

THREAD_POLICY = {
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "current_status_claim_allowed": False,
    "source_recheck_required_before_current_status_claim": True,
}
EVENT_POLICY = {
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "source_recheck_required_before_current_status_claim": True,
}


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_timestamp(value: Any, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(clean_text(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} requires an ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} requires an offset-aware timestamp")
    return parsed.astimezone(BUCHAREST)


def _require_policy(policy: Any, expected: dict[str, Any], label: str) -> None:
    if not isinstance(policy, dict):
        raise ValueError(f"{label} requires a policy object")
    for key, value in expected.items():
        if policy.get(key) != value:
            raise ValueError(f"{label} refuses policy drift: {key}")


def _validate_article_url(value: Any) -> str:
    text = clean_text(value)
    parsed = urlsplit(text)
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise ValueError("candidate evidence requires an HTTPS article_url")
    if parsed.hostname.casefold() != OFFICIAL_HOST or parsed.username or parsed.password:
        raise ValueError("candidate evidence refuses non-official article_url")
    if not parsed.path.startswith("/ro/info-trafic/"):
        raise ValueError("candidate evidence requires a direct INFOTRAFIC article_url")
    return text


def _road_family(road: str) -> str:
    if road.startswith("DN"):
        return "DN"
    if road.startswith("DJ"):
        return "DJ"
    if road.startswith("DC"):
        return "DC"
    if road.startswith("A"):
        return "A"
    raise ValueError("candidate requires a canonical road identifier")


def _validate_normalized_event(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        raise ValueError("normalized events must be objects")
    event_id = clean_text(event.get("event_id"))
    if not EVENT_ID_RE.fullmatch(event_id):
        raise ValueError("candidate evidence requires a canonical traffic-event id")
    if event.get("source_id") != SOURCE_ID or event.get("source_kind") != SOURCE_KIND:
        raise ValueError("candidate evidence accepts only canonical Vâlcea INFOTRAFIC events")
    if event.get("lifecycle") != EVENT_LIFECYCLE:
        raise ValueError("candidate evidence requires normalized internal-event lifecycle")
    if event.get("publication_authority") != "NONE":
        raise ValueError("candidate evidence refuses publication-authorized input")
    if event.get("public_projection") is not False or event.get("auto_publication") is not False:
        raise ValueError("candidate evidence refuses reader-facing or auto-publication input")

    road = clean_text(event.get("road")).upper()
    if not ROAD_RE.fullmatch(road):
        raise ValueError("candidate evidence requires a canonical road identifier")
    state = clean_text(event.get("state")).upper()
    if state not in ALLOWED_STATES:
        raise ValueError("candidate evidence refuses unknown state vocabulary")
    article_url = _validate_article_url(event.get("article_url"))
    source_timestamp = parse_timestamp(event.get("source_timestamp"), "source_timestamp")
    recheck_at = parse_timestamp(event.get("refresh_recheck_after"), "refresh_recheck_after")
    if recheck_at < source_timestamp:
        raise ValueError("candidate evidence refuses recheck deadline before source timestamp")
    sha = clean_text(event.get("source_content_sha256")).lower()
    if not SHA256_RE.fullmatch(sha):
        raise ValueError("candidate evidence requires a 64-hex source_content_sha256")
    provenance = event.get("provenance")
    if not isinstance(provenance, dict) or provenance.get("normalization") != NORMALIZATION_ID:
        raise ValueError("candidate evidence requires canonical normalizer provenance")

    validated = dict(event)
    validated.update(
        {
            "event_id": event_id,
            "road": road,
            "state": state,
            "article_url": article_url,
            "source_content_sha256": sha,
            "_source_dt": source_timestamp,
            "_recheck_dt": recheck_at,
        }
    )
    return validated


def validate_normalized_document(document: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(document, dict):
        raise ValueError("candidate generation requires a normalized-event document")
    if document.get("schema_version") != "1.0":
        raise ValueError("candidate generation requires normalized-event schema_version 1.0")
    if document.get("product") != "VÂLCEA CLAR internal traffic-event intelligence":
        raise ValueError("candidate generation refuses unknown normalized-event product")
    _require_policy(document.get("policy"), EVENT_POLICY, "normalized-event document")
    events = document.get("events")
    if not isinstance(events, list):
        raise ValueError("normalized-event document requires an events list")
    indexed: dict[str, dict[str, Any]] = {}
    for raw in events:
        event = _validate_normalized_event(raw)
        event_id = event["event_id"]
        if event_id in indexed:
            raise ValueError("candidate generation refuses duplicate event_id in evidence input")
        indexed[event_id] = event
    if document.get("event_count") != len(events):
        raise ValueError("normalized-event document event_count drift")
    return indexed


def _validate_optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"thread {field} must be a string or null")
    cleaned = clean_text(value)
    if not cleaned:
        raise ValueError(f"thread {field} cannot be blank")
    return cleaned


def _validate_thread(thread: Any, as_of: datetime) -> dict[str, Any]:
    if not isinstance(thread, dict):
        raise ValueError("thread-state threads must be objects")
    if thread.get("lifecycle") != THREAD_LIFECYCLE:
        raise ValueError("candidate generation requires canonical thread lifecycle")
    if thread.get("current_status_claim_allowed") is not False:
        raise ValueError("candidate generation refuses current-status-authorized thread")
    if thread.get("reader_facing_eligible") is not False:
        raise ValueError("candidate generation refuses reader-facing thread")

    logical_thread_id = clean_text(thread.get("logical_thread_id"))
    if not THREAD_ID_RE.fullmatch(logical_thread_id):
        raise ValueError("candidate generation requires canonical logical_thread_id")
    road = clean_text(thread.get("road")).upper()
    if not ROAD_RE.fullmatch(road):
        raise ValueError("candidate generation requires a canonical road identifier")
    state = clean_text(thread.get("latest_reported_state")).upper()
    if state not in ALLOWED_STATES:
        raise ValueError("candidate generation refuses unknown latest_reported_state")
    recheck_status = clean_text(thread.get("recheck_status"))
    if recheck_status not in ALLOWED_RECHECK:
        raise ValueError("candidate generation refuses unknown recheck_status")

    event_ids = thread.get("event_ids")
    if not isinstance(event_ids, list) or not event_ids:
        raise ValueError("candidate generation requires non-empty event_ids")
    normalized_ids = [clean_text(item) for item in event_ids]
    if any(not EVENT_ID_RE.fullmatch(item) for item in normalized_ids):
        raise ValueError("candidate generation requires canonical event_ids")
    if len(normalized_ids) != len(set(normalized_ids)):
        raise ValueError("candidate generation refuses duplicate event_ids inside a thread")
    if thread.get("source_update_count") != len(normalized_ids):
        raise ValueError("candidate generation refuses source_update_count drift")
    latest_event_id = clean_text(thread.get("latest_event_id"))
    if latest_event_id != normalized_ids[-1]:
        raise ValueError("candidate generation requires latest_event_id to be final event_id")

    first_at = parse_timestamp(thread.get("first_source_update_at"), "first_source_update_at")
    last_at = parse_timestamp(thread.get("last_source_update_at"), "last_source_update_at")
    recheck_due = parse_timestamp(thread.get("recheck_due_at"), "recheck_due_at")
    if first_at > last_at or last_at > as_of:
        raise ValueError("candidate generation refuses impossible thread chronology")
    if recheck_due < last_at:
        raise ValueError("candidate generation refuses recheck deadline before latest update")
    if state == "RESUMED":
        if recheck_status != "CLOSED_BY_EXPLICIT_RESUMED_UPDATE":
            raise ValueError("candidate generation requires explicit RESUMED closure semantics")
    else:
        expected = "RECHECK_OVERDUE" if as_of >= recheck_due else "RECHECK_NOT_YET_DUE"
        if recheck_status != expected:
            raise ValueError("candidate generation refuses inconsistent recheck status")

    segment = thread.get("latest_segment")
    if segment is not None:
        if not isinstance(segment, dict) or set(segment) != {"start", "end"}:
            raise ValueError("candidate generation requires segment start/end")
        start = _validate_optional_text(segment.get("start"), "latest_segment.start")
        end = _validate_optional_text(segment.get("end"), "latest_segment.end")
        if start is None or end is None:
            raise ValueError("candidate generation refuses null segment endpoints")
        segment = {"start": start, "end": end}
    locality = _validate_optional_text(thread.get("latest_locality"), "latest_locality")
    direction = _validate_optional_text(thread.get("latest_direction"), "latest_direction")
    basis = clean_text(thread.get("geography_basis"))
    expected_basis = "SEGMENT" if segment else "LOCALITY" if locality else "ROAD_ONLY_NO_FALLBACK_LINKING"
    if basis != expected_basis:
        raise ValueError("candidate generation refuses geography_basis drift")

    validated = dict(thread)
    validated.update(
        {
            "logical_thread_id": logical_thread_id,
            "road": road,
            "latest_reported_state": state,
            "recheck_status": recheck_status,
            "event_ids": normalized_ids,
            "latest_event_id": latest_event_id,
            "latest_segment": segment,
            "latest_locality": locality,
            "latest_direction": direction,
            "_first_dt": first_at,
            "_last_dt": last_at,
            "_recheck_dt": recheck_due,
        }
    )
    return validated


def validate_thread_document(document: Any) -> tuple[datetime, list[dict[str, Any]]]:
    if not isinstance(document, dict):
        raise ValueError("candidate generation requires a thread-state document")
    if document.get("schema_version") != "1.0":
        raise ValueError("candidate generation requires thread-state schema_version 1.0")
    if document.get("product") != "VÂLCEA CLAR internal INFOTRAFIC thread state":
        raise ValueError("candidate generation refuses unknown thread-state product")
    _require_policy(document.get("policy"), THREAD_POLICY, "thread-state document")
    as_of = parse_timestamp(document.get("as_of"), "as_of")
    threads = document.get("threads")
    if not isinstance(threads, list):
        raise ValueError("thread-state document requires a threads list")
    if document.get("thread_count") != len(threads):
        raise ValueError("thread-state document thread_count drift")
    return as_of, [_validate_thread(item, as_of) for item in threads]


def _candidate_kind(thread: dict[str, Any]) -> str:
    if thread["latest_reported_state"] == "RESUMED":
        return "RESOLVED"
    if thread["recheck_status"] == "RECHECK_OVERDUE":
        return "RECHECK_REQUIRED"
    return "NEW" if thread["source_update_count"] == 1 else "UPDATE"


def _local_specificity(thread: dict[str, Any]) -> tuple[int, str]:
    if thread["latest_segment"]:
        return 100, "EXPLICIT_SEGMENT"
    if thread["latest_locality"]:
        return 80, "EXPLICIT_LOCALITY"
    return 35, "ROAD_ONLY"


def _network_relevance(road: str) -> tuple[int, str]:
    family = _road_family(road)
    return NETWORK_RELEVANCE_SCORES[family], family


def _candidate_id(thread: dict[str, Any], kind: str) -> str:
    raw = "\0".join(
        [
            thread["logical_thread_id"],
            thread["latest_event_id"],
            kind,
            thread["recheck_status"],
        ]
    )
    return "traffic-candidate-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _evidence_entry(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event["event_id"],
        "source_signal_id": event.get("source_signal_id"),
        "article_url": event["article_url"],
        "source_timestamp": event["_source_dt"].isoformat(),
        "source_content_sha256": event["source_content_sha256"],
        "normalization": NORMALIZATION_ID,
    }


def _verify_thread_against_events(
    thread: dict[str, Any], indexed: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    missing = [event_id for event_id in thread["event_ids"] if event_id not in indexed]
    if missing:
        raise ValueError("candidate generation refuses thread without complete normalized evidence chain")
    events = [indexed[event_id] for event_id in thread["event_ids"]]
    for left, right in zip(events, events[1:]):
        if left["_source_dt"] > right["_source_dt"]:
            raise ValueError("candidate generation refuses evidence order drift")
    latest = events[-1]
    comparisons = {
        "road": latest["road"],
        "latest_reported_state": latest["state"],
        "latest_segment": latest.get("segment"),
        "latest_locality": latest.get("locality"),
        "latest_direction": latest.get("direction"),
    }
    for field, expected in comparisons.items():
        if thread.get(field) != expected:
            raise ValueError(f"candidate generation refuses thread/evidence mismatch: {field}")
    if thread["_last_dt"] != latest["_source_dt"]:
        raise ValueError("candidate generation refuses thread/evidence source timestamp mismatch")
    if thread["_recheck_dt"] != latest["_recheck_dt"]:
        raise ValueError("candidate generation refuses thread/evidence recheck mismatch")
    return events


def _render_candidate(thread: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any]:
    kind = _candidate_kind(thread)
    severity = SEVERITY_SCORES[thread["latest_reported_state"]]
    local_score, local_basis = _local_specificity(thread)
    network_score, road_family = _network_relevance(thread["road"])
    lifecycle_bonus = {"NEW": 0, "UPDATE": 8, "RESOLVED": 18, "RECHECK_REQUIRED": 12}[kind]
    triage_score = min(
        100,
        round(0.55 * severity + 0.25 * network_score + 0.20 * local_score + lifecycle_bonus),
    )
    known_impact = thread["latest_reported_state"] != "UNKNOWN"
    breaking_candidate_eligible = kind != "RECHECK_REQUIRED" and known_impact
    hold_reason = None
    if kind == "RECHECK_REQUIRED":
        hold_reason = "OFFICIAL_SOURCE_RECHECK_REQUIRED_BEFORE_BREAKING_CANDIDATE"
    elif not known_impact:
        hold_reason = "NO_EXPLICIT_TRAFFIC_IMPACT_STATE"

    return {
        "candidate_id": _candidate_id(thread, kind),
        "dedupe_key": thread["logical_thread_id"],
        "candidate_kind": kind,
        "breaking_candidate_eligible": breaking_candidate_eligible,
        "hold_reason": hold_reason,
        "road": thread["road"],
        "road_family": road_family,
        "segment": thread["latest_segment"],
        "locality": thread["latest_locality"],
        "direction": thread["latest_direction"],
        "latest_reported_state": thread["latest_reported_state"],
        "last_source_update_at": thread["_last_dt"].isoformat(),
        "source_update_count": thread["source_update_count"],
        "recheck_due_at": thread["_recheck_dt"].isoformat(),
        "recheck_status": thread["recheck_status"],
        "scores": {
            "reported_state_severity": severity,
            "road_network_relevance": network_score,
            "local_specificity": local_score,
            "internal_triage": triage_score,
            "semantics": "INTERNAL_REVIEW_HEURISTIC_NOT_A_CURRENT_IMPACT_OR_PUBLICATION_SCORE",
            "local_specificity_basis": local_basis,
        },
        "evidence_chain": [_evidence_entry(event) for event in events],
        "requires_editorial_verification": True,
        "requires_official_source_recheck_before_reader_current_status_claim": True,
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "lifecycle": OUTPUT_LIFECYCLE,
    }


def build_candidates(
    thread_document: dict[str, Any], normalized_document: dict[str, Any]
) -> dict[str, Any]:
    as_of, threads = validate_thread_document(thread_document)
    indexed = validate_normalized_document(normalized_document)
    candidates: list[dict[str, Any]] = []
    referenced: set[str] = set()
    for thread in threads:
        events = _verify_thread_against_events(thread, indexed)
        overlap = referenced.intersection(thread["event_ids"])
        if overlap:
            raise ValueError("candidate generation refuses event evidence shared across logical threads")
        referenced.update(thread["event_ids"])
        candidates.append(_render_candidate(thread, events))

    candidates.sort(
        key=lambda item: (
            item["scores"]["internal_triage"],
            item["last_source_update_at"],
            item["candidate_id"],
        ),
        reverse=True,
    )
    return {
        "schema_version": "1.0",
        "product": "VÂLCEA CLAR internal INFOTRAFIC breaking candidates",
        "as_of": as_of.isoformat(),
        "candidate_count": len(candidates),
        "breaking_candidate_count": sum(
            1 for item in candidates if item["breaking_candidate_eligible"]
        ),
        "recheck_required_count": sum(
            1 for item in candidates if item["candidate_kind"] == "RECHECK_REQUIRED"
        ),
        "candidates": candidates,
        "policy": {
            "reader_facing_eligible": False,
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "current_status_claim_allowed": False,
            "requires_editorial_verification": True,
            "source_recheck_required_before_current_status_claim": True,
            "recheck_required_candidates_are_breaking_eligible": False,
            "ranking_semantics": "INTERNAL_TRIAGE_ONLY_NO_PUBLICATION_OR_CURRENT_STATUS_AUTHORITY",
        },
    }


def _load_json(path: str) -> dict[str, Any]:
    if path == "-":
        import sys

        return json.load(sys.stdin)
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build internal INFOTRAFIC Vâlcea breaking candidates"
    )
    parser.add_argument("threads", help="Thread-state JSON path")
    parser.add_argument("events", help="Normalized-event JSON path")
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout")
    args = parser.parse_args()

    result = build_candidates(_load_json(args.threads), _load_json(args.events))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)


if __name__ == "__main__":
    main()
