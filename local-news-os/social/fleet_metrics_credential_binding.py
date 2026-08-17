#!/usr/bin/env python3
"""Explicit per-instance credential binding for fleet observed-metrics harvest.

Fleet discovery is intentionally generic, while secret injection must remain an
explicit least-privilege grant.  This boundary validates a checked-in registry
that maps one CIVORA instance to the *names* of the GitHub Actions secrets that
its verified native/free metrics channels require.

Important boundaries:
- no secret values are read, returned, fingerprinted, logged, or persisted here;
- a future instance is never granted credentials merely because fleet discovery
  finds it;
- one credential env name cannot belong to two instances;
- a binding cannot grant credentials or metric sources beyond what current
  CHANNEL_CONFIG + verified transport discovery requires;
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
import multi_instance_isolation

SCHEMA_VERSION = "1.0"
BINDING_ID = "local-news-os-fleet-metrics-credential-binding"
DEFAULT_RUNTIME_REGISTRY = Path("local-news-os/social/social_runtime_registry.json")
DEFAULT_BINDING_REGISTRY = Path("local-news-os/social/metrics_credential_bindings.json")

BINDING_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,95}$")
INSTANCE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,95}$")

TOP_LEVEL_FIELDS = {"schema_version", "product", "policy", "bindings"}
POLICY_FIELDS = {
    "explicit_per_instance_grant_required",
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
    "credential_env_names",
    "metric_sources",
}
REQUIRED_TRUE_POLICIES = POLICY_FIELDS

OrchestrateCall = Callable[..., dict[str, Any]]


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


def _eligible_requirements(fleet_result: dict[str, Any]) -> dict[str, dict[str, set[str]]]:
    required: dict[str, dict[str, set[str]]] = {}
    channels = fleet_result.get("channels") if isinstance(fleet_result.get("channels"), list) else []
    for row in channels:
        if not isinstance(row, dict) or row.get("eligible") is not True:
            continue
        instance_id = _clean(row.get("instance_id")).lower()
        credential = _clean(row.get("credential_env_name"))
        source = _clean(row.get("metric_source")).lower()
        if not instance_id or not credential or not source:
            continue
        bucket = required.setdefault(instance_id, {"credentials": set(), "sources": set()})
        bucket["credentials"].add(credential)
        bucket["sources"].add(source)
    return required


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


def plan_credential_bindings(
    runtime: dict[str, Any],
    binding_registry: dict[str, Any],
    fleet_result: dict[str, Any],
) -> dict[str, Any]:
    """Build a secret-free execution matrix from validated fleet discovery."""
    if not all(isinstance(value, dict) for value in (runtime, binding_registry, fleet_result)):
        raise TypeError("runtime, binding_registry and fleet_result must be mappings")

    blocks = _policy_blocks(binding_registry)
    if fleet_result.get("publication_blocked") is True:
        blocks.append("ANALYTICS_FLEET_RESULT_ATTEMPTED_TO_BLOCK_PUBLICATION")
    fleet_guards = fleet_result.get("guards") if isinstance(fleet_result.get("guards"), dict) else {}
    if fleet_guards.get("zero_paid_dependency") is not True:
        blocks.append("FLEET_ZERO_PAID_GUARD_MISSING")
    if fleet_guards.get("credential_values_returned") is not False:
        blocks.append("FLEET_CREDENTIAL_VALUE_GUARD_MISSING")

    instances = _instance_map(runtime)
    requirements = _eligible_requirements(fleet_result)
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
        credentials_raw = raw.get("credential_env_names")
        sources_raw = raw.get("metric_sources")

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

        if not isinstance(credentials_raw, list) or not credentials_raw:
            credentials: list[str] = []
            local.append("BINDING_CREDENTIAL_ENV_NAMES_REQUIRED")
        else:
            credentials = [_clean(item) for item in credentials_raw]
            if any(not ENV_NAME_RE.fullmatch(item) for item in credentials):
                local.append("INVALID_BINDING_CREDENTIAL_ENV_NAME")
            if len(set(credentials)) != len(credentials):
                local.append("DUPLICATE_BINDING_CREDENTIAL_ENV_NAME")
            if expected_namespace and any(not item.startswith(expected_namespace) for item in credentials):
                local.append("BINDING_CREDENTIAL_OUTSIDE_INSTANCE_NAMESPACE")

        if not isinstance(sources_raw, list) or not sources_raw:
            sources: list[str] = []
            local.append("BINDING_METRIC_SOURCES_REQUIRED")
        else:
            sources = [_clean(item).lower() for item in sources_raw]
            if any(not SOURCE_RE.fullmatch(item) for item in sources):
                local.append("INVALID_BINDING_METRIC_SOURCE")
            if len(set(sources)) != len(sources):
                local.append("DUPLICATE_BINDING_METRIC_SOURCE")

        requirement = requirements.get(instance_id)
        if requirement:
            required_credentials = requirement["credentials"]
            required_sources = requirement["sources"]
            missing_credentials = sorted(required_credentials - set(credentials))
            extra_credentials = sorted(set(credentials) - required_credentials)
            missing_sources = sorted(required_sources - set(sources))
            extra_sources = sorted(set(sources) - required_sources)
            if missing_credentials:
                local.append("BINDING_MISSING_REQUIRED_CREDENTIALS:" + ",".join(missing_credentials))
            if extra_credentials:
                local.append("BINDING_OVERGRANTS_CREDENTIALS:" + ",".join(extra_credentials))
            if missing_sources:
                local.append("BINDING_MISSING_REQUIRED_SOURCES:" + ",".join(missing_sources))
            if extra_sources:
                local.append("BINDING_OVERGRANTS_SOURCES:" + ",".join(extra_sources))
        else:
            local.append("BINDING_HAS_NO_ELIGIBLE_NATIVE_METRICS_CHANNELS")

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
            "credential_env_names": sorted(set(credentials)),
            "metric_sources": sorted(set(sources)),
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

    # Structural/policy faults invalidate the complete matrix. Per-instance
    # missing/invalid grants remain analytics-local holds and do not stop other
    # correctly bound instances.
    structural_hold = bool(blocks)
    if structural_hold:
        matrix = []

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
        "publication_blocked": False,
        "guards": {
            "explicit_per_instance_grant_required": True,
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
    """Execute or dry-run exactly one validated instance binding."""
    wanted = _clean(binding_id).lower()
    matrix = binding_plan.get("workflow_matrix") if isinstance(binding_plan.get("workflow_matrix"), list) else []
    match = next((row for row in matrix if isinstance(row, dict) and _clean(row.get("binding_id")).lower() == wanted), None)
    if not match:
        return {
            "schema_version": SCHEMA_VERSION,
            "binding_engine_id": BINDING_ID,
            "status": "HOLD_CREDENTIAL_BINDING",
            "hard_blocks": ["BINDING_NOT_AUTHORIZED_FOR_EXECUTION"],
            "publication_blocked": False,
            "binding_id": wanted or None,
            "instance_id": None,
            "durable_paths": [],
            "required_credential_env_names": [],
            "guards": binding_plan.get("guards", {}),
        }

    instance_id = _clean(match.get("instance_id")).lower()
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
            "guards": binding_plan.get("guards", {}),
        }

    filtered_runtime = dict(runtime)
    filtered_runtime["instances"] = [selected[0]]

    # Re-run a network-free preflight on the exact instance before execution so
    # a changed channel credential reference cannot outgrow the checked binding.
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
        "fleet_status": result.get("status") if isinstance(result, dict) else None,
        "fleet_result": result,
        "guards": binding_plan.get("guards", {}),
    }


def run_plan(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
    *,
    now: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    repo_root = repo_root.resolve()
    runtime_target = repo_root / runtime_registry_path
    binding_target = repo_root / binding_registry_path
    runtime = _load_json(runtime_target)
    registry = _load_json(binding_target)
    fleet_result = fleet.run_fleet(repo_root, runtime_registry_path, now=now, execute=False)
    plan = plan_credential_bindings(runtime, registry, fleet_result)
    return plan, runtime, registry, fleet_result


def run_binding(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = DEFAULT_BINDING_REGISTRY,
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
        now=args.now,
    )
    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if plan["status"] == "CREDENTIAL_BINDINGS_HOLD" else 0


if __name__ == "__main__":
    raise SystemExit(main())
