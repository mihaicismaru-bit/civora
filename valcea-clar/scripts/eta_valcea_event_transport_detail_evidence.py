#!/usr/bin/env python3
"""Bounded historical ETA event-transport evidence with explicit temporal limits.

This adapter reuses the existing ETA archive discovery and detail fetch/parser
primitives, but adds event-specific evidence tags needed by service journalism:
event identity, special-service offer, event/service window, departure times,
route/stops, temporary diversions and fare/ticketing context.

Historical event material is context only. A 2025 festival or rally notice must
never be promoted to a current route, timetable, special service or publication
fact without fresh first-party verification.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit

from eta_valcea_transport_archive_reference_adapter import build_receipt as build_archive_receipt
from eta_valcea_transport_detail_evidence import (
    VisibleTextParser,
    _fetch_detail,
    _sha256_bytes,
    _sha256_text,
)

SCHEMA = "ETA_VALCEA_EVENT_TRANSPORT_DETAIL_EVIDENCE_V1"
PARSER_VERSION = "ETA_VALCEA_EVENT_TRANSPORT_DETAIL_EVIDENCE_2026_09_02"
SOURCE_FAMILY = "ETA_VALCEA_PUBLIC_TRANSPORT"
AUTHORITY_CLASS = "FIRST_PARTY_LOCAL_PUBLIC_TRANSPORT_OPERATOR_HISTORICAL_EVENT_DETAIL"
OBSERVATION_STATE = "HISTORICAL_EVENT_TRANSPORT_EVIDENCE_NON_AUTHORIZING"
SOURCE_ASSERTION_SCOPE = "ETA_HISTORICAL_EVENT_STATEMENT_ONLY_CURRENTNESS_NOT_INFERRED"
MAX_DETAILS = 8
MAX_FIELD_EVIDENCE = 18
MAX_FRAGMENT_CHARS = 620

EVENT_CONTEXT_NEEDLES = (
    "eveniment",
    "festival",
    "fest ",
    "fest-",
    "deep forest",
    "we love music",
    "raliul",
    "rally",
    "participanților",
    "participantilor",
)
EVENT_SERVICE_OFFER_NEEDLES = (
    "pune la dispozi",
    "pune la dispoziție",
    "pune la dispozitie",
    "program de circula",
    "curse speciale",
    "cursă specială",
    "cursa speciala",
    "autobuz astfel",
    "un autobuz",
    "semicurs",
)
EVENT_ROUTE_OR_STOP_NEEDLES = (
    "stații tur",
    "statii tur",
    "stații retur",
    "statii retur",
    "stația",
    "statia",
    "stații",
    "statii",
    "traseu",
    "linia ",
    "liniei ",
    "dispecerat",
)
EVENT_DIVERSION_NEEDLES = (
    "deviere",
    "deviat",
    "deviată",
    "deviata",
    "traseu modificat",
    "trasee modificate",
    "nu vor mai tranzita",
    "nu mai tranzitează",
    "nu mai tranziteaza",
    "stație temporară",
    "statie temporara",
)
FARE_NEEDLES = (
    "tarif",
    "bilet",
    "lei",
    "card bancar",
    "24pay",
    "24 pay",
    "plata călătoriei",
    "plata calatoriei",
    "titlu de călătorie",
    "titlu de calatorie",
)

ROMANIAN_MONTH_PATTERN = (
    r"ian(?:uarie)?|feb(?:ruarie)?|mar(?:tie)?|apr(?:ilie)?|mai|"
    r"iun(?:ie)?|iul(?:ie)?|aug(?:ust)?|sep(?:tembrie)?|sept(?:embrie)?|"
    r"oct(?:ombrie)?|nov(?:iembrie)?|dec(?:embrie)?"
)
DATE_OR_WINDOW_RE = re.compile(
    rf"(?:\b20\d{{2}}\b.*\b(?:0?[1-9]|[12]\d|3[01])\s+(?:{ROMANIAN_MONTH_PATTERN})\b\s*[–—-]\s*\b(?:0?[1-9]|[12]\d|3[01])\s+(?:{ROMANIAN_MONTH_PATTERN})\b)"
    rf"|(?:\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-]20\d{{2}}\b\s*[–—-]\s*\b(?:0?[1-9]|[12]\d|3[01])[./-](?:0?[1-9]|1[0-2])[./-]20\d{{2}}\b)"
    rf"|(?:\b(?:în|in)\s+(?:intervalul|perioada)\b)"
    rf"|(?:\b(?:0?[1-9]|[12]\d|3[01])\s+(?:{ROMANIAN_MONTH_PATTERN})\s*[-–—]\s*(?:0?[1-9]|[12]\d|3[01])\s+(?:{ROMANIAN_MONTH_PATTERN})\b)",
    re.IGNORECASE,
)
TIME_RE = re.compile(r"(?<!\d)(?:[01]?\d|2[0-3])[:.]\d{2}(?!\d)")

ALLOWED_TAGS = {
    "EVENT_CONTEXT",
    "EVENT_SERVICE_OFFER",
    "EVENT_SERVICE_WINDOW",
    "EVENT_DEPARTURE_TIME",
    "EVENT_ROUTE_OR_STOP",
    "EVENT_TEMPORARY_DIVERSION",
    "FARE_OR_TICKETING_CONTEXT",
}

NON_AUTHORIZING_FLAGS = {
    "material_fact_use": False,
    "historical_state_promoted_to_current": False,
    "currentness_inference_authorized": False,
    "event_service_current_authorized": False,
    "route_service_current_authorized": False,
    "timetable_current_authorized": False,
    "fare_current_authorized": False,
    "same_event_dedupe_authorized": False,
    "breaking_authorized": False,
    "fact_kernel_write_authorized": False,
    "editorial_writer_authorized": False,
    "publication_authorized": False,
    "distribution_authorized": False,
    "runtime_persistence_authorized": False,
}


@dataclass(frozen=True)
class EventFieldEvidence:
    excerpt: str
    epistemic_tags: tuple[str, ...]
    evidence_origin: str
    source_evidence_sha256: str
    evidence_sha256: str
    source_assertion_scope: str = SOURCE_ASSERTION_SCOPE


def _event_tags(fragment: str) -> tuple[str, ...]:
    lowered = " ".join(fragment.casefold().split())
    tags: list[str] = []
    event_context = any(needle.casefold() in lowered for needle in EVENT_CONTEXT_NEEDLES)
    if event_context:
        tags.append("EVENT_CONTEXT")
    if any(needle.casefold() in lowered for needle in EVENT_SERVICE_OFFER_NEEDLES):
        tags.append("EVENT_SERVICE_OFFER")
    if DATE_OR_WINDOW_RE.search(fragment):
        tags.append("EVENT_SERVICE_WINDOW")
    if TIME_RE.search(fragment) and any(
        needle in lowered for needle in ("plecare", "ora ", "ore ", "interval", "program")
    ):
        tags.append("EVENT_DEPARTURE_TIME")
    if any(needle.casefold() in lowered for needle in EVENT_ROUTE_OR_STOP_NEEDLES):
        tags.append("EVENT_ROUTE_OR_STOP")
    if any(needle.casefold() in lowered for needle in EVENT_DIVERSION_NEEDLES):
        tags.append("EVENT_TEMPORARY_DIVERSION")
    if any(needle.casefold() in lowered for needle in FARE_NEEDLES):
        tags.append("FARE_OR_TICKETING_CONTEXT")
    return tuple(dict.fromkeys(tags))


def _candidate_fragments(segments: list[str]) -> list[str]:
    output: list[str] = []
    for segment in segments:
        for piece in re.split(r"(?<=[.!?;])\s+|\s+[•|]\s+", segment):
            cleaned = " ".join(piece.split()).strip(" -–—")
            if 12 <= len(cleaned) <= 2000:
                output.append(cleaned)
    return output


def _evidence_item(
    excerpt: str,
    tags: tuple[str, ...],
    origin: str,
    source_hash: str,
) -> EventFieldEvidence:
    rendered = excerpt[:MAX_FRAGMENT_CHARS]
    basis = json.dumps(
        {
            "excerpt": rendered,
            "epistemic_tags": tags,
            "evidence_origin": origin,
            "source_evidence_sha256": source_hash,
            "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return EventFieldEvidence(
        excerpt=rendered,
        epistemic_tags=tags,
        evidence_origin=origin,
        source_evidence_sha256=source_hash,
        evidence_sha256=_sha256_text(basis),
    )


def _extract_event_evidence(
    body: bytes,
    detail_sha256: str,
    index_title: str,
    index_evidence_sha256: str,
) -> tuple[tuple[EventFieldEvidence, ...], dict[str, int], str]:
    parser = VisibleTextParser()
    parser.feed(body.decode("utf-8", errors="replace"))

    evidence: list[EventFieldEvidence] = []
    seen: set[tuple[str, str]] = set()

    title_tags = _event_tags(index_title)
    if title_tags:
        evidence.append(_evidence_item(index_title, title_tags, "INDEX_TITLE", index_evidence_sha256))
        seen.add(("INDEX_TITLE", " ".join(index_title.casefold().split())))

    for fragment in _candidate_fragments(parser.evidence_segments()):
        tags = _event_tags(fragment)
        if not tags:
            continue
        normalized = " ".join(fragment.casefold().split())
        key = ("DETAIL_TEXT", normalized)
        if key in seen:
            continue
        seen.add(key)
        evidence.append(_evidence_item(fragment, tags, "DETAIL_TEXT", detail_sha256))
        if len(evidence) >= MAX_FIELD_EVIDENCE:
            break

    tag_counts: dict[str, int] = {}
    for item in evidence:
        for tag in item.epistemic_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    detail_specific = {
        tag
        for item in evidence
        if item.evidence_origin == "DETAIL_TEXT"
        for tag in item.epistemic_tags
        if tag not in {"EVENT_CONTEXT", "EVENT_SERVICE_WINDOW"}
    }
    if detail_specific:
        service_detail_state = "TEXT_SERVICE_DETAIL_CAPTURED_NON_AUTHORIZING"
    else:
        service_detail_state = "TITLE_OR_DATE_CONTEXT_ONLY_SERVICE_DETAIL_UNRESOLVED"

    return tuple(evidence), dict(sorted(tag_counts.items())), service_detail_state


def _eligible_event_reference(ref: dict[str, Any]) -> bool:
    return (
        str(ref.get("source_kind") or "") == "COMMUNIQUES_ARCHIVE"
        and bool(ref.get("historical_reference"))
        and int(ref.get("archive_year") or 0) == 2025
        and str(ref.get("topic_class") or "") == "EVENT_TRANSPORT"
        and bool(ref.get("target_url"))
    )


def _base_payload(status: str, archive: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "parser_version": PARSER_VERSION,
        "status": status,
        "source_family": SOURCE_FAMILY,
        "authority_class": AUTHORITY_CLASS,
        "observation_state": OBSERVATION_STATE,
        "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "coverage_note": "BOUNDED_ETA_2025_EVENT_TRANSPORT_DETAIL_EVIDENCE_TEXT_AND_INDEX_TITLE_ONLY",
        "archive_run_id": (archive or {}).get("run_id"),
        "archive_reference_count": (archive or {}).get("reference_count", 0),
        "eligible_event_detail_count": 0,
        "event_detail_evidence_count": 0,
        "event_detail_hold_count": 0,
        "details": [],
        "holds": [],
        "limitations": {
            "archive_event_notice_is_historical_context_not_current_status": True,
            "index_title_is_reference_evidence_not_service_detail_proof": True,
            "image_only_service_details_are_not_extracted_or_inferred": True,
            "event_date_does_not_authorize_current_or_future_service": True,
            "departure_times_require_fresh_first_party_verification_before_reader_use": True,
            "route_or_stop_details_require_fresh_first_party_verification_before_reader_use": True,
            "temporary_diversion_requires_fresh_first_party_verification_before_reader_use": True,
            "fare_context_requires_current_fare_reconciliation": True,
            "sample_is_bounded_to_eta_2025_archive_event_transport": True,
        },
        "interpretation": (
            "EVENT_TRANSPORT_EVIDENCE_SUPPORTS_DATE_BOUND_EDITORIAL_CONTEXT_ONLY;"
            "NO_CURRENT_SERVICE_OR_FUTURE_EVENT_SERVICE_MAY_BE_INFERRED"
        ),
        **NON_AUTHORIZING_FLAGS,
    }


def build_live_receipt() -> dict[str, Any]:
    try:
        archive = build_archive_receipt()
    except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
        payload = _base_payload("HOLD_ARCHIVE_FETCH_FAILED_NON_AUTHORIZING")
        payload["holds"] = [{
            "target_url": "https://eta-bus.ro/comunicate/2025",
            "state": "HOLD_ARCHIVE_FETCH_FAILED_NON_AUTHORIZING",
            "reason": f"{type(exc).__name__}:{exc}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    if archive.get("status") != "PASS":
        payload = _base_payload("HOLD_ARCHIVE_NOT_PASS_NON_AUTHORIZING", archive)
        payload["holds"] = [{
            "target_url": "https://eta-bus.ro/comunicate/2025",
            "state": "HOLD_ARCHIVE_NOT_PASS_NON_AUTHORIZING",
            "reason": f"archive_status:{archive.get('status')}",
        }]
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payload["run_id"] = _sha256_text(stable)[:24]
        return payload

    candidates = [
        ref for ref in archive.get("references", []) if _eligible_event_reference(ref)
    ][:MAX_DETAILS]

    details: list[dict[str, Any]] = []
    holds: list[dict[str, str]] = []
    for ref in candidates:
        target_url = str(ref.get("target_url") or "")
        try:
            body, final_url, content_type = _fetch_detail(target_url)
            detail_hash = _sha256_bytes(body)
            index_hash = str(ref.get("evidence_sha256") or "")
            field_evidence, tag_counts, service_detail_state = _extract_event_evidence(
                body,
                detail_hash,
                str(ref.get("title") or ""),
                index_hash,
            )
            details.append(
                {
                    "source_kind": "COMMUNIQUES_ARCHIVE_EVENT_DETAIL",
                    "topic_class": "EVENT_TRANSPORT",
                    "archive_year": 2025,
                    "historical_reference": True,
                    "index_title": str(ref.get("title") or ""),
                    "detail_url": final_url,
                    "detail_host": (urlsplit(final_url).hostname or "").lower(),
                    "content_type": content_type,
                    "content_length": len(body),
                    "detail_sha256": detail_hash,
                    "archive_index_evidence_sha256": index_hash,
                    "field_evidence": [asdict(item) for item in field_evidence],
                    "tag_counts": tag_counts,
                    "service_detail_state": service_detail_state,
                    "currentness_state": "HISTORICAL_EVENT_CONTEXT_ONLY_CURRENT_SERVICE_UNRESOLVED",
                    "verification_state": "ETA_EVENT_SOURCE_EVIDENCE_CAPTURED_NON_AUTHORIZING",
                    "authority_class": AUTHORITY_CLASS,
                    "observation_state": OBSERVATION_STATE,
                    "source_assertion_scope": SOURCE_ASSERTION_SCOPE,
                    "parser_version": PARSER_VERSION,
                }
            )
        except (HTTPError, URLError, OSError, RuntimeError, ValueError) as exc:
            holds.append(
                {
                    "target_url": target_url,
                    "archive_index_evidence_sha256": str(ref.get("evidence_sha256") or ""),
                    "state": "HOLD_EVENT_DETAIL_FETCH_FAILED_NON_AUTHORIZING",
                    "reason": f"{type(exc).__name__}:{exc}",
                }
            )

    if not candidates:
        status = "HOLD_NO_EVENT_TRANSPORT_REFERENCES"
    elif not details:
        status = "HOLD_NO_EVENT_TRANSPORT_DETAIL_EVIDENCE"
    else:
        status = "PASS"

    payload = _base_payload(status, archive)
    payload.update(
        {
            "eligible_event_detail_count": len(candidates),
            "event_detail_evidence_count": len(details),
            "event_detail_hold_count": len(holds),
            "details": details,
            "holds": holds,
        }
    )
    stable = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["run_id"] = _sha256_text(stable)[:24]
    return payload


def _self_test() -> None:
    title = "Deep Forest Fest 2025 - 01 August - 03 August"
    title_tags = set(_event_tags(title))
    assert {"EVENT_CONTEXT", "EVENT_SERVICE_WINDOW"} <= title_tags

    service = (
        "În intervalul 01.08.2025 - 03.08.2025, ETA SA pune la dispoziția "
        "participanților un autobuz. Stații Tur: Hermes - Deep Forest Fest. "
        "Ore de plecare: 13:00, 15:00."
    )
    service_tags = set(_event_tags(service))
    assert {
        "EVENT_CONTEXT",
        "EVENT_SERVICE_OFFER",
        "EVENT_SERVICE_WINDOW",
        "EVENT_DEPARTURE_TIME",
        "EVENT_ROUTE_OR_STOP",
    } <= service_tags

    diverted = (
        "Pentru eveniment, Linia 5 va fi deviată temporar și nu va mai tranzita "
        "stația Centrală în intervalul 18:00-23:00."
    )
    diverted_tags = set(_event_tags(diverted))
    assert {
        "EVENT_CONTEXT",
        "EVENT_SERVICE_WINDOW",
        "EVENT_DEPARTURE_TIME",
        "EVENT_ROUTE_OR_STOP",
        "EVENT_TEMPORARY_DIVERSION",
    } <= diverted_tags

    image_only_html = (
        "<html><body><main><p>Publicat la: 1 Aug 2025</p><img src='program.png'></main></body></html>"
    ).encode("utf-8")
    detail_hash = _sha256_bytes(image_only_html)
    fields, counts, state = _extract_event_evidence(
        image_only_html,
        detail_hash,
        title,
        "a" * 64,
    )
    assert fields
    assert fields[0].evidence_origin == "INDEX_TITLE"
    assert {"EVENT_CONTEXT", "EVENT_SERVICE_WINDOW"} <= set(fields[0].epistemic_tags)
    assert state == "TITLE_OR_DATE_CONTEXT_ONLY_SERVICE_DETAIL_UNRESOLVED"
    assert set(counts) <= ALLOWED_TAGS
    assert all(re.fullmatch(r"[0-9a-f]{64}", item.evidence_sha256) for item in fields)
    assert all(value is False for value in NON_AUTHORIZING_FLAGS.values())

    eligible = {
        "source_kind": "COMMUNIQUES_ARCHIVE",
        "historical_reference": True,
        "archive_year": 2025,
        "topic_class": "EVENT_TRANSPORT",
        "target_url": "https://eta-bus.ro/comunicate/deep-forest-fest-2025",
    }
    assert _eligible_event_reference(eligible)
    assert not _eligible_event_reference({**eligible, "archive_year": 2024})
    assert not _eligible_event_reference({**eligible, "topic_class": "ROUTE_CHANGE"})
    print("ETA Vâlcea event transport detail evidence self-test PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="ETA Vâlcea historical event-transport detail evidence")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--live-check", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return 0
    if not args.live_check:
        parser.error("use --self-test or --live-check")

    payload = build_live_receipt()
    rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0 if payload["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
