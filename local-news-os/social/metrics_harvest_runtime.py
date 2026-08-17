#!/usr/bin/env python3
"""Crash-safe observed-metrics harvest execution for LOCAL NEWS OS.

The scheduler decides *what is due*. This runtime adds durable execution semantics without
moving analytics onto the editorial publication path: a due publication/checkpoint is claimed
before network access, native/free observed metrics are collected through the existing transport,
the observation ledger and feedback snapshot are persisted first, and only then is the checkpoint
marked complete. Successful no-data windows are also remembered so they are not fetched forever.

Credentials exist only at the transport boundary. Checkpoint state is isolated per
instance/channel/platform, contains no provider payloads or predictive analytics, and is protected
with a same-filesystem lock plus compare-and-swap fingerprinting. Analytics failure never blocks,
rolls back, edits, promotes, or republishes editorial output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import durable_feedback_snapshot
import metrics_harvest_scheduler
import native_metrics_transport
import observed_metrics_collector

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-metrics-harvest-runtime"
DEFAULT_LEASE_MINUTES = 15
DEFAULT_RETRY_MINUTES = 15
DEFAULT_AUTH_RETRY_MINUTES = 60
LOCK_STALE_SECONDS = 120

CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]
PersistBundleCall = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _dt(value: str) -> datetime:
    text = _clean(value)
    if not text:
        raise ValueError("timestamp required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe_relative(raw: str) -> PurePosixPath:
    path = PurePosixPath(_clean(raw).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or path.name in {"", "."}:
        raise ValueError("unsafe runtime path")
    return path


def _safe_target(repo_root: Path, relative: str) -> Path:
    path = _safe_relative(relative)
    return repo_root.joinpath(*path.parts)


def expected_checkpoint_state_path(channel: dict[str, Any]) -> str:
    publication_state = channel.get("publication_state") if isinstance(channel.get("publication_state"), dict) else {}
    raw = _clean(publication_state.get("state_path"))
    if not raw:
        raise ValueError("channel publication_state.state_path is required")
    path = _safe_relative(raw)
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    return str(path.with_name(f"{stem}_metrics_harvest_state.json"))


def _state_fingerprint(state: dict[str, Any]) -> str:
    unsigned = _clone(state)
    unsigned.pop("state_fingerprint_sha256", None)
    return _digest(unsigned)


def empty_checkpoint_state(channel: dict[str, Any]) -> dict[str, Any]:
    state = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_checkpoint_state_path(channel),
        "entries": {},
        "guards": {
            "analytics_advisory_only": True,
            "publication_blocked_by_analytics": False,
            "credential_values_persisted": False,
            "raw_provider_payload_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "cross_channel_state": False,
            "zero_paid_dependency": True,
        },
    }
    state["state_fingerprint_sha256"] = _state_fingerprint(state)
    return state


def _entry_has_forbidden_fields(entry: dict[str, Any]) -> bool:
    forbidden_tokens = (
        "access_token", "refresh_token", "secret", "password", "api_key", "credential_value",
        "predicted", "prediction", "estimated", "expected_reach", "expected_views",
    )
    for key, value in entry.items():
        normalized = _clean(key).lower().replace("-", "_")
        if any(token in normalized for token in forbidden_tokens):
            return True
        if isinstance(value, dict) and _entry_has_forbidden_fields(value):
            return True
        if isinstance(value, list) and any(isinstance(item, dict) and _entry_has_forbidden_fields(item) for item in value):
            return True
    return False


def validate_checkpoint_state(channel: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(channel, dict) or not isinstance(state, dict):
        raise TypeError("channel and state must be mappings")
    blocks: list[str] = []
    if _clean(state.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("CHECKPOINT_STATE_SCHEMA_VERSION")
    if _clean(state.get("runtime_id")) != RUNTIME_ID:
        blocks.append("CHECKPOINT_STATE_RUNTIME_ID")
    if _clean(state.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("CHECKPOINT_STATE_INSTANCE_MISMATCH")
    if _clean(state.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("CHECKPOINT_STATE_CHANNEL_MISMATCH")
    if _clean(state.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("CHECKPOINT_STATE_PLATFORM_MISMATCH")
    try:
        expected_path = expected_checkpoint_state_path(channel)
    except ValueError:
        expected_path = ""
        blocks.append("CHECKPOINT_STATE_NAMESPACE_INVALID")
    if _clean(state.get("storage_path")) != expected_path:
        blocks.append("CHECKPOINT_STATE_NAMESPACE_MISMATCH")

    entries = state.get("entries")
    if not isinstance(entries, dict) or not all(isinstance(key, str) and isinstance(value, dict) for key, value in entries.items()):
        blocks.append("CHECKPOINT_STATE_ENTRIES_INVALID")
        entries = {}
    allowed_statuses = {
        "IN_FLIGHT", "COMPLETED", "COMPLETED_NO_DATA", "RETRY_WAIT",
        "BLOCKED_AUTH", "HOLD_ANALYTICS", "RECOVERY_REQUIRED",
    }
    for key, entry in entries.items():
        if _clean(entry.get("checkpoint_key")) != key:
            blocks.append("CHECKPOINT_ENTRY_KEY_MISMATCH")
        if not _clean(entry.get("job_fingerprint_sha256")):
            blocks.append("CHECKPOINT_ENTRY_JOB_FINGERPRINT_MISSING")
        if not _clean(entry.get("publication_id")) or not _clean(entry.get("source")):
            blocks.append("CHECKPOINT_ENTRY_IDENTITY_INCOMPLETE")
        if _clean(entry.get("status")).upper() not in allowed_statuses:
            blocks.append("CHECKPOINT_ENTRY_STATUS_INVALID")
        if _entry_has_forbidden_fields(entry):
            blocks.append("CHECKPOINT_ENTRY_FORBIDDEN_FIELD")

    guards = state.get("guards") if isinstance(state.get("guards"), dict) else {}
    required_guards = {
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "credential_values_persisted": False,
        "raw_provider_payload_persisted": False,
        "predictive_or_estimated_analytics_used": False,
        "cross_channel_state": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required_guards.items():
        if guards.get(key) is not expected:
            blocks.append("CHECKPOINT_STATE_GUARD:" + key)
    supplied = _clean(state.get("state_fingerprint_sha256"))
    if not supplied or supplied != _state_fingerprint(state):
        blocks.append("CHECKPOINT_STATE_FINGERPRINT_MISMATCH")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def load_checkpoint_state(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    try:
        target = _safe_target(repo_root, expected_checkpoint_state_path(channel))
    except ValueError as exc:
        return {}, ["CHECKPOINT_STATE_PATH_INVALID:" + str(exc)], False
    if not target.exists():
        return empty_checkpoint_state(channel), [], False
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, ["CHECKPOINT_STATE_READ_INVALID:" + str(exc)], True
    if not isinstance(value, dict):
        return {}, ["CHECKPOINT_STATE_NOT_OBJECT"], True
    checked = validate_checkpoint_state(channel, value)
    return value, list(checked.get("hard_blocks", [])), True


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


class _StateLock:
    def __init__(self, target: Path):
        self.path = target.with_name(target.name + ".lock")
        self.fd: int | None = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            try:
                age = time.time() - self.path.stat().st_mtime
            except OSError:
                age = 0
            if age <= LOCK_STALE_SECONDS:
                raise BlockingIOError("checkpoint state lock busy")
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            self.fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.write(self.fd, f"pid={os.getpid()}\n".encode("utf-8"))
        return self

    def __exit__(self, exc_type, exc, tb):
        if self.fd is not None:
            os.close(self.fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
        return False


def persist_checkpoint_state_cas(
    repo_root: Path,
    channel: dict[str, Any],
    state: dict[str, Any],
    *,
    expected_previous_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    checked = validate_checkpoint_state(channel, state)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_TARGET_CHECKPOINT_STATE", "hard_blocks": checked.get("hard_blocks", [])}
    relative = expected_checkpoint_state_path(channel)
    target = _safe_target(repo_root, relative)
    try:
        with _StateLock(target):
            existing, blocks, existed = load_checkpoint_state(repo_root, channel)
            if blocks:
                return {"persisted": False, "status": "HOLD_EXISTING_CHECKPOINT_STATE", "hard_blocks": blocks, "path": relative}
            actual = _clean(existing.get("state_fingerprint_sha256")) or None
            expected = _clean(expected_previous_fingerprint_sha256) or None
            canonical_empty = _clean(empty_checkpoint_state(channel).get("state_fingerprint_sha256")) or None
            matches = actual == expected if existed else expected in {None, canonical_empty}
            if not matches:
                return {
                    "persisted": False,
                    "status": "HOLD_CHECKPOINT_STATE_CAS_CONFLICT",
                    "hard_blocks": ["CHECKPOINT_STATE_COMPARE_AND_SWAP_CONFLICT"],
                    "path": relative,
                }
            target_fp = _clean(state.get("state_fingerprint_sha256"))
            if existed and actual == target_fp:
                return {"persisted": True, "status": "IDEMPOTENT_CHECKPOINT_STATE", "hard_blocks": [], "path": relative, "written": False}
            _atomic_write_json(target, state)
    except BlockingIOError:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE_LOCK_BUSY", "hard_blocks": ["CHECKPOINT_STATE_LOCK_BUSY"], "path": relative}
    persisted, blocks, _ = load_checkpoint_state(repo_root, channel)
    if blocks or _clean(persisted.get("state_fingerprint_sha256")) != _clean(state.get("state_fingerprint_sha256")):
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE_READBACK", "hard_blocks": blocks or ["CHECKPOINT_STATE_READBACK_FINGERPRINT_MISMATCH"], "path": relative}
    return {"persisted": True, "status": "CHECKPOINT_STATE_PERSISTED", "hard_blocks": [], "path": relative, "written": True}


def _publication(job: dict[str, Any]) -> dict[str, Any]:
    return job.get("publication") if isinstance(job.get("publication"), dict) else {}


def checkpoint_key(job: dict[str, Any]) -> str:
    publication = _publication(job)
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    identity = {
        "instance_id": _clean(publication.get("instance_id")),
        "channel_id": _clean(publication.get("channel_id")),
        "platform": _clean(publication.get("platform")).lower(),
        "publication_id": _clean(job.get("publication_id")),
        "source": _clean(job.get("source")),
        "checkpoint_hours": checkpoint.get("checkpoint_hours"),
        "checkpoint_at": _clean(checkpoint.get("checkpoint_at")),
    }
    return "harvest:" + _digest(identity)[:32]


def _job_blocks(plan: dict[str, Any], channel: dict[str, Any], job: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    publication = _publication(job)
    for key, code in (("instance_id", "JOB_INSTANCE_MISMATCH"), ("channel_id", "JOB_CHANNEL_MISMATCH")):
        if _clean(publication.get(key)) != _clean(channel.get(key)):
            blocks.append(code)
    if _clean(publication.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("JOB_PLATFORM_MISMATCH")
    supplied = _clean(job.get("job_fingerprint_sha256"))
    unsigned = _clone(job)
    unsigned.pop("job_fingerprint_sha256", None)
    if not supplied or supplied != _digest(unsigned):
        blocks.append("JOB_FINGERPRINT_MISMATCH")
    if _clean(job.get("publication_id")) != _clean(publication.get("publication_id")):
        blocks.append("JOB_PUBLICATION_ID_MISMATCH")
    if any(not _clean(plan.get(key)) for key in ("instance_id", "channel_id", "platform")):
        blocks.append("PLAN_IDENTITY_INCOMPLETE")
    return sorted(set(blocks))


def _claimed_entry(job: dict[str, Any], now_dt: datetime, attempt: int, lease_minutes: int) -> dict[str, Any]:
    publication = _publication(job)
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    return {
        "checkpoint_key": checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "source": _clean(job.get("source")),
        "checkpoint_hours": checkpoint.get("checkpoint_hours"),
        "checkpoint_at": _clean(checkpoint.get("checkpoint_at")),
        "status": "IN_FLIGHT",
        "attempt": attempt,
        "claimed_at": _iso(now_dt),
        "lease_expires_at": _iso(now_dt + timedelta(minutes=lease_minutes)),
        "retry_after_at": None,
        "completed_at": None,
        "last_result_status": None,
    }


def claim_checkpoint(repo_root: Path, channel: dict[str, Any], job: dict[str, Any], *, now: str, lease_minutes: int = DEFAULT_LEASE_MINUTES) -> dict[str, Any]:
    now_dt = _dt(now)
    if lease_minutes <= 0:
        raise ValueError("lease_minutes must be positive")
    state, blocks, _ = load_checkpoint_state(repo_root, channel)
    if blocks:
        return {"claimed": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": blocks, "publication_blocked": False}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    key = checkpoint_key(job)
    existing = state["entries"].get(key)
    if isinstance(existing, dict):
        if _clean(existing.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
            return {"claimed": False, "status": "HOLD_CHECKPOINT_IDENTITY_CONFLICT", "hard_blocks": ["CHECKPOINT_JOB_FINGERPRINT_CONFLICT"], "publication_blocked": False}
        status = _clean(existing.get("status")).upper()
        if status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"}:
            return {"claimed": False, "status": "ALREADY_" + status, "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
        gate_field = "lease_expires_at" if status == "IN_FLIGHT" else "retry_after_at"
        if status in {"IN_FLIGHT", "RETRY_WAIT", "BLOCKED_AUTH", "RECOVERY_REQUIRED"} and _clean(existing.get(gate_field)):
            try:
                if _dt(_clean(existing.get(gate_field))) > now_dt:
                    return {"claimed": False, "status": "LEASE_ACTIVE" if status == "IN_FLIGHT" else status, "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
            except ValueError:
                return {"claimed": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": ["CHECKPOINT_GATE_TIMESTAMP_INVALID"], "publication_blocked": False}
        attempt = int(existing.get("attempt") or 0) + 1
    else:
        attempt = 1
    entry = _claimed_entry(job, now_dt, attempt, lease_minutes)
    state["entries"][key] = entry
    state["state_fingerprint_sha256"] = _state_fingerprint(state)
    persisted = persist_checkpoint_state_cas(repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp)
    if persisted.get("persisted") is not True:
        return {"claimed": False, "status": persisted.get("status"), "hard_blocks": persisted.get("hard_blocks", []), "publication_blocked": False}
    return {"claimed": True, "status": "CLAIMED", "hard_blocks": [], "entry": entry, "publication_blocked": False}


def _transition(repo_root: Path, channel: dict[str, Any], job: dict[str, Any], *, now: str, status: str, last_result_status: str, retry_after_at: str | None = None) -> dict[str, Any]:
    state, blocks, _ = load_checkpoint_state(repo_root, channel)
    if blocks:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": blocks}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state["entries"].get(checkpoint_key(job))
    if not isinstance(entry, dict):
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": ["CHECKPOINT_CLAIM_MISSING"]}
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": ["CHECKPOINT_JOB_FINGERPRINT_CONFLICT"]}
    entry["status"] = status
    entry["last_result_status"] = last_result_status
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = retry_after_at
    entry["completed_at"] = _iso(_dt(now)) if status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"} else None
    state["state_fingerprint_sha256"] = _state_fingerprint(state)
    return persist_checkpoint_state_cas(repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp)


def _load_optional(repo_root: Path, relative: str) -> dict[str, Any] | None:
    try:
        target = _safe_target(repo_root, relative)
    except ValueError:
        return None
    if not target.exists():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _resolver(env_name: str) -> str:
    return os.environ.get(env_name, "")


def _summary(job: dict[str, Any], status: str, *, checkpoint_status: str | None = None, blocks: list[str] | None = None, issues: list[Any] | None = None) -> dict[str, Any]:
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    return {
        "publication_id": _clean(job.get("publication_id")) or None,
        "checkpoint_hours": checkpoint.get("checkpoint_hours"),
        "checkpoint_key": checkpoint_key(job),
        "status": status,
        "checkpoint_status": checkpoint_status,
        "hard_blocks": sorted(set(blocks or [])),
        "metric_issues": _clone(issues or []),
        "publication_blocked": False,
    }


def execute_plan_durably(
    plan: dict[str, Any],
    channel: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    repo_root: Path,
    now: str,
    credential_resolver: CredentialResolver = _resolver,
    transport_call: TransportCall = native_metrics_transport.collect_and_materialize,
    persist_bundle_call: PersistBundleCall = observed_metrics_collector.persist_bundle,
    lease_minutes: int = DEFAULT_LEASE_MINUTES,
    retry_minutes: int = DEFAULT_RETRY_MINUTES,
    auth_retry_minutes: int = DEFAULT_AUTH_RETRY_MINUTES,
    ttl_hours: int = 72,
    min_samples: int = 3,
) -> dict[str, Any]:
    if not all(isinstance(value, dict) for value in (plan, channel, access_attestation)):
        raise TypeError("plan, channel and access_attestation must be mappings")
    now_dt = _dt(now)
    if plan.get("status") != "HARVEST_READY":
        return {"schema_version": SCHEMA_VERSION, "runtime_id": RUNTIME_ID, "status": "NO_EXECUTION", "hard_blocks": [], "results": [], "publication_blocked": False}
    blocks: list[str] = []
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    if _clean(plan.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("PLAN_INSTANCE_ID_MISMATCH")
    if _clean(plan.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("PLAN_CHANNEL_ID_MISMATCH")
    if _clean(plan.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("PLAN_PLATFORM_MISMATCH")
    unsigned_plan = _clone(plan)
    supplied_plan_fp = _clean(unsigned_plan.pop("plan_fingerprint_sha256", None))
    if not supplied_plan_fp or supplied_plan_fp != _digest(unsigned_plan):
        blocks.append("PLAN_FINGERPRINT_MISMATCH")
    state, state_blocks, _ = load_checkpoint_state(repo_root, channel)
    blocks.extend(state_blocks)
    if blocks:
        return {"schema_version": SCHEMA_VERSION, "runtime_id": RUNTIME_ID, "status": "HOLD_HARVEST_RUNTIME", "hard_blocks": sorted(set(blocks)), "results": [], "publication_blocked": False}

    observation_path = observed_metrics_collector.expected_observation_store_path(channel)
    snapshot_path = durable_feedback_snapshot.expected_snapshot_path(channel)
    credentials: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    for job in plan.get("jobs", []):
        if not isinstance(job, dict):
            continue
        job_blocks = _job_blocks(plan, channel, job)
        if job_blocks:
            results.append(_summary(job, "HOLD_JOB_TAMPERED", blocks=job_blocks))
            continue
        claim = claim_checkpoint(repo_root, channel, job, now=now, lease_minutes=lease_minutes)
        if claim.get("claimed") is not True:
            results.append(_summary(job, _clean(claim.get("status")) or "HOLD_CHECKPOINT", checkpoint_status=_clean((claim.get("entry") or {}).get("status")) or None, blocks=claim.get("hard_blocks", [])))
            continue

        env_name = _clean(job.get("credential_env_name"))
        if env_name not in credentials:
            credentials[env_name] = _clean(credential_resolver(env_name))
        credential = credentials[env_name]
        existing_store = _load_optional(repo_root, observation_path)
        existing_snapshot = _load_optional(repo_root, snapshot_path)
        try:
            transport_result = transport_call(
                channel, _publication(job), access_attestation, credential,
                now=now, existing_store=existing_store, existing_snapshot=existing_snapshot,
                graph_version=_clean(job.get("graph_version")) or native_metrics_transport.DEFAULT_GRAPH_VERSION,
                ttl_hours=ttl_hours, min_samples=min_samples,
            )
        except Exception as exc:
            transport_result = {"status": "RETRY_LATER", "hard_blocks": [], "metric_issues": [{"code": "TRANSPORT_EXCEPTION", "type": type(exc).__name__}]}
        if not isinstance(transport_result, dict):
            transport_result = {"status": "HOLD_TRANSPORT", "hard_blocks": ["TRANSPORT_RESULT_INVALID"], "metric_issues": []}
        if credential and credential in _canonical(transport_result):
            transition = _transition(repo_root, channel, job, now=now, status="HOLD_ANALYTICS", last_result_status="HOLD_SECRET_EXPOSURE")
            results.append(_summary(job, "HOLD_SECRET_EXPOSURE", checkpoint_status="HOLD_ANALYTICS" if transition.get("persisted") else "TRANSITION_FAILED", blocks=["TRANSPORT_SECRET_EXPOSURE"]))
            continue

        status = _clean(transport_result.get("status")).upper() or "HOLD_TRANSPORT"
        issues = transport_result.get("metric_issues") if isinstance(transport_result.get("metric_issues"), list) else []
        result_blocks = transport_result.get("hard_blocks") if isinstance(transport_result.get("hard_blocks"), list) else []
        checkpoint_status = "HOLD_ANALYTICS"
        outward_status = status
        retry_after: str | None = None

        if status == "COLLECTED_AND_MATERIALIZED":
            bundle = transport_result.get("materialization") if isinstance(transport_result.get("materialization"), dict) else None
            if bundle is None or bundle.get("hard_blocks"):
                outward_status = "HOLD_OBSERVATION"
                checkpoint_status = "HOLD_ANALYTICS"
                result_blocks = list((bundle or {}).get("hard_blocks", [])) or ["MATERIALIZATION_MISSING"]
            else:
                try:
                    persisted = persist_bundle_call(repo_root, bundle)
                except Exception:
                    persisted = {"persisted": False}
                if persisted.get("persisted") is True:
                    checkpoint_status = "COMPLETED"
                else:
                    outward_status = "RECOVERY_REQUIRED"
                    checkpoint_status = "RECOVERY_REQUIRED"
                    retry_after = _iso(now_dt + timedelta(minutes=retry_minutes))
                    result_blocks = ["OBSERVATION_PERSISTENCE_NOT_CONFIRMED"]
        elif status == "NO_OBSERVED_METRICS":
            checkpoint_status = "COMPLETED_NO_DATA"
        elif status == "RETRY_LATER":
            checkpoint_status = "RETRY_WAIT"
            retry_after = _iso(now_dt + timedelta(minutes=retry_minutes))
        elif status == "BLOCKED_AUTH":
            checkpoint_status = "BLOCKED_AUTH"
            retry_after = _iso(now_dt + timedelta(minutes=auth_retry_minutes))

        transition = _transition(repo_root, channel, job, now=now, status=checkpoint_status, last_result_status=outward_status, retry_after_at=retry_after)
        if transition.get("persisted") is not True:
            results.append(_summary(job, "HOLD_CHECKPOINT_TRANSITION", checkpoint_status="TRANSITION_FAILED", blocks=transition.get("hard_blocks", []), issues=issues))
            continue
        results.append(_summary(job, outward_status, checkpoint_status=checkpoint_status, blocks=result_blocks, issues=issues))

    final_state, final_blocks, _ = load_checkpoint_state(repo_root, channel)
    result = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": "HARVEST_RUNTIME_EXECUTED" if not final_blocks else "HOLD_CHECKPOINT_STATE",
        "hard_blocks": final_blocks,
        "publication_blocked": False,
        "checkpoint_state_path": expected_checkpoint_state_path(channel),
        "checkpoint_state_fingerprint_sha256": _clean(final_state.get("state_fingerprint_sha256")) or None,
        "results": results,
        "guards": {
            "claim_persisted_before_network": True,
            "completed_checkpoint_reharvested": False,
            "credential_values_returned": False,
            "credential_values_persisted": False,
            "raw_provider_payload_returned": False,
            "raw_provider_payload_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "publication_blocked_by_analytics": False,
            "cross_channel_state": False,
            "zero_paid_dependency": True,
        },
    }
    result["runtime_fingerprint_sha256"] = _digest(result)
    return result


def _load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("publication_state", type=Path)
    parser.add_argument("access_attestation", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    channel = _load_object(args.channel)
    publication_state = _load_object(args.publication_state)
    attestation = _load_object(args.access_attestation)
    observation_store = _load_optional(args.repo_root, observed_metrics_collector.expected_observation_store_path(channel))
    windows = [int(item.strip()) for item in args.windows_hours.split(",") if item.strip()]
    plan = metrics_harvest_scheduler.plan_harvest(
        channel, publication_state, attestation, now=args.now,
        observation_store=observation_store, windows_hours=windows, max_publications=args.max_publications,
    )
    if not args.execute or plan.get("status") != "HARVEST_READY":
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if plan.get("status") in {"HARVEST_READY", "NO_HARVEST_DUE"} else 2
    result = execute_plan_durably(plan, channel, attestation, repo_root=args.repo_root, now=args.now)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("status") == "HARVEST_RUNTIME_EXECUTED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
