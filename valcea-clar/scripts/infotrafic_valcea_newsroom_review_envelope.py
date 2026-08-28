#!/usr/bin/env python3
"""Build a fail-closed, non-persistent newsroom review envelope for INFOTRAFIC Vâlcea.

The envelope is a deterministic triage surface only. It validates the upstream
breaking-candidate document, groups candidates into explicit human-review lanes,
and preserves the official evidence chain. It cannot assert current traffic status,
write Fact Kernel state, persist a queue, publish, or project reader-facing content.
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

BUCHAREST = ZoneInfo("Europe/Bucharest")
OFFICIAL_HOST = "politiaromana.ro"
INPUT_PRODUCT = "VÂLCEA CLAR internal INFOTRAFIC breaking candidates"
INPUT_LIFECYCLE = "INTERNAL_BREAKING_CANDIDATE_REVIEW_REQUIRED"
OUTPUT_PRODUCT = "VÂLCEA CLAR internal INFOTRAFIC newsroom review envelope"
OUTPUT_LIFECYCLE = "INTERNAL_NEWSROOM_REVIEW_ENVELOPE_ONLY"
NORMALIZATION_ID = "DETERMINISTIC_INTERNAL_EVENT_V1"

CANDIDATE_ID_RE = re.compile(r"^traffic-candidate-[0-9a-f]{24}$", re.IGNORECASE)
THREAD_ID_RE = re.compile(r"^traffic-logical-thread-[0-9a-f]{24}$", re.IGNORECASE)
EVENT_ID_RE = re.compile(r"^traffic-event-[0-9a-f]{24}$", re.IGNORECASE)
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ROAD_RE = re.compile(r"^(?:DN|DJ|DC|A)\d{1,4}[A-Z]?$", re.IGNORECASE)

ALLOWED_KINDS = {"NEW", "UPDATE", "RESOLVED", "RECHECK_REQUIRED"}
ALLOWED_STATES = {"TRAFFIC_STOPPED", "ALTERNATE", "HEAVY", "RESUMED", "UNKNOWN"}
ALLOWED_RECHECK = {
    "CLOSED_BY_EXPLICIT_RESUMED_UPDATE",
    "RECHECK_OVERDUE",
    "RECHECK_NOT_YET_DUE",
}
LANE_PRIORITY = {
    "URGENT_BREAKING_REVIEW": 5,
    "RESOLUTION_REVIEW": 4,
    "STANDARD_BREAKING_REVIEW": 3,
    "SOURCE_RECHECK": 2,
    "EVIDENCE_HOLD": 1,
}

INPUT_POLICY = {
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
}

CANDIDATE_BOUNDARY = {
    "requires_editorial_verification": True,
    "requires_official_source_recheck_before_reader_current_status_claim": True,
    "current_status_claim_allowed": False,
    "reader_facing_eligible": False,
    "publication_authority": "NONE",
    "public_projection": False,
    "auto_publication": False,
    "persistence_authority": "NONE",
    "lifecycle": INPUT_LIFECYCLE,
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


def _require_exact_policy(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("review envelope requires candidate policy object")
    if value != INPUT_POLICY:
        raise ValueError("review envelope refuses upstream candidate policy drift")


def _validate_article_url(value: Any) -> str:
    text = clean_text(value)
    parsed = urlsplit(text)
    if parsed.scheme.casefold() != "https" or parsed.hostname is None:
        raise ValueError("review evidence requires an HTTPS article_url")
    if parsed.hostname.casefold() != OFFICIAL_HOST or parsed.username or parsed.password:
        raise ValueError("review evidence refuses non-official article_url")
    if not parsed.path.startswith("/ro/info-trafic/"):
        raise ValueError("review evidence requires a direct INFOTRAFIC article_url")
    return text


def _optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be string or null")
    text = clean_text(value)
    if not text:
        raise ValueError(f"{field} cannot be blank")
    return text


def _validate_scores(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("candidate requires scores object")
    required = {
        "reported_state_severity",
        "road_network_relevance",
        "local_specificity",
        "internal_triage",
        "semantics",
        "local_specificity_basis",
    }
    if set(value) != required:
        raise ValueError("review envelope refuses candidate score schema drift")
    for field in (
        "reported_state_severity",
        "road_network_relevance",
        "local_specificity",
        "internal_triage",
    ):
        score = value[field]
        if isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100:
            raise ValueError(f"candidate {field} must be integer 0..100")
    if value["semantics"] != "INTERNAL_REVIEW_HEURISTIC_NOT_A_CURRENT_IMPACT_OR_PUBLICATION_SCORE":
        raise ValueError("review envelope refuses candidate score semantics drift")
    if value["local_specificity_basis"] not in {
        "EXPLICIT_SEGMENT",
        "EXPLICIT_LOCALITY",
        "ROAD_ONLY",
    }:
        raise ValueError("review envelope refuses local-specificity vocabulary drift")
    return dict(value)


def _validate_evidence_chain(value: Any, last_source_update: datetime) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise ValueError("candidate requires non-empty evidence_chain")
    seen_events: set[str] = set()
    validated: list[dict[str, Any]] = []
    previous: datetime | None = None
    for raw in value:
        if not isinstance(raw, dict):
            raise ValueError("candidate evidence entries must be objects")
        if set(raw) != {
            "event_id",
            "source_signal_id",
            "article_url",
            "source_timestamp",
            "source_content_sha256",
            "normalization",
        }:
            raise ValueError("review envelope refuses evidence schema drift")
        event_id = clean_text(raw.get("event_id"))
        if not EVENT_ID_RE.fullmatch(event_id) or event_id in seen_events:
            raise ValueError("review envelope requires unique canonical evidence event ids")
        seen_events.add(event_id)
        article_url = _validate_article_url(raw.get("article_url"))
        timestamp = parse_timestamp(raw.get("source_timestamp"), "evidence source_timestamp")
        if previous is not None and timestamp < previous:
            raise ValueError("review envelope refuses out-of-order evidence chain")
        previous = timestamp
        sha = clean_text(raw.get("source_content_sha256")).lower()
        if not SHA256_RE.fullmatch(sha):
            raise ValueError("review evidence requires a 64-hex source_content_sha256")
        if raw.get("normalization") != NORMALIZATION_ID:
            raise ValueError("review envelope requires canonical evidence normalization")
        source_signal_id = _optional_text(raw.get("source_signal_id"), "source_signal_id")
        validated.append(
            {
                "event_id": event_id,
                "source_signal_id": source_signal_id,
                "article_url": article_url,
                "source_timestamp": timestamp.isoformat(),
                "source_content_sha256": sha,
                "normalization": NORMALIZATION_ID,
            }
        )
    if previous != last_source_update:
        raise ValueError("review envelope requires latest evidence timestamp to match candidate")
    return validated


def _validate_candidate(raw: Any, as_of: datetime) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("review envelope candidates must be objects")
    for field, expected in CANDIDATE_BOUNDARY.items():
        if raw.get(field) != expected:
            raise ValueError(f"review envelope refuses candidate boundary drift: {field}")

    candidate_id = clean_text(raw.get("candidate_id"))
    dedupe_key = clean_text(raw.get("dedupe_key"))
    if not CANDIDATE_ID_RE.fullmatch(candidate_id):
        raise ValueError("review envelope requires canonical candidate_id")
    if not THREAD_ID_RE.fullmatch(dedupe_key):
        raise ValueError("review envelope requires canonical dedupe_key")

    kind = clean_text(raw.get("candidate_kind")).upper()
    if kind not in ALLOWED_KINDS:
        raise ValueError("review envelope refuses unknown candidate kind")
    eligible = raw.get("breaking_candidate_eligible")
    if not isinstance(eligible, bool):
        raise ValueError("breaking_candidate_eligible must be boolean")
    hold_reason = raw.get("hold_reason")
    if hold_reason is not None:
        hold_reason = clean_text(hold_reason)
        if not hold_reason:
            raise ValueError("hold_reason cannot be blank")

    road = clean_text(raw.get("road")).upper()
    if not ROAD_RE.fullmatch(road):
        raise ValueError("review envelope requires canonical road")
    state = clean_text(raw.get("latest_reported_state")).upper()
    if state not in ALLOWED_STATES:
        raise ValueError("review envelope refuses unknown traffic state")
    recheck_status = clean_text(raw.get("recheck_status"))
    if recheck_status not in ALLOWED_RECHECK:
        raise ValueError("review envelope refuses unknown recheck status")

    last_source_update = parse_timestamp(raw.get("last_source_update_at"), "last_source_update_at")
    recheck_due = parse_timestamp(raw.get("recheck_due_at"), "recheck_due_at")
    if last_source_update > as_of or recheck_due < last_source_update:
        raise ValueError("review envelope refuses impossible candidate chronology")

    update_count = raw.get("source_update_count")
    if isinstance(update_count, bool) or not isinstance(update_count, int) or update_count < 1:
        raise ValueError("source_update_count must be a positive integer")

    if kind == "NEW" and update_count != 1:
        raise ValueError("NEW candidate requires exactly one source update")
    if kind == "UPDATE" and update_count < 2:
        raise ValueError("UPDATE candidate requires at least two source updates")
    if kind == "RESOLVED":
        if state != "RESUMED" or recheck_status != "CLOSED_BY_EXPLICIT_RESUMED_UPDATE":
            raise ValueError("RESOLVED candidate requires explicit resumed closure")
    elif state == "RESUMED":
        raise ValueError("RESUMED state requires RESOLVED candidate kind")

    if kind == "RECHECK_REQUIRED":
        if eligible or recheck_status != "RECHECK_OVERDUE":
            raise ValueError("RECHECK_REQUIRED candidate must be held and overdue")
        if hold_reason != "OFFICIAL_SOURCE_RECHECK_REQUIRED_BEFORE_BREAKING_CANDIDATE":
            raise ValueError("RECHECK_REQUIRED candidate requires canonical hold reason")
    elif state == "UNKNOWN":
        if eligible or hold_reason != "NO_EXPLICIT_TRAFFIC_IMPACT_STATE":
            raise ValueError("UNKNOWN impact candidate must remain on evidence hold")
    else:
        if not eligible or hold_reason is not None:
            raise ValueError("verified non-overdue candidate eligibility drift")

    segment = raw.get("segment")
    if segment is not None:
        if not isinstance(segment, dict) or set(segment) != {"start", "end"}:
            raise ValueError("candidate segment requires start/end")
        segment = {
            "start": _optional_text(segment.get("start"), "segment.start"),
            "end": _optional_text(segment.get("end"), "segment.end"),
        }
        if segment["start"] is None or segment["end"] is None:
            raise ValueError("candidate segment endpoints cannot be null")
    locality = _optional_text(raw.get("locality"), "locality")
    direction = _optional_text(raw.get("direction"), "direction")
    scores = _validate_scores(raw.get("scores"))
    evidence = _validate_evidence_chain(raw.get("evidence_chain"), last_source_update)
    if len(evidence) != update_count:
        raise ValueError("source_update_count must match evidence chain length")

    return {
        "candidate_id": candidate_id,
        "dedupe_key": dedupe_key,
        "candidate_kind": kind,
        "breaking_candidate_eligible": eligible,
        "hold_reason": hold_reason,
        "road": road,
        "segment": segment,
        "locality": locality,
        "direction": direction,
        "latest_reported_state": state,
        "last_source_update_at": last_source_update.isoformat(),
        "source_update_count": update_count,
        "recheck_due_at": recheck_due.isoformat(),
        "recheck_status": recheck_status,
        "scores": scores,
        "evidence_chain": evidence,
    }


def validate_candidate_document(document: Any) -> tuple[datetime, list[dict[str, Any]]]:
    if not isinstance(document, dict):
        raise ValueError("review envelope requires a candidate document")
    if document.get("schema_version") != "1.0" or document.get("product") != INPUT_PRODUCT:
        raise ValueError("review envelope refuses unknown candidate document")
    _require_exact_policy(document.get("policy"))
    as_of = parse_timestamp(document.get("as_of"), "as_of")
    candidates = document.get("candidates")
    if not isinstance(candidates, list):
        raise ValueError("review envelope requires candidates list")
    if document.get("candidate_count") != len(candidates):
        raise ValueError("review envelope refuses candidate_count drift")
    if document.get("breaking_candidate_count") != sum(
        1 for item in candidates if isinstance(item, dict) and item.get("breaking_candidate_eligible") is True
    ):
        raise ValueError("review envelope refuses breaking_candidate_count drift")
    if document.get("recheck_required_count") != sum(
        1 for item in candidates if isinstance(item, dict) and item.get("candidate_kind") == "RECHECK_REQUIRED"
    ):
        raise ValueError("review envelope refuses recheck_required_count drift")

    validated: list[dict[str, Any]] = []
    candidate_ids: set[str] = set()
    dedupe_keys: set[str] = set()
    for raw in candidates:
        item = _validate_candidate(raw, as_of)
        if item["candidate_id"] in candidate_ids:
            raise ValueError("review envelope refuses duplicate candidate_id")
        if item["dedupe_key"] in dedupe_keys:
            raise ValueError("review envelope refuses multiple review candidates for one logical thread")
        candidate_ids.add(item["candidate_id"])
        dedupe_keys.add(item["dedupe_key"])
        validated.append(item)
    return as_of, validated


def _review_lane(candidate: dict[str, Any]) -> str:
    if candidate["candidate_kind"] == "RECHECK_REQUIRED":
        return "SOURCE_RECHECK"
    if not candidate["breaking_candidate_eligible"]:
        return "EVIDENCE_HOLD"
    if candidate["candidate_kind"] == "RESOLVED":
        return "RESOLUTION_REVIEW"
    if candidate["scores"]["internal_triage"] >= 80:
        return "URGENT_BREAKING_REVIEW"
    return "STANDARD_BREAKING_REVIEW"


def _review_item_id(candidate: dict[str, Any], lane: str) -> str:
    raw = "\0".join(
        [candidate["candidate_id"], candidate["last_source_update_at"], lane]
    )
    return "newsroom-review-" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _render_review_item(candidate: dict[str, Any]) -> dict[str, Any]:
    lane = _review_lane(candidate)
    return {
        "review_item_id": _review_item_id(candidate, lane),
        "candidate_id": candidate["candidate_id"],
        "dedupe_key": candidate["dedupe_key"],
        "review_lane": lane,
        "review_status": "HUMAN_REVIEW_REQUIRED",
        "editorial_decision_state": "UNREVIEWED",
        "candidate_kind": candidate["candidate_kind"],
        "breaking_candidate_eligible": candidate["breaking_candidate_eligible"],
        "hold_reason": candidate["hold_reason"],
        "road": candidate["road"],
        "segment": candidate["segment"],
        "locality": candidate["locality"],
        "direction": candidate["direction"],
        "latest_reported_state": candidate["latest_reported_state"],
        "last_source_update_at": candidate["last_source_update_at"],
        "recheck_due_at": candidate["recheck_due_at"],
        "recheck_status": candidate["recheck_status"],
        "internal_triage_score": candidate["scores"]["internal_triage"],
        "evidence_chain": candidate["evidence_chain"],
        "requires_editorial_verification": True,
        "requires_official_source_recheck_before_reader_current_status_claim": True,
        "current_status_claim_allowed": False,
        "reader_facing_eligible": False,
        "fact_kernel_authority": "NONE",
        "writer_authority": "NONE",
        "publication_authority": "NONE",
        "public_projection": False,
        "auto_publication": False,
        "persistence_authority": "NONE",
        "lifecycle": OUTPUT_LIFECYCLE,
    }


def build_review_envelope(candidate_document: dict[str, Any]) -> dict[str, Any]:
    as_of, candidates = validate_candidate_document(candidate_document)
    items = [_render_review_item(candidate) for candidate in candidates]
    items.sort(
        key=lambda item: (
            LANE_PRIORITY[item["review_lane"]],
            item["internal_triage_score"],
            item["last_source_update_at"],
            item["review_item_id"],
        ),
        reverse=True,
    )
    lane_counts = {
        lane: sum(1 for item in items if item["review_lane"] == lane)
        for lane in LANE_PRIORITY
    }
    return {
        "schema_version": "1.0",
        "product": OUTPUT_PRODUCT,
        "as_of": as_of.isoformat(),
        "review_item_count": len(items),
        "lane_counts": lane_counts,
        "items": items,
        "policy": {
            "reader_facing_eligible": False,
            "fact_kernel_authority": "NONE",
            "writer_authority": "NONE",
            "publication_authority": "NONE",
            "public_projection": False,
            "auto_publication": False,
            "persistence_authority": "NONE",
            "current_status_claim_allowed": False,
            "editorial_decision_authority": "HUMAN_EDITOR_OUTSIDE_THIS_STAGE",
            "stateful_queue": False,
            "source_recheck_required_before_current_status_claim": True,
            "review_lane_semantics": "INTERNAL_TRIAGE_ONLY_NO_ELIGIBILITY_PROMOTION_OR_PUBLICATION_AUTHORITY",
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
        description="Build internal INFOTRAFIC Vâlcea newsroom review envelope"
    )
    parser.add_argument("candidates", help="Breaking-candidate JSON path")
    parser.add_argument("--output", default="-", help="Output JSON path, or '-' for stdout")
    args = parser.parse_args()
    result = build_review_envelope(_load_json(args.candidates))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output == "-":
        print(rendered, end="")
    else:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)


if __name__ == "__main__":
    main()
