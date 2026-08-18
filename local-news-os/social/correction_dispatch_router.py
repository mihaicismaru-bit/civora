#!/usr/bin/env python3
"""Fail-closed correction dispatch routing for LOCAL NEWS OS social publications.

This boundary turns the channel-local actions emitted by ``correction_propagation``
into deterministic correction delivery intents without performing network I/O. It
never reuses prior social copy. Every published correction requires a freshly
regenerated native product from the verified corrected fact kernel.

Direct adapters may only receive a correction intent when their capability registry
explicitly proves the correction mode. Otherwise the correction remains in a durable
channel-local outbox. Outbox-only sister publications always remain outbox-only.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

SCHEMA_VERSION = "1.0"
DIRECT_MODES = {
    "native_api",
    "native_api_fail_closed",
    "native_api_gated_by_site_consent_and_app_audit",
}
OUTBOX_ONLY_MODE = "durable_outbox_only"
REQUIRED_CORRECTION_CAPABILITY_FLAGS = (
    "remote_edit_supported",
    "remote_edit_verified",
    "native_correction_direct_publish_supported",
    "durable_native_correction_outbox_supported",
    "requires_regenerated_native_product",
)
FORBIDDEN_KEY_PARTS = {
    "token", "secret", "password", "authorization", "api_key", "apikey",
    "cookie", "bearer",
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


def _contains_forbidden_secret_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = _clean(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return True
            if _contains_forbidden_secret_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_forbidden_secret_field(item) for item in value)
    return False


def _registry_entry(registry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = registry.get("channels") if isinstance(registry.get("channels"), list) else []
    matches = [
        row for row in rows
        if isinstance(row, dict) and _platform(row.get("channel_id")) == _platform(platform)
    ]
    return matches[0] if len(matches) == 1 else None


def _capability_entry(capabilities: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = capabilities.get("adapters") if isinstance(capabilities.get("adapters"), list) else []
    matches = [
        row for row in rows
        if isinstance(row, dict) and _platform(row.get("platform")) == _platform(platform)
    ]
    return matches[0] if len(matches) == 1 else None


def _correction_capability_errors(capability: dict[str, Any], platform: str) -> list[str]:
    errors: list[str] = []
    contract = capability.get("correction_capabilities")
    if not isinstance(contract, dict):
        return [f"{platform}:CORRECTION_CAPABILITY_CONTRACT_MISSING"]
    for key in REQUIRED_CORRECTION_CAPABILITY_FLAGS:
        if not isinstance(contract.get(key), bool):
            errors.append(f"{platform}:CORRECTION_CAPABILITY_FLAG_REQUIRED:{key}")
    if contract.get("remote_edit_supported") is True and contract.get("remote_edit_verified") is not True:
        errors.append(f"{platform}:REMOTE_EDIT_SUPPORT_REQUIRES_VERIFIED_PROOF")
    if contract.get("requires_regenerated_native_product") is not True:
        errors.append(f"{platform}:CORRECTION_MUST_REQUIRE_REGENERATED_NATIVE_PRODUCT")
    if (
        contract.get("native_correction_direct_publish_supported") is not True
        and contract.get("durable_native_correction_outbox_supported") is not True
        and contract.get("remote_edit_supported") is not True
    ):
        errors.append(f"{platform}:NO_SAFE_CORRECTION_DELIVERY_MODE")
    if _contains_forbidden_secret_field(contract):
        errors.append(f"{platform}:CORRECTION_CAPABILITY_CONTAINS_SECRET_FIELD")
    return errors


def validate_correction_capability_registry(
    registry: dict[str, Any],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Validate explicit correction support for every direct publication adapter."""
    if not isinstance(registry, dict) or not isinstance(capabilities, dict):
        raise TypeError("registry and capabilities must be mappings")
    errors: list[str] = []
    instance_id = _clean(registry.get("instance_id"))
    if not instance_id:
        errors.append("REGISTRY_INSTANCE_ID_MISSING")
    if _clean(capabilities.get("instance_id")) != instance_id:
        errors.append("CORRECTION_CAPABILITY_INSTANCE_MISMATCH")
    registry_policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    if registry_policy.get("correction_propagation_required") is not True:
        errors.append("CORRECTION_PROPAGATION_POLICY_REQUIRED")
    if registry_policy.get("paid_social_scheduler_required") is not False:
        errors.append("PAID_SOCIAL_SCHEDULER_FORBIDDEN")
    if registry_policy.get("paid_llm_api_required") is not False:
        errors.append("PAID_LLM_API_FORBIDDEN")
    capability_policy = capabilities.get("policy") if isinstance(capabilities.get("policy"), dict) else {}
    if capability_policy.get("zero_paid_dependency") is not True:
        errors.append("CORRECTION_CAPABILITY_ZERO_PAID_REQUIRED")
    if capability_policy.get("credential_values_allowed") is not False:
        errors.append("CORRECTION_CAPABILITY_CREDENTIAL_VALUES_FORBIDDEN")
    if _contains_forbidden_secret_field({"adapters": capabilities.get("adapters", [])}):
        errors.append("CORRECTION_CAPABILITY_REGISTRY_CONTAINS_SECRET_FIELD")

    direct_platforms: list[str] = []
    for raw in registry.get("channels", []) if isinstance(registry.get("channels"), list) else []:
        if not isinstance(raw, dict) or raw.get("direct_publication_enabled") is not True:
            continue
        platform = _platform(raw.get("channel_id"))
        if not platform:
            errors.append("DIRECT_CORRECTION_CHANNEL_MISSING_PLATFORM")
            continue
        direct_platforms.append(platform)
        if _clean(raw.get("status")).lower() != "active":
            errors.append(f"{platform}:DIRECT_CORRECTION_CHANNEL_NOT_ACTIVE")
        if _clean(raw.get("publication_mode")).lower() not in DIRECT_MODES:
            errors.append(f"{platform}:DIRECT_CORRECTION_MODE_INVALID")
        capability = _capability_entry(capabilities, platform)
        if capability is None:
            errors.append(f"{platform}:DIRECT_CORRECTION_CAPABILITY_MISSING")
            continue
        if _clean(capability.get("adapter")) != _clean(raw.get("adapter")):
            errors.append(f"{platform}:CORRECTION_CAPABILITY_ADAPTER_MISMATCH")
        errors.extend(_correction_capability_errors(capability, platform))

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not errors else "BLOCKED",
        "instance_id": instance_id or None,
        "direct_platforms": sorted(set(direct_platforms)),
        "errors": sorted(set(errors)),
        "guards": {
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "prior_social_copy_reused": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def _action_contract_errors(action: dict[str, Any], instance_id: str) -> list[str]:
    errors: list[str] = []
    if _clean(action.get("instance_id")) != instance_id:
        errors.append("CORRECTION_ACTION_INSTANCE_MISMATCH")
    if not _clean(action.get("action_id")):
        errors.append("CORRECTION_ACTION_ID_MISSING")
    if not _clean(action.get("channel_id")):
        errors.append("CORRECTION_ACTION_CHANNEL_ID_MISSING")
    if not _platform(action.get("platform")):
        errors.append("CORRECTION_ACTION_PLATFORM_MISSING")
    if not _clean(action.get("correction_story_id")):
        errors.append("CORRECTION_ACTION_STORY_ID_MISSING")
    native = action.get("native_regeneration")
    if not isinstance(native, dict):
        errors.append("CORRECTION_NATIVE_REGENERATION_CONTRACT_MISSING")
    else:
        if native.get("required") is not True:
            errors.append("CORRECTION_NATIVE_REGENERATION_REQUIRED")
        if native.get("reuse_prior_copy") is not False:
            errors.append("CORRECTION_PRIOR_COPY_REUSE_FORBIDDEN")
        if native.get("verbatim_cross_platform_reuse_allowed") is not False:
            errors.append("CORRECTION_VERBATIM_CROSS_PLATFORM_REUSE_FORBIDDEN")
        if not _is_sha256(native.get("fact_kernel_sha256")):
            errors.append("CORRECTION_FACT_KERNEL_FINGERPRINT_INVALID")
    guards = action.get("guards") if isinstance(action.get("guards"), dict) else {}
    if guards.get("zero_paid_dependency") is not True:
        errors.append("CORRECTION_ACTION_ZERO_PAID_REQUIRED")
    if _contains_forbidden_secret_field(action):
        errors.append("CORRECTION_ACTION_CONTAINS_SECRET_FIELD")
    return errors


def _route_id(action: dict[str, Any], decision: str, adapter: str | None, outbox: str | None) -> str:
    return "correction-route:" + _digest({
        "action_id": _clean(action.get("action_id")),
        "channel_id": _clean(action.get("channel_id")),
        "decision": decision,
        "adapter": adapter,
        "outbox": outbox,
    })[:24]


def _base_route(action: dict[str, Any], decision: str, entry: dict[str, Any]) -> dict[str, Any]:
    adapter = _clean(entry.get("adapter")) or None
    outbox = _clean(entry.get("outbox")) or None
    native = action.get("native_regeneration") if isinstance(action.get("native_regeneration"), dict) else {}
    return {
        "route_id": _route_id(action, decision, adapter, outbox),
        "action_id": _clean(action.get("action_id")),
        "decision": decision,
        "instance_id": _clean(action.get("instance_id")),
        "channel_id": _clean(action.get("channel_id")),
        "platform": _platform(action.get("platform")),
        "correction_story_id": _clean(action.get("correction_story_id")),
        "affected_story_id": _clean(action.get("affected_story_id")) or None,
        "affected_publication_id": _clean(action.get("affected_publication_id")) or None,
        "remote_publication_id": _clean(action.get("remote_publication_id")) or None,
        "adapter": adapter,
        "outbox": outbox,
        "fact_kernel_sha256": _clean(native.get("fact_kernel_sha256")).lower(),
        "native_regeneration_required": True,
        "reuse_prior_copy": False,
        "verbatim_cross_platform_reuse_allowed": False,
        "network_dispatch_performed": False,
        "credential_values_read": False,
        "zero_paid_dependency": True,
    }


def build_correction_dispatch_plan(
    propagation: dict[str, Any],
    registry: dict[str, Any],
    capabilities: dict[str, Any],
) -> dict[str, Any]:
    """Route correction actions to explicit direct/outbox/state-only delivery boundaries."""
    if not all(isinstance(value, dict) for value in (propagation, registry, capabilities)):
        raise TypeError("propagation, registry and capabilities must be mappings")

    instance_id = _clean(propagation.get("instance_id"))
    global_errors: list[str] = []
    if not instance_id:
        global_errors.append("CORRECTION_PROPAGATION_INSTANCE_ID_MISSING")
    if _clean(registry.get("instance_id")) != instance_id:
        global_errors.append("CORRECTION_REGISTRY_INSTANCE_MISMATCH")
    if _clean(capabilities.get("instance_id")) != instance_id:
        global_errors.append("CORRECTION_CAPABILITY_INSTANCE_MISMATCH")
    if propagation.get("blocked") is True:
        global_errors.append("UPSTREAM_CORRECTION_PROPAGATION_BLOCKED")
    if propagation.get("guards", {}).get("zero_paid_dependency") is not True:
        global_errors.append("UPSTREAM_CORRECTION_ZERO_PAID_GUARD_MISSING")

    capability_validation = validate_correction_capability_registry(registry, capabilities)
    global_errors.extend(capability_validation.get("errors", []))
    actions = propagation.get("actions")
    if not isinstance(actions, list):
        global_errors.append("CORRECTION_ACTIONS_INVALID")
        actions = []

    if global_errors:
        return {
            "schema_version": SCHEMA_VERSION,
            "status": "BLOCKED",
            "blocked": True,
            "partial": False,
            "instance_id": instance_id or None,
            "hard_blocks": sorted(set(global_errors)),
            "routes": [],
            "holds": [],
            "guards": {
                "network_calls_performed": False,
                "credential_values_read": False,
                "credential_values_exposed": False,
                "prior_social_copy_reused": False,
                "verbatim_cross_platform_reuse_allowed": False,
                "zero_paid_dependency": True,
            },
        }

    routes: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    for raw in actions:
        if not isinstance(raw, dict):
            holds.append({"action_id": None, "reason": "CORRECTION_ACTION_NOT_MAPPING"})
            continue
        action_errors = _action_contract_errors(raw, instance_id)
        platform = _platform(raw.get("platform"))
        entry = _registry_entry(registry, platform)
        if entry is None:
            action_errors.append("CORRECTION_CHANNEL_REGISTRY_ENTRY_MISSING")
        if action_errors:
            holds.append({
                "action_id": _clean(raw.get("action_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "platform": platform or None,
                "reasons": sorted(set(action_errors)),
            })
            continue
        assert entry is not None
        action_kind = _clean(raw.get("action")).upper()
        direct = entry.get("direct_publication_enabled") is True
        mode = _clean(entry.get("publication_mode")).lower()

        if action_kind == "ALREADY_PROPAGATED":
            route = _base_route(raw, "IDEMPOTENT_NOOP", entry)
            route["dispatchable"] = False
            routes.append(route)
            continue
        if action_kind == "SUPERSEDE_UNPUBLISHED":
            route = _base_route(raw, "STATE_ONLY_SUPERSEDE", entry)
            route["dispatchable"] = False
            routes.append(route)
            continue
        if action_kind == "RECONCILE_IN_FLIGHT":
            route = _base_route(raw, "RECONCILE_BEFORE_CORRECTION", entry)
            route["dispatchable"] = False
            routes.append(route)
            continue
        if action_kind != "CORRECT_PUBLISHED_NATIVE":
            holds.append({
                "action_id": _clean(raw.get("action_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "platform": platform or None,
                "reasons": ["CORRECTION_ACTION_KIND_UNSUPPORTED"],
            })
            continue
        if not _clean(raw.get("remote_publication_id")):
            holds.append({
                "action_id": _clean(raw.get("action_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "platform": platform or None,
                "reasons": ["CORRECTION_REMOTE_PUBLICATION_ID_REQUIRED"],
            })
            continue

        if not direct:
            if mode != OUTBOX_ONLY_MODE or not _clean(entry.get("outbox")):
                holds.append({
                    "action_id": _clean(raw.get("action_id")) or None,
                    "channel_id": _clean(raw.get("channel_id")) or None,
                    "platform": platform or None,
                    "reasons": ["CORRECTION_OUTBOX_ONLY_CHANNEL_NOT_DURABLE"],
                })
                continue
            route = _base_route(raw, "MATERIALIZE_NATIVE_CORRECTION_OUTBOX", entry)
            route["dispatchable"] = False
            route["publication_mode"] = OUTBOX_ONLY_MODE
            routes.append(route)
            continue

        capability = _capability_entry(capabilities, platform)
        assert capability is not None
        correction_contract = capability.get("correction_capabilities")
        assert isinstance(correction_contract, dict)
        if correction_contract.get("remote_edit_supported") is True and correction_contract.get("remote_edit_verified") is True:
            decision = "EDIT_REMOTE_PUBLICATION"
            dispatchable = True
        elif correction_contract.get("native_correction_direct_publish_supported") is True:
            decision = "PUBLISH_NATIVE_CORRECTION"
            dispatchable = True
        elif correction_contract.get("durable_native_correction_outbox_supported") is True and _clean(entry.get("outbox")):
            decision = "MATERIALIZE_NATIVE_CORRECTION_OUTBOX"
            dispatchable = False
        else:
            holds.append({
                "action_id": _clean(raw.get("action_id")) or None,
                "channel_id": _clean(raw.get("channel_id")) or None,
                "platform": platform or None,
                "reasons": ["NO_VERIFIED_CORRECTION_DELIVERY_MODE"],
            })
            continue
        route = _base_route(raw, decision, entry)
        route["dispatchable"] = dispatchable
        route["publication_mode"] = mode
        route["remote_edit_claimed"] = decision == "EDIT_REMOTE_PUBLICATION"
        routes.append(route)

    routes.sort(key=lambda row: (_clean(row.get("channel_id")), _clean(row.get("action_id")), _clean(row.get("decision"))))
    holds.sort(key=_canonical)
    status = "PASS" if not holds else ("PARTIAL" if routes else "BLOCKED")
    return {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "blocked": status == "BLOCKED",
        "partial": status == "PARTIAL",
        "instance_id": instance_id,
        "correction_story_id": _clean(propagation.get("correction_story_id")) or None,
        "propagation_fingerprint_sha256": _clean(propagation.get("propagation_fingerprint_sha256")) or None,
        "route_count": len(routes),
        "hold_count": len(holds),
        "routes": routes,
        "holds": holds,
        "dispatch_plan_fingerprint_sha256": _digest({"instance_id": instance_id, "routes": routes, "holds": holds}),
        "guards": {
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_exposed": False,
            "prior_social_copy_reused": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "remote_edit_requires_explicit_verified_capability": True,
            "unverified_direct_correction_falls_back_to_durable_outbox": True,
            "zero_paid_dependency": True,
        },
    }
