#!/usr/bin/env python3
"""Durable, single-use authorization handoff for ambiguous metrics re-reads.

A RECOVERY_REQUIRED observed-metrics checkpoint must first be reconciled against
its durable observation ledger. Only when no durable observation covers the
checkpoint may an operator issue this handoff. Issuing the handoff performs no
provider I/O and keeps the checkpoint in RECOVERY_REQUIRED. Consuming it is a
separate CAS-protected operation that rechecks the sealed authorization, receipt,
job identity and observation ledger immediately before making one future read
eligible via RETRY_WAIT.

The handoff is secret-free, analytics-only and zero-paid. It never contains a
credential value or raw provider payload and cannot block editorial publication.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import authorization_sealed_harvest_recovery as recovery
import metrics_harvest_runtime as runtime

SCHEMA_VERSION = "1.0"
HANDOFF_ID = "local-news-os-provider-reread-authorization-handoff"
FP_RE = re.compile(r"^[0-9a-f]{64}$")
DECISION_RE = re.compile(r"^[A-Za-z0-9._:-]{3,120}$")
REASON_RE = re.compile(r"^[A-Z0-9_:-]{3,80}$")
DEFAULT_TTL_MINUTES = 30


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _handoff_fingerprint(value: dict[str, Any]) -> str:
    unsigned = _clone(value)
    unsigned.pop("handoff_fingerprint_sha256", None)
    return _digest(unsigned)


def _guards() -> dict[str, Any]:
    return {
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "durable_observation_rechecked_before_reread_eligibility": True,
        "single_use_handoff": True,
        "sealed_authorization_required": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _summary(job: dict[str, Any], status: str, blocks: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": HANDOFF_ID,
        "status": status,
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "hard_blocks": sorted(set(blocks or [])),
        "publication_blocked": False,
        "provider_network_call_performed": False,
        "durable_paths": [],
        "guards": _guards(),
    }
    result.update(extra)
    return result


def _handoff_blocks(
    handoff: dict[str, Any],
    entry: dict[str, Any],
    authorization_fingerprint: str,
    *,
    now: str | None = None,
    required_status: str | None = None,
) -> list[str]:
    blocks: list[str] = []
    if _clean(handoff.get("schema_version")) != SCHEMA_VERSION:
        blocks.append("REREAD_HANDOFF_SCHEMA_VERSION")
    if _clean(handoff.get("handoff_id")) != HANDOFF_ID:
        blocks.append("REREAD_HANDOFF_ID")
    if required_status and _clean(handoff.get("status")).upper() != required_status:
        blocks.append("REREAD_HANDOFF_STATUS_INVALID")
    if _clean(handoff.get("checkpoint_key")) != _clean(entry.get("checkpoint_key")):
        blocks.append("REREAD_HANDOFF_CHECKPOINT_MISMATCH")
    if _clean(handoff.get("job_fingerprint_sha256")) != _clean(entry.get("job_fingerprint_sha256")):
        blocks.append("REREAD_HANDOFF_JOB_FINGERPRINT_MISMATCH")
    if _clean(handoff.get("authorization_fingerprint")) != authorization_fingerprint:
        blocks.append("REREAD_HANDOFF_AUTHORIZATION_CONTEXT_CHANGED")
    if _clean(entry.get("authorization_fingerprint")) != authorization_fingerprint:
        blocks.append("REREAD_HANDOFF_ENTRY_AUTHORIZATION_CONTEXT_CHANGED")
    if not DECISION_RE.fullmatch(_clean(handoff.get("decision_id"))):
        blocks.append("REREAD_HANDOFF_DECISION_ID_INVALID")
    if not REASON_RE.fullmatch(_clean(handoff.get("reason_code"))):
        blocks.append("REREAD_HANDOFF_REASON_CODE_INVALID")
    origin_fp = _clean(handoff.get("origin_receipt_fingerprint_sha256"))
    if not FP_RE.fullmatch(origin_fp):
        blocks.append("REREAD_HANDOFF_ORIGIN_RECEIPT_FINGERPRINT_INVALID")
    receipts = entry.get("execution_receipts") if isinstance(entry.get("execution_receipts"), list) else []
    origin_matches = [row for row in receipts if isinstance(row, dict) and _clean(row.get("receipt_fingerprint_sha256")) == origin_fp]
    status = _clean(handoff.get("status")).upper()
    if status == "AUTHORIZED" and not origin_matches:
        blocks.append("REREAD_HANDOFF_ORIGIN_RECEIPT_CHANGED")
    if status == "CONSUMED":
        evidence_matches = []
        handoff_fp = _clean(handoff.get("handoff_fingerprint_sha256"))
        for row in receipts:
            if not isinstance(row, dict):
                continue
            evidence = row.get("recovery_evidence") if isinstance(row.get("recovery_evidence"), dict) else {}
            if _clean(evidence.get("reread_handoff_fingerprint_sha256")) == handoff_fp:
                evidence_matches.append(row)
        if not evidence_matches:
            blocks.append("REREAD_HANDOFF_CONSUMPTION_RECEIPT_MISSING")
    supplied = _clean(handoff.get("handoff_fingerprint_sha256"))
    if not FP_RE.fullmatch(supplied) or not hmac.compare_digest(supplied, _handoff_fingerprint(handoff)):
        blocks.append("REREAD_HANDOFF_FINGERPRINT_MISMATCH")
    if runtime._entry_has_forbidden_fields(handoff):
        blocks.append("REREAD_HANDOFF_FORBIDDEN_FIELD")
    if handoff.get("publication_blocked") is not False:
        blocks.append("REREAD_HANDOFF_PUBLICATION_BLOCKED")
    if handoff.get("zero_paid_dependency") is not True:
        blocks.append("REREAD_HANDOFF_ZERO_PAID_DEPENDENCY")
    try:
        issued = runtime._dt(_clean(handoff.get("issued_at")))
        expires = runtime._dt(_clean(handoff.get("expires_at")))
        if expires <= issued:
            blocks.append("REREAD_HANDOFF_EXPIRY_INVALID")
        if now is not None and runtime._dt(now) > expires:
            blocks.append("REREAD_HANDOFF_EXPIRED")
    except ValueError:
        blocks.append("REREAD_HANDOFF_TIME_INVALID")
    return sorted(set(blocks))


def _recovery_entry(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None, list[str]]:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return state, None, None, list(blocks)
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return state, None, previous_fp, ["REREAD_HANDOFF_ENTRY_MISSING"]
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return state, entry, previous_fp, ["REREAD_HANDOFF_JOB_FINGERPRINT_CONFLICT"]
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return state, entry, previous_fp, list(checked.get("hard_blocks", []))
    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, previous_fp, ["REREAD_HANDOFF_RECOVERY_REQUIRED_EXPECTED"]
    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return state, entry, previous_fp, ["REREAD_HANDOFF_RECOVERY_RECEIPT_REQUIRED"]
    if not _clean(latest.get("network_started_at")):
        return state, entry, previous_fp, ["REREAD_HANDOFF_NETWORK_START_PROOF_REQUIRED"]
    return state, entry, previous_fp, []


def issue_provider_reread_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    decision_id: str,
    reason_code: str,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> dict[str, Any]:
    """Persist explicit reread authorization while leaving recovery unresolved."""
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _summary(job, "HOLD_REREAD_HANDOFF_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    if not DECISION_RE.fullmatch(_clean(decision_id)):
        return _summary(job, "HOLD_REREAD_HANDOFF_DECISION", ["REREAD_HANDOFF_DECISION_ID_INVALID"])
    if not REASON_RE.fullmatch(_clean(reason_code)):
        return _summary(job, "HOLD_REREAD_HANDOFF_DECISION", ["REREAD_HANDOFF_REASON_CODE_INVALID"])
    if ttl_minutes <= 0 or ttl_minutes > 180:
        return _summary(job, "HOLD_REREAD_HANDOFF_TTL", ["REREAD_HANDOFF_TTL_INVALID"])
    try:
        now_dt = runtime._dt(now)
    except ValueError:
        return _summary(job, "HOLD_REREAD_HANDOFF_TIME", ["REREAD_HANDOFF_NOW_INVALID"])
    if channel.get("zero_paid_dependency") is not True:
        return _summary(job, "HOLD_REREAD_HANDOFF_POLICY", ["ZERO_PAID_DEPENDENCY_VIOLATION"])
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    if metrics.get("observed_only") is not True:
        return _summary(job, "HOLD_REREAD_HANDOFF_POLICY", ["REREAD_HANDOFF_OBSERVED_ONLY_REQUIRED"])

    reconciled = recovery.reconcile_recovery(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        authorize_provider_reread=False,
    )
    if reconciled.get("status") == "RECOVERED_COMPLETED":
        return _summary(job, "NO_REREAD_DURABLE_OBSERVATION_RECOVERED", [], checkpoint_status="COMPLETED")
    if reconciled.get("status") != "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION":
        return _summary(job, "HOLD_REREAD_HANDOFF_RECONCILIATION", list(reconciled.get("hard_blocks", [])) or [str(reconciled.get("status"))])

    state, entry, previous_fp, blocks = _recovery_entry(repo_root, channel, job, authorization_fingerprint)
    if blocks or entry is None:
        return _summary(job, "HOLD_REREAD_HANDOFF_STATE", blocks)
    existing = entry.get("provider_reread_handoff") if isinstance(entry.get("provider_reread_handoff"), dict) else None
    if existing:
        existing_blocks = _handoff_blocks(existing, entry, authorization_fingerprint, now=now)
        if not existing_blocks and _clean(existing.get("status")).upper() == "AUTHORIZED":
            if _clean(existing.get("decision_id")) == _clean(decision_id) and _clean(existing.get("reason_code")) == _clean(reason_code):
                return _summary(
                    job,
                    "REREAD_HANDOFF_READY",
                    [],
                    checkpoint_status="RECOVERY_REQUIRED",
                    handoff=_clone(existing),
                    durable_paths=[runtime.expected_checkpoint_state_path(channel)],
                )
            return _summary(job, "HOLD_REREAD_HANDOFF_ALREADY_AUTHORIZED", ["REREAD_HANDOFF_DECISION_CONFLICT"])
        if existing_blocks and "REREAD_HANDOFF_EXPIRED" not in existing_blocks:
            return _summary(job, "HOLD_REREAD_HANDOFF_TAMPERED", existing_blocks)

    latest = receipt._latest_receipt(entry) or {}
    handoff = {
        "schema_version": SCHEMA_VERSION,
        "handoff_id": HANDOFF_ID,
        "status": "AUTHORIZED",
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "authorization_fingerprint": authorization_fingerprint,
        "origin_receipt_fingerprint_sha256": _clean(latest.get("receipt_fingerprint_sha256")),
        "decision_id": _clean(decision_id),
        "reason_code": _clean(reason_code),
        "issued_at": runtime._iso(now_dt),
        "expires_at": runtime._iso(now_dt + timedelta(minutes=ttl_minutes)),
        "consumed_at": None,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    handoff["handoff_fingerprint_sha256"] = _handoff_fingerprint(handoff)
    entry["provider_reread_handoff"] = handoff
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root,
        channel,
        state,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return _summary(job, _clean(persisted.get("status")) or "HOLD_REREAD_HANDOFF_PERSISTENCE", list(persisted.get("hard_blocks", [])))
    return _summary(
        job,
        "REREAD_HANDOFF_READY",
        [],
        checkpoint_status="RECOVERY_REQUIRED",
        handoff=_clone(handoff),
        durable_paths=[runtime.expected_checkpoint_state_path(channel)],
    )


def consume_provider_reread_handoff(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    """Consume exactly one valid handoff and make one future provider read eligible."""
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _summary(job, "HOLD_REREAD_HANDOFF_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    try:
        runtime._dt(now)
    except ValueError:
        return _summary(job, "HOLD_REREAD_HANDOFF_TIME", ["REREAD_HANDOFF_NOW_INVALID"])

    # The ledger is checked again immediately before eligibility is persisted.
    reconciled = recovery.reconcile_recovery(
        repo_root,
        channel,
        job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        authorize_provider_reread=False,
    )
    if reconciled.get("status") == "RECOVERED_COMPLETED":
        return _summary(job, "NO_REREAD_DURABLE_OBSERVATION_RECOVERED", [], checkpoint_status="COMPLETED")
    if reconciled.get("status") != "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION":
        return _summary(job, "HOLD_REREAD_HANDOFF_RECONCILIATION", list(reconciled.get("hard_blocks", [])) or [str(reconciled.get("status"))])

    state, entry, previous_fp, blocks = _recovery_entry(repo_root, channel, job, authorization_fingerprint)
    if blocks or entry is None:
        return _summary(job, "HOLD_REREAD_HANDOFF_STATE", blocks)
    handoff = entry.get("provider_reread_handoff") if isinstance(entry.get("provider_reread_handoff"), dict) else None
    if handoff is None:
        return _summary(job, "HOLD_REREAD_HANDOFF_REQUIRED", ["EXPLICIT_PROVIDER_REREAD_HANDOFF_REQUIRED"])
    handoff_blocks = _handoff_blocks(handoff, entry, authorization_fingerprint, now=now, required_status="AUTHORIZED")
    if handoff_blocks:
        return _summary(job, "HOLD_REREAD_HANDOFF_INVALID", handoff_blocks)

    origin_fp = _clean(handoff.get("origin_receipt_fingerprint_sha256"))
    handoff["status"] = "CONSUMED"
    handoff["consumed_at"] = runtime._iso(runtime._dt(now))
    handoff["handoff_fingerprint_sha256"] = _handoff_fingerprint(handoff)
    consumed_fp = _clean(handoff.get("handoff_fingerprint_sha256"))

    latest = receipt._latest_receipt(entry)
    if not latest:
        return _summary(job, "HOLD_REREAD_HANDOFF_STATE", ["REREAD_HANDOFF_RECOVERY_RECEIPT_REQUIRED"])
    evidence = {
        "kind": "EXPLICIT_PROVIDER_REREAD_HANDOFF_CONSUMED",
        "checked_at": runtime._iso(runtime._dt(now)),
        "origin_receipt_fingerprint_sha256": origin_fp,
        "reread_handoff_fingerprint_sha256": consumed_fp,
        "provider_reread_authorized": True,
        "provider_network_call_performed": False,
    }
    evidence["recovery_evidence_fingerprint_sha256"] = _digest(evidence)

    entry["provider_reread_handoff"] = handoff
    entry["status"] = "RETRY_WAIT"
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = runtime._iso(runtime._dt(now))
    entry["completed_at"] = None
    entry["last_result_status"] = "PROVIDER_REREAD_HANDOFF_CONSUMED"
    latest["status"] = "RETRY_WAIT"
    latest["checkpoint_status"] = "RETRY_WAIT"
    latest["provider_result_status"] = "PROVIDER_REREAD_HANDOFF_CONSUMED"
    latest["updated_at"] = runtime._iso(runtime._dt(now))
    latest["recovery_evidence"] = evidence
    latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root,
        channel,
        state,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return _summary(job, _clean(persisted.get("status")) or "HOLD_REREAD_HANDOFF_PERSISTENCE", list(persisted.get("hard_blocks", [])))
    return _summary(
        job,
        "REREAD_HANDOFF_CONSUMED",
        [],
        checkpoint_status="RETRY_WAIT",
        provider_reread_authorized=True,
        handoff=_clone(handoff),
        durable_paths=[runtime.expected_checkpoint_state_path(channel)],
    )


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("job", type=Path)
    parser.add_argument("--repo-root", type=Path, default=Path("."))
    parser.add_argument("--authorization-fingerprint", required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--decision-id", required=True)
    parser.add_argument("--reason-code", required=True)
    parser.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)
    parser.add_argument("--consume", action="store_true")
    args = parser.parse_args()
    channel = _load(args.channel)
    job = _load(args.job)
    if args.consume:
        result = consume_provider_reread_handoff(
            args.repo_root,
            channel,
            job,
            authorization_fingerprint=args.authorization_fingerprint,
            now=args.now,
        )
    else:
        result = issue_provider_reread_handoff(
            args.repo_root,
            channel,
            job,
            authorization_fingerprint=args.authorization_fingerprint,
            now=args.now,
            decision_id=args.decision_id,
            reason_code=args.reason_code,
            ttl_minutes=args.ttl_minutes,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if _clean(result.get("status")).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
