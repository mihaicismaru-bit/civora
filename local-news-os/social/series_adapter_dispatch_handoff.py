#!/usr/bin/env python3
"""Adapter-gated dispatch handoff for READY recurring social series.

This bridge consumes the durable result of ``series_publication_state_bridge`` and
moves only a series publication that is already in ``READY`` through the existing
publishing-adapter runtime gate and truthful adapter-capability contract.

It deliberately does not dispatch to a network. ``OUTBOX_READY`` and all timing,
link or approval holds remain non-dispatchable and produce no adapter handoff.
For a READY series, the bridge can preserve READY/DIRECT_READY, demote the exact
native product to OUTBOX_READY when the installed adapter lacks capability, or
move it to BLOCKED_AUTH when required credential *reference names* are absent.

The original channel-native series product is never rewritten. The atomic commit
bundle keeps recurring-series state/outbox synchronized with a separate logical
adapter-handoff outbox. Credential values are never accepted or exposed.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

import adapter_capability_gate
import adapter_dispatch_bridge
import publishing_adapters

SCHEMA_VERSION = "1.0"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SERIES_POLICY = "CHANNEL_NATIVE_SERIES_ONLY"
NON_DISPATCHABLE_STATES = {
    "OUTBOX_READY",
    "HOLD_LINK_BINDING",
    "HOLD_TIMING",
    "AWAITING_APPROVAL",
    "RETRY_WAIT",
    "BLOCKED_AUTH",
    "PUBLISHED",
    "FAILED_TERMINAL",
    "SUPERSEDED_CORRECTION",
    "CORRECTION_REQUIRED",
}
PREDICTIVE_KEYS = {
    "predicted_views",
    "predicted_reach",
    "predicted_engagement",
    "predicted_ctr",
    "predicted_shares",
    "predicted_saves",
    "virality_probability",
    "expected_views",
    "expected_reach",
    "expected_engagement",
    "forecast_views",
}
SECRET_KEYS = {
    "access_token",
    "refresh_token",
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "client_secret",
    "credential_value",
    "credential_values",
    "authorization",
    "bearer",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform(value: Any) -> str:
    return _clean(value).lower().replace("-", "_")


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _fingerprint_valid(value: dict[str, Any], field: str) -> bool:
    supplied = _clean(value.get(field)).lower()
    if not SHA256_RE.fullmatch(supplied):
        return False
    payload = copy.deepcopy(value)
    payload.pop(field, None)
    return _digest(payload) == supplied


def _contains_key(value: Any, keys: set[str]) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if _clean(key).casefold() in keys:
                return True
            if _contains_key(child, keys):
                return True
    elif isinstance(value, list):
        return any(_contains_key(item, keys) for item in value)
    return False


def _registry_entry(registry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = registry.get("channels") if isinstance(registry.get("channels"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _platform(row.get("channel_id")) == _platform(platform)]
    return matches[0] if len(matches) == 1 else None


def _capability_entry(capabilities: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = capabilities.get("adapters") if isinstance(capabilities.get("adapters"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _platform(row.get("platform")) == _platform(platform)]
    return matches[0] if len(matches) == 1 else None


def _story_ids(product: dict[str, Any]) -> list[str]:
    return [
        _clean(item.get("story_id"))
        for item in product.get("items", [])
        if isinstance(item, dict) and _clean(item.get("story_id"))
    ]


def _source_parts(series_result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    record = series_result.get("record") if isinstance(series_result.get("record"), dict) else {}
    item = series_result.get("outbox_item") if isinstance(series_result.get("outbox_item"), dict) else {}
    product = item.get("product") if isinstance(item.get("product"), dict) else {}
    state = series_result.get("state") if isinstance(series_result.get("state"), dict) else {}
    outbox = series_result.get("outbox") if isinstance(series_result.get("outbox"), dict) else {}
    return record, item, product, state, outbox


def _source_blocks(series_result: dict[str, Any], registry: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if series_result.get("blocked") is True:
        blocks.append("UPSTREAM_SERIES_RUNTIME_BLOCKED")

    instance_id = _clean(series_result.get("instance_id"))
    channel_id = _clean(series_result.get("channel_id"))
    platform = _platform(series_result.get("platform"))
    if not instance_id:
        blocks.append("MISSING_INSTANCE_ID")
    if not channel_id:
        blocks.append("MISSING_CHANNEL_ID")
    if not platform:
        blocks.append("MISSING_PLATFORM")
    if _clean(registry.get("instance_id")) != instance_id:
        blocks.append("REGISTRY_INSTANCE_MISMATCH")

    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    if policy.get("fail_closed_on_missing_credentials") is not True:
        blocks.append("REGISTRY_MUST_FAIL_CLOSED_ON_MISSING_CREDENTIALS")
    if policy.get("paid_social_scheduler_required") is not False:
        blocks.append("PAID_SCHEDULER_POLICY_VIOLATION")
    if policy.get("paid_llm_api_required") is not False:
        blocks.append("PAID_LLM_POLICY_VIOLATION")
    if policy.get("cross_post_verbatim_forbidden") is not True:
        blocks.append("REGISTRY_CROSS_POST_POLICY_WEAKENED")

    guards = series_result.get("guards") if isinstance(series_result.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    if guards.get("network_dispatch_performed") is not False:
        blocks.append("UPSTREAM_NETWORK_DISPATCH_FORBIDDEN")
    if guards.get("credential_values_read") is not False:
        blocks.append("UPSTREAM_CREDENTIAL_VALUES_READ")
    if guards.get("credential_values_exposed") is not False:
        blocks.append("UPSTREAM_CREDENTIAL_VALUES_EXPOSED")
    if guards.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")

    runtime_fp = _clean(series_result.get("runtime_fingerprint_sha256")).lower()
    if not SHA256_RE.fullmatch(runtime_fp):
        blocks.append("INVALID_SERIES_RUNTIME_FINGERPRINT")

    record, item, product, state, outbox = _source_parts(series_result)
    if not record:
        blocks.append("MISSING_SERIES_PUBLICATION_RECORD")
    if not item:
        blocks.append("MISSING_SERIES_PUBLICATION_OUTBOX_ITEM")
    if not product:
        blocks.append("MISSING_NATIVE_SERIES_PRODUCT")
    if not state:
        blocks.append("MISSING_SERIES_PUBLICATION_STATE")
    if not outbox:
        blocks.append("MISSING_SERIES_PUBLICATION_OUTBOX")
    if blocks:
        return sorted(set(blocks))

    for name, value in (("RECORD", record), ("OUTBOX_ITEM", item), ("PRODUCT", product)):
        if _clean(value.get("instance_id")) != instance_id:
            blocks.append(f"{name}_INSTANCE_MISMATCH")
        if _clean(value.get("channel_id")) != channel_id:
            blocks.append(f"{name}_CHANNEL_MISMATCH")
        if _platform(value.get("platform")) != platform:
            blocks.append(f"{name}_PLATFORM_MISMATCH")

    if _clean(record.get("publication_id")) != _clean(item.get("publication_id")):
        blocks.append("PUBLICATION_ID_DIVERGENCE")
    if _clean(record.get("dedupe_key")) != _clean(item.get("dedupe_key")):
        blocks.append("DEDUPE_KEY_DIVERGENCE")
    if _clean(record.get("product_id")) != _clean(product.get("product_id")):
        blocks.append("PRODUCT_ID_DIVERGENCE")
    if _clean(record.get("product_fingerprint_sha256")).lower() != _clean(product.get("product_fingerprint_sha256")).lower():
        blocks.append("PRODUCT_FINGERPRINT_DIVERGENCE")
    if _clean(item.get("product_fingerprint_sha256")).lower() != _clean(product.get("product_fingerprint_sha256")).lower():
        blocks.append("OUTBOX_PRODUCT_FINGERPRINT_DIVERGENCE")
    if not _fingerprint_valid(product, "product_fingerprint_sha256"):
        blocks.append("SERIES_PRODUCT_FINGERPRINT_MISMATCH")
    if not _fingerprint_valid(item, "outbox_item_fingerprint_sha256"):
        blocks.append("SERIES_OUTBOX_ITEM_FINGERPRINT_MISMATCH")

    if _clean(product.get("cross_post_policy")) != SERIES_POLICY:
        blocks.append("INVALID_SERIES_CROSS_POST_POLICY")
    if product.get("reuse_prior_copy") is not False:
        blocks.append("PRIOR_COPY_REUSE_FORBIDDEN")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE")
    if product.get("analytics_used") is not False:
        blocks.append("ANALYTICS_POLICY_VIOLATION")
    if product.get("network_dispatch_performed") is not False:
        blocks.append("PRODUCT_NETWORK_DISPATCH_ALREADY_PERFORMED")
    if product.get("zero_paid_dependency") is not True:
        blocks.append("PRODUCT_ZERO_PAID_DEPENDENCY_VIOLATION")
    if _contains_key(product, PREDICTIVE_KEYS):
        blocks.append("PREDICTIVE_ANALYTICS_FORBIDDEN")
    if _contains_key(product, SECRET_KEYS):
        blocks.append("SECRET_VALUE_IN_NATIVE_SERIES_PRODUCT")

    stories = _story_ids(product)
    if not stories:
        blocks.append("MISSING_SERIES_SOURCE_STORIES")
    elif len(stories) != len(set(stories)):
        blocks.append("DUPLICATE_SERIES_SOURCE_STORIES")

    records = state.get("records") if isinstance(state.get("records"), dict) else {}
    publication_id = _clean(record.get("publication_id"))
    stored_record = records.get(publication_id)
    if not isinstance(stored_record, dict):
        blocks.append("SERIES_STATE_RECORD_MISSING")
    elif _clean(stored_record.get("dedupe_key")) != _clean(record.get("dedupe_key")):
        blocks.append("SERIES_STATE_RECORD_DIVERGENCE")

    items = outbox.get("items") if isinstance(outbox.get("items"), list) else []
    matches = [candidate for candidate in items if isinstance(candidate, dict) and _clean(candidate.get("publication_id")) == publication_id]
    if len(matches) != 1:
        blocks.append("SERIES_OUTBOX_RECORD_MISSING_OR_AMBIGUOUS")
    elif _clean(matches[0].get("outbox_item_fingerprint_sha256")) != _clean(item.get("outbox_item_fingerprint_sha256")):
        blocks.append("SERIES_OUTBOX_TOP_LEVEL_ITEM_DIVERGENCE")

    entry = _registry_entry(registry, platform)
    if entry is None:
        blocks.append("CHANNEL_REGISTRY_ENTRY_MISSING_OR_AMBIGUOUS")
    return sorted(set(blocks))


def _capability_contract_blocks(
    capabilities: dict[str, Any],
    registry: dict[str, Any],
    *,
    platform: str,
    channel_id: str,
    adapter: str,
) -> tuple[list[str], dict[str, Any] | None]:
    blocks: list[str] = []
    if _clean(capabilities.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("CAPABILITY_SCHEMA_VERSION")
    if _clean(capabilities.get("instance_id")) != _clean(registry.get("instance_id")):
        blocks.append("CAPABILITY_INSTANCE_MISMATCH")
    policy = capabilities.get("policy") if isinstance(capabilities.get("policy"), dict) else {}
    expected = {
        "fail_closed_on_capability_mismatch": True,
        "durable_outbox_on_supported_channel_format_gap": True,
        "credential_values_allowed": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "zero_paid_dependency": True,
    }
    for key, value in expected.items():
        if policy.get(key) is not value:
            blocks.append(f"CAPABILITY_POLICY_INVALID:{key}")
    capability = _capability_entry(capabilities, platform)
    if capability is None:
        blocks.append("DIRECT_ADAPTER_CAPABILITY_MISSING")
        return sorted(set(blocks)), None
    if _clean(capability.get("channel_id")) != channel_id:
        blocks.append("CAPABILITY_CHANNEL_MISMATCH")
    if _clean(capability.get("adapter")) != adapter:
        blocks.append("CAPABILITY_ADAPTER_PATH_MISMATCH")
    return sorted(set(blocks)), capability


def _capability_report(series_result: dict[str, Any], product: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance_id": _clean(series_result.get("instance_id")),
        "channel_id": _clean(series_result.get("channel_id")),
        "platform": _platform(series_result.get("platform")),
        "disposition": "READY",
        "artifacts": {
            "format": {"product": copy.deepcopy(product)},
            "visual": {"binding": copy.deepcopy(item.get("visual_binding") or {})},
        },
    }


def _validate_handoff_outbox(outbox: dict[str, Any], series_result: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(outbox.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("HANDOFF_OUTBOX_SCHEMA_VERSION")
    if _clean(outbox.get("instance_id")) != _clean(series_result.get("instance_id")):
        blocks.append("HANDOFF_OUTBOX_INSTANCE_MISMATCH")
    if _clean(outbox.get("channel_id")) != _clean(series_result.get("channel_id")):
        blocks.append("HANDOFF_OUTBOX_CHANNEL_MISMATCH")
    if _platform(outbox.get("platform")) != _platform(series_result.get("platform")):
        blocks.append("HANDOFF_OUTBOX_PLATFORM_MISMATCH")
    if not isinstance(outbox.get("items"), dict):
        blocks.append("HANDOFF_OUTBOX_ITEMS_INVALID")
    guards = outbox.get("guards") if isinstance(outbox.get("guards"), dict) else {}
    if guards.get("credential_values_allowed") is not False:
        blocks.append("HANDOFF_OUTBOX_CREDENTIAL_VALUE_POLICY")
    if guards.get("zero_paid_dependency") is not True:
        blocks.append("HANDOFF_OUTBOX_ZERO_PAID_DEPENDENCY")
    return sorted(set(blocks))


def _blocked(series_result: dict[str, Any], reasons: Iterable[str], *, decision: str = "BLOCKED_SERIES_ADAPTER_HANDOFF") -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(series_result.get("instance_id")) or None,
        "channel_id": _clean(series_result.get("channel_id")) or None,
        "platform": _platform(series_result.get("platform")) or None,
        "series_id": _clean(series_result.get("series_id")) or None,
        "series_execution_id": _clean(series_result.get("series_execution_id")) or None,
        "blocked": True,
        "hard_blocks": sorted(set(str(reason) for reason in reasons)),
        "decision": decision,
        "dispatch_disposition": "BLOCKED",
        "runtime_gate": None,
        "capability_gate": None,
        "adapter_handoff": None,
        "commit_bundle": None,
        "guards": {
            "ready_series_only": True,
            "channel_native_series_only": True,
            "native_product_rewritten": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def _no_handoff(series_result: dict[str, Any], status: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(series_result.get("instance_id")),
        "channel_id": _clean(series_result.get("channel_id")),
        "platform": _platform(series_result.get("platform")),
        "series_id": _clean(series_result.get("series_id")),
        "series_execution_id": _clean(series_result.get("series_execution_id")),
        "blocked": False,
        "hard_blocks": [],
        "decision": "NO_HANDOFF_UPSTREAM_SERIES_STATE",
        "dispatch_disposition": "HOLD_UPSTREAM",
        "publication_status": status,
        "runtime_gate": None,
        "capability_gate": None,
        "adapter_handoff": None,
        "commit_bundle": None,
        "guards": {
            "ready_series_only": True,
            "channel_native_series_only": True,
            "native_product_rewritten": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def bridge_ready_series_handoff(
    series_result: dict[str, Any],
    channel_registry: dict[str, Any],
    capability_registry: dict[str, Any],
    present_credential_references: Iterable[str] | None,
    handoff_outbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an atomic adapter handoff for one READY recurring-series publication."""
    if not all(isinstance(value, dict) for value in (series_result, channel_registry, capability_registry)):
        raise TypeError("series_result, channel_registry and capability_registry must be mappings")
    if handoff_outbox is not None and not isinstance(handoff_outbox, dict):
        raise TypeError("handoff_outbox must be a mapping when provided")

    blocks = _source_blocks(series_result, channel_registry)
    refs, ref_errors = adapter_dispatch_bridge._normalize_present_refs(present_credential_references)
    blocks.extend(ref_errors)
    if blocks:
        return _blocked(series_result, blocks)

    record, source_item, product, source_state, source_outbox = _source_parts(series_result)
    publication_status = _clean(record.get("status"))
    if publication_status != "READY":
        if publication_status in NON_DISPATCHABLE_STATES:
            return _no_handoff(series_result, publication_status)
        return _blocked(series_result, ["UNKNOWN_SERIES_PUBLICATION_STATE"])
    dispatch_meta = source_item.get("dispatch") if isinstance(source_item.get("dispatch"), dict) else {}
    if dispatch_meta.get("adapter_dispatch_eligible") is not True:
        return _blocked(series_result, ["READY_SERIES_NOT_MARKED_ADAPTER_DISPATCH_ELIGIBLE"])

    platform = _platform(series_result.get("platform"))
    entry = _registry_entry(channel_registry, platform)
    assert entry is not None
    gate = publishing_adapters.runtime_gate(entry, refs)
    gate_decision = _clean(gate.get("decision"))
    if gate_decision == "BLOCKED_INVALID_CREDENTIAL_CONTRACT":
        return _blocked(series_result, gate.get("errors", []) or [gate_decision])

    adapter = _clean(entry.get("adapter"))
    refs_declared, credential_errors = publishing_adapters.credential_reference_names(entry)
    if credential_errors:
        return _blocked(series_result, credential_errors)
    if not _clean(entry.get("outbox")) or not _clean(entry.get("state")):
        return _blocked(series_result, ["MISSING_DURABLE_CHANNEL_PATHS"])

    capability_assessment: dict[str, Any] | None = None
    capability_gap_reasons: list[str] = []
    if gate_decision == "DIRECT_READY":
        if not adapter:
            return _blocked(series_result, ["DIRECT_READY_WITHOUT_ADAPTER"])
        if _clean(entry.get("publication_mode")).lower() not in publishing_adapters.DIRECT_MODES:
            return _blocked(series_result, ["DIRECT_READY_WITH_UNAPPROVED_MODE"])
        cap_blocks, capability = _capability_contract_blocks(
            capability_registry,
            channel_registry,
            platform=platform,
            channel_id=_clean(series_result.get("channel_id")),
            adapter=adapter,
        )
        if cap_blocks or capability is None:
            return _blocked(series_result, cap_blocks or ["DIRECT_ADAPTER_CAPABILITY_MISSING"])
        capability_assessment = adapter_capability_gate.assess_runtime_capability(
            _capability_report(series_result, product, source_item), capability
        )
        if capability_assessment.get("compatible") is True:
            disposition = "DIRECT_READY"
            state_after = "READY"
            state_reason = "SERIES_ADAPTER_RUNTIME_AND_CAPABILITY_GATE_CLEAR"
        else:
            disposition = "OUTBOX_ONLY"
            state_after = "OUTBOX_READY"
            state_reason = "SERIES_ADAPTER_CAPABILITY_GAP"
            capability_gap_reasons = [str(value) for value in capability_assessment.get("gap_reasons", [])]
    elif gate_decision == "BLOCKED_MISSING_CREDENTIALS":
        disposition = "BLOCKED_MISSING_CREDENTIALS"
        state_after = "BLOCKED_AUTH"
        state_reason = "MISSING_CREDENTIAL_REFERENCES"
    elif gate_decision == "OUTBOX_ONLY":
        disposition = "OUTBOX_ONLY"
        state_after = "OUTBOX_READY"
        state_reason = "SERIES_DISPATCH_REGISTRY_OUTBOX_ONLY"
    else:
        return _blocked(series_result, ["UNRECOGNIZED_RUNTIME_GATE_DECISION"])

    logical_outbox = copy.deepcopy(handoff_outbox) if handoff_outbox is not None else adapter_dispatch_bridge.empty_handoff_outbox(
        _clean(series_result.get("instance_id")),
        _clean(series_result.get("channel_id")),
        platform,
    )
    outbox_blocks = _validate_handoff_outbox(logical_outbox, series_result)
    if outbox_blocks:
        return _blocked(series_result, outbox_blocks)

    publication_id = _clean(record.get("publication_id"))
    stories = _story_ids(product)
    adapter_payload = {
        "publication_kind": "recurring_series",
        "instance_id": _clean(series_result.get("instance_id")),
        "channel_id": _clean(series_result.get("channel_id")),
        "platform": platform,
        "publication_id": publication_id,
        "dedupe_key": _clean(record.get("dedupe_key")),
        "product_id": _clean(product.get("product_id")),
        "product_fingerprint_sha256": _clean(product.get("product_fingerprint_sha256")),
        "series_id": _clean(product.get("series_id")),
        "series_execution_id": _clean(product.get("series_execution_id")),
        "series_slot_key": _clean(product.get("series_slot_key")),
        "source_story_ids": stories,
        "series_runtime_fingerprint_sha256": _clean(series_result.get("runtime_fingerprint_sha256")),
        "native_product": copy.deepcopy(product),
        "visual_binding": copy.deepcopy(source_item.get("visual_binding")),
        "link_binding": copy.deepcopy(source_item.get("link_binding")),
    }
    payload_fp = _digest(adapter_payload)
    handoff_id = "series-handoff:" + _digest({
        "instance_id": adapter_payload["instance_id"],
        "channel_id": adapter_payload["channel_id"],
        "platform": platform,
        "publication_id": publication_id,
        "dedupe_key": adapter_payload["dedupe_key"],
        "product_fingerprint_sha256": adapter_payload["product_fingerprint_sha256"],
        "series_slot_key": adapter_payload["series_slot_key"],
    })[:24]

    missing_refs = sorted(str(value) for value in gate.get("missing_references", []))
    handoff_item = {
        "handoff_id": handoff_id,
        "publication_kind": "recurring_series",
        "instance_id": adapter_payload["instance_id"],
        "channel_id": adapter_payload["channel_id"],
        "platform": platform,
        "publication_id": publication_id,
        "series_id": adapter_payload["series_id"],
        "series_execution_id": adapter_payload["series_execution_id"],
        "series_slot_key": adapter_payload["series_slot_key"],
        "product_id": adapter_payload["product_id"],
        "dispatch_disposition": disposition,
        "adapter": adapter or None,
        "physical_outbox_path": _clean(entry.get("outbox")),
        "physical_state_path": _clean(entry.get("state")),
        "credential_reference_names": refs_declared,
        "missing_reference_names": missing_refs,
        "credential_values_included": False,
        "network_dispatch_performed": False,
        "capability_gap_reasons": capability_gap_reasons,
        "adapter_payload": adapter_payload,
        "adapter_payload_fingerprint_sha256": payload_fp,
    }
    handoff_item["handoff_fingerprint_sha256"] = _digest(handoff_item)

    existing = logical_outbox["items"].get(handoff_id)
    if isinstance(existing, dict):
        if _clean(existing.get("adapter_payload_fingerprint_sha256")) != payload_fp:
            return _blocked(series_result, ["SERIES_HANDOFF_ID_COLLISION"])
        previous = _clean(existing.get("dispatch_disposition"))
        decision = "DEDUPE_EXISTING_SERIES_HANDOFF" if previous == disposition else "UPDATED_SERIES_HANDOFF_GATE"
    else:
        decision = "REGISTERED_SERIES_HANDOFF"
    logical_outbox["items"][handoff_id] = handoff_item

    candidate_state = copy.deepcopy(source_state)
    candidate_outbox = copy.deepcopy(source_outbox)
    candidate_record = candidate_state["records"][publication_id]
    candidate_record["status"] = state_after
    candidate_record["state_reason"] = state_reason
    if state_after == "BLOCKED_AUTH":
        candidate_record["next_attempt_at"] = None
    candidate_record["series_dispatch_bridge"] = {
        "handoff_id": handoff_id,
        "dispatch_disposition": disposition,
        "credential_reference_names": refs_declared,
        "missing_reference_names": missing_refs,
        "capability_gap_reasons": capability_gap_reasons,
        "credential_values_exposed": False,
        "network_dispatch_performed": False,
    }

    source_matches = [item for item in candidate_outbox["items"] if isinstance(item, dict) and _clean(item.get("publication_id")) == publication_id]
    if len(source_matches) != 1:
        return _blocked(series_result, ["SERIES_OUTBOX_RECORD_MISSING_OR_AMBIGUOUS"])
    candidate_item = source_matches[0]
    candidate_item["status"] = state_after
    candidate_item["state_reason"] = state_reason
    dispatch = candidate_item.setdefault("dispatch", {})
    if not isinstance(dispatch, dict):
        return _blocked(series_result, ["SERIES_OUTBOX_DISPATCH_METADATA_INVALID"])
    dispatch["adapter_dispatch_eligible"] = disposition == "DIRECT_READY"
    dispatch["durable_outbox_ready"] = disposition == "OUTBOX_ONLY"
    dispatch["blocked_missing_credentials"] = disposition == "BLOCKED_MISSING_CREDENTIALS"
    dispatch["handoff_id"] = handoff_id
    dispatch["network_dispatch_performed"] = False
    candidate_item["outbox_item_fingerprint_sha256"] = _digest({
        key: value for key, value in candidate_item.items() if key != "outbox_item_fingerprint_sha256"
    })

    commit_bundle = {
        "instance_id": adapter_payload["instance_id"],
        "channel_id": adapter_payload["channel_id"],
        "platform": platform,
        "publication_id": publication_id,
        "handoff_id": handoff_id,
        "series_publication_state": candidate_state,
        "series_publication_outbox": candidate_outbox,
        "dispatch_handoff_outbox": logical_outbox,
        "atomic_persist_required": True,
        "network_dispatch_performed": False,
    }
    bundle_fp = _digest(commit_bundle)

    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": adapter_payload["instance_id"],
        "channel_id": adapter_payload["channel_id"],
        "platform": platform,
        "series_id": adapter_payload["series_id"],
        "series_execution_id": adapter_payload["series_execution_id"],
        "series_slot_key": adapter_payload["series_slot_key"],
        "blocked": False,
        "hard_blocks": [],
        "decision": decision,
        "dispatch_disposition": disposition,
        "publication_status_before_bridge": publication_status,
        "publication_status_after_bridge": state_after,
        "runtime_gate": copy.deepcopy(gate),
        "capability_gate": copy.deepcopy(capability_assessment),
        "capability_gap_reasons": capability_gap_reasons,
        "adapter_handoff": {
            "handoff_id": handoff_id,
            "adapter": adapter or None,
            "dispatch_allowed": disposition == "DIRECT_READY",
            "durable_outbox_only": disposition == "OUTBOX_ONLY",
            "blocked_missing_credentials": disposition == "BLOCKED_MISSING_CREDENTIALS",
            "credential_reference_names": refs_declared,
            "missing_reference_names": missing_refs,
            "credential_values_exposed": False,
        },
        "commit_bundle": commit_bundle,
        "bundle_fingerprint_sha256": bundle_fp,
        "guards": {
            "ready_series_only": True,
            "channel_native_series_only": True,
            "source_story_identity_preserved": True,
            "native_product_rewritten": False,
            "fallback_format_invented": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_analytics_used": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("series_result", type=Path)
    parser.add_argument("channel_registry", type=Path)
    parser.add_argument("capability_registry", type=Path)
    parser.add_argument("--present-ref", action="append", default=[])
    parser.add_argument("--handoff-outbox", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = bridge_ready_series_handoff(
        _load(args.series_result),
        _load(args.channel_registry),
        _load(args.capability_registry),
        args.present_ref,
        _load(args.handoff_outbox) if args.handoff_outbox else None,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
