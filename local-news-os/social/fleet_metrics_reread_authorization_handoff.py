#!/usr/bin/env python3
"""Durable explicit provider re-read authorization handoff for fleet metrics recovery.

A RECOVERY_REQUIRED observed-metrics checkpoint represents an ambiguous prior provider
request. Fleet recovery may close it from durable local evidence, but must never blindly
re-read the provider. This boundary is the only supported bridge from that unresolved
state to a new read: an explicit decision is sealed against the current authorization,
checkpoint/job identity and latest execution receipt, persisted in a channel-local
single-use handoff store, then consumed only after the observation ledger is checked
again.

The handoff performs no provider I/O and resolves no credential values. Consumption only
moves the checkpoint to RETRY_WAIT so the existing authorization-sealed harvest path can
claim a fresh attempt later. Analytics stays advisory-only and zero-paid-dependency is
mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from datetime import timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_harvest_recovery as recovery
import metrics_harvest_runtime as runtime

SCHEMA_VERSION = "1.0"
HANDOFF_RUNTIME_ID = "local-news-os-fleet-metrics-reread-authorization-handoff"
DECISION = "AUTHORIZE_ONE_PROVIDER_REREAD"
REASON_CODE = "AMBIGUOUS_NETWORK_EXECUTION_NO_DURABLE_OBSERVATION"
DEFAULT_TTL_MINUTES = 30


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _guards() -> dict[str, Any]:
    return {
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "explicit_decision_required": True,
        "single_use_handoff_required": True,
        "authorization_sealed": True,
        "observation_ledger_rechecked_before_retry_eligibility": True,
        "blind_retry_after_ambiguous_network_call": False,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def expected_handoff_store_path(channel: dict[str, Any]) -> str:
    publication_state = channel.get("publication_state") if isinstance(channel.get("publication_state"), dict) else {}
    raw = _clean(publication_state.get("state_path"))
    if not raw:
        raise ValueError("channel publication_state.state_path is required")
    path = runtime._safe_relative(raw)
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    return str(path.with_name(f"{stem}_metrics_reread_handoffs.json"))


def _handoff_authorization_fingerprint(authorization: dict[str, Any]) -> str:
    return "sha256:" + _digest(authorization)


def _record_fingerprint(record: dict[str, Any]) -> str:
    unsigned = _clone(record)
    unsigned.pop("record_fingerprint_sha256", None)
    return _digest(unsigned)


def _store_fingerprint(store: dict[str, Any]) -> str:
    unsigned = _clone(store)
    unsigned.pop("store_fingerprint_sha256", None)
    return _digest(unsigned)


def empty_handoff_store(channel: dict[str, Any]) -> dict[str, Any]:
    store = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_handoff_store_path(channel),
        "records": {},
        "guards": _guards(),
    }
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return store


def _forbidden(value: Any) -> bool:
    if not isinstance(value, (dict, list)):
        return False
    if isinstance(value, list):
        return any(_forbidden(item) for item in value)
    forbidden_tokens = (
        "access_token", "refresh_token", "secret", "password", "api_key", "credential_value",
        "provider_payload", "predicted", "prediction", "estimated", "expected_reach", "expected_views",
    )
    for key, child in value.items():
        normalized = _clean(key).lower().replace("-", "_")
        if any(token in normalized for token in forbidden_tokens):
            return True
        if isinstance(child, (dict, list)) and _forbidden(child):
            return True
    return False


def _record_blocks(record: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(record.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_HANDOFF_SCHEMA_VERSION")
    if _clean(record.get("runtime_id")) != HANDOFF_RUNTIME_ID:
        blocks.append("REREAD_HANDOFF_RUNTIME_ID")
    if not _clean(record.get("handoff_id")):
        blocks.append("REREAD_HANDOFF_ID_REQUIRED")
    status = _clean(record.get("status")).upper()
    if status not in {"AUTHORIZED", "CONSUMED"}:
        blocks.append("REREAD_HANDOFF_STATUS_INVALID")
    authorization = record.get("authorization") if isinstance(record.get("authorization"), dict) else {}
    auth_fp = _clean(record.get("handoff_authorization_fingerprint_sha256"))
    if not receipt._valid_authorization_fingerprint(auth_fp):
        blocks.append("REREAD_HANDOFF_AUTHORIZATION_SEAL_INVALID")
    elif not hmac.compare_digest(auth_fp, _handoff_authorization_fingerprint(authorization)):
        blocks.append("REREAD_HANDOFF_AUTHORIZATION_SEAL_MISMATCH")
    if _clean(authorization.get("decision")) != DECISION:
        blocks.append("REREAD_HANDOFF_DECISION_INVALID")
    if _clean(authorization.get("reason_code")) != REASON_CODE:
        blocks.append("REREAD_HANDOFF_REASON_INVALID")
    if not _clean(authorization.get("decision_id")) or not _clean(authorization.get("decision_actor_ref")):
        blocks.append("REREAD_HANDOFF_EXPLICIT_DECISION_IDENTITY_REQUIRED")
    if not receipt._valid_authorization_fingerprint(authorization.get("authorization_fingerprint")):
        blocks.append("REREAD_HANDOFF_FLEET_AUTHORIZATION_INVALID")
    for key in (
        "instance_id", "channel_id", "platform", "checkpoint_key", "publication_id",
        "remote_publication_id", "job_fingerprint_sha256", "receipt_fingerprint_sha256",
        "checkpoint_state_fingerprint_at_issue", "issued_at", "expires_at",
    ):
        if not _clean(authorization.get(key)):
            blocks.append("REREAD_HANDOFF_AUTHORIZATION_FIELD_MISSING:" + key)
    try:
        issued = runtime._dt(_clean(authorization.get("issued_at")))
        expires = runtime._dt(_clean(authorization.get("expires_at")))
        if expires <= issued:
            blocks.append("REREAD_HANDOFF_EXPIRY_INVALID")
    except ValueError:
        blocks.append("REREAD_HANDOFF_TIME_INVALID")
    if status == "CONSUMED" and not _clean(record.get("consumed_at")):
        blocks.append("REREAD_HANDOFF_CONSUMED_AT_REQUIRED")
    if status == "AUTHORIZED" and _clean(record.get("consumed_at")):
        blocks.append("REREAD_HANDOFF_PREMATURE_CONSUMED_AT")
    if _forbidden(record):
        blocks.append("REREAD_HANDOFF_FORBIDDEN_FIELD")
    supplied = _clean(record.get("record_fingerprint_sha256"))
    if len(supplied) != 64 or supplied != _record_fingerprint(record):
        blocks.append("REREAD_HANDOFF_RECORD_FINGERPRINT_MISMATCH")
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
        expected = expected_handoff_store_path(channel)
    except ValueError:
        expected = ""
        blocks.append("REREAD_HANDOFF_STORE_NAMESPACE_INVALID")
    if _clean(store.get("storage_path")) != expected:
        blocks.append("REREAD_HANDOFF_STORE_NAMESPACE_MISMATCH")
    records = store.get("records")
    if not isinstance(records, dict):
        blocks.append("REREAD_HANDOFF_STORE_RECORDS_INVALID")
        records = {}
    for key, record in records.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            blocks.append("REREAD_HANDOFF_STORE_RECORD_INVALID")
            continue
        if _clean(record.get("handoff_id")) != key:
            blocks.append("REREAD_HANDOFF_STORE_KEY_MISMATCH")
        blocks.extend(_record_blocks(record))
    guards = store.get("guards") if isinstance(store.get("guards"), dict) else {}
    for key, expected_value in _guards().items():
        if guards.get(key) is not expected_value:
            blocks.append("REREAD_HANDOFF_STORE_GUARD:" + key)
    if _forbidden(store):
        blocks.append("REREAD_HANDOFF_STORE_FORBIDDEN_FIELD")
    supplied = _clean(store.get("store_fingerprint_sha256"))
    if len(supplied) != 64 or supplied != _store_fingerprint(store):
        blocks.append("REREAD_HANDOFF_STORE_FINGERPRINT_MISMATCH")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def load_handoff_store(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    try:
        relative = expected_handoff_store_path(channel)
        target = runtime._safe_target(repo_root, relative)
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


def persist_handoff_store_cas(
    repo_root: Path,
    channel: dict[str, Any],
    store: dict[str, Any],
    *,
    expected_previous_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    checked = validate_handoff_store(channel, store)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_TARGET_STORE", "hard_blocks": checked.get("hard_blocks", [])}
    relative = expected_handoff_store_path(channel)
    target = runtime._safe_target(repo_root, relative)
    try:
        with runtime._StateLock(target):
            existing, blocks, existed = load_handoff_store(repo_root, channel)
            if blocks:
                return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_EXISTING_STORE", "hard_blocks": blocks, "path": relative}
            actual = _clean(existing.get("store_fingerprint_sha256")) or None
            expected = _clean(expected_previous_fingerprint_sha256) or None
            canonical_empty = _clean(empty_handoff_store(channel).get("store_fingerprint_sha256")) or None
            matches = actual == expected if existed else expected in {None, canonical_empty}
            if not matches:
                return {
                    "persisted": False,
                    "status": "HOLD_REREAD_HANDOFF_STORE_CAS_CONFLICT",
                    "hard_blocks": ["REREAD_HANDOFF_STORE_COMPARE_AND_SWAP_CONFLICT"],
                    "path": relative,
                }
            target_fp = _clean(store.get("store_fingerprint_sha256"))
            if existed and actual == target_fp:
                return {"persisted": True, "status": "IDEMPOTENT_REREAD_HANDOFF_STORE", "hard_blocks": [], "path": relative, "written": False}
            runtime._atomic_write_json(target, store)
    except BlockingIOError:
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_STORE_LOCK_BUSY", "hard_blocks": ["REREAD_HANDOFF_STORE_LOCK_BUSY"], "path": relative}
    persisted, blocks, _ = load_handoff_store(repo_root, channel)
    if blocks or _clean(persisted.get("store_fingerprint_sha256")) != _clean(store.get("store_fingerprint_sha256")):
        return {"persisted": False, "status": "HOLD_REREAD_HANDOFF_STORE_READBACK", "hard_blocks": blocks or ["REREAD_HANDOFF_STORE_READBACK_FINGERPRINT_MISMATCH"], "path": relative}
    return {"persisted": True, "status": "REREAD_HANDOFF_STORE_PERSISTED", "hard_blocks": [], "path": relative, "written": True}


def _hold(channel: dict[str, Any], job: dict[str, Any], status: str, blocks: list[str]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "status": status,
        "hard_blocks": sorted(set(blocks)),
        "provider_reread_authorized": False,
        "provider_network_call_performed": False,
        "publication_blocked": False,
        "durable_paths": [],
        "guards": _guards(),
    }


def _decision_blocks(decision: dict[str, Any], now: str) -> list[str]:
    blocks: list[str] = []
    if not isinstance(decision, dict):
        return ["REREAD_EXPLICIT_DECISION_REQUIRED"]
    if _clean(decision.get("decision")) != DECISION:
        blocks.append("REREAD_EXPLICIT_DECISION_INVALID")
    if _clean(decision.get("reason_code")) != REASON_CODE:
        blocks.append("REREAD_EXPLICIT_REASON_INVALID")
    if not _clean(decision.get("decision_id")):
        blocks.append("REREAD_EXPLICIT_DECISION_ID_REQUIRED")
    if not _clean(decision.get("decision_actor_ref")):
        blocks.append("REREAD_EXPLICIT_DECISION_ACTOR_REQUIRED")
    decided_at = _clean(decision.get("decided_at"))
    try:
        decided_dt = runtime._dt(decided_at)
        now_dt = runtime._dt(now)
        if decided_dt > now_dt:
            blocks.append("REREAD_EXPLICIT_DECISION_FROM_FUTURE")
    except ValueError:
        blocks.append("REREAD_EXPLICIT_DECISION_TIME_INVALID")
    if _forbidden(decision):
        blocks.append("REREAD_EXPLICIT_DECISION_FORBIDDEN_FIELD")
    return sorted(set(blocks))


def _recovery_context(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str], str]:
    blocks = recovery._job_blocks(channel, job)
    if blocks:
        return None, None, None, blocks, "HOLD_REREAD_JOB"
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return None, None, None, state_blocks, "HOLD_REREAD_CHECKPOINT_STATE"
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return state, None, None, ["REREAD_RECOVERY_ENTRY_MISSING"], "HOLD_REREAD_CHECKPOINT_STATE"
    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, None, ["REREAD_RECOVERY_REQUIRED_STATE_EXPECTED"], "HOLD_REREAD_NOT_RECOVERY_REQUIRED"
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return state, entry, None, ["REREAD_JOB_FINGERPRINT_CONFLICT"], "HOLD_REREAD_IDENTITY"
    sealed = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if sealed.get("valid") is not True:
        return state, entry, None, list(sealed.get("hard_blocks", [])), "HOLD_REREAD_SEALED_RECEIPT"
    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, latest, ["REREAD_RECOVERY_REQUIRED_RECEIPT_EXPECTED"], "HOLD_REREAD_SEALED_RECEIPT"
    if not _clean(latest.get("network_started_at")):
        return state, entry, latest, ["REREAD_NETWORK_START_PROOF_REQUIRED"], "HOLD_REREAD_SEALED_RECEIPT"
    store, store_blocks, _ = recovery._load_store(repo_root, channel)
    if store_blocks:
        return state, entry, latest, store_blocks, "HOLD_REREAD_OBSERVATION_LEDGER"
    observation, evidence_blocks, _ = recovery._covering_observation(job, entry, store)
    if evidence_blocks:
        return state, entry, latest, evidence_blocks, "HOLD_REREAD_OBSERVATION_CONFLICT"
    if observation is not None:
        return state, entry, latest, ["REREAD_NOT_NEEDED_DURABLE_OBSERVATION_EXISTS"], "HOLD_REREAD_NOT_NEEDED"
    return state, entry, latest, [], "REREAD_CONTEXT_VALID"


def issue_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    decision: dict[str, Any],
    now: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> dict[str, Any]:
    """Persist one explicit, authorization-sealed, single-use provider re-read handoff."""
    if not isinstance(channel, dict) or not isinstance(job, dict):
        raise TypeError("channel and job must be mappings")
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _hold(channel, job, "HOLD_REREAD_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    try:
        now_dt = runtime._dt(now)
    except ValueError:
        return _hold(channel, job, "HOLD_REREAD_TIME", ["REREAD_NOW_INVALID"])
    try:
        ttl = int(ttl_minutes)
    except (TypeError, ValueError):
        ttl = 0
    if ttl <= 0 or ttl > 120:
        return _hold(channel, job, "HOLD_REREAD_TTL", ["REREAD_TTL_OUT_OF_RANGE"])
    decision_blocks = _decision_blocks(decision, now)
    if decision_blocks:
        return _hold(channel, job, "HOLD_REREAD_EXPLICIT_DECISION", decision_blocks)
    state, entry, latest, context_blocks, context_status = _recovery_context(
        repo_root, channel, job, authorization_fingerprint
    )
    if context_blocks or state is None or entry is None or latest is None:
        return _hold(channel, job, context_status, context_blocks or ["REREAD_CONTEXT_INVALID"])

    issued_at = runtime._iso(now_dt)
    expires_at = runtime._iso(now_dt + timedelta(minutes=ttl))
    authorization = {
        "decision": DECISION,
        "reason_code": REASON_CODE,
        "decision_id": _clean(decision.get("decision_id")),
        "decision_actor_ref": _clean(decision.get("decision_actor_ref")),
        "decided_at": runtime._iso(runtime._dt(_clean(decision.get("decided_at")))),
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean((job.get("publication") or {}).get("remote_publication_id")),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "receipt_fingerprint_sha256": _clean(latest.get("receipt_fingerprint_sha256")),
        "checkpoint_state_fingerprint_at_issue": _clean(state.get("state_fingerprint_sha256")),
        "issued_at": issued_at,
        "expires_at": expires_at,
        "max_provider_reads": 1,
        "zero_paid_dependency": True,
        "observed_only": True,
    }
    seal = _handoff_authorization_fingerprint(authorization)
    handoff_id = "metrics-reread:" + _digest({
        "checkpoint_key": authorization["checkpoint_key"],
        "decision_id": authorization["decision_id"],
        "authorization_fingerprint": authorization_fingerprint,
        "receipt_fingerprint_sha256": authorization["receipt_fingerprint_sha256"],
    })[:32]
    record = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": HANDOFF_RUNTIME_ID,
        "handoff_id": handoff_id,
        "status": "AUTHORIZED",
        "authorization": authorization,
        "handoff_authorization_fingerprint_sha256": seal,
        "consumed_at": None,
        "consumed_checkpoint_state_fingerprint_sha256": None,
        "provider_network_call_performed": False,
        "record_fingerprint_sha256": "",
    }
    record["record_fingerprint_sha256"] = _record_fingerprint(record)

    store, store_blocks, _ = load_handoff_store(repo_root, channel)
    if store_blocks:
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_STORE", store_blocks)
    previous_store_fp = _clean(store.get("store_fingerprint_sha256")) or None
    existing = store.get("records", {}).get(handoff_id)
    if isinstance(existing, dict):
        existing_blocks = _record_blocks(existing)
        if existing_blocks:
            return _hold(channel, job, "HOLD_REREAD_HANDOFF_STORE", existing_blocks)
        if _clean(existing.get("handoff_authorization_fingerprint_sha256")) != seal:
            return _hold(channel, job, "HOLD_REREAD_HANDOFF_CONFLICT", ["REREAD_HANDOFF_IDENTITY_CONFLICT"])
        return {
            **_hold(channel, job, "REREAD_HANDOFF_ALREADY_EXISTS", []),
            "hard_blocks": [],
            "provider_reread_authorized": _clean(existing.get("status")).upper() == "AUTHORIZED",
            "handoff": _clone(existing),
            "durable_paths": [expected_handoff_store_path(channel)],
        }
    store["records"][handoff_id] = record
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    persisted = persist_handoff_store_cas(
        repo_root, channel, store,
        expected_previous_fingerprint_sha256=previous_store_fp,
    )
    if persisted.get("persisted") is not True:
        return _hold(channel, job, persisted.get("status") or "HOLD_REREAD_HANDOFF_PERSISTENCE", list(persisted.get("hard_blocks", [])))
    return {
        **_hold(channel, job, "REREAD_HANDOFF_AUTHORIZED", []),
        "hard_blocks": [],
        "provider_reread_authorized": True,
        "handoff": _clone(record),
        "durable_paths": [expected_handoff_store_path(channel)],
    }


def _repair_consumed_store(
    repo_root: Path,
    channel: dict[str, Any],
    store: dict[str, Any],
    record: dict[str, Any],
    previous_store_fp: str | None,
    *,
    consumed_at: str,
    checkpoint_state_fingerprint: str,
) -> dict[str, Any]:
    updated = _clone(record)
    updated["status"] = "CONSUMED"
    updated["consumed_at"] = consumed_at
    updated["consumed_checkpoint_state_fingerprint_sha256"] = checkpoint_state_fingerprint
    updated["record_fingerprint_sha256"] = _record_fingerprint(updated)
    store["records"][updated["handoff_id"]] = updated
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return persist_handoff_store_cas(
        repo_root, channel, store,
        expected_previous_fingerprint_sha256=previous_store_fp,
    )


def consume_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    handoff_id: str,
    now: str,
) -> dict[str, Any]:
    """Consume a durable handoff once, making one fresh sealed attempt eligible later."""
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _hold(channel, job, "HOLD_REREAD_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    try:
        now_dt = runtime._dt(now)
    except ValueError:
        return _hold(channel, job, "HOLD_REREAD_TIME", ["REREAD_NOW_INVALID"])
    store, store_blocks, _ = load_handoff_store(repo_root, channel)
    if store_blocks:
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_STORE", store_blocks)
    previous_store_fp = _clean(store.get("store_fingerprint_sha256")) or None
    record = store.get("records", {}).get(_clean(handoff_id))
    if not isinstance(record, dict):
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_MISSING", ["REREAD_HANDOFF_NOT_FOUND"])
    record_blocks = _record_blocks(record)
    if record_blocks:
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_TAMPERED", record_blocks)
    authorization = record["authorization"]
    if not hmac.compare_digest(_clean(authorization.get("authorization_fingerprint")), authorization_fingerprint):
        return _hold(channel, job, "HOLD_REREAD_AUTHORIZATION_CHANGED", ["REREAD_HANDOFF_AUTHORIZATION_CONTEXT_CHANGED"])
    identity_pairs = (
        ("instance_id", _clean(channel.get("instance_id"))),
        ("channel_id", _clean(channel.get("channel_id"))),
        ("platform", _clean(channel.get("platform")).lower()),
        ("checkpoint_key", runtime.checkpoint_key(job)),
        ("publication_id", _clean(job.get("publication_id"))),
        ("job_fingerprint_sha256", _clean(job.get("job_fingerprint_sha256"))),
    )
    identity_blocks = ["REREAD_HANDOFF_IDENTITY_MISMATCH:" + key for key, expected in identity_pairs if _clean(authorization.get(key)) != expected]
    remote_id = _clean((job.get("publication") or {}).get("remote_publication_id"))
    if _clean(authorization.get("remote_publication_id")) != remote_id:
        identity_blocks.append("REREAD_HANDOFF_IDENTITY_MISMATCH:remote_publication_id")
    if identity_blocks:
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_IDENTITY", identity_blocks)

    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return _hold(channel, job, "HOLD_REREAD_CHECKPOINT_STATE", state_blocks)
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return _hold(channel, job, "HOLD_REREAD_CHECKPOINT_STATE", ["REREAD_RECOVERY_ENTRY_MISSING"])

    if _clean(record.get("status")).upper() == "CONSUMED":
        return {
            **_hold(channel, job, "REREAD_HANDOFF_ALREADY_CONSUMED", []),
            "hard_blocks": [],
            "handoff": _clone(record),
            "durable_paths": [expected_handoff_store_path(channel), runtime.expected_checkpoint_state_path(channel)],
        }

    latest = receipt._latest_receipt(entry)
    evidence = latest.get("recovery_evidence") if isinstance(latest, dict) and isinstance(latest.get("recovery_evidence"), dict) else {}
    seal = _clean(record.get("handoff_authorization_fingerprint_sha256"))
    if _clean(entry.get("status")).upper() == "RETRY_WAIT" and _clean(evidence.get("reread_handoff_authorization_fingerprint_sha256")) == seal:
        repaired = _repair_consumed_store(
            repo_root, channel, store, record, previous_store_fp,
            consumed_at=runtime._iso(now_dt),
            checkpoint_state_fingerprint=_clean(state.get("state_fingerprint_sha256")),
        )
        if repaired.get("persisted") is not True:
            return _hold(channel, job, repaired.get("status") or "HOLD_REREAD_HANDOFF_PERSISTENCE", list(repaired.get("hard_blocks", [])))
        repaired_store, _, _ = load_handoff_store(repo_root, channel)
        repaired_record = repaired_store.get("records", {}).get(_clean(handoff_id), {})
        return {
            **_hold(channel, job, "REREAD_HANDOFF_CONSUMPTION_RECOVERED", []),
            "hard_blocks": [],
            "handoff": _clone(repaired_record),
            "durable_paths": [expected_handoff_store_path(channel), runtime.expected_checkpoint_state_path(channel)],
        }

    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED":
        return _hold(channel, job, "HOLD_REREAD_NOT_RECOVERY_REQUIRED", ["REREAD_RECOVERY_REQUIRED_STATE_EXPECTED"])
    if _clean(state.get("state_fingerprint_sha256")) != _clean(authorization.get("checkpoint_state_fingerprint_at_issue")):
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_STALE", ["REREAD_CHECKPOINT_STATE_CHANGED_AFTER_HANDOFF_ISSUE"])
    sealed = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if sealed.get("valid") is not True:
        return _hold(channel, job, "HOLD_REREAD_SEALED_RECEIPT", list(sealed.get("hard_blocks", [])))
    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("receipt_fingerprint_sha256")) != _clean(authorization.get("receipt_fingerprint_sha256")):
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_STALE", ["REREAD_RECEIPT_CHANGED_AFTER_HANDOFF_ISSUE"])
    if now_dt > runtime._dt(_clean(authorization.get("expires_at"))):
        return _hold(channel, job, "HOLD_REREAD_HANDOFF_EXPIRED", ["REREAD_HANDOFF_EXPIRED"])

    observation_store, observation_blocks, _ = recovery._load_store(repo_root, channel)
    if observation_blocks:
        return _hold(channel, job, "HOLD_REREAD_OBSERVATION_LEDGER", observation_blocks)
    observation, evidence_blocks, _ = recovery._covering_observation(job, entry, observation_store)
    if evidence_blocks:
        return _hold(channel, job, "HOLD_REREAD_OBSERVATION_CONFLICT", evidence_blocks)
    if observation is not None:
        return _hold(channel, job, "HOLD_REREAD_SUPERSEDED_BY_DURABLE_OBSERVATION", ["REREAD_NOT_NEEDED_DURABLE_OBSERVATION_EXISTS"])

    recovery_evidence = recovery._recovery_evidence(
        kind="NO_DURABLE_COVERAGE_OBSERVATION",
        store=observation_store,
        observation=None,
        checked_at=runtime._iso(now_dt),
        provider_reread_authorized=True,
    )
    recovery_evidence["authorization_mode"] = "EXPLICIT_SINGLE_USE_HANDOFF"
    recovery_evidence["reread_handoff_id"] = _clean(record.get("handoff_id"))
    recovery_evidence["reread_handoff_authorization_fingerprint_sha256"] = seal
    recovery_evidence["explicit_decision_id"] = _clean(authorization.get("decision_id"))
    unsigned_evidence = _clone(recovery_evidence)
    unsigned_evidence.pop("recovery_evidence_fingerprint_sha256", None)
    recovery_evidence["recovery_evidence_fingerprint_sha256"] = recovery._digest(unsigned_evidence)

    previous_state_fp = _clean(state.get("state_fingerprint_sha256")) or None
    persisted = recovery._persist_reconciled_state(
        repo_root,
        channel,
        job,
        state,
        previous_state_fp,
        authorization_fingerprint=authorization_fingerprint,
        now=runtime._iso(now_dt),
        target_status="RETRY_WAIT",
        evidence=recovery_evidence,
    )
    if persisted.get("persisted") is not True:
        return _hold(channel, job, persisted.get("status") or "HOLD_REREAD_CHECKPOINT_PERSISTENCE", list(persisted.get("hard_blocks", [])))
    post_state, post_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if post_blocks:
        return _hold(channel, job, "HOLD_REREAD_CHECKPOINT_READBACK", post_blocks)
    repaired = _repair_consumed_store(
        repo_root,
        channel,
        store,
        record,
        previous_store_fp,
        consumed_at=runtime._iso(now_dt),
        checkpoint_state_fingerprint=_clean(post_state.get("state_fingerprint_sha256")),
    )
    if repaired.get("persisted") is not True:
        # Checkpoint already carries the immutable handoff seal, so a retry can repair
        # the sidecar without authorizing another provider read.
        result = _hold(channel, job, "REREAD_HANDOFF_CONSUMPTION_REPAIR_REQUIRED", list(repaired.get("hard_blocks", [])))
        result["provider_reread_authorized"] = True
        result["checkpoint_status"] = "RETRY_WAIT"
        result["durable_paths"] = [runtime.expected_checkpoint_state_path(channel), expected_handoff_store_path(channel)]
        return result
    final_store, _, _ = load_handoff_store(repo_root, channel)
    final_record = final_store.get("records", {}).get(_clean(handoff_id), {})
    return {
        **_hold(channel, job, "REREAD_HANDOFF_CONSUMED", []),
        "hard_blocks": [],
        "provider_reread_authorized": True,
        "checkpoint_status": "RETRY_WAIT",
        "handoff": _clone(final_record),
        "recovery_evidence": recovery_evidence,
        "durable_paths": [runtime.expected_checkpoint_state_path(channel), expected_handoff_store_path(channel)],
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
    issue.add_argument("decision", type=Path)
    issue.add_argument("--repo-root", type=Path, default=Path("."))
    issue.add_argument("--authorization-fingerprint", required=True)
    issue.add_argument("--now", required=True)
    issue.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)

    consume = sub.add_parser("consume")
    consume.add_argument("channel", type=Path)
    consume.add_argument("job", type=Path)
    consume.add_argument("--repo-root", type=Path, default=Path("."))
    consume.add_argument("--authorization-fingerprint", required=True)
    consume.add_argument("--handoff-id", required=True)
    consume.add_argument("--now", required=True)

    args = parser.parse_args()
    if args.command == "issue":
        result = issue_handoff(
            args.repo_root,
            _load(args.channel),
            _load(args.job),
            authorization_fingerprint=args.authorization_fingerprint,
            decision=_load(args.decision),
            now=args.now,
            ttl_minutes=args.ttl_minutes,
        )
    else:
        result = consume_handoff(
            args.repo_root,
            _load(args.channel),
            _load(args.job),
            authorization_fingerprint=args.authorization_fingerprint,
            handoff_id=args.handoff_id,
            now=args.now,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if _clean(result.get("status")).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
