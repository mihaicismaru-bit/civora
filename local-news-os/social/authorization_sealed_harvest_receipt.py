#!/usr/bin/env python3
"""Authorization-sealed durable receipts for observed-metrics harvest execution.

This layer is activated only inside a verified fleet authorization-seal execution.
It binds each provider-facing harvest attempt to the exact authorization fingerprint
that survived the pre-network TOCTOU recheck. The fingerprint, lease/checkpoint
identity, attempt number and provider outcome are persisted as a secret-free,
SHA-256-sealed receipt before/after network execution.

A crash after NETWORK_CALL_STARTED is deliberately ambiguous. After the lease
expires, that checkpoint becomes RECOVERY_REQUIRED and is never blindly retried.
A crash before NETWORK_CALL_STARTED remains safely reclaimable. Legacy/unsealed
metrics runtime calls are unchanged.

Analytics remains advisory-only and can never block, roll back or promote editorial
publication. No provider payload or credential value is persisted in receipts.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import re
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Iterator

import metrics_harvest_runtime as runtime

SCHEMA_VERSION = "1.0"
RECEIPT_ID = "local-news-os-authorization-sealed-harvest-receipt"
AUTHORIZATION_FINGERPRINT_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
RECEIPT_FINGERPRINT_RE = re.compile(r"^[0-9a-f]{64}$")

CredentialResolver = Callable[[str], str]
TransportCall = Callable[..., dict[str, Any]]
PersistBundleCall = Callable[[Path, dict[str, Any]], dict[str, Any]]

_ACTIVE_FINGERPRINT: str | None = None


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _valid_authorization_fingerprint(value: Any) -> bool:
    return bool(AUTHORIZATION_FINGERPRINT_RE.fullmatch(_clean(value)))


def _receipt_fingerprint(receipt: dict[str, Any]) -> str:
    unsigned = _clone(receipt)
    unsigned.pop("receipt_fingerprint_sha256", None)
    return _digest(unsigned)


def _execution_id(job: dict[str, Any], authorization_fingerprint: str, attempt: int) -> str:
    material = {
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "attempt": attempt,
    }
    return "harvest-execution:" + _digest(material)[:32]


def _new_receipt(job: dict[str, Any], authorization_fingerprint: str, attempt: int, claimed_at: str) -> dict[str, Any]:
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": RECEIPT_ID,
        "execution_id": _execution_id(job, authorization_fingerprint, attempt),
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "attempt": attempt,
        "status": "CLAIMED",
        "claimed_at": claimed_at,
        "network_started_at": None,
        "updated_at": claimed_at,
        "provider_result_status": None,
        "checkpoint_status": "IN_FLIGHT",
        "materialization_fingerprint_sha256": None,
        "guards": {
            "authorization_verified_before_network": True,
            "provider_payload_persisted": False,
            "credential_value_persisted": False,
            "publication_blocked": False,
            "zero_paid_dependency": True,
        },
    }
    receipt["receipt_fingerprint_sha256"] = _receipt_fingerprint(receipt)
    return receipt


def _receipt_blocks(receipt: dict[str, Any], entry: dict[str, Any], authorization_fingerprint: str | None = None) -> list[str]:
    blocks: list[str] = []
    if _clean(receipt.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("SEALED_RECEIPT_SCHEMA_VERSION")
    if _clean(receipt.get("receipt_id")) != RECEIPT_ID:
        blocks.append("SEALED_RECEIPT_ID")
    auth = _clean(receipt.get("authorization_fingerprint"))
    if not _valid_authorization_fingerprint(auth):
        blocks.append("SEALED_RECEIPT_AUTHORIZATION_FINGERPRINT_INVALID")
    if authorization_fingerprint and not hmac.compare_digest(auth, authorization_fingerprint):
        blocks.append("SEALED_RECEIPT_AUTHORIZATION_CONTEXT_CHANGED")
    if auth != _clean(entry.get("authorization_fingerprint")):
        blocks.append("SEALED_RECEIPT_ENTRY_AUTHORIZATION_MISMATCH")
    if _clean(receipt.get("checkpoint_key")) != _clean(entry.get("checkpoint_key")):
        blocks.append("SEALED_RECEIPT_CHECKPOINT_MISMATCH")
    if _clean(receipt.get("job_fingerprint_sha256")) != _clean(entry.get("job_fingerprint_sha256")):
        blocks.append("SEALED_RECEIPT_JOB_FINGERPRINT_MISMATCH")
    try:
        attempt = int(receipt.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    if attempt <= 0:
        blocks.append("SEALED_RECEIPT_ATTEMPT_INVALID")
    expected_execution_id = "harvest-execution:" + _digest({
        "checkpoint_key": _clean(entry.get("checkpoint_key")),
        "job_fingerprint_sha256": _clean(entry.get("job_fingerprint_sha256")),
        "authorization_fingerprint": auth,
        "attempt": attempt,
    })[:32]
    if _clean(receipt.get("execution_id")) != expected_execution_id:
        blocks.append("SEALED_RECEIPT_EXECUTION_ID_MISMATCH")
    allowed_statuses = {
        "CLAIMED", "NETWORK_CALL_STARTED", "COMPLETED", "COMPLETED_NO_DATA",
        "RETRY_WAIT", "BLOCKED_AUTH", "HOLD_ANALYTICS", "RECOVERY_REQUIRED",
    }
    if _clean(receipt.get("status")).upper() not in allowed_statuses:
        blocks.append("SEALED_RECEIPT_STATUS_INVALID")
    guards = receipt.get("guards") if isinstance(receipt.get("guards"), dict) else {}
    required_guards = {
        "authorization_verified_before_network": True,
        "provider_payload_persisted": False,
        "credential_value_persisted": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required_guards.items():
        if guards.get(key) is not expected:
            blocks.append("SEALED_RECEIPT_GUARD:" + key)
    supplied = _clean(receipt.get("receipt_fingerprint_sha256"))
    if not RECEIPT_FINGERPRINT_RE.fullmatch(supplied) or supplied != _receipt_fingerprint(receipt):
        blocks.append("SEALED_RECEIPT_FINGERPRINT_MISMATCH")
    if runtime._entry_has_forbidden_fields(receipt):
        blocks.append("SEALED_RECEIPT_FORBIDDEN_FIELD")
    materialization_fp = _clean(receipt.get("materialization_fingerprint_sha256"))
    if materialization_fp and not RECEIPT_FINGERPRINT_RE.fullmatch(materialization_fp):
        blocks.append("SEALED_RECEIPT_MATERIALIZATION_FINGERPRINT_INVALID")
    return sorted(set(blocks))


def validate_sealed_entry(entry: dict[str, Any], authorization_fingerprint: str | None = None) -> dict[str, Any]:
    if not isinstance(entry, dict):
        return {"valid": False, "hard_blocks": ["SEALED_ENTRY_NOT_OBJECT"]}
    blocks: list[str] = []
    auth = _clean(entry.get("authorization_fingerprint"))
    if not _valid_authorization_fingerprint(auth):
        blocks.append("SEALED_ENTRY_AUTHORIZATION_FINGERPRINT_INVALID")
    if authorization_fingerprint and not hmac.compare_digest(auth, authorization_fingerprint):
        blocks.append("SEALED_ENTRY_AUTHORIZATION_CONTEXT_CHANGED")
    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    if not receipts:
        blocks.append("SEALED_ENTRY_RECEIPT_HISTORY_REQUIRED")
    attempts: list[int] = []
    for receipt in receipts:
        if not isinstance(receipt, dict):
            blocks.append("SEALED_RECEIPT_NOT_OBJECT")
            continue
        blocks.extend(_receipt_blocks(receipt, entry, authorization_fingerprint))
        try:
            attempts.append(int(receipt.get("attempt") or 0))
        except (TypeError, ValueError):
            attempts.append(0)
    if attempts and attempts != list(range(1, len(attempts) + 1)):
        blocks.append("SEALED_RECEIPT_ATTEMPT_HISTORY_INVALID")
    if attempts and int(entry.get("attempt") or 0) != attempts[-1]:
        blocks.append("SEALED_ENTRY_ATTEMPT_MISMATCH")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def _claim_entry(job: dict[str, Any], authorization_fingerprint: str, now: str, attempt: int, lease_minutes: int, previous_receipts: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    now_dt = runtime._dt(now)
    entry = runtime._claimed_entry(job, now_dt, attempt, lease_minutes)
    entry["authorization_fingerprint"] = authorization_fingerprint
    receipts = _clone(previous_receipts or [])
    receipts.append(_new_receipt(job, authorization_fingerprint, attempt, runtime._iso(now_dt)))
    entry["execution_receipts"] = receipts
    return entry


def _latest_receipt(entry: dict[str, Any]) -> dict[str, Any] | None:
    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    return receipts[-1] if receipts and isinstance(receipts[-1], dict) else None


def _persist_recovery_required(repo_root: Path, channel: dict[str, Any], job: dict[str, Any], state: dict[str, Any], previous_fp: str, *, now: str) -> dict[str, Any]:
    entry = state["entries"].get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return {"claimed": False, "status": "HOLD_SEALED_RECEIPT", "hard_blocks": ["SEALED_ENTRY_MISSING"], "publication_blocked": False}
    receipt = _latest_receipt(entry)
    if not receipt:
        return {"claimed": False, "status": "HOLD_SEALED_RECEIPT", "hard_blocks": ["SEALED_RECEIPT_MISSING"], "publication_blocked": False}
    entry["status"] = "RECOVERY_REQUIRED"
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = None
    entry["last_result_status"] = "AMBIGUOUS_NETWORK_EXECUTION"
    receipt["status"] = "RECOVERY_REQUIRED"
    receipt["checkpoint_status"] = "RECOVERY_REQUIRED"
    receipt["provider_result_status"] = "AMBIGUOUS_NETWORK_EXECUTION"
    receipt["updated_at"] = runtime._iso(runtime._dt(now))
    receipt["receipt_fingerprint_sha256"] = _receipt_fingerprint(receipt)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {"claimed": False, "status": persisted.get("status") or "HOLD_CHECKPOINT_STATE", "hard_blocks": persisted.get("hard_blocks", []), "publication_blocked": False}
    return {"claimed": False, "status": "RECOVERY_REQUIRED", "hard_blocks": [], "entry": _clone(entry), "publication_blocked": False}


def claim_checkpoint_sealed(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    lease_minutes: int = runtime.DEFAULT_LEASE_MINUTES,
) -> dict[str, Any]:
    if not _valid_authorization_fingerprint(authorization_fingerprint):
        return {"claimed": False, "status": "HOLD_AUTHORIZATION_CONTEXT", "hard_blocks": ["AUTHORIZATION_FINGERPRINT_INVALID"], "publication_blocked": False}
    now_dt = runtime._dt(now)
    if lease_minutes <= 0:
        raise ValueError("lease_minutes must be positive")
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return {"claimed": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": blocks, "publication_blocked": False}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    key = runtime.checkpoint_key(job)
    existing = state["entries"].get(key)
    previous_receipts: list[dict[str, Any]] = []
    if isinstance(existing, dict):
        if _clean(existing.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
            return {"claimed": False, "status": "HOLD_CHECKPOINT_IDENTITY_CONFLICT", "hard_blocks": ["CHECKPOINT_JOB_FINGERPRINT_CONFLICT"], "publication_blocked": False}
        sealed = bool(_clean(existing.get("authorization_fingerprint")) or existing.get("execution_receipts"))
        if sealed:
            checked = validate_sealed_entry(existing, authorization_fingerprint)
            if checked.get("valid") is not True:
                code = "HOLD_AUTHORIZATION_CONTEXT_CHANGED" if "SEALED_ENTRY_AUTHORIZATION_CONTEXT_CHANGED" in checked.get("hard_blocks", []) or "SEALED_RECEIPT_AUTHORIZATION_CONTEXT_CHANGED" in checked.get("hard_blocks", []) else "HOLD_SEALED_RECEIPT_TAMPERED"
                return {"claimed": False, "status": code, "hard_blocks": checked.get("hard_blocks", []), "publication_blocked": False}
            previous_receipts = _clone(existing.get("execution_receipts", []))
        status = _clean(existing.get("status")).upper()
        if status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"}:
            return {"claimed": False, "status": "ALREADY_" + status, "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
        if status == "RECOVERY_REQUIRED" and sealed:
            return {"claimed": False, "status": "RECOVERY_REQUIRED", "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
        if status == "IN_FLIGHT":
            lease = _clean(existing.get("lease_expires_at"))
            if lease:
                try:
                    if runtime._dt(lease) > now_dt:
                        return {"claimed": False, "status": "LEASE_ACTIVE", "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
                except ValueError:
                    return {"claimed": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": ["CHECKPOINT_GATE_TIMESTAMP_INVALID"], "publication_blocked": False}
            if sealed:
                receipt = _latest_receipt(existing)
                if receipt and _clean(receipt.get("status")).upper() == "NETWORK_CALL_STARTED":
                    return _persist_recovery_required(repo_root, channel, job, state, previous_fp or "", now=now)
        if status in {"RETRY_WAIT", "BLOCKED_AUTH"}:
            gate = _clean(existing.get("retry_after_at"))
            if gate:
                try:
                    if runtime._dt(gate) > now_dt:
                        return {"claimed": False, "status": status, "hard_blocks": [], "entry": _clone(existing), "publication_blocked": False}
                except ValueError:
                    return {"claimed": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": ["CHECKPOINT_GATE_TIMESTAMP_INVALID"], "publication_blocked": False}
        attempt = int(existing.get("attempt") or 0) + 1
    else:
        attempt = 1

    entry = _claim_entry(job, authorization_fingerprint, now, attempt, lease_minutes, previous_receipts)
    state["entries"][key] = entry
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {"claimed": False, "status": persisted.get("status"), "hard_blocks": persisted.get("hard_blocks", []), "publication_blocked": False}
    return {"claimed": True, "status": "CLAIMED", "hard_blocks": [], "entry": _clone(entry), "publication_blocked": False}


def mark_network_started(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": blocks}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state["entries"].get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return {"persisted": False, "status": "HOLD_PRE_NETWORK_RECEIPT", "hard_blocks": ["SEALED_ENTRY_MISSING"]}
    checked = validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_PRE_NETWORK_RECEIPT", "hard_blocks": checked.get("hard_blocks", [])}
    receipt = _latest_receipt(entry)
    if not receipt or _clean(receipt.get("status")).upper() != "CLAIMED":
        return {"persisted": False, "status": "HOLD_PRE_NETWORK_RECEIPT", "hard_blocks": ["SEALED_RECEIPT_NOT_CLAIMED"]}
    receipt["status"] = "NETWORK_CALL_STARTED"
    receipt["network_started_at"] = runtime._iso(runtime._dt(now))
    receipt["updated_at"] = receipt["network_started_at"]
    receipt["receipt_fingerprint_sha256"] = _receipt_fingerprint(receipt)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    return runtime.persist_checkpoint_state_cas(
        repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp,
    )


def transition_sealed(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    status: str,
    last_result_status: str,
    retry_after_at: str | None = None,
    materialization_fingerprint_sha256: str | None = None,
) -> dict[str, Any]:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": blocks}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state["entries"].get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": ["SEALED_ENTRY_MISSING"]}
    checked = validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": checked.get("hard_blocks", [])}
    receipt = _latest_receipt(entry)
    if not receipt or _clean(receipt.get("status")).upper() != "NETWORK_CALL_STARTED":
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": ["SEALED_RECEIPT_NETWORK_START_PROOF_REQUIRED"]}
    if materialization_fingerprint_sha256 and not RECEIPT_FINGERPRINT_RE.fullmatch(materialization_fingerprint_sha256):
        return {"persisted": False, "status": "HOLD_CHECKPOINT_TRANSITION", "hard_blocks": ["SEALED_RECEIPT_MATERIALIZATION_FINGERPRINT_INVALID"]}
    now_iso = runtime._iso(runtime._dt(now))
    entry["status"] = status
    entry["last_result_status"] = last_result_status
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = retry_after_at
    entry["completed_at"] = now_iso if status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"} else None
    receipt["status"] = status
    receipt["provider_result_status"] = last_result_status
    receipt["checkpoint_status"] = status
    receipt["updated_at"] = now_iso
    receipt["materialization_fingerprint_sha256"] = materialization_fingerprint_sha256
    receipt["receipt_fingerprint_sha256"] = _receipt_fingerprint(receipt)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    return runtime.persist_checkpoint_state_cas(
        repo_root, channel, state, expected_previous_fingerprint_sha256=previous_fp,
    )


def _summary(job: dict[str, Any], status: str, *, checkpoint_status: str | None = None, blocks: list[str] | None = None, issues: list[Any] | None = None, authorization_fingerprint: str | None = None) -> dict[str, Any]:
    result = runtime._summary(job, status, checkpoint_status=checkpoint_status, blocks=blocks, issues=issues)
    result["authorization_fingerprint"] = authorization_fingerprint
    return result


def execute_plan_durably_sealed(
    plan: dict[str, Any],
    channel: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    authorization_fingerprint: str,
    repo_root: Path,
    now: str,
    credential_resolver: CredentialResolver = runtime._resolver,
    transport_call: TransportCall = runtime.native_metrics_transport.collect_and_materialize,
    persist_bundle_call: PersistBundleCall = runtime.observed_metrics_collector.persist_bundle,
    lease_minutes: int = runtime.DEFAULT_LEASE_MINUTES,
    retry_minutes: int = runtime.DEFAULT_RETRY_MINUTES,
    auth_retry_minutes: int = runtime.DEFAULT_AUTH_RETRY_MINUTES,
    ttl_hours: int = 72,
    min_samples: int = 3,
) -> dict[str, Any]:
    if not all(isinstance(value, dict) for value in (plan, channel, access_attestation)):
        raise TypeError("plan, channel and access_attestation must be mappings")
    if not _valid_authorization_fingerprint(authorization_fingerprint):
        return {
            "schema_version": SCHEMA_VERSION,
            "runtime_id": RECEIPT_ID,
            "status": "HOLD_AUTHORIZATION_CONTEXT",
            "hard_blocks": ["AUTHORIZATION_FINGERPRINT_INVALID"],
            "results": [],
            "publication_blocked": False,
        }
    now_dt = runtime._dt(now)
    if plan.get("status") != "HARVEST_READY":
        return {"schema_version": SCHEMA_VERSION, "runtime_id": RECEIPT_ID, "status": "NO_EXECUTION", "hard_blocks": [], "results": [], "publication_blocked": False, "authorization_fingerprint": authorization_fingerprint}

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
    if not supplied_plan_fp or supplied_plan_fp != runtime._digest(unsigned_plan):
        blocks.append("PLAN_FINGERPRINT_MISMATCH")
    _state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    blocks.extend(state_blocks)
    if blocks:
        return {"schema_version": SCHEMA_VERSION, "runtime_id": RECEIPT_ID, "status": "HOLD_HARVEST_RUNTIME", "hard_blocks": sorted(set(blocks)), "results": [], "publication_blocked": False, "authorization_fingerprint": authorization_fingerprint}

    observation_path = runtime.observed_metrics_collector.expected_observation_store_path(channel)
    snapshot_path = runtime.durable_feedback_snapshot.expected_snapshot_path(channel)
    credentials: dict[str, str] = {}
    results: list[dict[str, Any]] = []

    for job in plan.get("jobs", []):
        if not isinstance(job, dict):
            continue
        job_blocks = runtime._job_blocks(plan, channel, job)
        if job_blocks:
            results.append(_summary(job, "HOLD_JOB_TAMPERED", blocks=job_blocks, authorization_fingerprint=authorization_fingerprint))
            continue
        claim = claim_checkpoint_sealed(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            lease_minutes=lease_minutes,
        )
        if claim.get("claimed") is not True:
            results.append(_summary(
                job,
                _clean(claim.get("status")) or "HOLD_CHECKPOINT",
                checkpoint_status=_clean((claim.get("entry") or {}).get("status")) or None,
                blocks=claim.get("hard_blocks", []),
                authorization_fingerprint=authorization_fingerprint,
            ))
            continue

        pre_network = mark_network_started(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
        )
        if pre_network.get("persisted") is not True:
            results.append(_summary(
                job,
                "HOLD_PRE_NETWORK_RECEIPT_PERSISTENCE",
                checkpoint_status="IN_FLIGHT",
                blocks=pre_network.get("hard_blocks", []) or ["NETWORK_START_RECEIPT_NOT_PERSISTED"],
                authorization_fingerprint=authorization_fingerprint,
            ))
            continue

        env_name = _clean(job.get("credential_env_name"))
        if env_name not in credentials:
            credentials[env_name] = _clean(credential_resolver(env_name))
        credential = credentials[env_name]
        existing_store = runtime._load_optional(repo_root, observation_path)
        existing_snapshot = runtime._load_optional(repo_root, snapshot_path)
        try:
            transport_result = transport_call(
                channel, runtime._publication(job), access_attestation, credential,
                now=now, existing_store=existing_store, existing_snapshot=existing_snapshot,
                graph_version=_clean(job.get("graph_version")) or runtime.native_metrics_transport.DEFAULT_GRAPH_VERSION,
                ttl_hours=ttl_hours, min_samples=min_samples,
            )
        except Exception as exc:
            transport_result = {"status": "RETRY_LATER", "hard_blocks": [], "metric_issues": [{"code": "TRANSPORT_EXCEPTION", "type": type(exc).__name__}]}
        if not isinstance(transport_result, dict):
            transport_result = {"status": "HOLD_TRANSPORT", "hard_blocks": ["TRANSPORT_RESULT_INVALID"], "metric_issues": []}
        if credential and credential in _canonical(transport_result):
            transition = transition_sealed(
                repo_root, channel, job,
                authorization_fingerprint=authorization_fingerprint,
                now=now, status="HOLD_ANALYTICS", last_result_status="HOLD_SECRET_EXPOSURE",
            )
            results.append(_summary(job, "HOLD_SECRET_EXPOSURE", checkpoint_status="HOLD_ANALYTICS" if transition.get("persisted") else "TRANSITION_FAILED", blocks=["TRANSPORT_SECRET_EXPOSURE"], authorization_fingerprint=authorization_fingerprint))
            continue

        status = _clean(transport_result.get("status")).upper() or "HOLD_TRANSPORT"
        issues = transport_result.get("metric_issues") if isinstance(transport_result.get("metric_issues"), list) else []
        result_blocks = transport_result.get("hard_blocks") if isinstance(transport_result.get("hard_blocks"), list) else []
        checkpoint_status = "HOLD_ANALYTICS"
        outward_status = status
        retry_after: str | None = None
        materialization_fp: str | None = None

        if status == "COLLECTED_AND_MATERIALIZED":
            bundle = transport_result.get("materialization") if isinstance(transport_result.get("materialization"), dict) else None
            if bundle is None or bundle.get("hard_blocks"):
                outward_status = "HOLD_OBSERVATION"
                checkpoint_status = "HOLD_ANALYTICS"
                result_blocks = list((bundle or {}).get("hard_blocks", [])) or ["MATERIALIZATION_MISSING"]
            else:
                materialization_fp = _digest(bundle)
                try:
                    persisted = persist_bundle_call(repo_root, bundle)
                except Exception:
                    persisted = {"persisted": False}
                if persisted.get("persisted") is True:
                    checkpoint_status = "COMPLETED"
                else:
                    outward_status = "RECOVERY_REQUIRED"
                    checkpoint_status = "RECOVERY_REQUIRED"
                    retry_after = runtime._iso(now_dt + timedelta(minutes=retry_minutes))
                    result_blocks = ["OBSERVATION_PERSISTENCE_NOT_CONFIRMED"]
        elif status == "NO_OBSERVED_METRICS":
            checkpoint_status = "COMPLETED_NO_DATA"
        elif status == "RETRY_LATER":
            checkpoint_status = "RETRY_WAIT"
            retry_after = runtime._iso(now_dt + timedelta(minutes=retry_minutes))
        elif status == "BLOCKED_AUTH":
            checkpoint_status = "BLOCKED_AUTH"
            retry_after = runtime._iso(now_dt + timedelta(minutes=auth_retry_minutes))

        transition = transition_sealed(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            status=checkpoint_status,
            last_result_status=outward_status,
            retry_after_at=retry_after,
            materialization_fingerprint_sha256=materialization_fp,
        )
        if transition.get("persisted") is not True:
            results.append(_summary(job, "HOLD_CHECKPOINT_TRANSITION", checkpoint_status="TRANSITION_FAILED", blocks=transition.get("hard_blocks", []), issues=issues, authorization_fingerprint=authorization_fingerprint))
            continue
        results.append(_summary(job, outward_status, checkpoint_status=checkpoint_status, blocks=result_blocks, issues=issues, authorization_fingerprint=authorization_fingerprint))

    final_state, final_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    result = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RECEIPT_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": "HARVEST_RUNTIME_EXECUTED" if not final_blocks else "HOLD_CHECKPOINT_STATE",
        "hard_blocks": final_blocks,
        "publication_blocked": False,
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_state_path": runtime.expected_checkpoint_state_path(channel),
        "checkpoint_state_fingerprint_sha256": _clean(final_state.get("state_fingerprint_sha256")) or None,
        "results": results,
        "guards": {
            "authorization_sealed_receipts": True,
            "authorization_fingerprint_persisted_before_network": True,
            "network_start_receipt_persisted_before_provider_call": True,
            "blind_retry_after_ambiguous_sealed_network_call": False,
            "provider_payload_persisted_in_receipt": False,
            "credential_value_persisted_in_receipt": False,
            "publication_blocked_by_analytics": False,
            "zero_paid_dependency": True,
        },
    }
    result["runtime_fingerprint_sha256"] = _digest(result)
    return result


@contextmanager
def authorization_sealed_execution(authorization_fingerprint: str | None) -> Iterator[None]:
    """Temporarily route the existing metrics runtime through sealed receipts.

    The context is process-local, synchronous and restored in ``finally``. It is
    intentionally activated only by the already capability/access/credential-gated
    fleet execution path after the authorization fingerprint has been verified.
    """
    global _ACTIVE_FINGERPRINT
    fingerprint = _clean(authorization_fingerprint)
    if not fingerprint:
        yield
        return
    if not _valid_authorization_fingerprint(fingerprint):
        raise ValueError("invalid authorization fingerprint")
    if _ACTIVE_FINGERPRINT and not hmac.compare_digest(_ACTIVE_FINGERPRINT, fingerprint):
        raise RuntimeError("another authorization-sealed harvest context is active")

    previous_active = _ACTIVE_FINGERPRINT
    original_execute = runtime.execute_plan_durably

    def sealed_execute(plan: dict[str, Any], channel: dict[str, Any], access_attestation: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return execute_plan_durably_sealed(
            plan, channel, access_attestation,
            authorization_fingerprint=fingerprint,
            **kwargs,
        )

    _ACTIVE_FINGERPRINT = fingerprint
    runtime.execute_plan_durably = sealed_execute
    try:
        yield
    finally:
        runtime.execute_plan_durably = original_execute
        _ACTIVE_FINGERPRINT = previous_active
