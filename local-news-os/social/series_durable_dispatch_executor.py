#!/usr/bin/env python3
"""Crash-safe execution/reconciliation for recurring social-series handoffs.

The module deliberately composes the existing ``durable_dispatch_executor``.
It adds only the recurring-series durability contract around it: the exact
multi-story native product, ordered source-story identity, channel-local series
state and series outbox must remain synchronized while the generic executor owns
PUBLISHING claims, retry/backoff and remote-publication proof.

No credential values are accepted here and no network client is embedded. The
caller injects the exact adapter callback after a compare-and-swap claim has
been durably persisted.
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
PREDICTIVE_KEYS = {
    "predicted_views", "predicted_reach", "predicted_engagement", "predicted_ctr",
    "predicted_shares", "predicted_saves", "virality_probability", "expected_views",
    "expected_reach", "expected_engagement", "forecast_views",
}
# Exact names only: durable safety markers such as credential_values_read=False
# are policy assertions, not credential values, and must remain valid products.
SECRET_KEYS = {
    "access_token", "refresh_token", "token", "secret", "password", "api_key",
    "apikey", "client_secret", "credential_value", "credential_values",
    "authorization", "bearer",
}
SYNC_FIELDS = (
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


def _contains_exact_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _clean(key).casefold() in keys or _contains_exact_key(child, keys):
                return True
    elif isinstance(value, list):
        return any(_contains_exact_key(item, keys) for item in value)
    return False


def _seal(value: dict[str, Any]) -> dict[str, Any]:
    result = copy.deepcopy(value)
    result.pop("state_fingerprint_sha256", None)
    result["state_fingerprint_sha256"] = _digest(result)
    return result


def _fingerprint_ok(value: dict[str, Any]) -> bool:
    supplied = _clean(value.get("state_fingerprint_sha256")).lower()
    if not _is_sha256(supplied):
        return False
    candidate = copy.deepcopy(value)
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


def _handoff(outbox: dict[str, Any], handoff_id: str) -> dict[str, Any] | None:
    items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
    item = items.get(_clean(handoff_id))
    return item if isinstance(item, dict) else None


def _series_record(state: dict[str, Any]) -> dict[str, Any] | None:
    container = state.get("series_publication_state") if isinstance(state.get("series_publication_state"), dict) else {}
    records = container.get("records") if isinstance(container.get("records"), dict) else {}
    record = records.get(_clean(state.get("publication_id")))
    return record if isinstance(record, dict) else None


def _series_item(state: dict[str, Any]) -> dict[str, Any] | None:
    container = state.get("series_publication_outbox") if isinstance(state.get("series_publication_outbox"), dict) else {}
    items = container.get("items") if isinstance(container.get("items"), list) else []
    matches = [row for row in items if isinstance(row, dict) and _clean(row.get("publication_id")) == _clean(state.get("publication_id"))]
    return matches[0] if len(matches) == 1 else None


def _inner_record(inner: dict[str, Any]) -> dict[str, Any] | None:
    outbox = inner.get("outbox") if isinstance(inner.get("outbox"), dict) else {}
    item = _handoff(outbox, _clean(inner.get("handoff_id")))
    if item is None:
        return None
    ledger = inner.get("ledger") if isinstance(inner.get("ledger"), dict) else {}
    records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
    record = records.get(_clean(item.get("publication_id")))
    return record if isinstance(record, dict) else None


def _story_ids(product: dict[str, Any]) -> list[str]:
    return [
        _clean(row.get("story_id"))
        for row in product.get("items", [])
        if isinstance(row, dict) and _clean(row.get("story_id"))
    ]


def _validate_handoff_result(result: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(result.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("HANDOFF_SCHEMA_VERSION")
    if result.get("blocked") is True:
        blocks.append("HANDOFF_BLOCKED")
    if _clean(result.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_NOT_DIRECT_READY")

    guards = result.get("guards") if isinstance(result.get("guards"), dict) else {}
    expected = {
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
    for key, value in expected.items():
        if guards.get(key) is not value:
            blocks.append("HANDOFF_GUARD_INVALID:" + key)

    bundle = result.get("commit_bundle") if isinstance(result.get("commit_bundle"), dict) else {}
    supplied_bundle_fp = _clean(result.get("bundle_fingerprint_sha256")).lower()
    if not bundle:
        return sorted(set(blocks + ["MISSING_HANDOFF_COMMIT_BUNDLE"]))
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
    for label, actual, wanted in (
        ("INSTANCE", _clean(bundle.get("instance_id")), instance_id),
        ("CHANNEL", _clean(bundle.get("channel_id")), channel_id),
        ("PLATFORM", _platform(bundle.get("platform")), platform),
    ):
        if not actual or actual != wanted:
            blocks.append("HANDOFF_BUNDLE_" + label + "_MISMATCH")
    if not publication_id:
        blocks.append("MISSING_PUBLICATION_ID")
    if not handoff_id:
        blocks.append("MISSING_HANDOFF_ID")

    meta = result.get("adapter_handoff") if isinstance(result.get("adapter_handoff"), dict) else {}
    if meta.get("dispatch_allowed") is not True:
        blocks.append("HANDOFF_DISPATCH_NOT_ALLOWED")
    if _clean(meta.get("handoff_id")) != handoff_id:
        blocks.append("HANDOFF_META_ID_MISMATCH")
    if meta.get("credential_values_exposed") is not False:
        blocks.append("HANDOFF_META_CREDENTIAL_VALUES_EXPOSED")

    series_state = bundle.get("series_publication_state") if isinstance(bundle.get("series_publication_state"), dict) else {}
    series_outbox = bundle.get("series_publication_outbox") if isinstance(bundle.get("series_publication_outbox"), dict) else {}
    dispatch_outbox = bundle.get("dispatch_handoff_outbox") if isinstance(bundle.get("dispatch_handoff_outbox"), dict) else {}
    record = (series_state.get("records") or {}).get(publication_id) if isinstance(series_state.get("records"), dict) else None
    if not isinstance(record, dict):
        blocks.append("SERIES_PUBLICATION_RECORD_MISSING")
    elif _clean(record.get("status")) != "READY":
        blocks.append("SERIES_PUBLICATION_NOT_READY")
    rows = series_outbox.get("items") if isinstance(series_outbox.get("items"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _clean(row.get("publication_id")) == publication_id]
    if len(matches) != 1:
        blocks.append("SERIES_PUBLICATION_OUTBOX_ITEM_MISSING_OR_AMBIGUOUS")
    elif _clean(matches[0].get("status")) != "READY":
        blocks.append("SERIES_PUBLICATION_OUTBOX_ITEM_NOT_READY")

    handoff = _handoff(dispatch_outbox, handoff_id)
    if handoff is None:
        return sorted(set(blocks + ["SERIES_HANDOFF_ITEM_MISSING"]))
    if _clean(handoff.get("publication_kind")) != PUBLICATION_KIND:
        blocks.append("HANDOFF_PUBLICATION_KIND_MISMATCH")
    if _clean(handoff.get("dispatch_disposition")) != "DIRECT_READY":
        blocks.append("HANDOFF_ITEM_NOT_DIRECT_READY")
    if handoff.get("credential_values_included") is not False:
        blocks.append("HANDOFF_ITEM_CREDENTIAL_VALUES_INCLUDED")
    if handoff.get("network_dispatch_performed") is not False:
        blocks.append("HANDOFF_ITEM_ALREADY_DISPATCHED")
    handoff_fp = _clean(handoff.get("handoff_fingerprint_sha256")).lower()
    handoff_body = copy.deepcopy(handoff)
    handoff_body.pop("handoff_fingerprint_sha256", None)
    if not _is_sha256(handoff_fp) or handoff_fp != _digest(handoff_body):
        blocks.append("HANDOFF_ITEM_FINGERPRINT_INVALID")

    payload = handoff.get("adapter_payload") if isinstance(handoff.get("adapter_payload"), dict) else {}
    payload_fp = _clean(handoff.get("adapter_payload_fingerprint_sha256")).lower()
    if not payload or not _is_sha256(payload_fp) or payload_fp != _digest(payload):
        return sorted(set(blocks + ["HANDOFF_ADAPTER_PAYLOAD_FINGERPRINT_INVALID"]))
    for label, actual, wanted in (
        ("INSTANCE", _clean(payload.get("instance_id")), instance_id),
        ("CHANNEL", _clean(payload.get("channel_id")), channel_id),
        ("PLATFORM", _platform(payload.get("platform")), platform),
        ("PUBLICATION", _clean(payload.get("publication_id")), publication_id),
    ):
        if actual != wanted:
            blocks.append("ADAPTER_PAYLOAD_" + label + "_MISMATCH")
    if _clean(payload.get("publication_kind")) != PUBLICATION_KIND:
        blocks.append("ADAPTER_PAYLOAD_PUBLICATION_KIND_MISMATCH")

    product = payload.get("native_product") if isinstance(payload.get("native_product"), dict) else {}
    stories = _story_ids(product)
    if not product or not stories or len(stories) != len(set(stories)):
        blocks.append("INVALID_NATIVE_SERIES_SOURCE_STORIES")
    if stories != [str(value) for value in payload.get("source_story_ids", [])]:
        blocks.append("SERIES_SOURCE_STORY_IDENTITY_DIVERGENCE")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
    if product.get("zero_paid_dependency") is not True:
        blocks.append("PRODUCT_ZERO_PAID_DEPENDENCY_VIOLATION")
    if _contains_exact_key(product, PREDICTIVE_KEYS):
        blocks.append("PREDICTIVE_ANALYTICS_FORBIDDEN")
    if _contains_exact_key(product, SECRET_KEYS):
        blocks.append("SECRET_VALUE_IN_NATIVE_SERIES_PRODUCT")
    return sorted(set(blocks))


def _normalized_ledger(bundle: dict[str, Any]) -> dict[str, Any]:
    instance_id = _clean(bundle.get("instance_id"))
    channel_id = _clean(bundle.get("channel_id"))
    platform = _platform(bundle.get("platform"))
    publication_id = _clean(bundle.get("publication_id"))
    record = copy.deepcopy(bundle["series_publication_state"]["records"][publication_id])
    record.setdefault("attempt_count", 0)
    record.setdefault("attempts", [])
    record.setdefault("remote_publication_id", None)
    record.setdefault("next_attempt_at", None)
    ledger = publication_state.empty_ledger(instance_id, channel_id, platform)
    ledger["records"][publication_id] = record
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


def _sync(state: dict[str, Any], inner: dict[str, Any]) -> dict[str, Any]:
    candidate = copy.deepcopy(state)
    candidate["executor_state"] = copy.deepcopy(inner)
    candidate["dispatch_handoff_outbox"] = copy.deepcopy(inner.get("outbox"))
    source_record = _series_record(candidate)
    source_item = _series_item(candidate)
    inner_record = _inner_record(inner)
    if source_record is None or source_item is None or inner_record is None:
        raise ValueError("recurring-series and generic executor state diverged")
    for field in SYNC_FIELDS:
        if field in inner_record:
            source_record[field] = copy.deepcopy(inner_record[field])
        else:
            source_record.pop(field, None)
    source_item["status"] = _clean(inner_record.get("status"))
    source_item["state_reason"] = _clean(inner_record.get("state_reason"))
    dispatch = source_item.setdefault("dispatch", {})
    if not isinstance(dispatch, dict):
        raise ValueError("series outbox dispatch metadata must be a mapping")
    dispatch["durable_executor_status"] = _clean(inner_record.get("status"))
    dispatch["network_dispatch_attempted"] = int(inner_record.get("attempt_count", 0) or 0) > 0
    dispatch["remote_publication_id"] = _clean(inner_record.get("remote_publication_id")) or None
    attempts = inner_record.get("attempts") if isinstance(inner_record.get("attempts"), list) else []
    dispatch["last_attempt_at"] = _clean((attempts[-1] if attempts else {}).get("attempted_at")) or None
    source_item["outbox_item_fingerprint_sha256"] = _digest({
        key: value for key, value in source_item.items() if key != "outbox_item_fingerprint_sha256"
    })
    candidate["revision"] = int(candidate.get("revision", 0)) + 1
    return _seal(candidate)


def _validate_state(state: dict[str, Any]) -> list[str]:
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
        return sorted(set(blocks + ["MISSING_GENERIC_EXECUTOR_STATE"]))
    blocks.extend("GENERIC_EXECUTOR:" + reason for reason in executor._validate_state(inner))
    for label, actual, wanted in (
        ("INSTANCE", _clean(inner.get("instance_id")), _clean(state.get("instance_id"))),
        ("CHANNEL", _clean(inner.get("channel_id")), _clean(state.get("channel_id"))),
        ("PLATFORM", _platform(inner.get("platform")), _platform(state.get("platform"))),
        ("HANDOFF", _clean(inner.get("handoff_id")), _clean(state.get("handoff_id"))),
    ):
        if actual != wanted:
            blocks.append("EXECUTOR_" + label + "_MISMATCH")

    source_state = state.get("series_publication_state") if isinstance(state.get("series_publication_state"), dict) else {}
    source_outbox = state.get("series_publication_outbox") if isinstance(state.get("series_publication_outbox"), dict) else {}
    for label, doc in (("SERIES_STATE", source_state), ("SERIES_OUTBOX", source_outbox)):
        if _clean(doc.get("instance_id")) != _clean(state.get("instance_id")):
            blocks.append(label + "_INSTANCE_MISMATCH")
        if _clean(doc.get("channel_id")) != _clean(state.get("channel_id")):
            blocks.append(label + "_CHANNEL_MISMATCH")
        if _platform(doc.get("platform")) != _platform(state.get("platform")):
            blocks.append(label + "_PLATFORM_MISMATCH")
        if doc.get("zero_paid_dependency") is not True:
            blocks.append(label + "_ZERO_PAID_DEPENDENCY")

    source_record = _series_record(state)
    source_item = _series_item(state)
    inner_record = _inner_record(inner)
    if source_record is None:
        blocks.append("SERIES_RECORD_MISSING")
    if source_item is None:
        blocks.append("SERIES_OUTBOX_ITEM_MISSING_OR_AMBIGUOUS")
    if inner_record is None:
        blocks.append("EXECUTOR_RECORD_MISSING")
    if source_record is not None and inner_record is not None:
        for field in ("publication_id", "dedupe_key", "instance_id", "channel_id", "platform", "product_id", "product_fingerprint_sha256", "status"):
            left = _platform(source_record.get(field)) if field == "platform" else _clean(source_record.get(field))
            right = _platform(inner_record.get(field)) if field == "platform" else _clean(inner_record.get(field))
            if left != right:
                blocks.append("SERIES_EXECUTOR_RECORD_DIVERGENCE:" + field)
        for field in ("attempt_count", "remote_publication_id", "next_attempt_at"):
            if source_record.get(field) != inner_record.get(field):
                blocks.append("SERIES_EXECUTOR_RECORD_DIVERGENCE:" + field)
    if source_item is not None and inner_record is not None and _clean(source_item.get("status")) != _clean(inner_record.get("status")):
        blocks.append("SERIES_OUTBOX_STATUS_DIVERGENCE")

    if state.get("dispatch_handoff_outbox") != inner.get("outbox"):
        blocks.append("DISPATCH_HANDOFF_OUTBOX_DIVERGENCE")
    handoff = _handoff(inner.get("outbox") if isinstance(inner.get("outbox"), dict) else {}, _clean(state.get("handoff_id")))
    if source_item is not None:
        supplied = _clean(source_item.get("outbox_item_fingerprint_sha256")).lower()
        body = copy.deepcopy(source_item)
        body.pop("outbox_item_fingerprint_sha256", None)
        if not _is_sha256(supplied) or supplied != _digest(body):
            blocks.append("SERIES_OUTBOX_ITEM_FINGERPRINT_INVALID")
    if source_item is not None and handoff is not None:
        payload = handoff.get("adapter_payload") if isinstance(handoff.get("adapter_payload"), dict) else {}
        native = payload.get("native_product") if isinstance(payload.get("native_product"), dict) else {}
        current = source_item.get("product") if isinstance(source_item.get("product"), dict) else {}
        if current != native:
            blocks.append("NATIVE_SERIES_PRODUCT_MUTATED_AFTER_HANDOFF")
        if _story_ids(current) != [str(value) for value in payload.get("source_story_ids", [])]:
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
    for key, value in expected_guards.items():
        if guards.get(key) is not value:
            blocks.append("STATE_GUARD_INVALID:" + key)
    return sorted(set(blocks))


def initialize_series_dispatch_state(handoff_result: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(handoff_result, dict):
        raise TypeError("handoff_result must be a mapping")
    blocks = _validate_handoff_result(handoff_result)
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
    state = _sync(_seal(state), generic["state"])
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    return {"schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "SERIES_DISPATCH_STATE_INITIALIZED", "state": state, "adapter_invoked": False}


def claim_series_dispatch(state: dict[str, Any], now: str, worker_id: str, *, lease_seconds: int = executor.DEFAULT_LEASE_SECONDS) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    inner = executor.claim_dispatch(copy.deepcopy(state["executor_state"]), now, worker_id, lease_seconds=lease_seconds)
    if inner.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner.get("hard_blocks", [])])
    if _clean(inner.get("decision")) != "CLAIMED":
        result = copy.deepcopy(inner)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result
    candidate = _sync(state, inner["state"])
    invocation = copy.deepcopy(inner.get("adapter_invocation"))
    if isinstance(invocation, dict):
        invocation["publication_kind"] = PUBLICATION_KIND
        invocation["series_id"] = _clean(state.get("series_id"))
        invocation["series_execution_id"] = _clean(state.get("series_execution_id"))
        invocation["series_slot_key"] = _clean(state.get("series_slot_key"))
        payload = invocation.get("adapter_payload") if isinstance(invocation.get("adapter_payload"), dict) else {}
        invocation["source_story_ids"] = copy.deepcopy(payload.get("source_story_ids") or [])
    return {
        "schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "CLAIMED",
        "publication_kind": PUBLICATION_KIND, "state": candidate, "claim_token": _clean(inner.get("claim_token")),
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "claimed_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True, "persist_before_adapter_required": True,
        "adapter_invoked": False, "adapter_invocation": invocation,
    }


def reconcile_series_adapter_result(
    state: dict[str, Any], claim_token: str, attempted_at: str, adapter_result: dict[str, Any], *,
    max_attempts: int = 5, base_delay_seconds: int = 60, max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    if not isinstance(state, dict) or not isinstance(adapter_result, dict):
        raise TypeError("state and adapter_result must be mappings")
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    inner = executor.reconcile_adapter_result(
        copy.deepcopy(state["executor_state"]), claim_token, attempted_at, copy.deepcopy(adapter_result),
        max_attempts=max_attempts, base_delay_seconds=base_delay_seconds, max_delay_seconds=max_delay_seconds,
    )
    if inner.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner.get("hard_blocks", [])], adapter_invoked=True)
    if _clean(inner.get("decision")) == "RECONCILIATION_REQUIRED":
        result = copy.deepcopy(inner)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result
    candidate = _sync(state, inner["state"])
    record = _series_record(candidate) or {}
    return {
        "schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": _clean(inner.get("decision")),
        "publication_kind": PUBLICATION_KIND, "publication_status": _clean(record.get("status")),
        "record": copy.deepcopy(record), "state": candidate,
        "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True, "adapter_invoked": True,
    }


def recover_stale_series_claim(state: dict[str, Any], now: str, *, remote_publication_id: str | None = None, remote_absent_confirmed: bool = False) -> dict[str, Any]:
    if not isinstance(state, dict):
        raise TypeError("state must be a mapping")
    blocks = _validate_state(state)
    if blocks:
        return _blocked(state, blocks)
    inner = executor.recover_stale_claim(
        copy.deepcopy(state["executor_state"]), now,
        remote_publication_id=remote_publication_id, remote_absent_confirmed=remote_absent_confirmed,
    )
    if inner.get("blocked") is True:
        return _blocked(state, ["GENERIC_EXECUTOR:" + str(reason) for reason in inner.get("hard_blocks", [])])
    if _clean(inner.get("decision")) in {"LEASE_HELD", "RECONCILIATION_REQUIRED"}:
        result = copy.deepcopy(inner)
        result["state"] = copy.deepcopy(state)
        result["publication_kind"] = PUBLICATION_KIND
        return result
    candidate = _sync(state, inner["state"])
    return {
        "schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": _clean(inner.get("decision")),
        "publication_kind": PUBLICATION_KIND, "publication_status": _clean((_series_record(candidate) or {}).get("status")),
        "state": candidate, "expected_previous_state_fingerprint_sha256": _clean(state.get("state_fingerprint_sha256")),
        "result_state_fingerprint_sha256": _clean(candidate.get("state_fingerprint_sha256")),
        "compare_and_swap_required": True, "adapter_invoked": False,
    }


def execute_series_dispatch(
    state: dict[str, Any], now: str, worker_id: str, *,
    persist_claim: Callable[[str, dict[str, Any]], bool], invoke_adapter: Callable[[dict[str, Any]], dict[str, Any]],
    persist_result: Callable[[str, dict[str, Any]], bool] | None = None,
    lease_seconds: int = executor.DEFAULT_LEASE_SECONDS, max_attempts: int = 5,
    base_delay_seconds: int = 60, max_delay_seconds: int = 3600,
) -> dict[str, Any]:
    if not callable(persist_claim) or not callable(invoke_adapter):
        raise TypeError("persist_claim and invoke_adapter must be callable")
    if persist_result is not None and not callable(persist_result):
        raise TypeError("persist_result must be callable when provided")
    claim = claim_series_dispatch(state, now, worker_id, lease_seconds=lease_seconds)
    if claim.get("blocked") is True or _clean(claim.get("decision")) != "CLAIMED":
        return claim
    try:
        claim_saved = persist_claim(_clean(claim.get("expected_previous_state_fingerprint_sha256")), copy.deepcopy(claim["state"])) is True
    except Exception:
        claim_saved = False
    if not claim_saved:
        return {
            "schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [], "decision": "CLAIM_PERSIST_CONFLICT",
            "reason": "ADAPTER_NOT_INVOKED_BECAUSE_SERIES_PUBLISHING_CLAIM_WAS_NOT_DURABLE",
            "state": copy.deepcopy(state), "adapter_invoked": False,
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
        max_attempts=max_attempts, base_delay_seconds=base_delay_seconds, max_delay_seconds=max_delay_seconds,
    )
    if reconciled.get("blocked") is True or _clean(reconciled.get("decision")) == "RECONCILIATION_REQUIRED":
        reconciled["adapter_invoked"] = True
        return reconciled
    if persist_result is not None:
        try:
            saved = persist_result(_clean(claimed_state.get("state_fingerprint_sha256")), copy.deepcopy(reconciled["state"])) is True
        except Exception:
            saved = False
        if not saved:
            return {
                "schema_version": SCHEMA_VERSION, "blocked": False, "hard_blocks": [],
                "decision": "RESULT_PERSIST_CONFLICT_RECONCILIATION_REQUIRED",
                "reason": "ADAPTER_ALREADY_INVOKED_SERIES_STATE_REMAINS_PUBLISHING",
                "state": copy.deepcopy(claimed_state),
                "candidate_result_state_fingerprint_sha256": _clean(reconciled.get("result_state_fingerprint_sha256")),
                "adapter_invoked": True,
            }
    reconciled["claim_persisted_before_adapter"] = True
    reconciled["result_persisted"] = persist_result is not None
    return reconciled
