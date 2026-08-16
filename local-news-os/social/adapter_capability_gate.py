#!/usr/bin/env python3
"""Truthful adapter-capability gate for LOCAL NEWS OS social dispatch.

The generic social runtime can build a native product that a currently installed
network adapter cannot yet publish. This module closes that gap without weakening
the editorial product or inventing a fallback format.

It composes the existing Adapter-Gated Dispatch Bridge. If the current adapter
truthfully supports the runtime product, the normal DIRECT_READY handoff is
preserved. If the channel itself supports the product but the installed adapter
does not, the exact native product is durably retained as OUTBOX_ONLY instead of
being silently downgraded, cross-posted, or sent through the wrong media API.

The capability contract contains no credentials and never performs network calls.
Existing platform adapters remain the only network boundary.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable

import adapter_dispatch_bridge

SCHEMA_VERSION = "1.0"
ALLOWED_FORMATS = {
    "text", "single_photo", "carousel", "story", "reel", "short",
    "long_video", "thread", "alert", "digest", "live",
}
ALLOWED_MEDIA_KINDS = {"none", "photograph", "video"}
MEDIA_KIND_ALIASES = {
    "photo": "photograph",
    "photograph": "photograph",
    "real_photo": "photograph",
    "image": "photograph",
    "video": "video",
    "real_video": "video",
    "none": "none",
}
VIDEO_FORMATS = {"reel", "short", "long_video", "live"}
MULTI_ASSET_FORMATS = {"carousel"}
COMPLETION_MODELS = {"immediate_remote_id", "async_remote_status"}
FORBIDDEN_KEY_PARTS = {
    "token", "secret", "password", "authorization", "api_key", "apikey",
    "cookie", "bearer",
}


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform(value: Any) -> str:
    return _clean(value).lower().replace("-", "_")


def _media_kind(value: Any) -> str:
    return MEDIA_KIND_ALIASES.get(_clean(value).lower(), "")


def _inside_instance(path: Any, instance_root: str) -> bool:
    text = _clean(path)
    root_text = _clean(instance_root)
    if not text or not root_text:
        return False
    candidate = PurePosixPath(text)
    root = PurePosixPath(root_text)
    return not candidate.is_absolute() and ".." not in candidate.parts and (candidate == root or root in candidate.parents)


def _contains_secret_field(value: Any) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            lowered = _clean(key).lower()
            if any(part in lowered for part in FORBIDDEN_KEY_PARTS):
                return True
            if _contains_secret_field(child):
                return True
    elif isinstance(value, list):
        return any(_contains_secret_field(item) for item in value)
    return False


def _find_capability(capabilities: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = capabilities.get("adapters") if isinstance(capabilities.get("adapters"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _platform(row.get("platform")) == _platform(platform)]
    return matches[0] if len(matches) == 1 else None


def _find_channel_entry(channel_registry: dict[str, Any], platform: str) -> dict[str, Any] | None:
    rows = channel_registry.get("channels") if isinstance(channel_registry.get("channels"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _platform(row.get("channel_id")) == _platform(platform)]
    return matches[0] if len(matches) == 1 else None


def _entry_errors(entry: dict[str, Any], *, instance_id: str, instance_root: str | None = None) -> list[str]:
    errors: list[str] = []
    platform = _platform(entry.get("platform"))
    channel_id = _clean(entry.get("channel_id"))
    adapter = _clean(entry.get("adapter"))
    formats = entry.get("supported_native_formats")
    media = entry.get("supported_media_kinds")
    max_assets = entry.get("max_media_assets")
    completion = _clean(entry.get("completion_model"))

    if not platform:
        errors.append("CAPABILITY_MISSING_PLATFORM")
    if not channel_id:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MISSING_CHANNEL_ID")
    if not adapter:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MISSING_ADAPTER")
    elif instance_root and not _inside_instance(adapter, instance_root):
        errors.append(f"{platform or 'unknown'}:CAPABILITY_ADAPTER_OUTSIDE_INSTANCE")
    if not isinstance(formats, list) or not formats:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_NATIVE_FORMATS_INVALID")
        formats = []
    normalized_formats = [_clean(value) for value in formats if _clean(value)]
    if len(normalized_formats) != len(set(normalized_formats)):
        errors.append(f"{platform or 'unknown'}:CAPABILITY_NATIVE_FORMATS_DUPLICATE")
    for native_format in normalized_formats:
        if native_format not in ALLOWED_FORMATS:
            errors.append(f"{platform or 'unknown'}:CAPABILITY_NATIVE_FORMAT_UNSUPPORTED:{native_format}")

    if not isinstance(media, list) or not media:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MEDIA_KINDS_INVALID")
        media = []
    normalized_media = [_media_kind(value) for value in media if _clean(value)]
    if "" in normalized_media:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MEDIA_KIND_UNSUPPORTED")
    normalized_media = [value for value in normalized_media if value]
    if len(normalized_media) != len(set(normalized_media)):
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MEDIA_KINDS_DUPLICATE")
    for kind in normalized_media:
        if kind not in ALLOWED_MEDIA_KINDS:
            errors.append(f"{platform or 'unknown'}:CAPABILITY_MEDIA_KIND_UNSUPPORTED:{kind}")

    if not isinstance(max_assets, int) or isinstance(max_assets, bool) or not 0 <= max_assets <= 20:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_MAX_MEDIA_ASSETS_INVALID")
    if completion not in COMPLETION_MODELS:
        errors.append(f"{platform or 'unknown'}:CAPABILITY_COMPLETION_MODEL_INVALID")
    if completion == "async_remote_status" and entry.get("remote_reconciliation_supported") is not True:
        errors.append(f"{platform or 'unknown'}:ASYNC_ADAPTER_REQUIRES_REMOTE_RECONCILIATION")
    if not isinstance(entry.get("remote_reconciliation_supported"), bool):
        errors.append(f"{platform or 'unknown'}:REMOTE_RECONCILIATION_FLAG_REQUIRED")

    if any(fmt in VIDEO_FORMATS for fmt in normalized_formats) and "video" not in normalized_media:
        errors.append(f"{platform or 'unknown'}:VIDEO_FORMAT_DECLARED_WITHOUT_VIDEO_CAPABILITY")
    if any(fmt in MULTI_ASSET_FORMATS for fmt in normalized_formats) and isinstance(max_assets, int) and max_assets < 2:
        errors.append(f"{platform or 'unknown'}:MULTI_ASSET_FORMAT_EXCEEDS_ADAPTER_LIMIT")
    if _contains_secret_field(entry):
        errors.append(f"{platform or 'unknown'}:CAPABILITY_CONTRACT_MUST_NOT_CONTAIN_SECRETS")
    return errors


def validate_capability_registry(
    capabilities: dict[str, Any],
    channel_registry: dict[str, Any],
    *,
    load_channel: Callable[[str], dict[str, Any]] | None = None,
    instance_root: str | None = None,
) -> dict[str, Any]:
    """Validate capability claims against the installed channel registry/configs."""
    if not isinstance(capabilities, dict) or not isinstance(channel_registry, dict):
        raise TypeError("capabilities and channel_registry must be mappings")
    errors: list[str] = []
    warnings: list[str] = []

    if _clean(capabilities.get("schema_version")) != SCHEMA_VERSION:
        errors.append("CAPABILITY_SCHEMA_VERSION")
    instance_id = _clean(capabilities.get("instance_id"))
    registry_instance = _clean(channel_registry.get("instance_id"))
    if not instance_id:
        errors.append("CAPABILITY_MISSING_INSTANCE_ID")
    if registry_instance and instance_id != registry_instance:
        errors.append("CAPABILITY_INSTANCE_MISMATCH")

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
            errors.append(f"CAPABILITY_POLICY_INVALID:{key}")
    if _contains_secret_field({"adapters": capabilities.get("adapters", [])}):
        errors.append("CAPABILITY_REGISTRY_MUST_NOT_CONTAIN_SECRETS")

    rows = capabilities.get("adapters")
    if not isinstance(rows, list) or not rows:
        errors.append("CAPABILITY_ADAPTERS_MISSING")
        rows = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            errors.append("CAPABILITY_ENTRY_INVALID")
            continue
        platform = _platform(raw.get("platform"))
        if platform in seen:
            errors.append(f"DUPLICATE_CAPABILITY_PLATFORM:{platform}")
        seen.add(platform)
        errors.extend(_entry_errors(raw, instance_id=instance_id, instance_root=instance_root))

        registry_entry = _find_channel_entry(channel_registry, platform)
        if registry_entry is None:
            errors.append(f"{platform or 'unknown'}:CAPABILITY_CHANNEL_NOT_REGISTERED")
            continue
        if registry_entry.get("direct_publication_enabled") is not True:
            warnings.append(f"{platform}:CAPABILITY_DECLARED_FOR_NON_DIRECT_CHANNEL")
        if _clean(registry_entry.get("adapter")) != _clean(raw.get("adapter")):
            errors.append(f"{platform}:CAPABILITY_ADAPTER_PATH_MISMATCH")

        config_path = _clean(registry_entry.get("config"))
        if load_channel is not None and config_path:
            try:
                channel = load_channel(config_path)
            except Exception as exc:
                errors.append(f"{platform}:CAPABILITY_CHANNEL_CONFIG_UNREADABLE:{type(exc).__name__}")
            else:
                if _clean(channel.get("instance_id")) != instance_id:
                    errors.append(f"{platform}:CAPABILITY_CHANNEL_INSTANCE_MISMATCH")
                if _clean(channel.get("channel_id")) != _clean(raw.get("channel_id")):
                    errors.append(f"{platform}:CAPABILITY_CHANNEL_ID_MISMATCH")
                declared = set(channel.get("native_formats", [])) if isinstance(channel.get("native_formats"), list) else set()
                claimed = set(raw.get("supported_native_formats", [])) if isinstance(raw.get("supported_native_formats"), list) else set()
                extra = sorted(claimed - declared)
                if extra:
                    errors.append(f"{platform}:ADAPTER_CLAIMS_FORMAT_NOT_IN_CHANNEL_CONFIG:{','.join(extra)}")

    direct_platforms = {
        _platform(row.get("channel_id"))
        for row in channel_registry.get("channels", [])
        if isinstance(row, dict) and row.get("direct_publication_enabled") is True
    }
    for platform in sorted(direct_platforms - seen):
        errors.append(f"{platform}:DIRECT_ADAPTER_MISSING_CAPABILITY_CONTRACT")

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "PASS" if not errors else "BLOCKED",
        "instance_id": instance_id or None,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "direct_platforms": sorted(direct_platforms),
        "capability_platforms": sorted(seen),
        "guards": {
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_calls_performed": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def assess_runtime_capability(report: dict[str, Any], capability: dict[str, Any]) -> dict[str, Any]:
    """Compare one READY native runtime product with the truthful installed adapter."""
    if not isinstance(report, dict) or not isinstance(capability, dict):
        raise TypeError("report and capability must be mappings")
    platform = _platform(report.get("platform"))
    reasons: list[str] = []
    if _platform(capability.get("platform")) != platform:
        reasons.append("CAPABILITY_PLATFORM_MISMATCH")
    if _clean(capability.get("channel_id")) != _clean(report.get("channel_id")):
        reasons.append("CAPABILITY_CHANNEL_MISMATCH")

    artifacts = report.get("artifacts") if isinstance(report.get("artifacts"), dict) else {}
    formatted = artifacts.get("format") if isinstance(artifacts.get("format"), dict) else {}
    product = formatted.get("product") if isinstance(formatted.get("product"), dict) else {}
    visual = artifacts.get("visual") if isinstance(artifacts.get("visual"), dict) else {}
    binding = visual.get("binding") if isinstance(visual.get("binding"), dict) else {}
    native_format = _clean(product.get("native_format"))
    supported_formats = set(capability.get("supported_native_formats", [])) if isinstance(capability.get("supported_native_formats"), list) else set()
    supported_media = {_media_kind(value) for value in capability.get("supported_media_kinds", []) if _media_kind(value)} if isinstance(capability.get("supported_media_kinds"), list) else set()
    selected = binding.get("selected_assets") if isinstance(binding.get("selected_assets"), list) else []
    max_assets = capability.get("max_media_assets") if isinstance(capability.get("max_media_assets"), int) else -1

    if _clean(report.get("disposition")) != "READY":
        return {
            "schema_version": SCHEMA_VERSION,
            "applicable": False,
            "compatible": True,
            "decision": "UPSTREAM_NOT_READY",
            "platform": platform or None,
            "native_format": native_format or None,
            "gap_reasons": [],
        }
    if not native_format:
        reasons.append("RUNTIME_NATIVE_FORMAT_MISSING")
    elif native_format not in supported_formats:
        reasons.append(f"UNSUPPORTED_NATIVE_FORMAT:{native_format}")

    if max_assets >= 0 and len(selected) > max_assets:
        reasons.append(f"TOO_MANY_MEDIA_ASSETS:{len(selected)}>{max_assets}")
    for asset in selected:
        if not isinstance(asset, dict):
            reasons.append("INVALID_RUNTIME_MEDIA_ASSET")
            continue
        kind = _media_kind(asset.get("kind"))
        if kind not in supported_media:
            reasons.append(f"UNSUPPORTED_MEDIA_KIND:{kind or 'missing'}")
        if asset.get("synthetic") is not False:
            reasons.append("SYNTHETIC_MEDIA_FORBIDDEN")
        if asset.get("editor_approved") is not True or asset.get("subject_match") is not True:
            reasons.append("UNAPPROVED_OR_OFF_SUBJECT_MEDIA")
        if not _clean(asset.get("rights_basis")) or not _clean(asset.get("credit")):
            reasons.append("MEDIA_PROVENANCE_INCOMPLETE")

    visual_requirement = product.get("visual_requirement") if isinstance(product.get("visual_requirement"), dict) else {}
    if visual_requirement.get("required") is True and not selected:
        reasons.append("REQUIRED_MEDIA_NOT_BOUND")
    if native_format in VIDEO_FORMATS and "video" not in supported_media:
        reasons.append("VIDEO_NATIVE_PRODUCT_WITHOUT_VIDEO_ADAPTER")
    if native_format in MULTI_ASSET_FORMATS and max_assets < 2:
        reasons.append("MULTI_ASSET_PRODUCT_WITH_SINGLE_ASSET_ADAPTER")

    reasons = sorted(set(reasons))
    return {
        "schema_version": SCHEMA_VERSION,
        "applicable": True,
        "compatible": not reasons,
        "decision": "DIRECT_CAPABILITY_MATCH" if not reasons else "DURABLE_OUTBOX_CAPABILITY_GAP",
        "platform": platform or None,
        "native_format": native_format or None,
        "supported_native_formats": sorted(supported_formats),
        "selected_media_kinds": sorted({_media_kind(asset.get("kind")) for asset in selected if isinstance(asset, dict) and _media_kind(asset.get("kind"))}),
        "supported_media_kinds": sorted(supported_media),
        "selected_media_assets": len(selected),
        "max_media_assets": max_assets,
        "completion_model": _clean(capability.get("completion_model")) or None,
        "remote_reconciliation_supported": capability.get("remote_reconciliation_supported") is True,
        "gap_reasons": reasons,
        "guards": {
            "native_product_rewritten": False,
            "fallback_format_invented": False,
            "credential_values_read": False,
            "network_calls_performed": False,
            "zero_paid_dependency": True,
        },
    }


def _runtime_contract_errors(capabilities: dict[str, Any], channel_registry: dict[str, Any], platform: str) -> list[str]:
    errors: list[str] = []
    if _clean(capabilities.get("schema_version")) != SCHEMA_VERSION:
        errors.append("CAPABILITY_SCHEMA_VERSION")
    if _clean(capabilities.get("instance_id")) != _clean(channel_registry.get("instance_id")):
        errors.append("CAPABILITY_INSTANCE_MISMATCH")
    policy = capabilities.get("policy") if isinstance(capabilities.get("policy"), dict) else {}
    if policy.get("fail_closed_on_capability_mismatch") is not True:
        errors.append("CAPABILITY_POLICY_NOT_FAIL_CLOSED")
    if policy.get("durable_outbox_on_supported_channel_format_gap") is not True:
        errors.append("CAPABILITY_POLICY_OUTBOX_REQUIRED")
    if policy.get("credential_values_allowed") is not False:
        errors.append("CAPABILITY_CREDENTIAL_VALUES_FORBIDDEN")
    if policy.get("verbatim_cross_platform_reuse_allowed") is not False:
        errors.append("CAPABILITY_VERBATIM_REUSE_FORBIDDEN")
    if policy.get("zero_paid_dependency") is not True:
        errors.append("CAPABILITY_ZERO_PAID_DEPENDENCY_REQUIRED")

    capability = _find_capability(capabilities, platform)
    registry_entry = _find_channel_entry(channel_registry, platform)
    if capability is None:
        errors.append("DIRECT_ADAPTER_CAPABILITY_MISSING")
    if registry_entry is None:
        errors.append("CHANNEL_REGISTRY_ENTRY_MISSING")
    if capability is not None:
        errors.extend(_entry_errors(capability, instance_id=_clean(capabilities.get("instance_id"))))
    if capability is not None and registry_entry is not None and _clean(capability.get("adapter")) != _clean(registry_entry.get("adapter")):
        errors.append("CAPABILITY_ADAPTER_PATH_MISMATCH")
    return sorted(set(errors))


def _blocked(report: dict[str, Any], reasons: Iterable[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "instance_id": _clean(report.get("instance_id")) or None,
        "channel_id": _clean(report.get("channel_id")) or None,
        "platform": _platform(report.get("platform")) or None,
        "blocked": True,
        "hard_blocks": sorted(set(str(reason) for reason in reasons)),
        "decision": "BLOCKED_ADAPTER_CAPABILITY_CONTRACT",
        "dispatch_disposition": "BLOCKED",
        "capability_disposition": "BLOCKED",
        "capability_gate": None,
        "adapter_handoff": None,
        "commit_bundle": None,
        "guards": {
            "credential_values_read": False,
            "credential_values_exposed": False,
            "network_dispatch_performed": False,
            "native_product_rewritten": False,
            "verbatim_cross_platform_reuse_allowed": False,
            "zero_paid_dependency": True,
        },
    }


def _force_outbox_registry(channel_registry: dict[str, Any], platform: str) -> dict[str, Any]:
    result = copy.deepcopy(channel_registry)
    entry = _find_channel_entry(result, platform)
    if entry is None:
        return result
    entry["direct_publication_enabled"] = False
    entry["publication_mode"] = "durable_outbox_only"
    entry["adapter"] = None
    entry["credentials"] = None
    return result


def bridge_runtime_handoff_with_capabilities(
    report: dict[str, Any],
    channel_registry: dict[str, Any],
    capability_registry: dict[str, Any],
    present_credential_references: Iterable[str] | None,
    outbox: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the canonical bridge with a truthful installed-adapter capability gate."""
    if not all(isinstance(value, dict) for value in (report, channel_registry, capability_registry)):
        raise TypeError("report, channel_registry and capability_registry must be mappings")
    platform = _platform(report.get("platform"))

    # Upstream holds/blocks remain owned by the existing canonical bridge. Capability
    # compatibility matters only when the runtime has a READY native product.
    if _clean(report.get("disposition")) != "READY":
        result = adapter_dispatch_bridge.bridge_runtime_handoff(
            copy.deepcopy(report), copy.deepcopy(channel_registry),
            present_credential_references, copy.deepcopy(outbox),
        )
        result["capability_disposition"] = "NOT_APPLICABLE_UPSTREAM_NOT_READY"
        result["capability_gate"] = {
            "schema_version": SCHEMA_VERSION,
            "applicable": False,
            "compatible": True,
            "decision": "UPSTREAM_NOT_READY",
            "gap_reasons": [],
        }
        return result

    contract_errors = _runtime_contract_errors(capability_registry, channel_registry, platform)
    if contract_errors:
        return _blocked(report, contract_errors)
    capability = _find_capability(capability_registry, platform)
    assert capability is not None
    assessment = assess_runtime_capability(report, capability)

    if assessment["compatible"]:
        result = adapter_dispatch_bridge.bridge_runtime_handoff(
            copy.deepcopy(report), copy.deepcopy(channel_registry),
            present_credential_references, copy.deepcopy(outbox),
        )
        result["capability_disposition"] = "DIRECT_READY" if result.get("dispatch_disposition") == "DIRECT_READY" else result.get("dispatch_disposition")
    else:
        forced = _force_outbox_registry(channel_registry, platform)
        result = adapter_dispatch_bridge.bridge_runtime_handoff(
            copy.deepcopy(report), forced, set(), copy.deepcopy(outbox),
        )
        result["capability_disposition"] = "OUTBOX_ONLY_CAPABILITY_GAP"
        result["capability_gap_reasons"] = copy.deepcopy(assessment["gap_reasons"])

    result["capability_gate"] = assessment
    guards = result.setdefault("guards", {}) if isinstance(result.get("guards"), dict) else {}
    guards["adapter_capability_checked"] = True
    guards["native_product_rewritten"] = False
    guards["fallback_format_invented"] = False
    guards["credential_values_read_by_capability_gate"] = False
    guards["zero_paid_dependency"] = True
    return result


def validate_capability_registry_path(capability_path: Path, channel_registry_path: Path, repo_root: Path) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    capability_file = (repo_root / capability_path).resolve() if not capability_path.is_absolute() else capability_path.resolve()
    registry_file = (repo_root / channel_registry_path).resolve() if not channel_registry_path.is_absolute() else channel_registry_path.resolve()
    for path in (capability_file, registry_file):
        if repo_root != path and repo_root not in path.parents:
            raise ValueError("capability and channel registry paths must stay inside repository root")
    capabilities = json.loads(capability_file.read_text(encoding="utf-8"))
    channel_registry = json.loads(registry_file.read_text(encoding="utf-8"))
    instance_root = PurePosixPath(channel_registry_path.as_posix()).parts[0]

    def load_channel(rel: str) -> dict[str, Any]:
        candidate = (repo_root / rel).resolve()
        if repo_root not in candidate.parents or not candidate.is_file():
            raise ValueError("channel config path is not a repository file")
        value = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("channel config must be an object")
        return value

    return validate_capability_registry(
        capabilities,
        channel_registry,
        load_channel=load_channel,
        instance_root=instance_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capabilities", type=Path)
    parser.add_argument("channel_registry", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate_capability_registry_path(args.capabilities, args.channel_registry, args.repo_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
