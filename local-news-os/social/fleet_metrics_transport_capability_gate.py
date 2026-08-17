#!/usr/bin/env python3
"""Fleet capability gate before observed-metrics credential binding.

This is the non-network preflight between generic fleet discovery and explicit
per-instance credential binding. A channel may reach the secret matrix only when:
1. a native/free transport capability is explicitly registered;
2. that capability exactly matches an implemented transport profile;
3. CHANNEL_CONFIG declares the same observed-only metric source;
4. access attestation is present, inside the instance root, valid and ready;
5. fleet discovery itself did not hold the channel;
6. the separate credential-binding stage still grants the exact instance secrets.

No credential values are read or returned. Analytics never blocks publication.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any

import fleet_metrics_harvest_orchestrator as fleet
import metrics_transport_capability_registry as capabilities

SCHEMA_VERSION = "1.0"
GATE_ID = "local-news-os-fleet-metrics-transport-capability-gate"
DEFAULT_RUNTIME_REGISTRY = Path("local-news-os/social/social_runtime_registry.json")
DEFAULT_CAPABILITY_REGISTRY = Path("local-news-os/social/metrics_transport_capabilities.json")


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_rel(value: Any) -> str:
    text = _clean(value).replace("\\", "/")
    if not text:
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        return ""
    normalized = path.as_posix()
    return "" if normalized in {"", "."} else normalized


def _within(path: str, root: str) -> bool:
    if not path or not root:
        return False
    candidate = PurePosixPath(path)
    base = PurePosixPath(root)
    return candidate == base or base in candidate.parents


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def evaluate_capability_gate(
    repo_root: Path,
    runtime: dict[str, Any],
    fleet_result: dict[str, Any],
    capability_validation: dict[str, Any],
) -> dict[str, Any]:
    if not all(isinstance(item, dict) for item in (runtime, fleet_result, capability_validation)):
        raise TypeError("runtime, fleet_result and capability_validation must be mappings")

    structural_blocks: list[str] = []
    if capability_validation.get("status") != "PASS":
        structural_blocks.append("TRANSPORT_CAPABILITY_REGISTRY_INVALID")
    if fleet_result.get("publication_blocked") is True:
        structural_blocks.append("ANALYTICS_FLEET_ATTEMPTED_TO_BLOCK_PUBLICATION")
    fleet_guards = fleet_result.get("guards") if isinstance(fleet_result.get("guards"), dict) else {}
    if fleet_guards.get("zero_paid_dependency") is not True:
        structural_blocks.append("FLEET_ZERO_PAID_GUARD_MISSING")
    if fleet_guards.get("native_free_transport_only") is not True:
        structural_blocks.append("FLEET_NATIVE_FREE_GUARD_MISSING")
    if fleet_guards.get("credential_values_returned") is not False:
        structural_blocks.append("FLEET_CREDENTIAL_VALUE_GUARD_MISSING")

    instances_raw = runtime.get("instances") if isinstance(runtime.get("instances"), list) else []
    instances = {
        _clean(row.get("instance_id")).lower(): row
        for row in instances_raw
        if isinstance(row, dict) and _clean(row.get("instance_id"))
    }

    approved: list[dict[str, Any]] = []
    holds: list[dict[str, Any]] = []
    channels = fleet_result.get("channels") if isinstance(fleet_result.get("channels"), list) else []

    for row in channels:
        if not isinstance(row, dict) or row.get("eligible") is not True:
            continue
        local: list[str] = []
        instance_id = _clean(row.get("instance_id")).lower()
        channel_id = _clean(row.get("channel_id"))
        platform = _clean(row.get("platform")).lower()
        source = _clean(row.get("metric_source")).lower()
        credential_env_name = _clean(row.get("credential_env_name"))

        capability = capabilities.capability_for_platform(capability_validation, platform)
        if not capability:
            local.append("NO_EXPLICIT_IMPLEMENTED_TRANSPORT_CAPABILITY")
        else:
            if source != _clean(capability.get("metric_source")).lower():
                local.append("FLEET_METRIC_SOURCE_CAPABILITY_MISMATCH")
            if capability.get("zero_paid_dependency") is not True:
                local.append("CAPABILITY_ZERO_PAID_GUARD_MISSING")
            if capability.get("observed_only") is not True:
                local.append("CAPABILITY_OBSERVED_ONLY_GUARD_MISSING")

        status = _clean(row.get("status"))
        if status.startswith("HOLD_") or status in {"BLOCKED_AUTH", "RETRY_LATER"}:
            local.append("FLEET_CHANNEL_NOT_RUNTIME_READY:" + (status or "UNKNOWN"))

        instance = instances.get(instance_id)
        if not instance:
            local.append("CAPABILITY_GATE_INSTANCE_NOT_IN_RUNTIME")
            instance_root = ""
        else:
            instance_root = _safe_rel(instance.get("instance_root"))

        attestation_rel = _safe_rel(row.get("access_attestation_path"))
        if not attestation_rel:
            local.append("CAPABILITY_GATE_ACCESS_ATTESTATION_PATH_REQUIRED")
        elif not _within(attestation_rel, instance_root):
            local.append("CAPABILITY_GATE_ACCESS_ATTESTATION_OUTSIDE_INSTANCE")
        elif capability:
            try:
                attestation = _load_json(repo_root / attestation_rel)
                local.extend(capabilities.validate_access_attestation(capability, attestation))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                local.append(f"CAPABILITY_GATE_ACCESS_ATTESTATION_UNAVAILABLE:{type(exc).__name__}")

        if not credential_env_name:
            local.append("CAPABILITY_GATE_CREDENTIAL_ENV_NAME_REQUIRED")

        result_row = {
            "instance_id": instance_id or None,
            "channel_id": channel_id or None,
            "platform": platform or None,
            "metric_source": source or None,
            "transport_capability_id": capability.get("capability_id") if capability else None,
            "credential_env_name": credential_env_name or None,
            "access_attestation_path": attestation_rel or None,
            "hard_blocks": sorted(set(local)),
        }
        if local:
            holds.append(result_row)
        else:
            result_row["transport_implementation_verified"] = True
            result_row["verified_access_attestation"] = True
            approved.append(result_row)

    if structural_blocks:
        approved = []
        status = "CAPABILITY_GATE_HOLD"
    elif holds:
        status = "CAPABILITY_GATE_PARTIAL_HOLD"
    elif approved:
        status = "CAPABILITY_GATE_READY"
    else:
        status = "CAPABILITY_GATE_IDLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "gate_id": GATE_ID,
        "status": status,
        "hard_blocks": sorted(set(structural_blocks)),
        "channel_holds": holds,
        "approved_channels": sorted(
            approved,
            key=lambda row: (str(row.get("instance_id")), str(row.get("channel_id"))),
        ),
        "publication_blocked": False,
        "guards": {
            "explicit_transport_registration_required": True,
            "transport_implementation_match_required": True,
            "verified_access_attestation_required": True,
            "explicit_credential_binding_still_required": True,
            "implicit_transport_enablement_allowed": False,
            "credential_values_read": False,
            "credential_values_returned": False,
            "analytics_advisory_only": True,
            "publication_blocked_by_analytics": False,
            "native_free_transport_only": True,
            "zero_paid_dependency": True,
        },
    }


def run_gate(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY,
    *,
    now: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    runtime_rel = _safe_rel(runtime_registry_path.as_posix())
    capability_rel = _safe_rel(capability_registry_path.as_posix())
    if not runtime_rel or not capability_rel:
        raise ValueError("registry paths must be repository-relative")
    runtime = _load_json(root / runtime_rel)
    capability_registry = _load_json(root / capability_rel)
    capability_validation = capabilities.validate_registry(capability_registry)
    fleet_result = fleet.run_fleet(
        root,
        Path(runtime_rel),
        now=now,
        execute=False,
    )
    result = evaluate_capability_gate(root, runtime, fleet_result, capability_validation)
    result["capability_registry_status"] = capability_validation.get("status")
    result["fleet_status"] = fleet_result.get("status")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--runtime-registry", type=Path, default=DEFAULT_RUNTIME_REGISTRY)
    parser.add_argument("--capability-registry", type=Path, default=DEFAULT_CAPABILITY_REGISTRY)
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    result = run_gate(
        args.repo_root,
        args.runtime_registry,
        args.capability_registry,
        now=args.now,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] in {"CAPABILITY_GATE_HOLD", "CAPABILITY_GATE_PARTIAL_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
