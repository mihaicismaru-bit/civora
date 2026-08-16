#!/usr/bin/env python3
"""Durable publication-state bridge for native recurring social series.

This module consumes one channel-native recurring-series product after the
Native Series Compositor and, when required, the Series Visual Router. It then
applies link policy, the existing Cadence/Fatigue Engine and channel-local
publication state without performing network dispatch.

Website and social channels remain sibling publications. Each series product
keeps its own channel-native copy, media binding, cadence decision, durable
outbox entry and dedupe identity. Text-native series may bypass the visual gate
only when the compositor explicitly declared media not required. Visual series
must present a valid ``SERIES_VISUAL_READY`` binding with real-media provenance.

The bridge is side-effect free. Callers persist the returned outbox/state
atomically with their existing conflict-safe storage layer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

MODULE_DIR = Path(__file__).resolve().parent
if str(MODULE_DIR) not in sys.path:
    sys.path.insert(0, str(MODULE_DIR))

import cadence_fatigue
import visual_router

SCHEMA_VERSION = "1.0"
FORMAT_READY = "SERIES_FORMAT_READY"
VISUAL_READY = "SERIES_VISUAL_READY"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

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
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


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


def _default_outbox(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "publication_model": "recurring_series_native_publication",
        "items": [],
        "zero_paid_dependency": True,
    }


def _default_state(channel: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "publication_model": "recurring_series_native_publication",
        "records": {},
        "zero_paid_dependency": True,
    }


def _container_blocks(
    channel: dict[str, Any],
    outbox: dict[str, Any],
    state: dict[str, Any],
) -> list[str]:
    blocks: list[str] = []
    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()
    for name, doc in (("OUTBOX", outbox), ("STATE", state)):
        if _clean(doc.get("schema_version")) != SCHEMA_VERSION:
            blocks.append(f"{name}_SCHEMA_VERSION")
        if _clean(doc.get("instance_id")) != instance_id or not instance_id:
            blocks.append(f"{name}_INSTANCE_MISMATCH")
        if _clean(doc.get("channel_id")) != channel_id or not channel_id:
            blocks.append(f"{name}_CHANNEL_MISMATCH")
        if _clean(doc.get("platform")).lower() != platform or not platform:
            blocks.append(f"{name}_PLATFORM_MISMATCH")
        if _clean(doc.get("publication_model")) != "recurring_series_native_publication":
            blocks.append(f"{name}_PUBLICATION_MODEL")
        if doc.get("zero_paid_dependency") is not True:
            blocks.append(f"{name}_ZERO_PAID_DEPENDENCY_REQUIRED")

    items = outbox.get("items")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        blocks.append("INVALID_SERIES_PUBLICATION_OUTBOX")
    else:
        publication_ids = [_clean(item.get("publication_id")) for item in items]
        nonempty = [value for value in publication_ids if value]
        if len(nonempty) != len(items):
            blocks.append("OUTBOX_PUBLICATION_ID_REQUIRED")
        elif len(set(nonempty)) != len(nonempty):
            blocks.append("DUPLICATE_SERIES_PUBLICATION_ID")

    records = state.get("records")
    if not isinstance(records, dict) or any(not isinstance(value, dict) for value in records.values()):
        blocks.append("INVALID_SERIES_PUBLICATION_STATE")
    return sorted(set(blocks))


def _product_blocks(composition_result: dict[str, Any], channel: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if composition_result.get("blocked") is True:
        blocks.append("SERIES_COMPOSITION_BLOCKED")
    product = composition_result.get("product") if isinstance(composition_result.get("product"), dict) else {}
    if not product:
        blocks.append("MISSING_SERIES_PRODUCT")
        return blocks

    instance_id = _clean(channel.get("instance_id"))
    channel_id = _clean(channel.get("channel_id"))
    platform = _clean(channel.get("platform")).lower()
    identities = (
        (_clean(composition_result.get("instance_id")), instance_id, "INSTANCE_MISMATCH"),
        (_clean(composition_result.get("channel_id")), channel_id, "CHANNEL_MISMATCH"),
        (_clean(composition_result.get("platform")).lower(), platform, "PLATFORM_MISMATCH"),
        (_clean(product.get("instance_id")), instance_id, "PRODUCT_INSTANCE_MISMATCH"),
        (_clean(product.get("channel_id")), channel_id, "PRODUCT_CHANNEL_MISMATCH"),
        (_clean(product.get("platform")).lower(), platform, "PRODUCT_PLATFORM_MISMATCH"),
    )
    for actual, expected, reason in identities:
        if not actual or not expected or actual != expected:
            blocks.append(reason)

    if _clean(channel.get("status")) not in {"active", "outbox_only"}:
        blocks.append("CHANNEL_NOT_ACTIVE")
    if channel.get("zero_paid_dependency") is not True or product.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        blocks.append("OBSERVED_METRICS_POLICY_REQUIRED")

    if _clean(product.get("status")) != FORMAT_READY:
        blocks.append("SERIES_PRODUCT_NOT_FORMAT_READY")
    if _clean(product.get("cross_post_policy")) != "CHANNEL_NATIVE_SERIES_ONLY":
        blocks.append("INVALID_SERIES_CROSS_POST_POLICY")
    if product.get("reuse_prior_copy") is not False:
        blocks.append("PRIOR_COPY_REUSE_FORBIDDEN")
    if product.get("verbatim_cross_platform_reuse_allowed") is not False:
        blocks.append("VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN")
    if product.get("invented_claims_allowed") is not False:
        blocks.append("INVENTED_CLAIMS_POLICY")
    if product.get("analytics_used") is not False:
        blocks.append("ANALYTICS_POLICY")
    if product.get("network_dispatch_performed") is not False:
        blocks.append("NETWORK_DISPATCH_ALREADY_PERFORMED")
    if not _fingerprint_valid(product, "product_fingerprint_sha256"):
        blocks.append("SERIES_PRODUCT_FINGERPRINT_MISMATCH")
    if _contains_key(product, PREDICTIVE_KEYS):
        blocks.append("PREDICTIVE_ANALYTICS_FORBIDDEN")
    if _contains_key(product, SECRET_KEYS):
        blocks.append("SECRET_VALUE_IN_DURABLE_PRODUCT")

    product_series = _clean(product.get("series_id"))
    result_series = _clean(composition_result.get("series_id"))
    if not product_series or product_series != result_series:
        blocks.append("SERIES_ID_MISMATCH")
    for field, reason in (
        ("series_execution_id", "MISSING_SERIES_EXECUTION_ID"),
        ("series_slot_key", "MISSING_SERIES_SLOT_KEY"),
        ("product_id", "MISSING_PRODUCT_ID"),
    ):
        if not _clean(product.get(field)):
            blocks.append(reason)
    if _clean(product.get("series_execution_id")) != _clean(composition_result.get("series_execution_id")):
        blocks.append("SERIES_EXECUTION_ID_MISMATCH")
    if _clean(product.get("series_slot_key")) != _clean(composition_result.get("series_slot_key")):
        blocks.append("SERIES_SLOT_KEY_MISMATCH")

    visual = product.get("visual_requirement") if isinstance(product.get("visual_requirement"), dict) else None
    link = product.get("link_requirement") if isinstance(product.get("link_requirement"), dict) else None
    if visual is None:
        blocks.append("MISSING_VISUAL_REQUIREMENT")
    if link is None:
        blocks.append("MISSING_LINK_REQUIREMENT")
    if visual is not None:
        visual_required = visual.get("required") is True
        link_required = _clean((link or {}).get("mode")) == "required"
        expected_gate = "VISUAL_ROUTER" if visual_required else ("LINK_BINDING" if link_required else "CADENCE_FATIGUE")
        if _clean(product.get("next_gate")) != expected_gate:
            blocks.append("INVALID_SERIES_NEXT_GATE")

    items = product.get("items")
    if not isinstance(items, list) or not items:
        blocks.append("MISSING_SERIES_ITEMS")
    else:
        story_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                blocks.append("INVALID_SERIES_ITEM")
                continue
            story_id = _clean(item.get("story_id"))
            if not story_id:
                blocks.append("MISSING_SERIES_ITEM_STORY_ID")
            else:
                story_ids.append(story_id)
            source_hash = _clean(item.get("source_fingerprint_sha256")).lower()
            if not SHA256_RE.fullmatch(source_hash):
                blocks.append(f"INVALID_SERIES_SOURCE_HASH:{story_id or 'UNKNOWN'}")
            if item.get("re_atomized_from_verified_fact_kernel") is not True:
                blocks.append(f"UNVERIFIED_SERIES_ITEM:{story_id or 'UNKNOWN'}")
            if item.get("reuse_prior_copy") is not False:
                blocks.append(f"SERIES_ITEM_PRIOR_COPY_REUSE:{story_id or 'UNKNOWN'}")
            hook = item.get("hook") if isinstance(item.get("hook"), dict) else {}
            if hook.get("source_preserving") is not True or _clean(hook.get("clickbait_guard")) != "PASS":
                blocks.append(f"UNSAFE_SERIES_HOOK:{story_id or 'UNKNOWN'}")
        if len(story_ids) != len(set(story_ids)):
            blocks.append("DUPLICATE_SERIES_ITEM_STORY_ID")
    return sorted(set(blocks))


def _visual_blocks(
    product: dict[str, Any],
    channel: dict[str, Any],
    visual_result: dict[str, Any] | None,
) -> tuple[list[str], dict[str, Any] | None]:
    requirement = product.get("visual_requirement") if isinstance(product.get("visual_requirement"), dict) else {}
    if requirement.get("required") is not True:
        return [], None
    if not isinstance(visual_result, dict):
        return ["SERIES_VISUAL_BINDING_REQUIRED"], None

    blocks: list[str] = []
    if visual_result.get("blocked") is True or visual_result.get("hard_blocks"):
        blocks.append("SERIES_VISUAL_BINDING_BLOCKED")
    for actual, expected, reason in (
        (_clean(visual_result.get("instance_id")), _clean(channel.get("instance_id")), "VISUAL_INSTANCE_MISMATCH"),
        (_clean(visual_result.get("channel_id")), _clean(channel.get("channel_id")), "VISUAL_CHANNEL_MISMATCH"),
        (_clean(visual_result.get("platform")).lower(), _clean(channel.get("platform")).lower(), "VISUAL_PLATFORM_MISMATCH"),
        (_clean(visual_result.get("series_id")), _clean(product.get("series_id")), "VISUAL_SERIES_MISMATCH"),
        (_clean(visual_result.get("series_execution_id")), _clean(product.get("series_execution_id")), "VISUAL_EXECUTION_MISMATCH"),
        (_clean(visual_result.get("series_slot_key")), _clean(product.get("series_slot_key")), "VISUAL_SLOT_MISMATCH"),
        (_clean(visual_result.get("product_id")), _clean(product.get("product_id")), "VISUAL_PRODUCT_MISMATCH"),
    ):
        if not actual or actual != expected:
            blocks.append(reason)

    binding = visual_result.get("binding") if isinstance(visual_result.get("binding"), dict) else None
    if binding is None:
        blocks.append("MISSING_SERIES_VISUAL_BINDING")
        return sorted(set(blocks)), None
    if _clean(binding.get("status")) != VISUAL_READY:
        blocks.append("SERIES_VISUAL_NOT_READY")
    if not _fingerprint_valid(binding, "binding_fingerprint_sha256"):
        blocks.append("SERIES_VISUAL_FINGERPRINT_MISMATCH")
    if _clean(binding.get("source_product_fingerprint_sha256")).lower() != _clean(product.get("product_fingerprint_sha256")).lower():
        blocks.append("VISUAL_SOURCE_PRODUCT_FINGERPRINT_MISMATCH")
    link_required = _clean(product.get("link_requirement", {}).get("mode")) == "required"
    expected_next = "LINK_BINDING" if link_required else "CADENCE_FATIGUE"
    if _clean(binding.get("next_gate")) != expected_next:
        blocks.append("INVALID_VISUAL_NEXT_GATE")
    if binding.get("synthetic_media_used") is not False:
        blocks.append("SYNTHETIC_MEDIA_FORBIDDEN")
    if binding.get("provenance_complete") is not True:
        blocks.append("VISUAL_PROVENANCE_INCOMPLETE")
    if binding.get("reuse_rights_complete") is not True:
        blocks.append("VISUAL_REUSE_RIGHTS_INCOMPLETE")

    assets = binding.get("selected_assets")
    if not isinstance(assets, list) or not assets:
        blocks.append("MISSING_SELECTED_SERIES_MEDIA")
    else:
        for asset in assets:
            if not isinstance(asset, dict):
                blocks.append("INVALID_SELECTED_SERIES_MEDIA")
                continue
            asset_id = _clean(asset.get("asset_id")) or "UNKNOWN"
            if asset.get("synthetic") is not False:
                blocks.append(f"SYNTHETIC_SELECTED_MEDIA:{asset_id}")
            if asset.get("subject_match") is not True or asset.get("editor_approved") is not True:
                blocks.append(f"UNAPPROVED_SELECTED_MEDIA:{asset_id}")
            if not SHA256_RE.fullmatch(_clean(asset.get("sha256")).lower()):
                blocks.append(f"INVALID_SELECTED_MEDIA_HASH:{asset_id}")
            if not _clean(asset.get("credit")) or not _clean(asset.get("rights_basis")) or not _clean(asset.get("alt_text")):
                blocks.append(f"INCOMPLETE_SELECTED_MEDIA_PROVENANCE:{asset_id}")
            story_ids = asset.get("story_ids")
            if not isinstance(story_ids, list) or not any(_clean(value) for value in story_ids):
                blocks.append(f"SELECTED_MEDIA_STORY_ASSOCIATION_REQUIRED:{asset_id}")
    return sorted(set(blocks)), binding


def _link_binding(product: dict[str, Any], canonical_url: str | None) -> dict[str, Any]:
    requirement = product.get("link_requirement") if isinstance(product.get("link_requirement"), dict) else {}
    mode = _clean(requirement.get("mode")) or "optional"
    allowed = sorted({_clean(value).casefold() for value in requirement.get("canonical_hosts", []) if _clean(value)}) if isinstance(requirement.get("canonical_hosts"), list) else []
    supplied = _clean(canonical_url)
    result: dict[str, Any] = {
        "mode": mode,
        "required": mode == "required",
        "status": "OPTIONAL_UNBOUND",
        "bound_url": None,
        "canonical_host": None,
        "hard_blocks": [],
        "hold": False,
        "network_validation_performed": False,
    }
    if not supplied:
        if mode == "required":
            result["status"] = "REQUIRED_LINK_PENDING"
            result["hold"] = True
        elif mode == "native_preferred":
            result["status"] = "NATIVE_STANDALONE"
        result["binding_fingerprint_sha256"] = _digest(result)
        return result

    parsed = urlparse(supplied)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme.casefold() != "https" or not host:
        result["status"] = "LINK_BLOCKED"
        result["hard_blocks"] = ["INVALID_CANONICAL_URL"]
    elif allowed and host not in allowed:
        result["status"] = "LINK_BLOCKED"
        result["hard_blocks"] = ["LINK_HOST_NOT_ALLOWED"]
    else:
        result["status"] = "LINK_BOUND"
        result["bound_url"] = supplied
        result["canonical_host"] = host
    result["binding_fingerprint_sha256"] = _digest(result)
    return result


def _cadence_candidate(product: dict[str, Any], channel: dict[str, Any]) -> dict[str, Any]:
    series_id = _clean(product.get("series_id"))
    story_ids = [
        _clean(item.get("story_id"))
        for item in product.get("items", [])
        if isinstance(item, dict) and _clean(item.get("story_id"))
    ]
    topic_ids = [f"series:{series_id}"] if series_id else []
    topic_ids.extend(f"story:{story_id}" for story_id in story_ids)
    return {
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "story_id": f"series:{series_id}" if series_id else "",
        "publication_class": "normal",
        "correction_of": None,
        "topic_ids": topic_ids,
        "related_group_id": f"series:{series_id}" if series_id else None,
    }


def _identity(product: dict[str, Any], channel: dict[str, Any]) -> dict[str, str]:
    payload = {
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "series_id": _clean(product.get("series_id")),
        "series_slot_key": _clean(product.get("series_slot_key")),
        "series_execution_id": _clean(product.get("series_execution_id")),
        "product_id": _clean(product.get("product_id")),
        "product_fingerprint_sha256": _clean(product.get("product_fingerprint_sha256")).lower(),
    }
    dedupe_key = _digest(payload)
    return {
        **payload,
        "dedupe_key": dedupe_key,
        "publication_id": "series-publication:" + dedupe_key[:24],
    }


def _desired_status(
    channel: dict[str, Any],
    product: dict[str, Any],
    link: dict[str, Any],
    cadence: dict[str, Any] | None,
    human_approved: bool,
) -> tuple[str, str]:
    if link.get("hold") is True:
        return "HOLD_LINK_BINDING", "REQUIRED_LINK_PENDING"
    if cadence is not None and cadence.get("eligible") is not True:
        return "HOLD_TIMING", _clean(cadence.get("decision")) or "HOLD_CADENCE"
    approval = product.get("approval") if isinstance(product.get("approval"), dict) else {}
    if approval.get("human_review_required_before_publish") is True and human_approved is not True:
        return "AWAITING_APPROVAL", "HUMAN_APPROVAL_REQUIRED"
    if _clean(channel.get("status")) == "outbox_only":
        return "OUTBOX_READY", "CHANNEL_OUTBOX_ONLY"
    return "READY", "ALL_RUNTIME_GATES_CLEAR"


def _series_slot_conflict(
    identity: dict[str, str],
    outbox: dict[str, Any],
    state: dict[str, Any],
) -> tuple[list[str], bool]:
    slot_key = identity["series_slot_key"]
    outbox_matches = [item for item in outbox["items"] if _clean(item.get("series_slot_key")) == slot_key]
    state_matches = [record for record in state["records"].values() if isinstance(record, dict) and _clean(record.get("series_slot_key")) == slot_key]
    if len(outbox_matches) > 1 or len(state_matches) > 1:
        return ["DUPLICATE_SERIES_SLOT_PUBLICATION_STATE"], False
    if bool(outbox_matches) != bool(state_matches):
        return ["SERIES_PUBLICATION_STATE_OUTBOX_DIVERGENCE"], False
    if outbox_matches:
        outbox_id = _clean(outbox_matches[0].get("publication_id"))
        state_id = _clean(state_matches[0].get("publication_id"))
        if outbox_id != state_id:
            return ["SERIES_PUBLICATION_ID_DIVERGENCE"], False
        if outbox_id != identity["publication_id"]:
            return [], True
    return [], False


def _result(
    *,
    channel: dict[str, Any],
    product: dict[str, Any] | None,
    outbox: dict[str, Any],
    state: dict[str, Any],
    blocked: bool,
    disposition: str,
    hard_blocks: list[str] | None = None,
    series_blocks: list[str] | None = None,
    link_binding: dict[str, Any] | None = None,
    cadence: dict[str, Any] | None = None,
    record: dict[str, Any] | None = None,
    outbox_item: dict[str, Any] | None = None,
    idempotent: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "series_id": _clean((product or {}).get("series_id")) or None,
        "series_execution_id": _clean((product or {}).get("series_execution_id")) or None,
        "series_slot_key": _clean((product or {}).get("series_slot_key")) or None,
        "product_id": _clean((product or {}).get("product_id")) or None,
        "blocked": blocked,
        "hard_blocks": sorted(set(hard_blocks or [])),
        "series_blocks": sorted(set(series_blocks or [])),
        "disposition": disposition,
        "idempotent": idempotent,
        "link_binding": link_binding,
        "cadence": cadence,
        "record": record,
        "outbox_item": outbox_item,
        "outbox": outbox,
        "state": state,
        "handoff": {
            "publication_id": (record or {}).get("publication_id"),
            "publication_status": (record or {}).get("status"),
            "adapter_dispatch_eligible": (record or {}).get("status") == "READY",
            "durable_outbox_ready": (record or {}).get("status") == "OUTBOX_READY",
            "timing_hold": (record or {}).get("status") == "HOLD_TIMING",
            "link_hold": (record or {}).get("status") == "HOLD_LINK_BINDING",
            "human_approval_required": (record or {}).get("status") == "AWAITING_APPROVAL",
            "network_dispatch_performed": False,
        },
        "guards": {
            "channel_native_series_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "real_media_provenance_required_when_visual": True,
            "text_series_visual_bypass_only_when_declared_not_required": True,
            "predictive_analytics_used": False,
            "observed_metrics_only": True,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "paid_scheduler_used": False,
            "paid_llm_api_used": False,
            "zero_paid_dependency": True,
        },
    }
    payload["runtime_fingerprint_sha256"] = _digest({
        "instance_id": payload["instance_id"],
        "channel_id": payload["channel_id"],
        "platform": payload["platform"],
        "series_execution_id": payload["series_execution_id"],
        "product_id": payload["product_id"],
        "disposition": disposition,
        "product_fingerprint_sha256": _clean((product or {}).get("product_fingerprint_sha256")),
        "link_binding_fingerprint_sha256": _clean((link_binding or {}).get("binding_fingerprint_sha256")),
        "cadence_decision_fingerprint_sha256": _clean((cadence or {}).get("decision_fingerprint_sha256")),
        "publication_id": (record or {}).get("publication_id"),
        "publication_status": (record or {}).get("status"),
        "hard_blocks": payload["hard_blocks"],
        "series_blocks": payload["series_blocks"],
    })
    return payload


def bridge_series_publication(
    composition_result: dict[str, Any],
    channel: dict[str, Any],
    cadence_history: dict[str, Any],
    *,
    now: str,
    visual_result: dict[str, Any] | None = None,
    canonical_url: str | None = None,
    publication_outbox: dict[str, Any] | None = None,
    publication_state: dict[str, Any] | None = None,
    human_approved: bool = False,
) -> dict[str, Any]:
    """Move one native recurring-series product into durable publication state."""
    if not all(isinstance(value, dict) for value in (composition_result, channel, cadence_history)):
        raise TypeError("composition_result, channel and cadence_history must be mappings")
    if visual_result is not None and not isinstance(visual_result, dict):
        raise TypeError("visual_result must be a mapping when provided")
    if publication_outbox is not None and not isinstance(publication_outbox, dict):
        raise TypeError("publication_outbox must be a mapping when provided")
    if publication_state is not None and not isinstance(publication_state, dict):
        raise TypeError("publication_state must be a mapping when provided")
    if not _clean(now):
        raise ValueError("now is required and must be timezone-aware")

    outbox = copy.deepcopy(publication_outbox) if publication_outbox is not None else _default_outbox(channel)
    state = copy.deepcopy(publication_state) if publication_state is not None else _default_state(channel)
    container_blocks = _container_blocks(channel, outbox, state)
    if container_blocks:
        return _result(
            channel=channel,
            product=None,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_SERIES_PUBLICATION_STATE",
            hard_blocks=container_blocks,
        )

    product_blocks = _product_blocks(composition_result, channel)
    product = composition_result.get("product") if isinstance(composition_result.get("product"), dict) else None
    if product_blocks or product is None:
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_SERIES_PRODUCT",
            hard_blocks=product_blocks or ["MISSING_SERIES_PRODUCT"],
        )

    visual_blocks, visual_binding = _visual_blocks(product, channel, visual_result)
    if visual_blocks:
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_SERIES_VISUAL",
            hard_blocks=visual_blocks,
        )

    if _clean(cadence_history.get("instance_id")) != _clean(channel.get("instance_id")):
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_CADENCE_HISTORY",
            hard_blocks=["HISTORY_INSTANCE_MISMATCH"],
        )
    if _clean(cadence_history.get("channel_id")) != _clean(channel.get("channel_id")):
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_CADENCE_HISTORY",
            hard_blocks=["HISTORY_CHANNEL_MISMATCH"],
        )
    if not isinstance(cadence_history.get("records"), list):
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_CADENCE_HISTORY",
            hard_blocks=["INVALID_CADENCE_HISTORY"],
        )

    link = _link_binding(product, canonical_url)
    if link.get("hard_blocks"):
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_LINK_POLICY",
            hard_blocks=[str(value) for value in link.get("hard_blocks", [])],
            link_binding=link,
        )

    cadence: dict[str, Any] | None = None
    if link.get("hold") is not True:
        cadence = cadence_fatigue.evaluate_cadence(
            _cadence_candidate(product, channel),
            channel,
            cadence_history,
            now=now,
        )
        if cadence.get("hard_blocks"):
            return _result(
                channel=channel,
                product=product,
                outbox=outbox,
                state=state,
                blocked=True,
                disposition="BLOCKED_CADENCE",
                hard_blocks=[str(value) for value in cadence.get("hard_blocks", [])],
                link_binding=link,
                cadence=cadence,
            )

    identity = _identity(product, channel)
    divergence_blocks, slot_conflict = _series_slot_conflict(identity, outbox, state)
    if divergence_blocks:
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_SERIES_PUBLICATION_DIVERGENCE",
            hard_blocks=divergence_blocks,
            link_binding=link,
            cadence=cadence,
        )
    if slot_conflict:
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=False,
            disposition="HOLD_SERIES_SLOT_CONFLICT",
            series_blocks=["SERIES_SLOT_ALREADY_BOUND_TO_DIFFERENT_PRODUCT"],
            link_binding=link,
            cadence=cadence,
        )

    desired_status, state_reason = _desired_status(channel, product, link, cadence, human_approved)
    records = state["records"]
    existing_record = records.get(identity["publication_id"])
    existing_item = next((item for item in outbox["items"] if _clean(item.get("publication_id")) == identity["publication_id"]), None)
    if bool(existing_record) != bool(existing_item):
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=True,
            disposition="BLOCKED_SERIES_PUBLICATION_DIVERGENCE",
            hard_blocks=["SERIES_PUBLICATION_STATE_OUTBOX_DIVERGENCE"],
            link_binding=link,
            cadence=cadence,
        )

    cadence_summary = None
    if cadence is not None:
        cadence_summary = {
            "decision": cadence.get("decision"),
            "eligible": cadence.get("eligible") is True,
            "cadence_blocks": list(cadence.get("cadence_blocks", [])),
            "next_eligible_at": cadence.get("next_eligible_at"),
            "decision_fingerprint_sha256": cadence.get("decision_fingerprint_sha256"),
        }

    if isinstance(existing_record, dict) and isinstance(existing_item, dict):
        if _clean(existing_record.get("dedupe_key")) != identity["dedupe_key"]:
            return _result(
                channel=channel,
                product=product,
                outbox=outbox,
                state=state,
                blocked=True,
                disposition="BLOCKED_SERIES_PUBLICATION_COLLISION",
                hard_blocks=["SERIES_PUBLICATION_ID_COLLISION"],
                link_binding=link,
                cadence=cadence,
            )
        if _clean(existing_record.get("product_fingerprint_sha256")).lower() != identity["product_fingerprint_sha256"]:
            return _result(
                channel=channel,
                product=product,
                outbox=outbox,
                state=state,
                blocked=True,
                disposition="BLOCKED_SERIES_PUBLICATION_COLLISION",
                hard_blocks=["SERIES_PUBLICATION_PRODUCT_FINGERPRINT_DIVERGENCE"],
                link_binding=link,
                cadence=cadence,
            )
        if _clean(existing_item.get("product_fingerprint_sha256")).lower() != identity["product_fingerprint_sha256"]:
            return _result(
                channel=channel,
                product=product,
                outbox=outbox,
                state=state,
                blocked=True,
                disposition="BLOCKED_SERIES_PUBLICATION_COLLISION",
                hard_blocks=["SERIES_OUTBOX_PRODUCT_FINGERPRINT_DIVERGENCE"],
                link_binding=link,
                cadence=cadence,
            )

        current_status = _clean(existing_record.get("status"))
        if current_status == "PUBLISHED":
            disposition = "DEDUPE_ALREADY_PUBLISHED"
            idempotent = True
        else:
            idempotent = current_status == desired_status
            existing_record["status"] = desired_status
            existing_record["state_reason"] = state_reason
            existing_record["human_approved"] = human_approved is True or existing_record.get("human_approved") is True
            existing_record["link_binding_fingerprint_sha256"] = link.get("binding_fingerprint_sha256")
            existing_record["cadence_decision_fingerprint_sha256"] = (cadence or {}).get("decision_fingerprint_sha256")
            existing_record["next_eligible_at"] = (cadence or {}).get("next_eligible_at")
            existing_item["status"] = desired_status
            existing_item["state_reason"] = state_reason
            existing_item["human_approved"] = existing_record["human_approved"]
            existing_item["link_binding"] = copy.deepcopy(link)
            existing_item["cadence"] = copy.deepcopy(cadence_summary)
            existing_item["dispatch"]["adapter_dispatch_eligible"] = desired_status == "READY"
            existing_item["dispatch"]["durable_outbox_ready"] = desired_status == "OUTBOX_READY"
            existing_item["outbox_item_fingerprint_sha256"] = _digest({key: value for key, value in existing_item.items() if key != "outbox_item_fingerprint_sha256"})
            disposition = "IDEMPOTENT_" + desired_status if idempotent else "UPDATED_" + desired_status
        return _result(
            channel=channel,
            product=product,
            outbox=outbox,
            state=state,
            blocked=False,
            disposition=disposition,
            link_binding=link,
            cadence=cadence,
            record=copy.deepcopy(existing_record),
            outbox_item=copy.deepcopy(existing_item),
            idempotent=idempotent,
        )

    record = {
        "publication_id": identity["publication_id"],
        "dedupe_key": identity["dedupe_key"],
        "instance_id": identity["instance_id"],
        "channel_id": identity["channel_id"],
        "platform": identity["platform"],
        "series_id": identity["series_id"],
        "series_slot_key": identity["series_slot_key"],
        "series_execution_id": identity["series_execution_id"],
        "product_id": identity["product_id"],
        "product_fingerprint_sha256": identity["product_fingerprint_sha256"],
        "visual_binding_fingerprint_sha256": (visual_binding or {}).get("binding_fingerprint_sha256"),
        "link_binding_fingerprint_sha256": link.get("binding_fingerprint_sha256"),
        "cadence_decision_fingerprint_sha256": (cadence or {}).get("decision_fingerprint_sha256"),
        "status": desired_status,
        "state_reason": state_reason,
        "next_eligible_at": (cadence or {}).get("next_eligible_at"),
        "human_approved": human_approved is True,
        "remote_publication_id": None,
        "guards": {
            "channel_native_series_only": True,
            "verbatim_cross_platform_reuse_allowed": False,
            "network_dispatch_performed": False,
            "zero_paid_dependency": True,
        },
    }
    records[identity["publication_id"]] = record

    outbox_item = {
        "publication_id": identity["publication_id"],
        "dedupe_key": identity["dedupe_key"],
        "instance_id": identity["instance_id"],
        "channel_id": identity["channel_id"],
        "platform": identity["platform"],
        "series_id": identity["series_id"],
        "series_slot_key": identity["series_slot_key"],
        "series_execution_id": identity["series_execution_id"],
        "product_id": identity["product_id"],
        "product_fingerprint_sha256": identity["product_fingerprint_sha256"],
        "status": desired_status,
        "state_reason": state_reason,
        "human_approved": human_approved is True,
        "product": copy.deepcopy(product),
        "visual_binding": copy.deepcopy(visual_binding),
        "link_binding": copy.deepcopy(link),
        "cadence": copy.deepcopy(cadence_summary),
        "dispatch": {
            "adapter_dispatch_eligible": desired_status == "READY",
            "durable_outbox_ready": desired_status == "OUTBOX_READY",
            "network_dispatch_performed": False,
            "credentials_read": False,
        },
        "guards": {
            "reuse_prior_copy": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "predictive_analytics_used": False,
            "zero_paid_dependency": True,
        },
    }
    outbox_item["outbox_item_fingerprint_sha256"] = _digest(outbox_item)
    outbox["items"].append(outbox_item)

    return _result(
        channel=channel,
        product=product,
        outbox=outbox,
        state=state,
        blocked=False,
        disposition="REGISTERED_" + desired_status,
        link_binding=link,
        cadence=cadence,
        record=copy.deepcopy(record),
        outbox_item=copy.deepcopy(outbox_item),
        idempotent=False,
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("composition_result", type=Path)
    parser.add_argument("channel", type=Path)
    parser.add_argument("cadence_history", type=Path)
    parser.add_argument("--now", required=True, help="timezone-aware ISO-8601 instant")
    parser.add_argument("--visual-result", type=Path)
    parser.add_argument("--canonical-url")
    parser.add_argument("--publication-outbox", type=Path)
    parser.add_argument("--publication-state", type=Path)
    parser.add_argument("--human-approved", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    result = bridge_series_publication(
        _load(args.composition_result),
        _load(args.channel),
        _load(args.cadence_history),
        now=args.now,
        visual_result=_load(args.visual_result) if args.visual_result else None,
        canonical_url=args.canonical_url,
        publication_outbox=_load(args.publication_outbox) if args.publication_outbox else None,
        publication_state=_load(args.publication_state) if args.publication_state else None,
        human_approved=args.human_approved,
    )
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 2 if result["blocked"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
