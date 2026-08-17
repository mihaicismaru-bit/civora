#!/usr/bin/env python3
"""Route explicit provider re-read crash recovery before generic fleet recovery.

The generic fleet recovery boundary is intentionally able to close an ambiguous metrics
checkpoint from a covering observed-metrics row. That rule is correct for normal sealed
harvest attempts, but it is too weak after an *explicit provider re-read*: those attempts
also carry a single-use handoff, reclaim provenance, a SPENT record and an exact durable
materialization contract (including feedback snapshot read-back when required).

This operational router installs one narrow dispatch rule around the existing fleet
orchestrator. RECOVERY_REQUIRED entries that carry explicit re-read provenance are routed
only through ``reread_materialization_crash_reconciliation``. They can never fall through
to generic ``covering_observation`` recovery. Normal sealed recoveries are delegated to the
existing orchestrator unchanged.

The router reconstructs the original secret-free scheduler job from durable publication,
checkpoint, receipt and channel metadata and requires its SHA-256 to equal the job
fingerprint already sealed into the checkpoint/receipt lineage. Reconstruction failure is
fail-closed and never enables generic fallback or a provider read.
"""
from __future__ import annotations

import argparse
import json
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import fleet_metrics_authorization_seal as authorization_seal
import fleet_metrics_recovery_orchestrator as generic
import metrics_harvest_runtime as runtime
import metrics_harvest_scheduler as scheduler
import native_metrics_transport
import reread_materialization_crash_reconciliation as reread_recovery

SCHEMA_VERSION = "1.0"
ROUTER_ID = "local-news-os-fleet-reread-materialization-recovery-routing-v1"
ROUTE_EXPLICIT = "EXPLICIT_REREAD_DURABLE_MATERIALIZATION"
ROUTE_GENERIC = "GENERIC_SEALED_RECOVERY"

_BASE_RECONCILE_ENTRY: Callable[..., dict[str, Any]] = generic._reconcile_entry


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _guards() -> dict[str, Any]:
    value = dict(generic._guards())
    value.update(
        {
            "explicit_reread_materialization_recovery_routed_before_generic": True,
            "generic_covering_observation_allowed_for_explicit_reread": False,
            "explicit_reread_job_reconstruction_must_match_sealed_fingerprint": True,
            "provider_reread_authorized_by_router": False,
            "provider_network_calls_performed_by_router": False,
        }
    )
    return value


def _prior_observed_at(
    observation_store: dict[str, Any] | None,
    *,
    publication_id: str,
    source: str,
    checkpoint_at: str,
) -> str | None:
    if not isinstance(observation_store, dict):
        return None
    try:
        checkpoint_dt = runtime._dt(checkpoint_at)
    except ValueError:
        return None
    values = []
    for row in observation_store.get("observations", []):
        if not isinstance(row, dict):
            continue
        if _clean(row.get("publication_id")) != publication_id:
            continue
        if _clean(row.get("source")) != source:
            continue
        try:
            observed = runtime._dt(_clean(row.get("observed_at")))
        except ValueError:
            continue
        # A materialization written by the ambiguous/re-read attempt cannot have been
        # scheduler input for this already-sealed checkpoint. Only earlier observations
        # are eligible to reconstruct latest_observed_at.
        if observed < checkpoint_dt:
            values.append(observed)
    if not values:
        return None
    return runtime._iso(max(values))


def _reconstruct_sealed_job(
    channel: dict[str, Any],
    entry: dict[str, Any],
    publication: dict[str, Any],
    observation_store: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[str]]:
    """Rebuild the original secret-free scheduler job and verify its sealed digest."""
    blocks: list[str] = []
    platform = _clean(channel.get("platform")).lower()
    profile = native_metrics_transport.META_PROFILES.get(platform)
    if not isinstance(profile, dict):
        blocks.append("REREAD_ROUTE_UNSUPPORTED_NATIVE_METRICS_TRANSPORT")
    source = _clean(entry.get("source"))
    if isinstance(profile, dict) and source != _clean(profile.get("source")):
        blocks.append("REREAD_ROUTE_METRIC_SOURCE_MISMATCH")
    publication_id = _clean(entry.get("publication_id"))
    if publication_id != _clean(publication.get("publication_id")):
        blocks.append("REREAD_ROUTE_PUBLICATION_ID_MISMATCH")
    if _clean(entry.get("remote_publication_id")) != _clean(publication.get("remote_publication_id")):
        blocks.append("REREAD_ROUTE_REMOTE_PUBLICATION_ID_MISMATCH")

    try:
        checkpoint_hours = int(entry.get("checkpoint_hours"))
        checkpoint_at = runtime._iso(runtime._dt(_clean(entry.get("checkpoint_at"))))
        published_at = runtime._dt(_clean(publication.get("published_at")))
    except (TypeError, ValueError):
        blocks.append("REREAD_ROUTE_CHECKPOINT_IDENTITY_INVALID")
        return None, sorted(set(blocks))
    if checkpoint_hours not in scheduler.DEFAULT_WINDOWS_HOURS:
        blocks.append("REREAD_ROUTE_CHECKPOINT_WINDOW_NOT_CANONICAL")

    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    first = receipts[0] if receipts and isinstance(receipts[0], dict) else None
    if not isinstance(first, dict):
        blocks.append("REREAD_ROUTE_ORIGINAL_RECEIPT_REQUIRED")
        return None, sorted(set(blocks))
    try:
        original_claimed = runtime._dt(_clean(first.get("claimed_at")))
        checkpoint_dt = runtime._dt(checkpoint_at)
    except ValueError:
        blocks.append("REREAD_ROUTE_ORIGINAL_CLAIM_TIME_INVALID")
        return None, sorted(set(blocks))
    overdue_seconds = max(0, int((original_claimed - checkpoint_dt).total_seconds()))

    # Scheduler covered windows are a deterministic function of publication time and
    # checkpoint target. Preserve the scheduler's canonical ordering.
    covered: list[int] = []
    checkpoint_target = runtime._dt(checkpoint_at)
    for hours in scheduler.DEFAULT_WINDOWS_HOURS:
        if published_at + timedelta(hours=hours) <= checkpoint_target:
            covered.append(hours)
    if not covered or covered[-1] != checkpoint_hours:
        blocks.append("REREAD_ROUTE_COVERED_WINDOWS_RECONSTRUCTION_MISMATCH")

    try:
        credential_env_name = native_metrics_transport.credential_env_name(channel.get("credentials_ref"))
    except ValueError:
        credential_env_name = ""
        blocks.append("REREAD_ROUTE_CREDENTIAL_REFERENCE_INVALID")

    if blocks:
        return None, sorted(set(blocks))

    checkpoint = {
        "checkpoint_hours": checkpoint_hours,
        "checkpoint_at": checkpoint_at,
        "covered_checkpoints_hours": covered,
        "latest_observed_at": _prior_observed_at(
            observation_store,
            publication_id=publication_id,
            source=source,
            checkpoint_at=checkpoint_at,
        ),
        "overdue_seconds": overdue_seconds,
    }
    job: dict[str, Any] = {
        "publication": _clone(publication),
        "publication_id": publication_id,
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "checkpoint": checkpoint,
        "source": source,
        "credential_env_name": credential_env_name,
        "graph_version": native_metrics_transport.DEFAULT_GRAPH_VERSION,
        "metric_candidates": list(profile.get("metric_candidates", ())),
        "network_boundary": "native_free_api",
    }
    computed = runtime._digest(job)
    sealed = _clean(entry.get("job_fingerprint_sha256"))
    if not sealed or computed != sealed:
        return None, ["REREAD_ROUTE_SEALED_JOB_FINGERPRINT_RECONSTRUCTION_MISMATCH"]
    job["job_fingerprint_sha256"] = computed
    if runtime.checkpoint_key(job) != _clean(entry.get("checkpoint_key")):
        return None, ["REREAD_ROUTE_CHECKPOINT_KEY_RECONSTRUCTION_MISMATCH"]
    return job, []


def _explicit_result(
    checkpoint_key: str,
    entry: dict[str, Any],
    strict: dict[str, Any],
) -> dict[str, Any]:
    strict_status = _clean(strict.get("status"))
    if strict_status == "RECOVERED_COMPLETED_FROM_DURABLE_MATERIALIZATION":
        status = "RECOVERED_COMPLETED"
    elif strict_status == "RECOVERY_REQUIRED_NO_DURABLE_MATERIALIZATION":
        # Keep the generic aggregate contract while preserving the stricter status.
        status = "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION"
    elif strict_status == "ALREADY_COMPLETED":
        status = "RECOVERY_NO_LONGER_REQUIRED"
    elif strict_status.startswith("HOLD_"):
        status = strict_status
    else:
        status = "HOLD_RECOVERY_REREAD_ROUTE_INCONSISTENT"
    return {
        "checkpoint_key": checkpoint_key,
        "publication_id": _clean(entry.get("publication_id")) or None,
        "status": status,
        "hard_blocks": list(strict.get("hard_blocks", []))
        if status != "HOLD_RECOVERY_REREAD_ROUTE_INCONSISTENT"
        else ["REREAD_ROUTE_UNEXPECTED_STRICT_RECOVERY_STATUS:" + (strict_status or "MISSING")],
        "recovery_route": ROUTE_EXPLICIT,
        "strict_recovery_status": strict_status or None,
        "recovery_evidence": _clone(strict.get("recovery_evidence"))
        if isinstance(strict.get("recovery_evidence"), dict)
        else None,
        "provider_reread_authorized": False,
        "provider_network_call_performed": False,
        "publication_blocked": False,
        "durable_paths": list(strict.get("durable_paths", [])),
    }


def _routed_reconcile_entry(
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
        return _BASE_RECONCILE_ENTRY(
            repo_root,
            channel,
            checkpoint_key,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            publication_catalog=publication_catalog,
            observation_store=observation_store,
            observation_path=observation_path,
        )
    entry = state.get("entries", {}).get(checkpoint_key)
    if not isinstance(entry, dict) or not reread_recovery.is_explicit_reread_recovery(entry):
        result = _BASE_RECONCILE_ENTRY(
            repo_root,
            channel,
            checkpoint_key,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            publication_catalog=publication_catalog,
            observation_store=observation_store,
            observation_path=observation_path,
        )
        if isinstance(result, dict):
            result = _clone(result)
            result.setdefault("recovery_route", ROUTE_GENERIC)
        return result

    publication, publication_blocks = generic._catalog_publication(
        channel, _clean(entry.get("publication_id")), publication_catalog
    )
    if publication_blocks or publication is None:
        return {
            "checkpoint_key": checkpoint_key,
            "publication_id": _clean(entry.get("publication_id")) or None,
            "status": "HOLD_RECOVERY_PUBLICATION_CATALOG",
            "hard_blocks": publication_blocks or ["RECOVERY_PUBLICATION_DESCRIPTOR_MISSING"],
            "recovery_route": ROUTE_EXPLICIT,
            "provider_reread_authorized": False,
            "provider_network_call_performed": False,
            "publication_blocked": False,
            "durable_paths": [],
        }
    job, reconstruction_blocks = _reconstruct_sealed_job(
        channel, entry, publication, observation_store
    )
    if reconstruction_blocks or job is None:
        return {
            "checkpoint_key": checkpoint_key,
            "publication_id": _clean(entry.get("publication_id")) or None,
            "status": "HOLD_RECOVERY_REREAD_JOB_RECONSTRUCTION",
            "hard_blocks": reconstruction_blocks or ["REREAD_ROUTE_JOB_RECONSTRUCTION_REQUIRED"],
            "recovery_route": ROUTE_EXPLICIT,
            "provider_reread_authorized": False,
            "provider_network_call_performed": False,
            "publication_blocked": False,
            "durable_paths": [],
        }
    strict = reread_recovery.reconcile_materialized_reread_crash(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
    )
    return _explicit_result(checkpoint_key, entry, strict)


@contextmanager
def _installed_route() -> Iterator[None]:
    previous = generic._reconcile_entry
    generic._reconcile_entry = _routed_reconcile_entry
    try:
        yield
    finally:
        generic._reconcile_entry = previous


def reconcile_channel_recoveries(
    repo_root: Path,
    channel: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    with _installed_route():
        result = generic.reconcile_channel_recoveries(
            repo_root,
            channel,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
        )
    result = _clone(result)
    result["guards"] = _guards()
    result["router_id"] = ROUTER_ID
    return result


def reconcile_fleet_from_plan(
    repo_root: Path,
    runtime_registry: dict[str, Any],
    sealed_plan: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    with _installed_route():
        result = generic.reconcile_fleet_from_plan(
            repo_root, runtime_registry, sealed_plan, now=now
        )
    result = _clone(result)
    result["guards"] = _guards()
    result["router_id"] = ROUTER_ID
    return result


def run_fleet_recovery(
    repo_root: Path,
    runtime_registry_path: Path = authorization_seal.DEFAULT_RUNTIME_REGISTRY,
    binding_registry_path: Path = authorization_seal.DEFAULT_BINDING_REGISTRY,
    capability_registry_path: Path = authorization_seal.DEFAULT_CAPABILITY_REGISTRY,
    *,
    now: str,
) -> dict[str, Any]:
    root = repo_root.resolve()
    sealed_plan, runtime_registry = authorization_seal.build_sealed_plan(
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
    return 2 if result.get("status") in {"FLEET_RECOVERY_HOLD", "FLEET_RECOVERY_PARTIAL_HOLD"} else 0


if __name__ == "__main__":
    raise SystemExit(main())
