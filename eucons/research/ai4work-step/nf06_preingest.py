from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from research_storage import ALLOWED_FORMS, RESEARCH_ID, canonical_json_bytes, validate_record_envelope
from runtime import PII_PATTERNS, _form_by_id, _validate_group, load_forms, reject_forbidden_keys

PROD_EVIDENCE_CLASS = "PROD_REAL_EVIDENCE"
TEST_TWIN_EVIDENCE_CLASS = "TEST_TWIN_NON_EVIDENCE"
PROD_FRAME_STATUS = "APPROVED_FOR_PROD"
TEST_TWIN_FRAME_STATUS = "TEST_TWIN_ONLY"
EXPECTED_RECORD_KEYS = {
    "schema_version",
    "research_id",
    "form_id",
    "form_version",
    "response_id",
    "received_at",
    "profile",
    "answers",
    "synthetic",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PROD_ONLY_FRAME_FIELDS = {
    "privacy_notice_version",
    "controller_determination_reference",
    "controller_approval_reference",
    "processor_binding_reference",
    "server_log_profile_reference",
    "retention_schedule_reference",
    "production_store_binding_reference",
}
COMMON_FRAME_FIELDS = {
    "research_id",
    "collection_frame_id",
    "frame_status",
    "evidence_class",
    "instrument_versions",
    "collection_started_at",
    "collection_closed_at",
    "collection_channels",
    "source_system",
    "source_export_sha256",
    "direct_identifiers_collected",
    "crm_linkage",
    "commercial_tracking",
    "storage_class",
}


class NF06PreingestError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise NF06PreingestError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise NF06PreingestError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise NF06PreingestError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def _scan_identifier_like_strings(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _scan_identifier_like_strings(child, f"{path}.{key}")
    elif isinstance(value, list):
        for idx, child in enumerate(value):
            _scan_identifier_like_strings(child, f"{path}[{idx}]")
    elif isinstance(value, str):
        hits = [label for label, pattern in PII_PATTERNS.items() if pattern.search(value)]
        if hits:
            raise NF06PreingestError(f"identifier-like content at {path}: {sorted(hits)}")


def canonical_export_bytes(records: list[dict[str, Any]]) -> bytes:
    ordered = sorted(records, key=lambda row: (str(row.get("form_id", "")), str(row.get("received_at", "")), str(row.get("response_id", ""))))
    return b"".join(canonical_json_bytes(row) for row in ordered)


def validate_collection_frame(frame: Any, *, prod: bool) -> tuple[datetime, datetime]:
    if not isinstance(frame, dict):
        raise NF06PreingestError("collection frame must be an object")
    missing = COMMON_FRAME_FIELDS - set(frame)
    if prod:
        missing |= PROD_ONLY_FRAME_FIELDS - set(frame)
    if missing:
        raise NF06PreingestError(f"collection frame missing fields: {sorted(missing)}")

    reject_forbidden_keys(frame)
    _scan_identifier_like_strings(frame)

    if frame.get("research_id") != RESEARCH_ID:
        raise NF06PreingestError("collection frame research_id mismatch")
    if not isinstance(frame.get("collection_frame_id"), str) or not frame["collection_frame_id"].strip():
        raise NF06PreingestError("collection_frame_id required")
    if frame.get("source_system") != "eucons.ro":
        raise NF06PreingestError("source_system must be eucons.ro")
    if frame.get("direct_identifiers_collected") is not False:
        raise NF06PreingestError("direct_identifiers_collected must be false")
    if frame.get("crm_linkage") != "FORBIDDEN":
        raise NF06PreingestError("crm_linkage must remain FORBIDDEN")
    if frame.get("commercial_tracking") != "FORBIDDEN":
        raise NF06PreingestError("commercial_tracking must remain FORBIDDEN")
    if frame.get("storage_class") != "RESEARCH_ONLY_SEPARATE_FROM_CRM":
        raise NF06PreingestError("storage_class mismatch")
    if not isinstance(frame.get("source_export_sha256"), str) or not SHA256_RE.fullmatch(frame["source_export_sha256"]):
        raise NF06PreingestError("source_export_sha256 must be lowercase SHA-256 hex")

    instrument_versions = frame.get("instrument_versions")
    if not isinstance(instrument_versions, dict) or set(instrument_versions) != ALLOWED_FORMS:
        raise NF06PreingestError("instrument_versions must cover both frozen forms")
    if any(instrument_versions[form_id] != 1 for form_id in ALLOWED_FORMS):
        raise NF06PreingestError("instrument_versions must be 1 for both forms")

    channels = frame.get("collection_channels")
    if not isinstance(channels, list) or not channels or any(not isinstance(item, str) or not item.strip() for item in channels):
        raise NF06PreingestError("collection_channels must be a non-empty string list")

    start = _parse_ts(frame.get("collection_started_at"), field="collection_started_at")
    end = _parse_ts(frame.get("collection_closed_at"), field="collection_closed_at")
    if end < start:
        raise NF06PreingestError("collection window is inverted")

    if prod:
        if frame.get("frame_status") != PROD_FRAME_STATUS:
            raise NF06PreingestError("PROD collection frame must be APPROVED_FOR_PROD")
        if frame.get("evidence_class") != PROD_EVIDENCE_CLASS:
            raise NF06PreingestError("PROD evidence_class mismatch")
        for field in sorted(PROD_ONLY_FRAME_FIELDS):
            if not isinstance(frame.get(field), str) or not frame[field].strip():
                raise NF06PreingestError(f"{field} required for PROD")
    else:
        if frame.get("frame_status") != TEST_TWIN_FRAME_STATUS:
            raise NF06PreingestError("TEST TWIN collection frame must be TEST_TWIN_ONLY")
        if frame.get("evidence_class") != TEST_TWIN_EVIDENCE_CLASS:
            raise NF06PreingestError("TEST TWIN evidence_class mismatch")

    return start, end


def _validate_normalized_record(record: Any, *, prod: bool, start: datetime, end: datetime, forms: dict[str, Any]) -> datetime:
    if not isinstance(record, dict) or set(record) != EXPECTED_RECORD_KEYS:
        raise NF06PreingestError(f"record fields must be exactly {sorted(EXPECTED_RECORD_KEYS)}")
    reject_forbidden_keys(record)
    _scan_identifier_like_strings(record.get("profile"), "$.profile")
    _scan_identifier_like_strings(record.get("answers"), "$.answers")

    if record.get("research_id") != RESEARCH_ID:
        raise NF06PreingestError("record research_id mismatch")
    if record.get("form_id") not in ALLOWED_FORMS:
        raise NF06PreingestError("unsupported form_id")
    if record.get("schema_version") != 1 or record.get("form_version") != 1:
        raise NF06PreingestError("unsupported record schema/form version")
    if prod:
        try:
            validate_record_envelope(record)
        except Exception as exc:
            raise NF06PreingestError(str(exc)) from exc
    elif record.get("synthetic") is not True:
        raise NF06PreingestError("TEST TWIN records must have synthetic=true")

    form = _form_by_id(forms, record["form_id"])
    try:
        profile = _validate_group(form.get("profile", []), record.get("profile"), path="profile")
        answers = _validate_group(form.get("questions", []), record.get("answers"), path="answers")
    except Exception as exc:
        raise NF06PreingestError(f"normalized record fails frozen form validation: {exc}") from exc
    if profile != record["profile"] or answers != record["answers"]:
        raise NF06PreingestError("normalized record is not canonical for frozen form definition")

    received = _parse_ts(record.get("received_at"), field="received_at")
    if not start <= received <= end:
        raise NF06PreingestError("record received_at outside declared collection window")
    if not isinstance(record.get("response_id"), str) or not record["response_id"].strip():
        raise NF06PreingestError("response_id required")
    return received


def build_preingest_manifest(
    records: list[dict[str, Any]],
    *,
    collection_frame: dict[str, Any],
    source_bytes: bytes,
    prod: bool,
) -> dict[str, Any]:
    if not records:
        raise NF06PreingestError("empty batches are not eligible for NF06 handoff")
    if not isinstance(source_bytes, (bytes, bytearray)):
        raise NF06PreingestError("source_bytes must be bytes")

    start, end = validate_collection_frame(collection_frame, prod=prod)
    canonical = canonical_export_bytes(records)
    if bytes(source_bytes) != canonical:
        raise NF06PreingestError("source bytes do not match canonical parsed-record export")
    source_sha = hashlib.sha256(canonical).hexdigest()
    if source_sha != collection_frame["source_export_sha256"]:
        raise NF06PreingestError("source export SHA-256 mismatch")

    forms = load_forms()
    response_ids: set[str] = set()
    form_counts = {form_id: 0 for form_id in sorted(ALLOWED_FORMS)}
    received_values: list[datetime] = []
    for record in records:
        received = _validate_normalized_record(record, prod=prod, start=start, end=end, forms=forms)
        rid = record["response_id"]
        if rid in response_ids:
            raise NF06PreingestError("duplicate response_id inside batch")
        response_ids.add(rid)
        form_counts[record["form_id"]] += 1
        received_values.append(received)

    evidence_class = PROD_EVIDENCE_CLASS if prod else TEST_TWIN_EVIDENCE_CLASS
    return {
        "schema_version": "eucons.ai4work_nf06_preingest_manifest.v0.1",
        "research_id": RESEARCH_ID,
        "handoff_stage": "NF06_SOURCE_PREFLIGHT",
        "evidence_class": evidence_class,
        "non_evidence": not prod,
        "collection_frame_id": collection_frame["collection_frame_id"],
        "source_export_sha256": source_sha,
        "record_count": len(records),
        "form_counts": form_counts,
        "received_at_min": min(received_values).isoformat(),
        "received_at_max": max(received_values).isoformat(),
        "records_validated_against_frozen_forms": True,
        "direct_identifiers_collected": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "prod_promotion_eligible": prod,
        "scope_boundary": "This manifest validates source-batch integrity and eligibility for NF06 handoff only; it does not claim that NF06 ingestion, synthesis, ranking or QA has executed.",
    }


def manifest_json_bytes(manifest: dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)
