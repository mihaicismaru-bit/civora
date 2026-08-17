#!/usr/bin/env python3
"""Operational trigger for LOCAL NEWS OS observed-metrics harvest.

This layer connects already-persisted, authoritative publication metrics catalogs to
``metrics_harvest_scheduler`` and ``metrics_harvest_runtime``. It deliberately does
not infer descriptors from legacy publication state and never participates in the
editorial publication critical path.

Safety properties:
- only sealed channel-local publication metrics catalogs are consumed;
- a missing catalog is a clean no-op, never a legacy backfill request;
- only CHANNEL_CONFIG-declared observed/native/free transports are eligible;
- credentials are resolved only by the existing metrics runtime at its network boundary;
- channel failures are isolated and always report ``publication_blocked=false``;
- checkpoint/observation/snapshot persistence remains delegated to the existing
  crash-safe runtime and collector;
- no predictive analytics, paid dependency, cross-channel state, or publication
  mutation is introduced here.
"""
from __future__ import annotations

import argparse
import hashlib
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
TRIGGER_ID = "local-news-os-operational-metrics-harvest"
SUPPORTED_PLATFORMS = frozenset(native_metrics_transport.META_PROFILES)

CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_target(repo_root: Path, relative: str) -> Path:
    path = PurePosixPath(_clean(relative).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("unsafe operational metrics path")
    return repo_root.joinpath(*path.parts)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_optional(repo_root: Path, relative: str) -> dict[str, Any] | None:
    target = _safe_target(repo_root, relative)
    if not target.exists():
        return None
    return _load_object(target)


def runtime_paths(channel: dict[str, Any]) -> dict[str, str]:
    """Return only channel-derived durable analytics paths."""
    return {
        "catalog": publication_metrics_catalog.expected_catalog_path(channel),
        "checkpoint": metrics_harvest_runtime.expected_checkpoint_state_path(channel),
        "observations": observed_metrics_collector.expected_observation_store_path(channel),
        "feedback_snapshot": durable_feedback_snapshot.expected_snapshot_path(channel),
    }


def _base_result(channel: dict[str, Any], status: str, *, hard_blocks: list[str] | None = None) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "trigger_id": TRIGGER_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": sorted(set(hard_blocks or [])),
        "publication_blocked": False,
        "legacy_backfill_attempted": False,
        "plan": None,
        "runtime": None,
        "durable_paths": None,
        "guards": {
            "authoritative_catalog_required": True,
            "legacy_descriptor_fabrication_allowed": False,
            "analytics_advisory_only": True,
            "credential_values_returned": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "publication_state_mutated": False,
            "cross_channel_state": False,
            "zero_paid_dependency": True,
        },
    }
    result["trigger_fingerprint_sha256"] = _digest(result)
    return result


def _finish(result: dict[str, Any]) -> dict[str, Any]:
    result = _clone(result)
    result.pop("trigger_fingerprint_sha256", None)
    result["trigger_fingerprint_sha256"] = _digest(result)
    return result


def run_channel(
    channel: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    repo_root: Path,
    now: str,
    execute: bool = True,
    windows_hours: Any = None,
    max_publications: int = metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
) -> dict[str, Any]:
    """Plan and optionally execute one channel's due observed-metrics harvest."""
    if not isinstance(channel, dict) or not isinstance(access_attestation, dict):
        raise TypeError("channel and access_attestation must be mappings")

    platform = _clean(channel.get("platform")).lower()
    policy_blocks: list[str] = []
    if channel.get("zero_paid_dependency") is not True:
        policy_blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        policy_blocks.append("OBSERVED_ONLY_REQUIRED")
    if platform not in SUPPORTED_PLATFORMS:
        policy_blocks.append("UNSUPPORTED_NATIVE_METRICS_CHANNEL")
    if policy_blocks:
        return _base_result(channel, "HOLD_TRIGGER_POLICY", hard_blocks=policy_blocks)

    try:
        paths = runtime_paths(channel)
        catalog_target = _safe_target(repo_root, paths["catalog"])
    except (TypeError, ValueError) as exc:
        return _base_result(channel, "HOLD_TRIGGER_NAMESPACE", hard_blocks=["ANALYTICS_NAMESPACE_INVALID:" + str(exc)])

    if not catalog_target.exists():
        result = _base_result(channel, "NO_AUTHORITATIVE_CATALOG")
        result["durable_paths"] = paths
        return _finish(result)

    try:
        catalog = _load_object(catalog_target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = _base_result(channel, "HOLD_CATALOG", hard_blocks=["CATALOG_READ_INVALID:" + type(exc).__name__])
        result["durable_paths"] = paths
        return _finish(result)

    checked = publication_metrics_catalog.validate_catalog(channel, catalog)
    if checked.get("valid") is not True:
        result = _base_result(channel, "HOLD_CATALOG", hard_blocks=list(checked.get("hard_blocks", [])))
        result["durable_paths"] = paths
        return _finish(result)

    try:
        observation_store = _load_optional(repo_root, paths["observations"])
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = _base_result(channel, "HOLD_OBSERVATION_STORE", hard_blocks=["OBSERVATION_STORE_READ_INVALID:" + type(exc).__name__])
        result["durable_paths"] = paths
        return _finish(result)

    plan = metrics_harvest_scheduler.plan_harvest(
        channel,
        catalog,
        access_attestation,
        now=now,
        observation_store=observation_store,
        windows_hours=windows_hours,
        max_publications=max_publications,
    )
    result = _base_result(channel, _clean(plan.get("status")) or "HOLD_HARVEST_PLAN", hard_blocks=list(plan.get("hard_blocks", [])))
    result["durable_paths"] = paths
    result["plan"] = plan

    if execute and plan.get("status") == "HARVEST_READY":
        kwargs: dict[str, Any] = {
            "repo_root": repo_root,
            "now": now,
        }
        if credential_resolver is not None:
            kwargs["credential_resolver"] = credential_resolver
        if transport_call is not None:
            kwargs["transport_call"] = transport_call
        runtime = metrics_harvest_runtime.execute_plan_durably(
            plan,
            channel,
            access_attestation,
            **kwargs,
        )
        result["runtime"] = runtime
        result["status"] = _clean(runtime.get("status")) or "HOLD_HARVEST_RUNTIME"
        result["hard_blocks"] = sorted(set(list(result.get("hard_blocks", [])) + list(runtime.get("hard_blocks", []))))

    return _finish(result)


def run_operational_harvest(
    channels: list[dict[str, Any]],
    access_attestation: dict[str, Any],
    *,
    repo_root: Path,
    now: str,
    execute: bool = True,
    windows_hours: Any = None,
    max_publications: int = metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
    credential_resolver: CredentialResolver | None = None,
    transport_call: TransportCall | None = None,
) -> dict[str, Any]:
    """Run isolated harvest planning/execution for a bounded channel set."""
    if not isinstance(channels, list) or not all(isinstance(item, dict) for item in channels):
        raise TypeError("channels must be a list of mappings")
    if not isinstance(access_attestation, dict):
        raise TypeError("access_attestation must be a mapping")

    results: list[dict[str, Any]] = []
    for channel in channels:
        try:
            item = run_channel(
                channel,
                access_attestation,
                repo_root=repo_root,
                now=now,
                execute=execute,
                windows_hours=windows_hours,
                max_publications=max_publications,
                credential_resolver=credential_resolver,
                transport_call=transport_call,
            )
        except Exception as exc:  # isolate analytics faults from sibling publications
            item = _base_result(channel, "HOLD_CHANNEL_EXCEPTION", hard_blocks=["CHANNEL_EXCEPTION:" + type(exc).__name__])
        results.append(item)

    results.sort(key=lambda row: (_clean(row.get("instance_id")), _clean(row.get("channel_id")), _clean(row.get("platform"))))
    holds = [item for item in results if _clean(item.get("status")).startswith("HOLD_")]
    executed = [item for item in results if _clean(item.get("status")) == "HARVEST_RUNTIME_EXECUTED"]
    ready = [item for item in results if _clean((item.get("plan") or {}).get("status")) == "HARVEST_READY"]
    if holds:
        status = "PARTIAL_ANALYTICS_HOLD" if len(holds) < len(results) else "ANALYTICS_HOLD"
    elif executed:
        status = "HARVEST_EXECUTED"
    elif ready and not execute:
        status = "HARVEST_READY"
    else:
        status = "NO_HARVEST_DUE"

    report = {
        "schema_version": SCHEMA_VERSION,
        "trigger_id": TRIGGER_ID,
        "status": status,
        "publication_blocked": False,
        "channels": results,
        "guards": {
            "legacy_backfill_attempted": False,
            "publication_state_mutated": False,
            "analytics_advisory_only": True,
            "credential_values_returned": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "cross_channel_state": False,
            "zero_paid_dependency": True,
        },
    }
    report["report_fingerprint_sha256"] = _digest(report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", action="append", type=Path, required=True, help="CHANNEL_CONFIG JSON; repeat for each channel")
    parser.add_argument("--access-attestation", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    channels = [_load_object(path) for path in args.channel]
    attestation = _load_object(args.access_attestation)
    windows = [int(item.strip()) for item in args.windows_hours.split(",") if item.strip()]
    report = run_operational_harvest(
        channels,
        attestation,
        repo_root=args.repo_root,
        now=args.now,
        execute=args.execute,
        windows_hours=windows,
        max_publications=args.max_publications,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
    print(text, end="")
    return 2 if report.get("status") in {"ANALYTICS_HOLD", "PARTIAL_ANALYTICS_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
