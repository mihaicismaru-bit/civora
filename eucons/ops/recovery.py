#!/usr/bin/env python3
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import sys

OPS_DIR = Path(__file__).resolve().parent
if str(OPS_DIR) not in sys.path:
    sys.path.insert(0, str(OPS_DIR))

from persistence import digest_json  # noqa: E402

ALLOWED_DOMAINS = {
    "PUBLICATION",
    "LINKEDIN",
    "FACEBOOK",
    "OPPORTUNITY_RECONCILE",
    "OFFER_REPLAY",
}
ALLOWED_STATUSES = {"PENDING", "RUNNING", "FAILED", "SUCCEEDED"}
SIDE_EFFECTING = {"PUBLICATION", "LINKEDIN", "FACEBOOK", "OFFER_REPLAY"}
ACTION_PRIORITY = {
    "HOLD_CORRUPT_STATE": 0,
    "HOLD_DUPLICATE_CONFLICT": 1,
    "DISCARD_ORPHAN_PREPARE": 2,
    "RECONCILE_TO_HOLD": 3,
    "RESUME_AFTER_STALE_LEASE": 4,
    "RETRY": 5,
    "START": 6,
    "HOLD_MISSING_RECEIPT": 7,
    "HOLD_RETRY_EXHAUSTED": 8,
    "HOLD_NON_RETRYABLE": 9,
    "NOOP_ALREADY_DELIVERED": 10,
    "NOOP_COMPLETED": 11,
    "NOOP_ACTIVE_LEASE": 12,
}


def _parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _valid_sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def validate_operation(operation: dict[str, Any]) -> None:
    required = {
        "operation_id",
        "domain",
        "status",
        "input_hash",
        "expected_state_hash",
        "attempt",
        "max_attempts",
        "retryable",
        "lease",
        "orphan_prepare",
    }
    missing = sorted(required - operation.keys())
    if missing:
        raise ValueError(f"missing operation fields: {', '.join(missing)}")
    if not isinstance(operation["operation_id"], str) or not operation["operation_id"].strip():
        raise ValueError("operation_id required")
    if operation["domain"] not in ALLOWED_DOMAINS:
        raise ValueError("unsupported recovery domain")
    if operation["status"] not in ALLOWED_STATUSES:
        raise ValueError("unsupported operation status")
    if not _valid_sha256(operation["input_hash"]):
        raise ValueError("input_hash must be sha256")
    expected = operation["expected_state_hash"]
    if expected is not None and not _valid_sha256(expected):
        raise ValueError("expected_state_hash must be null or sha256")
    if not isinstance(operation["attempt"], int) or operation["attempt"] < 0:
        raise ValueError("attempt must be a non-negative integer")
    if not isinstance(operation["max_attempts"], int) or operation["max_attempts"] < 1:
        raise ValueError("max_attempts must be a positive integer")
    if operation["attempt"] > operation["max_attempts"]:
        raise ValueError("attempt cannot exceed max_attempts")
    if not isinstance(operation["retryable"], bool):
        raise ValueError("retryable must be boolean")
    if not isinstance(operation["orphan_prepare"], bool):
        raise ValueError("orphan_prepare must be boolean")

    lease = operation["lease"]
    if operation["status"] == "RUNNING":
        if not isinstance(lease, dict):
            raise ValueError("RUNNING operation requires lease")
        if not isinstance(lease.get("owner"), str) or not lease["owner"].strip():
            raise ValueError("lease owner required")
        acquired = _parse_time(lease.get("acquired_at"))
        expires = _parse_time(lease.get("expires_at"))
        if expires <= acquired:
            raise ValueError("lease expires_at must be after acquired_at")
    elif lease is not None:
        raise ValueError("non-RUNNING operation cannot retain lease")

    if operation["domain"] == "OPPORTUNITY_RECONCILE":
        if operation.get("object_state") not in {"FRESH", "STALE", "WITHDRAWN"}:
            raise ValueError("opportunity reconciliation requires object_state")
    if operation["domain"] == "OFFER_REPLAY":
        if not isinstance(operation.get("offer_version"), int) or operation["offer_version"] < 1:
            raise ValueError("offer replay requires positive offer_version")


def decide_recovery(
    operation: dict[str, Any],
    *,
    reference_time: str,
    current_state_hash: str | None,
    delivery_receipt_exists: bool,
) -> dict[str, Any]:
    validate_operation(operation)
    now = _parse_time(reference_time)
    if current_state_hash is not None and not _valid_sha256(current_state_hash):
        raise ValueError("current_state_hash must be null or sha256")
    if not isinstance(delivery_receipt_exists, bool):
        raise ValueError("delivery_receipt_exists must be boolean")

    expected = operation["expected_state_hash"]
    if expected != current_state_hash:
        action = "HOLD_CORRUPT_STATE"
        reason = "canonical state hash no longer matches the operation preimage"
    elif operation["orphan_prepare"]:
        action = "DISCARD_ORPHAN_PREPARE"
        reason = "orphan prepared state is discarded and never promoted implicitly"
    elif operation["domain"] in SIDE_EFFECTING and delivery_receipt_exists:
        action = "NOOP_ALREADY_DELIVERED"
        reason = "delivery receipt proves the side effect already happened"
    elif operation["domain"] == "OPPORTUNITY_RECONCILE" and operation["object_state"] in {"STALE", "WITHDRAWN"}:
        action = "RECONCILE_TO_HOLD"
        reason = "stale or withdrawn opportunity must be projected to HOLD"
    elif operation["status"] == "PENDING":
        action = "START"
        reason = "pending operation has a valid canonical preimage"
    elif operation["status"] == "RUNNING":
        expires_at = _parse_time(operation["lease"]["expires_at"])
        if expires_at <= now:
            action = "RESUME_AFTER_STALE_LEASE"
            reason = "lease is stale and canonical preimage is unchanged"
        else:
            action = "NOOP_ACTIVE_LEASE"
            reason = "active lease cannot be stolen"
    elif operation["status"] == "FAILED":
        if not operation["retryable"]:
            action = "HOLD_NON_RETRYABLE"
            reason = "failure is explicitly non-retryable"
        elif operation["attempt"] >= operation["max_attempts"]:
            action = "HOLD_RETRY_EXHAUSTED"
            reason = "retry budget is exhausted"
        else:
            action = "RETRY"
            reason = "retryable failure remains within the attempt budget"
    else:
        if operation["domain"] in SIDE_EFFECTING and not delivery_receipt_exists:
            action = "HOLD_MISSING_RECEIPT"
            reason = "side-effecting success without a delivery receipt is ambiguous"
        else:
            action = "NOOP_COMPLETED"
            reason = "completed non-side-effecting operation requires no recovery"

    return {
        "operation_id": operation["operation_id"],
        "domain": operation["domain"],
        "input_hash": operation["input_hash"],
        "action": action,
        "reason": reason,
        "attempt": operation["attempt"],
        "max_attempts": operation["max_attempts"],
    }


def build_recovery_plan(
    operations: list[dict[str, Any]],
    *,
    reference_time: str,
    current_state_hashes: dict[str, str | None],
    delivered_operation_ids: set[str] | None = None,
) -> dict[str, Any]:
    delivered = delivered_operation_ids or set()
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for operation in operations:
        validate_operation(operation)
        grouped[operation["operation_id"]].append(operation)

    decisions: list[dict[str, Any]] = []
    for operation_id in sorted(grouped):
        candidates = grouped[operation_id]
        input_hashes = {row["input_hash"] for row in candidates}
        if len(input_hashes) != 1:
            decisions.append({
                "operation_id": operation_id,
                "domain": sorted(row["domain"] for row in candidates)[0],
                "input_hash": None,
                "action": "HOLD_DUPLICATE_CONFLICT",
                "reason": "same operation_id is bound to multiple input hashes",
                "attempt": max(row["attempt"] for row in candidates),
                "max_attempts": max(row["max_attempts"] for row in candidates),
                "duplicate_count": len(candidates),
            })
            continue

        canonical = sorted(
            candidates,
            key=lambda row: (
                row["attempt"],
                row["status"],
                digest_json(row),
            ),
            reverse=True,
        )[0]
        decision = decide_recovery(
            canonical,
            reference_time=reference_time,
            current_state_hash=current_state_hashes.get(operation_id),
            delivery_receipt_exists=operation_id in delivered,
        )
        decision["duplicate_count"] = len(candidates)
        decisions.append(decision)

    decisions.sort(key=lambda row: (ACTION_PRIORITY[row["action"]], row["operation_id"]))
    plan = {
        "engine_id": "EUCONS_E24_RECOVERY",
        "reference_time": reference_time,
        "decision_count": len(decisions),
        "decisions": decisions,
    }
    plan["plan_hash"] = digest_json(plan)
    return plan


def rollback_plan(receipts: list[dict[str, Any]], *, current_state_hash: str) -> dict[str, Any]:
    if not _valid_sha256(current_state_hash):
        raise ValueError("current_state_hash must be sha256")
    if not receipts:
        raise ValueError("rollback requires receipt lineage")

    ordered = sorted(receipts, key=lambda row: row.get("version", 0))
    previous_postimage: str | None = None
    for index, receipt in enumerate(ordered):
        required = {"version", "preimage_hash", "postimage_hash", "committed"}
        if not required.issubset(receipt):
            raise ValueError("receipt lineage incomplete")
        if receipt["version"] != index + 1:
            raise ValueError("receipt versions must be contiguous from 1")
        if receipt["committed"] is not True:
            raise ValueError("rollback lineage cannot contain uncommitted receipt")
        if not _valid_sha256(receipt["postimage_hash"]):
            raise ValueError("receipt postimage hash invalid")
        preimage = receipt["preimage_hash"]
        if preimage is not None and not _valid_sha256(preimage):
            raise ValueError("receipt preimage hash invalid")
        if index == 0:
            if preimage is not None:
                raise ValueError("first receipt must have null preimage")
        elif preimage != previous_postimage:
            raise ValueError("receipt lineage is disconnected")
        previous_postimage = receipt["postimage_hash"]

    current = next((row for row in reversed(ordered) if row["postimage_hash"] == current_state_hash), None)
    if current is None:
        raise ValueError("current state hash absent from receipt lineage")
    if current["preimage_hash"] is None:
        raise ValueError("cannot infer rollback before first committed state")

    result = {
        "engine_id": "EUCONS_E24_RECOVERY",
        "action": "ROLLBACK_TO_PREIMAGE",
        "from_version": current["version"],
        "to_version": current["version"] - 1,
        "current_state_hash": current_state_hash,
        "target_state_hash": current["preimage_hash"],
    }
    result["plan_hash"] = digest_json(result)
    return result
