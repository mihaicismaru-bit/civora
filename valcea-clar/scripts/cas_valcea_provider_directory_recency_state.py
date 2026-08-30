#!/usr/bin/env python3
"""Fail-closed CAS Valcea provider-directory recency aggregation.

Consumes the metadata-only output of cas_valcea_provider_document_metadata_state.py
and emits one bounded editorial recency summary per supported directory scope.

"Recency" here means only age of an explicit date printed in the CAS document
reference. It never means a provider is currently contracted, open, available,
accepting patients, or that the referenced directory is operationally complete.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Optional

EXPECTED_SOURCE_ID = "signal-cas-valcea-service-access"
EXPECTED_METADATA_TAXONOMY = "2026-08-30.1"
TAXONOMY_VERSION = "2026-08-30.1"
ALLOWED_SCOPES = ("PRIMARY_CARE", "PHARMACY")
ALLOWED_METADATA_CLASSES = {
    "DATED_PROVIDER_DOCUMENT_REFERENCE",
    "UNDATED_PROVIDER_DOCUMENT_REFERENCE",
    "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE",
    "HOLD_PROVIDER_DOCUMENT_METADATA",
}

FORBIDDEN_TRUE_FLAGS = {
    "document_body_parse_allowed",
    "provider_identity_extraction_allowed",
    "provider_person_extraction_allowed",
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
class ProviderDirectoryRecencyState:
    state_id: str
    taxonomy_version: str
    directory_scope: str
    state_class: str
    review_status: str
    as_of_date: str
    input_state_count: int
    dated_reference_count: int
    undated_reference_count: int
    superseded_reference_count: int
    latest_source_signal_id: Optional[str]
    latest_document_date: Optional[str]
    latest_document_age_days: Optional[int]
    recency_band: str
    basis: str
    source_state_ids: tuple[str, ...]
    source_metadata_sha256s: tuple[str, ...]
    aggregate_sha256: str
    hold_reason: Optional[str]
    provider_identity_extraction_allowed: bool = False
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
    if parsed.isoformat() != text:
        return None
    return parsed


def state_id(scope: str, as_of_date: str, aggregate_hash: str) -> str:
    return f"casvl-dirrecency-{digest(scope, as_of_date, aggregate_hash)[:20]}"


def hold(
    scope: str,
    as_of: date,
    states: list[dict[str, Any]],
    reason: str,
) -> ProviderDirectoryRecencyState:
    state_ids = tuple(sorted(clean(item.get("state_id")) for item in states if clean(item.get("state_id"))))
    hashes = tuple(
        sorted(
            clean(item.get("metadata_sha256")).lower()
            for item in states
            if valid_sha256(clean(item.get("metadata_sha256")))
        )
    )
    aggregate_hash = digest(scope, as_of.isoformat(), reason, *state_ids, *hashes)
    return ProviderDirectoryRecencyState(
        state_id=state_id(scope, as_of.isoformat(), aggregate_hash),
        taxonomy_version=TAXONOMY_VERSION,
        directory_scope=scope,
        state_class="HOLD_PROVIDER_DIRECTORY_RECENCY",
        review_status="HOLD",
        as_of_date=as_of.isoformat(),
        input_state_count=len(states),
        dated_reference_count=0,
        undated_reference_count=0,
        superseded_reference_count=0,
        latest_source_signal_id=None,
        latest_document_date=None,
        latest_document_age_days=None,
        recency_band="UNKNOWN",
        basis="EXPLICIT_DOCUMENT_DATE_ONLY",
        source_state_ids=state_ids,
        source_metadata_sha256s=hashes,
        aggregate_sha256=aggregate_hash,
        hold_reason=reason,
    )


def validate_metadata_state(item: dict[str, Any], scope: str) -> Optional[str]:
    if clean(item.get("taxonomy_version")) != EXPECTED_METADATA_TAXONOMY:
        return "METADATA_TAXONOMY_DRIFT"
    if clean(item.get("source_id")) != EXPECTED_SOURCE_ID:
        return "UNEXPECTED_SOURCE"
    if clean(item.get("directory_scope")) != scope:
        return "SCOPE_MISMATCH"
    state_class = clean(item.get("state_class"))
    if state_class not in ALLOWED_METADATA_CLASSES:
        return "UNEXPECTED_METADATA_CLASS"
    if not clean(item.get("state_id")):
        return "MISSING_STATE_ID"
    if not clean(item.get("source_signal_id")):
        return "MISSING_SOURCE_SIGNAL_ID"
    metadata_hash = clean(item.get("metadata_sha256"))
    if not valid_sha256(metadata_hash):
        return "INVALID_METADATA_SHA256"
    for flag in FORBIDDEN_TRUE_FLAGS:
        if item.get(flag) is True:
            return f"UNSAFE_UPSTREAM_BOUNDARY_{flag.upper()}"
    if state_class == "HOLD_PROVIDER_DOCUMENT_METADATA" or clean(item.get("review_status")) == "HOLD":
        return "UPSTREAM_METADATA_HELD"
    if clean(item.get("review_status")) != "REVIEW_REQUIRED":
        return "UNEXPECTED_REVIEW_STATUS"

    document_date = clean(item.get("document_date"))
    if state_class in {"DATED_PROVIDER_DOCUMENT_REFERENCE", "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE"}:
        if parse_iso_date(document_date) is None:
            return "INVALID_EXPLICIT_DOCUMENT_DATE"
    elif document_date:
        return "UNDATED_REFERENCE_HAS_DOCUMENT_DATE"

    superseded_by = clean(item.get("superseded_by_source_signal_id"))
    if state_class == "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE":
        if not superseded_by:
            return "SUPERSEDED_REFERENCE_MISSING_SUCCESSOR"
    elif superseded_by:
        return "ACTIVE_REFERENCE_HAS_SUCCESSOR"
    return None


def recency_band(age_days: int) -> str:
    if age_days <= 30:
        return "DATED_0_30_DAYS"
    if age_days <= 90:
        return "DATED_31_90_DAYS"
    if age_days <= 180:
        return "DATED_91_180_DAYS"
    return "DATED_OVER_180_DAYS"


def aggregate_scope(
    all_states: list[dict[str, Any]],
    scope: str,
    as_of: date,
) -> ProviderDirectoryRecencyState:
    scoped = [item for item in all_states if clean(item.get("directory_scope")) == scope]
    if not scoped:
        aggregate_hash = digest(scope, as_of.isoformat(), "NO_REFERENCE_IN_INPUT")
        return ProviderDirectoryRecencyState(
            state_id=state_id(scope, as_of.isoformat(), aggregate_hash),
            taxonomy_version=TAXONOMY_VERSION,
            directory_scope=scope,
            state_class="NO_REFERENCE_IN_INPUT_REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            as_of_date=as_of.isoformat(),
            input_state_count=0,
            dated_reference_count=0,
            undated_reference_count=0,
            superseded_reference_count=0,
            latest_source_signal_id=None,
            latest_document_date=None,
            latest_document_age_days=None,
            recency_band="UNKNOWN",
            basis="NO_REFERENCE_IN_INPUT_NOT_SOURCE_ABSENCE",
            source_state_ids=(),
            source_metadata_sha256s=(),
            aggregate_sha256=aggregate_hash,
            hold_reason=None,
        )

    duplicate_state_ids = [
        value for value in {clean(item.get("state_id")) for item in scoped}
        if value and sum(clean(item.get("state_id")) == value for item in scoped) > 1
    ]
    if duplicate_state_ids:
        return hold(scope, as_of, scoped, "DUPLICATE_STATE_ID")

    duplicate_signal_ids = [
        value for value in {clean(item.get("source_signal_id")) for item in scoped}
        if value and sum(clean(item.get("source_signal_id")) == value for item in scoped) > 1
    ]
    if duplicate_signal_ids:
        return hold(scope, as_of, scoped, "DUPLICATE_SOURCE_SIGNAL_ID")

    for item in scoped:
        problem = validate_metadata_state(item, scope)
        if problem:
            return hold(scope, as_of, scoped, problem)

    by_signal = {clean(item["source_signal_id"]): item for item in scoped}
    dated = [
        item for item in scoped
        if clean(item.get("state_class")) in {
            "DATED_PROVIDER_DOCUMENT_REFERENCE",
            "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE",
        }
    ]
    active_dated = [
        item for item in dated
        if clean(item.get("state_class")) == "DATED_PROVIDER_DOCUMENT_REFERENCE"
    ]
    undated = [
        item for item in scoped
        if clean(item.get("state_class")) == "UNDATED_PROVIDER_DOCUMENT_REFERENCE"
    ]
    superseded = [
        item for item in scoped
        if clean(item.get("state_class")) == "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE"
    ]

    for item in dated:
        parsed = parse_iso_date(item.get("document_date"))
        assert parsed is not None
        if parsed > as_of:
            return hold(scope, as_of, scoped, "FUTURE_DOCUMENT_DATE")

    for item in superseded:
        successor_id = clean(item.get("superseded_by_source_signal_id"))
        successor = by_signal.get(successor_id)
        if successor is None:
            return hold(scope, as_of, scoped, "SUPERSESSION_SUCCESSOR_NOT_IN_INPUT")
        if clean(successor.get("state_class")) != "DATED_PROVIDER_DOCUMENT_REFERENCE":
            return hold(scope, as_of, scoped, "SUPERSESSION_SUCCESSOR_NOT_ACTIVE_DATED_REFERENCE")
        old_date = parse_iso_date(item.get("document_date"))
        successor_date = parse_iso_date(successor.get("document_date"))
        assert old_date is not None and successor_date is not None
        if successor_date <= old_date:
            return hold(scope, as_of, scoped, "INVALID_SUPERSESSION_ORDER")

    if not dated:
        state_ids = tuple(sorted(clean(item["state_id"]) for item in scoped))
        hashes = tuple(sorted(clean(item["metadata_sha256"]).lower() for item in scoped))
        aggregate_hash = digest(scope, as_of.isoformat(), "ONLY_UNDATED", *state_ids, *hashes)
        return ProviderDirectoryRecencyState(
            state_id=state_id(scope, as_of.isoformat(), aggregate_hash),
            taxonomy_version=TAXONOMY_VERSION,
            directory_scope=scope,
            state_class="ONLY_UNDATED_REFERENCES_REVIEW_REQUIRED",
            review_status="REVIEW_REQUIRED",
            as_of_date=as_of.isoformat(),
            input_state_count=len(scoped),
            dated_reference_count=0,
            undated_reference_count=len(undated),
            superseded_reference_count=0,
            latest_source_signal_id=None,
            latest_document_date=None,
            latest_document_age_days=None,
            recency_band="UNKNOWN",
            basis="NO_EXPLICIT_DOCUMENT_DATE",
            source_state_ids=state_ids,
            source_metadata_sha256s=hashes,
            aggregate_sha256=aggregate_hash,
            hold_reason=None,
        )

    max_date = max(parse_iso_date(item["document_date"]) for item in dated)
    assert max_date is not None
    max_active = [
        item for item in active_dated if parse_iso_date(item["document_date"]) == max_date
    ]
    if len(max_active) != 1:
        return hold(scope, as_of, scoped, "AMBIGUOUS_LATEST_DOCUMENT_DATE")

    latest = max_active[0]
    for item in active_dated:
        item_date = parse_iso_date(item["document_date"])
        assert item_date is not None
        if item is not latest and item_date < max_date:
            return hold(scope, as_of, scoped, "OLDER_DATED_REFERENCE_NOT_MARKED_SUPERSEDED")

    age_days = (as_of - max_date).days
    state_ids = tuple(sorted(clean(item["state_id"]) for item in scoped))
    hashes = tuple(sorted(clean(item["metadata_sha256"]).lower() for item in scoped))
    aggregate_hash = digest(
        scope,
        as_of.isoformat(),
        clean(latest["source_signal_id"]),
        max_date.isoformat(),
        age_days,
        *state_ids,
        *hashes,
    )
    return ProviderDirectoryRecencyState(
        state_id=state_id(scope, as_of.isoformat(), aggregate_hash),
        taxonomy_version=TAXONOMY_VERSION,
        directory_scope=scope,
        state_class="LATEST_DATED_REFERENCE_IDENTIFIED_REVIEW_REQUIRED",
        review_status="REVIEW_REQUIRED",
        as_of_date=as_of.isoformat(),
        input_state_count=len(scoped),
        dated_reference_count=len(dated),
        undated_reference_count=len(undated),
        superseded_reference_count=len(superseded),
        latest_source_signal_id=clean(latest["source_signal_id"]),
        latest_document_date=max_date.isoformat(),
        latest_document_age_days=age_days,
        recency_band=recency_band(age_days),
        basis="EXPLICIT_DOCUMENT_DATE_ONLY_NOT_OPERATIONAL_STATUS",
        source_state_ids=state_ids,
        source_metadata_sha256s=hashes,
        aggregate_sha256=aggregate_hash,
        hold_reason=None,
    )


def aggregate(
    states: list[dict[str, Any]],
    as_of: date,
) -> list[ProviderDirectoryRecencyState]:
    unknown_scopes = sorted(
        {
            clean(item.get("directory_scope"))
            for item in states
            if clean(item.get("directory_scope")) not in ALLOWED_SCOPES
        }
    )
    if unknown_scopes:
        return [
            hold(scope, as_of, states, "UNSUPPORTED_SCOPE_IN_INPUT")
            for scope in ALLOWED_SCOPES
        ]
    return [aggregate_scope(states, scope, as_of) for scope in ALLOWED_SCOPES]


def self_test() -> None:
    base = {
        "taxonomy_version": EXPECTED_METADATA_TAXONOMY,
        "review_status": "REVIEW_REQUIRED",
        "source_id": EXPECTED_SOURCE_ID,
        "source_taxonomy_version": "2026-08-30.1",
        "index_url": "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "payload_sha256": "a" * 64,
        "index_date": "2026-08-30",
        "hold_reason": None,
        "document_body_parse_allowed": False,
        "provider_identity_extraction_allowed": False,
        "provider_person_extraction_allowed": False,
        "current_contract_status_claim_allowed": False,
        "current_opening_status_claim_allowed": False,
        "appointment_availability_claim_allowed": False,
        "accepting_patients_claim_allowed": False,
        "persistence_allowed": False,
        "fact_kernel_promotion_allowed": False,
        "writer_allowed": False,
        "public_projection_allowed": False,
    }
    old = {
        **base,
        "state_id": "state-old",
        "state_class": "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE",
        "source_signal_id": "primary-old",
        "directory_scope": "PRIMARY_CARE",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/07/medicina-primara.xlsx",
        "document_date": "2026-07-31",
        "metadata_sha256": "b" * 64,
        "superseded_by_source_signal_id": "primary-new",
    }
    new = {
        **base,
        "state_id": "state-new",
        "state_class": "DATED_PROVIDER_DOCUMENT_REFERENCE",
        "source_signal_id": "primary-new",
        "directory_scope": "PRIMARY_CARE",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/medicina-primara.xlsx",
        "document_date": "2026-08-30",
        "metadata_sha256": "c" * 64,
        "superseded_by_source_signal_id": None,
    }
    pharmacy = {
        **base,
        "state_id": "state-pharmacy",
        "state_class": "UNDATED_PROVIDER_DOCUMENT_REFERENCE",
        "source_signal_id": "pharmacy-undated",
        "directory_scope": "PHARMACY",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/farmacii.xlsx",
        "document_date": None,
        "metadata_sha256": "d" * 64,
        "superseded_by_source_signal_id": None,
    }

    result = aggregate([old, new, pharmacy], date(2026, 8, 30))
    by_scope = {item.directory_scope: item for item in result}
    primary = by_scope["PRIMARY_CARE"]
    assert primary.state_class == "LATEST_DATED_REFERENCE_IDENTIFIED_REVIEW_REQUIRED"
    assert primary.latest_source_signal_id == "primary-new"
    assert primary.latest_document_date == "2026-08-30"
    assert primary.latest_document_age_days == 0
    assert primary.recency_band == "DATED_0_30_DAYS"
    assert primary.superseded_reference_count == 1
    assert primary.current_contract_status_claim_allowed is False
    assert primary.public_projection_allowed is False

    pharmacy_state = by_scope["PHARMACY"]
    assert pharmacy_state.state_class == "ONLY_UNDATED_REFERENCES_REVIEW_REQUIRED"
    assert pharmacy_state.latest_document_date is None
    assert pharmacy_state.basis == "NO_EXPLICIT_DOCUMENT_DATE"

    future = {**new, "state_id": "future", "source_signal_id": "future-signal", "document_date": "2026-08-31"}
    held_future = aggregate_scope([future], "PRIMARY_CARE", date(2026, 8, 30))
    assert held_future.review_status == "HOLD"
    assert held_future.hold_reason == "FUTURE_DOCUMENT_DATE"

    ambiguous = {
        **new,
        "state_id": "same-date-2",
        "source_signal_id": "primary-new-2",
        "metadata_sha256": "e" * 64,
    }
    held_ambiguous = aggregate_scope([new, ambiguous], "PRIMARY_CARE", date(2026, 8, 30))
    assert held_ambiguous.hold_reason == "AMBIGUOUS_LATEST_DOCUMENT_DATE"

    bad_successor = {**old, "superseded_by_source_signal_id": "missing"}
    held_successor = aggregate_scope([bad_successor, new], "PRIMARY_CARE", date(2026, 8, 30))
    assert held_successor.hold_reason == "SUPERSESSION_SUCCESSOR_NOT_IN_INPUT"

    stale_active = {
        **old,
        "state_id": "stale-active",
        "state_class": "DATED_PROVIDER_DOCUMENT_REFERENCE",
        "source_signal_id": "primary-stale-active",
        "metadata_sha256": "f" * 64,
        "superseded_by_source_signal_id": None,
    }
    held_stale = aggregate_scope([stale_active, new], "PRIMARY_CARE", date(2026, 8, 30))
    assert held_stale.hold_reason == "OLDER_DATED_REFERENCE_NOT_MARKED_SUPERSEDED"

    unsafe = {**new, "current_opening_status_claim_allowed": True}
    assert aggregate_scope([unsafe], "PRIMARY_CARE", date(2026, 8, 30)).review_status == "HOLD"

    upstream_hold = {
        **new,
        "state_class": "HOLD_PROVIDER_DOCUMENT_METADATA",
        "review_status": "HOLD",
        "hold_reason": "SOURCE_TAXONOMY_DRIFT",
    }
    assert aggregate_scope([upstream_hold], "PRIMARY_CARE", date(2026, 8, 30)).hold_reason == "UPSTREAM_METADATA_HELD"

    unknown = {**new, "directory_scope": "DENTAL"}
    all_held = aggregate([unknown], date(2026, 8, 30))
    assert all(item.review_status == "HOLD" for item in all_held)
    assert all(item.hold_reason == "UNSUPPORTED_SCOPE_IN_INPUT" for item in all_held)

    empty = aggregate([], date(2026, 8, 30))
    assert all(item.state_class == "NO_REFERENCE_IN_INPUT_REVIEW_REQUIRED" for item in empty)

    print("CAS Valcea provider-directory recency self-test: OK")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON array of CAS provider-document metadata states.")
    parser.add_argument("--as-of", help="Explicit YYYY-MM-DD comparison date; required outside self-test.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.input or not args.as_of:
        parser.error("--input and --as-of are required unless --self-test is used")

    as_of = parse_iso_date(args.as_of)
    if as_of is None:
        parser.error("--as-of must be an exact ISO date YYYY-MM-DD")

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("input must be a JSON array of metadata-state objects")

    output = json.dumps(
        [asdict(item) for item in aggregate(payload, as_of)],
        ensure_ascii=False,
        indent=2,
    ) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
