#!/usr/bin/env python3
"""Fail-closed metadata state for CAS Valcea provider-directory documents.

Consumes normalized signals emitted by cas_valcea_service_access_signal_adapter.py.
This layer is intentionally metadata-only: it does not download or parse provider
documents, extract provider/person identities, or assert current contract,
opening, appointment, availability, or patient-acceptance status.

It may record an explicit date found in the visible CAS anchor/title and may mark
an older document as superseded only when two same-scope documents carry
unambiguous explicit dates. An index-page date and URL upload path are retained
as provenance/context only and never promoted to document publication dates.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any, Optional

SOURCE_ID = "signal-cas-valcea-service-access"
EXPECTED_SOURCE_TAXONOMY = "2026-08-30.1"
TAXONOMY_VERSION = "2026-08-30.1"
ALLOWED_SCOPES = {"PRIMARY_CARE", "PHARMACY"}
DOCUMENT_REFERENCE = "DOCUMENT_REFERENCE"

ROMANIAN_MONTHS = {
    "ianuarie": 1, "februarie": 2, "martie": 3, "aprilie": 4,
    "mai": 5, "iunie": 6, "iulie": 7, "august": 8,
    "septembrie": 9, "octombrie": 10, "noiembrie": 11, "decembrie": 12,
}

FORBIDDEN_TRUE_FLAGS = {
    "current_provider_status_claim_allowed",
    "appointment_availability_claim_allowed",
    "linked_document_body_parse_allowed",
    "provider_person_extraction_allowed",
    "persistence_allowed",
    "fact_kernel_promotion_allowed",
    "writer_allowed",
    "public_projection_allowed",
}

@dataclass(frozen=True)
class ProviderDocumentMetadataState:
    state_id: str
    taxonomy_version: str
    state_class: str
    review_status: str
    source_signal_id: str
    source_id: str
    source_taxonomy_version: str
    directory_scope: str
    source_url: str
    index_url: str
    payload_sha256: str
    document_date: Optional[str]
    index_date: Optional[str]
    metadata_sha256: str
    superseded_by_source_signal_id: Optional[str]
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

def fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return clean("".join(ch for ch in normalized if not unicodedata.combining(ch)).lower())

def digest(*parts: Any) -> str:
    payload = "\0".join(clean(part) for part in parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(ch in "0123456789abcdefABCDEF" for ch in value)

def explicit_dates(text: str) -> list[str]:
    """Return unique valid dates explicitly present in visible text."""
    value = fold(text)
    found: set[str] = set()

    for day, month, year in re.findall(r"\b([0-3]?\d)[./-]([01]?\d)[./-](20\d{2})\b", value):
        try:
            found.add(date(int(year), int(month), int(day)).isoformat())
        except ValueError:
            pass

    month_names = "|".join(ROMANIAN_MONTHS)
    for day, month_name, year in re.findall(
        rf"\b([0-3]?\d)\s+({month_names})\s+(20\d{{2}})\b", value
    ):
        try:
            found.add(date(int(year), ROMANIAN_MONTHS[month_name], int(day)).isoformat())
        except ValueError:
            pass

    return sorted(found)

def state_id(signal_id: str, state_class: str) -> str:
    return f"casvl-docmeta-{digest(signal_id, state_class)[:20]}"

def metadata_hash(signal: dict[str, Any], document_date: Optional[str]) -> str:
    return digest(
        clean(signal.get("signal_id")),
        clean(signal.get("directory_scope")),
        clean(signal.get("source_url")),
        clean(signal.get("index_url")),
        clean(signal.get("payload_sha256")),
        document_date or "",
        clean(signal.get("index_date")),
    )

def hold(signal: dict[str, Any], reason: str) -> ProviderDocumentMetadataState:
    signal_id = clean(signal.get("signal_id")) or "unknown"
    source_id = clean(signal.get("source_id")) or "unknown"
    source_taxonomy = clean(signal.get("taxonomy_version")) or "unknown"
    scope = clean(signal.get("directory_scope")) or "UNKNOWN"
    payload = clean(signal.get("payload_sha256"))
    return ProviderDocumentMetadataState(
        state_id=state_id(signal_id, "HOLD"),
        taxonomy_version=TAXONOMY_VERSION,
        state_class="HOLD_PROVIDER_DOCUMENT_METADATA",
        review_status="HOLD",
        source_signal_id=signal_id,
        source_id=source_id,
        source_taxonomy_version=source_taxonomy,
        directory_scope=scope,
        source_url="",
        index_url="",
        payload_sha256=payload,
        document_date=None,
        index_date=None,
        metadata_sha256=digest(signal_id, reason, payload),
        superseded_by_source_signal_id=None,
        hold_reason=reason,
    )

def validate_signal(signal: dict[str, Any]) -> Optional[str]:
    if clean(signal.get("source_id")) != SOURCE_ID:
        return "UNEXPECTED_SOURCE"
    if clean(signal.get("taxonomy_version")) != EXPECTED_SOURCE_TAXONOMY:
        return "SOURCE_TAXONOMY_DRIFT"
    if clean(signal.get("signal_class")) == "HOLD" or signal.get("hold_reason"):
        return "UPSTREAM_SIGNAL_HELD"
    if clean(signal.get("signal_class")) != "HEALTH_PROVIDER_DIRECTORY":
        return "UNEXPECTED_SIGNAL_CLASS"
    if clean(signal.get("directory_scope")) not in ALLOWED_SCOPES:
        return "UNSUPPORTED_DIRECTORY_SCOPE"
    if clean(signal.get("reference_kind")) != DOCUMENT_REFERENCE:
        return "NOT_DOCUMENT_REFERENCE"
    if not clean(signal.get("signal_id")):
        return "MISSING_SIGNAL_ID"
    if not clean(signal.get("source_url")):
        return "MISSING_SOURCE_URL"
    payload = clean(signal.get("payload_sha256"))
    if not valid_sha256(payload):
        return "INVALID_PAYLOAD_SHA256"
    authority = signal.get("publication_authority")
    if authority not in (None, "NONE"):
        return "PUBLICATION_AUTHORITY_DRIFT"
    for flag in FORBIDDEN_TRUE_FLAGS:
        if signal.get(flag) is True:
            return f"UNSAFE_UPSTREAM_BOUNDARY_{flag.upper()}"
    return None

def normalize_signal(signal: dict[str, Any]) -> ProviderDocumentMetadataState:
    problem = validate_signal(signal)
    if problem:
        return hold(signal, problem)

    visible_title = clean(signal.get("title"))
    dates = explicit_dates(visible_title)
    if len(dates) > 1:
        return hold(signal, "AMBIGUOUS_EXPLICIT_DOCUMENT_DATE")
    document_date = dates[0] if dates else None

    signal_id = clean(signal["signal_id"])
    scope = clean(signal["directory_scope"])
    state_class = (
        "DATED_PROVIDER_DOCUMENT_REFERENCE"
        if document_date
        else "UNDATED_PROVIDER_DOCUMENT_REFERENCE"
    )
    return ProviderDocumentMetadataState(
        state_id=state_id(signal_id, state_class),
        taxonomy_version=TAXONOMY_VERSION,
        state_class=state_class,
        review_status="REVIEW_REQUIRED",
        source_signal_id=signal_id,
        source_id=SOURCE_ID,
        source_taxonomy_version=EXPECTED_SOURCE_TAXONOMY,
        directory_scope=scope,
        source_url=clean(signal["source_url"]),
        index_url=clean(signal.get("index_url")),
        payload_sha256=clean(signal["payload_sha256"]).lower(),
        document_date=document_date,
        index_date=clean(signal.get("index_date")) or None,
        metadata_sha256=metadata_hash(signal, document_date),
        superseded_by_source_signal_id=None,
        hold_reason=None,
    )

def apply_supersession(
    states: list[ProviderDocumentMetadataState],
) -> list[ProviderDocumentMetadataState]:
    """Mark older explicitly dated same-scope refs; undated refs never supersede."""
    newest: dict[str, ProviderDocumentMetadataState] = {}
    for item in states:
        if item.review_status != "REVIEW_REQUIRED" or not item.document_date:
            continue
        current = newest.get(item.directory_scope)
        if current is None or (item.document_date, item.source_signal_id) > (
            current.document_date or "",
            current.source_signal_id,
        ):
            newest[item.directory_scope] = item

    result: list[ProviderDocumentMetadataState] = []
    for item in states:
        latest = newest.get(item.directory_scope)
        if (
            latest
            and item.review_status == "REVIEW_REQUIRED"
            and item.document_date
            and item.source_signal_id != latest.source_signal_id
            and item.document_date < (latest.document_date or "")
        ):
            item = replace(
                item,
                state_class="SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE",
                superseded_by_source_signal_id=latest.source_signal_id,
                metadata_sha256=digest(
                    item.metadata_sha256, "superseded-by", latest.source_signal_id
                ),
            )
        result.append(item)
    return result

def normalize(signals: list[dict[str, Any]]) -> list[ProviderDocumentMetadataState]:
    states = [normalize_signal(signal) for signal in signals]
    states = apply_supersession(states)
    states.sort(
        key=lambda item: (
            item.directory_scope,
            item.document_date or "",
            item.source_signal_id,
        )
    )
    return states

def self_test() -> None:
    base = {
        "source_id": SOURCE_ID,
        "taxonomy_version": EXPECTED_SOURCE_TAXONOMY,
        "signal_class": "HEALTH_PROVIDER_DIRECTORY",
        "reference_kind": "DOCUMENT_REFERENCE",
        "index_url": "https://cas.cnas.ro/casvl/informatii-furnizori/furnizori-de-servicii-medicale",
        "payload_sha256": "a" * 64,
        "publication_authority": "NONE",
        "current_provider_status_claim_allowed": False,
        "appointment_availability_claim_allowed": False,
        "linked_document_body_parse_allowed": False,
        "provider_person_extraction_allowed": False,
    }
    old = {
        **base,
        "signal_id": "primary-old",
        "directory_scope": "PRIMARY_CARE",
        "title": "Furnizori medicina primară 31 iulie 2026",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/medicina-primara.xlsx",
        "index_date": "2026-08-30",
    }
    new = {
        **base,
        "signal_id": "primary-new",
        "directory_scope": "PRIMARY_CARE",
        "title": "Furnizori medicina primară - 30.08.2026",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/medicina-primara-2.xlsx",
        "index_date": "2026-08-30",
    }
    pharmacy = {
        **base,
        "signal_id": "pharmacy-undated",
        "directory_scope": "PHARMACY",
        "title": "Lista farmacii",
        "source_url": "https://cas.cnas.ro/casvl/wp-content/uploads/2026/08/farmacii.xlsx",
        "index_date": "2026-08-30",
    }
    states = normalize([new, old, pharmacy])
    by_id = {item.source_signal_id: item for item in states}
    assert by_id["primary-old"].state_class == "SUPERSEDED_PROVIDER_DOCUMENT_REFERENCE"
    assert by_id["primary-old"].superseded_by_source_signal_id == "primary-new"
    assert by_id["primary-new"].state_class == "DATED_PROVIDER_DOCUMENT_REFERENCE"
    assert by_id["primary-new"].document_date == "2026-08-30"
    assert by_id["pharmacy-undated"].state_class == "UNDATED_PROVIDER_DOCUMENT_REFERENCE"
    assert by_id["pharmacy-undated"].document_date is None
    assert by_id["pharmacy-undated"].index_date == "2026-08-30"

    assert explicit_dates(pharmacy["source_url"]) == []

    ambiguous = {
        **new,
        "signal_id": "ambiguous",
        "title": "Lista 29.08.2026 / actualizare 30.08.2026",
    }
    held = normalize_signal(ambiguous)
    assert held.review_status == "HOLD"
    assert held.hold_reason == "AMBIGUOUS_EXPLICIT_DOCUMENT_DATE"
    assert held.source_url == ""

    html_ref = {**pharmacy, "signal_id": "html", "reference_kind": "HTML_REFERENCE"}
    assert normalize_signal(html_ref).hold_reason == "NOT_DOCUMENT_REFERENCE"

    unsafe = {**new, "signal_id": "unsafe", "current_provider_status_claim_allowed": True}
    assert normalize_signal(unsafe).review_status == "HOLD"

    wrong_scope = {**new, "signal_id": "hospital", "directory_scope": "HOSPITAL"}
    assert normalize_signal(wrong_scope).hold_reason == "UNSUPPORTED_DIRECTORY_SCOPE"

    wrong_taxonomy = {**new, "signal_id": "drift", "taxonomy_version": "2099-01-01.1"}
    assert normalize_signal(wrong_taxonomy).hold_reason == "SOURCE_TAXONOMY_DRIFT"

    for item in states:
        assert item.document_body_parse_allowed is False
        assert item.provider_identity_extraction_allowed is False
        assert item.current_contract_status_claim_allowed is False
        assert item.current_opening_status_claim_allowed is False
        assert item.accepting_patients_claim_allowed is False
        assert item.persistence_allowed is False
        assert item.fact_kernel_promotion_allowed is False
        assert item.writer_allowed is False
        assert item.public_projection_allowed is False

    print("CAS Valcea provider-document metadata self-test: OK")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", help="JSON array of CAS service-access signals.")
    parser.add_argument("--output", help="Optional JSON output path.")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not args.input:
        parser.error("--input is required unless --self-test is used")

    payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError("input must be a JSON array of signal objects")
    output = json.dumps([asdict(item) for item in normalize(payload)], ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
