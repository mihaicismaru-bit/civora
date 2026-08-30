#!/usr/bin/env python3
"""Fail-closed CAS Valcea provider-directory reference change detector.

Consumes two snapshots produced by cas_valcea_provider_directory_recency_state.py
and reports only whether the newest explicitly dated CAS document reference has
advanced between snapshots.

A detected change is a reference-metadata event, not evidence that provider
membership, contract status, opening hours, appointments, availability, or
patient acceptance changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

EXPECTED_RECENCY_TAXONOMY = "2026-08-30.1"
TAXONOMY_VERSION = "2026-08-30.1"
ALLOWED_SCOPES = ("PRIMARY_CARE", "PHARMACY")
ALLOWED_RECENCY_CLASSES = {
    "NO_REFERENCE_IN_INPUT_REVIEW_REQUIRED",
    "ONLY_UNDATED_REFERENCES_REVIEW_REQUIRED",
    "LATEST_DATED_REFERENCE_IDENTIFIED_REVIEW_REQUIRED",
    "HOLD_PROVIDER_DIRECTORY_RECENCY",
}
FORBIDDEN_TRUE_FLAGS = {
    "provider_identity_extraction_allowed",
    "current_contract_status_claim_allowed",
    "current_opening_status_claim_allowed",
    "appointment_availability_claim_allowed",
    "accepting_patients_claim_allowed",
    "persistence_allowed",
    "fact_kernel_promotion_allowed",
    "writer_allowed",
    "public_projection_allowed",
}


@dataclass(frozen=True)
class ProviderDirectoryReferenceChange:
    change_id: str
    taxonomy_version: str
    directory_scope: str
    change_class: str
    review_status: str
    previous_as_of_date: Optional[str]
    current_as_of_date: Optional[str]
    previous_latest_source_signal_id: Optional[str]
    current_latest_source_signal_id: Optional[str]
    previous_latest_document_date: Optional[str]
    current_latest_document_date: Optional[str]
    document_date_delta_days: Optional[int]
    basis: str
    previous_state_id: Optional[str]
    current_state_id: Optional[str]
    previous_aggregate_sha256: Optional[str]
    current_aggregate_sha256: Optional[str]
    change_sha256: str
    hold_reason: Optional[str]
    document_body_parse_allowed: bool = False
    provider_identity_extraction_allowed: bool = False
    provider_person_extraction_allowed: bool = False
    current_contract_status_claim_allowed: bool = False
    current_opening_status_claim_allowed: bool = False
    appointment_availability_claim_allowed: bool = False
    accepting_patients_claim_allowed: bool = False
    persistence_allowed: bool = False
    fact_kernel_promotion_allowed: bool = False
    writer_allowed: bool = False
    public_projection_allowed: bool = False


def clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def digest(*parts: Any) -> str:
    payload = "\0".join(clean(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)


def parse_iso_date(value: Any) -> Optional[date]:
    text = clean(value)
    if not text:
        return None
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.isoformat() == text else None


def optional_text(value: Any) -> Optional[str]:
    text = clean(value)
    return text or None


def make_change(
    scope: str,
    previous: Optional[dict[str, Any]],
    current: Optional[dict[str, Any]],
    change_class: str,
    review_status: str,
    hold_reason: Optional[str] = None,
    delta_days: Optional[int] = None,
) -> ProviderDirectoryReferenceChange:
    prev_state_id = optional_text((previous or {}).get("state_id"))
    curr_state_id = optional_text((current or {}).get("state_id"))
    prev_hash = optional_text((previous or {}).get("aggregate_sha256"))
    curr_hash = optional_text((current or {}).get("aggregate_sha256"))
    prev_as_of = optional_text((previous or {}).get("as_of_date"))
    curr_as_of = optional_text((current or {}).get("as_of_date"))
    prev_signal = optional_text((previous or {}).get("latest_source_signal_id"))
    curr_signal = optional_text((current or {}).get("latest_source_signal_id"))
    prev_date = optional_text((previous or {}).get("latest_document_date"))
    curr_date = optional_text((current or {}).get("latest_document_date"))

    change_hash = digest(
        scope,
        change_class,
        review_status,
        hold_reason or "",
        prev_state_id or "",
        curr_state_id or "",
        prev_hash or "",
        curr_hash or "",
        prev_as_of or "",
        curr_as_of or "",
        prev_signal or "",
        curr_signal or "",
        prev_date or "",
        curr_date or "",
        "" if delta_days is None else delta_days,
    )
    return ProviderDirectoryReferenceChange(
        change_id=f"casvl-dirchange-{change_hash[:20]}",
        taxonomy_version=TAXONOMY_VERSION,
        directory_scope=scope,
        change_class=change_class,
        review_status=review_status,
        previous_as_of_date=prev_as_of,
        current_as_of_date=curr_as_of,
        previous_latest_source_signal_id=prev_signal,
        current_latest_source_signal_id=curr_signal,
        previous_latest_document_date=prev_date,
        current_latest_document_date=curr_date,
        document_date_delta_days=delta_days,
        basis="EXPLICIT_CAS_DOCUMENT_REFERENCE_METADATA_ONLY_NOT_PROVIDER_OR_OPERATIONAL_CHANGE",
        previous_state_id=prev_state_id,
        current_state_id=curr_state_id,
        previous_aggregate_sha256=prev_hash,
        current_aggregate_sha256=curr_hash,
        change_sha256=change_hash,
        hold_reason=hold_reason,
    )


def validate_snapshot(states: list[dict[str, Any]], label: str) -> Optional[str]:
    if len(states) != len(ALLOWED_SCOPES):
        return f"{label}_SNAPSHOT_SCOPE_COUNT_INVALID"
    seen: set[str] = set()
    for item in states:
        scope = clean(item.get("directory_scope"))
        if scope not in ALLOWED_SCOPES:
            return f"{label}_SNAPSHOT_UNSUPPORTED_SCOPE"
        if scope in seen:
            return f"{label}_SNAPSHOT_DUPLICATE_SCOPE"
        seen.add(scope)
        if clean(item.get("taxonomy_version")) != EXPECTED_RECENCY_TAXONOMY:
            return f"{label}_RECENCY_TAXONOMY_DRIFT"
        if clean(item.get("state_class")) not in ALLOWED_RECENCY_CLASSES:
            return f"{label}_UNEXPECTED_RECENCY_CLASS"
        if not clean(item.get("state_id")):
            return f"{label}_MISSING_STATE_ID"
        if not valid_sha256(clean(item.get("aggregate_sha256"))):
            return f"{label}_INVALID_AGGREGATE_SHA256"
        if parse_iso_date(item.get("as_of_date")) is None:
            return f"{label}_INVALID_AS_OF_DATE"
        for flag in FORBIDDEN_TRUE_FLAGS:
            if item.get(flag) is True:
                return f"{label}_UNSAFE_BOUNDARY_{flag.upper()}"

        state_class = clean(item.get("state_class"))
        review_status = clean(item.get("review_status"))
        latest_id = clean(item.get("latest_source_signal_id"))
        latest_date = clean(item.get("latest_document_date"))
        if state_class == "HOLD_PROVIDER_DIRECTORY_RECENCY" or review_status == "HOLD":
            return f"{label}_UPSTREAM_RECENCY_HELD"
        if review_status != "REVIEW_REQUIRED":
            return f"{label}_UNEXPECTED_REVIEW_STATUS"

        if state_class == "LATEST_DATED_REFERENCE_IDENTIFIED_REVIEW_REQUIRED":
            if not latest_id or parse_iso_date(latest_date) is None:
                return f"{label}_LATEST_REFERENCE_METADATA_INVALID"
        elif latest_id or latest_date:
            return f"{label}_NONLATEST_STATE_CARRIES_LATEST_REFERENCE"
    if seen != set(ALLOWED_SCOPES):
        return f"{label}_SNAPSHOT_SCOPE_SET_INVALID"
    return None


def detect_scope(
    previous: dict[str, Any],
    current: dict[str, Any],
    scope: str,
) -> ProviderDirectoryReferenceChange:
    previous_as_of = parse_iso_date(previous.get("as_of_date"))
    current_as_of = parse_iso_date(current.get("as_of_date"))
    assert previous_as_of is not None and current_as_of is not None
    if current_as_of < previous_as_of:
        return make_change(
            scope, previous, current,
            "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
            "HOLD",
            "SNAPSHOT_TIME_REGRESSION",
        )

    previous_date = parse_iso_date(previous.get("latest_document_date"))
    current_date = parse_iso_date(current.get("latest_document_date"))
    previous_id = clean(previous.get("latest_source_signal_id"))
    current_id = clean(current.get("latest_source_signal_id"))

    if previous_date is None and current_date is None:
        return make_change(
            scope, previous, current,
            "NO_DATED_REFERENCE_TO_COMPARE_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
        )

    if previous_date is None and current_date is not None:
        return make_change(
            scope, previous, current,
            "INITIAL_DATED_REFERENCE_OBSERVED_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
        )

    if previous_date is not None and current_date is None:
        return make_change(
            scope, previous, current,
            "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
            "HOLD",
            "LATEST_DATED_REFERENCE_DISAPPEARED",
        )

    assert previous_date is not None and current_date is not None
    delta_days = (current_date - previous_date).days
    if delta_days < 0:
        return make_change(
            scope, previous, current,
            "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
            "HOLD",
            "LATEST_DOCUMENT_DATE_REGRESSION",
            delta_days,
        )

    if delta_days == 0:
        if current_id != previous_id:
            return make_change(
                scope, previous, current,
                "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
                "HOLD",
                "SAME_DATE_REFERENCE_IDENTITY_DRIFT",
                0,
            )
        return make_change(
            scope, previous, current,
            "NO_NEW_DATED_REFERENCE_REVIEW_REQUIRED",
            "REVIEW_REQUIRED",
            delta_days=0,
        )

    if current_id == previous_id:
        return make_change(
            scope, previous, current,
            "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
            "HOLD",
            "DOCUMENT_DATE_ADVANCED_WITHOUT_REFERENCE_IDENTITY_CHANGE",
            delta_days,
        )

    return make_change(
        scope, previous, current,
        "NEW_DATED_REFERENCE_DETECTED_REVIEW_REQUIRED",
        "REVIEW_REQUIRED",
        delta_days=delta_days,
    )


def detect(
    previous_states: list[dict[str, Any]],
    current_states: list[dict[str, Any]],
) -> list[ProviderDirectoryReferenceChange]:
    previous_problem = validate_snapshot(previous_states, "PREVIOUS")
    current_problem = validate_snapshot(current_states, "CURRENT")
    problem = previous_problem or current_problem
    if problem:
        previous_by_scope = {clean(item.get("directory_scope")): item for item in previous_states}
        current_by_scope = {clean(item.get("directory_scope")): item for item in current_states}
        return [
            make_change(
                scope,
                previous_by_scope.get(scope),
                current_by_scope.get(scope),
                "HOLD_PROVIDER_DIRECTORY_REFERENCE_CHANGE",
                "HOLD",
                problem,
            )
            for scope in ALLOWED_SCOPES
        ]

    previous_by_scope = {clean(item["directory_scope"]): item for item in previous_states}
    current_by_scope = {clean(item["directory_scope"]): item for item in current_states}
    return [
        detect_scope(previous_by_scope[scope], current_by_scope[scope], scope)
        for scope in ALLOWED_SCOPES
    ]


def self_test() -> None:
    def recency(
        scope: str,
        *,
        state_id: str,
        as_of: str,
        latest_id: Optional[str] = None,
        latest_date: Optional[str] = None,
        state_class: Optional[str] = None,
        review_status: str = "REVIEW_REQUIRED",
        aggregate_char: str = "a",
    ) -> dict[str, Any]:
        if state_class is None:
            state_class = (
                "LATEST_DATED_REFERENCE_IDENTIFIED_REVIEW_REQUIRED"
                if latest_date
                else "ONLY_UNDATED_REFERENCES_REVIEW_REQUIRED"
            )
        return {
            "state_id": state_id,
            "taxonomy_version": EXPECTED_RECENCY_TAXONOMY,
            "directory_scope": scope,
            "state_class": state_class,
            "review_status": review_status,
            "as_of_date": as_of,
            "latest_source_signal_id": latest_id,
            "latest_document_date": latest_date,
            "aggregate_sha256": aggregate_char * 64,
            "provider_identity_extraction_allowed": False,
            "current_contract_status_claim_allowed": False,
            "current_opening_status_claim_allowed": False,
            "appointment_availability_claim_allowed": False,
            "accepting_patients_claim_allowed": False,
            "persistence_allowed": False,
            "fact_kernel_promotion_allowed": False,
            "writer_allowed": False,
            "public_projection_allowed": False,
        }

    previous = [
        recency("PRIMARY_CARE", state_id="p1", as_of="2026-08-29", latest_id="pc-old", latest_date="2026-08-01"),
        recency("PHARMACY", state_id="p2", as_of="2026-08-29", latest_id="ph-old", latest_date="2026-08-05", aggregate_char="b"),
    ]
    current = [
        recency("PRIMARY_CARE", state_id="c1", as_of="2026-08-30", latest_id="pc-new", latest_date="2026-08-20", aggregate_char="c"),
        recency("PHARMACY", state_id="c2", as_of="2026-08-30", latest_id="ph-old", latest_date="2026-08-05", aggregate_char="d"),
    ]
    result = detect(previous, current)
    assert result[0].change_class == "NEW_DATED_REFERENCE_DETECTED_REVIEW_REQUIRED"
    assert result[0].document_date_delta_days == 19
    assert result[1].change_class == "NO_NEW_DATED_REFERENCE_REVIEW_REQUIRED"

    initial_previous = [
        recency("PRIMARY_CARE", state_id="ip1", as_of="2026-08-29", aggregate_char="e"),
        previous[1],
    ]
    initial = detect(initial_previous, current)
    assert initial[0].change_class == "INITIAL_DATED_REFERENCE_OBSERVED_REVIEW_REQUIRED"

    disappeared_current = [
        recency("PRIMARY_CARE", state_id="dc1", as_of="2026-08-30", aggregate_char="f"),
        current[1],
    ]
    disappeared = detect(previous, disappeared_current)
    assert disappeared[0].review_status == "HOLD"
    assert disappeared[0].hold_reason == "LATEST_DATED_REFERENCE_DISAPPEARED"

    same_date_drift = [
        recency("PRIMARY_CARE", state_id="sd1", as_of="2026-08-30", latest_id="pc-other", latest_date="2026-08-01", aggregate_char="1"),
        current[1],
    ]
    drift = detect(previous, same_date_drift)
    assert drift[0].hold_reason == "SAME_DATE_REFERENCE_IDENTITY_DRIFT"

    regressed = [
        recency("PRIMARY_CARE", state_id="rg1", as_of="2026-08-30", latest_id="pc-older", latest_date="2026-07-01", aggregate_char="2"),
        current[1],
    ]
    regression = detect(previous, regressed)
    assert regression[0].hold_reason == "LATEST_DOCUMENT_DATE_REGRESSION"

    unsafe_current = [dict(current[0]), dict(current[1])]
    unsafe_current[0]["writer_allowed"] = True
    held = detect(previous, unsafe_current)
    assert all(item.review_status == "HOLD" for item in held)
    assert all(item.hold_reason == "CURRENT_UNSAFE_BOUNDARY_WRITER_ALLOWED" for item in held)

    missing_scope = detect(previous, [current[0]])
    assert all(item.review_status == "HOLD" for item in missing_scope)
    assert all(item.hold_reason == "CURRENT_SNAPSHOT_SCOPE_COUNT_INVALID" for item in missing_scope)

    time_regression_current = [
        recency("PRIMARY_CARE", state_id="tr1", as_of="2026-08-28", latest_id="pc-old", latest_date="2026-08-01", aggregate_char="3"),
        recency("PHARMACY", state_id="tr2", as_of="2026-08-28", latest_id="ph-old", latest_date="2026-08-05", aggregate_char="4"),
    ]
    time_regression = detect(previous, time_regression_current)
    assert all(item.hold_reason == "SNAPSHOT_TIME_REGRESSION" for item in time_regression)

    advanced_same_id = [
        recency("PRIMARY_CARE", state_id="as1", as_of="2026-08-30", latest_id="pc-old", latest_date="2026-08-20", aggregate_char="5"),
        current[1],
    ]
    same_id = detect(previous, advanced_same_id)
    assert same_id[0].hold_reason == "DOCUMENT_DATE_ADVANCED_WITHOUT_REFERENCE_IDENTITY_CHANGE"


def load_json_list(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path} must contain a JSON array of objects")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        print("CAS provider-directory reference change self-test: PASS")
        return 0

    if args.previous is None or args.current is None:
        parser.error("--previous and --current are required unless --self-test is used")

    result = detect(load_json_list(args.previous), load_json_list(args.current))
    payload = json.dumps([asdict(item) for item in result], ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
