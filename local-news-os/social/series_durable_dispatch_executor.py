#!/usr/bin/env python3
"""Crash-safe dispatch execution for recurring LOCAL NEWS OS social series.

This adapter composes the existing generic ``durable_dispatch_executor`` with the
recurring-series state/outbox contract produced by ``series_adapter_dispatch_handoff``.
It does not select channels, formats or media and never reads credential values.

Only a truthful ``DIRECT_READY`` recurring-series handoff may initialize an
executor state. The exact multi-story native product stays immutable while the
publication is claimed, attempted, retried, reconciled and finally proven by a
``remote_publication_id``. A PUBLISHING lease is persisted before any adapter
callback may run; an expired/ambiguous lease requires explicit remote
reconciliation and is never blindly resent.
"""
from __future__ import annotations

import copy
import hashlib
import json
from typing import Any, Callable

import durable_dispatch_executor as executor
import publication_state

SCHEMA_VERSION = "1.0"
PUBLICATION_KIND = "recurring_series"
SECRET_KEY_PARTS = (
    "access_token", "refresh_token", "secret", "password", "authorization",
    "api_key", "apikey", "client_secret", "credential_value",
)
PREDICTIVE_KEYS = {
    "predicted_views", "predicted_reach", "predicted_engagement", "predicted_ctr",
    "predicted_shares", "predicted_saves", "virality_probability", "expected_views",
    "expected_reach", "expected_engagement", "forecast_views",
}
SYNC_RECORD_FIELDS = (
    "status", "state_reason", "attempt_count", "attempts", "remote_publication_id",
    "next_attempt_at", "published_at", "dispatch_execution", "dispatch_history",
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


def _contains_key(value: Any, *, exact: set[str] | None = None, parts: tuple[str, ...] = ()) -> bool:
    exact = exact or set()
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = _clean(key).casefold()
            if lowered in exact or any(part in lowered for part in parts):
                return True
            if _contains_key(child, exact=exact, parts=parts):
                return True
    elif isinstance(value, list):
        return any(_contains_key(item, exact=exact, parts=parts) for item in value)
    return False


def _seal(state: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(state)
    candidate.pop("state_fingerprint_sha256", None)
    candidate["state_fingerprint_sha256"] = _digest(candidate)
    return candidate


def _fingerprint_ok(state: dict[str, Any]) -> bool:
    supplied = _clean(state.get("state_fingerprint_sha256")).lower()
    if not _is_sha256(supplied):
        return False
    candidate = copy.deepcopy(state)
    candidate.pop("state_fingerprint_sha256", None)
    return supplied == _digest(candidate)


def _blocked(state: dict[str, Any] | None, reasons: list[str], *, adapter_invoked: bool = False) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": True,
        "hard_blocks": sorted(set(str(reason) for reason in reasons)),
        "decision": "BLOCKED_SERIES_DURABLE_DISPATCH",
        "state": copy.deepcopy(state) if isinstance(state, dict) else None,
        "adapter_invoked": adapter_invoked,
    }


def _handoff_item(dispatch_outbox: dict[str, Any], handoff_id: str) -> dict[str, Any] | None:
    items = dispatch_outbox.get("items") if isinstance(dispatch_outbox.get("items"), dict) else {}
    item = items.get(_clean(handoff_id))
    return item if isinstance(item, dict) else None


def _series_record(state: dict[str, Any]) -> dict[str, Any] | None:
    series_state = state.get("series_publication_state") if isinstance(state.get("series_publication_state"), dict) else {}
    records = series_state.get("records") if isinstance(series_state.get("records"), dict) else {}
    record = records.get(_clean(state.get("publication_id")))
    return record if isinstance(record, dict) else None


def _series_outbox_item(state: dict[str, Any]) -> dict[str, Any] | None:
    outbox = state.get("series_publication_outbox") if isinstance(state.get("series_publication_outbox"), dict) else {}
    items = outbox.get("items") if isinstance(outbox.get("items"), list) else []
    matches = [item for item in items if isinstance(item, dict) and _clean(item.get("publication_id")) == _clean(state.get("publication_id"))]
    return matches[0] if len(matches) == 1 else None


def _executor_record(inner: dict[str, Any]) -> dict[str, Any] | None:
    ledger = inner.get("ledger") if isinstance(inner.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    outbox = inner.get("outbox") if isinstance(inner.get("outbox"), dict) else {}
    item = _handoff_item(outbox, _clean(inner.get("handoff_id")))
    if item is None:
        return None
    record = records.get(_clean(item.get("publication_id")))
    return record if isinstance(record, dict) else None


def _story_ids_from_product(product: dict[str, Any]) -> list[str]:
    return [
        _clean(item.get("story_id"))
        for item in product.get("items", [])
        if isinstance(item, dict) and _clean(item.get("story_id"))
    ]


def _initial_handoff_blocks(result: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(result.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("HANDOFF_SCHEMA_VERSION")
    if result.get("blocked") is True:
        blocks.append("HANDOFF_BLOCKED")
    if _clean(result.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_NOT_DIRECT_READY")

    guards = result.get("guards") if isinstance(result.get("guards"), dict) else {}
    expected_guards = {
        "channel_native_series_only": True,
        "native_product_rewritten": False,
        "credential_values_read": False,
        "credential_values_exposed": False,
        "network_dispatch_performed": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "predictive_analytics_used": False,
        "paid_scheduler_used": False,
        "paid_llm_api_used": False,
        "zero_paid_dependency": True,
    }
    for key, expected in expected_guards.items():
        if guards.get(key) is not expected:
            blocks.append("HANDOFF_GUARD_INVALID:" + key)

    bundle = result.get("commit_bundle") if isinstance(result.get("commit_bundle"), dict) else {}
    supplied_bundle_fp = _clean(result.get("bundle_fingerprint_sha256")).lower()
    if not bundle:
        blocks.append("MISSING_HANDOFF_COMMIT_BUNDLE")
        return sorted(set(blocks))
    if not _is_sha256(supplied_bundle_fp) or supplied_bundle_fp != _digest(bundle):
        blocks.append("HANDOFF_BUNDLE_FINGERPRINT_INVALID")
    if bundle.get("atomic_persist_required") is not True:
        blocks.append("HANDOFF_ATOMIC_PERSIST_REQUIRED")
    if bundle.get("network_dispatch_performed") is not False:
        blocks.append("HANDOFF_BUNDLE_NETWORK_ALREADY_PERFORMED")

    instance_id = _clean(result.get("instance_id"))
    channel_id = _clean(result.get("channel_id"))
    platform = _platform(result.get("platform"))
    publication_id = _clean(bundle.get("publication_id"))
    handoff_id = _clean(bundle.get("handoff_id"))
    for key, actual, expected in (
        ("INSTANCE", _clean(bundle.get("instance_id")), instance_id),
        ("CHANNEL", _clean(bundle.get("channel_id")), channel_id),
        ("PLATFORM", _platform(bundle.get("platform")), platform),
    ):
        if not actual or actual != expected:
            blocks.append(f"HANDOFF_BUNDLE_{key}_MISMATCH")
    if not publication_id:
        blocks.append("MISSING_PUBLICATION_ID")
    if not handoff_id:
        blocks.append("MISSING_HANDOFF_ID")

    handoff_meta = result.get("adapter_handoff") if isinstance(result.get("adapter_handoff"), dict) else {}
    if handoff_meta.get("dispatch_allowed") is not True:
        blocks.append("HANDOFF_DISPATCH_NOT_ALLOWED")
    if _clean(handoff_meta.get("handoff_id")) != handoff_id:
        blocks.append("HANDOFF_META_ID_MISMATCH")
    if handoff_meta.get("credential_values_exposed") is not False:
        blocks.append("HANDOFF_META_CREDENTIAL_VALUES_EXPOSED")

    series_state = bundle.get("series_publication_state") if isinstance(bundle.get("series_publication_state"), dict) else {}
    series_outbox = bundle.get("series_publication_outbox") if isinstance(bundle.get("series_publication_outbox"), dict) else {}
    dispatch_outbox = bundle.get("dispatch_handoff_outbox") if isinstance(bundle.get("dispatch_handoff_outbox"), dict) else {}
    if not series_state:
        blocks.append("MISSING_SERIES_PUBLICATION_STATE")
    if not series_outbox:
        blocks.append("MISSING_SERIES_PUBLICATION_OUTBOX")
    if not dispatch_outbox:
        blocks.append("MISSING_SERIES_DISPATCH_HANDOFF_OUTBOX")
    if blocks:
        return sorted(set(blocks))

    records = series_state.get("records") if isinstance(series_state.get("records"), dict) else {}
    record = records.get(publication_id)
    if not isinstance(record, dict):
        blocks.append("SERIES_PUBLICATION_RECORD_MISSING")
    elif _clean(record.get("status")) != "READY":
        blocks.append("SERIES_PUBLICATION_NOT_READY")

    series_items = series_outbox.get("items") if isinstance(series_outbox.get("items"), list) else []
    matches = [item for item in series_items if isinstance(item, dict) and _clean(item.get("publication_id")) == publication_id]
    if len(matches) != 1:
        blocks.append("SERIES_PUBLICATION_OUTBOX_ITEM_MISSING_OR_AMBIGUOUS")
    elif _clean(matches[0].get("status")) != "READY":
        blocks.append("SERIES_PUBLICATION_OUTBOX_ITEM_NOT_READY")

    handoff = _handoff_item(dispatch_outbox, handoff_id)
    if handoff is None:
        blocks.append("SERIES_HANDOFF_ITEM_MISSING")
        return sorted(set(blocks))
    if _clean(handoff.get("publication_kind")) != PUBLICATION_KIND:
        blocks.append("HANDOFF_PUBLICATION_KIND_MISMATCH")
    if _clean(handoff.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_ITEM_NOT_DIRECT_READY")
    if handoff.get("credential_values_included") is not False:
        blocks.append("HANDOFF_ITEM_CREDENTIAL_VALUES_INCLUDED")
    if handoff.get("network_dispatch_performed") is not False:
        blocks.append("HANDOFF_ITEM_ALREADY_DISPATCHED")
    if _clean(handoff.get("publication_id")) != publication_id:
        blocks.append("HANDOFF_ITEM_PUBLICATION_MISMATCH")
    supplied_handoff_fp = _clean(handoff.get("handoff_fingerprint_sha256")).lower()
    handoff_payload = copy.deepcopy(handoff)
    handoff_payload.pop("handoff_fingerprint_sha256", None)
    if not _is_sha256(supplied_handoff_fp) or supplied_handoff_fp != _digest(handoff_payload):
        blocks.append("HANDOFF_ITEM_FINGERPRINT_INVALID")

    payload = handoff.get("adapter_payload") if isinstance(handoff.get("adapter_payload"), dict) else {}
    payload_fp = _clean(handoff.get("adapter_payload_fingerprint_sha256")).lower()
    if not payload or not _is_sha256(payload_fp) or payload_fp != _digest(payload):
        blocks.append("HANDOFF_ADAPTER_PAYLOAD_FINGERPRINT_INVALID")
    else:
        if _clean(payload.get("publication_kind")) != PUBLICATION_KIND:
            blocks.append("ADAPTER_PAYLOAD_PUBLICATION_KIND_MISMATCH")
        if _clean(payload.get("publication_id")) != publication_id:
            blocks.append("ADAPTER_PAYLOAD_PUBLICATION_MISMATCH")
        if _clean(payload.get("instance_id")) != instance_id:
            blocks.append("ADAPTER_PAYLOAD_INSTANCE_MISMATCH")
        if _clean(payload.get("channel_id")) != channel_id:
            blocks.append("ADAPTER_PAYLOAD_CHANNEL_MISMATCH")
        if _platform(payload.get("platform")) != platform:
            blocks.append("ADAPTER_PAYLOAD_PLATFORM_MISMATCH")
        product = payload.get("native_product") if isinstance(payload.get("native_product"), dict) else {}
        if not product:
            blocks.append("MISSING_NATIVE_SERIES_PRODUCT")
        else:
            story_ids = _story_ids_from_product(product)
            if not story_ids or len(story_ids) != len(set(story_ids)):
                blocks.append("INVALID_NATIVE_SERIES_SOURCE_STORIES")
            if story_ids != [str(v) for v in payload.get("source_story_ids", [])]:
                blocks.append("SERIES_SOURCE_STORY_IDENTITY_DIVERGENCE")
            if product.get("verbatim_cross_platform_reuse_allowed") is not False:
                blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
            if product.get("zero_paid_dependency") is not True:
                blocks.append("PRODUCT_ZERO_PAID_DEPENDENCY_VIOLATION")
            if _contains_key(product, exact=PREDICTIVE_KEYS):
                blocks.append("PREDICTIVE_ANALYTICS_FORBIDDEN")
            if _contains_key(product, parts=SECRET_KEY_PARTS):
                blocks.append("SECRET_VALUE_IN_NATIVE_SERIES_PRODUCT")
    return sorted(set(blocks))


def _normalized_ledger(bundle: dict[str, Any]) -> dict[str, Any]:
    instance_id = _clean(bundle.get("instance_id"))
    channel_id = _clean(bundle.get("channel_id"))
    platform = _platform(bundle.get("platform"))
    publication_id = _clean(bundle.get("publication_id"))
    source_state = bundle["series_publication_state"]
    source_record = copy.deepcopy(source_state["records"][publication_id])
    source_record.setdefault("attempt_count", 0)
    source_record.setdefault("attempts", [])
    source_record.setdefault("remote_publication_id", None)
    source_record.setdefault("next_attempt_at", None)
    ledger = publication_state.empty_ledger(instance_id, channel_id, platform)
    ledger["records"][publication_id] = source_record
    return ledger


def _generic_bridge(result: dict[str, Any]) -> dict[str, Any]:
    bundle = result["commit_bundle"]
    generic_bundle = {
        "instance_id": _clean(bundle.get("instance_id")),
        "channel_id": _clean(bundle.get("channel_id")),
        "platform": _platform(bundle.get("platform")),
        "publication_id": _clean(bundle.get("publication_id")),
        "handoff_id": _clean(bundle.get("handoff_id")),
        "ledger": _normalized_ledger(bundle),
        "outbox": copy.deepcopy(bundle["dispatch_handoff_outbox"]),
        "atomic_persist_required": True,
        "network_dispatch_performed": False,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "dispatch_disposition": "DIRECT_READY",
        "instance_id": generic_bundle["instance_id"],
        "channel_id": generic_bundle["channel_id"],
        "platform": generic_bundle["platform"],
        "adapter_handoff": copy.deepcopy(result["adapter_handoff"]),
        "commit_bundle": generic_bundle,
        "bundle_fingerprint_sha256": _digest(generic_bundle),
        "guards": {
            "credential_values_read": False,
            "credential_values_exposed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def _sync_series_from_inner(state: dict[str, Any], inner: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(state)
    candidate["executor_state"] = copy.deepcopy(inner)
    inner_record = _executor_record(inner)
    series_record = _series_record(candidate)
    series_item = _series_outbox_item(candidate)
    if inner_record is None or series_record is None or series_item is None:
        raise ValueError("executor and recurring-series state diverged")

    for field in SYNC_RECORD_FIELDS:
        if field in inner_record:
            series_record[field] = copy.deepcopy(inner_record[field])
        else:
            series_record.pop(field, None)
    series_item["status"] = _clean(inner_record.get("status"))
    series_item["state_reason"] = _clean(inner_record.get("state_reason"))
    dispatch = series_item.setdefault("dispatch", {})
    if not isinstance(dispatch, dict):
        raise ValueError("series outbox dispatch metadata must be a mapping")
    dispatch["durable_executor_status"] = _clean(inner_record.get("status"))
    dispatch["network_dispatch_attempted"] = int(inner_record.get("attempt_count", 0) or 0) > 0
    dispatch["remote_publication_id"] = _clean(inner_record.get("remote_publication_id")) or None
    attempts = inner_record.get("attempts") if isinstance(inner_record.get("attempts"), list) else []
    dispatch["last_attempt_at"] = _clean((attempts[-1] if attempts else {}).get("attempted_at")) or None
    series_item["outbox_item_fingerprint_sha256"] = _digest({
        key: value for key, value in series_item.items() if key != "outbox_item_fingerprint_sha256"
    })

    candidate["revision"] = int(candidate.get("revision", 0)) + 1
    return _seal(candidate)


def _state_blocks(state: dict[str, Any]) -> list[str]:
    if not isinstance(state, dict):
        return ["STATE_NOT_MAPPING"]
    blocks: list[str] = []
    if _clean(state.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("STATE_SCHEMA_VERSION")
    if _clean(state.get("publication_kind")) != PUBLICATION_KIND:
        blocks.append("STATE_PUBLICATION_KIND")
    if not _fingerprint_ok(state):
        blocks.append("STATE_FINGERPRINT_INVALID")
    if not isinstance(state.get("revision"), int) or int(state.get("revision", -1)) < 0:
        blocks.append("STATE_REVISION_INVALID")

    inner = state.get("executor_state") if isinstance(state.get("executor_state"), dict) else {}
    if not inner:
        blocks.append("MISSING_GENERIC_EXECUTOR_STATE")
        return sorted(set(blocks))
    generic_blocks = executor._validate_state(inner)
    blocks.extend("GENERIC_EXECUTOR:" + reason for reason in generic_blocks)

    instance_id = _clean(state.get("instance_id"))
    channel_id = _clean(state.get("channel_id"))
    platform = _platform(state.get("platform"))
    if _clean(inner.get("instance_id")) != instance_id:
        blocks.append("EXECUTOR_INSTANCE_MISMATCH")
    if _clean(inner.get("channel_id")) != channel_id:
        blocks.append("EXECUTOR_CHANNEL_MISMATCH")
    if _platform(inner.get("platform")) != platform:
        blocks.append("EXECUTOR_PLATFORM_MISMATCH")
    if _clean(inner.get("handoff_id")) != _clean(state.get("handoff_id")):
        blocks.append("EXECUTOR_HANDOFF_MISMATCH")

    series_state = state.get("series_publication_state") if isinstance(state.get("series_publication_state"), dict) else {}
    series_outbox = state.get("series_publication_outbox") if isinstance(state.get("series_publication_outbox"), dict) else {}
    for name, doc in (("SERIES_STATE", series_state), ("SERIES_OUTBOX", series_outbox)):
        if _clean(doc.get("instance_id")) != instance_id:
            blocks.append(f"{name}_INSTANCE_MISMATCH")
        if _clean(doc.get("channel_id")) != channel_id:
            blocks.append(f"{name}_CHANNEL_MISMATCH")
        if _platform(doc.get("platform")) != platform:
            blocks.append(f"{name}_PLATFORM_MISMATCH")
        if doc.get("zero_paid_dependency") is not True:
            blocks.append(f"{name}_ZERO_PAID_DEPENDENCY")

    series_record = _series_record(state)
    series_item = _series_outbox_item(state)
    inner_record = _executor_record(inner)
    if series_record is None:
        blocks.append("SERIES_RECORD_MISSING")
    if series_item is None:
        blocks.append("SERIES_OUTBOX_ITEM_MISSING_OR_AMBIGUOUS")
    if inner_record is None:
        blocks.append("EXECUTOR_RECORD_MISSING")
    if series_record is not None and inner_record is not None:
        for field in ("publication_id", "dedupe_key", "instance_id", "channel_id", "platform", "product_id", "product_fingerprint_sha256", "status"):
            left = _platform(series_record.get(field)) if field == "platform" else _clean(series_record.get(field))
            right = _platform(inner_record.get(field)) if field == "platform" else _clean(inner_record.get(field))
            if left != right:
                blocks.append("SERIES_EXECUTOR_RECORD_DIVERGENCE:" + field)
        for field in ("attempt_count", "remote_publication_id", "next_attempt_at"):
            if series_record.get(field) != inner_record.get(field):
                blocks.append("SERIES_EXECUTOR_RECORD_DIVERGENCE:" + field)
    if series_item is not None and inner_record is not None and _clean(series_item.get("status")) != _clean(inner_record.get("status")):
        blocks.append("SERIES_OUTBOX_STATUS_DIVERGENCE")

    dispatch_copy = state.get("dispatch_handoff_outbox") if isinstance(state.get("dispatch_handoff_outbox"), dict) else {}
    if not dispatch_copy or dispatch_copy != inner.get("outbox"):
        blocks.append("DISPATCH_HANDOFF_OUTBOX_DIVERGENCE")
    handoff = _handoff_item(inner.get("outbox") if isinstance(inner.get("outbox"), dict) else {}, _clean(state.get("handoff_id")))
    if series_item is not None:
        supplied_item_fp = _clean(series_item.get("outbox_item_fingerprint_sha256")).lower()
        item_payload = copy.deepcopy(series_item)
        item_payload.pop("outbox_item_fingerprint_sha256", None)
        if not _is_sha256(supplied_item_fp) or supplied_item_fp != _digest(item_payload):
            blocks.append("SERIES_OUTBOX_ITEM_FINGERPRINT_INVALID")
    if series_item is not None and handoff is not None:
        payload = handoff.get("adapter_payload") if isinstance(handoff.get("adapter_payload"), dict) else {}
        native = payload.get("native_product") if isinstance(payload.get("native_product"), dict) else {}
        current_product = series_item.get("product") if isinstance(series_item.get("product"), dict) else {}
        if current_product != native:
            blocks.append("NATIVE_SERIES_PRODUCT_MUTATED_AFTER_HANDOFF")
        if _story_ids_from_product(current_product) != [str(v) for v in payload.get("source_story_ids", [])]:
            blocks.append("SERIES_SOURCE_STORY_IDENTITY_DIVERGENCE")

    guards = state.get("guards") if isinstance(state.get("guards"), dict) else {}
    expected_guards = {
        "claim_persisted_before_adapter_required": True,
        "ambiguous_crash_requires_remote_reconciliation": True,
        "native_multi_story_product_preserved": True,
        "credential_values_read": False,
        "credential_values_exposed": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "paid_scheduler_used": False,
        "paid_llm_api_used": False,
        "zero_paid_dependency": True,
    }
    for key, expected in expected_guards.items():
        if guards.get(key) is not expected:
            blocks.append("STATE_GUARD_INVALID:" + key)
    return sorted(set(blocks))


def initialize_series_dispatch_state(handoff_result: dict[str, Any]) -> dict[str, Any]:
    """Initialize crash-safe executor state from one DIRECT_READY series handoff."""
    if not isinstance(handoff_result, dict):
        raise TypeError("handoff_result must be a mapping")
    blocks = _initial_handoff_blocks(handoff_result)
    if blocks:
        return _blocked(None, blocks)

    generic = executor.initialize_dispatch_state(_generic_bridge(handoff_result))
    if generic.get("blocked") is True:
        return _blocked(None, ["GENERIC_EXECUTOR_INIT:" + str(reason) for reason in generic.get("hard_blocks", [])])

    bundle = handoff_result["commit_bundle"]
    state = {
        "schema_version": SCHEMA_VERSION,
        "publication_kind": PUBLICATION_KIND,
        "instance_id": _clean(bundle.get("instance_id")),
        "channel_id": _clean(bundle.get("channel_id")),
        "platform": _platform(bundle.get("platform")),
        "publication_id": _clean(bundle.get("publication_id")),
        "handoff_id": _clean(bundle.get("handoff_id")),
        "series_id": _clean(handoff_result.get("series_id")),
        "series_execution_id": _clean(handoff_result.get("series_execution_id")),
        "series_slot_key": _clean(handoff_result.get("series_slot_key")),
        "source_handoff_bundle_fingerprint_sha256": _clean(handoff_result.get("bundle_fingerprint_sha256")),
        "revision": 0,
        "series_publication_state": copy.deepcopy(bundle["series_publication_state"]),
        "series_publication_outbox": copy.deepcopy(bundle["series_publication_outbox"]),
        "dispatch_handoff_outbox": copy.deepcopy(bundle["dispatch_handoff_outbox"]),
        "executor_state": copy.deepcopy(generic["state"]),
        "guards": {
            "direct_ready_only": True,
            "claim_persisted_before_adapter_required": True,
            "ambiguous_crash_requires_remote_reconciliation": True,
            "remote_publication_id_required_for_published": True,
            "native_multi_story_product_preserved": True,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_analytics_used": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }
    state = _sync_series_from_inner(_seal(state), generic["state"])
    blocks = _state_blocks(state)
    if blocks:
        return _blocked(state, blocks)
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "SERIES_DISPATCH_STATE_INITIALIZED",
        "state": state,
        "adapter_invoked": False,
    }


def claim_series_dispatch(state: dict[str, Any], now: str, worker_id: str, *, lease_seconds: int = executor.DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
    """Claim one recurring-series publication; caller must CAS-persist before network."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    blocks = _state_blocks(state)
    if blocks:
        return _blocked(state, blocks)
    inner_result = executor.claim_dispatch(copy.deepcopy(state["executor_state"]), now, worker_id, lease_seconds=lease_seconds)
    if inner_result.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner_result.get("hard_blocks", [])])
    decision = _clean(inner_result.get("decision"))
    if decision != "CLAIMED":
        result = copy.deepcopy(inner_result)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result

    candidate = _sync_series_from_inner(state, inner_result["state"])
    invocation = copy.deepcopy(inner_result.get("adapter_invocation"))
    if isinstance(invocation, dict):
        invocation["publication_kind"] = PUBLICATION_KIND
        invocation["series_id"] = _clean(state.get("series_id"))
        invocation["series_execution_id"] = _clean(state.get("series_execution_id"))
        invocation["series_slot_key"] = _clean(state.get("series_slot_key"))
        payload = invocation.get("adapter_payload") if isinstance(invocation.get("adapter_payload"), dict) else {}
        invocation["source_story_ids"] = copy.deepcopy(payload.get("source_story_ids") or [])
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": "CLAIMED",
        "publication_kind": PUBLICATION_KIND,
        "state": candidate,
        "claim_token": _clean(inner_result.get("claim_token")),
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "claimed_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "persist_before_adapter_required": True,
        "adapter_invoked": False,
        "adapter_invocation": invocation,
    }


def reconcile_series_adapter_result(
    state: dict[str, Any], claim_token: str, attempted_at: str, adapter_result: dict[str, Any], *,
    max_attempts: int = 5, base_delay_seconds: int = 60, max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """Reconcile one sanitized adapter result and synchronize series state/outbox."""
    if not isinstance(state, dict) or not isinstance(adapter_result, dict):
        raise TypeError("state and adapter_result must be mappings")
    blocks = _state_blocks(state)
    if blocks:
        return _blocked(state, blocks)
    inner = executor.reconcile_adapter_result(
        copy.deepcopy(state["executor_state"]), claim_token, attempted_at, copy.deepcopy(adapter_result),
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    decision = _clean(inner.get("decision"))
    if inner.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner.get("hard_blocks", [])], adapter_invoked=True)
    if decision == "RECONCILIATION_REQUIRED":
        result = copy.deepcopy(inner)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result

    candidate = _sync_series_from_inner(state, inner["state"])
    final_record = _series_record(candidate) or {}
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "publication_kind": PUBLICATION_KIND,
        "publication_status": _clean(final_record.get("status")),
        "record": copy.deepcopy(final_record),
        "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "adapter_invoked": True,
    }


def recover_stale_series_claim(
    state: dict[str, Any], now: str, *, remote_publication_id: str | None = None, remote_absent_confirmed: bool = False,
) -> dict[str, Any]:
    """Resolve an expired series claim only from explicit remote evidence."""
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    blocks = _state_blocks(state)
    if blocks:
        return _blocked(state, blocks)
    inner = executor.recover_stale_claim(
        copy.deepcopy(state["executor_state"]), now,
        remote_publication_id=remote_publication_id,
        remote_absent_confirmed=remote_absent_confirmed,
    )
    if inner.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner.get("hard_blocks", [])])
    decision = _clean(inner.get("decision"))
    if decision in {"LEASE_HELD", "RECONCILIATION_REQUIRED"}:
        result = copy.deepcopy(inner)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result
    candidate = _sync_series_from_inner(state, inner["state"])
    return {
        "schema_version": SCHEMA_VERSION,
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "publication_kind": PUBLICATION_KIND,
        "publication_status": _clean((_series_record(candidate) or {}).get("status")),
        "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True,
        "adapter_invoked": False,
    }


def execute_series_dispatch(
    state: dict[str, Any], now: str, worker_id: str, *,
    persist_claim: Callable[[str, dict[str, Any]], bool],
    invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_result: Callable[[str, dict[str, Any]], bool] | None = None,
    lease_seconds: int = executor.DEFAULT_LEASE_SECONDS,
    max_attempts: int = 5,
    base_delay_seconds: int = 60,
    max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    """CAS-persist claim, invoke exact adapter once, then CAS-persist reconciled state."""
    if not callable(persist_claim) or not callable(invoke_adapter):
        raise TypeError("persist_claim and invoke_adapter must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable when provided")

    claim = claim_series_dispatch(state, now, worker_id, lease_seconds=lease_seconds)
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
            "reason": "ADAPTER_NOT_INVOKED_BECAUSE_SERIES_PUBLISHING_CLAIM_WAS_NOT_DURABLE",
            "state": copy.deepcopy(state),
            "adapter_invoked": False,
        }

    claimed_state = claim["state"]
    try:
        adapter_result = invoke_adapter(copy.deepcopy(claim["adapter_invocation"]))
        if not isinstance(adapter_result, dict):
            adapter_result = {"success": False, "error_class": "transient", "error_code": "ADAPTER_RESULT_NOT_MAPPING"}
    except Exception as exc:
        adapter_result = {"success": False, "error_class": "network_error", "error_code": "ADAPTER_EXCEPTION_" + type(exc).__name__.upper()}

    reconciled = reconcile_series_adapter_result(
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
            result_saved = persist_result(
                _clean(claimed_state.get("state_fingerprint_sha256")),
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
                "reason": "ADAPTER_ALREADY_INVOKED_SERIES_STATE_REMAINS_PUBLISHING",
                "state": copy.deepcopy(claimed_state),
                "candidate_result_state_fingerprint_sha256": _clean(reconciled.get("result_state_fingerprint_sha256")),
                "adapter_invoked": True,
            }
    reconciled["claim_persisted_before_adapter"] = True
    reconciled["result_persisted"] = persist_result is not None
    return reconciled
