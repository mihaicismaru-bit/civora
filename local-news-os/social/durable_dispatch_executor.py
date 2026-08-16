#!/usr/bin/env python3
"""Crash-safe durable dispatch executor for LOCAL NEWS OS social publications.

The executor begins where ``adapter_dispatch_bridge`` ends. It accepts only a
validated DIRECT_READY handoff, persists a channel-local PUBLISHING claim before
an adapter may touch the network, and reconciles the sanitized outcome through
the canonical publication-state retry policy. An ambiguous crash never causes a
blind resend: expired PUBLISHING claims require explicit remote reconciliation.

The module is dependency-free beyond the LOCAL NEWS OS core. It never accepts
credential values, never selects a different adapter than the handoff declares,
and preserves instance/channel isolation plus zero-paid-dependency.
"""
from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Any, Callable

import publication_state

SCHEMA_VERSION = "1.0"
DEFAULT_LEASE_SECONDS = 300
MAX_LEASE_SECONDS = 3600
REFERENCE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
SECRET_PREFIXES = ("eaa", "eyj", "ghp_", "github_pat_", "sk-")
RESULT_FIELDS = {
    "success", "remote_publication_id", "http_status", "error_class",
    "error_code", "retry_after_seconds", "adapter", "handoff_id",
    "publication_id",
}
FORBIDDEN_RESULT_KEY_PARTS = (
    "token", "secret", "password", "authorization", "api_key", "apikey",
    "cookie", "headers", "raw_response", "response_body",
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform(value: Any) -> str:
    return _clean(value).lower().replace("-", "_")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _parse_time(value: str) -> datetime:
    text = _clean(value)
    if not text:
        raise ValueError("timestamp is required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_adapter_path(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    path = PurePosixPath(text)
    return not path.is_absolute() and ".." not in path.parts and path.suffix == ".py"


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(state)
    result.pop("state_fingerprint_sha256", None)
    result["state_fingerprint_sha256"] = _digest(result)
    return result


def _fingerprint_ok(state: dict[str, Any]) -> bool:
    supplied = _clean(state.get("state_fingerprint_sha256"))
    if not _is_sha256(supplied):
        return False
    candidate = copy.deepcopy(state)
    candidate.pop("state_fingerprint_sha256", None)
    return supplied == _digest(candidate)


def _handoff(state: dict[str, Any]) -> dict[str, Any] | None:
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
    item = items.get(_clean(state.get("handoff_id")))
    return item if isinstance(item, dict) else None


def _record(state: dict[str, Any]) -> dict[str, Any] | None:
    item = _handoff(state)
    if item is None:
        return None
    ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    value = records.get(_clean(item.get("publication_id")))
    return value if isinstance(value, dict) else None


def _blocked(state: dict[str, Any] | None, reasons: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": True,
        "hard_blocks": sorted(set(reasons)),
        "decision": "BLOCKED",
        "state": copy.deepcopy(state) if isinstance(state, dict) else None,
        "adapter_invoked": False,
    }


def _validate_reference_names(item: dict[str, Any]) -> list[str]:
    refs = item.get("credential_reference_names")
    if not isinstance(refs, list):
        return ["CREDENTIAL_REFERENCE_NAMES_INVALID"]
    blocks: list[str] = []
    for value in refs:
        text = _clean(value)
        if not REFERENCE_RE.fullmatch(text) or text.lower().startswith(SECRET_PREFIXES):
            blocks.append("CREDENTIAL_REFERENCE_NOT_NAME")
    if item.get("credential_values_included") is not False:
        blocks.append("CREDENTIAL_VALUES_INCLUDED")
    return blocks


def _validate_state(state: dict[str, Any]) -> list[str]:
    if not isinstance(state, dict):
        return ["STATE_NOT_MAPPING"]
    blocks: list[str] = []
    if _clean(state.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("STATE_SCHEMA_VERSION")
    if not _fingerprint_ok(state):
        blocks.append("STATE_FINGERPRINT_INVALID")

    instance_id = _clean(state.get("instance_id"))
    channel_id = _clean(state.get("channel_id"))
    platform = _platform(state.get("platform"))
    handoff_id = _clean(state.get("handoff_id"))
    if not instance_id or not channel_id or not platform or not handoff_id:
        blocks.append("STATE_IDENTITY_INCOMPLETE")
    if not _is_sha256(state.get("source_bridge_bundle_fingerprint_sha256")):
        blocks.append("SOURCE_BRIDGE_FINGERPRINT_INVALID")
    if not isinstance(state.get("revision"), int) or int(state.get("revision", -1)) < 0:
        blocks.append("INVALID_REVISION")

    guards = state.get("guards") if isinstance(state.get("guards"), dict) else {}
    expected_guards = {
        "atomic_compare_and_swap_required": True,
        "credential_values_read": False,
        "credential_values_exposed": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "zero_paid_dependency": True,
    }
    for key, expected in expected_guards.items():
        if guards.get(key) is not expected:
            blocks.append({
                "atomic_compare_and_swap_required": "ATOMIC_COMPARE_AND_SWAP_REQUIRED",
                "credential_values_read": "CREDENTIAL_VALUES_READ",
                "credential_values_exposed": "CREDENTIAL_VALUES_EXPOSED",
                "verbatim_cross_platform_reuse_allowed": "VERBATIM_CROSS_PLATFORM_REUSE",
                "zero_paid_dependency": "ZERO_PAID_DEPENDENCY_VIOLATION",
            }[key])

    ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    for prefix, container in (("LEDGER", ledger), ("OUTBOX", outbox)):
        if _clean(container.get("instance_id")) != instance_id:
            blocks.append(f"{prefix}_INSTANCE_MISMATCH")
        if _clean(container.get("channel_id")) != channel_id:
            blocks.append(f"{prefix}_CHANNEL_MISMATCH")
        if _platform(container.get("platform")) != platform:
            blocks.append(f"{prefix}_PLATFORM_MISMATCH")

    item = _handoff(state)
    if item is None:
        return sorted(set(blocks + ["HANDOFF_ITEM_MISSING"]))
    if _clean(item.get("handoff_id")) != handoff_id:
        blocks.append("HANDOFF_ID_MISMATCH")
    if _clean(item.get("instance_id")) != instance_id:
        blocks.append("HANDOFF_INSTANCE_MISMATCH")
    if _clean(item.get("channel_id")) != channel_id:
        blocks.append("HANDOFF_CHANNEL_MISMATCH")
    if _platform(item.get("platform")) != platform:
        blocks.append("HANDOFF_PLATFORM_MISMATCH")
    if _clean(item.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_NOT_DIRECT_READY")
    if not _safe_adapter_path(item.get("adapter")):
        blocks.append("INVALID_ADAPTER_PATH")
    if item.get("network_dispatch_performed") is not False:
        blocks.append("HANDOFF_ALREADY_DISPATCHED")
    blocks.extend(_validate_reference_names(item))

    supplied_handoff_fp = _clean(item.get("handoff_fingerprint_sha256"))
    handoff_payload = copy.deepcopy(item)
    handoff_payload.pop("handoff_fingerprint_sha256", None)
    if not _is_sha256(supplied_handoff_fp) or supplied_handoff_fp != _digest(handoff_payload):
        blocks.append("HANDOFF_FINGERPRINT_INVALID")

    payload = item.get("adapter_payload") if isinstance(item.get("adapter_payload"), dict) else {}
    supplied_payload_fp = _clean(item.get("adapter_payload_fingerprint_sha256"))
    if not payload or not _is_sha256(supplied_payload_fp) or supplied_payload_fp != _digest(payload):
        blocks.append("ADAPTER_PAYLOAD_FINGERPRINT_INVALID")
    else:
        if _clean(payload.get("instance_id")) != instance_id:
            blocks.append("PAYLOAD_INSTANCE_MISMATCH")
        if _clean(payload.get("channel_id")) != channel_id:
            blocks.append("PAYLOAD_CHANNEL_MISMATCH")
        if _platform(payload.get("platform")) != platform:
            blocks.append("PAYLOAD_PLATFORM_MISMATCH")
        if _clean(payload.get("publication_id")) != _clean(item.get("publication_id")):
            blocks.append("PAYLOAD_PUBLICATION_MISMATCH")

    record = _record(state)
    if record is None:
        blocks.append("PUBLICATION_RECORD_MISSING")
    else:
        if _clean(record.get("publication_id")) != _clean(item.get("publication_id")):
            blocks.append("RECORD_PUBLICATION_MISMATCH")
        if _clean(record.get("instance_id")) != instance_id:
            blocks.append("RECORD_INSTANCE_MISMATCH")
        if _clean(record.get("channel_id")) != channel_id:
            blocks.append("RECORD_CHANNEL_MISMATCH")
        if _platform(record.get("platform")) != platform:
            blocks.append("RECORD_PLATFORM_MISMATCH")
        if _clean(record.get("product_id")) != _clean(item.get("product_id")):
            blocks.append("RECORD_PRODUCT_MISMATCH")
        if record.get("remote_publication_id") and _clean(record.get("status")) != "PUBLISHED":
            blocks.append("REMOTE_ID_WITHOUT_PUBLISHED_STATE")
    return sorted(set(blocks))


def initialize_dispatch_state(bridge_result: dict[str, Any]) -> dict[str, Any]:
    """Initialize executor state from one real Adapter-Gated Dispatch Bridge result."""
    if not isinstance(bridge_result, dict):
        raise TypeError("bridge_result must be a mapping")
    blocks: list[str] = []
    if bridge_result.get("blocked") is True:
        blocks.append("BRIDGE_BLOCKED")
    if _clean(bridge_result.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("BRIDGE_NOT_DIRECT_READY")

    handoff_meta = bridge_result.get("adapter_handoff") if isinstance(bridge_result.get("adapter_handoff"), dict) else {}
    if handoff_meta.get("dispatch_allowed") is not True:
        blocks.append("BRIDGE_DISPATCH_NOT_ALLOWED")
    if handoff_meta.get("credential_values_exposed") is not False:
        blocks.append("BRIDGE_CREDENTIAL_VALUES_EXPOSED")

    guards = bridge_result.get("guards") if isinstance(bridge_result.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("BRIDGE_ZERO_PAID_DEPENDENCY_VIOLATION")
    if guards.get("credential_values_read") is not False or guards.get("credential_values_exposed") is not False:
        blocks.append("BRIDGE_CREDENTIAL_POLICY_VIOLATION")
    if guards.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("BRIDGE_VERBATIM_REUSE")

    bundle = bridge_result.get("commit_bundle") if isinstance(bridge_result.get("commit_bundle"), dict) else {}
    bundle_fp = _clean(bridge_result.get("bundle_fingerprint_sha256"))
    if not bundle:
        blocks.append("MISSING_BRIDGE_COMMIT_BUNDLE")
    elif not _is_sha256(bundle_fp) or bundle_fp != _digest(bundle):
        blocks.append("BRIDGE_BUNDLE_FINGERPRINT_INVALID")
    if bundle:
        if bundle.get("atomic_persist_required") is not True:
            blocks.append("BRIDGE_ATOMIC_PERSIST_REQUIRED")
        if bundle.get("network_dispatch_performed") is not False:
            blocks.append("BRIDGE_NETWORK_ALREADY_PERFORMED")
        for key in ("instance_id", "channel_id", "platform"):
            left = _platform(bundle.get(key)) if key == "platform" else _clean(bundle.get(key))
            right = _platform(bridge_result.get(key)) if key == "platform" else _clean(bridge_result.get(key))
            if left != right:
                blocks.append(f"BRIDGE_BUNDLE_{key.upper()}_MISMATCH")
        if _clean(bundle.get("handoff_id")) != _clean(handoff_meta.get("handoff_id")):
            blocks.append("BRIDGE_BUNDLE_HANDOFF_ID_MISMATCH")

    if blocks:
        return _blocked(None, blocks)
    state = _seal_state({
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(bundle.get("instance_id")),
        "channel_id": _clean(bundle.get("channel_id")),
        "platform": _platform(bundle.get("platform")),
        "handoff_id": _clean(bundle.get("handoff_id")),
        "source_bridge_bundle_fingerprint_sha256": bundle_fp,
        "revision": 0,
        "ledger": copy.deepcopy(bundle.get("ledger")),
        "outbox": copy.deepcopy(bundle.get("outbox")),
        "guards": {
            "atomic_compare_and_swap_required": True,
            "claim_persisted_before_adapter_required": True,
            "ambiguous_crash_requires_remote_reconciliation": True,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    })
    state_blocks = _validate_state(state)
    current = _record(state)
    if current is not None and _clean(current.get("status")) != "READY":
        state_blocks.append("INITIAL_PUBLICATION_NOT_READY")
    if state_blocks:
        return _blocked(state, state_blocks)
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "DISPATCH_STATE_INITIALIZED",
        "state": state,
        "adapter_invoked": False,
    }


def _lease(record: dict[str, Any], now: datetime) -> tuple[str, dict[str, Any] | None]:
    execution = record.get("dispatch_execution") if isinstance(record.get("dispatch_execution"), dict) else None
    if execution is None or _clean(execution.get("status")) != "ACTIVE":
        return "INVALID", execution
    try:
        expires = _parse_time(_clean(execution.get("lease_expires_at")))
    except (TypeError, ValueError):
        return "INVALID", execution
    return ("ACTIVE" if now < expires else "EXPIRED"), execution


def claim_dispatch(state: dict[str, Any], now: str, worker_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
    """Create a PUBLISHING claim candidate; caller must CAS-persist it before dispatch."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    if not _clean(worker_id):
        raise ValueError("worker_id is required")
    if lease_seconds < 30 or lease_seconds > MAX_LEASE_SECONDS:
        raise ValueError("lease_seconds must be between 30 and 3600")
    current_time = _parse_time(now)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    item = _handoff(state)
    current_record = _record(state)
    assert item is not None and current_record is not None
    status = _clean(current_record.get("status"))

    if status == "PUBLISHED":
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "ALREADY_PUBLISHED", "state": copy.deepcopy(state), "adapter_invoked": False, "adapter_invocation": None}
    if status == "PUBLISHING":
        lease_status, execution = _lease(current_record, current_time)
        if lease_status == "ACTIVE":
            return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "LEASE_HELD", "state": copy.deepcopy(state), "active_worker_id": _clean((execution or {}).get("worker_id")) or None, "lease_expires_at": _clean((execution or {}).get("lease_expires_at")) or None, "adapter_invoked": False, "adapter_invocation": None}
        if lease_status == "EXPIRED":
            return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "RECONCILIATION_REQUIRED", "reason": "PUBLISHING_LEASE_EXPIRED_REMOTE_STATE_UNKNOWN", "state": copy.deepcopy(state), "adapter_invoked": False, "adapter_invocation": None}
        return _blocked(state, ["INVALID_PUBLISHING_LEASE"])

    working = copy.deepcopy(state)
    if status == "RETRY_WAIT":
        released = publication_state.release_retry(working["ledger"], _clean(item.get("publication_id")), _iso(current_time))
        if released.get("blocked") is True:
            return _blocked(state, [str(v) for v in released.get("hard_blocks", [])])
        if _clean(released.get("decision")) == "RETRY_NOT_DUE":
            return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "RETRY_NOT_DUE", "state": copy.deepcopy(state), "next_attempt_at": _clean(current_record.get("next_attempt_at")) or None, "adapter_invoked": False, "adapter_invocation": None}
        working["ledger"] = released["ledger"]
        current_record = _record(working)
        assert current_record is not None
        status = _clean(current_record.get("status"))
    if status not in {"READY", "RETRY_READY"}:
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "NOT_DISPATCHABLE", "publication_status": status, "state": copy.deepcopy(state), "adapter_invoked": False, "adapter_invocation": None}

    expected_fp = _clean(state.get("state_fingerprint_sha256"))
    claimed_at = _iso(current_time)
    claim_token = "claim:" + _digest({
        "handoff_id": _clean(state.get("handoff_id")),
        "publication_id": _clean(item.get("publication_id")),
        "worker_id": _clean(worker_id),
        "claimed_at": claimed_at,
        "expected_state_fingerprint_sha256": expected_fp,
    })[:32]
    candidate_record = _record(working)
    assert candidate_record is not None
    pre_status = _clean(candidate_record.get("status"))
    candidate_record["status"] = "PUBLISHING"
    candidate_record["state_reason"] = "DURABLE_DISPATCH_CLAIMED"
    candidate_record["dispatch_execution"] = {
        "status": "ACTIVE",
        "handoff_id": _clean(state.get("handoff_id")),
        "claim_token": claim_token,
        "worker_id": _clean(worker_id),
        "claimed_at": claimed_at,
        "lease_expires_at": _iso(current_time + timedelta(seconds=lease_seconds)),
        "pre_claim_status": pre_status,
        "credential_values_included": False,
    }
    working["revision"] = int(working.get("revision", 0)) + 1
    working = _seal_state(working)
    invocation = {
        "handoff_id": _clean(state.get("handoff_id")),
        "publication_id": _clean(item.get("publication_id")),
        "claim_token": claim_token,
        "adapter": _clean(item.get("adapter")),
        "adapter_payload": copy.deepcopy(item.get("adapter_payload")),
        "adapter_payload_fingerprint_sha256": _clean(item.get("adapter_payload_fingerprint_sha256")),
        "credential_reference_names": copy.deepcopy(item.get("credential_reference_names")),
        "credential_values_included": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "CLAIMED",
        "state": working,
        "claim_token": claim_token,
        "expected_previous_state_fingerprint_sha256": expected_fp,
        "claimed_state_fingerprint_sha256": _clean(working.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "persist_before_adapter_required": True,
        "adapter_invoked": False,
        "adapter_invocation": invocation,
    }


def _result_blocks(result: dict[str, Any], item: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    unknown = sorted(set(result) - RESULT_FIELDS)
    if unknown:
        blocks.append("ADAPTER_RESULT_UNKNOWN_FIELDS:" + ",".join(unknown))
    if any(any(part in _clean(key).lower() for part in FORBIDDEN_RESULT_KEY_PARTS) for key in result):
        blocks.append("ADAPTER_RESULT_SECRET_OR_RAW_FIELD")
    if not isinstance(result.get("success"), bool):
        blocks.append("ADAPTER_RESULT_SUCCESS_MUST_BE_BOOL")
    if result.get("adapter") is not None and _clean(result.get("adapter")) != _clean(item.get("adapter")):
        blocks.append("ADAPTER_RESULT_ADAPTER_MISMATCH")
    if result.get("handoff_id") is not None and _clean(result.get("handoff_id")) != _clean(item.get("handoff_id")):
        blocks.append("ADAPTER_RESULT_HANDOFF_MISMATCH")
    if result.get("publication_id") is not None and _clean(result.get("publication_id")) != _clean(item.get("publication_id")):
        blocks.append("ADAPTER_RESULT_PUBLICATION_MISMATCH")
    http_status = result.get("http_status")
    if http_status is not None and (not isinstance(http_status, int) or isinstance(http_status, bool) or not 100 <= http_status <= 599):
        blocks.append("ADAPTER_RESULT_HTTP_STATUS_INVALID")
    retry_after = result.get("retry_after_seconds")
    if retry_after is not None and (not isinstance(retry_after, int) or isinstance(retry_after, bool) or retry_after < 0):
        blocks.append("ADAPTER_RESULT_RETRY_AFTER_INVALID")
    if result.get("success") is True and not _clean(result.get("remote_publication_id")):
        blocks.append("ADAPTER_SUCCESS_MISSING_REMOTE_PUBLICATION_ID")
    return sorted(set(blocks))


def _finish_execution(record: dict[str, Any], execution: dict[str, Any], decision: str, completed_at: str, *, recovery: bool = False) -> None:
    history = record.setdefault("dispatch_history", [])
    if not isinstance(history, list):
        history = []
        record["dispatch_history"] = history
    history.append({
        "handoff_id": _clean(execution.get("handoff_id")),
        "claim_token": _clean(execution.get("claim_token")),
        "worker_id": _clean(execution.get("worker_id")),
        "claimed_at": _clean(execution.get("claimed_at")),
        "lease_expires_at": _clean(execution.get("lease_expires_at")),
        "completed_at": completed_at,
        "decision": decision,
        "crash_recovery": recovery is True,
        "credential_values_included": False,
    })
    record.pop("dispatch_execution", None)


def reconcile_adapter_result(
    state: dict[str, Any], claim_token: str, attempted_at: str, adapter_result: dict[str, Any], *,
    max_attempts: int = 5, base_delay_seconds: int = 60, max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Apply one sanitized adapter result to the active PUBLISHING claim."""
    if not isinstance(state, dict) or not isinstance(adapter_result, dict):
        raise TypeError("state and adapter_result must be mappings")
    when = _parse_time(attempted_at)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    item = _handoff(state)
    current_record = _record(state)
    assert item is not None and current_record is not None
    if _clean(current_record.get("status")) != "PUBLISHING":
        return _blocked(state, ["PUBLICATION_NOT_PUBLISHING"])
    execution = current_record.get("dispatch_execution") if isinstance(current_record.get("dispatch_execution"), dict) else {}
    if _clean(execution.get("status")) != "ACTIVE":
        return _blocked(state, ["ACTIVE_DISPATCH_EXECUTION_MISSING"])
    if _clean(execution.get("claim_token")) != _clean(claim_token):
        return _blocked(state, ["CLAIM_TOKEN_MISMATCH"])

    result_blocks = _result_blocks(adapter_result, item)
    if result_blocks:
        if adapter_result.get("success") is True and "ADAPTER_SUCCESS_MISSING_REMOTE_PUBLICATION_ID" in result_blocks:
            return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": result_blocks, "decision": "RECONCILIATION_REQUIRED", "reason": "ADAPTER_REPORTED_SUCCESS_WITHOUT_REMOTE_PROOF", "state": copy.deepcopy(state), "adapter_invoked": True}
        return _blocked(state, result_blocks)

    ledger = copy.deepcopy(state["ledger"])
    publication_id = _clean(item.get("publication_id"))
    candidate_record = ledger["records"][publication_id]
    pre_status = _clean(execution.get("pre_claim_status"))
    if pre_status not in {"READY", "RETRY_READY"}:
        return _blocked(state, ["INVALID_PRE_CLAIM_STATUS"])
    candidate_record["status"] = pre_status
    outcome = publication_state.apply_attempt(
        ledger, publication_id, _iso(when),
        success=adapter_result.get("success") is True,
        remote_publication_id=_clean(adapter_result.get("remote_publication_id")) or None,
        http_status=adapter_result.get("http_status"),
        error_class=_clean(adapter_result.get("error_class")) or None,
        error_code=_clean(adapter_result.get("error_code")) or None,
        retry_after_seconds=adapter_result.get("retry_after_seconds"),
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    if outcome.get("blocked") is True:
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [str(v) for v in outcome.get("hard_blocks", [])], "decision": "RECONCILIATION_REQUIRED", "reason": "PUBLICATION_STATE_REJECTED_ADAPTER_OUTCOME", "state": copy.deepcopy(state), "adapter_invoked": True}

    candidate = copy.deepcopy(state)
    candidate["ledger"] = outcome["ledger"]
    final_record = _record(candidate)
    assert final_record is not None
    _finish_execution(final_record, execution, _clean(outcome.get("decision")), _iso(when))
    candidate["revision"] = int(candidate.get("revision", 0)) + 1
    candidate = _seal_state(candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": _clean(outcome.get("decision")),
        "publication_status": _clean(final_record.get("status")),
        "record": copy.deepcopy(final_record),
        "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "adapter_invoked": True,
    }


def recover_stale_claim(state: dict[str, Any], now: str, *, remote_publication_id: str | None = None, remote_absent_confirmed: bool = False) -> dict[str, Any]:
    """Resolve an expired PUBLISHING lease only with explicit remote evidence."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    current_time = _parse_time(now)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    if _clean(remote_publication_id) and remote_absent_confirmed is True:
        return _blocked(state, ["CONTRADICTORY_REMOTE_RECONCILIATION"])
    current_record = _record(state)
    item = _handoff(state)
    assert current_record is not None and item is not None
    if _clean(current_record.get("status")) != "PUBLISHING":
        return _blocked(state, ["PUBLICATION_NOT_PUBLISHING"])
    lease_status, execution = _lease(current_record, current_time)
    if lease_status == "ACTIVE":
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "LEASE_HELD", "state": copy.deepcopy(state), "adapter_invoked": False}
    if lease_status != "EXPIRED" or execution is None:
        return _blocked(state, ["INVALID_PUBLISHING_LEASE"])
    remote_id = _clean(remote_publication_id)
    if not remote_id and remote_absent_confirmed is not True:
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "RECONCILIATION_REQUIRED", "reason": "REMOTE_STATE_MUST_BE_CHECKED_BEFORE_RETRY", "state": copy.deepcopy(state), "adapter_invoked": False}

    candidate = copy.deepcopy(state)
    publication_id = _clean(item.get("publication_id"))
    if remote_id:
        ledger = copy.deepcopy(candidate["ledger"])
        ledger_record = ledger["records"][publication_id]
        pre_status = _clean(execution.get("pre_claim_status"))
        ledger_record["status"] = pre_status if pre_status in {"READY", "RETRY_READY"} else "READY"
        outcome = publication_state.apply_attempt(ledger, publication_id, _iso(current_time), success=True, remote_publication_id=remote_id)
        if outcome.get("blocked") is True:
            return _blocked(state, ["REMOTE_RECONCILIATION_FAILED"] + [str(v) for v in outcome.get("hard_blocks", [])])
        candidate["ledger"] = outcome["ledger"]
        final_record = _record(candidate)
        assert final_record is not None
        _finish_execution(final_record, execution, "PUBLISHED_AFTER_CRASH_RECONCILIATION", _iso(current_time), recovery=True)
        decision = "PUBLISHED_AFTER_CRASH_RECONCILIATION"
    else:
        final_record = _record(candidate)
        assert final_record is not None
        final_record["status"] = "RETRY_READY"
        final_record["state_reason"] = "CRASH_RECONCILED_REMOTE_ABSENT"
        final_record["next_attempt_at"] = None
        _finish_execution(final_record, execution, "REQUEUED_AFTER_REMOTE_ABSENT", _iso(current_time), recovery=True)
        decision = "REQUEUED_AFTER_REMOTE_ABSENT"

    candidate["revision"] = int(candidate.get("revision", 0)) + 1
    candidate = _seal_state(candidate)
    final_record = _record(candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "publication_status": _clean((final_record or {}).get("status")),
        "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "adapter_invoked": False,
    }


def execute_dispatch(
    state: dict[str, Any], now: str, worker_id: str, *,
    persist_claim: Callable[[str, dict[str, Any]], bool],
    invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_result: Callable[[str, dict[str, Any]], bool] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Persist claim, invoke exact adapter, then CAS-persist reconciled result."""
    if not callable(persist_claim) or not callable(invoke_adapter):
        raise TypeError("persist_claim and invoke_adapter must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable when provided")
    claim = claim_dispatch(state, now, worker_id, lease_seconds=lease_seconds)
    if claim.get("blocked") is True or _clean(claim.get("decision")) != "CLAIMED":
        return claim

    try:
        claim_persisted = persist_claim(
            _clean(claim.get("expected_previous_state_fingerprint_sha256")),
            copy.deepcopy(claim["state"]),
        ) is True
    except Exception:
        claim_persisted = False
    if not claim_persisted:
        return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "CLAIM_PERSIST_CONFLICT", "reason": "ADAPTER_NOT_INVOKED_BECAUSE_PUBLISHING_CLAIM_WAS_NOT_DURABLE", "state": copy.deepcopy(state), "adapter_invoked": False}

    claimed_state = claim["state"]
    try:
        adapter_result = invoke_adapter(copy.deepcopy(claim["adapter_invocation"]))
        if not isinstance(adapter_result, dict):
            adapter_result = {"success": False, "error_class": "transient", "error_code": "ADAPTER_RESULT_NOT_MAPPING"}
    except Exception as exc:
        adapter_result = {"success": False, "error_class": "network_error", "error_code": "ADAPTER_EXCEPTION_" + type(exc).__name__.upper()}

    reconciled = reconcile_adapter_result(
        claimed_state, _clean(claim.get("claim_token")), now, adapter_result,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    if reconciled.get("blocked") is True or _clean(reconciled.get("decision")) == "RECONCILIATION_REQUIRED":
        reconciled["adapter_invoked"] = True
        return reconciled

    if persist_result is not None:
        try:
            result_persisted = persist_result(
                _clean(claimed_state.get("state_fingerprint_sha256")),
                copy.deepcopy(reconciled["state"]),
            ) is True
        except Exception:
            result_persisted = False
        if not result_persisted:
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": [],
                "decision": "RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED",
                "reason": "ADAPTER_ALREADY_INVOKED_DURABLE_STATE_REMAINS_PUBLISHING",
                "state": copy.deepcopy(claimed_state),
                "candidate_result_state_fingerprint_sha256": _clean(reconciled.get("result_state_fingerprint_sha256")),
                "adapter_invoked": True,
            }
    reconciled["adapter_invoked"] = True
    reconciled["claim_persisted_before_adapter"] = True
    reconciled["result_persisted"] = persist_result is not None
    return reconciled
