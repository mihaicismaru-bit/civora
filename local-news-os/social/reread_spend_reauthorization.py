#!/usr/bin/env python3
"""Durable single-use spend seal for explicit observed-metrics provider re-reads.

An explicit recovery handoff authorizes at most one provider re-read after an
ambiguous metrics request. ``authorization_sealed_harvest_receipt`` already binds
the next attempt to the exact consumed handoff. This boundary adds the missing
spend ledger: the handoff is reserved before ``NETWORK_CALL_STARTED`` and sealed
as SPENT before the provider call is allowed to proceed.

A RESERVED or SPENT handoff can never authorize a later provider read. A new read
therefore requires a new explicit recovery decision/handoff. The ledger contains
only authorization/provenance metadata; credential values and raw provider payloads
are never read or persisted. Analytics remains advisory-only and zero-paid.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import fleet_metrics_reread_authorization_handoff as handoff
import metrics_harvest_runtime as runtime

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-spend-reauthorization-v1"
PATCH_ID = RUNTIME_ID + ":installed"
SPEND_FINGERPRINT_RE = receipt.RECEIPT_FINGERPRINT_RE

_BASE_CLAIM = receipt.claim_checkpoint_sealed
_BASE_MARK_NETWORK_STARTED = receipt.mark_network_started
_INSTALLED = False


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def spend_guards() -> dict[str, Any]:
    return {
        "explicit_single_use_handoff_required": True,
        "spend_reserved_before_network_start": True,
        "spend_sealed_before_provider_call": True,
        "spent_handoff_reuse_allowed": False,
        "new_explicit_reauthorization_required_after_spend": True,
        "provider_network_call_performed_by_spend_boundary": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def expected_spend_store_path(channel: dict[str, Any]) -> str:
    publication_state = channel.get("publication_state") if isinstance(channel.get("publication_state"), dict) else {}
    raw = _clean(publication_state.get("state_path"))
    if not raw:
        raise ValueError("channel publication_state.state_path is required")
    path = runtime._safe_relative(raw)
    stem = path.name[:-5] if path.name.endswith(".json") else path.name
    return str(path.with_name(f"{stem}_metrics_reread_spend.json"))


def _record_fingerprint(record: dict[str, Any]) -> str:
    unsigned = _clone(record)
    unsigned.pop("record_fingerprint_sha256", None)
    return _digest(unsigned)


def _store_fingerprint(store: dict[str, Any]) -> str:
    unsigned = _clone(store)
    unsigned.pop("store_fingerprint_sha256", None)
    return _digest(unsigned)


def empty_spend_store(channel: dict[str, Any]) -> dict[str, Any]:
    store = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "storage_path": expected_spend_store_path(channel),
        "records": {},
        "guards": spend_guards(),
    }
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    return store


def _record_blocks(record: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    if _clean(record.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_SPEND_SCHEMA_VERSION")
    if _clean(record.get("runtime_id")) != RUNTIME_ID:
        blocks.append("REREAD_SPEND_RUNTIME_ID")
    if not _clean(record.get("spend_id")) or not _clean(record.get("handoff_id")):
        blocks.append("REREAD_SPEND_IDENTITY_REQUIRED")
    status = _clean(record.get("status")).upper()
    if status not in {"RESERVED", "SPENT"}:
        blocks.append("REREAD_SPEND_STATUS_INVALID")
    if not receipt._valid_authorization_fingerprint(record.get("authorization_fingerprint")):
        blocks.append("REREAD_SPEND_AUTHORIZATION_FINGERPRINT_INVALID")
    if not receipt._valid_authorization_fingerprint(record.get("handoff_authorization_fingerprint_sha256")):
        blocks.append("REREAD_SPEND_HANDOFF_SEAL_INVALID")
    for key in (
        "handoff_record_fingerprint_sha256",
        "reservation_receipt_fingerprint_sha256",
    ):
        if not SPEND_FINGERPRINT_RE.fullmatch(_clean(record.get(key))):
            blocks.append("REREAD_SPEND_FINGERPRINT_INVALID:" + key)
    if not _clean(record.get("explicit_decision_id")):
        blocks.append("REREAD_SPEND_DECISION_ID_REQUIRED")
    if not _clean(record.get("checkpoint_key")) or not _clean(record.get("job_fingerprint_sha256")):
        blocks.append("REREAD_SPEND_CHECKPOINT_IDENTITY_REQUIRED")
    if not _clean(record.get("execution_id")):
        blocks.append("REREAD_SPEND_EXECUTION_ID_REQUIRED")
    try:
        attempt = int(record.get("attempt") or 0)
    except (TypeError, ValueError):
        attempt = 0
    if attempt <= 0:
        blocks.append("REREAD_SPEND_ATTEMPT_INVALID")
    if not _clean(record.get("reserved_at")):
        blocks.append("REREAD_SPEND_RESERVED_AT_REQUIRED")
    if record.get("reauthorization_required_after_network_start") is not True:
        blocks.append("REREAD_SPEND_REAUTHORIZATION_GUARD_MISSING")
    if record.get("provider_network_call_performed_by_boundary") is not False:
        blocks.append("REREAD_SPEND_NETWORK_BOUNDARY_VIOLATION")
    if record.get("publication_blocked") is not False:
        blocks.append("REREAD_SPEND_PUBLICATION_BOUNDARY_VIOLATION")
    if record.get("zero_paid_dependency") is not True:
        blocks.append("REREAD_SPEND_ZERO_PAID_POLICY_VIOLATION")
    if status == "RESERVED":
        if record.get("provider_reads_spent") != 0:
            blocks.append("REREAD_SPEND_RESERVED_COUNT_INVALID")
        if _clean(record.get("network_started_at")) or _clean(record.get("network_receipt_fingerprint_sha256")):
            blocks.append("REREAD_SPEND_PREMATURE_NETWORK_PROOF")
    if status == "SPENT":
        if record.get("provider_reads_spent") != 1:
            blocks.append("REREAD_SPEND_COUNT_INVALID")
        if not _clean(record.get("network_started_at")):
            blocks.append("REREAD_SPEND_NETWORK_STARTED_AT_REQUIRED")
        if not SPEND_FINGERPRINT_RE.fullmatch(_clean(record.get("network_receipt_fingerprint_sha256"))):
            blocks.append("REREAD_SPEND_NETWORK_RECEIPT_FINGERPRINT_INVALID")
    if handoff._contains_forbidden_material(record):
        blocks.append("REREAD_SPEND_FORBIDDEN_MATERIAL")
    supplied = _clean(record.get("record_fingerprint_sha256"))
    if not SPEND_FINGERPRINT_RE.fullmatch(supplied) or supplied != _record_fingerprint(record):
        blocks.append("REREAD_SPEND_RECORD_FINGERPRINT_MISMATCH")
    return sorted(set(blocks))


def validate_spend_store(channel: dict[str, Any], store: dict[str, Any]) -> dict[str, Any]:
    blocks: list[str] = []
    if not isinstance(store, dict):
        return {"valid": False, "hard_blocks": ["REREAD_SPEND_STORE_NOT_OBJECT"]}
    if _clean(store.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_SPEND_STORE_SCHEMA_VERSION")
    if _clean(store.get("runtime_id")) != RUNTIME_ID:
        blocks.append("REREAD_SPEND_STORE_RUNTIME_ID")
    for key, code in (("instance_id", "INSTANCE"), ("channel_id", "CHANNEL")):
        if _clean(store.get(key)) != _clean(channel.get(key)):
            blocks.append(f"REREAD_SPEND_STORE_{code}_MISMATCH")
    if _clean(store.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("REREAD_SPEND_STORE_PLATFORM_MISMATCH")
    try:
        expected_path = expected_spend_store_path(channel)
    except ValueError:
        expected_path = ""
        blocks.append("REREAD_SPEND_STORE_NAMESPACE_INVALID")
    if _clean(store.get("storage_path")) != expected_path:
        blocks.append("REREAD_SPEND_STORE_NAMESPACE_MISMATCH")
    records = store.get("records")
    if not isinstance(records, dict):
        blocks.append("REREAD_SPEND_STORE_RECORDS_INVALID")
        records = {}
    for key, record in records.items():
        if not isinstance(key, str) or not isinstance(record, dict):
            blocks.append("REREAD_SPEND_STORE_RECORD_INVALID")
            continue
        if _clean(record.get("handoff_id")) != key:
            blocks.append("REREAD_SPEND_STORE_KEY_MISMATCH")
        blocks.extend(_record_blocks(record))
    guards = store.get("guards") if isinstance(store.get("guards"), dict) else {}
    for key, expected in spend_guards().items():
        if guards.get(key) is not expected:
            blocks.append("REREAD_SPEND_STORE_GUARD:" + key)
    supplied = _clean(store.get("store_fingerprint_sha256"))
    if not SPEND_FINGERPRINT_RE.fullmatch(supplied) or supplied != _store_fingerprint(store):
        blocks.append("REREAD_SPEND_STORE_FINGERPRINT_MISMATCH")
    return {"valid": not blocks, "hard_blocks": sorted(set(blocks))}


def load_spend_store(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any], list[str], bool]:
    try:
        relative = expected_spend_store_path(channel)
        target = runtime._safe_target(repo_root, relative)
    except ValueError as exc:
        return {}, ["REREAD_SPEND_STORE_PATH_INVALID:" + str(exc)], False
    if not target.exists():
        return empty_spend_store(channel), [], False
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, ["REREAD_SPEND_STORE_READ_INVALID:" + str(exc)], True
    checked = validate_spend_store(channel, value)
    return value, list(checked.get("hard_blocks", [])), True


def persist_spend_store_cas(
    repo_root: Path,
    channel: dict[str, Any],
    store: dict[str, Any],
    *,
    expected_previous_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    checked = validate_spend_store(channel, store)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_TARGET_STORE", "hard_blocks": checked.get("hard_blocks", [])}
    relative = expected_spend_store_path(channel)
    target = runtime._safe_target(repo_root, relative)
    try:
        with runtime._StateLock(target):
            existing, blocks, existed = load_spend_store(repo_root, channel)
            if blocks:
                return {"persisted": False, "status": "HOLD_REREAD_SPEND_EXISTING_STORE", "hard_blocks": blocks, "path": relative}
            actual = _clean(existing.get("store_fingerprint_sha256")) or None
            expected = _clean(expected_previous_fingerprint_sha256) or None
            empty_fp = _clean(empty_spend_store(channel).get("store_fingerprint_sha256")) or None
            if (actual == expected if existed else expected in {None, empty_fp}) is not True:
                return {"persisted": False, "status": "HOLD_REREAD_SPEND_STORE_CAS_CONFLICT", "hard_blocks": ["REREAD_SPEND_STORE_COMPARE_AND_SWAP_CONFLICT"], "path": relative}
            if existed and actual == _clean(store.get("store_fingerprint_sha256")):
                return {"persisted": True, "status": "IDEMPOTENT_REREAD_SPEND_STORE", "hard_blocks": [], "path": relative, "written": False}
            runtime._atomic_write_json(target, store)
    except BlockingIOError:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_STORE_LOCK_BUSY", "hard_blocks": ["REREAD_SPEND_STORE_LOCK_BUSY"], "path": relative}
    persisted, blocks, _ = load_spend_store(repo_root, channel)
    if blocks or _clean(persisted.get("store_fingerprint_sha256")) != _clean(store.get("store_fingerprint_sha256")):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_STORE_READBACK", "hard_blocks": blocks or ["REREAD_SPEND_STORE_READBACK_FINGERPRINT_MISMATCH"], "path": relative}
    return {"persisted": True, "status": "REREAD_SPEND_STORE_PERSISTED", "hard_blocks": [], "path": relative, "written": True}


def _lineage_handoff_id(entry: dict[str, Any]) -> str:
    lineage = receipt._lineage_recovery_receipt(entry)
    evidence = lineage.get("recovery_evidence") if isinstance(lineage, dict) and isinstance(lineage.get("recovery_evidence"), dict) else {}
    return _clean(evidence.get("reread_handoff_id"))


def _spend_record(repo_root: Path, channel: dict[str, Any], handoff_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    store, blocks, _ = load_spend_store(repo_root, channel)
    if blocks:
        return None, blocks
    record = store.get("records", {}).get(_clean(handoff_id))
    if not isinstance(record, dict):
        return None, []
    record_blocks = _record_blocks(record)
    return (record if not record_blocks else None), record_blocks


def _guard_reauthorization_before_claim(repo_root: Path, channel: dict[str, Any], job: dict[str, Any]) -> dict[str, Any] | None:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict) or not receipt._requires_reread_attempt_provenance(entry):
        return None
    handoff_id = _lineage_handoff_id(entry)
    if not handoff_id:
        return None
    record, record_blocks = _spend_record(repo_root, channel, handoff_id)
    if record_blocks:
        return {
            "claimed": False,
            "status": "HOLD_REREAD_SPEND_TAMPERED",
            "hard_blocks": record_blocks,
            "entry": _clone(entry),
            "publication_blocked": False,
        }
    if isinstance(record, dict) and _clean(record.get("status")).upper() in {"RESERVED", "SPENT"}:
        return {
            "claimed": False,
            "status": "HOLD_REREAD_REAUTHORIZATION_REQUIRED",
            "hard_blocks": ["REREAD_SINGLE_USE_PROVIDER_READ_ALREADY_SPENT"],
            "entry": _clone(entry),
            "publication_blocked": False,
            "spent_handoff_id": handoff_id,
        }
    return None


def claim_checkpoint_sealed(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    lease_minutes: int = runtime.DEFAULT_LEASE_MINUTES,
) -> dict[str, Any]:
    blocked = _guard_reauthorization_before_claim(repo_root, channel, job)
    if blocked is not None:
        return blocked
    return _BASE_CLAIM(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        lease_minutes=lease_minutes,
    )


def _reserve_spend(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    entry: dict[str, Any],
    provenance: dict[str, Any],
    now: str,
) -> dict[str, Any]:
    verification_blocks = receipt._verify_bound_reread_attempt(
        repo_root, channel, job, authorization_fingerprint, provenance
    )
    if verification_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_PROVENANCE", "hard_blocks": verification_blocks}
    latest = receipt._latest_receipt(entry)
    if not isinstance(latest, dict) or _clean(latest.get("status")).upper() != "CLAIMED":
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_RECEIPT", "hard_blocks": ["REREAD_SPEND_CLAIM_RECEIPT_REQUIRED"]}

    handoff_id = _clean(provenance.get("handoff_id"))
    store, store_blocks, _ = load_spend_store(repo_root, channel)
    if store_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_STORE", "hard_blocks": store_blocks}
    previous_fp = _clean(store.get("store_fingerprint_sha256")) or None
    existing = store.get("records", {}).get(handoff_id)
    execution_id = _clean(latest.get("execution_id"))
    if isinstance(existing, dict):
        existing_blocks = _record_blocks(existing)
        if existing_blocks:
            return {"persisted": False, "status": "HOLD_REREAD_SPEND_TAMPERED", "hard_blocks": existing_blocks}
        if _clean(existing.get("status")).upper() == "RESERVED" and hmac.compare_digest(_clean(existing.get("execution_id")), execution_id):
            return {"persisted": True, "status": "REREAD_SPEND_ALREADY_RESERVED", "hard_blocks": [], "record": _clone(existing), "path": expected_spend_store_path(channel)}
        return {"persisted": False, "status": "HOLD_REREAD_REAUTHORIZATION_REQUIRED", "hard_blocks": ["REREAD_SINGLE_USE_PROVIDER_READ_ALREADY_SPENT"], "record": _clone(existing)}

    authorization = provenance
    record = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "spend_id": "metrics-reread-spend:" + _digest({
            "handoff_id": handoff_id,
            "execution_id": execution_id,
            "authorization_fingerprint": authorization_fingerprint,
        })[:32],
        "handoff_id": handoff_id,
        "status": "RESERVED",
        "authorization_fingerprint": authorization_fingerprint,
        "handoff_authorization_fingerprint_sha256": _clean(authorization.get("handoff_authorization_fingerprint_sha256")),
        "handoff_record_fingerprint_sha256": _clean(authorization.get("handoff_record_fingerprint_sha256")),
        "explicit_decision_id": _clean(authorization.get("explicit_decision_id")),
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean((job.get("publication") or {}).get("remote_publication_id")),
        "execution_id": execution_id,
        "attempt": int(latest.get("attempt") or entry.get("attempt") or 0),
        "reserved_at": runtime._iso(runtime._dt(now)),
        "reservation_receipt_fingerprint_sha256": _clean(latest.get("receipt_fingerprint_sha256")),
        "network_started_at": None,
        "network_receipt_fingerprint_sha256": None,
        "provider_reads_spent": 0,
        "reauthorization_required_after_network_start": True,
        "provider_network_call_performed_by_boundary": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    record["record_fingerprint_sha256"] = _record_fingerprint(record)
    store["records"][handoff_id] = record
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    persisted = persist_spend_store_cas(
        repo_root,
        channel,
        store,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {"persisted": False, "status": persisted.get("status") or "HOLD_REREAD_SPEND_PERSISTENCE", "hard_blocks": list(persisted.get("hard_blocks", []))}
    return {"persisted": True, "status": "REREAD_SPEND_RESERVED", "hard_blocks": [], "record": _clone(record), "path": expected_spend_store_path(channel)}


def _finalize_spend(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    provenance: dict[str, Any],
) -> dict[str, Any]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_CHECKPOINT", "hard_blocks": state_blocks}
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    latest = receipt._latest_receipt(entry) if isinstance(entry, dict) else None
    if not isinstance(latest, dict) or _clean(latest.get("status")).upper() != "NETWORK_CALL_STARTED" or not _clean(latest.get("network_started_at")):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_NETWORK_PROOF", "hard_blocks": ["REREAD_SPEND_NETWORK_START_RECEIPT_REQUIRED"]}
    if not hmac.compare_digest(_clean(entry.get("authorization_fingerprint")), authorization_fingerprint):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_AUTHORIZATION", "hard_blocks": ["REREAD_SPEND_AUTHORIZATION_CONTEXT_CHANGED"]}

    handoff_id = _clean(provenance.get("handoff_id"))
    store, store_blocks, _ = load_spend_store(repo_root, channel)
    if store_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_STORE", "hard_blocks": store_blocks}
    previous_fp = _clean(store.get("store_fingerprint_sha256")) or None
    record = store.get("records", {}).get(handoff_id)
    if not isinstance(record, dict):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_MISSING", "hard_blocks": ["REREAD_SPEND_RESERVATION_MISSING"]}
    record_blocks = _record_blocks(record)
    if record_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_TAMPERED", "hard_blocks": record_blocks}
    if _clean(record.get("status")).upper() == "SPENT":
        if hmac.compare_digest(_clean(record.get("execution_id")), _clean(latest.get("execution_id"))):
            return {"persisted": True, "status": "REREAD_SPEND_ALREADY_SEALED", "hard_blocks": [], "record": _clone(record), "path": expected_spend_store_path(channel)}
        return {"persisted": False, "status": "HOLD_REREAD_REAUTHORIZATION_REQUIRED", "hard_blocks": ["REREAD_SINGLE_USE_PROVIDER_READ_ALREADY_SPENT"]}
    if not hmac.compare_digest(_clean(record.get("execution_id")), _clean(latest.get("execution_id"))):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_EXECUTION_MISMATCH", "hard_blocks": ["REREAD_SPEND_EXECUTION_ID_MISMATCH"]}
    if not hmac.compare_digest(_clean(record.get("authorization_fingerprint")), authorization_fingerprint):
        return {"persisted": False, "status": "HOLD_REREAD_SPEND_AUTHORIZATION", "hard_blocks": ["REREAD_SPEND_AUTHORIZATION_CONTEXT_CHANGED"]}

    updated = _clone(record)
    updated["status"] = "SPENT"
    updated["network_started_at"] = _clean(latest.get("network_started_at"))
    updated["network_receipt_fingerprint_sha256"] = _clean(latest.get("receipt_fingerprint_sha256"))
    updated["provider_reads_spent"] = 1
    updated["record_fingerprint_sha256"] = _record_fingerprint(updated)
    store["records"][handoff_id] = updated
    store["store_fingerprint_sha256"] = _store_fingerprint(store)
    persisted = persist_spend_store_cas(
        repo_root,
        channel,
        store,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {"persisted": False, "status": persisted.get("status") or "HOLD_REREAD_SPEND_FINALIZATION", "hard_blocks": list(persisted.get("hard_blocks", []))}
    return {"persisted": True, "status": "REREAD_SPEND_SEALED", "hard_blocks": [], "record": updated, "path": expected_spend_store_path(channel)}


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
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    latest = receipt._latest_receipt(entry) if isinstance(entry, dict) else None
    provenance = latest.get("reread_attempt_provenance") if isinstance(latest, dict) and isinstance(latest.get("reread_attempt_provenance"), dict) else None
    if provenance is None:
        return _BASE_MARK_NETWORK_STARTED(
            repo_root,
            channel,
            job,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
        )

    reserved = _reserve_spend(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
        entry,
        provenance,
        now,
    )
    if reserved.get("persisted") is not True:
        return reserved

    started = _BASE_MARK_NETWORK_STARTED(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
    )
    if started.get("persisted") is not True:
        return started

    sealed = _finalize_spend(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
        provenance,
    )
    if sealed.get("persisted") is not True:
        return {
            "persisted": False,
            "status": "HOLD_REREAD_SPEND_FINALIZATION",
            "hard_blocks": list(sealed.get("hard_blocks", [])) or ["REREAD_SPEND_NOT_SEALED_BEFORE_PROVIDER_CALL"],
            "spend_path": expected_spend_store_path(channel),
        }
    result = dict(started)
    result.update({
        "reread_handoff_spent": True,
        "reread_spend_id": _clean((sealed.get("record") or {}).get("spend_id")),
        "reread_spend_path": expected_spend_store_path(channel),
        "reauthorization_required_for_next_provider_read": True,
    })
    return result


def install() -> None:
    """Install the spend guard into the authorization-sealed harvest module."""
    global _INSTALLED
    if _INSTALLED or getattr(receipt, "_reread_spend_patch_id", None) == PATCH_ID:
        _INSTALLED = True
        return
    receipt.claim_checkpoint_sealed = claim_checkpoint_sealed
    receipt.mark_network_started = mark_network_started
    setattr(receipt, "_reread_spend_patch_id", PATCH_ID)
    _INSTALLED = True
