#!/usr/bin/env python3
"""Explicit per-instance credential binding for fleet observed-metrics harvest.

Fleet discovery is intentionally generic, while secret injection must remain an
explicit least-privilege grant. This boundary validates a checked-in registry
that maps each CIVORA instance credential *name* to the exact verified
native/free transport capability and metric source it may serve.

Important boundaries:
- no secret values are read, returned, fingerprinted, logged, or persisted here;
- a future instance is never granted credentials merely because fleet discovery
  finds it;
- one credential env name cannot belong to two instances;
- every credential grant is bound to an approved transport_capability_id + source;
- standalone CLI planning/execution re-runs the transport capability/access gate;
- a binding cannot grant credentials, sources, or capabilities beyond that gate;
- unsupported or unbound instances are skipped for analytics without blocking
  editorial publication;
- execution is scoped to exactly one validated instance binding per process;
- zero-paid dependency and observed-only analytics remain mandatory.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Callable

import fleet_metrics_harvest_orchestrator as fleet
import fleet_metrics_transport_capability_gate as capability_gate
import multi_instance_isolation

SCHEMA_VERSION = "1.0"
BINDING_ID = "local-news-os-fleet-metrics-credential-binding"
DEFAULT_RUNTIME_REGISTRY = Path("local-news-os/social/social_runtime_registry.json")
DEFAULT_BINDING_REGISTRY = Path("local-news-os/social/metrics_credential_bindings.json")
DEFAULT_CAPABILITY_REGISTRY = Path("local-news-os/social/metrics_transport_capabilities.json")

BINDING_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,95}$")
CAPABILITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")

TOP_LEVEL_FIELDS = {"schema_version", "product", "policy", "bindings"}
POLICY_FIELDS = {
    "explicit_per_instance_grant_required",
    "transport_capability_binding_required",
    "cross_instance_secret_sharing_forbidden",
    "secret_values_in_registry_forbidden",
    "dynamic_secret_enumeration_forbidden",
    "analytics_advisory_only",
    "zero_paid_dependency",
}
BINDING_FIELDS = {
    "binding_id",
    "instance_id",
    "credential_namespace",
    "capability_grants",
}
GRANT_FIELDS = {
    "transport_capability_id",
    "metric_source",
    "credential_env_name",
}
REQUIRED_TRUE_POLICIES = POLICY_FIELDS

OrchestrateCall = Callable[..., dict[str, Any]]
GrantTuple = tuple[str, str, str]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _instance_map(runtime: dict[str, Any]) -> dict[str, dict[str, Any]]:
    instances = runtime.get("instances") if isinstance(runtime.get("instances"), list) else []
    rows: dict[str, dict[str, Any]] = {}
    for item in instances:
        if not isinstance(item, dict):
            continue
        instance_id = _clean(item.get("instance_id")).lower()
        if instance_id and instance_id not in rows:
            rows[instance_id] = item
    return rows


def _fleet_eligible_keys(fleet_result: dict[str, Any]) -> set[tuple[str, str, str, str, str]]:
    keys: set[tuple[str, str, str, str, str]] = set()
    channels = fleet_result.get("channels") if isinstance(fleet_result.get("channels"), list) else []
    for row in channels:
        if not isinstance(row, dict) or row.get("eligible") is not True:
            continue
        key = (
            _clean(row.get("instance_id")).lower(),
            _clean(row.get("channel_id")),
            _clean(row.get("platform")).lower(),
            _clean(row.get("metric_source")).lower(),
            _clean(row.get("credential_env_name")),
        )
        if all(key):
            keys.add(key)
    return keys


def _capability_requirements(
    capability_result: dict[str, Any] | None,
    fleet_result: dict[str, Any],
) -> tuple[dict[str, dict[str, set[Any]]], list[str]]:
    required: dict[str, dict[str, set[Any]]] = {}
    blocks: list[str] = []
    if not isinstance(capability_result, dict):
        return required, ["CAPABILITY_GATE_RESULT_REQUIRED"]

    status = _clean(capability_result.get("status"))
    if status == "CAPABILITY_GATE_HOLD":
        blocks.append("CAPABILITY_GATE_STRUCTURAL_HOLD")
    elif status not in {"CAPABILITY_GATE_READY", "CAPABILITY_GATE_PARTIAL_HOLD", "CAPABILITY_GATE_IDLE"}:
        blocks.append("CAPABILITY_GATE_STATUS_INVALID:" + (status or "MISSING"))
    if capability_result.get("publication_blocked") is not False:
        blocks.append("CAPABILITY_GATE_ATTEMPTED_TO_BLOCK_PUBLICATION")

    guards = capability_result.get("guards") if isinstance(capability_result.get("guards"), dict) else {}
    required_guards = {
        "explicit_transport_registration_required": True,
        "transport_implementation_match_required": True,
        "verified_access_attestation_required": True,
        "explicit_credential_binding_still_required": True,
        "credential_values_read": False,
        "credential_values_returned": False,
        "native_free_transport_only": True,
        "zero_paid_dependency": True,
    }
    for key, expected in required_guards.items():
        if guards.get(key) is not expected:
            blocks.append(f"CAPABILITY_GATE_GUARD_MISMATCH:{key}")

    fleet_keys = _fleet_eligible_keys(fleet_result)
    approved = capability_result.get("approved_channels") if isinstance(capability_result.get("approved_channels"), list) else []
    for row in approved:
        if not isinstance(row, dict):
            blocks.append("CAPABILITY_GATE_APPROVED_CHANNEL_INVALID")
            continue
        instance_id = _clean(row.get("instance_id")).lower()
        channel_id = _clean(row.get("channel_id"))
        platform = _clean(row.get("platform")).lower()
        source = _clean(row.get("metric_source")).lower()
        capability_id = _clean(row.get("transport_capability_id")).lower()
        credential = _clean(row.get("credential_env_name"))
        fleet_key = (instance_id, channel_id, platform, source, credential)
        if not all(fleet_key) or not CAPABILITY_ID_RE.fullmatch(capability_id):
            blocks.append("CAPABILITY_GATE_APPROVED_CHANNEL_INCOMPLETE")
            continue
        if fleet_key not in fleet_keys:
            blocks.append("CAPABILITY_GATE_APPROVAL_NOT_IN_FLEET")
            continue
        if row.get("transport_implementation_verified") is not True:
            blocks.append("CAPABILITY_GATE_IMPLEMENTATION_PROOF_MISSING")
            continue
        if row.get("verified_access_attestation") is not True:
            blocks.append("CAPABILITY_GATE_ACCESS_PROOF_MISSING")
            continue
        row_blocks = row.get("hard_blocks") if isinstance(row.get("hard_blocks"), list) else []
        if row_blocks:
            blocks.append("CAPABILITY_GATE_APPROVED_CHANNEL_HAS_BLOCKS")
            continue

        bucket = required.setdefault(
            instance_id,
            {"credentials": set(), "sources": set(), "capability_ids": set(), "grants": set()},
        )
        grant: GrantTuple = (capability_id, source, credential)
        bucket["credentials"].add(credential)
        bucket["sources"].add(source)
        bucket["capability_ids"].add(capability_id)
        bucket["grants"].add(grant)

    return required, sorted(set(blocks))


def _policy_blocks(registry: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    unknown_top = sorted(set(registry) - TOP_LEVEL_FIELDS)
    if unknown_top:
        blocks.append("UNKNOWN_BINDING_REGISTRY_FIELDS:" + ",".join(unknown_top))
    if _clean(registry.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("BINDING_REGISTRY_SCHEMA_VERSION_MISMATCH")
    policy = registry.get("policy") if isinstance(registry.get("policy"), dict) else {}
    unknown_policy = sorted(set(policy) - POLICY_FIELDS)
    if unknown_policy:
        blocks.append("UNKNOWN_BINDING_POLICY_FIELDS:" + ",".join(unknown_policy))
    for key in sorted(REQUIRED_TRUE_POLICIES):
        if policy.get(key) is not True:
            blocks.append(f"BINDING_POLICY_REQUIRED:{key}")
    return blocks


def _grant_label(grant: GrantTuple) -> str:
    return "|".join(grant)


def plan_credential_bindings(
    runtime: dict[str, Any],
    binding_registry: dict[str, Any],
    fleet_result: dict[str, Any],
    capability_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a secret-free matrix only from capability/access-approved channels."""
    if not all(isinstance(value, dict) for value in (runtime, binding_registry, fleet_result)):
        raise TypeError("runtime, binding_registry and fleet_result must be mappings")

    blocks = _policy_blocks(binding_registry)
    if fleet_result.get("publication_blocked") is True:
        blocks.append("ANALYTICS_FLEET_RESULT_ATTEMPTED_TO_BLOCK_PUBLICATION")
    fleet_guards = fleet_result.get("guards") if isinstance(fleet_result.get("guards"), dict) else {}
    if fleet_guards.get("zero_paid_dependency") is not True:
        blocks.append("FLEET_ZERO_PAID_GUARD_MISSING")
    if fleet_guards.get("native_free_transport_only") is not True:
        blocks.append("FLEET_NATIVE_FREE_GUARD_MISSING")
    if fleet_guards.get("credential_values_returned") is not False:
        blocks.append("FLEET_CREDENTIAL_VALUE_GUARD_MISSING")

    instances = _instance_map(runtime)
    requirements, capability_blocks = _capability_requirements(capability_result, fleet_result)
    blocks.extend(capability_blocks)

    raw_bindings = binding_registry.get("bindings")
    if not isinstance(raw_bindings, list):
        raw_bindings = []
        blocks.append("BINDINGS_LIST_REQUIRED")

    seen_binding_ids: set[str] = set()
    seen_instances: set[str] = set()
    credential_owner: dict[str, str] = {}
    parsed: dict[str, dict[str, Any]] = {}
    binding_holds: list[dict[str, Any]] = []

    for raw in raw_bindings:
        local: list[str] = []
        if not isinstance(raw, dict):
            binding_holds.append({"binding_id": None, "instance_id": None, "hard_blocks": ["INVALID_BINDING_RECORD"]})
            continue

        unknown = sorted(set(raw) - BINDING_FIELDS)
        if unknown:
            local.append("UNKNOWN_BINDING_FIELDS:" + ",".join(unknown))

        binding_id = _clean(raw.get("binding_id")).lower()
        instance_id = _clean(raw.get("instance_id")).lower()
        namespace = _clean(raw.get("credential_namespace"))
        grants_raw = raw.get("capability_grants")

        if not BINDING_KEY_RE.fullmatch(binding_id):
            local.append("INVALID_BINDING_ID")
        elif binding_id in seen_binding_ids:
            local.append("DUPLICATE_BINDING_ID")
        seen_binding_ids.add(binding_id)

        if not INSTANCE_ID_RE.fullmatch(instance_id):
            local.append("INVALID_BINDING_INSTANCE_ID")
        elif instance_id in seen_instances:
            local.append("DUPLICATE_INSTANCE_BINDING")
        seen_instances.add(instance_id)

        instance = instances.get(instance_id)
        if not instance:
            local.append("BINDING_INSTANCE_NOT_IN_RUNTIME")
            expected_namespace = ""
        else:
            expected_namespace = _clean(instance.get("credential_namespace"))
            if not expected_namespace:
                local.append("RUNTIME_CREDENTIAL_NAMESPACE_REQUIRED")
            if namespace != expected_namespace:
                local.append("BINDING_CREDENTIAL_NAMESPACE_MISMATCH")

        grants: list[dict[str, str]] = []
        grant_tuples: list[GrantTuple] = []
        if not isinstance(grants_raw, list) or not grants_raw:
            local.append("BINDING_CAPABILITY_GRANTS_REQUIRED")
        else:
            for item in grants_raw:
                if not isinstance(item, dict):
                    local.append("INVALID_CAPABILITY_GRANT_RECORD")
                    continue
                grant_unknown = sorted(set(item) - GRANT_FIELDS)
                if grant_unknown:
                    local.append("UNKNOWN_CAPABILITY_GRANT_FIELDS:" + ",".join(grant_unknown))
                capability_id = _clean(item.get("transport_capability_id")).lower()
                source = _clean(item.get("metric_source")).lower()
                credential = _clean(item.get("credential_env_name"))
                if not CAPABILITY_ID_RE.fullmatch(capability_id):
                    local.append("INVALID_GRANT_TRANSPORT_CAPABILITY_ID")
                if not SOURCE_RE.fullmatch(source):
                    local.append("INVALID_GRANT_METRIC_SOURCE")
                if not ENV_NAME_RE.fullmatch(credential):
                    local.append("INVALID_GRANT_CREDENTIAL_ENV_NAME")
                if expected_namespace and credential and not credential.startswith(expected_namespace):
                    local.append("BINDING_CREDENTIAL_OUTSIDE_INSTANCE_NAMESPACE")
                if capability_id and source and credential:
                    normalized = {
                        "transport_capability_id": capability_id,
                        "metric_source": source,
                        "credential_env_name": credential,
                    }
                    grants.append(normalized)
                    grant_tuples.append((capability_id, source, credential))

        if len(set(grant_tuples)) != len(grant_tuples):
            local.append("DUPLICATE_BINDING_CAPABILITY_GRANT")

        credentials = {grant[2] for grant in grant_tuples}
        sources = {grant[1] for grant in grant_tuples}
        capability_ids = {grant[0] for grant in grant_tuples}

        requirement = requirements.get(instance_id)
        if requirement:
            required_grants: set[GrantTuple] = requirement["grants"]  # type: ignore[assignment]
            actual_grants = set(grant_tuples)
            missing_grants = sorted(required_grants - actual_grants)
            extra_grants = sorted(actual_grants - required_grants)
            if missing_grants:
                local.append("BINDING_MISSING_REQUIRED_CAPABILITY_GRANTS:" + ",".join(_grant_label(item) for item in missing_grants))
            if extra_grants:
                local.append("BINDING_OVERGRANTS_CAPABILITY_GRANTS:" + ",".join(_grant_label(item) for item in extra_grants))

            required_credentials: set[str] = requirement["credentials"]  # type: ignore[assignment]
            required_sources: set[str] = requirement["sources"]  # type: ignore[assignment]
            required_capability_ids: set[str] = requirement["capability_ids"]  # type: ignore[assignment]
            missing_credentials = sorted(required_credentials - credentials)
            extra_credentials = sorted(credentials - required_credentials)
            missing_sources = sorted(required_sources - sources)
            extra_sources = sorted(sources - required_sources)
            missing_capabilities = sorted(required_capability_ids - capability_ids)
            extra_capabilities = sorted(capability_ids - required_capability_ids)
            if missing_credentials:
                local.append("BINDING_MISSING_REQUIRED_CREDENTIALS:" + ",".join(missing_credentials))
            if extra_credentials:
                local.append("BINDING_OVERGRANTS_CREDENTIALS:" + ",".join(extra_credentials))
            if missing_sources:
                local.append("BINDING_MISSING_REQUIRED_SOURCES:" + ",".join(missing_sources))
            if extra_sources:
                local.append("BINDING_OVERGRANTS_SOURCES:" + ",".join(extra_sources))
            if missing_capabilities:
                local.append("BINDING_MISSING_REQUIRED_CAPABILITIES:" + ",".join(missing_capabilities))
            if extra_capabilities:
                local.append("BINDING_OVERGRANTS_CAPABILITIES:" + ",".join(extra_capabilities))
        else:
            local.append("BINDING_HAS_NO_CAPABILITY_APPROVED_METRICS_CHANNELS")

        for name in credentials:
            owner = credential_owner.get(name)
            if owner and owner != instance_id:
                local.append(f"CROSS_INSTANCE_CREDENTIAL_REUSE:{name}:{owner}")
            else:
                credential_owner[name] = instance_id

        row = {
            "binding_id": binding_id or None,
            "instance_id": instance_id or None,
            "credential_namespace": namespace or None,
            "capability_grants": sorted(
                grants,
                key=lambda grant: (
                    grant["transport_capability_id"],
                    grant["metric_source"],
                    grant["credential_env_name"],
                ),
            ),
            "credential_env_names": sorted(credentials),
            "metric_sources": sorted(sources),
            "transport_capability_ids": sorted(capability_ids),
            "hard_blocks": sorted(set(local)),
        }
        if local:
            binding_holds.append(row)
        elif binding_id and instance_id:
            parsed[instance_id] = row

    unbound_instances = sorted(set(requirements) - set(parsed))
    matrix = [
        {
            "binding_id": parsed[instance_id]["binding_id"],
            "instance_id": instance_id,
            "credential_env_names": parsed[instance_id]["credential_env_names"],
            "metric_sources": parsed[instance_id]["metric_sources"],
        }
        for instance_id in sorted(parsed)
    ]
    capability_authorizations = [
        {
            "binding_id": parsed[instance_id]["binding_id"],
            "instance_id": instance_id,
            "transport_capability_ids": parsed[instance_id]["transport_capability_ids"],
            "capability_grants": parsed[instance_id]["capability_grants"],
        }
        for instance_id in sorted(parsed)
    ]

    structural_hold = bool(blocks)
    if structural_hold:
        matrix = []
        capability_authorizations = []

    if structural_hold:
        status = "CREDENTIAL_BINDINGS_HOLD"
    elif binding_holds or unbound_instances:
        status = "CREDENTIAL_BINDINGS_PARTIAL"
    elif matrix:
        status = "CREDENTIAL_BINDINGS_READY"
    else:
        status = "CREDENTIAL_BINDINGS_IDLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "binding_engine_id": BINDING_ID,
        "status": status,
        "hard_blocks": sorted(set(blocks)),
        "binding_holds": binding_holds,
        "unbound_instances": unbound_instances,
        "workflow_matrix": matrix,
        "capability_authorizations": capability_authorizations,
        "capability_gate_status": capability_result.get("status") if isinstance(capability_result, dict) else None,
        "publication_blocked": False,
        "guards": {
            "explicit_per_instance_grant_required": True,
            "transport_capability_binding_required": True,
            "standalone_capability_gate_required": True,
            "capability_gate_bypass_allowed": False,
            "future_instance_implicit_secret_grant": False,
            "cross_instance_secret_sharing_forbidden": True,
            "secret_values_read_by_binding_engine": False,
            "secret_values_returned": False,
            "secret_values_persisted": False,
            "dynamic_secret_enumeration_allowed": False,
            "tojson_secrets_allowed": False,
            "analytics_advisory_only": True,
            "publication_blocked_by_analytics": False,
            "zero_paid_dependency": True,
        },
    }


def execute_bound_instance(
    repo_root: Path,
    runtime: dict[str, Any],
    isolation_result: dict[str, Any],
    binding_plan: dict[str, Any],
    binding_id: str,
    *,
    now: str,
    execute: bool,
    windows_hours: tuple[int, ...] = fleet.operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    orchestrate_call: OrchestrateCall = fleet.orchestrate_fleet,
) -> dict[str, Any]:
    """Execute or dry-run exactly one capability-authorized instance binding."""
    wanted = _clean(binding_id).lower()
    matrix = binding_plan.get("workflow_matrix") if isinstance(binding_plan.get("workflow_matrix"), list) else []
    match = next((row for row in matrix if isinstance(row, dict) and _clean(row.get("binding_id")).lower() == wanted), None)
    authorizations = binding_plan.get("capability_authorizations") if isinstance(binding_plan.get("capability_authorizations"), list) else []
    authorization = next((row for row in authorizations if isinstance(row, dict) and _clean(row.get("binding_id")).lower() == wanted), None)
    if not match or not authorization:
        reason = "BINDING_NOT_AUTHORIZED_FOR_EXECUTION" if not match else "BINDING_CAPABILITY_AUTHORIZATION_MISSING"
        return {
            "schema_version": SCHEMA_VERSION,
            "binding_engine_id": BINDING_ID,
            "status": "HOLD_CREDENTIAL_BINDING",
            "hard_blocks": [reason],
            "publication_blocked": False,
            "binding_id": wanted or None,
            "instance_id": None,
            "durable_paths": [],
            "required_credential_env_names": [],
            "transport_capability_ids": [],
            "guards": binding_plan.get("guards", {}),
        }

    instance_id = _clean(match.get("instance_id")).lower()
    if _clean(authorization.get("instance_id")).lower() != instance_id:
        return {
            "schema_version": SCHEMA_VERSION,
            "binding_engine_id": BINDING_ID,
            "status": "HOLD_CREDENTIAL_BINDING",
            "hard_blocks": ["BINDING_CAPABILITY_AUTHORIZATION_INSTANCE_MISMATCH"],
            "publication_blocked": False,
            "binding_id": wanted,
            "instance_id": instance_id or None,
            "durable_paths": [],
            "required_credential_env_names": [],
            "transport_capability_ids": [],
            "guards": binding_plan.get("guards", {}),
        }

    instances = runtime.get("instances") if isinstance(runtime.get("instances"), list) else []
    selected = [item for item in instances if isinstance(item, dict) and _clean(item.get("instance_id")).lower() == instance_id]
    if len(selected) != 1:
        return {
            "schema_version": SCHEMA_VERSION,
            "binding_engine_id": BINDING_ID,
            "status": "HOLD_CREDENTIAL_BINDING",
            "hard_blocks": ["BOUND_INSTANCE_RUNTIME_CARDINALITY_MISMATCH"],
            "publication_blocked": False,
            "binding_id": wanted,
            "instance_id": instance_id or None,
            "durable_paths": [],
            "required_credential_env_names": [],
            "transport_capability_ids": [],
            "guards": binding_plan.get("guards", {}),
        }

    filtered_runtime = dict(runtime)
    filtered_runtime["instances"] = [selected[0]]

    preflight = orchestrate_call(
        repo_root,
        filtered_runtime,
        isolation_result,
        now=now,
        execute=False,
        windows_hours=windows_hours,
        max_publications=max_publications,
    )
    expected_credentials = sorted(set(match.get("credential_env_names", [])))
    actual_credentials = sorted(set(preflight.get("required_credential_env_names", []))) if isinstance(preflight, dict) else []
    if actual_credentials != expected_credentials:
        return {
            "schema_version": SCHEMA_VERSION,
            "binding_engine_id": BINDING_ID,
            "status": "HOLD_CREDENTIAL_BINDING",
            "hard_blocks": ["BOUND_INSTANCE_CREDENTIAL_REQUIREMENTS_CHANGED"],
            "publication_blocked": False,
            "binding_id": wanted,
            "instance_id": instance_id,
            "durable_paths": [],
            "required_credential_env_names": actual_credentials,
            "transport_capability_ids": sorted(set(authorization.get("transport_capability_ids", []))),
            "guards": binding_plan.get("guards", {}),
        }

    result = preflight
    if execute:
        result = orchestrate_call(
            repo_root,
            filtered_runtime,
            isolation_result,
            now=now,
            execute=True,
            windows_hours=windows_hours,
            max_publications=max_publications,
        )

    durable_paths = sorted(set(result.get("durable_paths", []))) if isinstance(result, dict) and isinstance(result.get("durable_paths"), list) else []
    return {
        "schema_version": SCHEMA_VERSION,
        "binding_engine_id": BINDING_ID,
        "status": "BOUND_INSTANCE_EXECUTED" if execute else "BOUND_INSTANCE_READY",
        "hard_blocks": list(result.get("hard_blocks", [])) if isinstance(result, dict) and isinstance(result.get("hard_blocks"), list) else [],
        "publication_blocked": False,
        "binding_id": wanted,
        "instance_id": instance_id,
        "durable_paths": durable_paths,
        "required_credential_env_names": expected_credentials,
        "transport_capability_ids": sorted(set(authorization.get("transport_capability_ids", []))),
        "fleet_status": result.get("status") if isinstance(result, dict) else None,
        "fleet_result": result,
        "guards": binding_plan.get("guards", {}),
    }


def run_plan(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY,
    *,
    now: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = repo_root.resolve()
    runtime_target = root / runtime_registry_path
    binding_target = root / binding_registry_path
    runtime = _load_json(runtime_target)
    registry = _load_json(binding_target)
    fleet_result = fleet.run_fleet(root, runtime_registry_path, now=now, execute=False)
    capability_result = capability_gate.run_gate(
        root,
        runtime_registry_path,
        capability_registry_path,
        now=now,
    )
    plan = plan_credential_bindings(runtime, registry, fleet_result, capability_result)
    return plan, runtime, registry, fleet_result


def run_binding(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = DEFAULT_CAPABILITY_REGISTRY,
    *,
    binding_id: str,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = fleet.operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
) -> dict[str, Any]:
    plan, runtime, _registry, _fleet_result = run_plan(
        repo_root,
        runtime_registry_path,
        binding_registry_path,
        capability_registry_path,
        now=now,
    )
    isolation_result = multi_instance_isolation.validate_runtime_path(runtime_registry_path, repo_root.resolve())
    return execute_bound_instance(
        repo_root.resolve(),
        runtime,
        isolation_result,
        plan,
        binding_id,
        now=now,
        execute=execute,
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
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=fleet.operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
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
            now=args.now,
            execute=args.execute,
            windows_hours=windows,
            max_publications=args.max_publications,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 2 if result["status"].startswith("HOLD_") else 0

    plan, _runtime, _registry, _fleet_result = run_plan(
        args.repo_root,
        args.runtime_registry,
        args.binding_registry,
        args.capability_registry,
        now=args.now,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if plan["status"] == "CREDENTIAL_BINDINGS_HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
