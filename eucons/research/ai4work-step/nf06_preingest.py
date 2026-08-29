from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from channel_provenance import ChannelProvenanceError, validate_channel_set, validate_recruitment_channel_id
from research_storage import ALLOWED_FORMS, RESEARCH_ID, canonical_json_bytes, validate_record_envelope
from runtime import CONTRACT_PATH, FORMS_PATH, PII_PATTERNS, _form_by_id, _validate_group, load_forms, reject_forbidden_keys

PROD_EVIDENCE_CLASS = "PROD_REAL_EVIDENCE"
TEST_TWIN_EVIDENCE_CLASS = "TEST_TWIN_NON_EVIDENCE"
PROD_FRAME_STATUS = "APPROVED_FOR_PROD"
TEST_TWIN_FRAME_STATUS = "TEST_TWIN_ONLY"
TARGET_REGIONS = ("Centru", "Sud-Muntenia", "Sud-Vest Oltenia")
EXPECTED_RECORD_KEYS = {
    "schema_version",
    "research_id",
    "form_id",
    "form_version",
    "response_id",
    "received_at",
    "recruitment_channel_id",
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
    "form_contract_sha256",
    "forms_definition_sha256",
    "collection_started_at",
    "collection_closed_at",
    "collection_channels",
    "collection_channel_register_sha256",
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
        leaf = path.rsplit(".", 1)[-1]
        if leaf.endswith("_sha256") and SHA256_RE.fullmatch(value):
            return
        hits = [label for label, pattern in PII_PATTERNS.items() if pattern.search(value)]
        if hits:
            raise NF06PreingestError(f"identifier-like content at {path}: {sorted(hits)}")


def canonical_export_bytes(records: list[dict[str, Any]]) -> bytes:
    ordered = sorted(records, key=lambda row: (str(row.get("form_id", "")), str(row.get("received_at", "")), str(row.get("response_id", ""))))
    return b"".join(canonical_json_bytes(row) for row in ordered)


def instrument_definition_hashes() -> dict[str, str]:
    return {
        "form_contract_sha256": hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest(),
        "forms_definition_sha256": hashlib.sha256(FORMS_PATH.read_bytes()).hexdigest(),
    }


def validate_collection_frame(frame: Any, *, prod: bool) -> tuple[datetime, datetime, frozenset[str]]:
    if not isinstance(frame, dict):
        raise NF06PreingestError("collection frame must be an object")
    expected_fields = COMMON_FRAME_FIELDS | (PROD_ONLY_FRAME_FIELDS if prod else set())
    actual_fields = set(frame)
    missing = expected_fields - actual_fields
    extra = actual_fields - expected_fields
    if missing:
        raise NF06PreingestError(f"collection frame missing fields: {sorted(missing)}")
    if extra:
        raise NF06PreingestError(f"collection frame contains unreviewed fields: {sorted(extra)}")

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
    if not isinstance(frame.get("collection_channel_register_sha256"), str) or not SHA256_RE.fullmatch(frame["collection_channel_register_sha256"]):
        raise NF06PreingestError("collection_channel_register_sha256 must be lowercase SHA-256 hex")

    current_instrument_hashes = instrument_definition_hashes()
    for field, expected_hash in current_instrument_hashes.items():
        if not isinstance(frame.get(field), str) or not SHA256_RE.fullmatch(frame[field]):
            raise NF06PreingestError(f"{field} must be lowercase SHA-256 hex")
        if frame[field] != expected_hash:
            raise NF06PreingestError(f"{field} does not match the frozen repository instrument")

    instrument_versions = frame.get("instrument_versions")
    if not isinstance(instrument_versions, dict) or set(instrument_versions) != ALLOWED_FORMS:
        raise NF06PreingestError("instrument_versions must cover both frozen forms")
    if any(instrument_versions[form_id] != 1 for form_id in ALLOWED_FORMS):
        raise NF06PreingestError("instrument_versions must be 1 for both forms")

    try:
        channels = frozenset(validate_channel_set(frame.get("collection_channels")))
    except ChannelProvenanceError as exc:
        raise NF06PreingestError(str(exc)) from exc

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

    return start, end, channels


def _validate_normalized_record(
    record: Any,
    *,
    prod: bool,
    start: datetime,
    end: datetime,
    forms: dict[str, Any],
    allowed_channels: frozenset[str],
) -> datetime:
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
    if not isinstance(record.get("response_id"), str) or not SHA256_RE.fullmatch(record["response_id"]):
        raise NF06PreingestError("response_id must be a lowercase 64-hex opaque receipt")
    try:
        channel_id = validate_recruitment_channel_id(record.get("recruitment_channel_id"))
    except ChannelProvenanceError as exc:
        raise NF06PreingestError(str(exc)) from exc
    if channel_id not in allowed_channels:
        raise NF06PreingestError("record recruitment_channel_id is not declared in collection frame")
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

    start, end, allowed_channels = validate_collection_frame(collection_frame, prod=prod)
    canonical = canonical_export_bytes(records)
    if bytes(source_bytes) != canonical:
        raise NF06PreingestError("source bytes do not match canonical parsed-record export")
    source_sha = hashlib.sha256(canonical).hexdigest()
    if source_sha != collection_frame["source_export_sha256"]:
        raise NF06PreingestError("source export SHA-256 mismatch")

    forms = load_forms()
    response_ids: set[str] = set()
    form_counts = {form_id: 0 for form_id in sorted(ALLOWED_FORMS)}
    region_counts: Counter[str] = Counter()
    form_region_counts: dict[str, Counter[str]] = {
        form_id: Counter({region: 0 for region in TARGET_REGIONS}) for form_id in sorted(ALLOWED_FORMS)
    }
    region_channel_ids: dict[str, set[str]] = {region: set() for region in TARGET_REGIONS}
    form_region_channel_ids: dict[str, dict[str, set[str]]] = {
        form_id: {region: set() for region in TARGET_REGIONS} for form_id in sorted(ALLOWED_FORMS)
    }
    channel_counts: Counter[str] = Counter()
    received_values: list[datetime] = []
    for record in records:
        received = _validate_normalized_record(
            record,
            prod=prod,
            start=start,
            end=end,
            forms=forms,
            allowed_channels=allowed_channels,
        )
        rid = record["response_id"]
        if rid in response_ids:
            raise NF06PreingestError("duplicate response_id inside batch")
        response_ids.add(rid)
        form_id = record["form_id"]
        region = record["profile"]["region"]
        if region not in TARGET_REGIONS:
            raise NF06PreingestError("record region outside AI4WORK target regions")
        channel_id = record["recruitment_channel_id"]
        form_counts[form_id] += 1
        region_counts[region] += 1
        form_region_counts[form_id][region] += 1
        region_channel_ids[region].add(channel_id)
        form_region_channel_ids[form_id][region].add(channel_id)
        channel_counts[channel_id] += 1
        received_values.append(received)

    evidence_class = PROD_EVIDENCE_CLASS if prod else TEST_TWIN_EVIDENCE_CLASS
    dominant_channel_share = max(channel_counts.values()) / len(records)
    frame_sha = hashlib.sha256(canonical_json_bytes(collection_frame)).hexdigest()
    return {
        "schema_version": "eucons.ai4work_nf06_preingest_manifest.v0.5",
        "research_id": RESEARCH_ID,
        "handoff_stage": "NF06_SOURCE_PREFLIGHT",
        "evidence_class": evidence_class,
        "non_evidence": not prod,
        "collection_frame_id": collection_frame["collection_frame_id"],
        "collection_frame_sha256": frame_sha,
        "source_export_sha256": source_sha,
        "collection_channel_register_sha256": collection_frame["collection_channel_register_sha256"],
        "form_contract_sha256": collection_frame["form_contract_sha256"],
        "forms_definition_sha256": collection_frame["forms_definition_sha256"],
        "record_count": len(records),
        "form_counts": form_counts,
        "region_counts": {region: region_counts.get(region, 0) for region in TARGET_REGIONS},
        "form_region_counts": {
            form_id: {region: form_region_counts[form_id].get(region, 0) for region in TARGET_REGIONS}
            for form_id in sorted(ALLOWED_FORMS)
        },
        "region_channel_ids": {
            region: sorted(region_channel_ids[region]) for region in TARGET_REGIONS
        },
        "form_region_channel_ids": {
            form_id: {
                region: sorted(form_region_channel_ids[form_id][region]) for region in TARGET_REGIONS
            }
            for form_id in sorted(ALLOWED_FORMS)
        },
        "channel_counts": dict(sorted(channel_counts.items())),
        "dominant_channel_share": dominant_channel_share,
        "received_at_min": min(received_values).isoformat(),
        "received_at_max": max(received_values).isoformat(),
        "records_validated_against_frozen_forms": True,
        "instrument_content_hashes_validated": True,
        "collection_frame_exact_field_allowlist_validated": True,
        "channel_membership_validated_against_collection_frame": True,
        "method_coverage_aggregates_emitted": True,
        "form_audience_channel_provenance_emitted": True,
        "direct_identifiers_collected": False,
        "crm_linkage": "FORBIDDEN",
        "commercial_tracking": "FORBIDDEN",
        "prod_promotion_eligible": prod,
        "scope_boundary": "This manifest validates source-batch integrity, exact collection-frame identity, frozen instrument content, opaque recruitment-channel provenance and eligibility for NF06 handoff only. Region/form coverage and form-specific channel provenance aggregates are internal method-QA inputs, not population estimates or need evidence; it does not claim that NF06 ingestion, synthesis, ranking or QA has executed.",
    }


def manifest_json_bytes(manifest: dict[str, Any]) -> bytes:
    return canonical_json_bytes(manifest)
