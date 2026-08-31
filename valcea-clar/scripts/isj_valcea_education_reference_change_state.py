#!/usr/bin/env python3
"""Fail-closed change detection for dated ISJ Vâlcea education references.

Consumes two caller-declared complete snapshots of
isj_valcea_education_deadline_state.py outputs. It detects only newly observed,
explicitly dated education-process references that require newsroom review.

This module never infers that enrolment is open/closed, a deadline is active,
an exam is happening now, results are valid/current, or that a reference is
breaking news. No network access, document-body access, person extraction,
persistence, Fact Kernel promotion, Writer or public projection.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

SOURCE_ID = "signal-isj-valcea-education-notices"
SOURCE_TAXONOMY_VERSION = "2026-08-30.1"
UPSTREAM_STATE_VERSION = "2026-08-30.1"
STATE_VERSION = "2026-08-31.1"
SNAPSHOT_SCOPE = "ISJ_VALCEA_PROCESS_DATE_NORMALIZED_REFERENCES"
SNAPSHOT_STATE = "PROCESS_DATE_SNAPSHOT_READY"
UPSTREAM_ITEM_STATE = "PROCESS_DATE_NORMALIZED_REVIEW_REQUIRED"

ALLOWED_SIGNAL_CLASSES = {
    "PRESCHOOL_ENROLMENT_NOTICE",
    "SECONDARY_ADMISSION_NOTICE",
    "TEACHER_EXAM_NOTICE",
    "SCHOOL_MANAGEMENT_NOTICE",
    "MERIT_GRANT_NOTICE",
    "SCHOOL_CALENDAR_NOTICE",
    "SUMMER_PRESCHOOL_SERVICE_REFERENCE",
    "EDUCATION_DOCUMENT_REFERENCE",
}
ALLOWED_PROCESS_KINDS = {
    "APPLICATION_WINDOW",
    "CONTESTATION_WINDOW",
    "SERVICE_PERIOD",
    "APPLICATION_DEADLINE",
    "EXAM_DATE",
    "RESULT_PUBLICATION_DATE",
    "CONTESTATION_DEADLINE",
}
ALLOWED_DATE_SEMANTICS = {
    "EXPLICIT_VISIBLE_LABEL_PROCESS_DATE",
    "EXPLICIT_VISIBLE_LABEL_PROCESS_WINDOW",
}
FALSE_BOUNDARY_FLAGS = (
    "process_current_status_claim_allowed",
    "publication_date_as_process_date_allowed",
    "source_label_date_as_process_date_allowed",
    "document_body_fetch_allowed",
    "persistence_allowed",
    "fact_kernel_promotion_allowed",
    "writer_allowed",
    "public_projection_allowed",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class EducationReferenceChangeState:
    state_version: str
    source_id: str
    source_taxonomy_version: str
    upstream_state_version: str
    snapshot_scope: str
    state: str
    hold_reason: Optional[str]
    previous_as_of_date: Optional[str]
    current_as_of_date: Optional[str]
    previous_item_count: int
    current_item_count: int
    new_reference_count: int
    new_references: list[dict[str, Any]]
    review_required: bool
    current_status_claim_allowed: bool = False
    deadline_active_claim_allowed: bool = False
    exam_live_claim_allowed: bool = False
    result_validity_claim_allowed: bool = False
    breaking_news_promotion_allowed: bool = False
    person_fact_extraction_allowed: bool = False
    document_body_fetch_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def parse_iso_date(value: Any) -> Optional[dt.date]:
    text = clean(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        return None


def is_hex64(value: Any) -> bool:
    return bool(HEX64.fullmatch(clean(value)))


def _hold(
    reason: str,
    previous: Optional[dict[str, Any]] = None,
    current: Optional[dict[str, Any]] = None,
) -> EducationReferenceChangeState:
    previous_items = previous.get("items") if isinstance(previous, dict) else None
    current_items = current.get("items") if isinstance(current, dict) else None
    return EducationReferenceChangeState(
        state_version=STATE_VERSION,
        source_id=SOURCE_ID,
        source_taxonomy_version=SOURCE_TAXONOMY_VERSION,
        upstream_state_version=UPSTREAM_STATE_VERSION,
        snapshot_scope=SNAPSHOT_SCOPE,
        state="HOLD",
        hold_reason=reason,
        previous_as_of_date=clean(previous.get("as_of_date")) or None if isinstance(previous, dict) else None,
        current_as_of_date=clean(current.get("as_of_date")) or None if isinstance(current, dict) else None,
        previous_item_count=len(previous_items) if isinstance(previous_items, list) else 0,
        current_item_count=len(current_items) if isinstance(current_items, list) else 0,
        new_reference_count=0,
        new_references=[],
        review_required=True,
    )


def _validate_snapshot(snapshot: Any, label: str) -> Optional[str]:
    if not isinstance(snapshot, dict):
        return f"{label}_SNAPSHOT_NOT_OBJECT"
    expected = {
        "snapshot_scope": SNAPSHOT_SCOPE,
        "state": SNAPSHOT_STATE,
        "source_id": SOURCE_ID,
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "upstream_state_version": UPSTREAM_STATE_VERSION,
    }
    for field, value in expected.items():
        if clean(snapshot.get(field)) != value:
            return f"{label}_{field.upper()}_DRIFT"
    if snapshot.get("complete_snapshot") is not True:
        return f"{label}_SNAPSHOT_NOT_DECLARED_COMPLETE"
    as_of = parse_iso_date(snapshot.get("as_of_date"))
    if as_of is None:
        return f"{label}_INVALID_AS_OF_DATE"
    items = snapshot.get("items")
    if not isinstance(items, list):
        return f"{label}_ITEMS_NOT_ARRAY"
    if snapshot.get("normalized_item_count") != len(items):
        return f"{label}_ITEM_COUNT_MISMATCH"

    seen_stable: set[str] = set()
    for index, item in enumerate(items):
        error = _validate_item(item, as_of)
        if error:
            return f"{label}_ITEM_{index}_{error}"
        stable = _stable_key(item)
        if stable in seen_stable:
            return f"{label}_DUPLICATE_STABLE_REFERENCE"
        seen_stable.add(stable)
    return None


def _validate_item(item: Any, snapshot_as_of: dt.date) -> Optional[str]:
    if not isinstance(item, dict):
        return "NOT_OBJECT"
    if clean(item.get("state_version")) != UPSTREAM_STATE_VERSION:
        return "UPSTREAM_STATE_VERSION_DRIFT"
    if clean(item.get("source_id")) != SOURCE_ID:
        return "SOURCE_ID_DRIFT"
    if clean(item.get("source_taxonomy_version")) != SOURCE_TAXONOMY_VERSION:
        return "SOURCE_TAXONOMY_DRIFT"
    if clean(item.get("state")) != UPSTREAM_ITEM_STATE:
        return "UPSTREAM_ITEM_NOT_REVIEWABLE"
    if item.get("hold_reason") not in (None, ""):
        return "UPSTREAM_HOLD_REASON_PRESENT"
    if clean(item.get("source_signal_class")) not in ALLOWED_SIGNAL_CLASSES:
        return "UNSUPPORTED_SIGNAL_CLASS"
    if not is_hex64(item.get("source_payload_sha256")):
        return "INVALID_SOURCE_PAYLOAD_SHA256"
    document_hash = clean(item.get("source_document_url_sha256"))
    if document_hash and not is_hex64(document_hash):
        return "INVALID_DOCUMENT_URL_SHA256"
    if clean(item.get("process_kind")) not in ALLOWED_PROCESS_KINDS:
        return "UNSUPPORTED_PROCESS_KIND"
    if clean(item.get("date_semantics")) not in ALLOWED_DATE_SEMANTICS:
        return "UNSUPPORTED_DATE_SEMANTICS"
    if parse_iso_date(item.get("as_of_date")) != snapshot_as_of:
        return "ITEM_AS_OF_DATE_MISMATCH"

    for flag in FALSE_BOUNDARY_FLAGS:
        if item.get(flag) is not False:
            return f"UPSTREAM_BOUNDARY_DRIFT_{flag.upper()}"

    process_date = parse_iso_date(item.get("process_date"))
    start = parse_iso_date(item.get("window_start_date"))
    end = parse_iso_date(item.get("window_end_date"))
    if process_date and (start or end):
        return "POINT_AND_WINDOW_BOTH_PRESENT"
    if process_date is None and (start is None or end is None):
        return "MISSING_PROCESS_DATE_OR_COMPLETE_WINDOW"
    if start and end and end < start:
        return "WINDOW_END_BEFORE_START"

    for field in ("source_label_date", "publication_date"):
        raw = clean(item.get(field))
        if raw and parse_iso_date(raw) is None:
            return f"INVALID_{field.upper()}"
    publication = parse_iso_date(item.get("publication_date"))
    if publication and publication > snapshot_as_of:
        return "FUTURE_PUBLICATION_DATE"

    relation = clean(item.get("clock_relation"))
    if relation not in {"BEFORE_DATE", "ON_DATE", "AFTER_DATE"}:
        return "INVALID_CLOCK_RELATION"
    days = item.get("days_until_process_date")
    if not isinstance(days, int) or isinstance(days, bool):
        return "INVALID_DAYS_UNTIL_PROCESS_DATE"
    anchor = process_date or start
    assert anchor is not None
    expected_days = (anchor - snapshot_as_of).days
    expected_relation = "BEFORE_DATE" if expected_days > 0 else ("ON_DATE" if expected_days == 0 else "AFTER_DATE")
    if days != expected_days or relation != expected_relation:
        return "CLOCK_METADATA_MISMATCH"
    return None


def _stable_key(item: dict[str, Any]) -> str:
    document_hash = clean(item.get("source_document_url_sha256"))
    if document_hash:
        parts = (
            clean(item.get("source_signal_class")),
            "DOC",
            document_hash,
            clean(item.get("process_kind")),
        )
    else:
        parts = (
            clean(item.get("source_signal_class")),
            "PROCESS",
            clean(item.get("school_year")),
            clean(item.get("process_kind")),
            clean(item.get("process_date")),
            clean(item.get("window_start_date")),
            clean(item.get("window_end_date")),
        )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _content_fingerprint(item: dict[str, Any]) -> str:
    # Deliberately excludes source_payload_sha256, as that is the whole source-page
    # payload hash and may legitimately change when another notice is added.
    fields = (
        "source_signal_class",
        "source_document_url_sha256",
        "school_year",
        "process_kind",
        "process_date",
        "window_start_date",
        "window_end_date",
        "date_semantics",
        "source_label_date",
        "publication_date",
    )
    payload = {field: item.get(field) for field in fields}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _review_reference(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "reference_key": _stable_key(item),
        "source_signal_class": clean(item.get("source_signal_class")),
        "source_payload_sha256": clean(item.get("source_payload_sha256")),
        "source_document_url_sha256": clean(item.get("source_document_url_sha256")) or None,
        "school_year": clean(item.get("school_year")) or None,
        "process_kind": clean(item.get("process_kind")),
        "process_date": clean(item.get("process_date")) or None,
        "window_start_date": clean(item.get("window_start_date")) or None,
        "window_end_date": clean(item.get("window_end_date")) or None,
        "date_semantics": clean(item.get("date_semantics")),
        "source_label_date": clean(item.get("source_label_date")) or None,
        "publication_date": clean(item.get("publication_date")) or None,
        "review_reason": "NEW_EXPLICIT_PROCESS_REFERENCE",
        "current_status_claim_allowed": False,
        "deadline_active_claim_allowed": False,
        "exam_live_claim_allowed": False,
        "result_validity_claim_allowed": False,
        "breaking_news_promotion_allowed": False,
        "person_fact_extraction_allowed": False,
        "document_body_fetch_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
    }


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> EducationReferenceChangeState:
    for label, snapshot in (("PREVIOUS", previous), ("CURRENT", current)):
        error = _validate_snapshot(snapshot, label)
        if error:
            return _hold(error, previous, current)

    previous_date = parse_iso_date(previous.get("as_of_date"))
    current_date = parse_iso_date(current.get("as_of_date"))
    assert previous_date is not None and current_date is not None
    if current_date < previous_date:
        return _hold("SNAPSHOT_TIME_REGRESSION", previous, current)

    previous_items = {_stable_key(item): item for item in previous["items"]}
    current_items = {_stable_key(item): item for item in current["items"]}

    missing = sorted(set(previous_items) - set(current_items))
    if missing:
        return _hold("PREVIOUS_REFERENCE_DISAPPEARED_FROM_COMPLETE_SNAPSHOT", previous, current)

    for key in sorted(set(previous_items) & set(current_items)):
        if _content_fingerprint(previous_items[key]) != _content_fingerprint(current_items[key]):
            return _hold("STABLE_REFERENCE_CONTENT_DRIFT", previous, current)

    new_keys = sorted(set(current_items) - set(previous_items))
    new_refs = [_review_reference(current_items[key]) for key in new_keys]

    if new_refs:
        state = "NEW_PROCESS_REFERENCE_REVIEW_REQUIRED"
        review_required = True
    else:
        state = "NO_REFERENCE_CHANGE"
        review_required = False

    return EducationReferenceChangeState(
        state_version=STATE_VERSION,
        source_id=SOURCE_ID,
        source_taxonomy_version=SOURCE_TAXONOMY_VERSION,
        upstream_state_version=UPSTREAM_STATE_VERSION,
        snapshot_scope=SNAPSHOT_SCOPE,
        state=state,
        hold_reason=None,
        previous_as_of_date=previous_date.isoformat(),
        current_as_of_date=current_date.isoformat(),
        previous_item_count=len(previous_items),
        current_item_count=len(current_items),
        new_reference_count=len(new_refs),
        new_references=new_refs,
        review_required=review_required,
    )


def _item(
    *,
    payload: str = "a",
    document: Optional[str] = "b",
    signal_class: str = "PRESCHOOL_ENROLMENT_NOTICE",
    process_kind: str = "APPLICATION_DEADLINE",
    process_date: Optional[str] = "2026-09-10",
    window_start: Optional[str] = None,
    window_end: Optional[str] = None,
    as_of: str = "2026-08-30",
    publication_date: Optional[str] = "2026-08-29",
    school_year: Optional[str] = "2026-2027",
    source_label_date: Optional[str] = None,
    **overrides: Any,
) -> dict[str, Any]:
    anchor = parse_iso_date(process_date) or parse_iso_date(window_start)
    as_of_date = parse_iso_date(as_of)
    assert anchor is not None and as_of_date is not None
    days = (anchor - as_of_date).days
    item: dict[str, Any] = {
        "state_version": UPSTREAM_STATE_VERSION,
        "source_id": SOURCE_ID,
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "source_signal_class": signal_class,
        "source_payload_sha256": payload * 64,
        "source_document_url_sha256": document * 64 if document else None,
        "school_year": school_year,
        "state": UPSTREAM_ITEM_STATE,
        "hold_reason": None,
        "process_kind": process_kind,
        "process_date": process_date,
        "window_start_date": window_start,
        "window_end_date": window_end,
        "date_semantics": (
            "EXPLICIT_VISIBLE_LABEL_PROCESS_WINDOW"
            if window_start
            else "EXPLICIT_VISIBLE_LABEL_PROCESS_DATE"
        ),
        "source_label_date": source_label_date,
        "publication_date": publication_date,
        "as_of_date": as_of,
        "days_until_process_date": days,
        "clock_relation": "BEFORE_DATE" if days > 0 else ("ON_DATE" if days == 0 else "AFTER_DATE"),
        "process_current_status_claim_allowed": False,
        "publication_date_as_process_date_allowed": False,
        "source_label_date_as_process_date_allowed": False,
        "document_body_fetch_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
    }
    item.update(overrides)
    return item


def _snapshot(items: list[dict[str, Any]], as_of: str = "2026-08-30", **overrides: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "snapshot_scope": SNAPSHOT_SCOPE,
        "state": SNAPSHOT_STATE,
        "source_id": SOURCE_ID,
        "source_taxonomy_version": SOURCE_TAXONOMY_VERSION,
        "upstream_state_version": UPSTREAM_STATE_VERSION,
        "complete_snapshot": True,
        "as_of_date": as_of,
        "normalized_item_count": len(items),
        "items": items,
    }
    value.update(overrides)
    return value


def _assert_fail_closed(result: EducationReferenceChangeState) -> None:
    assert result.current_status_claim_allowed is False
    assert result.deadline_active_claim_allowed is False
    assert result.exam_live_claim_allowed is False
    assert result.result_validity_claim_allowed is False
    assert result.breaking_news_promotion_allowed is False
    assert result.person_fact_extraction_allowed is False
    assert result.document_body_fetch_allowed is False
    assert result.persistence_allowed is False
    assert result.fact_kernel_promotion_allowed is False
    assert result.writer_allowed is False
    assert result.public_projection_allowed is False
    for item in result.new_references:
        assert all(
            item[flag] is False
            for flag in (
                "current_status_claim_allowed",
                "deadline_active_claim_allowed",
                "exam_live_claim_allowed",
                "result_validity_claim_allowed",
                "breaking_news_promotion_allowed",
                "person_fact_extraction_allowed",
                "document_body_fetch_allowed",
                "persistence_allowed",
                "fact_kernel_promotion_allowed",
                "writer_allowed",
                "public_projection_allowed",
            )
        )


def self_test() -> None:
    old_item = _item()
    previous = _snapshot([old_item])

    same_later = _item(as_of="2026-08-31")
    unchanged = compare_snapshots(previous, _snapshot([same_later], as_of="2026-08-31"))
    assert unchanged.state == "NO_REFERENCE_CHANGE"
    assert unchanged.review_required is False
    _assert_fail_closed(unchanged)

    new_item = _item(
        payload="c",
        document="d",
        signal_class="TEACHER_EXAM_NOTICE",
        process_kind="EXAM_DATE",
        process_date="2027-07-14",
        as_of="2026-08-31",
        publication_date="2026-08-30",
    )
    created = compare_snapshots(previous, _snapshot([same_later, new_item], as_of="2026-08-31"))
    assert created.state == "NEW_PROCESS_REFERENCE_REVIEW_REQUIRED"
    assert created.new_reference_count == 1
    assert created.new_references[0]["source_signal_class"] == "TEACHER_EXAM_NOTICE"
    _assert_fail_closed(created)

    missing = compare_snapshots(previous, _snapshot([], as_of="2026-08-31"))
    assert missing.state == "HOLD"
    assert missing.hold_reason == "PREVIOUS_REFERENCE_DISAPPEARED_FROM_COMPLETE_SNAPSHOT"

    duplicate = _snapshot([same_later, dict(same_later)], as_of="2026-08-31")
    duplicate["normalized_item_count"] = 2
    duplicate_result = compare_snapshots(previous, duplicate)
    assert duplicate_result.state == "HOLD"
    assert duplicate_result.hold_reason == "CURRENT_DUPLICATE_STABLE_REFERENCE"

    held = _item(as_of="2026-08-31", state="HOLD", hold_reason="UPSTREAM")
    held_result = compare_snapshots(previous, _snapshot([held], as_of="2026-08-31"))
    assert held_result.state == "HOLD"
    assert "UPSTREAM_ITEM_NOT_REVIEWABLE" in clean(held_result.hold_reason)

    taxonomy = _snapshot([same_later], as_of="2026-08-31", source_taxonomy_version="2099-drift")
    taxonomy_result = compare_snapshots(previous, taxonomy)
    assert taxonomy_result.state == "HOLD"
    assert taxonomy_result.hold_reason == "CURRENT_SOURCE_TAXONOMY_VERSION_DRIFT"

    unsafe = _item(as_of="2026-08-31", public_projection_allowed=True)
    unsafe_result = compare_snapshots(previous, _snapshot([unsafe], as_of="2026-08-31"))
    assert unsafe_result.state == "HOLD"
    assert "UPSTREAM_BOUNDARY_DRIFT_PUBLIC_PROJECTION_ALLOWED" in clean(unsafe_result.hold_reason)

    time_regression_item = _item(as_of="2026-08-29")
    time_regression = compare_snapshots(previous, _snapshot([time_regression_item], as_of="2026-08-29"))
    assert time_regression.state == "HOLD"
    assert time_regression.hold_reason == "SNAPSHOT_TIME_REGRESSION"

    drift_item = _item(as_of="2026-08-31", publication_date="2026-08-28")
    drift = compare_snapshots(previous, _snapshot([drift_item], as_of="2026-08-31"))
    assert drift.state == "HOLD"
    assert drift.hold_reason == "STABLE_REFERENCE_CONTENT_DRIFT"

    incomplete = _snapshot([same_later], as_of="2026-08-31", complete_snapshot=False)
    incomplete_result = compare_snapshots(previous, incomplete)
    assert incomplete_result.state == "HOLD"
    assert incomplete_result.hold_reason == "CURRENT_SNAPSHOT_NOT_DECLARED_COMPLETE"

    unsupported = _item(as_of="2026-08-31", signal_class="PERSON_LEVEL_RESULT")
    unsupported_result = compare_snapshots(previous, _snapshot([unsupported], as_of="2026-08-31"))
    assert unsupported_result.state == "HOLD"
    assert "UNSUPPORTED_SIGNAL_CLASS" in clean(unsupported_result.hold_reason)

    window = _item(
        payload="e",
        document="f",
        process_kind="APPLICATION_WINDOW",
        process_date=None,
        window_start="2026-09-01",
        window_end="2026-09-05",
        as_of="2026-08-31",
    )
    window_created = compare_snapshots(
        previous,
        _snapshot([same_later, window], as_of="2026-08-31"),
    )
    assert window_created.state == "NEW_PROCESS_REFERENCE_REVIEW_REQUIRED"
    assert window_created.new_references[0]["window_end_date"] == "2026-09-05"
    _assert_fail_closed(window_created)

    print("ISJ education reference-change fail-closed self-test: PASS")


def load_snapshot(path: str) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("snapshot input must be a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", help="previous complete normalized-process snapshot JSON")
    parser.add_argument("--current", help="current complete normalized-process snapshot JSON")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.previous or not args.current:
        parser.error("--previous and --current are required outside --self-test")

    result = compare_snapshots(load_snapshot(args.previous), load_snapshot(args.current))
    print(json.dumps(asdict(result), ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
