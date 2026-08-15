#!/usr/bin/env python3
"""Generic publishing-adapter contract and fail-closed dispatch planner for LOCAL NEWS OS.

The social core treats each channel as an independent publication. This module validates
instance channel registries without knowing platform credentials or making network calls.
It deliberately keeps secrets out of plans: runtime gating receives only the *names* of
credential references that are present, never their values.

Instance-specific adapters (Facebook, Instagram, TikTok, etc.) remain responsible for
native API semantics. This layer generalizes their contract, verifies routing/isolation,
and forces unverified channels into durable-outbox-only mode.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable

CONTRACT_VERSION = "1.0"
DIRECT_MODES = {
    "native_api",
    "native_api_fail_closed",
    "native_api_gated_by_site_consent_and_app_audit",
}
OUTBOX_ONLY_MODE = "durable_outbox_only"
REQUIRED_TRUE_POLICIES = {
    "verified_fact_kernel_required",
    "channel_native_copy_required",
    "cross_post_verbatim_forbidden",
    "idempotency_required",
    "deduplication_required",
    "correction_propagation_required",
    "fail_closed_on_missing_credentials",
    "fail_closed_on_missing_adapter",
}
REQUIRED_FALSE_POLICIES = {
    "paid_social_scheduler_required",
    "paid_llm_api_required",
}
REFERENCE_KEY_SUFFIXES = ("_secret", "_variable")
REFERENCE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
SECRET_VALUE_PREFIXES = ("eaa", "eyj", "ghp_", "github_pat_", "sk-")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _platform_key(value: Any) -> str:
    return _clean(value).lower().replace("-", "_")


def _within_instance(path: str, instance_root: str) -> bool:
    if not path or not instance_root:
        return False
    candidate = PurePosixPath(path)
    root = PurePosixPath(instance_root)
    if candidate.is_absolute() or ".." in candidate.parts:
        return False
    return candidate == root or root in candidate.parents


def credential_reference_names(entry: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return declared runtime reference names and validation errors, never secret values."""
    errors: list[str] = []
    credentials = entry.get("credentials")
    if credentials is None:
        return [], errors
    if not isinstance(credentials, dict):
        return [], ["INVALID_CREDENTIALS_CONTRACT"]

    refs: list[str] = []
    for key, value in sorted(credentials.items()):
        key_text = _clean(key).lower()
        value_text = _clean(value)
        if key_text.endswith(REFERENCE_KEY_SUFFIXES):
            if not value_text:
                errors.append(f"EMPTY_CREDENTIAL_REFERENCE:{key}")
                continue
            if not REFERENCE_RE.fullmatch(value_text):
                errors.append(f"CREDENTIAL_REFERENCE_NOT_NAME:{key}")
                continue
            refs.append(value_text)
            continue

        # Non-reference metadata may describe where an ID comes from, but it may not
        # smuggle a token/secret value into repository config.
        normalized = value_text.lower()
        if "token" in key_text or "secret" in key_text or "password" in key_text or "api_key" in key_text:
            errors.append(f"CREDENTIAL_VALUE_FIELD_FORBIDDEN:{key}")
        elif normalized.startswith(SECRET_VALUE_PREFIXES) or len(value_text) > 160:
            errors.append(f"SECRET_LIKE_CREDENTIAL_VALUE:{key}")
    return sorted(set(refs)), errors


def runtime_gate(entry: dict[str, Any], present_refs: set[str]) -> dict[str, Any]:
    """Decide dispatch eligibility using credential *names present*, not credential values."""
    channel_id = _clean(entry.get("channel_id"))
    if entry.get("direct_publication_enabled") is not True:
        return {
            "channel_id": channel_id,
            "decision": "OUTBOX_ONLY",
            "missing_references": [],
        }
    refs, errors = credential_reference_names(entry)
    if errors:
        return {
            "channel_id": channel_id,
            "decision": "BLOCKED_INVALID_CREDENTIAL_CONTRACT",
            "missing_references": [],
            "errors": errors,
        }
    missing = sorted(ref for ref in refs if ref not in present_refs)
    return {
        "channel_id": channel_id,
        "decision": "DIRECT_READY" if not missing else "BLOCKED_MISSING_CREDENTIALS",
        "missing_references": missing,
    }


def validate_registry(
    registry: dict[str, Any],
    *,
    load_channel: Callable[[str], dict[str, Any]],
    file_exists: Callable[[str], bool],
    instance_root: str,
) -> dict[str, Any]:
    """Validate one instance's adapter registry and build a deterministic dispatch plan."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(registry, dict):
        raise TypeError("registry must be a mapping")

    execution_owner = _clean(registry.get("execution_owner"))
    if not execution_owner:
        errors.append("MISSING_EXECUTION_OWNER")
    scheduler = _clean(registry.get("scheduler"))
    if scheduler != "github_actions":
        errors.append("SCHEDULER_MUST_BE_GITHUB_ACTIONS")
    state_owner = _clean(registry.get("state_owner"))
    if state_owner != "repository":
        errors.append("STATE_OWNER_MUST_BE_REPOSITORY")

    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    for key in sorted(REQUIRED_TRUE_POLICIES):
        if policy.get(key) is not True:
            errors.append(f"POLICY_MUST_BE_TRUE:{key}")
    for key in sorted(REQUIRED_FALSE_POLICIES):
        if policy.get(key) is not False:
            errors.append(f"POLICY_MUST_BE_FALSE:{key}")

    channels = registry.get("channels")
    if not isinstance(channels, list) or not channels:
        return {
            "contract_version": CONTRACT_VERSION,
            "status": "BLOCKED",
            "errors": sorted(set(errors + ["MISSING_CHANNELS"])),
            "warnings": warnings,
            "dispatch": [],
        }

    seen_registry_ids: set[str] = set()
    seen_config_ids: set[str] = set()
    state_owners: dict[str, str] = {}
    direct_ids: set[str] = set()
    dispatch: list[dict[str, Any]] = []

    for raw in channels:
        if not isinstance(raw, dict):
            errors.append("INVALID_CHANNEL_ENTRY")
            continue
        registry_id = _platform_key(raw.get("channel_id"))
        if not registry_id:
            errors.append("MISSING_REGISTRY_CHANNEL_ID")
            continue
        if registry_id in seen_registry_ids:
            errors.append(f"DUPLICATE_REGISTRY_CHANNEL:{registry_id}")
            continue
        seen_registry_ids.add(registry_id)

        direct = raw.get("direct_publication_enabled") is True
        status = _clean(raw.get("status")).lower()
        mode = _clean(raw.get("publication_mode")).lower()
        adapter = _clean(raw.get("adapter"))
        config_path = _clean(raw.get("config"))
        outbox_path = _clean(raw.get("outbox"))
        state_path = _clean(raw.get("state"))
        refs, credential_errors = credential_reference_names(raw)
        errors.extend(f"{registry_id}:{error}" for error in credential_errors)

        config: dict[str, Any] | None = None
        if config_path:
            if not _within_instance(config_path, instance_root):
                errors.append(f"{registry_id}:CONFIG_OUTSIDE_INSTANCE")
            elif not file_exists(config_path):
                errors.append(f"{registry_id}:MISSING_CHANNEL_CONFIG")
            else:
                try:
                    config = load_channel(config_path)
                except Exception as exc:
                    errors.append(f"{registry_id}:INVALID_CHANNEL_CONFIG:{type(exc).__name__}")
        elif direct:
            errors.append(f"{registry_id}:DIRECT_CHANNEL_MISSING_CONFIG")

        config_channel_id = ""
        instance_id = ""
        if config is not None:
            config_channel_id = _clean(config.get("channel_id"))
            instance_id = _clean(config.get("instance_id"))
            config_platform = _platform_key(config.get("platform"))
            if not config_channel_id:
                errors.append(f"{registry_id}:CONFIG_MISSING_CHANNEL_ID")
            elif config_channel_id in seen_config_ids:
                errors.append(f"{registry_id}:DUPLICATE_CONFIG_CHANNEL_ID")
            else:
                seen_config_ids.add(config_channel_id)
            if config_platform != registry_id:
                errors.append(f"{registry_id}:CONFIG_PLATFORM_MISMATCH")
            if not instance_id:
                errors.append(f"{registry_id}:CONFIG_MISSING_INSTANCE_ID")
            if config.get("zero_paid_dependency") is not True:
                errors.append(f"{registry_id}:ZERO_PAID_DEPENDENCY_REQUIRED")
            cfg_state = config.get("publication_state") if isinstance(config.get("publication_state"), dict) else {}
            cfg_outbox = _clean(cfg_state.get("outbox_path"))
            cfg_state_path = _clean(cfg_state.get("state_path"))
            if outbox_path and cfg_outbox and outbox_path != cfg_outbox:
                errors.append(f"{registry_id}:OUTBOX_PATH_MISMATCH")
            if state_path and cfg_state_path and state_path != cfg_state_path:
                errors.append(f"{registry_id}:STATE_PATH_MISMATCH")
            if direct and cfg_state.get("dedupe_by_id") is not True:
                errors.append(f"{registry_id}:DEDUPE_NOT_ENABLED")

        if state_path:
            if not _within_instance(state_path, instance_root):
                errors.append(f"{registry_id}:STATE_OUTSIDE_INSTANCE")
            previous = state_owners.get(state_path)
            if previous and previous != registry_id:
                errors.append(f"STATE_COLLISION:{previous}:{registry_id}")
            else:
                state_owners[state_path] = registry_id
        elif direct:
            errors.append(f"{registry_id}:DIRECT_CHANNEL_MISSING_STATE")

        if outbox_path and not _within_instance(outbox_path, instance_root):
            errors.append(f"{registry_id}:OUTBOX_OUTSIDE_INSTANCE")
        elif direct and not outbox_path:
            errors.append(f"{registry_id}:DIRECT_CHANNEL_MISSING_OUTBOX")

        if direct:
            direct_ids.add(registry_id)
            if status != "active":
                errors.append(f"{registry_id}:DIRECT_CHANNEL_NOT_ACTIVE")
            if mode not in DIRECT_MODES:
                errors.append(f"{registry_id}:UNAPPROVED_DIRECT_MODE")
            if not adapter:
                errors.append(f"{registry_id}:DIRECT_CHANNEL_MISSING_ADAPTER")
            elif not _within_instance(adapter, instance_root):
                errors.append(f"{registry_id}:ADAPTER_OUTSIDE_INSTANCE")
            elif not file_exists(adapter):
                errors.append(f"{registry_id}:ADAPTER_FILE_MISSING")
            if not refs:
                errors.append(f"{registry_id}:DIRECT_CHANNEL_MISSING_CREDENTIAL_REFS")
        else:
            if mode != OUTBOX_ONLY_MODE:
                errors.append(f"{registry_id}:DISABLED_CHANNEL_MUST_BE_OUTBOX_ONLY")
            if adapter:
                errors.append(f"{registry_id}:UNVERIFIED_CHANNEL_HAS_ADAPTER")
            if raw.get("credentials") is not None:
                errors.append(f"{registry_id}:UNVERIFIED_CHANNEL_HAS_CREDENTIALS")
            if not config_path:
                warnings.append(f"{registry_id}:OUTBOX_ONLY_CHANNEL_NOT_YET_CONFIGURED")

        dispatch.append(
            {
                "registry_channel_id": registry_id,
                "channel_id": config_channel_id or None,
                "instance_id": instance_id or None,
                "platform": registry_id,
                "publication_mode": mode,
                "dispatch_mode": "DIRECT_RUNTIME_GATED" if direct else "OUTBOX_ONLY",
                "adapter": adapter or None,
                "outbox": outbox_path or None,
                "state": state_path or None,
                "credential_references": refs,
                "credential_values_exposed": False,
            }
        )

    required_direct = {
        _platform_key(value)
        for value in registry.get("required_active_direct_channels", [])
        if _platform_key(value)
    }
    missing_required = sorted(required_direct - direct_ids)
    if missing_required:
        errors.append("REQUIRED_DIRECT_CHANNELS_MISSING:" + ",".join(missing_required))

    return {
        "contract_version": CONTRACT_VERSION,
        "status": "PASS" if not errors else "BLOCKED",
        "execution_owner": execution_owner or None,
        "scheduler": scheduler or None,
        "state_owner": state_owner or None,
        "required_active_direct_channels": sorted(required_direct),
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
        "dispatch": sorted(dispatch, key=lambda item: item["registry_channel_id"]),
    }


def validate_registry_path(registry_path: Path, repo_root: Path, instance_root: str) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    registry_file = (repo_root / registry_path).resolve() if not registry_path.is_absolute() else registry_path.resolve()
    if repo_root != registry_file and repo_root not in registry_file.parents:
        raise ValueError("registry path must be inside repository root")
    registry = json.loads(registry_file.read_text(encoding="utf-8"))

    def exists(rel: str) -> bool:
        candidate = (repo_root / rel).resolve()
        return repo_root == candidate or (repo_root in candidate.parents and candidate.is_file())

    def load(rel: str) -> dict[str, Any]:
        candidate = (repo_root / rel).resolve()
        if repo_root not in candidate.parents:
            raise ValueError("channel config outside repository root")
        value = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("channel config must be an object")
        return value

    return validate_registry(
        registry,
        load_channel=load,
        file_exists=exists,
        instance_root=instance_root,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--instance-root", required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    result = validate_registry_path(args.registry, args.repo_root, args.instance_root)
    payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
