#!/usr/bin/env python3
"""Fail-closed CFR Craiova Vâlcea-scope bulletin reference change detector.

Consumes two snapshots produced by cfr_craiova_valcea_scope_validator.py and
reports only whether the latest first-party CFR bulletin reference advanced and
whether the *new* bulletin contained an explicit Vâlcea rail anchor.

This is reference-metadata intelligence only. It never turns a bulletin into an
"active restriction", delay, timetable impact, train-specific claim, breaking
news item, or public article.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

EXPECTED_SOURCE_ID = "scope-cfr-srcf-craiova-valcea-bulletin-docx"
EXPECTED_TAXONOMY_VERSION = "2026-08-31.1"
TAXONOMY_VERSION = "2026-08-31.1"
SOURCE_ID = "change-cfr-srcf-craiova-valcea-bulletin-reference"
SOURCE_NAME = "CNCF CFR SA — SRCF Craiova Vâlcea bulletin reference change detector"
SOURCE_TIER = "T1_OFFICIAL_RAIL_INFRASTRUCTURE"

UPSTREAM_SOURCE_ID = "reference-cfr-srcf-craiova-speed-restriction-bulletins"
HOST = "cfr.ro"
DOCUMENT_PREFIX = "/wp-content/uploads/"

ALLOWED_REVIEW_STATES = {
    "REFERENCE_ONLY",
    "SCOPE_CONFIRMED_REFERENCE_ONLY",
}
FORBIDDEN_TRUE_FLAGS = {
    "speed_restriction_details_extracted",
    "current_operational_status_inferred",
    "delay_or_timetable_impact_inferred",
    "train_specific_impact_inferred",
    "breaking_news_promotion_allowed",
    "inferred_photo_rights_allowed",
    "persistence_allowed",
    "fact_kernel_promotion_allowed",
    "writer_allowed",
    "public_projection_allowed",
}


@dataclass(frozen=True)
class BulletinReferenceChange:
    change_id: str
    source_id: str
    taxonomy_version: str
    source_name: str
    source_tier: str
    review_status: str
    change_class: str
    previous_signal_id: Optional[str]
    current_signal_id: Optional[str]
    previous_upstream_signal_id: Optional[str]
    current_upstream_signal_id: Optional[str]
    previous_period_start: Optional[str]
    previous_period_end: Optional[str]
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    previous_scope_state: Optional[str]
    current_scope_state: Optional[str]
    previous_document_url: Optional[str]
    current_document_url: Optional[str]
    current_matched_anchors: tuple[str, ...]
    period_start_delta_days: Optional[int]
    basis: str
    change_sha256: str
    hold_reason: Optional[str]
    publication_authority: str = "NONE"
    operational_restriction_claim_allowed: bool = False
    delay_or_timetable_claim_allowed: bool = False
    train_specific_claim_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def digest(*parts: Any) -> str:
    return hashlib.sha256(
        "\0".join(clean(part) for part in parts).encode("utf-8")
    ).hexdigest()


def parse_iso(value: Any) -> Optional[date]:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def valid_sha256(value: Any) -> bool:
    text = clean(value)
    return len(text) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in text)


def normalize_docx_url(value: Any) -> Optional[str]:
    text = clean(value)
    parsed = urlsplit(text)
    path = re.sub(r"/+", "/", unquote(parsed.path or "/"))
    if (
        parsed.scheme.casefold() != "https"
        or (parsed.hostname or "").casefold() != HOST
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or not path.startswith(DOCUMENT_PREFIX)
        or not path.casefold().endswith(".docx")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return urlunsplit(("https", HOST, path, "", ""))


def optional_text(value: Any) -> Optional[str]:
    text = clean(value)
    return text or None


def validate_snapshot(payload: dict[str, Any], label: str) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    if clean(payload.get("status")) != "PASS":
        return None, f"{label}_UPSTREAM_ENVELOPE_NOT_PASS"
    if clean(payload.get("source_id")) != EXPECTED_SOURCE_ID:
        return None, f"{label}_UPSTREAM_SOURCE_DRIFT"
    if clean(payload.get("taxonomy_version")) != EXPECTED_TAXONOMY_VERSION:
        return None, f"{label}_UPSTREAM_TAXONOMY_DRIFT"

    safety = payload.get("safety")
    if not isinstance(safety, dict):
        return None, f"{label}_SAFETY_ENVELOPE_MISSING"
    if safety.get("scope_confirmation_only") is not True:
        return None, f"{label}_SCOPE_ONLY_BOUNDARY_MISSING"
    for flag in FORBIDDEN_TRUE_FLAGS:
        if safety.get(flag) is True:
            return None, f"{label}_UNSAFE_BOUNDARY_{flag.upper()}"

    signal = payload.get("signal")
    if not isinstance(signal, dict):
        return None, f"{label}_SIGNAL_MISSING"
    if clean(signal.get("source_id")) != EXPECTED_SOURCE_ID:
        return None, f"{label}_SIGNAL_SOURCE_DRIFT"
    if clean(signal.get("taxonomy_version")) != EXPECTED_TAXONOMY_VERSION:
        return None, f"{label}_SIGNAL_TAXONOMY_DRIFT"
    if clean(signal.get("upstream_source_id")) != UPSTREAM_SOURCE_ID:
        return None, f"{label}_REFERENCE_SOURCE_DRIFT"
    if clean(signal.get("review_status")) not in ALLOWED_REVIEW_STATES:
        return None, f"{label}_UNEXPECTED_REVIEW_STATUS"
    if clean(signal.get("hold_reason")):
        return None, f"{label}_UPSTREAM_SIGNAL_HELD"

    start = parse_iso(signal.get("period_start"))
    end = parse_iso(signal.get("period_end"))
    if not start or not end or start > end:
        return None, f"{label}_INVALID_PERIOD"
    if not clean(signal.get("signal_id")) or not clean(signal.get("upstream_signal_id")):
        return None, f"{label}_SIGNAL_ID_MISSING"

    document_url = normalize_docx_url(signal.get("document_url"))
    if not document_url or document_url != clean(signal.get("document_url")):
        return None, f"{label}_DOCUMENT_URL_INVALID"
    if not valid_sha256(signal.get("document_sha256")):
        return None, f"{label}_DOCUMENT_HASH_INVALID"
    if not valid_sha256(signal.get("document_text_sha256")):
        return None, f"{label}_DOCUMENT_TEXT_HASH_INVALID"

    anchors = signal.get("matched_anchors")
    if not isinstance(anchors, list) and not isinstance(anchors, tuple):
        return None, f"{label}_ANCHORS_SHAPE_INVALID"
    normalized_anchors = tuple(clean(item) for item in anchors if clean(item))
    if len(set(normalized_anchors)) != len(normalized_anchors):
        return None, f"{label}_DUPLICATE_ANCHORS"

    scope_state = clean(signal.get("scope_state"))
    review_status = clean(signal.get("review_status"))
    if scope_state == "VALCEA_EXPLICIT_DOCUMENT_REFERENCE":
        if review_status != "SCOPE_CONFIRMED_REFERENCE_ONLY" or not normalized_anchors:
            return None, f"{label}_VALCEA_SCOPE_INCONSISTENT"
    elif scope_state == "REGIONAL_REFERENCE_ONLY":
        if review_status != "REFERENCE_ONLY" or normalized_anchors:
            return None, f"{label}_REGIONAL_SCOPE_INCONSISTENT"
    else:
        return None, f"{label}_UNEXPECTED_SCOPE_STATE"

    for flag in FORBIDDEN_TRUE_FLAGS:
        if signal.get(flag) is True:
            return None, f"{label}_UNSAFE_SIGNAL_BOUNDARY_{flag.upper()}"
    return signal, None


def make_change(
    previous: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
    change_class: str,
    review_status: str,
    *,
    hold_reason: Optional[str] = None,
    delta_days: Optional[int] = None,
) -> BulletinReferenceChange:
    prev = previous or {}
    curr = current or {}
    current_anchors_raw = curr.get("matched_anchors")
    current_anchors = tuple(
        clean(item)
        for item in current_anchors_raw
        if clean(item)
    ) if isinstance(current_anchors_raw, (list, tuple)) else ()
    fingerprint = digest(
        change_class,
        review_status,
        hold_reason or "",
        prev.get("signal_id"),
        curr.get("signal_id"),
        prev.get("upstream_signal_id"),
        curr.get("upstream_signal_id"),
        prev.get("period_start"),
        prev.get("period_end"),
        curr.get("period_start"),
        curr.get("period_end"),
        prev.get("scope_state"),
        curr.get("scope_state"),
        prev.get("document_url"),
        curr.get("document_url"),
        ",".join(current_anchors),
        "" if delta_days is None else delta_days,
    )
    return BulletinReferenceChange(
        change_id=f"cfr-valcea-change-{fingerprint[:20]}",
        source_id=SOURCE_ID,
        taxonomy_version=TAXONOMY_VERSION,
        source_name=SOURCE_NAME,
        source_tier=SOURCE_TIER,
        review_status=review_status,
        change_class=change_class,
        previous_signal_id=optional_text(prev.get("signal_id")),
        current_signal_id=optional_text(curr.get("signal_id")),
        previous_upstream_signal_id=optional_text(prev.get("upstream_signal_id")),
        current_upstream_signal_id=optional_text(curr.get("upstream_signal_id")),
        previous_period_start=optional_text(prev.get("period_start")),
        previous_period_end=optional_text(prev.get("period_end")),
        current_period_start=optional_text(curr.get("period_start")),
        current_period_end=optional_text(curr.get("period_end")),
        previous_scope_state=optional_text(prev.get("scope_state")),
        current_scope_state=optional_text(curr.get("scope_state")),
        previous_document_url=optional_text(prev.get("document_url")),
        current_document_url=optional_text(curr.get("document_url")),
        current_matched_anchors=current_anchors,
        period_start_delta_days=delta_days,
        basis="CFR_FIRST_PARTY_BULLETIN_REFERENCE_AND_EXPLICIT_VALCEA_ANCHOR_ONLY_NOT_OPERATIONAL_STATUS",
        change_sha256=fingerprint,
        hold_reason=hold_reason,
    )


def detect(previous_payload: dict[str, Any], current_payload: dict[str, Any]) -> BulletinReferenceChange:
    previous, prev_problem = validate_snapshot(previous_payload, "PREVIOUS")
    current, curr_problem = validate_snapshot(current_payload, "CURRENT")
    problem = prev_problem or curr_problem
    if problem:
        return make_change(
            previous, current,
            "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
            "HOLD",
            hold_reason=problem,
        )
    assert previous is not None and current is not None

    prev_start = parse_iso(previous["period_start"])
    prev_end = parse_iso(previous["period_end"])
    curr_start = parse_iso(current["period_start"])
    curr_end = parse_iso(current["period_end"])
    assert prev_start and prev_end and curr_start and curr_end
    delta_days = (curr_start - prev_start).days

    if delta_days < 0:
        return make_change(
            previous, current,
            "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
            "HOLD",
            hold_reason="BULLETIN_PERIOD_REGRESSION",
            delta_days=delta_days,
        )

    same_period = curr_start == prev_start and curr_end == prev_end
    same_upstream_id = clean(current["upstream_signal_id"]) == clean(previous["upstream_signal_id"])
    same_document_url = clean(current["document_url"]) == clean(previous["document_url"])
    same_document_hash = clean(current["document_sha256"]) == clean(previous["document_sha256"])
    same_text_hash = clean(current["document_text_sha256"]) == clean(previous["document_text_sha256"])

    if same_period:
        if not (same_upstream_id and same_document_url and same_document_hash and same_text_hash):
            return make_change(
                previous, current,
                "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
                "HOLD",
                hold_reason="SAME_PERIOD_REFERENCE_OR_CONTENT_DRIFT",
                delta_days=0,
            )
        if clean(previous["scope_state"]) != clean(current["scope_state"]) or tuple(previous.get("matched_anchors") or ()) != tuple(current.get("matched_anchors") or ()):
            return make_change(
                previous, current,
                "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
                "HOLD",
                hold_reason="SAME_DOCUMENT_SCOPE_CLASSIFICATION_DRIFT",
                delta_days=0,
            )
        return make_change(
            previous, current,
            "NO_NEW_CFR_BULLETIN_REFERENCE_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
            delta_days=0,
        )

    if curr_start <= prev_end:
        return make_change(
            previous, current,
            "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
            "HOLD",
            hold_reason="OVERLAPPING_OR_REVISED_BULLETIN_PERIOD",
            delta_days=delta_days,
        )
    if same_upstream_id or same_document_url:
        return make_change(
            previous, current,
            "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
            "HOLD",
            hold_reason="PERIOD_ADVANCED_WITHOUT_REFERENCE_IDENTITY_CHANGE",
            delta_days=delta_days,
        )

    if clean(current["scope_state"]) == "VALCEA_EXPLICIT_DOCUMENT_REFERENCE":
        return make_change(
            previous, current,
            "NEW_VALCEA_SCOPED_CFR_BULLETIN_REFERENCE_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
            delta_days=delta_days,
        )
    return make_change(
        previous, current,
        "NEW_REGIONAL_CFR_BULLETIN_REFERENCE_NO_VALCEA_MATCH_REVIEW_REQUIRED",
        "REVIEW_REQUIRED",
        delta_days=delta_days,
    )


def envelope(change: BulletinReferenceChange) -> dict[str, Any]:
    return {
        "status": "HOLD" if change.review_status == "HOLD" else "PASS",
        "source_id": SOURCE_ID,
        "taxonomy_version": TAXONOMY_VERSION,
        "source_name": SOURCE_NAME,
        "source_tier": SOURCE_TIER,
        "change": asdict(change),
        "safety": {
            "reference_change_detection_only": True,
            "operational_restriction_claim_allowed": False,
            "delay_or_timetable_claim_allowed": False,
            "train_specific_claim_allowed": False,
            "breaking_news_promotion_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        },
    }


def _fixture(
    *,
    signal_id: str,
    upstream_signal_id: str,
    period_start: str,
    period_end: str,
    document_url: str,
    scope_state: str = "REGIONAL_REFERENCE_ONLY",
    anchors: tuple[str, ...] = (),
    document_char: str = "a",
    text_char: str = "b",
) -> dict[str, Any]:
    review_status = (
        "SCOPE_CONFIRMED_REFERENCE_ONLY"
        if scope_state == "VALCEA_EXPLICIT_DOCUMENT_REFERENCE"
        else "REFERENCE_ONLY"
    )
    signal = {
        "signal_id": signal_id,
        "source_id": EXPECTED_SOURCE_ID,
        "taxonomy_version": EXPECTED_TAXONOMY_VERSION,
        "upstream_source_id": UPSTREAM_SOURCE_ID,
        "upstream_taxonomy_version": "2026-08-31.1",
        "upstream_signal_id": upstream_signal_id,
        "review_status": review_status,
        "scope_state": scope_state,
        "period_start": period_start,
        "period_end": period_end,
        "document_url": document_url,
        "document_sha256": document_char * 64,
        "document_text_sha256": text_char * 64,
        "matched_anchors": list(anchors),
        "line_201_mentioned": True,
        "hold_reason": None,
        "speed_restriction_details_extracted": False,
        "current_operational_status_inferred": False,
        "delay_or_timetable_impact_inferred": False,
        "train_specific_impact_inferred": False,
        "breaking_news_promotion_allowed": False,
        "inferred_photo_rights_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
    }
    return {
        "status": "PASS",
        "source_id": EXPECTED_SOURCE_ID,
        "taxonomy_version": EXPECTED_TAXONOMY_VERSION,
        "signal": signal,
        "safety": {
            "server_side_docx_fetch_allowed": True,
            "bounded_docx_body_parse_allowed": True,
            "scope_confirmation_only": True,
            "speed_restriction_details_extracted": False,
            "current_operational_status_inferred": False,
            "delay_or_timetable_impact_inferred": False,
            "train_specific_impact_inferred": False,
            "breaking_news_promotion_allowed": False,
            "inferred_photo_rights_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        },
    }


def run_self_test() -> None:
    previous = _fixture(
        signal_id="scope-old",
        upstream_signal_id="ref-old",
        period_start="2026-08-21",
        period_end="2026-08-31",
        document_url="https://cfr.ro/wp-content/uploads/2026/08/craiova-old.docx",
    )
    current = _fixture(
        signal_id="scope-new",
        upstream_signal_id="ref-new",
        period_start="2026-09-01",
        period_end="2026-09-10",
        document_url="https://cfr.ro/wp-content/uploads/2026/08/craiova-new.docx",
        scope_state="VALCEA_EXPLICIT_DOCUMENT_REFERENCE",
        anchors=("CALIMANESTI", "LOTRU"),
        document_char="c",
        text_char="d",
    )
    changed = detect(previous, current)
    assert changed.review_status == "REVIEW_REQUIRED"
    assert changed.change_class == "NEW_VALCEA_SCOPED_CFR_BULLETIN_REFERENCE_REVIEW_REQUIRED"
    assert changed.current_matched_anchors == ("CALIMANESTI", "LOTRU")
    assert changed.period_start_delta_days == 11
    assert changed.operational_restriction_claim_allowed is False
    assert changed.public_projection_allowed is False

    regional = _fixture(
        signal_id="scope-new-r",
        upstream_signal_id="ref-new-r",
        period_start="2026-09-01",
        period_end="2026-09-10",
        document_url="https://cfr.ro/wp-content/uploads/2026/08/craiova-new-r.docx",
        document_char="e",
        text_char="f",
    )
    no_match = detect(previous, regional)
    assert no_match.change_class == "NEW_REGIONAL_CFR_BULLETIN_REFERENCE_NO_VALCEA_MATCH_REVIEW_REQUIRED"

    same = detect(previous, previous)
    assert same.change_class == "NO_NEW_CFR_BULLETIN_REFERENCE_REVIEW_REQUIRED"

    drifted = json.loads(json.dumps(previous))
    drifted["signal"]["document_sha256"] = "9" * 64
    same_period_drift = detect(previous, drifted)
    assert same_period_drift.review_status == "HOLD"
    assert same_period_drift.hold_reason == "SAME_PERIOD_REFERENCE_OR_CONTENT_DRIFT"

    regressed = _fixture(
        signal_id="scope-regressed",
        upstream_signal_id="ref-regressed",
        period_start="2026-08-11",
        period_end="2026-08-20",
        document_url="https://cfr.ro/wp-content/uploads/2026/08/craiova-regressed.docx",
        document_char="1",
        text_char="2",
    )
    regression = detect(previous, regressed)
    assert regression.hold_reason == "BULLETIN_PERIOD_REGRESSION"

    overlap = _fixture(
        signal_id="scope-overlap",
        upstream_signal_id="ref-overlap",
        period_start="2026-08-30",
        period_end="2026-09-05",
        document_url="https://cfr.ro/wp-content/uploads/2026/08/craiova-overlap.docx",
        document_char="3",
        text_char="4",
    )
    overlap_result = detect(previous, overlap)
    assert overlap_result.hold_reason == "OVERLAPPING_OR_REVISED_BULLETIN_PERIOD"

    unsafe = json.loads(json.dumps(current))
    unsafe["safety"]["public_projection_allowed"] = True
    held = detect(previous, unsafe)
    assert held.review_status == "HOLD"
    assert held.hold_reason == "CURRENT_UNSAFE_BOUNDARY_PUBLIC_PROJECTION_ALLOWED"

    taxonomy_drift = json.loads(json.dumps(current))
    taxonomy_drift["taxonomy_version"] = "2026-08-30.9"
    held_taxonomy = detect(previous, taxonomy_drift)
    assert held_taxonomy.hold_reason == "CURRENT_UPSTREAM_TAXONOMY_DRIFT"

    inconsistent = json.loads(json.dumps(current))
    inconsistent["signal"]["matched_anchors"] = []
    held_scope = detect(previous, inconsistent)
    assert held_scope.hold_reason == "CURRENT_VALCEA_SCOPE_INCONSISTENT"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--previous-json", type=Path)
    parser.add_argument("--current-json", type=Path)
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        print(json.dumps({"status": "PASS", "self_test": True, "source_id": SOURCE_ID}, ensure_ascii=False))
        return 0

    if not args.previous_json or not args.current_json:
        change = make_change(
            None, None,
            "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
            "HOLD",
            hold_reason="PREVIOUS_AND_CURRENT_JSON_REQUIRED",
        )
        print(json.dumps(envelope(change), ensure_ascii=False, indent=2, sort_keys=True))
        return 2

    try:
        previous_payload = json.loads(args.previous_json.read_text(encoding="utf-8"))
        current_payload = json.loads(args.current_json.read_text(encoding="utf-8"))
        if not isinstance(previous_payload, dict) or not isinstance(current_payload, dict):
            raise ValueError("SNAPSHOT_SHAPE_INVALID")
        output = envelope(detect(previous_payload, current_payload))
    except Exception as exc:
        output = envelope(
            make_change(
                None, None,
                "HOLD_CFR_VALCEA_BULLETIN_REFERENCE_CHANGE",
                "HOLD",
                hold_reason=f"SNAPSHOT_READ_OR_PARSE_FAILURE:{type(exc).__name__}",
            )
        )

    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["status"] == "PASS" else 2


if __name__ == "__main__":
    sys.exit(main())
