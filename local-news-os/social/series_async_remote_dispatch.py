#!/usr/bin/env python3
"""Crash-safe async remote lifecycle for recurring social-series dispatch.

This module composes the existing recurring-series durable executor with the
existing generic async remote-dispatch lifecycle. It exists for adapters whose
network acknowledgement is only a submission id (for example TikTok Direct
Post), so a recurring series can never be marked PUBLISHED before remote proof
exists.

The exact channel-native series product and ordered source-story identity stay
bound to the durable series state and to the async pending sidecar. Credential
values, raw provider payloads, predictive analytics and network clients do not
belong in this layer; callers inject persistence and adapter/status callbacks.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

import async_remote_dispatch as async_dispatch
import series_durable_dispatch_executor as series_executor

SCHEMA_VERSION = "1.0"
PUBLICATION_KIND = "recurring_series"
ASYNC_COMPLETION_MODEL = "async_remote_status"
SECRET_KEYS = {
    "access_token", "refresh_token", "token", "secret", "password", "api_key",
    "apikey", "client_secret", "credential_value", "credential_values",
    "authorization", "bearer",
}


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


def _contains_exact_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _clean(key).casefold() in keys or _contains_exact_key(child, keys):
                return True
    elif isinstance(value, list):
        return any(_contains_exact_key(item, keys) for item in value)
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
    inner = state.get("executor_state") if isinstance(state.get("executor_state"), dict) else {}
    outbox = inner.get("outbox") if isinstance(inner.get("outbox"), dict) else {}
    items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
    value = items.get(_clean(state.get("handoff_id")))
    return value if isinstance(value, dict) else None


def _native_product(state: dict[str, Any]) -> dict[str, Any]:
    item = series_executor._series_item(state)
    product = item.get("product") if isinstance(item, dict) and isinstance(item.get("product"), dict) else {}
    return product


def _source_story_ids(state: dict[str, Any]) -> list[str]:
    return series_executor._story_ids(_native_product(state))


def _blocked(state: dict[str, Any] | None, reasons: list[str], *, adapter_invoked: bool = False) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "publication_kind": PUBLICATION_KIND,
        "blocked": True,
        "hard_blocks": sorted(set(str(reason) for reason in reasons)),
        "decision": "BLOCKED_SERIES_ASYNC_REMOTE_DISPATCH",
        "state": copy.deepcopy(state) if isinstance(state, dict) else None,
        "adapter_invoked": adapter_invoked,
        "blind_retry_allowed": False,
    }


def _capability_entry(capabilities: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = capabilities.get("adapters") if isinstance(capabilities.get("adapters"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _platform(row.get("platform")) == platform]
    return matches[0] if len(matches) == 1 else None


def _capability_blocks(state: dict[str, Any], capabilities: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if not isinstance(capabilities, dict):
        return ["ASYNC_CAPABILITY_REGISTRY_NOT_MAPPING"]
    if _clean(capabilities.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("ASYNC_CAPABILITY_SCHEMA_VERSION")
    if _clean(capabilities.get("instance_id")) != _clean(state.get("instance_id")):
        blocks.append("ASYNC_CAPABILITY_INSTANCE_MISMATCH")
    if _contains_exact_key(capabilities, SECRET_KEYS):
        blocks.append("ASYNC_CAPABILITY_SECRET_VALUE_FIELD")

    policy = capabilities.get("policy") if isinstance(capabilities.get("policy"), dict) else {}
    expected_policy = {
        "credential_values_allowed": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "zero_paid_dependency": True,
    }
    for key, expected in expected_policy.items():
        if policy.get(key) is not expected:
            blocks.append("ASYNC_CAPABILITY_POLICY_INVALID:" + key)

    platform = _platform(state.get("platform"))
    capability = _capability_entry(capabilities, platform)
    if capability is None:
        return sorted(set(blocks + ["ASYNC_CAPABILITY_ENTRY_MISSING_OR_AMBIGUOUS"]))

    handoff = _handoff(state)
    if handoff is None:
        return sorted(set(blocks + ["ASYNC_CAPABILITY_HANDOFF_MISSING"]))
    if _clean(capability.get("channel_id")) != _clean(state.get("channel_id")):
        blocks.append("ASYNC_CAPABILITY_CHANNEL_MISMATCH")
    if _clean(capability.get("adapter")) != _clean(handoff.get("adapter")):
        blocks.append("ASYNC_CAPABILITY_ADAPTER_MISMATCH")
    if _clean(capability.get("completion_model")) != ASYNC_COMPLETION_MODEL:
        blocks.append("ASYNC_CAPABILITY_COMPLETION_MODEL_MISMATCH")
    if capability.get("remote_reconciliation_supported") is not True:
        blocks.append("ASYNC_CAPABILITY_REMOTE_RECONCILIATION_REQUIRED")

    product = _native_product(state)
    native_format = _clean(product.get("native_format"))
    supported = {_clean(value) for value in capability.get("supported_native_formats", []) if _clean(value)}
    if not native_format or native_format not in supported:
        blocks.append("ASYNC_CAPABILITY_NATIVE_FORMAT_MISMATCH")
    return sorted(set(blocks))


def _series_invocation(state: dict[str, Any], invocation: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(invocation)
    result["publication_kind"] = PUBLICATION_KIND
    result["series_id"] = _clean(state.get("series_id"))
    result["series_execution_id"] = _clean(state.get("series_execution_id"))
    result["series_slot_key"] = _clean(state.get("series_slot_key"))
    result["source_story_ids"] = _source_story_ids(state)
    return result


def _wrap_generic_pending(state: dict[str, Any], generic_pending: dict[str, Any]) -> dict[str, Any]:
    product = _native_product(state)
    record = series_executor._series_record(state) or {}
    return _seal_pending({
        "schema_version": SCHEMA_VERSION,
        "publication_kind": PUBLICATION_KIND,
        "instance_id": _clean(state.get("instance_id")),
        "channel_id": _clean(state.get("channel_id")),
        "platform": _platform(state.get("platform")),
        "handoff_id": _clean(state.get("handoff_id")),
        "publication_id": _clean(state.get("publication_id")),
        "adapter": _clean(generic_pending.get("adapter")),
        "series_id": _clean(state.get("series_id")),
        "series_execution_id": _clean(state.get("series_execution_id")),
        "series_slot_key": _clean(state.get("series_slot_key")),
        "claim_token": _clean(generic_pending.get("claim_token")),
        "remote_submission_id": _clean(generic_pending.get("remote_submission_id")),
        "native_format": _clean(generic_pending.get("native_format")) or None,
        "source_story_ids": _source_story_ids(state),
        "product_id": _clean(record.get("product_id")) or _clean(product.get("product_id")),
        "product_fingerprint_sha256": _clean(record.get("product_fingerprint_sha256")) or _clean(product.get("product_fingerprint_sha256")),
        "submitted_at": generic_pending.get("submitted_at"),
        "provider_status": generic_pending.get("provider_status"),
        "last_checked_at": generic_pending.get("last_checked_at"),
        "claimed_series_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "generic_pending": copy.deepcopy(generic_pending),
        "publication_confirmed": False,
        "guards": {
            "blind_retry_allowed": False,
            "remote_publication_proof_required": True,
            "native_multi_story_product_preserved": True,
            "credential_values_persisted": False,
            "raw_provider_payload_persisted": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    })


def _pending_blocks(state: dict[str, Any], pending: dict[str, Any]) -> list[str]:
    blocks = list(series_executor._validate_state(state))
    if not isinstance(pending, dict):
        return sorted(set(blocks + ["SERIES_ASYNC_PENDING_NOT_MAPPING"]))
    if _clean(pending.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("SERIES_ASYNC_PENDING_SCHEMA_VERSION")
    if _clean(pending.get("publication_kind")) != PUBLICATION_KIND:
        blocks.append("SERIES_ASYNC_PENDING_PUBLICATION_KIND")
    if not _pending_fingerprint_ok(pending):
        blocks.append("SERIES_ASYNC_PENDING_FINGERPRINT_INVALID")
    if _contains_exact_key(pending, SECRET_KEYS) or async_dispatch._contains_forbidden_field(pending):
        blocks.append("SERIES_ASYNC_PENDING_SECRET_OR_RAW_FIELD")

    expected = {
        "instance_id": _clean(state.get("instance_id")),
        "channel_id": _clean(state.get("channel_id")),
        "platform": _platform(state.get("platform")),
        "handoff_id": _clean(state.get("handoff_id")),
        "publication_id": _clean(state.get("publication_id")),
        "series_id": _clean(state.get("series_id")),
        "series_execution_id": _clean(state.get("series_execution_id")),
        "series_slot_key": _clean(state.get("series_slot_key")),
    }
    for key, expected_value in expected.items():
        actual = _platform(pending.get(key)) if key == "platform" else _clean(pending.get(key))
        if actual != expected_value:
            blocks.append("SERIES_ASYNC_PENDING_" + key.upper() + "_MISMATCH")

    if _clean(pending.get("claimed_series_state_fingerprint_sha256")) != _clean(state.get("state_fingerprint_sha256")):
        blocks.append("SERIES_ASYNC_PENDING_CLAIMED_STATE_MISMATCH")
    if pending.get("publication_confirmed") is not False:
        blocks.append("SERIES_ASYNC_PENDING_FALSE_PUBLICATION_PROOF")
    if not _clean(pending.get("remote_submission_id")):
        blocks.append("SERIES_ASYNC_PENDING_SUBMISSION_ID_MISSING")

    stories = _source_story_ids(state)
    if pending.get("source_story_ids") != stories:
        blocks.append("SERIES_ASYNC_PENDING_SOURCE_STORY_DIVERGENCE")
    record = series_executor._series_record(state) or {}
    if _clean(pending.get("product_id")) != _clean(record.get("product_id")):
        blocks.append("SERIES_ASYNC_PENDING_PRODUCT_ID_MISMATCH")
    if _clean(pending.get("product_fingerprint_sha256")) != _clean(record.get("product_fingerprint_sha256")):
        blocks.append("SERIES_ASYNC_PENDING_PRODUCT_FINGERPRINT_MISMATCH")

    guards = pending.get("guards") if isinstance(pending.get("guards"), dict) else {}
    expected_guards = {
        "blind_retry_allowed": False,
        "remote_publication_proof_required": True,
        "native_multi_story_product_preserved": True,
        "credential_values_persisted": False,
        "raw_provider_payload_persisted": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "zero_paid_dependency": True,
    }
    for key, expected_value in expected_guards.items():
        if guards.get(key) is not expected_value:
            blocks.append("SERIES_ASYNC_PENDING_GUARD_INVALID:" + key)

    generic = pending.get("generic_pending") if isinstance(pending.get("generic_pending"), dict) else {}
    if not generic:
        blocks.append("SERIES_ASYNC_GENERIC_PENDING_MISSING")
    else:
        blocks.extend("GENERIC_ASYNC:" + reason for reason in async_dispatch._pending_blocks(generic, state.get("executor_state") or {}))
        if _clean(generic.get("remote_submission_id")) != _clean(pending.get("remote_submission_id")):
            blocks.append("SERIES_ASYNC_GENERIC_SUBMISSION_ID_DIVERGENCE")
        if _clean(generic.get("claim_token")) != _clean(pending.get("claim_token")):
            blocks.append("SERIES_ASYNC_GENERIC_CLAIM_TOKEN_DIVERGENCE")
    return sorted(set(blocks))


def begin_series_async_dispatch(
    state: dict[str, Any],
    capabilities: dict[str, Any],
    now: str,
    worker_id: str,
    *,
    persist_claim: Callable[[str, dict[str, Any]], bool],
    invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_pending: Callable[[dict[str, Any]], bool],
    lease_seconds: int = 300,
) -> dict[str, Any]:
    """Claim one recurring series, submit once, and durably bind submission id."""
    if not isinstance(state, dict) or not isinstance(capabilities, dict):
        raise TypeError("state and capabilities must be mappings")
    if not all(callable(fn) for fn in (persist_claim, invoke_adapter, persist_pending)):
        raise TypeError("persist_claim, invoke_adapter and persist_pending must be callable")
    state_blocks = series_executor._validate_state(state)
    if state_blocks:
        return _blocked(state, state_blocks)
    capability_blocks = _capability_blocks(state, capabilities)
    if capability_blocks:
        return _blocked(state, capability_blocks)

    stored: dict[str, Any] = {"claimed_outer": None, "series_pending": None}
    expected_outer_fp = _clean(state.get("state_fingerprint_sha256"))
    expected_inner_fp = _clean((state.get("executor_state") or {}).get("state_fingerprint_sha256"))

    def persist_inner_claim(expected: str, candidate_inner: dict[str, Any]) -> bool:
        if _clean(expected) != expected_inner_fp:
            return False
        try:
            candidate_outer = series_executor._sync(state, candidate_inner)
            saved = persist_claim(expected_outer_fp, copy.deepcopy(candidate_outer)) is True
        except Exception:
            saved = False
        if saved:
            stored["claimed_outer"] = candidate_outer
        return saved

    def invoke_series(invocation: dict[str, Any]) -> dict[str, Any]:
        outer = stored.get("claimed_outer") if isinstance(stored.get("claimed_outer"), dict) else state
        return invoke_adapter(_series_invocation(outer, invocation))

    def persist_generic_pending(generic_pending: dict[str, Any]) -> bool:
        claimed_outer = stored.get("claimed_outer")
        if not isinstance(claimed_outer, dict):
            return False
        series_pending = _wrap_generic_pending(claimed_outer, generic_pending)
        try:
            saved = persist_pending(copy.deepcopy(series_pending)) is True
        except Exception:
            saved = False
        if saved:
            stored["series_pending"] = series_pending
        else:
            stored["series_pending_candidate"] = series_pending
        return saved

    generic = async_dispatch.begin_async_dispatch(
        copy.deepcopy(state["executor_state"]),
        now,
        worker_id,
        persist_claim=persist_inner_claim,
        invoke_adapter=invoke_series,
        persist_pending=persist_generic_pending,
        lease_seconds=lease_seconds,
    )

    claimed_outer = stored.get("claimed_outer") if isinstance(stored.get("claimed_outer"), dict) else state
    decision = _clean(generic.get("decision"))
    if decision == "ASYNC_REMOTE_PENDING":
        return {
            "schema_version": SCHEMA_VERSION,
            "publication_kind": PUBLICATION_KIND,
            "blocked": False,
            "hard_blocks": [],
            "decision": "SERIES_ASYNC_REMOTE_PENDING",
            "state": copy.deepcopy(claimed_outer),
            "pending": copy.deepcopy(stored["series_pending"]),
            "remote_submission_id": _clean(generic.get("remote_submission_id")),
            "publication_status": "PUBLISHING",
            "claim_persisted_before_adapter": True,
            "pending_persisted_after_submission": True,
            "adapter_invoked": True,
            "publication_confirmed": False,
            "blind_retry_allowed": False,
        }

    result = copy.deepcopy(generic)
    result["publication_kind"] = PUBLICATION_KIND
    result["state"] = copy.deepcopy(claimed_outer)
    result["blind_retry_allowed"] = False
    if decision == "PENDING_PERSIST_CONFLICT_RECONCILIATION_REQUIRED" and isinstance(stored.get("series_pending_candidate"), dict):
        result.pop("candidate_pending", None)
        result["candidate_pending"] = copy.deepcopy(stored["series_pending_candidate"])
    return result


def reconcile_series_async_dispatch(
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
    """Poll one submitted recurring series and finalize only with remote proof."""
    if not isinstance(state, dict) or not isinstance(pending, dict):
        raise TypeError("state and pending must be mappings")
    if not callable(fetch_remote_status):
        raise TypeError("fetch_remote_status must be callable")
    if persist_pending is not None and not callable(persist_pending):
        raise TypeError("persist_pending must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable")

    blocks = _pending_blocks(state, pending)
    if blocks:
        return _blocked(state, blocks)

    stored: dict[str, Any] = {"updated_pending": None, "result_outer": None}
    outer_fp = _clean(state.get("state_fingerprint_sha256"))
    inner_fp = _clean((state.get("executor_state") or {}).get("state_fingerprint_sha256"))
    pending_fp = _clean(pending.get("pending_fingerprint_sha256"))

    def fetch_generic_status(generic_pending: dict[str, Any]) -> dict[str, Any]:
        return fetch_remote_status(copy.deepcopy(pending))

    def persist_generic_pending(expected_generic_fp: str, updated_generic: dict[str, Any]) -> bool:
        generic_current = pending.get("generic_pending") if isinstance(pending.get("generic_pending"), dict) else {}
        if _clean(expected_generic_fp) != _clean(generic_current.get("pending_fingerprint_sha256")):
            return False
        updated_series = _wrap_generic_pending(state, updated_generic)
        updated_series["claimed_series_state_fingerprint_sha256"] = outer_fp
        updated_series = _seal_pending(updated_series)
        if persist_pending is None:
            stored["updated_pending"] = updated_series
            return True
        try:
            saved = persist_pending(pending_fp, copy.deepcopy(updated_series)) is True
        except Exception:
            saved = False
        if saved:
            stored["updated_pending"] = updated_series
        return saved

    def persist_generic_result(expected: str, candidate_inner: dict[str, Any]) -> bool:
        if _clean(expected) != inner_fp:
            return False
        try:
            candidate_outer = series_executor._sync(state, candidate_inner)
        except Exception:
            return False
        if persist_result is None:
            stored["result_outer"] = candidate_outer
            return True
        try:
            saved = persist_result(outer_fp, copy.deepcopy(candidate_outer)) is True
        except Exception:
            saved = False
        if saved:
            stored["result_outer"] = candidate_outer
        return saved

    generic = async_dispatch.reconcile_async_dispatch(
        copy.deepcopy(state["executor_state"]),
        copy.deepcopy(pending["generic_pending"]),
        now,
        fetch_remote_status=fetch_generic_status,
        persist_pending=persist_generic_pending if _clean((pending.get("generic_pending") or {}).get("provider_status")) is not None else None,
        persist_result=persist_generic_result,
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )

    decision = _clean(generic.get("decision"))
    result = copy.deepcopy(generic)
    result["publication_kind"] = PUBLICATION_KIND
    result["series_id"] = _clean(state.get("series_id")) or None
    result["series_execution_id"] = _clean(state.get("series_execution_id")) or None
    result["series_slot_key"] = _clean(state.get("series_slot_key")) or None
    result["source_story_ids"] = _source_story_ids(state)
    result["blind_retry_allowed"] = False

    if decision == "REMOTE_STILL_PENDING":
        updated = stored.get("updated_pending")
        if not isinstance(updated, dict):
            updated = _wrap_generic_pending(state, generic.get("pending") or pending["generic_pending"])
        result["state"] = copy.deepcopy(state)
        result["pending"] = copy.deepcopy(updated)
        result["publication_status"] = "PUBLISHING"
        result["publication_confirmed"] = False
        return result

    final_outer = stored.get("result_outer")
    if isinstance(final_outer, dict) and decision not in {"RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED", "RECONCILIATION_REQUIRED"}:
        result["state"] = copy.deepcopy(final_outer)
        record = series_executor._series_record(final_outer) or {}
        result["record"] = copy.deepcopy(record)
        result["publication_status"] = _clean(record.get("status"))
    else:
        result["state"] = copy.deepcopy(state)
    result["remote_submission_id"] = _clean(pending.get("remote_submission_id"))
    result["async_reconciliation_completed"] = decision in {"PUBLISHED", "FAILED_TERMINAL", "BLOCKED_AUTH", "RETRY_SCHEDULED"}
    return result
