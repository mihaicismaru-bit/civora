#!/usr/bin/env python3
"""Durable, crash-safe dispatch executor for LOCAL NEWS OS social publications.

This module consumes only DIRECT_READY handoffs emitted by ``adapter_dispatch_bridge``.
It owns the durable execution protocol around an existing native adapter, not the
platform API itself:

1. validate the immutable handoff and its fingerprints;
2. claim the publication with an atomic compare-and-swap transition to PUBLISHING;
3. persist that claim *before* the adapter callback may perform a network request;
4. reconcile the sanitized adapter result through the canonical publication-state
   retry policy and require a remote publication id before claiming success;
5. stop automatic re-dispatch after an ambiguous crash until remote state has been
   explicitly reconciled.

Credential values are never accepted by this contract. Adapter paths and native
payloads come from the validated handoff; a caller cannot substitute a different
adapter or cross-post another channel's product. Persistence and adapter invocation
are injected callbacks so the core stays dependency-free and testable.
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
SECRET_LIKE_PREFIXES = ("eaa", "eyj", "ghp_", "github_pat_", "sk-")
RESULT_ALLOWED_FIELDS = {
    "success",
    "remote_publication_id",
    "http_status",
    "error_class",
    "error_code",
    "retry_after_seconds",
    "adapter",
    "handoff_id",
    "publication_id",
}
RESULT_FORBIDDEN_KEY_PARTS = (
    "token",
    "secret",
    "password",
    "authorization",
    "api_key",
    "apikey",
    "cookie",
    "raw_response",
    "response_body",
    "headers",
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform_key(value: Any) -> str:
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


def _safe_repo_path(value: Any) -> bool:
    text = _clean(value)
    if not text:
        return False
    path = PurePosixPath(text)
    return not path.is_absolute() and ".." not in path.parts and path.suffix == ".py"


def _seal_state(state: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(state)
    state.pop("state_fingerprint_sha256", None)
    state["state_fingerprint_sha256"] = _digest(state)
    return state


def _state_fingerprint_valid(state: dict[str, Any]) -> bool:
    supplied = _clean(state.get("state_fingerprint_sha256"))
    if not _is_sha256(supplied):
        return False
    payload = copy.deepcopy(state)
    payload.pop("state_fingerprint_sha256", None)
    return supplied == _digest(payload)


def _item_without_fingerprint(item: dict[str, Any]) -> dict[str, Any]:
    payload = copy.deepcopy(item)
    payload.pop("handoff_fingerprint_sha256", None)
    return payload


def _handoff_item(state: dict[str, Any]) -> dict[str, Any] | None:
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
    item = items.get(_clean(state.get("handoff_id")))
    return item if isinstance(item, dict) else None


def _record(state: dict[str, Any]) -> dict[str, Any] | None:
    item = _handoff_item(state)
    if item is None:
        return None
    ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    record = records.get(_clean(item.get("publication_id")))
    return record if isinstance(record, dict) else None


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
    blocks: list[str] = []
    refs = item.get("credential_reference_names")
    if not isinstance(refs, list):
        return ["CREDENTIAL_REFERENCE_NAMES_INVALID"]
    for raw in refs:
        text = _clean(raw)
        lowered = text.lower()
        if not REFERENCE_RE.fullmatch(text) or lowered.startswith(SECRET_LIKE_PREFIXES):
            blocks.append("CREDENTIAL_REFERENCE_NOT_NAME")
    if item.get("credential_values_included") is not False:
        blocks.append("CREDENTIAL_VALUES_INCLUDED")
    return sorted(set(blocks))


def _validate_state(state: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if not isinstance(state, dict):
        return ["STATE_NOT_MAPPING"]
    if _clean(state.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("STATE_SCHEMA_VERSION")
    if not _state_fingerprint_valid(state):
        blocks.append("STATE_FINGERPRINT_INVALID")

    instance_id = _clean(state.get("instance_id"))
    channel_id = _clean(state.get("channel_id"))
    platform = _platform_key(state.get("platform"))
    handoff_id = _clean(state.get("handoff_id"))
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not platform:
        blocks.append("MISSING_PLATFORM")
    if not handoff_id:
        blocks.append("MISSING_HANDOFF_ID")
    if not _is_sha256(state.get("source_bridge_bundle_fingerprint_sha256")):
        blocks.append("SOURCE_BRIDGE_FINGERPRINT_INVALID")
    if not isinstance(state.get("revision"), int) or int(state.get("revision", -1)) < 0:
        blocks.append("INVALID_REVISION")

    guards = state.get("guards") if isinstance(state.get("guards"), dict) else {}
    if guards.get("atomic_compare_and_swap_required") is not True:
        blocks.append("ATOMIC_COMPARE_AND_SWAP_REQUIRED")
    if guards.get("credential_values_read") is not False:
        blocks.append("CREDENTIAL_VALUES_READ")
    if guards.get("credential_values_exposed") is not False:
        blocks.append("CREDENTIAL_VALUES_EXPOSED")
    if guards.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")

    ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    if _clean(ledger.get("instance_id")) != instance_id:
        blocks.append("LEDGER_INSTANCE_MISMATCH")
    if _clean(ledger.get("channel_id")) != channel_id:
        blocks.append("LEDGER_CHANNEL_MISMATCH")
    if _platform_key(ledger.get("platform")) != platform:
        blocks.append("LEDGER_PLATFORM_MISMATCH")
    if _clean(outbox.get("instance_id")) != instance_id:
        blocks.append("OUTBOX_INSTANCE_MISMATCH")
    if _clean(outbox.get("channel_id")) != channel_id:
        blocks.append("OUTBOX_CHANNEL_MISMATCH")
    if _platform_key(outbox.get("platform")) != platform:
        blocks.append("OUTBOX_PLATFORM_MISMATCH")

    item = _handoff_item(state)
    if item is None:
        blocks.append("HANDOFF_ITEM_MISSING")
        return sorted(set(blocks))
    if _clean(item.get("handoff_id")) != handoff_id:
        blocks.append("HANDOFF_ID_MISMATCH")
    if _clean(item.get("instance_id")) != instance_id:
        blocks.append("HANDOFF_INSTANCE_MISMATCH")
    if _clean(item.get("channel_id")) != channel_id:
        blocks.append("HANDOFF_CHANNEL_MISMATCH")
    if _platform_key(item.get("platform")) != platform:
        blocks.append("HANDOFF_PLATFORM_MISMATCH")
    if _clean(item.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_NOT_DIRECT_READY")
    if not _safe_repo_path(item.get("adapter")):
        blocks.append("INVALID_ADAPTER_PATH")
    blocks.extend(_validate_reference_names(item))
    if item.get("network_dispatch_performed") is not False:
        blocks.append("HANDOFF_ALREADY_DISPATCHED")

    supplied_handoff_fp = _clean(item.get("handoff_fingerprint_sha256"))
    if not _is_sha256(supplied_handoff_fp) or supplied_handoff_fp != _digest(_item_without_fingerprint(item)):
        blocks.append("HANDOFF_FINGERPRINT_INVALID")
    payload = item.get("adapter_payload") if isinstance(item.get("adapter_payload"), dict) else {}
    payload_fp = _clean(item.get("adapter_payload_fingerprint_sha256"))
    if not payload or not _is_sha256(payload_fp) or payload_fp != _digest(payload):
        blocks.append("ADAPTER_PAYLOAD_FINGERPRINT_INVALID")
    else:
        if _clean(payload.get("instance_id")) != instance_id:
            blocks.append("PAYLOAD_INSTANCE_MISMATCH")
        if _clean(payload.get("channel_id")) != channel_id:
            blocks.append("PAYLOAD_CHANNEL_MISMATCH")
        if _platform_key(payload.get("platform")) != platform:
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
        if _platform_key(record.get("platform")) != platform:
            blocks.append("RECORD_PLATFORM_MISMATCH")
        if _clean(record.get("product_id")) != _clean(item.get("product_id")):
            blocks.append("RECORD_PRODUCT_MISMATCH")
        if record.get("remote_publication_id") and _clean(record.get("status")) != "PUBLISHED":
            blocks.append("REMOTE_ID_WITHOUT_PUBLISHED_STATE")
    return sorted(set(blocks))


def initialize_dispatch_state(bridge_result: dict[str, Any]) -> dict[str, Any]:
    """Convert one validated DIRECT_READY bridge result into executor-owned state."""
    if not isinstance(bridge_result, dict):
        raise TypeError("bridge_result must be a mapping")
    blocks: list[str] = []
    if bridge_result.get("blocked") is True:
        blocks.append("BRIDGE_BLOCKED")
    if _clean(bridge_result.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("BRIDGE_NOT_DIRECT_READY")
    handoff = bridge_result.get("adapter_handoff") if isinstance(bridge_result.get("adapter_handoff"), dict) else {}
    if handoff.get("dispatch_allowed") is not True:
        blocks.append("BRIDGE_DISPATCH_NOT_ALLOWED")
    if handoff.get("credential_values_exposed") is not False:
        blocks.append("BRIDGE_CREDENTIAL_VALUES_EXPOSED")
    guards = bridge_result.get("guards") if isinstance(bridge_result.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("BRIDGE_ZERO_PAID_DEPENDENCY_VIOLATION")
    if guards.get("credential_values_read") is not False or guards.get("credential_values_exposed") is not False:
        blocks.append("BRIDGE_CREDENTIAL_POLICY_VIOLATION")
    if guards.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("BRIDGE_VERBATIM_REUSE")

    bundle = bridge_result.get("commit_bundle") if isinstance(bridge_result.get("commit_bundle"), dict) else {}
    supplied_bundle_fp = _clean(bridge_result.get("bundle_fingerprint_sha256"))
    if not bundle:
        blocks.append("MISSING_BRIDGE_COMMIT_BUNDLE")
    elif not _is_sha256(supplied_bundle_fp) or supplied_bundle_fp != _digest(bundle):
        blocks.append("BRIDGE_BUNDLE_FINGERPRINT_INVALID")
    if bundle:
        if bundle.get("atomic_persist_required") is not True:
            blocks.append("BRIDGE_ATOMIC_PERSIST_REQUIRED")
        if bundle.get("network_dispatch_performed") is not False:
            blocks.append("BRIDGE_NETWORK_ALREADY_PERFORMED")
        for key in ("instance_id", "channel_id", "platform", "handoff_id"):
            left = _platform_key(bundle.get(key)) if key == "platform" else _clean(bundle.get(key))
            right = _platform_key(bridge_result.get(key)) if key == "platform" else _clean(bridge_result.get(key))
            if left != right:
                blocks.append(f"BRIDGE_BUNDLE_{key.upper()}_MISMATCH")

    if blocks:
        return _blocked(None, blocks)

    state = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(bridge_result.get("instance_id")),
        "channel_id": _clean(bridge_result.get("channel_id")),
        "platform": _platform_key(bridge_result.get("platform")),
        "handoff_id": _clean(bundle.get("handoff_id")),
        "source_bridge_bundle_fingerprint_sha256": supplied_bundle_fp,
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
    }
    state = _seal_state(state)
    state_blocks = _validate_state(state)
    record = _record(state)
    if record is not None and _clean(record.get("status")) != "READY":
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


def _lease_status(record: dict[str, Any], now: datetime) -> tuple[str, dict[str, Any] | None]:
    execution = record.get("dispatch_execution") if isinstance(record.get("dispatch_execution"), dict) else None
    if execution is None:
        return "MISSING", None
    if _clean(execution.get("status")) != "ACTIVE":
        return "INVALID", execution
    try:
        expires = _parse_time(_clean(execution.get("lease_expires_at")))
    except (TypeError, ValueError):
        return "INVALID", execution
    return ("ACTIVE" if now < expires else "EXPIRED"), execution


def claim_dispatch(
    state: dict[str, Any],
    now: str,
    worker_id: str,
    *,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    """Build a CAS claim candidate that must be persisted before adapter invocation."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    if not _clean(worker_id):
        raise ValueError("worker_id is required")
    if lease_seconds < 30 or lease_seconds > MAX_LEASE_SECONDS:
        raise ValueError("lease_seconds must be between 30 and 3600")
    current = _parse_time(now)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)

    record = _record(state)
    item = _handoff_item(state)
    assert record is not None and item is not None
    status = _clean(record.get("status"))
    if status == "PUBLISHED":
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "ALREADY_PUBLISHED",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
            "adapter_invocation": None,
        }
    if status == "PUBLISHING":
        lease_status, execution = _lease_status(record, current)
        if lease_status == "ACTIVE":
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": [],
                "decision": "LEASE_HELD",
                "state": copy.deepcopy(state),
                "active_worker_id": _clean((execution or {}).get("worker_id")) or None,
                "lease_expires_at": _clean((execution or {}).get("lease_expires_at")) or None,
                "adapter_invoked": False,
                "adapter_invocation": None,
            }
        if lease_status == "EXPIRED":
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": [],
                "decision": "RECONCILIATION_REQUIRED",
                "state": copy.deepcopy(state),
                "reason": "PUBLISHING_LEASE_EXPIRED_REMOTE_STATE_UNKNOWN",
                "adapter_invoked": False,
                "adapter_invocation": None,
            }
        return _blocked(state, ["INVALID_PUBLISHING_LEASE"])

    working = copy.deepcopy(state)
    if status == "RETRY_WAIT":
        released = publication_state.release_retry(working["ledger"], _clean(item.get("publication_id")), _iso(current))
        if released.get("blocked") is True:
            return _blocked(state, [str(value) for value in released.get("hard_blocks", [])])
        if _clean(released.get("decision")) == "RETRY_NOT_DUE":
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": [],
                "decision": "RETRY_NOT_DUE",
                "state": copy.deepcopy(state),
                "next_attempt_at": _clean(record.get("next_attempt_at")) or None,
                "adapter_invoked": False,
                "adapter_invocation": None,
            }
        working["ledger"] = released["ledger"]
        record = _record(working)
        assert record is not None
        status = _clean(record.get("status"))

    if status not in {"READY", "RETRY_READY"}:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "NOT_DISPATCHABLE",
            "publication_status": status,
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
            "adapter_invocation": None,
        }

    expected_fp = _clean(state.get("state_fingerprint_sha256"))
    claim_token = "claim:" + _digest(
        {
            "handoff_id": _clean(state.get("handoff_id")),
            "publication_id": _clean(item.get("publication_id")),
            "worker_id": _clean(worker_id),
            "claimed_at": _iso(current),
            "expected_state_fingerprint_sha256": expected_fp,
        }
    )[:32]
    expires = current + timedelta(seconds=lease_seconds)
    candidate_record = _record(working)
    assert candidate_record is not None
    pre_claim_status = _clean(candidate_record.get("status"))
    candidate_record["status"] = "PUBLISHING"
    candidate_record["state_reason"] = "DURABLE_DISPATCH_CLAIMED"
    candidate_record["dispatch_execution"] = {
        "status": "ACTIVE",
        "handoff_id": _clean(state.get("handoff_id")),
        "claim_token": claim_token,
        "worker_id": _clean(worker_id),
        "claimed_at": _iso(current),
        "lease_expires_at": _iso(expires),
        "pre_claim_status": pre_claim_status,
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


def _result_contract_blocks(result: dict[str, Any], item: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    unknown = sorted(set(result) - RESULT_ALLOWED_FIELDS)
    if unknown:
        blocks.append("ADAPTER_RESULT_UNKNOWN_FIELDS:" + ",".join(unknown))
    for key in result:
        lowered = _clean(key).lower()
        if any(part in lowered for part in RESULT_FORBIDDEN_KEY_PARTS):
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
    if http_status is not None and (not isinstance(http_status, int) or isinstance(http_status, bool) or http_status < 100 or http_status > 599):
        blocks.append("ADAPTER_RESULT_HTTP_STATUS_INVALID")
    retry_after = result.get("retry_after_seconds")
    if retry_after is not None and (not isinstance(retry_after, int) or isinstance(retry_after, bool) or retry_after < 0):
        blocks.append("ADAPTER_RESULT_RETRY_AFTER_INVALID")
    if result.get("success") is True and not _clean(result.get("remote_publication_id")):
        blocks.append("ADAPTER_SUCCESS_MISSING_REMOTE_PUBLICATION_ID")
    return sorted(set(blocks))


def _append_history(record: dict[str, Any], execution: dict[str, Any], *, decision: str, completed_at: str, recovery: bool = False) -> None:
    history = record.setdefault("dispatch_history", [])
    if not isinstance(history, list):
        history = []
        record["dispatch_history"] = history
    history.append(
        {
            "handoff_id": _clean(execution.get("handoff_id")),
            "claim_token": _clean(execution.get("claim_token")),
            "worker_id": _clean(execution.get("worker_id")),
            "claimed_at": _clean(execution.get("claimed_at")),
            "lease_expires_at": _clean(execution.get("lease_expires_at")),
            "completed_at": completed_at,
            "decision": decision,
            "crash_recovery": recovery is True,
            "credential_values_included": False,
        }
    )
    record.pop("dispatch_execution", None)


def reconcile_adapter_result(
    state: dict[str, Any],
    claim_token: str,
    attempted_at: str,
    adapter_result: dict[str, Any],
    *,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Reconcile one sanitized adapter outcome against the active durable claim."""
    if not isinstance(state, dict) or not isinstance(adapter_result, dict):
        raise TypeError("state and adapter_result must be mappings")
    when = _parse_time(attempted_at)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    item = _handoff_item(state)
    record = _record(state)
    assert item is not None and record is not None
    if _clean(record.get("status")) != "PUBLISHING":
        return _blocked(state, ["PUBLICATION_NOT_PUBLISHING"])
    execution = record.get("dispatch_execution") if isinstance(record.get("dispatch_execution"), dict) else {}
    if _clean(execution.get("status")) != "ACTIVE":
        return _blocked(state, ["ACTIVE_DISPATCH_EXECUTION_MISSING"])
    if _clean(execution.get("claim_token")) != _clean(claim_token):
        return _blocked(state, ["CLAIM_TOKEN_MISMATCH"])

    result_blocks = _result_contract_blocks(adapter_result, item)
    if result_blocks:
        if "ADAPTER_SUCCESS_MISSING_REMOTE_PUBLICATION_ID" in result_blocks and adapter_result.get("success") is True:
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": result_blocks,
                "decision": "RECONCILIATION_REQUIRED",
                "reason": "ADAPTER_REPORTED_SUCCESS_WITHOUT_REMOTE_PROOF",
                "state": copy.deepcopy(state),
                "adapter_invoked": True,
            }
        return _blocked(state, result_blocks)

    working_ledger = copy.deepcopy(state["ledger"])
    publication_id = _clean(item.get("publication_id"))
    working_record = working_ledger["records"][publication_id]
    pre_claim_status = _clean(execution.get("pre_claim_status"))
    if pre_claim_status not in {"READY", "RETRY_READY"}:
        return _blocked(state, ["INVALID_PRE_CLAIM_STATUS"])
    # The canonical retry engine intentionally accepts READY/RETRY_READY only. We
    # restore that pre-claim status on an isolated candidate solely for outcome
    # classification; durable state remains PUBLISHING until this reconciliation
    # is successfully persisted.
    working_record["status"] = pre_claim_status
    outcome = publication_state.apply_attempt(
        working_ledger,
        publication_id,
        _iso(when),
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
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [str(value) for value in outcome.get("hard_blocks", [])],
            "decision": "RECONCILIATION_REQUIRED",
            "reason": "PUBLICATION_STATE_REJECTED_ADAPTER_OUTCOME",
            "state": copy.deepcopy(state),
            "adapter_invoked": True,
        }

    candidate = copy.deepcopy(state)
    candidate["ledger"] = outcome["ledger"]
    final_record = _record(candidate)
    assert final_record is not None
    _append_history(final_record, execution, decision=_clean(outcome.get("decision")), completed_at=_iso(when))
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


def recover_stale_claim(
    state: dict[str, Any],
    now: str,
    *,
    remote_publication_id: str | None = None,
    remote_absent_confirmed: bool = False,
) -> dict[str, Any]:
    """Reconcile an expired PUBLISHING lease without blind re-dispatch."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    current = _parse_time(now)
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    if _clean(remote_publication_id) and remote_absent_confirmed is True:
        return _blocked(state, ["CONTRADICTORY_REMOTE_RECONCILIATION"])
    record = _record(state)
    item = _handoff_item(state)
    assert record is not None and item is not None
    if _clean(record.get("status")) != "PUBLISHING":
        return _blocked(state, ["PUBLICATION_NOT_PUBLISHING"])
    lease_status, execution = _lease_status(record, current)
    if lease_status == "ACTIVE":
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "LEASE_HELD",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
        }
    if lease_status != "EXPIRED" or execution is None:
        return _blocked(state, ["INVALID_PUBLISHING_LEASE"])

    remote_id = _clean(remote_publication_id)
    if not remote_id and remote_absent_confirmed is not True:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "RECONCILIATION_REQUIRED",
            "reason": "REMOTE_STATE_MUST_BE_CHECKED_BEFORE_RETRY",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
        }

    candidate = copy.deepcopy(state)
    candidate_record = _record(candidate)
    assert candidate_record is not None
    if remote_id:
        pre_claim_status = _clean(execution.get("pre_claim_status"))
        working_ledger = copy.deepcopy(candidate["ledger"])
        working_record = working_ledger["records"][_clean(item.get("publication_id"))]
        working_record["status"] = pre_claim_status if pre_claim_status in {"READY", "RETRY_READY"} else "READY"
        outcome = publication_state.apply_attempt(
            working_ledger,
            _clean(item.get("publication_id")),
            _iso(current),
            success=True,
            remote_publication_id=remote_id,
        )
        if outcome.get("blocked") is True:
            return _blocked(state, ["REMOTE_RECONCILIATION_FAILED"] + [str(value) for value in outcome.get("hard_blocks", [])])
        candidate["ledger"] = outcome["ledger"]
        candidate_record = _record(candidate)
        assert candidate_record is not None
        _append_history(candidate_record, execution, decision="PUBLISHED_AFTER_CRASH_RECONCILIATION", completed_at=_iso(current), recovery=True)
        decision = "PUBLISHED_AFTER_CRASH_RECONCILIATION"
    else:
        candidate_record["status"] = "RETRY_READY"
        candidate_record["state_reason"] = "CRASH_RECONCILED_REMOTE_ABSENT"
        candidate_record["next_attempt_at"] = None
        _append_history(candidate_record, execution, decision="REQUEUED_AFTER_REMOTE_ABSENT", completed_at=_iso(current), recovery=True)
        decision = "REQUEUED_AFTER_REMOTE_ABSENT"

    candidate["revision"] = int(candidate.get("revision", 0)) + 1
    candidate = _seal_state(candidate)
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "publication_status": _clean((_record(candidate) or {}).get("status")),
        "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "adapter_invoked": False,
    }


def execute_dispatch(
    state: dict[str, Any],
    now: str,
    worker_id: str,
    *,
    persist_claim: Callable[[str, dict[str, Any]], bool],
    invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_result: Callable[[str, dict[str, Any]], bool] | None = None,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Execute one dispatch with mandatory durable claim-before-network ordering.

    ``persist_claim`` and ``persist_result`` are compare-and-swap callbacks. They
    receive the expected prior state fingerprint and the replacement state. A
    false return means another worker or persistence race won; the adapter is not
    invoked before claim persistence, and a post-network result conflict becomes
    reconciliation-required instead of an unsafe retry.
    """
    if not callable(persist_claim) or not callable(invoke_adapter):
        raise TypeError("persist_claim and invoke_adapter must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable when provided")

    claim = claim_dispatch(state, now, worker_id, lease_seconds=lease_seconds)
    if claim.get("blocked") is True or _clean(claim.get("decision")) != "CLAIMED":
        return claim
    expected = _clean(claim.get("expected_previous_state_fingerprint_sha256"))
    claimed_state = claim["state"]
    try:
        persisted = persist_claim(expected, copy.deepcopy(claimed_state)) is True
    except Exception:
        persisted = False
    if not persisted:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "CLAIM_PERSIST_CONFLICT",
            "reason": "ADAPTER_NOT_INVOKED_BECAUSE_PUBLISHING_CLAIM_WAS_NOT_DURABLE",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
        }

    invocation = copy.deepcopy(claim["adapter_invocation"])
    try:
        raw_result = invoke_adapter(invocation)
        if not isinstance(raw_result, dict):
            raw_result = {
                "success": False,
                "error_class": "transient",
                "error_code": "ADAPTER_RESULT_NOT_MAPPING",
            }
    except Exception as exc:
        raw_result = {
            "success": False,
            "error_class": "network_error",
            "error_code": "ADAPTER_EXCEPTION_" + type(exc).__name__.upper(),
        }

    reconciled = reconcile_adapter_result(
        claimed_state,
        _clean(claim.get("claim_token")),
        now,
        raw_result,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    if _clean(reconciled.get("decision")) == "RECONCILIATION_REQUIRED" or reconciled.get("blocked") is True:
        reconciled["adapter_invoked"] = True
        return reconciled

    if persist_result is not None:
        expected_claimed = _clean(claimed_state.get("state_fingerprint_sha256"))
        try:
            result_persisted = persist_result(expected_claimed, copy.deepcopy(reconciled["state"])) is True
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
