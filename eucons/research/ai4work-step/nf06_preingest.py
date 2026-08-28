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
        # A cryptographic digest is opaque machine provenance, not respondent text.
        # Decimal substrings inside a valid 64-hex SHA-256 can coincidentally match
        # CNP/phone-like heuristics, so do not run semantic PII regexes over a value
        # whose field is explicitly a *_sha256 digest. Every accepted digest field is
        # separately format-validated below, and the instrument/channel/source hashes
        # are additionally bound to their actual bytes by their respective validators.
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
        raise NF06PreingestError("instrument_versions must match frozen form versions")

    collection_channels = frame.get("collection_channels")
    if not isinstance(collection_channels, list) or not collection_channels:
        raise NF06PreingestError("collection_channels must be a non-empty list")
    try:
        allowed_channels = validate_channel_set(collection_channels)
    except ChannelProvenanceError as exc:
        raise NF06PreingestError(str(exc)) from exc

    start = _parse_ts(frame.get("collection_started_at"), field="collection_started_at")
    end = _parse_ts(frame.get("collection_closed_at"), field="collection_closed_at")
    if start >= end:
        raise NF06PreingestError("collection window must have positive duration")

    if prod:
        if frame.get("frame_status") != PROD_FRAME_STATUS:
            raise NF06PreingestError("PROD requires APPROVED_FOR_PROD collection frame")
        if frame.get("evidence_class") != PROD_EVIDENCE_CLASS:
            raise NF06PreingestError("PROD requires PROD_REAL_EVIDENCE")
        for field in PROD_ONLY_FRAME_FIELDS:
            if not isinstance(frame.get(field), str) or not frame[field].strip():
                raise NF06PreingestError(f"PROD frame requires {field}")
    else:
        if frame.get("frame_status") != TEST_TWIN_FRAME_STATUS:
            raise NF06PreingestError("TEST TWIN requires TEST_TWIN_ONLY frame")
        if frame.get("evidence_class") != TEST_TWIN_EVIDENCE_CLASS:
            raise NF06PreingestError("TEST TWIN must remain TEST_TWIN_NON_EVIDENCE")

    return start, end, allowed_channels


def _record_method_coverage(records: list[dict[str, Any]]) -> dict[str, Any]:
    regions: Counter[str] = Counter()
    forms: Counter[str] = Counter()
    region_forms: Counter[tuple[str, str]] = Counter()
    channels: Counter[str] = Counter()
    region_channels: dict[str, set[str]] = {region: set() for region in TARGET_REGIONS}
    for record in records:
        region = str(record["profile"]["region"])
        form_id = str(record["form_id"])
        channel = str(record["recruitment_channel_id"])
        regions[region] += 1
        forms[form_id] += 1
        region_forms[(region, form_id)] += 1
        channels[channel] += 1
        region_channels.setdefault(region, set()).add(channel)
    return {
        "records_total": len(records),
        "by_region": dict(sorted(regions.items())),
        "by_form": dict(sorted(forms.items())),
        "by_region_form": {
            f"{region}|{form_id}": count
            for (region, form_id), count in sorted(region_forms.items())
        },
        "by_channel": dict(sorted(channels.items())),
        "channels_by_region": {
            region: sorted(region_channels.get(region, set()))
            for region in TARGET_REGIONS
        },
    }


def _validate_source_export(records: list[dict[str, Any]], frame: dict[str, Any]) -> tuple[bytes, str]:
    export_bytes = canonical_export_bytes(records)
    export_hash = hashlib.sha256(export_bytes).hexdigest()
    if frame["source_export_sha256"] != export_hash:
        raise NF06PreingestError("source export SHA-256 does not match canonical export bytes")
    return export_bytes, export_hash


def _validate_records(
    records: Any,
    *,
    prod: bool,
    start: datetime,
    end: datetime,
    allowed_channels: frozenset[str],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not isinstance(records, list) or not records:
        raise NF06PreingestError("response batch must contain at least one record")
    seen_response_ids: set[str] = set()
    counts = {form_id: 0 for form_id in ALLOWED_FORMS}
    validated: list[dict[str, Any]] = []
    forms = load_forms()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise NF06PreingestError(f"record {index} must be an object")
        if set(record) != EXPECTED_RECORD_KEYS:
            missing = EXPECTED_RECORD_KEYS - set(record)
            extra = set(record) - EXPECTED_RECORD_KEYS
            raise NF06PreingestError(f"record {index} schema mismatch missing={sorted(missing)} extra={sorted(extra)}")
        reject_forbidden_keys(record)
        validate_record_envelope(record, expected_synthetic=not prod)
        if record["response_id"] in seen_response_ids:
            raise NF06PreingestError(f"duplicate response_id at record {index}")
        seen_response_ids.add(record["response_id"])

        try:
            validate_recruitment_channel_id(record["recruitment_channel_id"])
        except ChannelProvenanceError as exc:
            raise NF06PreingestError(f"record {index}: {exc}") from exc
        if record["recruitment_channel_id"] not in allowed_channels:
            raise NF06PreingestError(f"record {index}: recruitment_channel_id not in frozen collection frame")

        received = _parse_ts(record["received_at"], field=f"record[{index}].received_at")
        if not (start <= received <= end):
            raise NF06PreingestError(f"record {index}: received_at outside collection window")

        form_id = record["form_id"]
        form = _form_by_id(forms, form_id)
        if record["form_version"] != 1:
            raise NF06PreingestError(f"record {index}: form_version mismatch")
        _validate_group(record["profile"], form.get("profile", []), context=f"record[{index}].profile")
        _validate_group(record["answers"], form.get("questions", []), context=f"record[{index}].answers")
        _scan_identifier_like_strings(record["profile"], f"$.records[{index}].profile")
        _scan_identifier_like_strings(record["answers"], f"$.records[{index}].answers")
        counts[form_id] += 1
        validated.append(record)
    return validated, counts


def build_preingest_manifest(
    records: Any,
    collection_frame: Any,
    *,
    prod: bool,
) -> dict[str, Any]:
    start, end, allowed_channels = validate_collection_frame(collection_frame, prod=prod)
    validated, counts = _validate_records(records, prod=prod, start=start, end=end, allowed_channels=allowed_channels)
    export_bytes, export_hash = _validate_source_export(validated, collection_frame)
    return {
        "schema_version": "eucons.nf06_preingest_manifest.v0.4",
        "research_id": RESEARCH_ID,
        "evidence_class": PROD_EVIDENCE_CLASS if prod else TEST_TWIN_EVIDENCE_CLASS,
        "collection_frame_id": collection_frame["collection_frame_id"],
        "source_export_sha256": export_hash,
        "source_export_bytes": len(export_bytes),
        "record_count": len(validated),
        "form_counts": counts,
        "method_coverage": _record_method_coverage(validated),
        "synthetic": not prod,
        "nf06_handoff_eligible": True,
        "claim_boundary": (
            "Pre-ingest validation proves schema/provenance/source-byte integrity only; it does not prove representativeness, prevalence, causality or a need conclusion."
            if prod
            else "TEST TWIN only. NON-EVIDENCE and permanently non-promotable to PROD evidence."
        ),
    }
