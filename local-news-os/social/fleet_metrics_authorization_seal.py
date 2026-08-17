#!/usr/bin/env python3
"""TOCTOU-safe authorization seal for fleet observed-metrics credential execution.

The existing fleet capability gate and credential-binding engine establish *what*
may run. This boundary binds that approval to the later credential execution
handoff with a deterministic SHA-256 authorization fingerprint.

The seal intentionally covers only authorization material, never credential
values:
- the selected CIVORA instance namespace and access-attestation mapping;
- the exact capability-bound credential grants;
- the registered native/free transport capability contract;
- the channel's credential reference name and observed-only metrics declaration;
- a safe, explicit view of the verified access attestation.

Operational execution must present the fingerprint emitted by the planning job.
The authorization material is rebuilt again immediately before the downstream
orchestrator is allowed to make a provider call. Any drift fails closed for
analytics only; editorial publication remains unblocked.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import fleet_metrics_credential_binding as binding
import fleet_metrics_transport_capability_gate as capability_gate
import multi_instance_isolation

SCHEMA_VERSION = "1.0"
SEAL_ID = "local-news-os-fleet-metrics-authorization-seal"
DEFAULT_RUNTIME_REGISTRY = Path("local-news-os/social/social_runtime_registry.json")
DEFAULT_BINDING_REGISTRY = Path("local-news-os/social/metrics_credential_bindings.json")
DEFAULT_CAPABILITY_REGISTRY = Path("local-news-os/social/metrics_transport_capabilities.json")

FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
SECRETISH_FRAGMENTS = (
    "secret_value",
    "token_value",
    "password",
    "api_key",
    "credential_value",
    "access_token_value",
)
SAFE_CAPABILITY_FIELDS = (
    "capability_id",
    "platform",
    "metric_source",
    "transport_module",
    "transport_profile",
    "network_boundary",
    "credential_ref_kind",
    "access_ready_key",
    "metric_candidates",
    "requires_remote_publication_proof",
    "observed_only",
    "zero_paid_dependency",
)
SAFE_ATTESTATION_FIELDS = (
    "schema_version",
    "execution_owner",
    "token_source",
    "status",
    "secret_material_persisted",
    "verified_metrics_access",
    "page_id",
    "page_name",
    "instagram_account_id",
)

OrchestrateCall = Callable[..., dict[str, Any]]
RecheckCall = Callable[[], str | None]


class AuthorizationChanged(RuntimeError):
    """Raised before network execution when sealed authorization material drifted."""


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


def _canonical_fingerprint(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _secretish_keys(value: Any, prefix: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = _clean(raw_key)
            lowered = key.lower()
            current = f"{prefix}.{key}" if prefix else key
            if any(fragment in lowered for fragment in SECRETISH_FRAGMENTS):
                found.append(current)
                continue
            found.extend(_secretish_keys(child, current))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_secretish_keys(child, f"{prefix}[{index}]"))
    return sorted(set(found))


def _instance_map(runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = runtime.get("instances") if isinstance(runtime.get("instances"), list) else []
    return {
        _clean(row.get("instance_id")).lower(): row
        for row in rows
        if isinstance(row, dict) and _clean(row.get("instance_id"))
    }


def _binding_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = registry.get("bindings") if isinstance(registry.get("bindings"), list) else []
    return {
        _clean(row.get("binding_id")).lower(): row
        for row in rows
        if isinstance(row, dict) and _clean(row.get("binding_id"))
    }


def _capability_map(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = registry.get("capabilities") if isinstance(registry.get("capabilities"), list) else []
    return {
        _clean(row.get("capability_id")).lower(): row
        for row in rows
        if isinstance(row, dict) and _clean(row.get("capability_id"))
    }


def _normalized_grants(raw: dict[str, Any]) -> list[dict[str, str]]:
    grants = raw.get("capability_grants") if isinstance(raw.get("capability_grants"), list) else []
    result: list[dict[str, str]] = []
    for item in grants:
        if not isinstance(item, dict):
            continue
        result.append({
            "transport_capability_id": _clean(item.get("transport_capability_id")).lower(),
            "metric_source": _clean(item.get("metric_source")).lower(),
            "credential_env_name": _clean(item.get("credential_env_name")),
        })
    return sorted(
        result,
        key=lambda row: (
            row["transport_capability_id"],
            row["metric_source"],
            row["credential_env_name"],
        ),
    )


def _capability_view(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(raw.get(key))
        for key in SAFE_CAPABILITY_FIELDS
    }


def _attestation_view(capability: dict[str, Any], attestation: dict[str, Any]) -> dict[str, Any]:
    view = {key: copy.deepcopy(attestation.get(key)) for key in SAFE_ATTESTATION_FIELDS if key in attestation}
    ready_key = _clean(capability.get("access_ready_key"))
    if ready_key:
        view["access_ready_key"] = ready_key
        view["access_ready_value"] = attestation.get(ready_key)
    return view


def _channel_authorization_view(channel: dict[str, Any]) -> dict[str, Any]:
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    sources = metrics.get("sources") if isinstance(metrics.get("sources"), list) else []
    return {
        "instance_id": _clean(channel.get("instance_id")).lower(),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "credentials_ref": _clean(channel.get("credentials_ref")),
        "metrics": {
            "observed_only": metrics.get("observed_only") is True,
            "sources": sorted(_clean(item).lower() for item in sources if _clean(item)),
        },
        "zero_paid_dependency": channel.get("zero_paid_dependency") is True,
    }


def _channel_for_approval(
    repo_root: Path,
    instance: dict[str, Any],
    approval: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    blocks: list[str] = []
    instance_root = _safe_rel(instance.get("instance_root"))
    registry_rel = _safe_rel(instance.get("channel_registry"))
    if not instance_root or not registry_rel or not _within(registry_rel, instance_root):
        return None, ["AUTHORIZATION_CHANNEL_REGISTRY_PATH_INVALID"]
    try:
        registry = _load_json(repo_root / registry_rel)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, [f"AUTHORIZATION_CHANNEL_REGISTRY_UNAVAILABLE:{type(exc).__name__}"]

    wanted_channel = _clean(approval.get("channel_id"))
    wanted_platform = _clean(approval.get("platform")).lower()
    matches: list[dict[str, Any]] = []
    rows = registry.get("channels") if isinstance(registry.get("channels"), list) else []
    for row in rows:
        if not isinstance(row, dict):
            continue
        config_rel = _safe_rel(row.get("config"))
        if not config_rel or not _within(config_rel, instance_root):
            continue
        try:
            channel = _load_json(repo_root / config_rel)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if (
            _clean(channel.get("channel_id")) == wanted_channel
            and _clean(channel.get("platform")).lower() == wanted_platform
        ):
            matches.append(channel)
    if len(matches) != 1:
        blocks.append("AUTHORIZATION_CHANNEL_CONFIG_CARDINALITY_MISMATCH")
        return None, blocks
    return matches[0], blocks


def _authorization_material(
    repo_root: Path,
    instance: dict[str, Any],
    binding_row: dict[str, Any],
    approved_rows: list[dict[str, Any]],
    capability_rows: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    blocks: list[str] = []
    instance_id = _clean(instance.get("instance_id")).lower()
    instance_root = _safe_rel(instance.get("instance_root"))
    metrics_harvest = instance.get("metrics_harvest") if isinstance(instance.get("metrics_harvest"), dict) else {}
    attestation_map = metrics_harvest.get("access_attestations") if isinstance(metrics_harvest.get("access_attestations"), dict) else {}

    channel_material: list[dict[str, Any]] = []
    for approval in sorted(
        approved_rows,
        key=lambda row: (_clean(row.get("channel_id")), _clean(row.get("transport_capability_id"))),
    ):
        capability_id = _clean(approval.get("transport_capability_id")).lower()
        capability = capability_rows.get(capability_id)
        if not capability:
            blocks.append("AUTHORIZATION_CAPABILITY_NOT_IN_REGISTRY:" + (capability_id or "MISSING"))
            continue
        capability_secretish = _secretish_keys(capability)
        if capability_secretish:
            blocks.append("AUTHORIZATION_CAPABILITY_SECRETISH_FIELDS_FORBIDDEN")
            continue

        channel, channel_blocks = _channel_for_approval(repo_root, instance, approval)
        blocks.extend(channel_blocks)
        if not channel:
            continue
        channel_view = _channel_authorization_view(channel)
        if channel_view["instance_id"] != instance_id:
            blocks.append("AUTHORIZATION_CHANNEL_INSTANCE_MISMATCH")
            continue
        if channel_view["credentials_ref"] == "":
            blocks.append("AUTHORIZATION_CHANNEL_CREDENTIAL_REFERENCE_REQUIRED")
            continue

        source = _clean(approval.get("metric_source")).lower()
        attestation_rel = _safe_rel(approval.get("access_attestation_path"))
        declared_attestation = _safe_rel(attestation_map.get(source))
        if not attestation_rel or not declared_attestation or attestation_rel != declared_attestation:
            blocks.append("AUTHORIZATION_ACCESS_ATTESTATION_MAPPING_MISMATCH")
            continue
        if not _within(attestation_rel, instance_root):
            blocks.append("AUTHORIZATION_ACCESS_ATTESTATION_OUTSIDE_INSTANCE")
            continue
        try:
            attestation = _load_json(repo_root / attestation_rel)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blocks.append(f"AUTHORIZATION_ACCESS_ATTESTATION_UNAVAILABLE:{type(exc).__name__}")
            continue
        secretish = _secretish_keys(attestation)
        if secretish:
            blocks.append("AUTHORIZATION_ACCESS_ATTESTATION_SECRETISH_FIELDS_FORBIDDEN")
            continue

        channel_material.append({
            "instance_id": instance_id,
            "channel_id": _clean(approval.get("channel_id")),
            "platform": _clean(approval.get("platform")).lower(),
            "metric_source": source,
            "transport_capability_id": capability_id,
            "credential_env_name": _clean(approval.get("credential_env_name")),
            "access_attestation_path": attestation_rel,
            "capability": _capability_view(capability),
            "channel_authorization": channel_view,
            "access_attestation": _attestation_view(capability, attestation),
        })

    if blocks:
        return None, sorted(set(blocks))
    if not channel_material:
        return None, ["AUTHORIZATION_CHANNEL_MATERIAL_REQUIRED"]

    relevant_sources = sorted({_clean(row.get("metric_source")).lower() for row in approved_rows if _clean(row.get("metric_source"))})
    scoped_attestations = {
        source: _safe_rel(attestation_map.get(source))
        for source in relevant_sources
    }
    material = {
        "schema_version": SCHEMA_VERSION,
        "seal_id": SEAL_ID,
        "binding": {
            "binding_id": _clean(binding_row.get("binding_id")).lower(),
            "instance_id": _clean(binding_row.get("instance_id")).lower(),
            "credential_namespace": _clean(binding_row.get("credential_namespace")),
            "capability_grants": _normalized_grants(binding_row),
        },
        "instance": {
            "instance_id": instance_id,
            "instance_root": instance_root,
            "channel_registry": _safe_rel(instance.get("channel_registry")),
            "credential_namespace": _clean(instance.get("credential_namespace")),
            "metrics_access_attestations": scoped_attestations,
        },
        "channels": channel_material,
    }
    return material, []


def seal_plan(
    repo_root: Path,
    plan: dict[str, Any],
    runtime: dict[str, Any],
    binding_registry: dict[str, Any],
    capability_result: dict[str, Any],
    capability_registry: dict[str, Any],
) -> dict[str, Any]:
    """Attach deterministic authorization fingerprints to a validated binding plan."""
    if not all(isinstance(item, dict) for item in (plan, runtime, binding_registry, capability_result, capability_registry)):
        raise TypeError("authorization seal inputs must be mappings")

    result = copy.deepcopy(plan)
    guards = result.get("guards") if isinstance(result.get("guards"), dict) else {}
    guards.update({
        "authorization_fingerprint_required_for_execution": True,
        "authorization_recheck_immediately_before_network": True,
        "authorization_material_secret_values_included": False,
        "authorization_material_cross_instance_sharing_allowed": False,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    })
    result["guards"] = guards
    result["authorization_seal_id"] = SEAL_ID

    if result.get("status") == "CREDENTIAL_BINDINGS_HOLD":
        result["authorization_seal_status"] = "AUTHORIZATION_SEAL_NOT_ISSUED"
        return result

    instances = _instance_map(runtime)
    bindings = _binding_map(binding_registry)
    capabilities = _capability_map(capability_registry)
    approved = capability_result.get("approved_channels") if isinstance(capability_result.get("approved_channels"), list) else []
    approved_by_instance: dict[str, list[dict[str, Any]]] = {}
    for row in approved:
        if isinstance(row, dict):
            approved_by_instance.setdefault(_clean(row.get("instance_id")).lower(), []).append(row)

    authorizations = result.get("capability_authorizations") if isinstance(result.get("capability_authorizations"), list) else []
    matrix = result.get("workflow_matrix") if isinstance(result.get("workflow_matrix"), list) else []
    fingerprints: dict[str, str] = {}
    blocks: list[str] = []

    for authorization in authorizations:
        if not isinstance(authorization, dict):
            blocks.append("AUTHORIZATION_SIDECAR_RECORD_INVALID")
            continue
        binding_id = _clean(authorization.get("binding_id")).lower()
        instance_id = _clean(authorization.get("instance_id")).lower()
        instance = instances.get(instance_id)
        binding_row = bindings.get(binding_id)
        if not instance or not binding_row:
            blocks.append("AUTHORIZATION_BINDING_OR_INSTANCE_NOT_FOUND:" + (binding_id or "MISSING"))
            continue
        material, local_blocks = _authorization_material(
            repo_root,
            instance,
            binding_row,
            approved_by_instance.get(instance_id, []),
            capabilities,
        )
        if local_blocks or material is None:
            blocks.extend(local_blocks or ["AUTHORIZATION_MATERIAL_UNAVAILABLE"])
            continue
        fingerprint = _canonical_fingerprint(material)
        fingerprints[binding_id] = fingerprint
        authorization["authorization_fingerprint"] = fingerprint
        authorization["authorization_material_version"] = SCHEMA_VERSION

    for row in matrix:
        if not isinstance(row, dict):
            blocks.append("AUTHORIZATION_WORKFLOW_MATRIX_RECORD_INVALID")
            continue
        binding_id = _clean(row.get("binding_id")).lower()
        fingerprint = fingerprints.get(binding_id)
        if not fingerprint:
            blocks.append("AUTHORIZATION_FINGERPRINT_MISSING_FOR_MATRIX:" + (binding_id or "MISSING"))
            continue
        row["authorization_fingerprint"] = fingerprint
        row["authorization_material_version"] = SCHEMA_VERSION

    if blocks:
        result["hard_blocks"] = sorted(set(list(result.get("hard_blocks", [])) + blocks))
        result["workflow_matrix"] = []
        result["capability_authorizations"] = []
        result["status"] = "CREDENTIAL_BINDINGS_HOLD"
        result["authorization_seal_status"] = "AUTHORIZATION_SEAL_HOLD"
    else:
        result["authorization_seal_status"] = "AUTHORIZATION_SEAL_READY" if fingerprints else "AUTHORIZATION_SEAL_IDLE"
    result["publication_blocked"] = False
    return result


def build_sealed_plan(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY,
    *,
    now: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    root = repo_root.resolve()
    plan, runtime, binding_registry, _fleet_result = binding.run_plan(
        root,
        runtime_registry_path,
        binding_registry_path,
        capability_registry_path,
        now=now,
    )
    capability_result = capability_gate.run_gate(
        root,
        runtime_registry_path,
        capability_registry_path,
        now=now,
    )
    capability_registry = _load_json(root / capability_registry_path)
    sealed = seal_plan(root, plan, runtime, binding_registry, capability_result, capability_registry)
    return sealed, runtime


def _fingerprint_for_binding(plan: dict[str, Any], binding_id: str) -> str | None:
    wanted = _clean(binding_id).lower()
    rows = plan.get("workflow_matrix") if isinstance(plan.get("workflow_matrix"), list) else []
    matches = [row for row in rows if isinstance(row, dict) and _clean(row.get("binding_id")).lower() == wanted]
    if len(matches) != 1:
        return None
    value = _clean(matches[0].get("authorization_fingerprint"))
    return value if FINGERPRINT_RE.fullmatch(value) else None


def _hold(binding_id: str, reason: str, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    guards = plan.get("guards", {}) if isinstance(plan, dict) and isinstance(plan.get("guards"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "authorization_seal_id": SEAL_ID,
        "status": "HOLD_CREDENTIAL_AUTHORIZATION",
        "hard_blocks": [reason],
        "publication_blocked": False,
        "binding_id": _clean(binding_id).lower() or None,
        "instance_id": None,
        "authorization_fingerprint": None,
        "durable_paths": [],
        "required_credential_env_names": [],
        "guards": guards,
    }


def execute_sealed_instance(
    repo_root: Path,
    runtime: dict[str, Any],
    isolation_result: dict[str, Any],
    sealed_plan: dict[str, Any],
    binding_id: str,
    *,
    expected_authorization_fingerprint: str | None,
    now: str,
    execute: bool,
    recheck_fingerprint_call: RecheckCall | None = None,
    orchestrate_call: OrchestrateCall = binding.fleet.orchestrate_fleet,
    windows_hours: tuple[int, ...] = binding.fleet.operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = binding.fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
) -> dict[str, Any]:
    """Execute one binding only when the planned authorization seal is still current."""
    current = _fingerprint_for_binding(sealed_plan, binding_id)
    expected = _clean(expected_authorization_fingerprint)
    if not current:
        return _hold(binding_id, "CURRENT_AUTHORIZATION_FINGERPRINT_UNAVAILABLE", sealed_plan)
    if not expected or not FINGERPRINT_RE.fullmatch(expected):
        return _hold(binding_id, "EXPECTED_AUTHORIZATION_FINGERPRINT_REQUIRED", sealed_plan)
    if not hmac.compare_digest(current, expected):
        return _hold(binding_id, "AUTHORIZATION_FINGERPRINT_CHANGED_SINCE_PLAN", sealed_plan)
    if execute and recheck_fingerprint_call is None:
        return _hold(binding_id, "PRE_NETWORK_AUTHORIZATION_RECHECK_REQUIRED", sealed_plan)

    def guarded_orchestrate(*args: Any, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("execute") is True:
            latest = _clean(recheck_fingerprint_call() if recheck_fingerprint_call else None)
            if not latest or not FINGERPRINT_RE.fullmatch(latest):
                raise AuthorizationChanged("PRE_NETWORK_AUTHORIZATION_FINGERPRINT_UNAVAILABLE")
            if not hmac.compare_digest(latest, expected):
                raise AuthorizationChanged("AUTHORIZATION_CHANGED_BEFORE_NETWORK")
        return orchestrate_call(*args, **kwargs)

    try:
        result = binding.execute_bound_instance(
            repo_root,
            runtime,
            isolation_result,
            sealed_plan,
            binding_id,
            now=now,
            execute=execute,
            windows_hours=windows_hours,
            max_publications=max_publications,
            orchestrate_call=guarded_orchestrate,
        )
    except AuthorizationChanged as exc:
        return _hold(binding_id, str(exc), sealed_plan)

    result = dict(result)
    result["authorization_seal_id"] = SEAL_ID
    result["authorization_fingerprint"] = current
    result["authorization_fingerprint_verified"] = True
    result["pre_network_authorization_recheck"] = bool(execute)
    result["publication_blocked"] = False
    return result


def run_binding(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY,
    *,
    binding_id: str,
    expected_authorization_fingerprint: str,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = binding.fleet.operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = binding.fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
) -> dict[str, Any]:
    root = repo_root.resolve()
    sealed_plan, runtime = build_sealed_plan(
        root,
        runtime_registry_path,
        binding_registry_path,
        capability_registry_path,
        now=now,
    )
    isolation_result = multi_instance_isolation.validate_runtime_path(runtime_registry_path, root)

    def recheck() -> str | None:
        latest_plan, _latest_runtime = build_sealed_plan(
            root,
            runtime_registry_path,
            binding_registry_path,
            capability_registry_path,
            now=now,
        )
        return _fingerprint_for_binding(latest_plan, binding_id)

    return execute_sealed_instance(
        root,
        runtime,
        isolation_result,
        sealed_plan,
        binding_id,
        expected_authorization_fingerprint=expected_authorization_fingerprint,
        now=now,
        execute=execute,
        recheck_fingerprint_call=recheck if execute else None,
        windows_hours=windows_hours,
        max_publications=max_publications,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--runtime-registry", type=Path, default=DEFAULT_RUNTIME_REGISTRY)
    parser.add_argument("--binding-registry", type=Path, default=DEFAULT_BINDING_REGISTRY)
    parser.add_argument("--capability-registry", type=Path, default=DEFAULT_CAPABILITY_REGISTRY)
    parser.add_argument("--binding-id")
    parser.add_argument("--expected-authorization-fingerprint")
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=binding.fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    if args.binding_id:
        windows = tuple(int(item.strip()) for item in args.windows_hours.split(",") if item.strip())
        result = run_binding(
            args.repo_root,
            args.runtime_registry,
            args.binding_registry,
            args.capability_registry,
            binding_id=args.binding_id,
            expected_authorization_fingerprint=_clean(args.expected_authorization_fingerprint),
            now=args.now,
            execute=args.execute,
            windows_hours=windows,
            max_publications=args.max_publications,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if _clean(result.get("status")).startswith("HOLD_") else 0

    plan, _runtime = build_sealed_plan(
        args.repo_root,
        args.runtime_registry,
        args.binding_registry,
        args.capability_registry,
        now=args.now,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if plan.get("status") == "CREDENTIAL_BINDINGS_HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
