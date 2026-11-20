from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from research_storage import RESEARCH_ID, canonical_json_bytes


LOCK_KEYS = {
    "schema_version",
    "research_id",
    "status",
    "evidence_class",
    "collection_frame_id",
    "method_frame_sha256",
    "approved_at",
    "approver_reference",
}
LOCK_SCHEMA_VERSION = "eucons.ai4work_method_frame_lock.v0.1"
LOCK_STATUS = "APPROVED_BEFORE_COLLECTION"
LOCK_EVIDENCE_CLASS = "METHOD_CONTROL_NOT_EVIDENCE"


class MethodFrameLockError(ValueError):
    pass


def _parse_ts(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise MethodFrameLockError(f"{field} must be a non-empty ISO timestamp")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise MethodFrameLockError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise MethodFrameLockError(f"{field} must include timezone information")
    return parsed.astimezone(timezone.utc)


def assert_method_frame_locked_before_collection(
    method_frame: dict[str, Any],
    *,
    collection_frame: dict[str, Any],
    method_frame_lock: dict[str, Any],
) -> dict[str, Any]:
    """Bind the exact approved method frame to the PROD collection frame before collection.

    This is a governance/provenance control only. It prevents later threshold or
    coverage-dimension drift from being silently substituted after responses are
    collected. It is never empirical need evidence.
    """
    if not isinstance(method_frame, dict):
        raise MethodFrameLockError("method_frame must be an object")
    if not isinstance(collection_frame, dict):
        raise MethodFrameLockError("collection_frame must be an object")
    if not isinstance(method_frame_lock, dict) or set(method_frame_lock) != LOCK_KEYS:
        raise MethodFrameLockError(f"method_frame_lock fields must be exactly {sorted(LOCK_KEYS)}")
    if method_frame_lock.get("schema_version") != LOCK_SCHEMA_VERSION:
        raise MethodFrameLockError("unsupported method_frame_lock schema")
    if method_frame_lock.get("research_id") != RESEARCH_ID or method_frame.get("research_id") != RESEARCH_ID:
        raise MethodFrameLockError("research_id mismatch in method-frame lock")
    if method_frame_lock.get("status") != LOCK_STATUS:
        raise MethodFrameLockError("method_frame_lock must be APPROVED_BEFORE_COLLECTION")
    if method_frame_lock.get("evidence_class") != LOCK_EVIDENCE_CLASS:
        raise MethodFrameLockError("method_frame_lock must remain METHOD_CONTROL_NOT_EVIDENCE")

    frame_id = collection_frame.get("collection_frame_id")
    if not isinstance(frame_id, str) or not frame_id.strip():
        raise MethodFrameLockError("collection_frame_id is required")
    if method_frame_lock.get("collection_frame_id") != frame_id:
        raise MethodFrameLockError("method_frame_lock collection_frame_id mismatch")

    expected_sha = hashlib.sha256(canonical_json_bytes(method_frame)).hexdigest()
    if method_frame_lock.get("method_frame_sha256") != expected_sha:
        raise MethodFrameLockError("method_frame bytes do not match approved method_frame_sha256")

    approver_reference = method_frame_lock.get("approver_reference")
    if not isinstance(approver_reference, str) or not approver_reference.strip():
        raise MethodFrameLockError("method_frame_lock approver_reference is required")

    approved_at = _parse_ts(method_frame_lock.get("approved_at"), field="method_frame_lock.approved_at")
    collection_started_at = _parse_ts(
        collection_frame.get("collection_started_at"),
        field="collection_frame.collection_started_at",
    )
    if approved_at > collection_started_at:
        raise MethodFrameLockError("method frame was not locked before collection started")

    return {
        "schema_version": "eucons.ai4work_method_frame_lock_control.v0.1",
        "research_id": RESEARCH_ID,
        "stage": "PRE_SYNTHESIS_METHOD_FRAME_LOCK",
        "evidence_class": "CONTROL_ARTIFACT_NOT_EVIDENCE",
        "method_frame_sha256": expected_sha,
        "collection_frame_id": frame_id,
        "approved_before_collection": True,
        "approver_reference_present": True,
        "representativeness_claim_allowed": False,
        "scope_boundary": "PASS proves only that the exact method frame supplied to synthesis was explicitly locked for this collection_frame_id before collection_started_at. It does not prove need, prevalence, causality or representativeness.",
    }
