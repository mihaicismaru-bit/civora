#!/usr/bin/env python3
"""Crash-safe async remote-dispatch lifecycle for LOCAL NEWS OS.

Adapters such as TikTok can acknowledge a submission before a public post id
exists. This module composes the existing Durable Dispatch Executor with a
credential-free pending sidecar so that an acknowledgement is never mistaken for
publication and an ambiguous crash never causes a blind resend.

No network calls or credential resolution happen here. The caller injects the
adapter submission and remote-status callbacks.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

import durable_dispatch_executor as executor

SCHEMA_VERSION = "1.0"
FORBIDDEN_KEY_PARTS = (
    "token", "secret", "password", "authorization", "api_key", "apikey",
    "cookie", "headers", "raw_response", "response_body",
)
SAFE_INTERNAL_KEYS = {"claim_token"}
PENDING_STATES = {"PENDING", "PENDING_PUBLICATION_PROOF"}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _is_sha256(value: Any) -> bool:
    text = _clean(value).lower()
    return len(text) == 64 and all(ch in "0123456789abcdef" for ch in text)


def _contains_forbidden_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = _clean(key).lower()
            if lowered not in SAFE_INTERNAL_KEYS and any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_field(item) for item in value)
    return False


def _seal_pending(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("pending_fingerprint_sha256", None)
    result["pending_fingerprint_sha256"] = _digest(result)
    return result


def _pending_fingerprint_ok(value: dict[str, Any]) -> bool:
    supplied = _clean(value.get("pending_fingerprint_sha256"))
    if not _is_sha256(supplied):
        return False
    candidate = copy.deepcopy(value)
    candidate.pop("pending_fingerprint_sha256", None)
    return supplied == _digest(candidate)


def _handoff(state: dict[str, Any]) -> dict[str, Any] | None:
    outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
    items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
    value = items.get(_clean(state.get("handoff_id")))
    return value if isinstance(value, dict) else None


def _record(state: dict[str, Any]) -> dict[str, Any] | None:
    item = _handoff(state)
    if item is None:
        return None
    ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    value = records.get(_clean(item.get("publication_id")))
    return value if isinstance(value, dict) else None


def _blocked(state: dict[str, Any] | None, reasons: list[str], *, adapter_invoked: bool = False) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": True,
        "hard_blocks": sorted(set(reasons)),
        "decision": "BLOCKED",
        "state": copy.deepcopy(state) if isinstance(state, dict) else None,
        "adapter_invoked": adapter_invoked,
    }


def _submission_blocks(result: dict[str, Any], invocation: dict[str, Any]) -> list[str]:
    allowed = {
        "accepted", "remote_submission_id", "adapter", "publication_id",
        "native_format", "credential_values_included",
        "network_submission_performed", "publication_confirmed",
    }
    blocks: list[str] = []
    unknown = sorted(set(result) - allowed)
    if unknown:
        blocks.append("ASYNC_SUBMISSION_UNKNOWN_FIELDS:" + ",".join(unknown))
    if _contains_forbidden_field(result):
        blocks.append("ASYNC_SUBMISSION_SECRET_OR_RAW_FIELD")
    if result.get("accepted") is not True:
        blocks.append("ASYNC_SUBMISSION_NOT_ACCEPTED")
    if not _clean(result.get("remote_submission_id")):
        blocks.append("ASYNC_SUBMISSION_ID_MISSING")
    if result.get("publication_confirmed") is not False:
        blocks.append("ASYNC_SUBMISSION_MUST_NOT_CLAIM_PUBLICATION")
    if result.get("credential_values_included") is not False:
        blocks.append("ASYNC_SUBMISSION_CREDENTIAL_VALUES_INCLUDED")
    if result.get("network_submission_performed") is not True:
        blocks.append("ASYNC_SUBMISSION_NETWORK_ACK_MISSING")
    if result.get("adapter") is not None and _clean(result.get("adapter")) != _clean(invocation.get("adapter")):
        blocks.append("ASYNC_SUBMISSION_ADAPTER_MISMATCH")
    if result.get("publication_id") is not None and _clean(result.get("publication_id")) != _clean(invocation.get("publication_id")):
        blocks.append("ASYNC_SUBMISSION_PUBLICATION_MISMATCH")
    return sorted(set(blocks))


def _pending_blocks(pending: dict[str, Any], state: dict[str, Any]) -> list[str]:
    if not isinstance(pending, dict):
        return ["ASYNC_PENDING_NOT_MAPPING"]
    blocks: list[str] = []
    if _clean(pending.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("ASYNC_PENDING_SCHEMA_VERSION")
    if not _pending_fingerprint_ok(pending):
        blocks.append("ASYNC_PENDING_FINGERPRINT_INVALID")
    if _contains_forbidden_field(pending):
        blocks.append("ASYNC_PENDING_SECRET_OR_RAW_FIELD")

    item = _handoff(state)
    record = _record(state)
    if item is None or record is None:
        return sorted(set(blocks + ["ASYNC_PENDING_SOURCE_STATE_INVALID"]))
    expected = {
        "instance_id": _clean(state.get("instance_id")),
        "channel_id": _clean(state.get("channel_id")),
        "platform": _clean(state.get("platform")),
        "handoff_id": _clean(state.get("handoff_id")),
        "publication_id": _clean(item.get("publication_id")),
        "adapter": _clean(item.get("adapter")),
    }
    for key, expected_value in expected.items():
        if _clean(pending.get(key)) != expected_value:
            blocks.append("ASYNC_PENDING_" + key.upper() + "_MISMATCH")
    if not _clean(pending.get("remote_submission_id")):
        blocks.append("ASYNC_PENDING_SUBMISSION_ID_MISSING")
    if pending.get("credential_values_included") is not False:
        blocks.append("ASYNC_PENDING_CREDENTIAL_VALUES_INCLUDED")
    if pending.get("publication_confirmed") is not False:
        blocks.append("ASYNC_PENDING_FALSE_PUBLICATION_PROOF")
    if _clean(record.get("status")) != "PUBLISHING":
        blocks.append("ASYNC_PENDING_PUBLICATION_NOT_PUBLISHING")
    execution = record.get("dispatch_execution") if isinstance(record.get("dispatch_execution"), dict) else {}
    if _clean(execution.get("claim_token")) != _clean(pending.get("claim_token")):
        blocks.append("ASYNC_PENDING_CLAIM_TOKEN_MISMATCH")
    if _clean(pending.get("claimed_state_fingerprint_sha256")) != _clean(state.get("state_fingerprint_sha256")):
        blocks.append("ASYNC_PENDING_CLAIMED_STATE_MISMATCH")
    return sorted(set(blocks))


def begin_async_dispatch(
    state: dict[str, Any],
    now: str,
    worker_id: str,
    *,
    persist_claim: Callable[[str, dict[str, Any]], bool],
    invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_pending: Callable[[dict[str, Any]], bool],
    lease_seconds: int = executor.DEFAULT_LEASE_SECONDS,
) -> dict[str, Any]:
    """Persist a generic claim, submit exactly once, and persist provider submission id."""
    if not all(callable(fn) for fn in (persist_claim, invoke_adapter, persist_pending)):
        raise TypeError("persist_claim, invoke_adapter and persist_pending must be callable")
    claim = executor.claim_dispatch(state, now, worker_id, lease_seconds=lease_seconds)
    if claim.get("blocked") is True or _clean(claim.get("decision")) != "CLAIMED":
        return claim

    try:
        claim_saved = persist_claim(
            _clean(claim.get("expected_previous_state_fingerprint_sha256")),
            copy.deepcopy(claim["state"]),
        ) is True
    except Exception:
        claim_saved = False
    if not claim_saved:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "CLAIM_PERSIST_CONFLICT",
            "reason": "ASYNC_ADAPTER_NOT_INVOKED_BECAUSE_PUBLISHING_CLAIM_WAS_NOT_DURABLE",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
        }

    claimed_state = claim["state"]
    invocation = claim["adapter_invocation"]
    try:
        submission = invoke_adapter(copy.deepcopy(invocation))
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "ASYNC_SUBMISSION_AMBIGUOUS_RECONCILIATION_REQUIRED",
            "reason": "ADAPTER_EXCEPTION_" + type(exc).__name__.upper(),
            "state": copy.deepcopy(claimed_state),
            "claim_token": _clean(claim.get("claim_token")),
            "adapter_invoked": True,
            "blind_retry_allowed": False,
        }
    if not isinstance(submission, dict):
        return _blocked(claimed_state, ["ASYNC_SUBMISSION_RESULT_NOT_MAPPING"], adapter_invoked=True)
    blocks = _submission_blocks(submission, invocation)
    if blocks:
        result = _blocked(claimed_state, blocks, adapter_invoked=True)
        result["blind_retry_allowed"] = False
        return result

    pending = _seal_pending({
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(claimed_state.get("instance_id")),
        "channel_id": _clean(claimed_state.get("channel_id")),
        "platform": _clean(claimed_state.get("platform")),
        "handoff_id": _clean(claimed_state.get("handoff_id")),
        "publication_id": _clean(invocation.get("publication_id")),
        "adapter": _clean(invocation.get("adapter")),
        "claim_token": _clean(claim.get("claim_token")),
        "remote_submission_id": _clean(submission.get("remote_submission_id")),
        "native_format": _clean(submission.get("native_format")) or None,
        "submitted_at": now,
        "provider_status": "SUBMITTED",
        "last_checked_at": None,
        "claimed_state_fingerprint_sha256": _clean(claimed_state.get("state_fingerprint_sha256")),
        "credential_values_included": False,
        "network_submission_performed": True,
        "publication_confirmed": False,
        "guards": {
            "blind_retry_allowed": False,
            "remote_publication_proof_required": True,
            "credential_values_persisted": False,
            "raw_provider_payload_persisted": False,
            "zero_paid_dependency": True,
        },
    })
    try:
        pending_saved = persist_pending(copy.deepcopy(pending)) is True
    except Exception:
        pending_saved = False
    if not pending_saved:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "PENDING_PERSIST_CONFLICT_RECONCILIATION_REQUIRED",
            "reason": "REMOTE_SUBMISSION_ACCEPTED_BUT_SUBMISSION_ID_DURABILITY_NOT_CONFIRMED",
            "state": copy.deepcopy(claimed_state),
            "candidate_pending": pending,
            "adapter_invoked": True,
            "blind_retry_allowed": False,
        }
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "ASYNC_REMOTE_PENDING",
        "state": copy.deepcopy(claimed_state),
        "pending": pending,
        "remote_submission_id": pending["remote_submission_id"],
        "publication_status": "PUBLISHING",
        "claim_persisted_before_adapter": True,
        "pending_persisted_after_submission": True,
        "adapter_invoked": True,
        "publication_confirmed": False,
        "blind_retry_allowed": False,
    }


def _status_blocks(status: dict[str, Any], pending: dict[str, Any]) -> list[str]:
    allowed = {
        "state", "remote_submission_id", "remote_publication_id",
        "provider_status", "error_code", "publication_confirmed",
    }
    blocks: list[str] = []
    unknown = sorted(set(status) - allowed)
    if unknown:
        blocks.append("ASYNC_STATUS_UNKNOWN_FIELDS:" + ",".join(unknown))
    if _contains_forbidden_field(status):
        blocks.append("ASYNC_STATUS_SECRET_OR_RAW_FIELD")
    remote_state = _clean(status.get("state")).upper()
    if remote_state not in PENDING_STATES | {"PUBLISHED", "FAILED"}:
        blocks.append("ASYNC_STATUS_STATE_INVALID")
    if _clean(status.get("remote_submission_id")) != _clean(pending.get("remote_submission_id")):
        blocks.append("ASYNC_STATUS_SUBMISSION_ID_MISMATCH")
    if remote_state == "PUBLISHED":
        if status.get("publication_confirmed") is not True:
            blocks.append("ASYNC_STATUS_PUBLISHED_WITHOUT_CONFIRMATION")
        if not _clean(status.get("remote_publication_id")):
            blocks.append("ASYNC_STATUS_PUBLISHED_WITHOUT_REMOTE_ID")
    elif status.get("publication_confirmed") is not False:
        blocks.append("ASYNC_STATUS_FALSE_PUBLICATION_CONFIRMATION")
    return sorted(set(blocks))


def reconcile_async_dispatch(
    state: dict[str, Any],
    pending: dict[str, Any],
    now: str,
    *,
    fetch_remote_status: Callable[[dict[str, Any]], dict[str, Any]],
    persist_pending: Callable[[str, dict[str, Any]], bool] | None = None,
    persist_result: Callable[[str, dict[str, Any]], bool] | None = None,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Poll a provider submission and finalize generic state only with remote proof."""
    if not callable(fetch_remote_status):
        raise TypeError("fetch_remote_status must be callable")
    if persist_pending is not None and not callable(persist_pending):
        raise TypeError("persist_pending must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable")
    blocks = _pending_blocks(pending, state)
    if blocks:
        return _blocked(state, blocks)

    try:
        status = fetch_remote_status(copy.deepcopy(pending))
    except Exception as exc:
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "REMOTE_STATUS_CHECK_RETRY_LATER",
            "reason": "STATUS_EXCEPTION_" + type(exc).__name__.upper(),
            "state": copy.deepcopy(state),
            "pending": copy.deepcopy(pending),
            "adapter_invoked": False,
            "publication_confirmed": False,
            "blind_retry_allowed": False,
        }
    if not isinstance(status, dict):
        return _blocked(state, ["ASYNC_STATUS_RESULT_NOT_MAPPING"])
    status_blocks = _status_blocks(status, pending)
    if status_blocks:
        return _blocked(state, status_blocks)

    remote_state = _clean(status.get("state")).upper()
    if remote_state in PENDING_STATES:
        updated = copy.deepcopy(pending)
        updated["provider_status"] = _clean(status.get("provider_status")) or remote_state
        updated["last_checked_at"] = now
        updated["publication_confirmed"] = False
        updated = _seal_pending(updated)
        if persist_pending is not None:
            try:
                saved = persist_pending(
                    _clean(pending.get("pending_fingerprint_sha256")),
                    copy.deepcopy(updated),
                ) is True
            except Exception:
                saved = False
            if not saved:
                return {
                    "schema_version": SCHEMA_VERSION,
                    "blocked": False,
                    "hard_blocks": [],
                    "decision": "PENDING_STATUS_PERSIST_CONFLICT",
                    "state": copy.deepcopy(state),
                    "pending": copy.deepcopy(pending),
                    "candidate_pending": updated,
                    "adapter_invoked": False,
                    "publication_confirmed": False,
                    "blind_retry_allowed": False,
                }
        return {
            "schema_version": SCHEMA_VERSION,
            "blocked": False,
            "hard_blocks": [],
            "decision": "REMOTE_STILL_PENDING",
            "state": copy.deepcopy(state),
            "pending": updated,
            "publication_status": "PUBLISHING",
            "adapter_invoked": False,
            "publication_confirmed": False,
            "blind_retry_allowed": False,
        }

    if remote_state == "PUBLISHED":
        adapter_result = {
            "success": True,
            "remote_publication_id": _clean(status.get("remote_publication_id")),
            "adapter": _clean(pending.get("adapter")),
            "publication_id": _clean(pending.get("publication_id")),
        }
    else:
        adapter_result = {
            "success": False,
            "error_class": "permanent",
            "error_code": _clean(status.get("error_code"))[:240] or "REMOTE_ASYNC_FAILED",
            "adapter": _clean(pending.get("adapter")),
            "publication_id": _clean(pending.get("publication_id")),
        }

    reconciled = executor.reconcile_adapter_result(
        state,
        _clean(pending.get("claim_token")),
        now,
        adapter_result,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    if reconciled.get("blocked") is True or _clean(reconciled.get("decision")) == "RECONCILIATION_REQUIRED":
        reconciled["blind_retry_allowed"] = False
        return reconciled

    if persist_result is not None:
        try:
            result_saved = persist_result(
                _clean(state.get("state_fingerprint_sha256")),
                copy.deepcopy(reconciled["state"]),
            ) is True
        except Exception:
            result_saved = False
        if not result_saved:
            return {
                "schema_version": SCHEMA_VERSION,
                "blocked": False,
                "hard_blocks": [],
                "decision": "RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED",
                "reason": "REMOTE_RESULT_KNOWN_BUT_GENERIC_STATE_CAS_FAILED",
                "state": copy.deepcopy(state),
                "candidate_result_state_fingerprint_sha256": _clean(reconciled.get("result_state_fingerprint_sha256")),
                "adapter_invoked": False,
                "blind_retry_allowed": False,
            }
    reconciled["remote_submission_id"] = _clean(pending.get("remote_submission_id"))
    reconciled["async_reconciliation_completed"] = True
    reconciled["publication_confirmed"] = remote_state == "PUBLISHED"
    reconciled["blind_retry_allowed"] = False
    return reconciled
