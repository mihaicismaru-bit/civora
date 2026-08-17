#!/usr/bin/env python3
"""Fleet-level pre-harvest reconciliation for authorization-sealed metrics recovery.

This boundary scans only CIVORA instances/canals already present in the sealed
observed-metrics plan. Before the normal harvest workflow runs, it inspects durable
checkpoint state for RECOVERY_REQUIRED entries and attempts one safe action only:
complete the checkpoint from already-persisted observed-metrics evidence.

It never authorizes a provider re-read, never resolves credential values, and never
performs a network request. If durable evidence is absent, the checkpoint remains
RECOVERY_REQUIRED. The existing authorization-sealed claim path therefore continues
to refuse blind retry during the later normal harvest.

This makes recovery fleet-operational without creating a second analytics transport
path or weakening editorial publication gates.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_harvest_recovery as recovery
import fleet_metrics_authorization_seal as authorization_seal
import metrics_harvest_runtime as runtime
import native_metrics_transport
import observed_metrics_collector as collector
import publication_metrics_catalog as catalog

SCHEMA_VERSION = "1.0"
ORCHESTRATOR_ID = "local-news-os-fleet-harvest-recovery-orchestrator"

BuildSealedPlan = Callable[..., tuple[dict[str, Any], dict[str, Any]]]


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


def _target(repo_root: Path, relative: str) -> Path:
    safe = _safe_rel(relative)
    if not safe:
        raise ValueError("unsafe repository-relative path")
    return repo_root.joinpath(*PurePosixPath(safe).parts)


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _guards() -> dict[str, Any]:
    return {
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "provider_reread_authorized_automatically": False,
        "recovery_runs_before_normal_harvest": True,
        "sealed_authorization_required": True,
        "durable_observation_required_for_automatic_completion": True,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _channel_hold(channel: dict[str, Any], status: str, blocks: list[str]) -> dict[str, Any]:
    return {
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": sorted(set(blocks)),
        "recovery_required_count": 0,
        "recovered_count": 0,
        "unresolved_count": 0,
        "publication_blocked": False,
        "durable_paths": [],
        "results": [],
    }


def _catalog_publication(
    channel: dict[str, Any], publication_id: str, publication_catalog: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    checked = catalog.validate_catalog(channel, publication_catalog)
    if checked.get("valid") is not True:
        return None, ["RECOVERY_CATALOG:" + str(code) for code in checked.get("hard_blocks", [])]
    records = publication_catalog.get("records")
    if not isinstance(records, dict):
        return None, ["RECOVERY_CATALOG_RECORDS_INVALID"]
    publication = records.get(publication_id)
    if not isinstance(publication, dict):
        return None, ["RECOVERY_PUBLICATION_DESCRIPTOR_MISSING"]
    descriptor_check = collector.validate_publication_descriptor(channel, publication)
    if descriptor_check.get("valid") is not True:
        return None, ["RECOVERY_PUBLICATION_DESCRIPTOR:" + str(code) for code in descriptor_check.get("hard_blocks", [])]
    return json.loads(json.dumps(publication, ensure_ascii=False)), []


def _synthetic_job(
    channel: dict[str, Any], entry: dict[str, Any], publication: dict[str, Any]
) -> tuple[dict[str, Any] | None, list[str]]:
    blocks: list[str] = []
    if _clean(entry.get("publication_id")) != _clean(publication.get("publication_id")):
        blocks.append("RECOVERY_ENTRY_PUBLICATION_ID_MISMATCH")
    if _clean(entry.get("remote_publication_id")) != _clean(publication.get("remote_publication_id")):
        blocks.append("RECOVERY_ENTRY_REMOTE_PUBLICATION_ID_MISMATCH")
    if _clean(publication.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("RECOVERY_DESCRIPTOR_INSTANCE_MISMATCH")
    if _clean(publication.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("RECOVERY_DESCRIPTOR_CHANNEL_MISMATCH")
    if _clean(publication.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("RECOVERY_DESCRIPTOR_PLATFORM_MISMATCH")
    source = _clean(entry.get("source"))
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    declared_sources = {_clean(value) for value in metrics.get("sources", []) if _clean(value)} if isinstance(metrics.get("sources"), list) else set()
    if source not in declared_sources:
        blocks.append("RECOVERY_ENTRY_SOURCE_NOT_DECLARED")
    checkpoint_hours = entry.get("checkpoint_hours")
    checkpoint_at = _clean(entry.get("checkpoint_at"))
    if checkpoint_hours is None or not checkpoint_at:
        blocks.append("RECOVERY_ENTRY_CHECKPOINT_IDENTITY_INCOMPLETE")
    if blocks:
        return None, sorted(set(blocks))
    job = {
        "publication": publication,
        "publication_id": _clean(entry.get("publication_id")),
        "checkpoint": {
            "checkpoint_hours": checkpoint_hours,
            "checkpoint_at": checkpoint_at,
        },
        "source": source,
    }
    expected_key = _clean(entry.get("checkpoint_key"))
    actual_key = runtime.checkpoint_key(job)
    if not expected_key or actual_key != expected_key:
        return None, ["RECOVERY_CHECKPOINT_KEY_RECONSTRUCTION_MISMATCH"]
    return job, []


def _reconcile_entry(
    repo_root: Path,
    channel: dict[str, Any],
    checkpoint_key: str,
    *,
    authorization_fingerprint: str,
    now: str,
    publication_catalog: dict[str, Any],
    observation_store: dict[str, Any] | None,
    observation_path: str,
) -> dict[str, Any]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_CHECKPOINT_STATE",
            "hard_blocks": state_blocks,
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(checkpoint_key)
    if not isinstance(entry, dict):
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_CHECKPOINT_STATE",
            "hard_blocks": ["RECOVERY_ENTRY_MISSING"],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED":
        return {
            "checkpoint_key": checkpoint_key,
            "status": "RECOVERY_NO_LONGER_REQUIRED",
            "hard_blocks": [],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }

    sealed = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if sealed.get("valid") is not True:
        changed = {
            "SEALED_ENTRY_AUTHORIZATION_CONTEXT_CHANGED",
            "SEALED_RECEIPT_AUTHORIZATION_CONTEXT_CHANGED",
        }
        status = (
            "HOLD_RECOVERY_AUTHORIZATION_CHANGED"
            if changed.intersection(sealed.get("hard_blocks", []))
            else "HOLD_RECOVERY_RECEIPT_TAMPERED"
        )
        return {
            "checkpoint_key": checkpoint_key,
            "status": status,
            "hard_blocks": list(sealed.get("hard_blocks", [])),
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }

    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_RECEIPT_TAMPERED",
            "hard_blocks": ["RECOVERY_REQUIRED_RECEIPT_EXPECTED"],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    if not _clean(latest.get("network_started_at")):
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_RECEIPT_TAMPERED",
            "hard_blocks": ["RECOVERY_NETWORK_START_PROOF_REQUIRED"],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }

    publication, publication_blocks = _catalog_publication(
        channel, _clean(entry.get("publication_id")), publication_catalog
    )
    if publication_blocks or publication is None:
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_PUBLICATION_CATALOG",
            "hard_blocks": publication_blocks or ["RECOVERY_PUBLICATION_DESCRIPTOR_MISSING"],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    job, job_blocks = _synthetic_job(channel, entry, publication)
    if job_blocks or job is None:
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_IDENTITY",
            "hard_blocks": job_blocks or ["RECOVERY_IDENTITY_UNAVAILABLE"],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }

    observation, evidence_blocks, evidence_kind = recovery._covering_observation(
        job, entry, observation_store
    )
    if evidence_blocks:
        return {
            "checkpoint_key": checkpoint_key,
            "status": "HOLD_RECOVERY_OBSERVATION_CONFLICT",
            "hard_blocks": evidence_blocks,
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    if observation is None:
        return {
            "checkpoint_key": checkpoint_key,
            "publication_id": _clean(entry.get("publication_id")) or None,
            "status": "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION",
            "hard_blocks": [],
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }

    evidence = recovery._recovery_evidence(
        kind=evidence_kind or "DURABLE_COVERAGE_OBSERVATION",
        store=observation_store,
        observation=observation,
        checked_at=runtime._iso(runtime._dt(now)),
        provider_reread_authorized=False,
    )
    persisted = recovery._persist_reconciled_state(
        repo_root,
        channel,
        job,
        state,
        previous_fp,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        target_status="COMPLETED",
        evidence=evidence,
    )
    if persisted.get("persisted") is not True:
        return {
            "checkpoint_key": checkpoint_key,
            "status": _clean(persisted.get("status")) or "HOLD_RECOVERY_PERSISTENCE",
            "hard_blocks": list(persisted.get("hard_blocks", [])),
            "provider_reread_authorized": False,
            "publication_blocked": False,
        }
    return {
        "checkpoint_key": checkpoint_key,
        "publication_id": _clean(entry.get("publication_id")) or None,
        "status": "RECOVERED_COMPLETED",
        "hard_blocks": [],
        "recovery_evidence": evidence,
        "provider_reread_authorized": False,
        "publication_blocked": False,
        "durable_paths": sorted(
            set(
                [runtime.expected_checkpoint_state_path(channel)]
                + ([observation_path] if observation_path else [])
            )
        ),
    }


def reconcile_channel_recoveries(
    repo_root: Path,
    channel: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    """Reconcile all sealed RECOVERY_REQUIRED checkpoints for one channel."""
    if not isinstance(channel, dict):
        raise TypeError("channel must be a mapping")
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _channel_hold(
            channel, "HOLD_RECOVERY_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"]
        )
    try:
        runtime._dt(now)
    except ValueError:
        return _channel_hold(channel, "HOLD_RECOVERY_TIME", ["RECOVERY_NOW_INVALID"])
    if channel.get("zero_paid_dependency") is not True:
        return _channel_hold(
            channel, "HOLD_RECOVERY_POLICY", ["ZERO_PAID_DEPENDENCY_VIOLATION"]
        )
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        return _channel_hold(
            channel, "HOLD_RECOVERY_POLICY", ["RECOVERY_OBSERVED_ONLY_REQUIRED"]
        )

    state, state_blocks, existed = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return _channel_hold(channel, "HOLD_RECOVERY_CHECKPOINT_STATE", state_blocks)
    if not existed:
        result = _channel_hold(channel, "NO_RECOVERY_REQUIRED", [])
        result["hard_blocks"] = []
        return result

    recovery_keys = sorted(
        key
        for key, entry in state.get("entries", {}).items()
        if isinstance(entry, dict) and _clean(entry.get("status")).upper() == "RECOVERY_REQUIRED"
    )
    if not recovery_keys:
        result = _channel_hold(channel, "NO_RECOVERY_REQUIRED", [])
        result["hard_blocks"] = []
        result["durable_paths"] = [runtime.expected_checkpoint_state_path(channel)]
        return result

    try:
        catalog_path = catalog.expected_catalog_path(channel)
        publication_catalog = _load_object(_target(repo_root, catalog_path))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = _channel_hold(
            channel,
            "HOLD_RECOVERY_PUBLICATION_CATALOG",
            [f"RECOVERY_CATALOG_UNAVAILABLE:{type(exc).__name__}"],
        )
        result["recovery_required_count"] = len(recovery_keys)
        return result
    checked_catalog = catalog.validate_catalog(channel, publication_catalog)
    if checked_catalog.get("valid") is not True:
        result = _channel_hold(
            channel,
            "HOLD_RECOVERY_PUBLICATION_CATALOG",
            ["RECOVERY_CATALOG:" + str(code) for code in checked_catalog.get("hard_blocks", [])],
        )
        result["recovery_required_count"] = len(recovery_keys)
        return result

    observation_path = ""
    observation_store: dict[str, Any] | None = None
    try:
        observation_path = collector.expected_observation_store_path(channel)
        observation_target = _target(repo_root, observation_path)
        if observation_target.exists():
            observation_store = _load_object(observation_target)
            checked_store = collector.validate_observation_store(channel, observation_store)
            if checked_store.get("valid") is not True:
                result = _channel_hold(
                    channel,
                    "HOLD_RECOVERY_OBSERVATION_LEDGER",
                    ["RECOVERY_OBSERVATION_STORE:" + str(code) for code in checked_store.get("hard_blocks", [])],
                )
                result["recovery_required_count"] = len(recovery_keys)
                return result
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        result = _channel_hold(
            channel,
            "HOLD_RECOVERY_OBSERVATION_LEDGER",
            [f"RECOVERY_OBSERVATION_STORE_UNAVAILABLE:{type(exc).__name__}"],
        )
        result["recovery_required_count"] = len(recovery_keys)
        return result

    rows: list[dict[str, Any]] = []
    durable_paths = {runtime.expected_checkpoint_state_path(channel)}
    if observation_store is not None and observation_path:
        durable_paths.add(observation_path)
    for key in recovery_keys:
        row = _reconcile_entry(
            repo_root,
            channel,
            key,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            publication_catalog=publication_catalog,
            observation_store=observation_store,
            observation_path=observation_path,
        )
        rows.append(row)
        durable_paths.update(row.get("durable_paths", []))

    recovered = sum(row.get("status") == "RECOVERED_COMPLETED" for row in rows)
    unresolved = sum(row.get("status") == "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION" for row in rows)
    holds = [row for row in rows if _clean(row.get("status")).startswith("HOLD_")]
    if holds:
        status = "RECOVERY_PARTIAL_HOLD" if len(holds) < len(rows) else "RECOVERY_HOLD"
    elif unresolved:
        status = "RECOVERY_PARTIAL" if recovered else "RECOVERY_UNRESOLVED"
    elif recovered:
        status = "RECOVERY_RECONCILED"
    else:
        status = "NO_RECOVERY_REQUIRED"

    return {
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": sorted(
            {code for row in rows for code in row.get("hard_blocks", [])}
        ),
        "recovery_required_count": len(recovery_keys),
        "recovered_count": recovered,
        "unresolved_count": unresolved,
        "publication_blocked": False,
        "provider_reread_authorized": False,
        "durable_paths": sorted(durable_paths),
        "results": rows,
    }


def _iter_instance_channels(
    repo_root: Path, instance: dict[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    instance_id = _clean(instance.get("instance_id")).lower()
    instance_root = _safe_rel(instance.get("instance_root"))
    registry_rel = _safe_rel(instance.get("channel_registry"))
    if not instance_id or not instance_root or not registry_rel:
        return [], ["INVALID_INSTANCE_DISCOVERY_METADATA"]
    if not _within(registry_rel, instance_root):
        return [], ["CHANNEL_REGISTRY_OUTSIDE_INSTANCE"]
    try:
        registry = _load_object(_target(repo_root, registry_rel))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [], [f"CHANNEL_REGISTRY_UNAVAILABLE:{type(exc).__name__}"]
    if _clean(registry.get("instance_id")).lower() != instance_id:
        return [], ["CHANNEL_REGISTRY_INSTANCE_MISMATCH"]

    rows: list[dict[str, Any]] = []
    blocks: list[str] = []
    channels = registry.get("channels") if isinstance(registry.get("channels"), list) else []
    for item in sorted(
        (value for value in channels if isinstance(value, dict)),
        key=lambda value: _clean(value.get("channel_id")),
    ):
        config_rel = _safe_rel(item.get("config"))
        if not config_rel or not _within(config_rel, instance_root):
            blocks.append("CHANNEL_CONFIG_OUTSIDE_INSTANCE")
            continue
        try:
            channel = _load_object(_target(repo_root, config_rel))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            blocks.append(f"CHANNEL_CONFIG_UNAVAILABLE:{type(exc).__name__}")
            continue
        if _clean(channel.get("instance_id")).lower() != instance_id:
            blocks.append("CHANNEL_INSTANCE_MISMATCH")
            continue
        platform = _clean(channel.get("platform")).lower()
        if platform not in native_metrics_transport.META_PROFILES:
            continue
        metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
        if metrics.get("observed_only") is not True:
            blocks.append("RECOVERY_OBSERVED_ONLY_REQUIRED")
            continue
        if channel.get("zero_paid_dependency") is not True:
            blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
            continue
        try:
            checkpoint_path = runtime.expected_checkpoint_state_path(channel)
        except (TypeError, ValueError):
            blocks.append("RECOVERY_CHECKPOINT_PATH_INVALID")
            continue
        if not _within(_safe_rel(checkpoint_path), instance_root):
            blocks.append("RECOVERY_CHECKPOINT_OUTSIDE_INSTANCE")
            continue
        rows.append(channel)
    return rows, sorted(set(blocks))


def reconcile_fleet_from_plan(
    repo_root: Path,
    runtime_registry: dict[str, Any],
    sealed_plan: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    """Reconcile current sealed fleet recoveries without provider I/O."""
    if not isinstance(runtime_registry, dict) or not isinstance(sealed_plan, dict):
        raise TypeError("runtime_registry and sealed_plan must be mappings")
    try:
        runtime._dt(now)
    except ValueError:
        return {
            "schema_version": SCHEMA_VERSION,
            "orchestrator_id": ORCHESTRATOR_ID,
            "status": "FLEET_RECOVERY_HOLD",
            "hard_blocks": ["RECOVERY_NOW_INVALID"],
            "publication_blocked": False,
            "instances": [],
            "channels": [],
            "durable_paths": [],
            "guards": _guards(),
        }

    if sealed_plan.get("authorization_seal_status") not in {
        "AUTHORIZATION_SEAL_READY",
        "AUTHORIZATION_SEAL_IDLE",
    }:
        return {
            "schema_version": SCHEMA_VERSION,
            "orchestrator_id": ORCHESTRATOR_ID,
            "status": "FLEET_RECOVERY_HOLD",
            "hard_blocks": ["SEALED_AUTHORIZATION_PLAN_REQUIRED"],
            "publication_blocked": False,
            "instances": [],
            "channels": [],
            "durable_paths": [],
            "guards": _guards(),
        }

    instances = {
        _clean(row.get("instance_id")).lower(): row
        for row in runtime_registry.get("instances", [])
        if isinstance(row, dict) and _clean(row.get("instance_id"))
    } if isinstance(runtime_registry.get("instances"), list) else {}
    matrix = sealed_plan.get("workflow_matrix") if isinstance(sealed_plan.get("workflow_matrix"), list) else []
    channel_rows: list[dict[str, Any]] = []
    instance_rows: list[dict[str, Any]] = []
    hard_blocks: list[str] = []

    for binding_row in sorted(
        (row for row in matrix if isinstance(row, dict)),
        key=lambda row: (_clean(row.get("instance_id")), _clean(row.get("binding_id"))),
    ):
        instance_id = _clean(binding_row.get("instance_id")).lower()
        fingerprint = _clean(binding_row.get("authorization_fingerprint"))
        instance = instances.get(instance_id)
        summary = {
            "instance_id": instance_id or None,
            "binding_id": _clean(binding_row.get("binding_id")) or None,
            "status": "NO_RECOVERY_REQUIRED",
            "recovered_count": 0,
            "unresolved_count": 0,
            "held_count": 0,
        }
        if instance is None:
            hard_blocks.append("BOUND_INSTANCE_NOT_FOUND:" + (instance_id or "MISSING"))
            summary["status"] = "RECOVERY_HOLD"
            summary["held_count"] = 1
            instance_rows.append(summary)
            continue
        if not receipt._valid_authorization_fingerprint(fingerprint):
            hard_blocks.append("BOUND_AUTHORIZATION_FINGERPRINT_INVALID:" + instance_id)
            summary["status"] = "RECOVERY_HOLD"
            summary["held_count"] = 1
            instance_rows.append(summary)
            continue

        channels, discovery_blocks = _iter_instance_channels(repo_root, instance)
        if discovery_blocks:
            hard_blocks.extend(f"{instance_id}:{code}" for code in discovery_blocks)
        for channel in channels:
            row = reconcile_channel_recoveries(
                repo_root,
                channel,
                authorization_fingerprint=fingerprint,
                now=now,
            )
            channel_rows.append(row)
            summary["recovered_count"] += int(row.get("recovered_count") or 0)
            summary["unresolved_count"] += int(row.get("unresolved_count") or 0)
            if _clean(row.get("status")).endswith("HOLD") or _clean(row.get("status")).startswith("HOLD_"):
                summary["held_count"] += 1
            hard_blocks.extend(
                f"{instance_id}:{_clean(channel.get('channel_id'))}:{code}"
                for code in row.get("hard_blocks", [])
            )
        if summary["held_count"]:
            summary["status"] = "RECOVERY_PARTIAL_HOLD"
        elif summary["unresolved_count"]:
            summary["status"] = "RECOVERY_UNRESOLVED"
        elif summary["recovered_count"]:
            summary["status"] = "RECOVERY_RECONCILED"
        instance_rows.append(summary)

    recovered_total = sum(int(row.get("recovered_count") or 0) for row in channel_rows)
    unresolved_total = sum(int(row.get("unresolved_count") or 0) for row in channel_rows)
    holds = [
        row for row in channel_rows
        if "HOLD" in _clean(row.get("status"))
    ]
    if hard_blocks or holds:
        status = "FLEET_RECOVERY_PARTIAL_HOLD" if channel_rows else "FLEET_RECOVERY_HOLD"
    elif unresolved_total:
        status = "FLEET_RECOVERY_UNRESOLVED"
    elif recovered_total:
        status = "FLEET_RECOVERY_RECONCILED"
    else:
        status = "FLEET_RECOVERY_IDLE"

    return {
        "schema_version": SCHEMA_VERSION,
        "orchestrator_id": ORCHESTRATOR_ID,
        "status": status,
        "hard_blocks": sorted(set(hard_blocks)),
        "publication_blocked": False,
        "instances": instance_rows,
        "channels": channel_rows,
        "recovered_count": recovered_total,
        "unresolved_count": unresolved_total,
        "provider_reread_authorized": False,
        "durable_paths": sorted(
            {path for row in channel_rows for path in row.get("durable_paths", [])}
        ),
        "guards": _guards(),
    }


def run_fleet_recovery(
    repo_root: Path,
    runtime_registry_path: Path = authorization_seal.DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = authorization_seal.DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = authorization_seal.DEFAULT_CAPABILITY_REGISTRY,
    *,
    now: str,
    build_sealed_plan_call: BuildSealedPlan = authorization_seal.build_sealed_plan,
) -> dict[str, Any]:
    """Build the current secret-free authorization plan and reconcile fleet state."""
    root = repo_root.resolve()
    sealed_plan, runtime_registry = build_sealed_plan_call(
        root,
        runtime_registry_path,
        binding_registry_path,
        capability_registry_path,
        now=now,
    )
    result = reconcile_fleet_from_plan(root, runtime_registry, sealed_plan, now=now)
    result["authorization_seal_status"] = sealed_plan.get("authorization_seal_status")
    result["publication_blocked"] = False
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--runtime-registry", type=Path, default=authorization_seal.DEFAULT_RUNTIME_REGISTRY)
    parser.add_argument("--binding-registry", type=Path, default=authorization_seal.DEFAULT_BINDING_REGISTRY)
    parser.add_argument("--capability-registry", type=Path, default=authorization_seal.DEFAULT_CAPABILITY_REGISTRY)
    parser.add_argument("--now", required=True)
    args = parser.parse_args()
    result = run_fleet_recovery(
        args.repo_root,
        args.runtime_registry,
        args.binding_registry,
        args.capability_registry,
        now=args.now,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if result["status"] in {"FLEET_RECOVERY_HOLD", "FLEET_RECOVERY_PARTIAL_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
