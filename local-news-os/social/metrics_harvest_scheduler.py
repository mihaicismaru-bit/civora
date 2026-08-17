#!/usr/bin/env python3
"""Deterministic observed-metrics harvest scheduler for LOCAL NEWS OS.

This layer turns confirmed, descriptor-complete publication state into bounded
native/free analytics work. It deliberately schedules analytics *after*
publication and can never become an editorial or dispatch gate.

The scheduler is conservative by design:
- only PUBLISHED records with remote-publication proof and the full metrics
  descriptor are eligible;
- incomplete legacy state is diagnosed and skipped instead of fabricating
  product/topic/format identity;
- observation windows are cumulative checkpoints after publication; a later
  valid observation covers earlier checkpoints, so delayed runs make one catch-up
  request rather than replaying every missed window;
- only one observation is scheduled per publication per run and the channel has
  a deterministic per-run cap;
- native transport capability, declared sources, verified access and the
  zero-paid policy are checked before a job is emitted;
- observation-store identity/fingerprint failures stop harvesting for that
  channel, never publication;
- predictive/estimated fields and credential values are not scheduling inputs;
- credential values exist only inside execute_harvest's network boundary and are
  never returned or persisted.

Website and each social channel remain sibling publications. Harvest state is
inferred from each channel's own durable observed-metrics ledger; no cross-channel
normalization or shared performance state is introduced here.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

import native_metrics_transport
import observed_metrics_collector

SCHEMA_VERSION = "1.0"
SCHEDULER_ID = "local-news-os-metrics-harvest-scheduler"
DEFAULT_WINDOWS_HOURS = (1, 6, 24, 72)
DEFAULT_MAX_PUBLICATIONS = 8

CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]

DESCRIPTOR_FIELDS = (
    "instance_id",
    "channel_id",
    "platform",
    "status",
    "publication_id",
    "remote_publication_id",
    "story_id",
    "product_id",
    "published_at",
    "native_format",
    "topic_keys",
    "series_id",
)


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _parse_time(value: Any) -> dt.datetime:
    text = _clean(value)
    if not text:
        raise ValueError("timestamp is required")
    parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def _iso(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _windows(values: Any) -> tuple[int, ...]:
    if values is None:
        return DEFAULT_WINDOWS_HOURS
    if not isinstance(values, (list, tuple)):
        raise ValueError("harvest windows must be a list or tuple")
    parsed: list[int] = []
    for raw in values:
        if isinstance(raw, bool):
            raise ValueError("harvest windows must be positive integer hours")
        try:
            number = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("harvest windows must be positive integer hours") from exc
        if number <= 0 or float(raw) != float(number):
            raise ValueError("harvest windows must be positive integer hours")
        parsed.append(number)
    if not parsed or len(set(parsed)) != len(parsed):
        raise ValueError("harvest windows must be non-empty and unique")
    return tuple(sorted(parsed))


def _descriptor(record: dict[str, Any]) -> dict[str, Any]:
    """Project only the authoritative fields consumed by observed metrics.

    This intentionally strips predicted/estimated analytics and unrelated adapter
    metadata before scheduling, so they cannot influence timing or identity.
    """
    return {key: _clone(record.get(key)) for key in DESCRIPTOR_FIELDS if key in record}


def _state_identity_blocks(channel: dict[str, Any], state: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    for key, code in (
        ("instance_id", "STATE_INSTANCE_MISMATCH"),
        ("channel_id", "STATE_CHANNEL_MISMATCH"),
        ("platform", "STATE_PLATFORM_MISMATCH"),
    ):
        supplied = _clean(state.get(key))
        expected = _clean(channel.get(key))
        if key == "platform":
            supplied, expected = supplied.lower(), expected.lower()
        if supplied and supplied != expected:
            blocks.append(code)
    return sorted(set(blocks))


def enumerate_publications(channel: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    """Return descriptor-complete confirmed publications from channel-local state.

    The canonical generic publication ledger uses ``records``. Historical adapter
    state may use a ``published`` map without product/topic/native-format identity;
    those rows are explicitly skipped rather than reverse-engineered.
    """
    if not isinstance(channel, dict) or not isinstance(state, dict):
        raise TypeError("channel and state must be mappings")
    identity_blocks = _state_identity_blocks(channel, state)
    if identity_blocks:
        return {
            "valid": False,
            "hard_blocks": identity_blocks,
            "publications": [],
            "skipped": [],
        }

    raw_records = state.get("records")
    records: list[dict[str, Any]] = []
    if isinstance(raw_records, dict):
        records = [value for _, value in sorted(raw_records.items()) if isinstance(value, dict)]
    elif isinstance(raw_records, list):
        records = [value for value in raw_records if isinstance(value, dict)]

    publications: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for record in records:
        descriptor = _descriptor(record)
        checked = observed_metrics_collector.validate_publication_descriptor(channel, descriptor)
        publication_id = _clean(record.get("publication_id")) or None
        if checked.get("valid") is not True:
            skipped.append({
                "publication_id": publication_id,
                "reason": "INCOMPLETE_OR_INELIGIBLE_PUBLICATION_DESCRIPTOR",
                "hard_blocks": list(checked.get("hard_blocks", [])),
            })
            continue
        publications.append(descriptor)

    legacy = state.get("published")
    if isinstance(legacy, dict):
        for legacy_key in sorted(legacy):
            skipped.append({
                "publication_id": None,
                "legacy_key": _clean(legacy_key),
                "reason": "LEGACY_STATE_DESCRIPTOR_NOT_FABRICATED",
                "hard_blocks": ["AUTHORITATIVE_METRICS_DESCRIPTOR_REQUIRED"],
            })

    publications.sort(key=lambda row: (_clean(row.get("published_at")), _clean(row.get("publication_id"))))
    skipped.sort(key=lambda row: (_clean(row.get("publication_id")), _clean(row.get("legacy_key")), row["reason"]))
    return {
        "valid": True,
        "hard_blocks": [],
        "publications": publications,
        "skipped": skipped,
    }


def _latest_observed_at(
    channel: dict[str, Any],
    store: dict[str, Any] | None,
    publication_id: str,
) -> tuple[dt.datetime | None, list[str]]:
    if store is None:
        return None, []
    checked = observed_metrics_collector.validate_observation_store(channel, store)
    if checked.get("valid") is not True:
        return None, list(checked.get("hard_blocks", []))
    latest: dt.datetime | None = None
    for observation in checked["store"].get("observations", []):
        if _clean(observation.get("publication_id")) != publication_id:
            continue
        try:
            when = _parse_time(observation.get("observed_at"))
        except ValueError:
            return None, ["INVALID_OBSERVED_AT"]
        if latest is None or when > latest:
            latest = when
    return latest, []


def _due_checkpoint(
    publication: dict[str, Any],
    latest_observed_at: dt.datetime | None,
    now: dt.datetime,
    windows_hours: tuple[int, ...],
) -> dict[str, Any] | None:
    published = _parse_time(publication.get("published_at"))
    if now < published:
        return None
    due: list[tuple[int, dt.datetime]] = []
    for hours in windows_hours:
        target = published + dt.timedelta(hours=hours)
        if target <= now and (latest_observed_at is None or latest_observed_at < target):
            due.append((hours, target))
    if not due:
        return None
    # Catch up directly to the latest checkpoint currently due. Because provider
    # observations are cumulative from published_at, this safely covers earlier
    # missed checkpoints without spending additional API requests.
    hours, target = due[-1]
    covered = [value for value in windows_hours if published + dt.timedelta(hours=value) <= target]
    return {
        "checkpoint_hours": hours,
        "checkpoint_at": _iso(target),
        "covered_checkpoints_hours": covered,
        "latest_observed_at": _iso(latest_observed_at) if latest_observed_at else None,
        "overdue_seconds": max(0, int((now - target).total_seconds())),
    }


def plan_harvest(
    channel: dict[str, Any],
    publication_state: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    now: str,
    observation_store: dict[str, Any] | None = None,
    windows_hours: Any = None,
    max_publications: int = DEFAULT_MAX_PUBLICATIONS,
) -> dict[str, Any]:
    """Build a secret-free bounded harvest plan for one independent channel."""
    if not all(isinstance(value, dict) for value in (channel, publication_state, access_attestation)):
        raise TypeError("channel, publication_state and access_attestation must be mappings")
    now_dt = _parse_time(now)
    windows = _windows(windows_hours)
    if isinstance(max_publications, bool) or not isinstance(max_publications, int) or max_publications <= 0:
        raise ValueError("max_publications must be a positive integer")

    hard_blocks: list[str] = []
    if channel.get("zero_paid_dependency") is not True:
        hard_blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        hard_blocks.append("OBSERVED_ONLY_REQUIRED")
    if hard_blocks:
        result = {
            "schema_version": SCHEMA_VERSION,
            "scheduler_id": SCHEDULER_ID,
            "status": "HOLD_HARVEST",
            "hard_blocks": sorted(set(hard_blocks)),
            "publication_blocked": False,
            "jobs": [],
            "skipped": [],
        }
        result["plan_fingerprint_sha256"] = _digest(result)
        return result

    enumerated = enumerate_publications(channel, publication_state)
    if enumerated.get("valid") is not True:
        result = {
            "schema_version": SCHEMA_VERSION,
            "scheduler_id": SCHEDULER_ID,
            "instance_id": _clean(channel.get("instance_id")) or None,
            "channel_id": _clean(channel.get("channel_id")) or None,
            "platform": _clean(channel.get("platform")).lower() or None,
            "status": "HOLD_HARVEST",
            "hard_blocks": list(enumerated.get("hard_blocks", [])),
            "publication_blocked": False,
            "jobs": [],
            "skipped": list(enumerated.get("skipped", [])),
        }
        result["plan_fingerprint_sha256"] = _digest(result)
        return result

    if observation_store is not None:
        checked_store = observed_metrics_collector.validate_observation_store(channel, observation_store)
        if checked_store.get("valid") is not True:
            result = {
                "schema_version": SCHEMA_VERSION,
                "scheduler_id": SCHEDULER_ID,
                "instance_id": _clean(channel.get("instance_id")) or None,
                "channel_id": _clean(channel.get("channel_id")) or None,
                "platform": _clean(channel.get("platform")).lower() or None,
                "status": "HOLD_OBSERVATION_STORE",
                "hard_blocks": list(checked_store.get("hard_blocks", [])),
                "publication_blocked": False,
                "jobs": [],
                "skipped": list(enumerated.get("skipped", [])),
            }
            result["plan_fingerprint_sha256"] = _digest(result)
            return result

    jobs: list[dict[str, Any]] = []
    skipped = list(enumerated.get("skipped", []))
    for publication in enumerated["publications"]:
        publication_id = _clean(publication.get("publication_id"))
        latest, store_blocks = _latest_observed_at(channel, observation_store, publication_id)
        if store_blocks:
            skipped.append({
                "publication_id": publication_id,
                "reason": "OBSERVATION_STORE_ROW_INVALID",
                "hard_blocks": store_blocks,
            })
            continue
        checkpoint = _due_checkpoint(publication, latest, now_dt, windows)
        if checkpoint is None:
            skipped.append({
                "publication_id": publication_id,
                "reason": "NO_CHECKPOINT_DUE",
                "hard_blocks": [],
            })
            continue
        transport = native_metrics_transport.build_transport_plan(
            channel, publication, access_attestation
        )
        if transport.get("status") != "TRANSPORT_PLANNED":
            skipped.append({
                "publication_id": publication_id,
                "reason": "TRANSPORT_NOT_ELIGIBLE",
                "hard_blocks": list(transport.get("hard_blocks", [])),
            })
            continue
        transport_plan = transport["plan"]
        job = {
            "publication": _clone(publication),
            "publication_id": publication_id,
            "remote_publication_id": _clean(publication.get("remote_publication_id")),
            "checkpoint": checkpoint,
            "source": transport_plan.get("source"),
            "credential_env_name": transport_plan.get("credential_env_name"),
            "graph_version": transport_plan.get("graph_version"),
            "metric_candidates": list(transport_plan.get("metric_candidates", [])),
            "network_boundary": "native_free_api",
        }
        job["job_fingerprint_sha256"] = _digest(job)
        jobs.append(job)

    # Oldest due checkpoint first; ties are stable by publication identity. This
    # prevents nondeterministic request order while keeping the per-run budget hard.
    jobs.sort(key=lambda row: (row["checkpoint"]["checkpoint_at"], row["publication_id"]))
    deferred = jobs[max_publications:]
    jobs = jobs[:max_publications]
    for job in deferred:
        skipped.append({
            "publication_id": job["publication_id"],
            "reason": "DEFERRED_BY_RUN_BUDGET",
            "hard_blocks": [],
        })
    skipped.sort(key=lambda row: (_clean(row.get("publication_id")), _clean(row.get("legacy_key")), row["reason"]))

    status = "HARVEST_READY" if jobs else "NO_HARVEST_DUE"
    result = {
        "schema_version": SCHEMA_VERSION,
        "scheduler_id": SCHEDULER_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": [],
        "publication_blocked": False,
        "planned_at": _iso(now_dt),
        "windows_hours": list(windows),
        "max_publications_per_run": max_publications,
        "jobs": jobs,
        "skipped": skipped,
        "guards": {
            "observed_only": True,
            "predictive_or_estimated_fields_used_for_scheduling": False,
            "cross_channel_learning": False,
            "credential_values_in_plan": False,
            "publication_blocked_by_analytics": False,
            "zero_paid_dependency": True,
        },
    }
    result["plan_fingerprint_sha256"] = _digest(result)
    return result


def _default_credential_resolver(env_name: str) -> str:
    return os.environ.get(env_name, "")


def execute_harvest(
    plan: dict[str, Any],
    channel: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    now: str,
    observation_store: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
    credential_resolver: CredentialResolver = _default_credential_resolver,
    transport_call: TransportCall = native_metrics_transport.collect_and_materialize,
    persist_root: Path | None = None,
    ttl_hours: int = 72,
    min_samples: int = 3,
) -> dict[str, Any]:
    """Execute only jobs emitted by plan_harvest, sequentially and channel-locally."""
    if not all(isinstance(value, dict) for value in (plan, channel, access_attestation)):
        raise TypeError("plan, channel and access_attestation must be mappings")
    if plan.get("status") != "HARVEST_READY":
        return {
            "schema_version": SCHEMA_VERSION,
            "scheduler_id": SCHEDULER_ID,
            "status": "NO_EXECUTION",
            "publication_blocked": False,
            "results": [],
            "observation_store": _clone(observation_store) if observation_store is not None else None,
            "snapshot": _clone(snapshot) if snapshot is not None else None,
        }
    for key in ("instance_id", "channel_id"):
        if _clean(plan.get(key)) != _clean(channel.get(key)):
            return {
                "schema_version": SCHEMA_VERSION,
                "scheduler_id": SCHEDULER_ID,
                "status": "HOLD_HARVEST",
                "hard_blocks": ["PLAN_" + key.upper() + "_MISMATCH"],
                "publication_blocked": False,
                "results": [],
            }
    if _clean(plan.get("platform")).lower() != _clean(channel.get("platform")).lower():
        return {
            "schema_version": SCHEMA_VERSION,
            "scheduler_id": SCHEDULER_ID,
            "status": "HOLD_HARVEST",
            "hard_blocks": ["PLAN_PLATFORM_MISMATCH"],
            "publication_blocked": False,
            "results": [],
        }

    current_store = _clone(observation_store) if observation_store is not None else None
    current_snapshot = _clone(snapshot) if snapshot is not None else None
    results: list[dict[str, Any]] = []
    credential_cache: dict[str, str] = {}

    for job in plan.get("jobs", []):
        if not isinstance(job, dict):
            continue
        supplied_fp = _clean(job.get("job_fingerprint_sha256"))
        unsigned = _clone(job)
        unsigned.pop("job_fingerprint_sha256", None)
        if supplied_fp != _digest(unsigned):
            results.append({
                "publication_id": _clean(job.get("publication_id")) or None,
                "status": "HOLD_JOB_TAMPERED",
                "publication_blocked": False,
            })
            continue
        env_name = _clean(job.get("credential_env_name"))
        if env_name not in credential_cache:
            credential_cache[env_name] = _clean(credential_resolver(env_name))
        credential = credential_cache[env_name]
        result = transport_call(
            channel,
            job["publication"],
            access_attestation,
            credential,
            now=now,
            existing_store=current_store,
            existing_snapshot=current_snapshot,
            graph_version=_clean(job.get("graph_version")) or native_metrics_transport.DEFAULT_GRAPH_VERSION,
            ttl_hours=ttl_hours,
            min_samples=min_samples,
        )

        # Defense in depth: a transport implementation must never echo its runtime
        # secret. If it does, discard the result and do not persist analytics state.
        if credential and credential in _canonical(result):
            results.append({
                "publication_id": job["publication_id"],
                "status": "HOLD_SECRET_EXPOSURE",
                "publication_blocked": False,
            })
            continue

        materialization = result.get("materialization") if isinstance(result.get("materialization"), dict) else None
        if result.get("status") == "COLLECTED_AND_MATERIALIZED" and materialization and not materialization.get("hard_blocks"):
            current_store = _clone(materialization.get("observation_store"))
            next_snapshot = materialization.get("snapshot_to_persist")
            if isinstance(next_snapshot, dict):
                current_snapshot = _clone(next_snapshot)
            if persist_root is not None:
                materialization["persistence_result"] = observed_metrics_collector.persist_bundle(
                    persist_root, materialization
                )
        results.append({
            "publication_id": job["publication_id"],
            "checkpoint_hours": job["checkpoint"]["checkpoint_hours"],
            "status": result.get("status"),
            "publication_blocked": False,
            "metric_issues": _clone(result.get("metric_issues", [])),
            "hard_blocks": _clone(result.get("hard_blocks", [])),
        })

    final = {
        "schema_version": SCHEMA_VERSION,
        "scheduler_id": SCHEDULER_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": "HARVEST_EXECUTED",
        "publication_blocked": False,
        "results": results,
        "observation_store": current_store,
        "snapshot": current_snapshot,
        "guards": {
            "credential_values_returned": False,
            "raw_provider_payload_returned": False,
            "publication_blocked_by_analytics": False,
            "cross_channel_learning": False,
            "zero_paid_dependency": True,
        },
    }
    final["execution_fingerprint_sha256"] = _digest(final)
    return final


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("publication_state", type=Path)
    parser.add_argument("access_attestation", type=Path)
    parser.add_argument("--now", required=True)
    parser.add_argument("--observation-store", type=Path)
    parser.add_argument("--snapshot", type=Path)
    parser.add_argument("--persist-root", type=Path)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()

    windows = [int(item.strip()) for item in args.windows_hours.split(",") if item.strip()]
    channel = _load(args.channel)
    state = _load(args.publication_state)
    attestation = _load(args.access_attestation)
    store = _load_optional(args.observation_store)
    snapshot = _load_optional(args.snapshot)
    plan = plan_harvest(
        channel,
        state,
        attestation,
        now=args.now,
        observation_store=store,
        windows_hours=windows,
        max_publications=args.max_publications,
    )
    if not args.execute or plan.get("status") != "HARVEST_READY":
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan.get("status") in {"HARVEST_READY", "NO_HARVEST_DUE"} else 2

    result = execute_harvest(
        plan,
        channel,
        attestation,
        now=args.now,
        observation_store=store,
        snapshot=snapshot,
        persist_root=args.persist_root,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "HARVEST_EXECUTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
