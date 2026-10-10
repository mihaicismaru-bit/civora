from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from research_storage import canonical_json_bytes, validate_record_envelope

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_WRAPPER_KEYS = {
    "schema_version",
    "received_at",
    "raw_sha256",
    "normalized_sha256",
    "record",
}
EXPECTED_RECEIPT_KEYS = {
    "schema_version",
    "response_id",
    "form_id",
    "accepted_at",
    "body_sha256",
    "normalized_sha256",
    "raw_sha256",
    "pii_in_receipt",
}


class CanonicalExportIntegrityError(ValueError):
    pass


def _sha256_hex(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CanonicalExportIntegrityError(f"{field} must be lowercase SHA-256 hex")
    return value


def _canonical_json_no_newline(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def analytical_body_sha256(record: dict[str, Any]) -> str:
    required = (
        "research_id",
        "form_id",
        "form_version",
        "recruitment_channel_id",
        "profile",
        "answers",
        "synthetic",
    )
    missing = [key for key in required if key not in record]
    if missing:
        raise CanonicalExportIntegrityError(
            "record missing analytical-body fields: " + ",".join(sorted(missing))
        )
    analytical_body = {key: record[key] for key in required}
    return hashlib.sha256(_canonical_json_no_newline(analytical_body)).hexdigest()


def validate_persisted_bundle(bundle: Any) -> dict[str, Any]:
    """Validate one provider/export bundle before it can become canonical NF06 source bytes.

    This control never infers respondent identity and never promotes evidence by itself.
    It checks that the record read from storage is exactly the record whose persistence
    hashes and idempotency receipt were committed by the research runtime.
    """
    if not isinstance(bundle, dict):
        raise CanonicalExportIntegrityError("persisted bundle must be an object")
    if set(bundle) != {"filename_response_id", "wrapper", "receipt"}:
        raise CanonicalExportIntegrityError("persisted bundle fields mismatch")

    filename_response_id = _sha256_hex(
        bundle.get("filename_response_id"), field="filename_response_id"
    )
    wrapper = bundle.get("wrapper")
    receipt = bundle.get("receipt")
    if not isinstance(wrapper, dict) or set(wrapper) != EXPECTED_WRAPPER_KEYS:
        raise CanonicalExportIntegrityError("response wrapper fields mismatch")
    if not isinstance(receipt, dict) or set(receipt) != EXPECTED_RECEIPT_KEYS:
        raise CanonicalExportIntegrityError("idempotency receipt fields mismatch")
    if wrapper.get("schema_version") != 1 or receipt.get("schema_version") != 1:
        raise CanonicalExportIntegrityError("unsupported persisted wrapper/receipt version")

    record = wrapper.get("record")
    if not isinstance(record, dict):
        raise CanonicalExportIntegrityError("persisted record must be an object")
    try:
        validate_record_envelope(record)
    except Exception as exc:
        raise CanonicalExportIntegrityError(str(exc)) from exc

    response_id = _sha256_hex(record.get("response_id"), field="record.response_id")
    if response_id != filename_response_id:
        raise CanonicalExportIntegrityError("response filename does not match record response_id")
    if receipt.get("response_id") != response_id:
        raise CanonicalExportIntegrityError("receipt response_id does not match record")
    if receipt.get("form_id") != record.get("form_id"):
        raise CanonicalExportIntegrityError("receipt form_id does not match record")
    if wrapper.get("received_at") != record.get("received_at"):
        raise CanonicalExportIntegrityError("wrapper received_at does not match record")
    if receipt.get("accepted_at") != record.get("received_at"):
        raise CanonicalExportIntegrityError("receipt accepted_at does not match record")
    if receipt.get("pii_in_receipt") is not False:
        raise CanonicalExportIntegrityError("receipt must assert pii_in_receipt=false")

    wrapper_raw_sha = _sha256_hex(wrapper.get("raw_sha256"), field="wrapper.raw_sha256")
    receipt_raw_sha = _sha256_hex(receipt.get("raw_sha256"), field="receipt.raw_sha256")
    if wrapper_raw_sha != receipt_raw_sha:
        raise CanonicalExportIntegrityError("raw request SHA-256 differs between wrapper and receipt")

    expected_normalized_sha = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    wrapper_normalized_sha = _sha256_hex(
        wrapper.get("normalized_sha256"), field="wrapper.normalized_sha256"
    )
    receipt_normalized_sha = _sha256_hex(
        receipt.get("normalized_sha256"), field="receipt.normalized_sha256"
    )
    if wrapper_normalized_sha != expected_normalized_sha:
        raise CanonicalExportIntegrityError("stored record normalized SHA-256 mismatch")
    if receipt_normalized_sha != expected_normalized_sha:
        raise CanonicalExportIntegrityError("receipt normalized SHA-256 mismatch")

    receipt_body_sha = _sha256_hex(receipt.get("body_sha256"), field="receipt.body_sha256")
    if receipt_body_sha != analytical_body_sha256(record):
        raise CanonicalExportIntegrityError("receipt analytical body SHA-256 mismatch")

    return record


def canonical_export_bytes_from_persisted_bundles(bundles: list[dict[str, Any]]) -> bytes:
    if not isinstance(bundles, list) or not bundles:
        raise CanonicalExportIntegrityError("persisted bundle list must be non-empty")
    records: list[dict[str, Any]] = []
    response_ids: set[str] = set()
    for bundle in bundles:
        record = validate_persisted_bundle(bundle)
        response_id = str(record["response_id"])
        if response_id in response_ids:
            raise CanonicalExportIntegrityError("duplicate response_id in persisted export")
        response_ids.add(response_id)
        records.append(record)

    records.sort(
        key=lambda row: (
            str(row.get("form_id", "")),
            str(row.get("received_at", "")),
            str(row.get("response_id", "")),
        )
    )
    return b"".join(canonical_json_bytes(record) for record in records)
