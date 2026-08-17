#!/usr/bin/env python3
"""Crash-safe reconciliation for RESERVED explicit observed-metrics re-read spend.

The spend seal is deliberately persisted before NETWORK_CALL_STARTED. If a worker
dies in that narrow window, a durable RESERVED record can remain even though no
provider read was allowed to start. This layer reconciles that state from durable
checkpoint/receipt evidence only:

* active CLAIMED lease -> leave the reservation untouched;
* expired CLAIMED receipt with no network-start proof -> persist release evidence
  into the sealed execution receipt, then CAS-remove exactly that reservation;
* NETWORK_CALL_STARTED receipt -> conservatively seal the reservation SPENT and
  require a fresh explicit reauthorization;
* missing, contradictory or tampered evidence -> fail closed.

No provider call is made here. Credential values and provider payloads are never
read or persisted. Analytics remains advisory-only and zero-paid.
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

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-spend-reservation-recovery-v1"
PATCH_ID = RUNTIME_ID + ":installed"
EVIDENCE_FIELD = "reread_spend_reservation_recovery"

# The spend boundary must be installed first; this recovery layer wraps only claim.
spend.install()
_BASE_CLAIM = receipt.claim_checkpoint_sealed
_INSTALLED = False


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def recovery_guards() -> dict[str, Any]:
    return {
        "reserved_release_requires_expired_claimed_receipt": True,
        "active_lease_release_allowed": False,
        "network_start_receipt_forces_spent": True,
        "ambiguous_reservation_release_allowed": False,
        "release_evidence_persisted_before_reservation_removal": True,
        "reservation_removal_compare_and_swap": True,
        "provider_network_call_performed_by_recovery": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _evidence_fingerprint(value: dict[str, Any]) -> str:
    unsigned = _clone(value)
    unsigned.pop("evidence_fingerprint_sha256", None)
    return _digest(unsigned)


def _evidence_blocks(
    evidence: dict[str, Any],
    *,
    record: dict[str, Any],
    entry: dict[str, Any],
    latest: dict[str, Any],
    handoff_id: str,
    authorization_fingerprint: str,
) -> list[str]:
    blocks: list[str] = []
    if _clean(evidence.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_RESERVATION_RECOVERY_SCHEMA_VERSION")
    if _clean(evidence.get("runtime_id")) != RUNTIME_ID:
        blocks.append("REREAD_RESERVATION_RECOVERY_RUNTIME_ID")
    if _clean(evidence.get("action")) != "RELEASE_AUTHORIZED_NO_NETWORK_START":
        blocks.append("REREAD_RESERVATION_RECOVERY_ACTION_INVALID")
    if not _clean(evidence.get("recovery_id")):
        blocks.append("REREAD_RESERVATION_RECOVERY_ID_REQUIRED")
    expected_pairs = {
        "handoff_id": handoff_id,
        "spend_id": _clean(record.get("spend_id")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": _clean(entry.get("checkpoint_key")),
        "job_fingerprint_sha256": _clean(entry.get("job_fingerprint_sha256")),
        "execution_id": _clean(latest.get("execution_id")),
        "source_spend_record_fingerprint_sha256": _clean(record.get("record_fingerprint_sha256")),
        "reservation_receipt_fingerprint_sha256": _clean(record.get("reservation_receipt_fingerprint_sha256")),
    }
    for key, expected in expected_pairs.items():
        if not expected or not hmac.compare_digest(_clean(evidence.get(key)), expected):
            blocks.append("REREAD_RESERVATION_RECOVERY_IDENTITY_MISMATCH:" + key)
    try:
        evidence_attempt = int(evidence.get("attempt") or 0)
        latest_attempt = int(latest.get("attempt") or 0)
    except (TypeError, ValueError):
        evidence_attempt = latest_attempt = 0
    if evidence_attempt <= 0 or evidence_attempt != latest_attempt:
        blocks.append("REREAD_RESERVATION_RECOVERY_ATTEMPT_MISMATCH")
    if not _clean(evidence.get("lease_expires_at")) or not _clean(evidence.get("reconciled_at")):
        blocks.append("REREAD_RESERVATION_RECOVERY_TIMESTAMP_REQUIRED")
    if evidence.get("network_start_proven") is not False:
        blocks.append("REREAD_RESERVATION_RECOVERY_NETWORK_PROOF_INVALID")
    if evidence.get("provider_read_result_proven") is not False:
        blocks.append("REREAD_RESERVATION_RECOVERY_PROVIDER_RESULT_INVALID")
    if evidence.get("provider_network_call_performed_by_recovery") is not False:
        blocks.append("REREAD_RESERVATION_RECOVERY_NETWORK_BOUNDARY_VIOLATION")
    if evidence.get("publication_blocked") is not False:
        blocks.append("REREAD_RESERVATION_RECOVERY_PUBLICATION_BOUNDARY_VIOLATION")
    if evidence.get("zero_paid_dependency") is not True:
        blocks.append("REREAD_RESERVATION_RECOVERY_ZERO_PAID_POLICY_VIOLATION")
    supplied = _clean(evidence.get("evidence_fingerprint_sha256"))
    if not spend.SPEND_FINGERPRINT_RE.fullmatch(supplied) or supplied != _evidence_fingerprint(evidence):
        blocks.append("REREAD_RESERVATION_RECOVERY_FINGERPRINT_MISMATCH")
    if spend.handoff._contains_forbidden_material(evidence):
        blocks.append("REREAD_RESERVATION_RECOVERY_FORBIDDEN_MATERIAL")
    return sorted(set(blocks))


def _reservation_context(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, dict[str, Any] | None, str, list[str]]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return None, None, None, "", list(state_blocks)
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return None, None, None, "", []
    latest = receipt._latest_receipt(entry)
    if not isinstance(latest, dict):
        return entry, None, None, "", ["REREAD_RESERVATION_RECOVERY_RECEIPT_MISSING"]
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return entry, latest, None, "", list(checked.get("hard_blocks", []))

    handoff_id = spend._lineage_handoff_id(entry)
    if not handoff_id:
        return entry, latest, None, "", []

    record, record_blocks = spend._spend_record(repo_root, channel, handoff_id)
    if record_blocks:
        return entry, latest, None, handoff_id, list(record_blocks)
    if not isinstance(record, dict):
        return entry, latest, None, handoff_id, []

    identity_blocks: list[str] = []
    if _clean(record.get("status")).upper() != "RESERVED":
        return entry, latest, record, handoff_id, []
    expected = {
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "execution_id": _clean(latest.get("execution_id")),
    }
    for key, expected_value in expected.items():
        if not expected_value or not hmac.compare_digest(_clean(record.get(key)), expected_value):
            identity_blocks.append("REREAD_RESERVATION_RECOVERY_IDENTITY_MISMATCH:" + key)
    try:
        if int(record.get("attempt") or 0) != int(latest.get("attempt") or 0):
            identity_blocks.append("REREAD_RESERVATION_RECOVERY_ATTEMPT_MISMATCH")
    except (TypeError, ValueError):
        identity_blocks.append("REREAD_RESERVATION_RECOVERY_ATTEMPT_MISMATCH")
    return entry, latest, record, handoff_id, sorted(set(identity_blocks))


def _persist_release_evidence(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    record: dict[str, Any],
    handoff_id: str,
    *,
    now: str,
) -> dict[str, Any]:
    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_CHECKPOINT", "hard_blocks": state_blocks}
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    latest = receipt._latest_receipt(entry) if isinstance(entry, dict) else None
    if not isinstance(entry, dict) or not isinstance(latest, dict):
        return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_CHECKPOINT", "hard_blocks": ["REREAD_RESERVATION_RECOVERY_RECEIPT_MISSING"]}

    existing = latest.get(EVIDENCE_FIELD)
    if isinstance(existing, dict):
        blocks = _evidence_blocks(
            existing,
            record=record,
            entry=entry,
            latest=latest,
            handoff_id=handoff_id,
            authorization_fingerprint=authorization_fingerprint,
        )
        if blocks:
            return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE", "hard_blocks": blocks}
        return {"persisted": True, "status": "REREAD_RESERVATION_RELEASE_EVIDENCE_ALREADY_PERSISTED", "hard_blocks": [], "evidence": _clone(existing)}

    latest_fp = _clean(latest.get("receipt_fingerprint_sha256"))
    reservation_fp = _clean(record.get("reservation_receipt_fingerprint_sha256"))
    if not latest_fp or not hmac.compare_digest(latest_fp, reservation_fp):
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_RECEIPT",
            "hard_blocks": ["REREAD_RESERVATION_RECEIPT_CHANGED_BEFORE_RELEASE_EVIDENCE"],
        }

    evidence = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "recovery_id": "metrics-reread-reservation-recovery:" + _digest({
            "handoff_id": handoff_id,
            "spend_id": _clean(record.get("spend_id")),
            "execution_id": _clean(latest.get("execution_id")),
            "source_spend_record_fingerprint_sha256": _clean(record.get("record_fingerprint_sha256")),
        })[:32],
        "action": "RELEASE_AUTHORIZED_NO_NETWORK_START",
        "handoff_id": handoff_id,
        "spend_id": _clean(record.get("spend_id")),
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": _clean(entry.get("checkpoint_key")),
        "job_fingerprint_sha256": _clean(entry.get("job_fingerprint_sha256")),
        "execution_id": _clean(latest.get("execution_id")),
        "attempt": int(latest.get("attempt") or 0),
        "source_spend_record_fingerprint_sha256": _clean(record.get("record_fingerprint_sha256")),
        "reservation_receipt_fingerprint_sha256": reservation_fp,
        "lease_expires_at": _clean(entry.get("lease_expires_at")),
        "reconciled_at": runtime._iso(runtime._dt(now)),
        "network_start_proven": False,
        "provider_read_result_proven": False,
        "provider_network_call_performed_by_recovery": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    evidence["evidence_fingerprint_sha256"] = _evidence_fingerprint(evidence)
    evidence_blocks = _evidence_blocks(
        evidence,
        record=record,
        entry=entry,
        latest=latest,
        handoff_id=handoff_id,
        authorization_fingerprint=authorization_fingerprint,
    )
    if evidence_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE", "hard_blocks": evidence_blocks}

    latest[EVIDENCE_FIELD] = evidence
    latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
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
            "status": persisted.get("status") or "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE_PERSISTENCE",
            "hard_blocks": list(persisted.get("hard_blocks", [])),
        }
    return {"persisted": True, "status": "REREAD_RESERVATION_RELEASE_EVIDENCE_PERSISTED", "hard_blocks": [], "evidence": _clone(evidence)}


def _remove_reserved_record_cas(
    repo_root: Path,
    channel: dict[str, Any],
    handoff_id: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    store, store_blocks, _ = spend.load_spend_store(repo_root, channel)
    if store_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_SPEND_STORE", "hard_blocks": store_blocks}
    previous_fp = _clean(store.get("store_fingerprint_sha256")) or None
    current = store.get("records", {}).get(handoff_id)
    if not isinstance(current, dict):
        return {"persisted": True, "status": "REREAD_RESERVATION_ALREADY_RELEASED", "hard_blocks": [], "written": False}
    current_blocks = spend._record_blocks(current)
    if current_blocks:
        return {"persisted": False, "status": "HOLD_REREAD_RESERVATION_RECOVERY_SPEND_TAMPERED", "hard_blocks": current_blocks}
    if _clean(current.get("status")).upper() != "RESERVED":
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_SPEND_STATE",
            "hard_blocks": ["REREAD_RESERVATION_NOT_RESERVED_AT_RELEASE"],
        }
    if not hmac.compare_digest(
        _clean(current.get("record_fingerprint_sha256")),
        _clean(record.get("record_fingerprint_sha256")),
    ):
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_SPEND_CAS",
            "hard_blocks": ["REREAD_RESERVATION_SOURCE_RECORD_CHANGED"],
        }
    updated = _clone(store)
    updated["records"].pop(handoff_id, None)
    updated["store_fingerprint_sha256"] = spend._store_fingerprint(updated)
    persisted = spend.persist_spend_store_cas(
        repo_root,
        channel,
        updated,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return {
            "persisted": False,
            "status": persisted.get("status") or "HOLD_REREAD_RESERVATION_RECOVERY_SPEND_PERSISTENCE",
            "hard_blocks": list(persisted.get("hard_blocks", [])),
        }
    return {"persisted": True, "status": "REREAD_RESERVATION_RELEASED", "hard_blocks": [], "written": True}


def _reconcile_reserved(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
    *,
    now: str,
) -> dict[str, Any] | None:
    entry, latest, record, handoff_id, blocks = _reservation_context(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
    )
    if blocks:
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY",
            "hard_blocks": blocks,
            "entry": _clone(entry) if isinstance(entry, dict) else None,
            "publication_blocked": False,
        }
    if not isinstance(record, dict) or _clean(record.get("status")).upper() != "RESERVED":
        return None
    if not isinstance(entry, dict) or not isinstance(latest, dict):
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY",
            "hard_blocks": ["REREAD_RESERVATION_RECOVERY_RECEIPT_MISSING"],
            "publication_blocked": False,
        }

    receipt_status = _clean(latest.get("status")).upper()
    if receipt_status == "NETWORK_CALL_STARTED":
        provenance = latest.get("reread_attempt_provenance")
        if not isinstance(provenance, dict):
            provenance = {"handoff_id": handoff_id}
        sealed = spend._finalize_spend(
            repo_root,
            channel,
            job,
            authorization_fingerprint,
            provenance,
        )
        if sealed.get("persisted") is not True:
            return {
                "claimed": False,
                "status": "HOLD_REREAD_RESERVATION_RECOVERY_SPENT_RECONCILIATION",
                "hard_blocks": list(sealed.get("hard_blocks", [])) or ["REREAD_RESERVATION_SPENT_RECONCILIATION_FAILED"],
                "entry": _clone(entry),
                "publication_blocked": False,
            }
        return {
            "claimed": False,
            "status": "HOLD_REREAD_REAUTHORIZATION_REQUIRED",
            "hard_blocks": ["REREAD_RESERVATION_NETWORK_START_PROOF_REQUIRES_FRESH_REAUTHORIZATION"],
            "entry": _clone(entry),
            "publication_blocked": False,
            "reread_reservation_reconciled": "SPENT",
            "spent_handoff_id": handoff_id,
        }

    if receipt_status != "CLAIMED" or _clean(latest.get("network_started_at")):
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_AMBIGUOUS",
            "hard_blocks": ["REREAD_RESERVATION_DURABLE_EVIDENCE_AMBIGUOUS"],
            "entry": _clone(entry),
            "publication_blocked": False,
        }
    if _clean(entry.get("status")).upper() != "IN_FLIGHT":
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_AMBIGUOUS",
            "hard_blocks": ["REREAD_RESERVATION_CHECKPOINT_NOT_IN_FLIGHT"],
            "entry": _clone(entry),
            "publication_blocked": False,
        }

    lease_raw = _clean(entry.get("lease_expires_at"))
    if not lease_raw:
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_AMBIGUOUS",
            "hard_blocks": ["REREAD_RESERVATION_LEASE_PROOF_REQUIRED"],
            "entry": _clone(entry),
            "publication_blocked": False,
        }
    try:
        lease_dt = runtime._dt(lease_raw)
        now_dt = runtime._dt(now)
    except ValueError:
        return {
            "claimed": False,
            "status": "HOLD_REREAD_RESERVATION_RECOVERY_AMBIGUOUS",
            "hard_blocks": ["REREAD_RESERVATION_LEASE_TIMESTAMP_INVALID"],
            "entry": _clone(entry),
            "publication_blocked": False,
        }
    if lease_dt > now_dt:
        return {
            "claimed": False,
            "status": "LEASE_ACTIVE",
            "hard_blocks": [],
            "entry": _clone(entry),
            "publication_blocked": False,
            "reread_reservation_release_allowed": False,
        }

    existing_evidence = latest.get(EVIDENCE_FIELD)
    if isinstance(existing_evidence, dict):
        evidence_blocks = _evidence_blocks(
            existing_evidence,
            record=record,
            entry=entry,
            latest=latest,
            handoff_id=handoff_id,
            authorization_fingerprint=authorization_fingerprint,
        )
        if evidence_blocks:
            return {
                "claimed": False,
                "status": "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE",
                "hard_blocks": evidence_blocks,
                "entry": _clone(entry),
                "publication_blocked": False,
            }
    else:
        if not hmac.compare_digest(
            _clean(latest.get("receipt_fingerprint_sha256")),
            _clean(record.get("reservation_receipt_fingerprint_sha256")),
        ):
            return {
                "claimed": False,
                "status": "HOLD_REREAD_RESERVATION_RECOVERY_RECEIPT",
                "hard_blocks": ["REREAD_RESERVATION_RECEIPT_CHANGED_BEFORE_RELEASE"],
                "entry": _clone(entry),
                "publication_blocked": False,
            }

    evidenced = _persist_release_evidence(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
        record,
        handoff_id,
        now=now,
    )
    if evidenced.get("persisted") is not True:
        return {
            "claimed": False,
            "status": evidenced.get("status") or "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE",
            "hard_blocks": list(evidenced.get("hard_blocks", [])),
            "entry": _clone(entry),
            "publication_blocked": False,
        }

    released = _remove_reserved_record_cas(repo_root, channel, handoff_id, record)
    if released.get("persisted") is not True:
        return {
            "claimed": False,
            "status": released.get("status") or "HOLD_REREAD_RESERVATION_RECOVERY_RELEASE",
            "hard_blocks": list(released.get("hard_blocks", [])),
            "entry": _clone(entry),
            "publication_blocked": False,
        }
    return {
        "claimed": None,
        "status": "REREAD_RESERVATION_RELEASED_NO_NETWORK_START",
        "hard_blocks": [],
        "entry": _clone(entry),
        "publication_blocked": False,
        "reread_reservation_reconciled": "RELEASED_NO_NETWORK_START",
        "released_handoff_id": handoff_id,
    }


def claim_checkpoint_sealed(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    lease_minutes: int = runtime.DEFAULT_LEASE_MINUTES,
) -> dict[str, Any]:
    reconciled = _reconcile_reserved(
        repo_root,
        channel,
        job,
        authorization_fingerprint,
        now=now,
    )
    if reconciled is not None and reconciled.get("claimed") is not None:
        return reconciled
    result = _BASE_CLAIM(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        lease_minutes=lease_minutes,
    )
    if reconciled is not None and reconciled.get("reread_reservation_reconciled"):
        result = dict(result)
        result["reread_reservation_reconciled"] = reconciled["reread_reservation_reconciled"]
        result["released_handoff_id"] = reconciled.get("released_handoff_id")
    return result


def install() -> None:
    """Install RESERVED-spend reconciliation around the spend-aware claim boundary."""
    global _INSTALLED
    if _INSTALLED or getattr(receipt, "_reread_spend_reservation_recovery_patch_id", None) == PATCH_ID:
        _INSTALLED = True
        return
    receipt.claim_checkpoint_sealed = claim_checkpoint_sealed
    setattr(receipt, "_reread_spend_reservation_recovery_patch_id", PATCH_ID)
    _INSTALLED = True
