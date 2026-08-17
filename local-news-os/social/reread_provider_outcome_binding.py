#!/usr/bin/env python3
"""Atomically bind an explicit provider re-read outcome to its authorization lineage.

The explicit re-read path is already sealed before a provider call: recovery evidence
is bound to the reclaim attempt and the single-use handoff is marked SPENT before
network execution. This layer closes the post-network gap. A provider-facing re-read
cannot transition from NETWORK_CALL_STARTED to a durable checkpoint outcome unless
that exact outcome is atomically sealed to the reclaim provenance and current SPENT
record.

The binding stores only authorization/provenance metadata and normalized outcome
status. It performs no provider call, reads no credential value, persists no raw
provider payload, never blocks editorial publication, and preserves zero-paid policy.
Normal non-reread harvest transitions are delegated unchanged.
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
import reread_spend_reclaim_binding as reclaim

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-provider-outcome-binding-v1"
PATCH_ID = RUNTIME_ID + ":installed"
OUTCOME_FIELD = "reread_provider_outcome_provenance"
ACTION = "SEAL_PROVIDER_REREAD_OUTCOME"
ALLOWED_TRANSITION_STATUSES = {
    "COMPLETED",
    "COMPLETED_NO_DATA",
    "RETRY_WAIT",
    "BLOCKED_AUTH",
    "HOLD_ANALYTICS",
    "RECOVERY_REQUIRED",
}

# Preserve the established install order before wrapping the terminal transition.
spend.install()
recovery.install()
reclaim.install()
_BASE_TRANSITION = receipt.transition_sealed
_INSTALLED = False


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def outcome_guards() -> dict[str, Any]:
    return {
        "reclaim_provenance_required_for_reread_outcome": True,
        "spent_handoff_required_before_outcome": True,
        "network_start_receipt_bound": True,
        "provider_outcome_bound_atomically_with_checkpoint_transition": True,
        "materialization_fingerprint_bound_when_present": True,
        "normal_non_reread_transition_unchanged": True,
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _outcome_fingerprint(value: dict[str, Any]) -> str:
    unsigned = _clone(value)
    unsigned.pop("outcome_fingerprint_sha256", None)
    return _digest(unsigned)


def _find_release_source(
    entry: dict[str, Any],
    provenance: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    expected_receipt_fp = _clean(provenance.get("source_release_receipt_fingerprint_sha256"))
    expected_evidence_fp = _clean(provenance.get("source_release_evidence_fingerprint_sha256"))
    handoff_id = _clean(provenance.get("handoff_id"))
    for row in receipts:
        if not isinstance(row, dict):
            continue
        evidence = row.get(recovery.EVIDENCE_FIELD) if isinstance(row.get(recovery.EVIDENCE_FIELD), dict) else None
        if not isinstance(evidence, dict):
            continue
        if _clean(evidence.get("handoff_id")) != handoff_id:
            continue
        if expected_receipt_fp and not hmac.compare_digest(_clean(row.get("receipt_fingerprint_sha256")), expected_receipt_fp):
            continue
        if expected_evidence_fp and not hmac.compare_digest(_clean(evidence.get("evidence_fingerprint_sha256")), expected_evidence_fp):
            continue
        blocks = reclaim._release_evidence_blocks(evidence, row, job, authorization_fingerprint)
        return row, evidence, blocks
    return None, None, ["REREAD_OUTCOME_RELEASE_SOURCE_NOT_FOUND"]


def _spent_record(
    repo_root: Path,
    channel: dict[str, Any],
    current_receipt: dict[str, Any],
    provenance: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, list[str]]:
    handoff_id = _clean(provenance.get("handoff_id"))
    record, blocks = spend._spend_record(repo_root, channel, handoff_id)
    if blocks:
        return None, blocks
    if not isinstance(record, dict):
        return None, ["REREAD_OUTCOME_SPENT_RECORD_REQUIRED"]
    if _clean(record.get("status")).upper() != "SPENT":
        blocks.append("REREAD_OUTCOME_HANDOFF_NOT_SPENT")
    expected = {
        "handoff_id": handoff_id,
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": _clean(current_receipt.get("checkpoint_key")),
        "job_fingerprint_sha256": _clean(current_receipt.get("job_fingerprint_sha256")),
        "execution_id": _clean(current_receipt.get("execution_id")),
    }
    for key, expected_value in expected.items():
        if not expected_value or not hmac.compare_digest(_clean(record.get(key)), expected_value):
            blocks.append("REREAD_OUTCOME_SPEND_IDENTITY_MISMATCH:" + key)
    if not _clean(record.get("spend_id")):
        blocks.append("REREAD_OUTCOME_CURRENT_SPEND_ID_REQUIRED")
    # A safely released reservation and its later reclaim are distinct spend records.
    # The current SPENT record must therefore not be confused with released_spend_id.
    if _clean(record.get("spend_id")) == _clean(provenance.get("released_spend_id")):
        blocks.append("REREAD_OUTCOME_CURRENT_SPEND_REUSED_RELEASED_SPEND_ID")
    try:
        if int(record.get("attempt") or 0) != int(current_receipt.get("attempt") or 0):
            blocks.append("REREAD_OUTCOME_SPEND_ATTEMPT_MISMATCH")
    except (TypeError, ValueError):
        blocks.append("REREAD_OUTCOME_SPEND_ATTEMPT_MISMATCH")
    if record.get("provider_reads_spent") != 1:
        blocks.append("REREAD_OUTCOME_SPEND_COUNT_INVALID")
    if not _clean(record.get("network_started_at")):
        blocks.append("REREAD_OUTCOME_NETWORK_STARTED_AT_REQUIRED")
    if not hmac.compare_digest(
        _clean(record.get("network_receipt_fingerprint_sha256")),
        _clean(current_receipt.get("receipt_fingerprint_sha256")),
    ):
        blocks.append("REREAD_OUTCOME_NETWORK_RECEIPT_FINGERPRINT_MISMATCH")
    return (record if not blocks else None), sorted(set(blocks))


def _context(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    entry: dict[str, Any],
    current_receipt: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    provenance = current_receipt.get(reclaim.PROVENANCE_FIELD) if isinstance(current_receipt.get(reclaim.PROVENANCE_FIELD), dict) else None
    if provenance is None:
        return None, None, None, None, []
    source_receipt, evidence, release_blocks = _find_release_source(
        entry, provenance, job, authorization_fingerprint
    )
    blocks = list(release_blocks)
    if isinstance(source_receipt, dict) and isinstance(evidence, dict):
        blocks.extend(reclaim._provenance_blocks(
            provenance,
            evidence=evidence,
            source_receipt=source_receipt,
            current_receipt=current_receipt,
            job=job,
            authorization_fingerprint=authorization_fingerprint,
        ))
    record, spend_blocks = _spent_record(
        repo_root, channel, current_receipt, provenance, authorization_fingerprint
    )
    blocks.extend(spend_blocks)
    return provenance, source_receipt, evidence, record, sorted(set(blocks))


def _build_outcome(
    *,
    provenance: dict[str, Any],
    evidence: dict[str, Any],
    spend_record: dict[str, Any],
    current_receipt: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    now: str,
    status: str,
    last_result_status: str,
    retry_after_at: str | None,
    materialization_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    now_iso = runtime._iso(runtime._dt(now))
    outcome = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "outcome_binding_id": "metrics-reread-outcome:" + _digest({
            "reclaim_binding_id": _clean(provenance.get("reclaim_binding_id")),
            "execution_id": _clean(current_receipt.get("execution_id")),
            "checkpoint_status": status,
            "provider_result_status": last_result_status,
            "materialization_fingerprint_sha256": _clean(materialization_fingerprint_sha256),
        })[:32],
        "action": ACTION,
        "handoff_id": _clean(provenance.get("handoff_id")),
        "released_spend_id": _clean(provenance.get("released_spend_id")),
        "current_spend_id": _clean(spend_record.get("spend_id")),
        "reclaim_binding_id": _clean(provenance.get("reclaim_binding_id")),
        "reclaim_provenance_fingerprint_sha256": _clean(provenance.get("provenance_fingerprint_sha256")),
        "source_release_evidence_fingerprint_sha256": _clean(evidence.get("evidence_fingerprint_sha256")),
        "spend_record_fingerprint_sha256": _clean(spend_record.get("record_fingerprint_sha256")),
        "network_receipt_fingerprint_sha256": _clean(spend_record.get("network_receipt_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean((job.get("publication") or {}).get("remote_publication_id")),
        "execution_id": _clean(current_receipt.get("execution_id")),
        "attempt": int(current_receipt.get("attempt") or 0),
        "network_started_at": _clean(current_receipt.get("network_started_at")),
        "checkpoint_status": status,
        "provider_result_status": last_result_status,
        "retry_after_at": _clean(retry_after_at) or None,
        "materialization_fingerprint_sha256": _clean(materialization_fingerprint_sha256) or None,
        "bound_at": now_iso,
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    outcome["outcome_fingerprint_sha256"] = _outcome_fingerprint(outcome)
    return outcome


def _outcome_blocks(
    outcome: dict[str, Any],
    *,
    provenance: dict[str, Any],
    evidence: dict[str, Any],
    spend_record: dict[str, Any],
    current_receipt: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    status: str,
    last_result_status: str,
    retry_after_at: str | None,
    materialization_fingerprint_sha256: str | None,
) -> list[str]:
    blocks: list[str] = []
    if not isinstance(outcome, dict):
        return ["REREAD_OUTCOME_PROVENANCE_REQUIRED"]
    if _clean(outcome.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_OUTCOME_SCHEMA_VERSION")
    if _clean(outcome.get("runtime_id")) != RUNTIME_ID:
        blocks.append("REREAD_OUTCOME_RUNTIME_ID")
    if _clean(outcome.get("action")) != ACTION:
        blocks.append("REREAD_OUTCOME_ACTION_INVALID")
    if not _clean(outcome.get("outcome_binding_id")):
        blocks.append("REREAD_OUTCOME_BINDING_ID_REQUIRED")
    expected = {
        "handoff_id": _clean(provenance.get("handoff_id")),
        "released_spend_id": _clean(provenance.get("released_spend_id")),
        "current_spend_id": _clean(spend_record.get("spend_id")),
        "reclaim_binding_id": _clean(provenance.get("reclaim_binding_id")),
        "reclaim_provenance_fingerprint_sha256": _clean(provenance.get("provenance_fingerprint_sha256")),
        "source_release_evidence_fingerprint_sha256": _clean(evidence.get("evidence_fingerprint_sha256")),
        "spend_record_fingerprint_sha256": _clean(spend_record.get("record_fingerprint_sha256")),
        "network_receipt_fingerprint_sha256": _clean(spend_record.get("network_receipt_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean((job.get("publication") or {}).get("remote_publication_id")),
        "execution_id": _clean(current_receipt.get("execution_id")),
        "network_started_at": _clean(current_receipt.get("network_started_at")),
        "checkpoint_status": status,
        "provider_result_status": last_result_status,
        "retry_after_at": _clean(retry_after_at),
        "materialization_fingerprint_sha256": _clean(materialization_fingerprint_sha256),
    }
    for key, expected_value in expected.items():
        actual = _clean(outcome.get(key))
        if actual != expected_value:
            blocks.append("REREAD_OUTCOME_IDENTITY_MISMATCH:" + key)
    try:
        if int(outcome.get("attempt") or 0) != int(current_receipt.get("attempt") or 0):
            blocks.append("REREAD_OUTCOME_ATTEMPT_MISMATCH")
    except (TypeError, ValueError):
        blocks.append("REREAD_OUTCOME_ATTEMPT_MISMATCH")
    if not _clean(outcome.get("bound_at")):
        blocks.append("REREAD_OUTCOME_BOUND_AT_REQUIRED")
    required_bools = {
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    for key, expected_bool in required_bools.items():
        if outcome.get(key) is not expected_bool:
            blocks.append("REREAD_OUTCOME_GUARD:" + key)
    supplied = _clean(outcome.get("outcome_fingerprint_sha256"))
    if not spend.SPEND_FINGERPRINT_RE.fullmatch(supplied) or supplied != _outcome_fingerprint(outcome):
        blocks.append("REREAD_OUTCOME_FINGERPRINT_MISMATCH")
    if spend.handoff._contains_forbidden_material(outcome):
        blocks.append("REREAD_OUTCOME_FORBIDDEN_MATERIAL")
    return sorted(set(blocks))


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
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {"persisted": False, "status": "HOLD_CHECKPOINT_STATE", "hard_blocks": state_blocks}
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return _BASE_TRANSITION(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now, status=status, last_result_status=last_result_status,
            retry_after_at=retry_after_at,
            materialization_fingerprint_sha256=materialization_fingerprint_sha256,
        )
    current = receipt._latest_receipt(entry)
    provenance = current.get(reclaim.PROVENANCE_FIELD) if isinstance(current, dict) and isinstance(current.get(reclaim.PROVENANCE_FIELD), dict) else None
    if provenance is None:
        return _BASE_TRANSITION(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now, status=status, last_result_status=last_result_status,
            retry_after_at=retry_after_at,
            materialization_fingerprint_sha256=materialization_fingerprint_sha256,
        )

    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_REREAD_OUTCOME_RECEIPT", "hard_blocks": list(checked.get("hard_blocks", []))}
    target_status = _clean(status).upper()
    if target_status not in ALLOWED_TRANSITION_STATUSES:
        return {"persisted": False, "status": "HOLD_REREAD_OUTCOME_STATUS", "hard_blocks": ["REREAD_OUTCOME_CHECKPOINT_STATUS_INVALID"]}
    if not isinstance(current, dict) or _clean(current.get("status")).upper() != "NETWORK_CALL_STARTED" or not _clean(current.get("network_started_at")):
        return {"persisted": False, "status": "HOLD_REREAD_OUTCOME_NETWORK_PROOF", "hard_blocks": ["REREAD_OUTCOME_NETWORK_START_RECEIPT_REQUIRED"]}
    if materialization_fingerprint_sha256 and not receipt.RECEIPT_FINGERPRINT_RE.fullmatch(_clean(materialization_fingerprint_sha256)):
        return {"persisted": False, "status": "HOLD_REREAD_OUTCOME_MATERIALIZATION", "hard_blocks": ["REREAD_OUTCOME_MATERIALIZATION_FINGERPRINT_INVALID"]}

    provenance, source_receipt, evidence, spend_record, context_blocks = _context(
        repo_root, channel, job, entry, current, authorization_fingerprint
    )
    if context_blocks or not all(isinstance(value, dict) for value in (provenance, source_receipt, evidence, spend_record)):
        return {
            "persisted": False,
            "status": "HOLD_REREAD_OUTCOME_LINEAGE",
            "hard_blocks": context_blocks or ["REREAD_OUTCOME_LINEAGE_INCOMPLETE"],
        }

    outcome = _build_outcome(
        provenance=provenance,
        evidence=evidence,
        spend_record=spend_record,
        current_receipt=current,
        job=job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        status=target_status,
        last_result_status=_clean(last_result_status),
        retry_after_at=retry_after_at,
        materialization_fingerprint_sha256=materialization_fingerprint_sha256,
    )
    outcome_blocks = _outcome_blocks(
        outcome,
        provenance=provenance,
        evidence=evidence,
        spend_record=spend_record,
        current_receipt=current,
        job=job,
        authorization_fingerprint=authorization_fingerprint,
        status=target_status,
        last_result_status=_clean(last_result_status),
        retry_after_at=retry_after_at,
        materialization_fingerprint_sha256=materialization_fingerprint_sha256,
    )
    if outcome_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_OUTCOME_PROVENANCE", "hard_blocks": outcome_blocks}

    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    now_iso = runtime._iso(runtime._dt(now))
    entry["status"] = target_status
    entry["last_result_status"] = last_result_status
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = retry_after_at
    entry["completed_at"] = now_iso if target_status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"} else None
    current["status"] = target_status
    current["provider_result_status"] = last_result_status
    current["checkpoint_status"] = target_status
    current["updated_at"] = now_iso
    current["materialization_fingerprint_sha256"] = materialization_fingerprint_sha256
    current[OUTCOME_FIELD] = outcome
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
            "status": persisted.get("status") or "HOLD_REREAD_OUTCOME_PERSISTENCE",
            "hard_blocks": list(persisted.get("hard_blocks", [])),
        }
    result = dict(persisted)
    result.update({
        "reread_provider_outcome_bound": True,
        "reread_provider_outcome_binding_id": outcome["outcome_binding_id"],
        "publication_blocked": False,
    })
    return result


def install() -> None:
    """Install atomic terminal outcome binding on the authorization-sealed runtime."""
    global _INSTALLED
    if _INSTALLED or getattr(receipt, "_reread_provider_outcome_binding_patch_id", None) == PATCH_ID:
        _INSTALLED = True
        return
    receipt.transition_sealed = transition_sealed
    setattr(receipt, "_reread_provider_outcome_binding_patch_id", PATCH_ID)
    _INSTALLED = True
