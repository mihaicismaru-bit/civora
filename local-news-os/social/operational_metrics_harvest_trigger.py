#!/usr/bin/env python3
"""Operational observed-metrics harvest trigger for LOCAL NEWS OS.

This boundary connects a channel-local publication metrics catalog to the existing
bounded scheduler and crash-safe harvest runtime. It is intentionally outside the
editorial publication path: missing catalogs, no due checkpoints, provider auth
problems, and analytics transport failures never block or roll back publication.

Only native/free transports already implemented by ``native_metrics_transport``
are eligible. Credential *names* may appear in plans; credential values are read
only by ``metrics_harvest_runtime`` at its network boundary and are never returned
or persisted by this trigger.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import durable_feedback_snapshot
import metrics_harvest_runtime
import metrics_harvest_scheduler
import native_metrics_transport
import observed_metrics_collector
import publication_metrics_catalog

SCHEMA_VERSION = "1.0"
TRIGGER_ID = "local-news-os-operational-metrics-harvest-trigger"
DEFAULT_WINDOWS_HOURS = (1, 6, 24, 72)

CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]
PersistBundleCall = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _safe_target(repo_root: Path, relative: str) -> Path:
    path = PurePosixPath(_clean(relative).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("unsafe runtime path")
    return repo_root.joinpath(*path.parts)


def _load_optional(repo_root: Path, relative: str) -> dict[str, Any] | None:
    target = _safe_target(repo_root, relative)
    if not target.exists():
        return None
    return _load_object(target)


def _channel_result(channel: dict[str, Any], status: str, *, hard_blocks: list[str] | None = None,
                    plan: dict[str, Any] | None = None, runtime: dict[str, Any] | None = None,
                    durable_paths: list[str] | None = None) -> dict[str, Any]:
    return {
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": sorted(set(hard_blocks or [])),
        "publication_blocked": False,
        "plan_status": _clean((plan or {}).get("status")) or None,
        "runtime_status": _clean((runtime or {}).get("status")) or None,
        "runtime_results": (runtime or {}).get("results", []) if isinstance((runtime or {}).get("results", []), list) else [],
        "durable_paths": sorted(set(durable_paths or [])),
    }


def _durable_paths(repo_root: Path, channel: dict[str, Any]) -> list[str]:
    paths = [
        metrics_harvest_runtime.expected_checkpoint_state_path(channel),
        observed_metrics_collector.expected_observation_store_path(channel),
        durable_feedback_snapshot.expected_snapshot_path(channel),
    ]
    return [relative for relative in paths if _safe_target(repo_root, relative).exists()]


def evaluate_channel(
    repo_root: Path,
    channel: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = DEFAULT_WINDOWS_HOURS,
    max_publications: int = metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
    persist_bundle_call: PersistBundleCall | None = None,
) -> dict[str, Any]:
    """Evaluate or execute one channel's due observed-metrics work."""
    if not all(isinstance(value, dict) for value in (channel, access_attestation)):
        raise TypeError("channel and access_attestation must be mappings")

    platform = _clean(channel.get("platform")).lower()
    if platform not in native_metrics_transport.META_PROFILES:
        return _channel_result(channel, "SKIP_UNSUPPORTED_NATIVE_METRICS_TRANSPORT")

    policy_blocks: list[str] = []
    if channel.get("zero_paid_dependency") is not True:
        policy_blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        policy_blocks.append("OBSERVED_ONLY_REQUIRED")
    if policy_blocks:
        return _channel_result(channel, "HOLD_CHANNEL_POLICY", hard_blocks=policy_blocks)

    try:
        catalog_path = publication_metrics_catalog.expected_catalog_path(channel)
        catalog_target = _safe_target(repo_root, catalog_path)
    except (TypeError, ValueError) as exc:
        return _channel_result(channel, "HOLD_CATALOG_NAMESPACE", hard_blocks=["CATALOG_PATH_INVALID:" + str(exc)])

    if not catalog_target.exists():
        return _channel_result(channel, "NO_AUTHORITATIVE_PUBLICATION_CATALOG")

    try:
        catalog = _load_object(catalog_target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _channel_result(channel, "HOLD_PUBLICATION_CATALOG", hard_blocks=["CATALOG_READ_INVALID:" + str(exc)])

    checked_catalog = publication_metrics_catalog.validate_catalog(channel, catalog)
    if checked_catalog.get("valid") is not True:
        return _channel_result(channel, "HOLD_PUBLICATION_CATALOG", hard_blocks=list(checked_catalog.get("hard_blocks", [])))

    try:
        observation_path = observed_metrics_collector.expected_observation_store_path(channel)
        observation_store = _load_optional(repo_root, observation_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return _channel_result(channel, "HOLD_OBSERVATION_STORE", hard_blocks=["OBSERVATION_STORE_READ_INVALID:" + str(exc)])

    plan = metrics_harvest_scheduler.plan_harvest(
        channel,
        catalog,
        access_attestation,
        now=now,
        observation_store=observation_store,
        windows_hours=windows_hours,
        max_publications=max_publications,
    )
    if plan.get("status") == "NO_HARVEST_DUE":
        return _channel_result(channel, "NO_HARVEST_DUE", plan=plan, durable_paths=_durable_paths(repo_root, channel))
    if plan.get("status") != "HARVEST_READY":
        return _channel_result(channel, "HOLD_HARVEST_PLAN", hard_blocks=list(plan.get("hard_blocks", [])), plan=plan)
    if not execute:
        return _channel_result(channel, "HARVEST_READY", plan=plan, durable_paths=_durable_paths(repo_root, channel))

    kwargs: dict[str, Any] = {}
    if credential_resolver is not None:
        kwargs["credential_resolver"] = credential_resolver
    if transport_call is not None:
        kwargs["transport_call"] = transport_call
    if persist_bundle_call is not None:
        kwargs["persist_bundle_call"] = persist_bundle_call

    runtime = metrics_harvest_runtime.execute_plan_durably(
        plan,
        channel,
        access_attestation,
        repo_root=repo_root,
        now=now,
        **kwargs,
    )
    if runtime.get("status") != "HARVEST_RUNTIME_EXECUTED":
        return _channel_result(
            channel,
            "HOLD_HARVEST_RUNTIME",
            hard_blocks=list(runtime.get("hard_blocks", [])),
            plan=plan,
            runtime=runtime,
            durable_paths=_durable_paths(repo_root, channel),
        )
    return _channel_result(
        channel,
        "HARVEST_EXECUTED",
        plan=plan,
        runtime=runtime,
        durable_paths=_durable_paths(repo_root, channel),
    )


def run_trigger(
    repo_root: Path,
    channel_paths: list[Path],
    access_attestation_path: Path,
    *,
    now: str,
    execute: bool = False,
    windows_hours: tuple[int, ...] = DEFAULT_WINDOWS_HOURS,
    max_publications: int = metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
    persist_bundle_call: PersistBundleCall | None = None,
) -> dict[str, Any]:
    if not channel_paths:
        raise ValueError("at least one channel path is required")
    attestation = _load_object(access_attestation_path)
    results: list[dict[str, Any]] = []
    for path in channel_paths:
        channel = _load_object(path)
        results.append(evaluate_channel(
            repo_root,
            channel,
            attestation,
            now=now,
            execute=execute,
            windows_hours=windows_hours,
            max_publications=max_publications,
            credential_resolver=credential_resolver,
            transport_call=transport_call,
            persist_bundle_call=persist_bundle_call,
        ))

    hard_blocks = sorted({code for result in results for code in result.get("hard_blocks", [])})
    holds = [result for result in results if _clean(result.get("status")).startswith("HOLD_")]
    executed = [result for result in results if result.get("status") == "HARVEST_EXECUTED"]
    ready = [result for result in results if result.get("status") == "HARVEST_READY"]
    if holds:
        status = "TRIGGER_PARTIAL_HOLD" if len(holds) < len(results) else "TRIGGER_HOLD"
    elif execute and executed:
        status = "TRIGGER_EXECUTED"
    elif not execute and ready:
        status = "TRIGGER_HARVEST_READY"
    else:
        status = "TRIGGER_IDLE"

    durable_paths = sorted({path for result in results for path in result.get("durable_paths", [])})
    return {
        "schema_version": SCHEMA_VERSION,
        "trigger_id": TRIGGER_ID,
        "status": status,
        "hard_blocks": hard_blocks,
        "publication_blocked": False,
        "execute": bool(execute),
        "channels": results,
        "durable_paths": durable_paths,
        "guards": {
            "analytics_advisory_only": True,
            "publication_blocked_by_analytics": False,
            "legacy_descriptor_fabrication_allowed": False,
            "credential_values_returned": False,
            "credential_values_persisted": False,
            "raw_provider_payload_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "native_free_transport_only": True,
            "zero_paid_dependency": True,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--channel", type=Path, action="append", required=True)
    parser.add_argument("--access-attestation", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    windows = tuple(int(item.strip()) for item in args.windows_hours.split(",") if item.strip())
    result = run_trigger(
        args.repo_root,
        args.channel,
        args.access_attestation,
        now=args.now,
        execute=args.execute,
        windows_hours=windows,
        max_publications=args.max_publications,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] in {"TRIGGER_HOLD", "TRIGGER_PARTIAL_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
