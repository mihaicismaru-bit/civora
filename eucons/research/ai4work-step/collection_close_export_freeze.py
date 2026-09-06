from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from research_storage import RESEARCH_ID, canonical_json_bytes

HERE = Path(__file__).resolve().parent
RETENTION_PATH = HERE / "GDPR_RETENTION_SCHEDULE_DRAFT.json"

SCHEMA_VERSION = "eucons.ai4work_collection_close_export_freeze.v0.1"
ARTIFACT_CLASS = "COLLECTION_CLOSE_EXPORT_FREEZE_CONTROL_NOT_NEED_EVIDENCE"
PROD_EVIDENCE_CLASS = "PROD_REAL_EVIDENCE"
FREEZE_STATUS = "FROZEN_FOR_NF06_PROD"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_CONTROL_CLOCK_SKEW = timedelta(minutes=5)
EXPECTED_KEYS = {
    "schema_version",
    "research_id",
    "artifact_class",
    "evidence_class",
    "freeze_status",
    "collection_frame_id",
    "collection_frame_sha256",
    "collection_closed_at",
    "runtime_acceptance_disabled_at",
    "export_frozen_at",
    "source_export_sha256",
    "accepted_record_count",
    "post_close_accepted_record_count",
    "rights_hold_snapshot_sha256",
    "collection_channel_register_sha256",
    "retention_schedule_sha256",
    "retention_anchor_at",
    "live_respondent_delete_max_days_after_close",
    "live_respondent_hard_stop",
    "synthetic_records_included",
    "direct_identifiers_in_receipt",
    "crm_linkage",
    "commercial_tracking",
    "control_artifact_not_need_evidence",
    "receipt_is_authorization",
    "nf06_freeze_prerequisite_satisfied",
}


class CollectionCloseExportFreezeError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise CollectionCloseExportFreezeError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        )
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise CollectionCloseExportFreezeError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None:
        raise CollectionCloseExportFreezeError(f"{field} must include timezone")
    return parsed.astimezone(timezone.utc)


def _sha256(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise CollectionCloseExportFreezeError(f"{field} must be lowercase SHA-256 hex")
    return value


def retention_schedule_sha256() -> str:
    return hashlib.sha256(RETENTION_PATH.read_bytes()).hexdigest()


def validate_collection_freeze_receipt(
    receipt: dict[str, Any] | None,
    *,
    collection_frame: dict[str, Any],
    source_bytes: bytes,
    record_count: int,
    latest_record_at: str,
    rights_hold_snapshot_sha256: str,
) -> dict[str, Any]:
    """Validate the immutable close/freeze control required before NF06 PROD handoff.

    The receipt is CONTROL metadata, never evidence of need and never an approval by
    itself. It proves that the declared collection window was closed, the runtime
    acceptance path was disabled, no post-close records were accepted, and the
    exact canonical export/rights snapshot/retention policy are frozen together.
    Future-dated operational completion claims fail closed beyond bounded clock skew.
    """
    if receipt is None:
        raise CollectionCloseExportFreezeError(
            "authoritative collection close/export freeze receipt is required"
        )
    if not isinstance(receipt, dict):
        raise CollectionCloseExportFreezeError("collection freeze receipt must be an object")
    if set(receipt) != EXPECTED_KEYS:
        missing = sorted(EXPECTED_KEYS - set(receipt))
        unexpected = sorted(set(receipt) - EXPECTED_KEYS)
        details: list[str] = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        raise CollectionCloseExportFreezeError(
            "collection freeze receipt exact field allowlist mismatch"
            + (": " + "; ".join(details) if details else "")
        )

    if receipt.get("schema_version") != SCHEMA_VERSION:
        raise CollectionCloseExportFreezeError("collection freeze receipt schema_version mismatch")
    if receipt.get("research_id") != RESEARCH_ID:
        raise CollectionCloseExportFreezeError("collection freeze receipt research_id mismatch")
    if receipt.get("artifact_class") != ARTIFACT_CLASS:
        raise CollectionCloseExportFreezeError("collection freeze receipt artifact_class mismatch")
    if receipt.get("evidence_class") != PROD_EVIDENCE_CLASS:
        raise CollectionCloseExportFreezeError("collection freeze receipt evidence_class mismatch")
    if receipt.get("freeze_status") != FREEZE_STATUS:
        raise CollectionCloseExportFreezeError("collection freeze receipt must be FROZEN_FOR_NF06_PROD")
    if receipt.get("control_artifact_not_need_evidence") is not True:
        raise CollectionCloseExportFreezeError("collection freeze receipt must be classified as control-only")
    if receipt.get("receipt_is_authorization") is not False:
        raise CollectionCloseExportFreezeError("collection freeze receipt must not act as controller/deploy authorization")
    if receipt.get("nf06_freeze_prerequisite_satisfied") is not True:
        raise CollectionCloseExportFreezeError("collection freeze prerequisite is not satisfied")
    if receipt.get("synthetic_records_included") is not False:
        raise CollectionCloseExportFreezeError("synthetic records are forbidden in PROD freeze")
    if receipt.get("direct_identifiers_in_receipt") is not False:
        raise CollectionCloseExportFreezeError("direct identifiers are forbidden in collection freeze receipt")
    if receipt.get("crm_linkage") != "FORBIDDEN":
        raise CollectionCloseExportFreezeError("collection freeze receipt must keep CRM linkage FORBIDDEN")
    if receipt.get("commercial_tracking") != "FORBIDDEN":
        raise CollectionCloseExportFreezeError("collection freeze receipt must keep commercial tracking FORBIDDEN")

    frame_id = collection_frame.get("collection_frame_id")
    if receipt.get("collection_frame_id") != frame_id:
        raise CollectionCloseExportFreezeError("collection freeze receipt collection_frame_id mismatch")
    expected_frame_sha = hashlib.sha256(canonical_json_bytes(collection_frame)).hexdigest()
    if _sha256(receipt.get("collection_frame_sha256"), field="collection_frame_sha256") != expected_frame_sha:
        raise CollectionCloseExportFreezeError("collection freeze receipt collection_frame_sha256 mismatch")

    if not isinstance(source_bytes, (bytes, bytearray)):
        raise CollectionCloseExportFreezeError("source_bytes must be bytes")
    expected_source_sha = hashlib.sha256(bytes(source_bytes)).hexdigest()
    if _sha256(receipt.get("source_export_sha256"), field="source_export_sha256") != expected_source_sha:
        raise CollectionCloseExportFreezeError("collection freeze receipt source_export_sha256 mismatch")
    if collection_frame.get("source_export_sha256") != expected_source_sha:
        raise CollectionCloseExportFreezeError("collection frame source_export_sha256 does not match frozen export")

    expected_rights_sha = _sha256(
        rights_hold_snapshot_sha256,
        field="authoritative rights_hold_snapshot_sha256",
    )
    if _sha256(receipt.get("rights_hold_snapshot_sha256"), field="rights_hold_snapshot_sha256") != expected_rights_sha:
        raise CollectionCloseExportFreezeError("collection freeze receipt rights_hold_snapshot_sha256 mismatch")

    frame_channel_sha = _sha256(
        collection_frame.get("collection_channel_register_sha256"),
        field="collection_frame.collection_channel_register_sha256",
    )
    if _sha256(receipt.get("collection_channel_register_sha256"), field="collection_channel_register_sha256") != frame_channel_sha:
        raise CollectionCloseExportFreezeError("collection freeze receipt channel-register SHA-256 mismatch")

    if _sha256(receipt.get("retention_schedule_sha256"), field="retention_schedule_sha256") != retention_schedule_sha256():
        raise CollectionCloseExportFreezeError("collection freeze receipt retention schedule SHA-256 mismatch")

    if not isinstance(record_count, int) or record_count <= 0:
        raise CollectionCloseExportFreezeError("record_count must be a positive integer")
    if receipt.get("accepted_record_count") != record_count:
        raise CollectionCloseExportFreezeError("collection freeze accepted_record_count mismatch")
    if receipt.get("post_close_accepted_record_count") != 0:
        raise CollectionCloseExportFreezeError("post-close accepted records must be zero")

    frame_closed_raw = collection_frame.get("collection_closed_at")
    if receipt.get("collection_closed_at") != frame_closed_raw:
        raise CollectionCloseExportFreezeError("collection freeze receipt collection_closed_at mismatch")
    closed_at = _parse_ts(frame_closed_raw, field="collection_frame.collection_closed_at")
    latest_at = _parse_ts(latest_record_at, field="latest_record_at")
    disabled_at = _parse_ts(
        receipt.get("runtime_acceptance_disabled_at"),
        field="runtime_acceptance_disabled_at",
    )
    frozen_at = _parse_ts(receipt.get("export_frozen_at"), field="export_frozen_at")
    retention_anchor = _parse_ts(receipt.get("retention_anchor_at"), field="retention_anchor_at")

    if latest_at > closed_at:
        raise CollectionCloseExportFreezeError("latest candidate record is after declared collection close")
    if disabled_at < closed_at:
        raise CollectionCloseExportFreezeError("runtime acceptance was disabled before declared collection close")
    if frozen_at < disabled_at:
        raise CollectionCloseExportFreezeError("canonical export was frozen before runtime acceptance was disabled")
    if frozen_at < latest_at:
        raise CollectionCloseExportFreezeError("canonical export was frozen before latest candidate record")
    if retention_anchor != closed_at:
        raise CollectionCloseExportFreezeError("retention anchor must equal collection_closed_at")

    validation_now = datetime.now(timezone.utc)
    latest_allowed_control_time = validation_now + MAX_CONTROL_CLOCK_SKEW
    for field, value in (
        ("collection_closed_at", closed_at),
        ("runtime_acceptance_disabled_at", disabled_at),
        ("export_frozen_at", frozen_at),
    ):
        if value > latest_allowed_control_time:
            raise CollectionCloseExportFreezeError(
                f"{field} is future-dated beyond allowed clock skew"
            )

    if receipt.get("live_respondent_delete_max_days_after_close") != 180:
        raise CollectionCloseExportFreezeError("live respondent deletion maximum must remain 180 days after collection close")
    if receipt.get("live_respondent_hard_stop") != "2027-03-31":
        raise CollectionCloseExportFreezeError("live respondent hard stop mismatch")

    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_class": ARTIFACT_CLASS,
        "freeze_status": FREEZE_STATUS,
        "collection_closed_at": receipt["collection_closed_at"],
        "runtime_acceptance_disabled_at": receipt["runtime_acceptance_disabled_at"],
        "export_frozen_at": receipt["export_frozen_at"],
        "collection_frame_sha256": expected_frame_sha,
        "source_export_sha256": expected_source_sha,
        "rights_hold_snapshot_sha256": expected_rights_sha,
        "retention_schedule_sha256": receipt["retention_schedule_sha256"],
        "record_count": record_count,
        "post_close_accepted_record_count": 0,
        "control_artifact_not_need_evidence": True,
        "receipt_is_authorization": False,
    }
