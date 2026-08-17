#!/usr/bin/env python3
"""Bind a safely released re-read spend reservation to the eventual reclaim attempt.

``reread_spend_reservation_recovery`` may release a RESERVED spend only when a
sealed CLAIMED receipt proves that NETWORK_CALL_STARTED never happened. The same
single-use handoff is intentionally reusable after that safe release. This layer
closes the remaining provenance gap: the eventual provider-facing reclaim attempt
must carry a durable link to the exact release evidence before network start.

The binding is receipt-only. It performs no provider call, reads no credential
value, persists no provider payload, and never affects editorial publication.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import reread_spend_reauthorization as spend
import reread_spend_reservation_recovery as recovery

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-spend-reclaim-binding-v1"
PATCH_ID = RUNTIME_ID + ":installed"
PROVENANCE_FIELD = "reread_spend_reclaim_provenance"
ACTION = "RECLAIM_AFTER_RELEASED_RESERVATION_NO_NETWORK_START"

# Preserve ordering: spend -> reservation recovery -> reclaim binding.
spend.install()
recovery.install()
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


def reclaim_guards() -> dict[str, Any]:
    return {
        "safe_release_evidence_required": True,
        "released_handoff_identity_preserved": True,
        "release_evidence_fingerprint_bound": True,
        "reclaim_attempt_bound_before_network_start": True,
        "unsatisfied_release_cannot_reach_network_without_binding": True,
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _provenance_fingerprint(value: dict[str, Any]) -> str:
    unsigned = _clone(value)
    unsigned.pop("provenance_fingerprint_sha256", None)
    return _digest(unsigned)


def _release_evidence_blocks(
    evidence: dict[str, Any],
    source_receipt: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> list[str]:
    blocks: list[str] = []
    if not isinstance(evidence, dict):
        return ["REREAD_RECLAIM_RELEASE_EVIDENCE_REQUIRED"]
    if _clean(evidence.get("schema_version")) != recovery.SCHEMA_VERSION:
        blocks.append("REREAD_RECLAIM_RELEASE_SCHEMA_VERSION")
    if _clean(evidence.get("runtime_id")) != recovery.RUNTIME_ID:
        blocks.append("REREAD_RECLAIM_RELEASE_RUNTIME_ID")
    if _clean(evidence.get("action")) != "RELEASE_AUTHORIZED_NO_NETWORK_START":
        blocks.append("REREAD_RECLAIM_RELEASE_ACTION_INVALID")
    if not _clean(evidence.get("recovery_id")):
        blocks.append("REREAD_RECLAIM_RELEASE_ID_REQUIRED")
    if not _clean(evidence.get("handoff_id")) or not _clean(evidence.get("spend_id")):
        blocks.append("REREAD_RECLAIM_RELEASE_HANDOFF_OR_SPEND_REQUIRED")
    if not hmac.compare_digest(_clean(evidence.get("authorization_fingerprint")), authorization_fingerprint):
        blocks.append("REREAD_RECLAIM_RELEASE_AUTHORIZATION_CHANGED")
    if _clean(evidence.get("checkpoint_key")) != runtime.checkpoint_key(job):
        blocks.append("REREAD_RECLAIM_RELEASE_CHECKPOINT_MISMATCH")
    if _clean(evidence.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        blocks.append("REREAD_RECLAIM_RELEASE_JOB_FINGERPRINT_MISMATCH")
    if _clean(evidence.get("execution_id")) != _clean(source_receipt.get("execution_id")):
        blocks.append("REREAD_RECLAIM_RELEASE_EXECUTION_MISMATCH")
    try:
        evidence_attempt = int(evidence.get("attempt") or 0)
        receipt_attempt = int(source_receipt.get("attempt") or 0)
    except (TypeError, ValueError):
        evidence_attempt = receipt_attempt = 0
    if evidence_attempt <= 0 or evidence_attempt != receipt_attempt:
        blocks.append("REREAD_RECLAIM_RELEASE_ATTEMPT_MISMATCH")
    if _clean(source_receipt.get("status")).upper() != "CLAIMED" or _clean(source_receipt.get("network_started_at")):
        blocks.append("REREAD_RECLAIM_RELEASE_SOURCE_RECEIPT_NOT_PRE_NETWORK")
    if _clean(source_receipt.get("authorization_fingerprint")) != authorization_fingerprint:
        blocks.append("REREAD_RECLAIM_RELEASE_SOURCE_RECEIPT_AUTHORIZATION_MISMATCH")
    if _clean(source_receipt.get("checkpoint_key")) != runtime.checkpoint_key(job):
        blocks.append("REREAD_RECLAIM_RELEASE_SOURCE_RECEIPT_CHECKPOINT_MISMATCH")
    if _clean(source_receipt.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        blocks.append("REREAD_RECLAIM_RELEASE_SOURCE_RECEIPT_JOB_MISMATCH")
    for key in (
        "source_spend_record_fingerprint_sha256",
        "reservation_receipt_fingerprint_sha256",
        "evidence_fingerprint_sha256",
    ):
        if not spend.SPEND_FINGERPRINT_RE.fullmatch(_clean(evidence.get(key))):
            blocks.append("REREAD_RECLAIM_RELEASE_FINGERPRINT_INVALID:" + key)
    supplied = _clean(evidence.get("evidence_fingerprint_sha256"))
    if supplied and supplied != recovery._evidence_fingerprint(evidence):
        blocks.append("REREAD_RECLAIM_RELEASE_EVIDENCE_FINGERPRINT_MISMATCH")
    if evidence.get("network_start_proven") is not False:
        blocks.append("REREAD_RECLAIM_RELEASE_NETWORK_START_PROOF_INVALID")
    if evidence.get("provider_read_result_proven") is not False:
        blocks.append("REREAD_RECLAIM_RELEASE_PROVIDER_RESULT_PROOF_INVALID")
    if evidence.get("provider_network_call_performed_by_recovery") is not False:
        blocks.append("REREAD_RECLAIM_RELEASE_NETWORK_BOUNDARY_VIOLATION")
    if evidence.get("publication_blocked") is not False:
        blocks.append("REREAD_RECLAIM_RELEASE_PUBLICATION_BOUNDARY_VIOLATION")
    if evidence.get("zero_paid_dependency") is not True:
        blocks.append("REREAD_RECLAIM_RELEASE_ZERO_PAID_POLICY_VIOLATION")
    if spend.handoff._contains_forbidden_material(evidence):
        blocks.append("REREAD_RECLAIM_RELEASE_FORBIDDEN_MATERIAL")
    return sorted(set(blocks))


def _receipt_handoff_id(row: dict[str, Any]) -> str:
    provenance = row.get("reread_attempt_provenance") if isinstance(row.get("reread_attempt_provenance"), dict) else {}
    return _clean(provenance.get("handoff_id"))


def _unsatisfied_release_context(
    entry: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    handoff_id: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    release_index = -1
    source_receipt: dict[str, Any] | None = None
    evidence: dict[str, Any] | None = None
    evidence_blocks: list[str] = []
    for index in range(len(receipts) - 1, -1, -1):
        row = receipts[index]
        if not isinstance(row, dict):
            continue
        candidate = row.get(recovery.EVIDENCE_FIELD) if isinstance(row.get(recovery.EVIDENCE_FIELD), dict) else None
        if not isinstance(candidate, dict) or _clean(candidate.get("handoff_id")) != handoff_id:
            continue
        blocks = _release_evidence_blocks(candidate, row, job, authorization_fingerprint)
        if blocks:
            evidence_blocks.extend(blocks)
            source_receipt = row
            evidence = candidate
            release_index = index
            break
        source_receipt = row
        evidence = candidate
        release_index = index
        break
    if release_index < 0:
        return None, None, []
    if evidence_blocks:
        return source_receipt, evidence, sorted(set(evidence_blocks))

    # A later provider-facing attempt for the same handoff already consumed this
    # release lineage. Intermediate CLAIMED attempts without network start do not.
    for row in receipts[release_index + 1 :]:
        if not isinstance(row, dict):
            continue
        if _receipt_handoff_id(row) != handoff_id:
            continue
        if _clean(row.get("network_started_at")):
            return None, None, []
    return source_receipt, evidence, []


def _provenance_blocks(
    provenance: dict[str, Any],
    *,
    evidence: dict[str, Any],
    source_receipt: dict[str, Any],
    current_receipt: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> list[str]:
    blocks: list[str] = []
    if not isinstance(provenance, dict):
        return ["REREAD_RECLAIM_PROVENANCE_REQUIRED"]
    if _clean(provenance.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_RECLAIM_PROVENANCE_SCHEMA_VERSION")
    if _clean(provenance.get("runtime_id")) != RUNTIME_ID:
        blocks.append("REREAD_RECLAIM_PROVENANCE_RUNTIME_ID")
    if _clean(provenance.get("action")) != ACTION:
        blocks.append("REREAD_RECLAIM_PROVENANCE_ACTION_INVALID")
    if not _clean(provenance.get("reclaim_binding_id")):
        blocks.append("REREAD_RECLAIM_PROVENANCE_ID_REQUIRED")
    expected_pairs = {
        "handoff_id": _clean(evidence.get("handoff_id")),
        "released_spend_id": _clean(evidence.get("spend_id")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "source_release_recovery_id": _clean(evidence.get("recovery_id")),
        "source_release_evidence_fingerprint_sha256": _clean(evidence.get("evidence_fingerprint_sha256")),
        "source_release_receipt_fingerprint_sha256": _clean(source_receipt.get("receipt_fingerprint_sha256")),
        "source_released_spend_record_fingerprint_sha256": _clean(evidence.get("source_spend_record_fingerprint_sha256")),
        "released_execution_id": _clean(evidence.get("execution_id")),
        "reclaim_execution_id": _clean(current_receipt.get("execution_id")),
    }
    for key, expected in expected_pairs.items():
        if not expected or not hmac.compare_digest(_clean(provenance.get(key)), expected):
            blocks.append("REREAD_RECLAIM_PROVENANCE_IDENTITY_MISMATCH:" + key)
    try:
        released_attempt = int(provenance.get("released_attempt") or 0)
        evidence_attempt = int(evidence.get("attempt") or 0)
        reclaim_attempt = int(provenance.get("reclaim_attempt") or 0)
        current_attempt = int(current_receipt.get("attempt") or 0)
    except (TypeError, ValueError):
        released_attempt = evidence_attempt = reclaim_attempt = current_attempt = 0
    if released_attempt <= 0 or released_attempt != evidence_attempt:
        blocks.append("REREAD_RECLAIM_PROVENANCE_RELEASED_ATTEMPT_MISMATCH")
    if reclaim_attempt <= released_attempt or reclaim_attempt != current_attempt:
        blocks.append("REREAD_RECLAIM_PROVENANCE_RECLAIM_ATTEMPT_MISMATCH")
    current_handoff = _receipt_handoff_id(current_receipt)
    if not current_handoff or current_handoff != _clean(evidence.get("handoff_id")):
        blocks.append("REREAD_RECLAIM_PROVENANCE_CURRENT_HANDOFF_MISMATCH")
    if not _clean(provenance.get("bound_at")):
        blocks.append("REREAD_RECLAIM_PROVENANCE_BOUND_AT_REQUIRED")
    if provenance.get("provider_network_call_performed_by_binding") is not False:
        blocks.append("REREAD_RECLAIM_PROVENANCE_NETWORK_BOUNDARY_VIOLATION")
    if provenance.get("publication_blocked") is not False:
        blocks.append("REREAD_RECLAIM_PROVENANCE_PUBLICATION_BOUNDARY_VIOLATION")
    if provenance.get("zero_paid_dependency") is not True:
        blocks.append("REREAD_RECLAIM_PROVENANCE_ZERO_PAID_POLICY_VIOLATION")
    supplied = _clean(provenance.get("provenance_fingerprint_sha256"))
    if not spend.SPEND_FINGERPRINT_RE.fullmatch(supplied) or supplied != _provenance_fingerprint(provenance):
        blocks.append("REREAD_RECLAIM_PROVENANCE_FINGERPRINT_MISMATCH")
    if spend.handoff._contains_forbidden_material(provenance):
        blocks.append("REREAD_RECLAIM_PROVENANCE_FORBIDDEN_MATERIAL")
    return sorted(set(blocks))


def _persist_reclaim_provenance(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    *,
    now: str,
) -> dict[str, Any]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_CHECKPOINT", "hard_blocks": state_blocks}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_CHECKPOINT", "hard_blocks": ["REREAD_RECLAIM_ENTRY_MISSING"]}
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_RECEIPT", "hard_blocks": list(checked.get("hard_blocks", []))}
    current = receipt._latest_receipt(entry)
    if not isinstance(current, dict) or _clean(current.get("status")).upper() != "CLAIMED" or _clean(current.get("network_started_at")):
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_RECEIPT", "hard_blocks": ["REREAD_RECLAIM_CURRENT_CLAIM_RECEIPT_REQUIRED"]}
    handoff_id = _receipt_handoff_id(current)
    if not handoff_id:
        return {"persisted": True, "status": "NO_REREAD_RECLAIM_REQUIRED", "hard_blocks": [], "written": False}
    source_receipt, evidence, release_blocks = _unsatisfied_release_context(
        entry, job, authorization_fingerprint, handoff_id
    )
    if release_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_RELEASE_EVIDENCE", "hard_blocks": release_blocks}
    if not isinstance(source_receipt, dict) or not isinstance(evidence, dict):
        return {"persisted": True, "status": "NO_REREAD_RECLAIM_REQUIRED", "hard_blocks": [], "written": False}

    existing = current.get(PROVENANCE_FIELD)
    if isinstance(existing, dict):
        blocks = _provenance_blocks(
            existing,
            evidence=evidence,
            source_receipt=source_receipt,
            current_receipt=current,
            job=job,
            authorization_fingerprint=authorization_fingerprint,
        )
        if blocks:
            return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_PROVENANCE", "hard_blocks": blocks}
        return {"persisted": True, "status": "REREAD_RECLAIM_PROVENANCE_ALREADY_BOUND", "hard_blocks": [], "written": False, "provenance": _clone(existing)}

    provenance = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "reclaim_binding_id": "metrics-reread-reclaim:" + _digest({
            "handoff_id": handoff_id,
            "release_evidence_fingerprint_sha256": _clean(evidence.get("evidence_fingerprint_sha256")),
            "reclaim_execution_id": _clean(current.get("execution_id")),
        })[:32],
        "action": ACTION,
        "handoff_id": handoff_id,
        "released_spend_id": _clean(evidence.get("spend_id")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "source_release_recovery_id": _clean(evidence.get("recovery_id")),
        "source_release_evidence_fingerprint_sha256": _clean(evidence.get("evidence_fingerprint_sha256")),
        "source_release_receipt_fingerprint_sha256": _clean(source_receipt.get("receipt_fingerprint_sha256")),
        "source_released_spend_record_fingerprint_sha256": _clean(evidence.get("source_spend_record_fingerprint_sha256")),
        "released_execution_id": _clean(evidence.get("execution_id")),
        "released_attempt": int(evidence.get("attempt") or 0),
        "reclaim_execution_id": _clean(current.get("execution_id")),
        "reclaim_attempt": int(current.get("attempt") or 0),
        "bound_at": runtime._iso(runtime._dt(now)),
        "provider_network_call_performed_by_binding": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    provenance["provenance_fingerprint_sha256"] = _provenance_fingerprint(provenance)
    provenance_blocks = _provenance_blocks(
        provenance,
        evidence=evidence,
        source_receipt=source_receipt,
        current_receipt=current,
        job=job,
        authorization_fingerprint=authorization_fingerprint,
    )
    if provenance_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RECLAIM_PROVENANCE", "hard_blocks": provenance_blocks}

    current[PROVENANCE_FIELD] = provenance
    current["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(current)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root,
        channel,
        state,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {
            "persisted": False,
            "status": persisted.get("status") or "HOLD_REREAD_RECLAIM_PROVENANCE_PERSISTENCE",
            "hard_blocks": list(persisted.get("hard_blocks", [])),
        }
    return {"persisted": True, "status": "REREAD_RECLAIM_PROVENANCE_BOUND", "hard_blocks": [], "written": True, "provenance": _clone(provenance)}


def claim_checkpoint_sealed(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    lease_minutes: int = runtime.DEFAULT_LEASE_MINUTES,
) -> dict[str, Any]:
    result = _BASE_CLAIM(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        lease_minutes=lease_minutes,
    )
    if result.get("claimed") is not True:
        return result
    bound = _persist_reclaim_provenance(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
        now=now,
    )
    if bound.get("persisted") is not True:
        return {
            "claimed": False,
            "status": bound.get("status") or "HOLD_REREAD_RECLAIM_PROVENANCE",
            "hard_blocks": list(bound.get("hard_blocks", [])),
            "entry": result.get("entry"),
            "publication_blocked": False,
        }
    if bound.get("status") == "NO_REREAD_RECLAIM_REQUIRED":
        return result
    final_state, final_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    final_entry = final_state.get("entries", {}).get(runtime.checkpoint_key(job)) if not final_blocks else None
    if final_blocks or not isinstance(final_entry, dict):
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RECLAIM_PROVENANCE_READBACK",
            "hard_blocks": final_blocks or ["REREAD_RECLAIM_PROVENANCE_READBACK_MISSING"],
            "publication_blocked": False,
        }
    merged = dict(result)
    merged["entry"] = _clone(final_entry)
    merged["reread_reservation_reclaim_provenance_bound"] = True
    merged["reread_reclaim_binding_id"] = _clean((bound.get("provenance") or {}).get("reclaim_binding_id"))
    return merged


def mark_network_started(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": state_blocks}
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return _BASE_MARK_NETWORK_STARTED(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint, now=now,
        )
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", "hard_blocks": list(checked.get("hard_blocks", []))}
    current = receipt._latest_receipt(entry)
    if not isinstance(current, dict):
        return {"persisted": False, "status": "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", "hard_blocks": ["REREAD_RECLAIM_CURRENT_RECEIPT_MISSING"]}
    handoff_id = _receipt_handoff_id(current)
    if handoff_id:
        source_receipt, evidence, release_blocks = _unsatisfied_release_context(
            entry, job, authorization_fingerprint, handoff_id
        )
        if release_blocks:
            return {"persisted": False, "status": "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", "hard_blocks": release_blocks}
        if isinstance(source_receipt, dict) and isinstance(evidence, dict):
            provenance = current.get(PROVENANCE_FIELD) if isinstance(current.get(PROVENANCE_FIELD), dict) else None
            if provenance is None:
                return {
                    "persisted": False,
                    "status": "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE",
                    "hard_blocks": ["REREAD_RECLAIM_PROVENANCE_REQUIRED_BEFORE_NETWORK"],
                }
            provenance_blocks = _provenance_blocks(
                provenance,
                evidence=evidence,
                source_receipt=source_receipt,
                current_receipt=current,
                job=job,
                authorization_fingerprint=authorization_fingerprint,
            )
            if provenance_blocks:
                return {"persisted": False, "status": "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", "hard_blocks": provenance_blocks}

    result = _BASE_MARK_NETWORK_STARTED(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
    )
    if result.get("persisted") is True and handoff_id:
        result = dict(result)
        result["reread_reservation_reclaim_provenance_verified"] = True
    return result


def install() -> None:
    """Install reclaim provenance outside reservation recovery and spend sealing."""
    global _INSTALLED
    if _INSTALLED or getattr(receipt, "_reread_spend_reclaim_binding_patch_id", None) == PATCH_ID:
        _INSTALLED = True
        return
    receipt.claim_checkpoint_sealed = claim_checkpoint_sealed
    receipt.mark_network_started = mark_network_started
    setattr(receipt, "_reread_spend_reclaim_binding_patch_id", PATCH_ID)
    _INSTALLED = True
