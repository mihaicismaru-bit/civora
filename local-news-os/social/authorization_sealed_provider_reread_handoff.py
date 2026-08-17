#!/usr/bin/env python3
"""Durable single-use authorization handoff for ambiguous metrics provider re-reads.

A provider-facing observed-metrics request that crashed after NETWORK_CALL_STARTED is
ambiguous. The authorization-sealed recovery layer first checks the durable observed
ledger and leaves the checkpoint in RECOVERY_REQUIRED when no covering observation
exists. This module adds the explicit bridge from that state to a future provider
re-read without turning recovery into an implicit retry path.

The bridge has two separate operations:

* ``issue_provider_reread_handoff`` validates the current sealed checkpoint/receipt,
  re-runs network-free ledger reconciliation, and persists an AUTHORIZED handoff.
  It does not alter the checkpoint and cannot make a provider request eligible.
* ``consume_provider_reread_handoff`` revalidates the same authorization, receipt,
  job and observation-ledger context, marks the handoff CONSUMED first, then moves
  the checkpoint to RETRY_WAIT. Because consumption is persisted before checkpoint
  eligibility, a crash between those writes fails closed and requires a new explicit
  authorization instead of risking a double read.

Handoffs are isolated per instance/channel, expire, are SHA-256 sealed, and are
single-use. Credential values and raw provider payloads are neither accepted nor
persisted. Analytics remains advisory-only and never blocks editorial publication.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any, Callable

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_harvest_recovery as recovery
import metrics_harvest_runtime as runtime

SCHEMA_VERSION = "1.0"
HANDOFF_RUNTIME_ID = "local-news-os-authorization-sealed-provider-reread-handoff"
DEFAULT_TTL_MINUTES = 30
MAX_TTL_MINUTES = 120
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_REASON_CODES = {
    "AMBIGUOUS_PROVIDER_READ_RETRY_APPROVED",
    "OPERATOR_VERIFIED_NO_DURABLE_OBSERVATION",
    "PROVIDER_CONFIRMATION_UNAVAILABLE_RETRY_APPROVED",
}

CheckpointPersistCall = Callable[..., dict[str, Any]]


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _entry_fingerprint(entry: dict[str, Any]) -> str:
    unsigned = _clone(entry)
    unsigned.pop("handoff_fingerprint_sha256", None)
    return _digest(unsigned)


def _store_fingerprint(store: dict[str, Any]) -> str:
    unsigned = _clone(store)
    unsigned.pop("store_fingerprint_sha256", None)
    return _digest(unsigned)


def _guards() -> dict[str, Any]:
    return {
        "explicit_authorization_required": True,
        "single_use_handoff": True,
        "handoff_consumed_before_retry_eligibility": True,
        "observation_ledger_rechecked_before_consume": True,
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def expected_handoff_store_path(channel: dict[str, Any]) -> str:
    state_path = PurePosixPath(runtime.expected_checkpoint_state_path(channel))
    if state_path.is_absolute() or ".." in state_path.parts:
        raise ValueError("unsafe checkpoint state path")
    stem = state_path.name[:-5] if state_path.name.endswith(".json") else state_path.name
    return state_path.with_name(f"{stem}_provider_reread_handoffs.json").as_posix()


def empty_handoff_store(channel: dict[str, Any]) -> dict[str, Any]:
    store = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_handoff_store_path(channel),
        "entries": {},
        "guards": _guards(),
    }
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return store


def _decision_blocks(decision_reference: Any, reason_code: Any) -> list[str]:
    blocks: list[str] = []
    reference = _clean(decision_reference)
    reason = _clean(reason_code).upper()
    if not reference or len(reference) > 160 or any(ord(ch) < 32 for ch in reference):
        blocks.append("REREAD_DECISION_REFERENCE_INVALID")
    if reason not in ALLOWED_REASON_CODES:
        blocks.append("REREAD_REASON_CODE_NOT_ALLOWED")
    return sorted(set(blocks))


def _entry_blocks(channel: dict[str, Any], entry: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(entry.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_HANDOFF_SCHEMA_VERSION")
    if _clean(entry.get("runtime_id")) != HANDOFF_RUNTIME_ID:
        blocks.append("REREAD_HANDOFF_RUNTIME_ID")
    if _clean(entry.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("REREAD_HANDOFF_INSTANCE_MISMATCH")
    if _clean(entry.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("REREAD_HANDOFF_CHANNEL_MISMATCH")
    if _clean(entry.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("REREAD_HANDOFF_PLATFORM_MISMATCH")
    if not _clean(entry.get("handoff_id")).startswith("reread-handoff:"):
        blocks.append("REREAD_HANDOFF_ID_INVALID")
    if not _clean(entry.get("checkpoint_key")).startswith("harvest:"):
        blocks.append("REREAD_HANDOFF_CHECKPOINT_KEY_INVALID")
    if not HEX64_RE.fullmatch(_clean(entry.get("job_fingerprint_sha256"))):
        blocks.append("REREAD_HANDOFF_JOB_FINGERPRINT_INVALID")
    if not receipt._valid_authorization_fingerprint(entry.get("authorization_fingerprint")):
        blocks.append("REREAD_HANDOFF_AUTHORIZATION_FINGERPRINT_INVALID")
    if not HEX64_RE.fullmatch(_clean(entry.get("sealed_receipt_fingerprint_sha256"))):
        blocks.append("REREAD_HANDOFF_RECEIPT_FINGERPRINT_INVALID")
    store_fp = _clean(entry.get("observation_store_fingerprint_sha256"))
    if store_fp and not HEX64_RE.fullmatch(store_fp):
        blocks.append("REREAD_HANDOFF_OBSERVATION_STORE_FINGERPRINT_INVALID")
    if not HEX64_RE.fullmatch(_clean(entry.get("recovery_evidence_fingerprint_sha256"))):
        blocks.append("REREAD_HANDOFF_RECOVERY_EVIDENCE_FINGERPRINT_INVALID")
    if not _clean(entry.get("publication_id")) or not _clean(entry.get("remote_publication_id")):
        blocks.append("REREAD_HANDOFF_PUBLICATION_PROOF_INCOMPLETE")
    if not _clean(entry.get("metric_source")):
        blocks.append("REREAD_HANDOFF_METRIC_SOURCE_REQUIRED")
    try:
        target_attempt = int(entry.get("target_attempt") or 0)
    except (TypeError, ValueError):
        target_attempt = 0
    if target_attempt <= 1:
        blocks.append("REREAD_HANDOFF_TARGET_ATTEMPT_INVALID")
    status = _clean(entry.get("status")).upper()
    if status not in {"AUTHORIZED", "CONSUMED"}:
        blocks.append("REREAD_HANDOFF_STATUS_INVALID")
    try:
        issued_at = runtime._dt(_clean(entry.get("issued_at")))
        expires_at = runtime._dt(_clean(entry.get("expires_at")))
        if expires_at <= issued_at:
            blocks.append("REREAD_HANDOFF_EXPIRY_INVALID")
    except ValueError:
        blocks.append("REREAD_HANDOFF_TIME_INVALID")
    consumed_at = _clean(entry.get("consumed_at"))
    consumption_id = _clean(entry.get("consumption_id"))
    if status == "AUTHORIZED" and (consumed_at or consumption_id):
        blocks.append("REREAD_HANDOFF_AUTHORIZED_CONSUMPTION_STATE_INVALID")
    if status == "CONSUMED":
        if not consumed_at or not consumption_id.startswith("reread-consumption:"):
            blocks.append("REREAD_HANDOFF_CONSUMPTION_PROOF_REQUIRED")
        else:
            try:
                runtime._dt(consumed_at)
            except ValueError:
                blocks.append("REREAD_HANDOFF_CONSUMED_AT_INVALID")
    blocks.extend(_decision_blocks(entry.get("decision_reference"), entry.get("reason_code")))
    guards = entry.get("guards") if isinstance(entry.get("guards"), dict) else {}
    for key, expected in _guards().items():
        if guards.get(key) is not expected:
            blocks.append("REREAD_HANDOFF_GUARD:" + key)
    supplied = _clean(entry.get("handoff_fingerprint_sha256"))
    if not HEX64_RE.fullmatch(supplied) or supplied != _entry_fingerprint(entry):
        blocks.append("REREAD_HANDOFF_FINGERPRINT_MISMATCH")
    if runtime._entry_has_forbidden_fields(entry):
        blocks.append("REREAD_HANDOFF_FORBIDDEN_FIELD")
    return sorted(set(blocks))


def validate_handoff_store(channel: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(channel, dict) or not isinstance(store, dict):
        raise TypeError("channel and store must be mappings")
    blocks: list[str] = []
    if _clean(store.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_HANDOFF_STORE_SCHEMA_VERSION")
    if _clean(store.get("runtime_id")) != HANDOFF_RUNTIME_ID:
        blocks.append("REREAD_HANDOFF_STORE_RUNTIME_ID")
    if _clean(store.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("REREAD_HANDOFF_STORE_INSTANCE_MISMATCH")
    if _clean(store.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("REREAD_HANDOFF_STORE_CHANNEL_MISMATCH")
    if _clean(store.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("REREAD_HANDOFF_STORE_PLATFORM_MISMATCH")
    try:
        expected_path = expected_handoff_store_path(channel)
    except ValueError:
        expected_path = ""
        blocks.append("REREAD_HANDOFF_STORE_PATH_INVALID")
    if _clean(store.get("storage_path")) != expected_path:
        blocks.append("REREAD_HANDOFF_STORE_PATH_MISMATCH")
    entries = store.get("entries")
    if not isinstance(entries, dict):
        blocks.append("REREAD_HANDOFF_STORE_ENTRIES_INVALID")
        entries = {}
    active_by_checkpoint: dict[str, int] = {}
    for key, entry in entries.items():
        if not isinstance(key, str) or not isinstance(entry, dict):
            blocks.append("REREAD_HANDOFF_STORE_ENTRY_INVALID")
            continue
        if _clean(entry.get("handoff_id")) != key:
            blocks.append("REREAD_HANDOFF_STORE_KEY_MISMATCH")
        blocks.extend(_entry_blocks(channel, entry))
        if _clean(entry.get("status")).upper() == "AUTHORIZED":
            checkpoint = _clean(entry.get("checkpoint_key"))
            active_by_checkpoint[checkpoint] = active_by_checkpoint.get(checkpoint, 0) + 1
    if any(count > 1 for count in active_by_checkpoint.values()):
        blocks.append("REREAD_HANDOFF_MULTIPLE_ACTIVE_FOR_CHECKPOINT")
    guards = store.get("guards") if isinstance(store.get("guards"), dict) else {}
    for key, expected in _guards().items():
        if guards.get(key) is not expected:
            blocks.append("REREAD_HANDOFF_STORE_GUARD:" + key)
    supplied = _clean(store.get("store_fingerprint_sha256"))
    if not HEX64_RE.fullmatch(supplied) or supplied != _store_fingerprint(store):
        blocks.append("REREAD_HANDOFF_STORE_FINGERPRINT_MISMATCH")
    if runtime._entry_has_forbidden_fields(store):
        blocks.append("REREAD_HANDOFF_STORE_FORBIDDEN_FIELD")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def load_handoff_store(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    try:
        relative = expected_handoff_store_path(channel)
        target = repo_root.joinpath(*PurePosixPath(relative).parts)
    except ValueError as exc:
        return {}, ["REREAD_HANDOFF_STORE_PATH_INVALID:" + str(exc)], False
    if not target.exists():
        return empty_handoff_store(channel), [], False
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, ["REREAD_HANDOFF_STORE_READ_INVALID:" + str(exc)], True
    if not isinstance(value, dict):
        return {}, ["REREAD_HANDOFF_STORE_NOT_OBJECT"], True
    checked = validate_handoff_store(channel, value)
    return value, list(checked.get("hard_blocks", [])), True


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f".tmp.{os.getpid()}")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def persist_handoff_store_cas(
    repo_root: Path,
    channel: dict[str, Any],
    store: dict[str, Any],
    *,
    expected_previous_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    checked = validate_handoff_store(channel, store)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_TARGET", "hard_blocks": checked.get("hard_blocks", [])}
    relative = expected_handoff_store_path(channel)
    target = repo_root.joinpath(*PurePosixPath(relative).parts)
    try:
        with runtime._StateLock(target):
            existing, blocks, existed = load_handoff_store(repo_root, channel)
            if blocks:
                return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_EXISTING", "hard_blocks": blocks, "path": relative}
            actual = _clean(existing.get("store_fingerprint_sha256")) or None
            expected = _clean(expected_previous_fingerprint_sha256) or None
            canonical_empty = _clean(empty_handoff_store(channel).get("store_fingerprint_sha256")) or None
            matches = actual == expected if existed else expected in {None, canonical_empty}
            if not matches:
                return {
                    "persisted": False,
                    "status": "HOLD_REREAD_HANDOFF_CAS_CONFLICT",
                    "hard_blocks": ["REREAD_HANDOFF_COMPARE_AND_SWAP_CONFLICT"],
                    "path": relative,
                }
            target_fp = _clean(store.get("store_fingerprint_sha256"))
            if existed and actual == target_fp:
                return {"persisted": True, "status": "IDEMPOTENT_REREAD_HANDOFF_STORE", "hard_blocks": [], "path": relative, "written": False}
            _atomic_write_json(target, store)
    except BlockingIOError:
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_LOCK_BUSY", "hard_blocks": ["REREAD_HANDOFF_STORE_LOCK_BUSY"], "path": relative}
    persisted, blocks, _ = load_handoff_store(repo_root, channel)
    if blocks or _clean(persisted.get("store_fingerprint_sha256")) != _clean(store.get("store_fingerprint_sha256")):
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_READBACK", "hard_blocks": blocks or ["REREAD_HANDOFF_READBACK_FINGERPRINT_MISMATCH"], "path": relative}
    return {"persisted": True, "status": "REREAD_HANDOFF_STORE_PERSISTED", "hard_blocks": [], "path": relative, "written": True}


def _hold(job: dict[str, Any], status: str, blocks: list[str], *, handoff_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "status": status,
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "handoff_id": handoff_id,
        "provider_reread_eligible": False,
        "provider_network_calls_performed": False,
        "publication_blocked": False,
        "durable_paths": [],
        "hard_blocks": sorted(set(blocks)),
        "guards": _guards(),
    }


def _current_recovery_entry(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None, list[str]]:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return None, None, None, blocks
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return None, None, previous_fp, ["REREAD_HANDOFF_RECOVERY_ENTRY_MISSING"]
    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, previous_fp, ["REREAD_HANDOFF_RECOVERY_REQUIRED_EXPECTED"]
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return state, entry, previous_fp, ["REREAD_HANDOFF_JOB_FINGERPRINT_CONFLICT"]
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return state, entry, previous_fp, list(checked.get("hard_blocks", []))
    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, previous_fp, ["REREAD_HANDOFF_RECOVERY_RECEIPT_EXPECTED"]
    return state, entry, previous_fp, []


def _handoff_id(
    job: dict[str, Any],
    authorization_fingerprint: str,
    sealed_receipt_fingerprint: str,
    observation_store_fingerprint: str | None,
    decision_reference: str,
    reason_code: str,
) -> str:
    material = {
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "sealed_receipt_fingerprint_sha256": sealed_receipt_fingerprint,
        "observation_store_fingerprint_sha256": observation_store_fingerprint,
        "decision_reference": decision_reference,
        "reason_code": reason_code,
    }
    return "reread-handoff:" + _digest(material)[:40]


def issue_provider_reread_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    decision_reference: str,
    reason_code: str,
    now: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> dict[str, Any]:
    """Persist an explicit re-read authorization without changing retry eligibility."""
    if not all(isinstance(value, dict) for value in (channel, job)):
        raise TypeError("channel and job must be mappings")
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _hold(job, "HOLD_REREAD_HANDOFF_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    decision_blocks = _decision_blocks(decision_reference, reason_code)
    if decision_blocks:
        return _hold(job, "HOLD_REREAD_HANDOFF_DECISION", decision_blocks)
    if not isinstance(ttl_minutes, int) or ttl_minutes <= 0 or ttl_minutes > MAX_TTL_MINUTES:
        return _hold(job, "HOLD_REREAD_HANDOFF_TTL", ["REREAD_HANDOFF_TTL_INVALID"])
    try:
        now_dt = runtime._dt(now)
    except ValueError:
        return _hold(job, "HOLD_REREAD_HANDOFF_TIME", ["REREAD_HANDOFF_NOW_INVALID"])

    reconciled = recovery.reconcile_recovery(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        authorize_provider_reread=False,
    )
    if reconciled.get("status") == "RECOVERED_COMPLETED":
        result = _hold(job, "NO_REREAD_NEEDED_DURABLE_OBSERVATION", [])
        result["hard_blocks"] = []
        result["durable_paths"] = list(reconciled.get("durable_paths", []))
        return result
    if reconciled.get("status") != "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION":
        return _hold(job, "HOLD_REREAD_HANDOFF_RECOVERY", list(reconciled.get("hard_blocks", [])) or [_clean(reconciled.get("status")) or "RECOVERY_RECONCILIATION_FAILED"])

    state, entry, _checkpoint_fp, checkpoint_blocks = _current_recovery_entry(
        repo_root, channel, job, authorization_fingerprint,
    )
    if checkpoint_blocks or not isinstance(entry, dict):
        return _hold(job, "HOLD_REREAD_HANDOFF_CHECKPOINT", checkpoint_blocks)
    latest = receipt._latest_receipt(entry)
    if not latest:
        return _hold(job, "HOLD_REREAD_HANDOFF_RECEIPT", ["REREAD_HANDOFF_RECOVERY_RECEIPT_EXPECTED"])
    sealed_receipt_fp = _clean(latest.get("receipt_fingerprint_sha256"))
    evidence = reconciled.get("recovery_evidence") if isinstance(reconciled.get("recovery_evidence"), dict) else {}
    evidence_fp = _clean(evidence.get("recovery_evidence_fingerprint_sha256"))
    observation_store_fp = _clean(evidence.get("observation_store_fingerprint_sha256")) or None
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    reason = _clean(reason_code).upper()
    decision = _clean(decision_reference)
    handoff_id = _handoff_id(job, authorization_fingerprint, sealed_receipt_fp, observation_store_fp, decision, reason)

    store, store_blocks, _ = load_handoff_store(repo_root, channel)
    if store_blocks:
        return _hold(job, "HOLD_REREAD_HANDOFF_STORE", store_blocks, handoff_id=handoff_id)
    previous_store_fp = _clean(store.get("store_fingerprint_sha256")) or None
    existing = store.get("entries", {}).get(handoff_id)
    if isinstance(existing, dict):
        checked = _entry_blocks(channel, existing)
        if checked:
            return _hold(job, "HOLD_REREAD_HANDOFF_EXISTING_TAMPERED", checked, handoff_id=handoff_id)
        result = _hold(job, "REREAD_HANDOFF_ALREADY_" + _clean(existing.get("status")).upper(), [], handoff_id=handoff_id)
        result["hard_blocks"] = []
        result["handoff"] = _clone(existing)
        result["durable_paths"] = [expected_handoff_store_path(channel)]
        return result

    for other in store.get("entries", {}).values():
        if not isinstance(other, dict) or _clean(other.get("checkpoint_key")) != runtime.checkpoint_key(job):
            continue
        if _clean(other.get("status")).upper() != "AUTHORIZED":
            continue
        try:
            if runtime._dt(_clean(other.get("expires_at"))) > now_dt:
                return _hold(job, "HOLD_REREAD_HANDOFF_ACTIVE_EXISTS", ["REREAD_HANDOFF_ACTIVE_AUTHORIZATION_EXISTS"], handoff_id=_clean(other.get("handoff_id")) or None)
        except ValueError:
            return _hold(job, "HOLD_REREAD_HANDOFF_EXISTING_TAMPERED", ["REREAD_HANDOFF_TIME_INVALID"], handoff_id=_clean(other.get("handoff_id")) or None)

    handoff = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "handoff_id": handoff_id,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "metric_source": _clean(job.get("source")),
        "authorization_fingerprint": authorization_fingerprint,
        "sealed_receipt_fingerprint_sha256": sealed_receipt_fp,
        "observation_store_fingerprint_sha256": observation_store_fp,
        "recovery_evidence_fingerprint_sha256": evidence_fp,
        "decision_reference": decision,
        "reason_code": reason,
        "target_attempt": int(entry.get("attempt") or 0) + 1,
        "status": "AUTHORIZED",
        "issued_at": runtime._iso(now_dt),
        "expires_at": runtime._iso(now_dt + timedelta(minutes=ttl_minutes)),
        "consumed_at": None,
        "consumption_id": None,
        "guards": _guards(),
    }
    handoff["handoff_fingerprint_sha256"] = _entry_fingerprint(handoff)
    store["entries"][handoff_id] = handoff
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    persisted = persist_handoff_store_cas(
        repo_root,
        channel,
        store,
        expected_previous_fingerprint_sha256=previous_store_fp,
    )
    if persisted.get("persisted") is not True:
        return _hold(job, persisted.get("status") or "HOLD_REREAD_HANDOFF_PERSISTENCE", list(persisted.get("hard_blocks", [])), handoff_id=handoff_id)
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "status": "REREAD_HANDOFF_AUTHORIZED",
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "handoff_id": handoff_id,
        "handoff": _clone(handoff),
        "provider_reread_eligible": False,
        "provider_network_calls_performed": False,
        "publication_blocked": False,
        "durable_paths": [expected_handoff_store_path(channel)],
        "hard_blocks": [],
        "guards": _guards(),
    }


def _consumption_id(handoff: dict[str, Any], now: str) -> str:
    material = {
        "handoff_id": _clean(handoff.get("handoff_id")),
        "handoff_fingerprint_sha256": _clean(handoff.get("handoff_fingerprint_sha256")),
        "authorization_fingerprint": _clean(handoff.get("authorization_fingerprint")),
        "target_attempt": handoff.get("target_attempt"),
        "consumed_at": runtime._iso(runtime._dt(now)),
    }
    return "reread-consumption:" + _digest(material)[:40]


def consume_provider_reread_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    handoff_id: str,
    authorization_fingerprint: str,
    now: str,
    checkpoint_persist_call: CheckpointPersistCall = recovery._persist_reconciled_state,
) -> dict[str, Any]:
    """Consume a durable handoff once, then make the sealed checkpoint retry-eligible."""
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _hold(job, "HOLD_REREAD_HANDOFF_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"], handoff_id=handoff_id)
    try:
        now_dt = runtime._dt(now)
    except ValueError:
        return _hold(job, "HOLD_REREAD_HANDOFF_TIME", ["REREAD_HANDOFF_NOW_INVALID"], handoff_id=handoff_id)

    store, store_blocks, _ = load_handoff_store(repo_root, channel)
    if store_blocks:
        return _hold(job, "HOLD_REREAD_HANDOFF_STORE", store_blocks, handoff_id=handoff_id)
    previous_store_fp = _clean(store.get("store_fingerprint_sha256")) or None
    handoff = store.get("entries", {}).get(_clean(handoff_id))
    if not isinstance(handoff, dict):
        return _hold(job, "HOLD_REREAD_HANDOFF_MISSING", ["REREAD_HANDOFF_NOT_FOUND"], handoff_id=handoff_id)
    entry_blocks = _entry_blocks(channel, handoff)
    if entry_blocks:
        return _hold(job, "HOLD_REREAD_HANDOFF_TAMPERED", entry_blocks, handoff_id=handoff_id)
    if _clean(handoff.get("status")).upper() == "CONSUMED":
        result = _hold(job, "REREAD_HANDOFF_ALREADY_CONSUMED", [], handoff_id=handoff_id)
        result["hard_blocks"] = []
        result["handoff"] = _clone(handoff)
        return result
    if runtime._dt(_clean(handoff.get("expires_at"))) <= now_dt:
        return _hold(job, "HOLD_REREAD_HANDOFF_EXPIRED", ["REREAD_HANDOFF_EXPIRED"], handoff_id=handoff_id)
    if not hmac.compare_digest(_clean(handoff.get("authorization_fingerprint")), authorization_fingerprint):
        return _hold(job, "HOLD_REREAD_HANDOFF_AUTHORIZATION_CHANGED", ["REREAD_HANDOFF_AUTHORIZATION_CONTEXT_CHANGED"], handoff_id=handoff_id)
    if _clean(handoff.get("checkpoint_key")) != runtime.checkpoint_key(job):
        return _hold(job, "HOLD_REREAD_HANDOFF_JOB_CHANGED", ["REREAD_HANDOFF_CHECKPOINT_MISMATCH"], handoff_id=handoff_id)
    if _clean(handoff.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return _hold(job, "HOLD_REREAD_HANDOFF_JOB_CHANGED", ["REREAD_HANDOFF_JOB_FINGERPRINT_MISMATCH"], handoff_id=handoff_id)
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    if _clean(handoff.get("publication_id")) != _clean(job.get("publication_id")) or _clean(handoff.get("remote_publication_id")) != _clean(publication.get("remote_publication_id")):
        return _hold(job, "HOLD_REREAD_HANDOFF_PUBLICATION_CHANGED", ["REREAD_HANDOFF_REMOTE_PUBLICATION_PROOF_MISMATCH"], handoff_id=handoff_id)
    if _clean(handoff.get("metric_source")) != _clean(job.get("source")):
        return _hold(job, "HOLD_REREAD_HANDOFF_SOURCE_CHANGED", ["REREAD_HANDOFF_METRIC_SOURCE_MISMATCH"], handoff_id=handoff_id)

    reconciled = recovery.reconcile_recovery(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        authorize_provider_reread=False,
    )
    if reconciled.get("status") == "RECOVERED_COMPLETED":
        result = _hold(job, "NO_REREAD_NEEDED_DURABLE_OBSERVATION", [], handoff_id=handoff_id)
        result["hard_blocks"] = []
        result["durable_paths"] = list(reconciled.get("durable_paths", []))
        return result
    if reconciled.get("status") != "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION":
        return _hold(job, "HOLD_REREAD_HANDOFF_RECOVERY", list(reconciled.get("hard_blocks", [])) or [_clean(reconciled.get("status")) or "RECOVERY_RECONCILIATION_FAILED"], handoff_id=handoff_id)
    fresh_evidence = reconciled.get("recovery_evidence") if isinstance(reconciled.get("recovery_evidence"), dict) else {}
    fresh_store_fp = _clean(fresh_evidence.get("observation_store_fingerprint_sha256")) or None
    if fresh_store_fp != (_clean(handoff.get("observation_store_fingerprint_sha256")) or None):
        return _hold(job, "HOLD_REREAD_HANDOFF_LEDGER_CONTEXT_CHANGED", ["REREAD_HANDOFF_OBSERVATION_STORE_CHANGED"], handoff_id=handoff_id)

    checkpoint_state, checkpoint_entry, checkpoint_previous_fp, checkpoint_blocks = _current_recovery_entry(
        repo_root, channel, job, authorization_fingerprint,
    )
    if checkpoint_blocks or not isinstance(checkpoint_state, dict) or not isinstance(checkpoint_entry, dict):
        return _hold(job, "HOLD_REREAD_HANDOFF_CHECKPOINT", checkpoint_blocks, handoff_id=handoff_id)
    latest = receipt._latest_receipt(checkpoint_entry)
    if not latest:
        return _hold(job, "HOLD_REREAD_HANDOFF_RECEIPT", ["REREAD_HANDOFF_RECOVERY_RECEIPT_EXPECTED"], handoff_id=handoff_id)
    if not hmac.compare_digest(_clean(handoff.get("sealed_receipt_fingerprint_sha256")), _clean(latest.get("receipt_fingerprint_sha256"))):
        return _hold(job, "HOLD_REREAD_HANDOFF_RECEIPT_CHANGED", ["REREAD_HANDOFF_SEALED_RECEIPT_CHANGED"], handoff_id=handoff_id)
    if int(handoff.get("target_attempt") or 0) != int(checkpoint_entry.get("attempt") or 0) + 1:
        return _hold(job, "HOLD_REREAD_HANDOFF_ATTEMPT_CHANGED", ["REREAD_HANDOFF_TARGET_ATTEMPT_MISMATCH"], handoff_id=handoff_id)

    consumed = _clone(handoff)
    consumed["status"] = "CONSUMED"
    consumed["consumed_at"] = runtime._iso(now_dt)
    consumed["consumption_id"] = _consumption_id(handoff, now)
    consumed["handoff_fingerprint_sha256"] = _entry_fingerprint(consumed)
    store["entries"][handoff_id] = consumed
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    persisted_handoff = persist_handoff_store_cas(
        repo_root,
        channel,
        store,
        expected_previous_fingerprint_sha256=previous_store_fp,
    )
    if persisted_handoff.get("persisted") is not True:
        return _hold(job, persisted_handoff.get("status") or "HOLD_REREAD_HANDOFF_CONSUMPTION", list(persisted_handoff.get("hard_blocks", [])), handoff_id=handoff_id)

    evidence = recovery._recovery_evidence(
        kind="EXPLICIT_SINGLE_USE_PROVIDER_REREAD_HANDOFF",
        store=None,
        observation=None,
        checked_at=runtime._iso(now_dt),
        provider_reread_authorized=True,
    )
    evidence["observation_store_fingerprint_sha256"] = fresh_store_fp
    evidence["handoff_id"] = handoff_id
    evidence["handoff_fingerprint_sha256"] = _clean(consumed.get("handoff_fingerprint_sha256"))
    evidence["consumption_id"] = _clean(consumed.get("consumption_id"))
    evidence["single_use"] = True
    evidence.pop("recovery_evidence_fingerprint_sha256", None)
    evidence["recovery_evidence_fingerprint_sha256"] = recovery._digest(evidence)

    persisted_checkpoint = checkpoint_persist_call(
        repo_root,
        channel,
        job,
        checkpoint_state,
        checkpoint_previous_fp,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        target_status="RETRY_WAIT",
        evidence=evidence,
    )
    if persisted_checkpoint.get("persisted") is not True:
        result = _hold(
            job,
            "HOLD_REREAD_CHECKPOINT_AFTER_HANDOFF_CONSUMED",
            list(persisted_checkpoint.get("hard_blocks", [])) or ["REREAD_HANDOFF_CONSUMED_CHECKPOINT_NOT_RETRY_ELIGIBLE"],
            handoff_id=handoff_id,
        )
        result["handoff_consumed"] = True
        result["durable_paths"] = [expected_handoff_store_path(channel)]
        return result

    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "status": "REREAD_HANDOFF_CONSUMED",
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "handoff_id": handoff_id,
        "consumption_id": _clean(consumed.get("consumption_id")),
        "target_attempt": consumed.get("target_attempt"),
        "checkpoint_status": "RETRY_WAIT",
        "provider_reread_eligible": True,
        "provider_network_calls_performed": False,
        "publication_blocked": False,
        "durable_paths": [expected_handoff_store_path(channel), runtime.expected_checkpoint_state_path(channel)],
        "hard_blocks": [],
        "guards": _guards(),
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    issue = sub.add_parser("issue")
    issue.add_argument("channel", type=Path)
    issue.add_argument("job", type=Path)
    issue.add_argument("--repo-root", type=Path, default=Path("."))
    issue.add_argument("--authorization-fingerprint", required=True)
    issue.add_argument("--decision-reference", required=True)
    issue.add_argument("--reason-code", required=True, choices=sorted(ALLOWED_REASON_CODES))
    issue.add_argument("--now", required=True)
    issue.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)

    consume = sub.add_parser("consume")
    consume.add_argument("channel", type=Path)
    consume.add_argument("job", type=Path)
    consume.add_argument("--repo-root", type=Path, default=Path("."))
    consume.add_argument("--handoff-id", required=True)
    consume.add_argument("--authorization-fingerprint", required=True)
    consume.add_argument("--now", required=True)

    args = parser.parse_args()
    channel = _load(args.channel)
    job = _load(args.job)
    if args.command == "issue":
        result = issue_provider_reread_handoff(
            args.repo_root,
            channel,
            job,
            authorization_fingerprint=args.authorization_fingerprint,
            decision_reference=args.decision_reference,
            reason_code=args.reason_code,
            now=args.now,
            ttl_minutes=args.ttl_minutes,
        )
    else:
        result = consume_provider_reread_handoff(
            args.repo_root,
            channel,
            job,
            handoff_id=args.handoff_id,
            authorization_fingerprint=args.authorization_fingerprint,
            now=args.now,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if _clean(result.get("status")).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
