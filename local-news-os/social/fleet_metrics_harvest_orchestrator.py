#!/usr/bin/env python3
"""Fleet-level observed-metrics harvest orchestration for LOCAL NEWS OS.

This layer removes instance/channel hard-coding from the operational metrics trigger.
It discovers CIVORA instances from ``social_runtime_registry.json``, validates the
existing multi-instance isolation contract, loads each instance's channel registry,
and delegates only channels with an already-implemented native/free metrics profile
to ``operational_metrics_harvest_trigger``.

Important boundaries:
- analytics can never block or roll back editorial publication;
- no transport or access is invented for unsupported/unverified channels;
- access-attestation paths are declared explicitly per instance/source in the fleet
  registry and must remain inside that instance root;
- credential *names* may be returned for operator/runtime wiring, but values are
  resolved only by the downstream network boundary and are never persisted here;
- derived metrics state is preflighted for instance ownership before execution;
- zero-paid dependency and observed-only metrics remain mandatory.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import multi_instance_isolation
import native_metrics_transport
import operational_metrics_harvest_trigger

SCHEMA_VERSION = "1.0"
ORCHESTRATOR_ID = "local-news-os-fleet-metrics-harvest-orchestrator"
DEFAULT_RUNTIME_REGISTRY = Path("local-news-os/social/social_runtime_registry.json")

EvaluateChannel = Callable[..., dict[str, Any]]
FleetValidator = Callable[[Path, Path], dict[str, Any]]
CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]
PersistBundleCall = Callable[[Path, dict[str, Any]], dict[str, Any]]


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


def _target(repo_root: Path, relative: Any) -> Path:
    safe = _safe_rel(relative)
    if not safe:
        raise ValueError("unsafe repository-relative path")
    return repo_root.joinpath(*PurePosixPath(safe).parts)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _hold(instance_id: str, registry_channel_id: str | None, platform: str | None,
          reason: str, *, channel_id: str | None = None) -> dict[str, Any]:
    return {
        "instance_id": instance_id or None,
        "registry_channel_id": registry_channel_id or None,
        "channel_id": channel_id or None,
        "platform": platform or None,
        "status": "HOLD_FLEET_DISCOVERY",
        "hard_blocks": [reason],
        "publication_blocked": False,
        "durable_paths": [],
    }


def _expected_runtime_paths(channel: dict[str, Any]) -> list[str]:
    """Return channel-local catalog/runtime paths before any provider call."""
    paths = [
        operational_metrics_harvest_trigger.publication_metrics_catalog.expected_catalog_path(channel),
        operational_metrics_harvest_trigger.metrics_harvest_runtime.expected_checkpoint_state_path(channel),
        operational_metrics_harvest_trigger.observed_metrics_collector.expected_observation_store_path(channel),
        operational_metrics_harvest_trigger.durable_feedback_snapshot.expected_snapshot_path(channel),
    ]
    clean = [_safe_rel(path) for path in paths]
    if not all(clean):
        raise ValueError("invalid derived metrics runtime path")
    return sorted(set(clean))


def _source_for_platform(platform: str) -> str:
    profile = native_metrics_transport.META_PROFILES.get(platform)
    return _clean(profile.get("source")) if isinstance(profile, dict) else ""


def _top_status(rows: list[dict[str, Any]], *, execute: bool, isolation_ok: bool) -> str:
    if not isolation_ok:
        return "FLEET_HOLD"
    holds = [row for row in rows if _clean(row.get("status")).startswith("HOLD_")]
    eligible = [row for row in rows if row.get("eligible") is True]
    executed = [row for row in eligible if row.get("status") == "HARVEST_EXECUTED"]
    ready = [row for row in eligible if row.get("status") == "HARVEST_READY"]
    if holds:
        return "FLEET_PARTIAL_HOLD" if len(holds) < len(rows) else "FLEET_HOLD"
    if execute and executed:
        return "FLEET_EXECUTED"
    if not execute and ready:
        return "FLEET_HARVEST_READY"
    return "FLEET_IDLE"


def orchestrate_fleet(
    repo_root: Path,
    runtime: dict[str, Any],
    isolation_result: dict[str, Any],
    *,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    evaluate_channel_call: EvaluateChannel = operational_metrics_harvest_trigger.evaluate_channel,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
    persist_bundle_call: PersistBundleCall | None = None,
) -> dict[str, Any]:
    """Discover and evaluate all fleet channels with verified native/free transport.

    ``isolation_result`` is passed separately so tests can exercise discovery without
    constructing a complete adapter fleet. Production callers always obtain it from
    ``multi_instance_isolation.validate_runtime_path`` before this function runs.
    """
    if not isinstance(runtime, dict) or not isinstance(isolation_result, dict):
        raise TypeError("runtime and isolation_result must be mappings")

    isolation_ok = isolation_result.get("status") == "PASS"
    if not isolation_ok:
        return {
            "schema_version": SCHEMA_VERSION,
            "orchestrator_id": ORCHESTRATOR_ID,
            "status": "FLEET_HOLD",
            "hard_blocks": ["FLEET_ISOLATION_BLOCKED"] + [
                _clean(item) for item in isolation_result.get("errors", []) if _clean(item)
            ],
            "publication_blocked": False,
            "execute": bool(execute),
            "instances": [],
            "channels": [],
            "skipped_channels": [],
            "durable_paths": [],
            "required_credential_env_names": [],
            "guards": _guards(),
        }

    instances = runtime.get("instances")
    if not isinstance(instances, list):
        instances = []

    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    instance_rows: list[dict[str, Any]] = []
    required_credentials: set[str] = set()
    durable_owners: dict[str, str] = {}
    discovered_channel_keys: set[tuple[str, str]] = set()

    for entry in sorted((item for item in instances if isinstance(item, dict)), key=lambda x: _clean(x.get("instance_id"))):
        instance_id = _clean(entry.get("instance_id")).lower()
        instance_root = _safe_rel(entry.get("instance_root"))
        registry_rel = _safe_rel(entry.get("channel_registry"))
        credential_namespace = _clean(entry.get("credential_namespace"))
        metrics_harvest = entry.get("metrics_harvest") if isinstance(entry.get("metrics_harvest"), dict) else {}
        attestation_map = metrics_harvest.get("access_attestations") if isinstance(metrics_harvest.get("access_attestations"), dict) else {}
        instance_summary = {
            "instance_id": instance_id or None,
            "instance_root": instance_root or None,
            "channel_registry": registry_rel or None,
            "eligible_channels": 0,
            "skipped_channels": 0,
            "held_channels": 0,
        }

        if not instance_id or not instance_root or not registry_rel:
            rows.append(_hold(instance_id, None, None, "INVALID_INSTANCE_DISCOVERY_METADATA"))
            instance_summary["held_channels"] += 1
            instance_rows.append(instance_summary)
            continue

        try:
            registry_target = _target(repo_root, registry_rel)
            if not _within(registry_rel, instance_root):
                raise ValueError("channel registry outside instance root")
            registry = _load_json(registry_target)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            rows.append(_hold(instance_id, None, None, f"CHANNEL_REGISTRY_UNAVAILABLE:{type(exc).__name__}"))
            instance_summary["held_channels"] += 1
            instance_rows.append(instance_summary)
            continue

        if _clean(registry.get("instance_id")).lower() != instance_id:
            rows.append(_hold(instance_id, None, None, "CHANNEL_REGISTRY_INSTANCE_MISMATCH"))
            instance_summary["held_channels"] += 1
            instance_rows.append(instance_summary)
            continue

        channels = registry.get("channels") if isinstance(registry.get("channels"), list) else []
        for registry_channel in sorted((item for item in channels if isinstance(item, dict)), key=lambda x: _clean(x.get("channel_id"))):
            registry_channel_id = _clean(registry_channel.get("channel_id")).lower()
            config_rel = _safe_rel(registry_channel.get("config"))
            if not registry_channel_id or not config_rel:
                rows.append(_hold(instance_id, registry_channel_id, None, "INVALID_CHANNEL_DISCOVERY_ENTRY"))
                instance_summary["held_channels"] += 1
                continue
            if not _within(config_rel, instance_root):
                rows.append(_hold(instance_id, registry_channel_id, None, "CHANNEL_CONFIG_OUTSIDE_INSTANCE"))
                instance_summary["held_channels"] += 1
                continue

            try:
                channel = _load_json(_target(repo_root, config_rel))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                rows.append(_hold(instance_id, registry_channel_id, None, f"CHANNEL_CONFIG_UNAVAILABLE:{type(exc).__name__}"))
                instance_summary["held_channels"] += 1
                continue

            platform = _clean(channel.get("platform")).lower()
            channel_id = _clean(channel.get("channel_id"))
            if _clean(channel.get("instance_id")).lower() != instance_id:
                rows.append(_hold(instance_id, registry_channel_id, platform, "CHANNEL_INSTANCE_MISMATCH", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue

            key = (instance_id, channel_id)
            if not channel_id or key in discovered_channel_keys:
                rows.append(_hold(instance_id, registry_channel_id, platform, "DUPLICATE_OR_MISSING_CHANNEL_ID", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            discovered_channel_keys.add(key)

            source = _source_for_platform(platform)
            if not source:
                skipped.append({
                    "instance_id": instance_id,
                    "registry_channel_id": registry_channel_id,
                    "channel_id": channel_id,
                    "platform": platform or None,
                    "reason": "UNSUPPORTED_NATIVE_METRICS_TRANSPORT",
                    "publication_blocked": False,
                })
                instance_summary["skipped_channels"] += 1
                continue

            metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
            declared_sources = {_clean(item) for item in metrics.get("sources", []) if _clean(item)} if isinstance(metrics.get("sources"), list) else set()
            if channel.get("zero_paid_dependency") is not True:
                rows.append(_hold(instance_id, registry_channel_id, platform, "ZERO_PAID_DEPENDENCY_VIOLATION", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            if metrics.get("observed_only") is not True or source not in declared_sources:
                rows.append(_hold(instance_id, registry_channel_id, platform, "NATIVE_METRICS_POLICY_NOT_DECLARED", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue

            try:
                credential_name = native_metrics_transport.credential_env_name(channel.get("credentials_ref"))
            except ValueError as exc:
                rows.append(_hold(instance_id, registry_channel_id, platform, str(exc), channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            if not credential_namespace or not credential_name.startswith(credential_namespace):
                rows.append(_hold(instance_id, registry_channel_id, platform, "CREDENTIAL_OUTSIDE_INSTANCE_NAMESPACE", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue

            attestation_rel = _safe_rel(attestation_map.get(source))
            if not attestation_rel:
                rows.append(_hold(instance_id, registry_channel_id, platform, "METRICS_ACCESS_ATTESTATION_NOT_DECLARED", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            if not _within(attestation_rel, instance_root):
                rows.append(_hold(instance_id, registry_channel_id, platform, "METRICS_ACCESS_ATTESTATION_OUTSIDE_INSTANCE", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            try:
                attestation = _load_json(_target(repo_root, attestation_rel))
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                rows.append(_hold(instance_id, registry_channel_id, platform, f"METRICS_ACCESS_ATTESTATION_UNAVAILABLE:{type(exc).__name__}", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue

            try:
                expected_paths = _expected_runtime_paths(channel)
            except (TypeError, ValueError) as exc:
                rows.append(_hold(instance_id, registry_channel_id, platform, f"METRICS_RUNTIME_PATH_INVALID:{type(exc).__name__}", channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue

            collision = None
            for path in expected_paths:
                if not _within(path, instance_root):
                    collision = "METRICS_RUNTIME_PATH_OUTSIDE_INSTANCE"
                    break
                owner = durable_owners.get(path)
                if owner and owner != instance_id:
                    collision = "CROSS_INSTANCE_METRICS_RUNTIME_COLLISION"
                    break
            if collision:
                rows.append(_hold(instance_id, registry_channel_id, platform, collision, channel_id=channel_id))
                instance_summary["held_channels"] += 1
                continue
            for path in expected_paths:
                durable_owners.setdefault(path, instance_id)

            kwargs: dict[str, Any] = {
                "now": now,
                "execute": execute,
                "windows_hours": windows_hours,
                "max_publications": max_publications,
            }
            if credential_resolver is not None:
                kwargs["credential_resolver"] = credential_resolver
            if transport_call is not None:
                kwargs["transport_call"] = transport_call
            if persist_bundle_call is not None:
                kwargs["persist_bundle_call"] = persist_bundle_call

            result = evaluate_channel_call(repo_root, channel, attestation, **kwargs)
            row = dict(result) if isinstance(result, dict) else {}
            row.update({
                "instance_id": instance_id,
                "registry_channel_id": registry_channel_id,
                "channel_id": channel_id,
                "platform": platform,
                "metric_source": source,
                "access_attestation_path": attestation_rel,
                "credential_env_name": credential_name,
                "eligible": True,
                "publication_blocked": False,
            })
            result_paths = [_safe_rel(path) for path in row.get("durable_paths", []) if _safe_rel(path)] if isinstance(row.get("durable_paths"), list) else []
            unsafe_result_path = next((path for path in result_paths if not _within(path, instance_root)), None)
            if unsafe_result_path:
                row["status"] = "HOLD_FLEET_DISCOVERY"
                row["hard_blocks"] = sorted(set(list(row.get("hard_blocks", [])) + ["RETURNED_DURABLE_PATH_OUTSIDE_INSTANCE"]))
                row["durable_paths"] = []
                instance_summary["held_channels"] += 1
            else:
                row["durable_paths"] = sorted(set(result_paths))
                if _clean(row.get("status")).startswith("HOLD_"):
                    instance_summary["held_channels"] += 1
                else:
                    instance_summary["eligible_channels"] += 1
            required_credentials.add(credential_name)
            rows.append(row)

        instance_rows.append(instance_summary)

    # Returned durable paths must remain single-owner even if a custom evaluator is injected.
    persisted_owner: dict[str, str] = {}
    for row in rows:
        instance_id = _clean(row.get("instance_id"))
        for path in row.get("durable_paths", []) if isinstance(row.get("durable_paths"), list) else []:
            owner = persisted_owner.get(path)
            if owner and owner != instance_id:
                row["status"] = "HOLD_FLEET_DISCOVERY"
                row["hard_blocks"] = sorted(set(list(row.get("hard_blocks", [])) + ["CROSS_INSTANCE_RETURNED_DURABLE_PATH_COLLISION"]))
                row["durable_paths"] = []
                break
            persisted_owner[path] = instance_id

    hard_blocks = sorted({
        _clean(code) for row in rows for code in (row.get("hard_blocks", []) if isinstance(row.get("hard_blocks"), list) else []) if _clean(code)
    })
    durable_paths = sorted({
        _safe_rel(path) for row in rows for path in (row.get("durable_paths", []) if isinstance(row.get("durable_paths"), list) else []) if _safe_rel(path)
    })

    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_id": ORCHESTRATOR_ID,
        "status": _top_status(rows, execute=execute, isolation_ok=True),
        "hard_blocks": hard_blocks,
        "publication_blocked": False,
        "execute": bool(execute),
        "instances": instance_rows,
        "channels": rows,
        "skipped_channels": skipped,
        "durable_paths": durable_paths,
        "required_credential_env_names": sorted(required_credentials),
        "guards": _guards(),
    }


def _guards() -> dict[str, Any]:
    return {
        "fleet_discovery_from_registry": True,
        "hardcoded_instance_or_platform_selection": False,
        "cross_instance_metrics_sharing_forbidden": True,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "legacy_descriptor_fabrication_allowed": False,
        "credential_values_returned": False,
        "credential_values_persisted": False,
        "raw_provider_payload_persisted": False,
        "predictive_or_estimated_analytics_used": False,
        "native_free_transport_only": True,
        "zero_paid_dependency": True,
    }


def run_fleet(
    repo_root: Path,
    runtime_registry_path: Path = DEFAULT_RUNTIME_REGISTRY,
    *,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = operational_metrics_harvest_trigger.DEFAULT_WINDOWS_HOURS,
    max_publications: int = operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    fleet_validator: FleetValidator = multi_instance_isolation.validate_runtime_path,
    evaluate_channel_call: EvaluateChannel = operational_metrics_harvest_trigger.evaluate_channel,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
    persist_bundle_call: PersistBundleCall | None = None,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    runtime_rel = _safe_rel(runtime_registry_path.as_posix())
    if not runtime_rel:
        raise ValueError("runtime registry must be repository-relative")
    runtime_target = _target(repo_root, runtime_rel)
    runtime = _load_json(runtime_target)
    isolation_result = fleet_validator(Path(runtime_rel), repo_root)
    return orchestrate_fleet(
        repo_root,
        runtime,
        isolation_result,
        now=now,
        execute=execute,
        windows_hours=windows_hours,
        max_publications=max_publications,
        evaluate_channel_call=evaluate_channel_call,
        credential_resolver=credential_resolver,
        transport_call=transport_call,
        persist_bundle_call=persist_bundle_call,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--runtime-registry", type=Path, default=DEFAULT_RUNTIME_REGISTRY)
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=operational_metrics_harvest_trigger.metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    windows = tuple(int(item.strip()) for item in args.windows_hours.split(",") if item.strip())
    result = run_fleet(
        args.repo_root,
        args.runtime_registry,
        now=args.now,
        execute=args.execute,
        windows_hours=windows,
        max_publications=args.max_publications,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] in {"FLEET_HOLD", "FLEET_PARTIAL_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
