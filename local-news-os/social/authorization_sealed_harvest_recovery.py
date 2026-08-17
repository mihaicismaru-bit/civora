#!/usr/bin/env python3
"""Fail-closed reconciliation for authorization-sealed metrics harvest recovery.

This boundary resolves an existing RECOVERY_REQUIRED checkpoint without making a
provider request. It first proves that the checkpoint, execution receipt,
authorization fingerprint and durable observation ledger still describe the same
publication/channel. If a durable cumulative observation already covers the
checkpoint, the checkpoint is completed from that evidence. Otherwise the default
is to remain in RECOVERY_REQUIRED. A later provider read can only be made eligible
through the durable, explicit, single-use provider re-read handoff boundary; the
legacy direct authorization flag is retained only as a fail-closed compatibility
surface and can no longer transition the checkpoint to RETRY_WAIT.

No credential value or provider payload is accepted or persisted here. Analytics
remains advisory-only and never blocks editorial publication.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
from pathlib import Path, PurePosixPath
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime

collector = runtime.observed_metrics_collector

SCHEMA_VERSION = "1.0"
RECOVERY_ID = "local-news-os-authorization-sealed-harvest-recovery"


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
        "observation_ledger_checked_before_provider_reread": True,
        "explicit_reread_handoff_required": True,
        "blind_retry_after_ambiguous_network_call": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _hold(job: dict[str, Any], status: str, blocks: list[str], *, entry: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "recovery_id": RECOVERY_ID,
        "status": status,
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "hard_blocks": sorted(set(blocks)),
        "checkpoint_status": _clean((entry or {}).get("status")) or None,
        "provider_reread_authorized": False,
        "publication_blocked": False,
        "durable_paths": [],
        "guards": _guards(),
    }


def _job_blocks(channel: dict[str, Any], job: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    if _clean(publication.get("instance_id")) != _clean(channel.get("instance_id")):
        blocks.append("RECOVERY_JOB_INSTANCE_MISMATCH")
    if _clean(publication.get("channel_id")) != _clean(channel.get("channel_id")):
        blocks.append("RECOVERY_JOB_CHANNEL_MISMATCH")
    if _clean(publication.get("platform")).lower() != _clean(channel.get("platform")).lower():
        blocks.append("RECOVERY_JOB_PLATFORM_MISMATCH")
    if _clean(job.get("publication_id")) != _clean(publication.get("publication_id")):
        blocks.append("RECOVERY_JOB_PUBLICATION_ID_MISMATCH")
    supplied = _clean(job.get("job_fingerprint_sha256"))
    unsigned = _clone(job)
    unsigned.pop("job_fingerprint_sha256", None)
    if not supplied or supplied != runtime._digest(unsigned):
        blocks.append("RECOVERY_JOB_FINGERPRINT_MISMATCH")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    sources = metrics.get("sources") if isinstance(metrics.get("sources"), list) else []
    if _clean(job.get("source")) not in {_clean(value) for value in sources}:
        blocks.append("RECOVERY_METRIC_SOURCE_NOT_DECLARED")
    if metrics.get("observed_only") is not True:
        blocks.append("RECOVERY_OBSERVED_ONLY_REQUIRED")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    try:
        runtime._dt(_clean(checkpoint.get("checkpoint_at")))
    except ValueError:
        blocks.append("RECOVERY_CHECKPOINT_AT_INVALID")
    if not _clean(publication.get("published_at")):
        blocks.append("RECOVERY_PUBLICATION_TIME_REQUIRED")
    else:
        try:
            runtime._dt(_clean(publication.get("published_at")))
        except ValueError:
            blocks.append("RECOVERY_PUBLICATION_TIME_INVALID")
    return sorted(set(blocks))


def _safe_store_path(channel: dict[str, Any]) -> str:
    relative = collector.expected_observation_store_path(channel)
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe observation store path")
    return path.as_posix()


def _load_store(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
    try:
        relative = _safe_store_path(channel)
    except (TypeError, ValueError):
        return None, ["RECOVERY_OBSERVATION_STORE_PATH_INVALID"], ""
    target = repo_root.joinpath(*PurePosixPath(relative).parts)
    if not target.exists():
        return None, [], relative
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, ["RECOVERY_OBSERVATION_STORE_UNREADABLE"], relative
    if not isinstance(value, dict):
        return None, ["RECOVERY_OBSERVATION_STORE_NOT_OBJECT"], relative
    checked = collector.validate_observation_store(channel, value)
    if checked.get("valid") is not True:
        return None, ["RECOVERY_OBSERVATION_STORE:" + str(code) for code in checked.get("hard_blocks", [])], relative
    return value, [], relative


def _observation_time(value: Any) -> Any:
    try:
        return runtime._dt(_clean(value))
    except ValueError:
        return None


def _covering_observation(
    job: dict[str, Any], entry: dict[str, Any], store: dict[str, Any] | None
) -> tuple[dict[str, Any] | None, list[str], str | None]:
    if store is None:
        return None, [], None
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    latest_receipt = receipt._latest_receipt(entry)
    if not latest_receipt:
        return None, ["RECOVERY_RECEIPT_MISSING"], None
    network_started = _clean(latest_receipt.get("network_started_at"))
    if not network_started:
        return None, ["RECOVERY_NETWORK_START_PROOF_REQUIRED"], None
    checkpoint = job.get("checkpoint") if isinstance(job.get("checkpoint"), dict) else {}
    checkpoint_at = _observation_time(checkpoint.get("checkpoint_at"))
    published_at = _observation_time(publication.get("published_at"))
    network_at = _observation_time(network_started)
    if checkpoint_at is None or published_at is None or network_at is None:
        return None, ["RECOVERY_TIME_EVIDENCE_INVALID"], None

    publication_id = _clean(job.get("publication_id"))
    remote_id = _clean(publication.get("remote_publication_id"))
    source = _clean(job.get("source"))
    exact: list[dict[str, Any]] = []
    covering: list[dict[str, Any]] = []
    conflicts: list[str] = []

    for observation in store.get("observations", []):
        if not isinstance(observation, dict):
            continue
        if _clean(observation.get("publication_id")) != publication_id or _clean(observation.get("source")) != source:
            continue
        if _clean(observation.get("remote_publication_id")) != remote_id:
            conflicts.append("RECOVERY_OBSERVATION_REMOTE_PROOF_CONFLICT")
            continue
        window = observation.get("window") if isinstance(observation.get("window"), dict) else {}
        start_at = _observation_time(window.get("start_at"))
        end_at = _observation_time(window.get("end_at"))
        observed_at = _observation_time(observation.get("observed_at"))
        if start_at is None or end_at is None or observed_at is None:
            conflicts.append("RECOVERY_OBSERVATION_TIME_INVALID")
            continue
        if start_at != published_at:
            conflicts.append("RECOVERY_OBSERVATION_WINDOW_ORIGIN_CONFLICT")
            continue
        if observed_at == network_at and end_at == network_at:
            exact.append(observation)
        if observed_at >= checkpoint_at and end_at >= checkpoint_at:
            covering.append(observation)

    if conflicts:
        return None, sorted(set(conflicts)), None
    if len(exact) > 1:
        return None, ["RECOVERY_EXACT_OBSERVATION_CARDINALITY_CONFLICT"], None
    if exact:
        return _clone(exact[0]), [], "EXACT_ATTEMPT_OBSERVATION"
    if covering:
        covering.sort(key=lambda row: (_clean(row.get("observed_at")), _clean(row.get("observation_id"))))
        return _clone(covering[0]), [], "CUMULATIVE_COVERAGE_OBSERVATION"
    return None, [], None


def _recovery_evidence(
    *, kind: str, store: dict[str, Any] | None, observation: dict[str, Any] | None,
    checked_at: str, provider_reread_authorized: bool,
) -> dict[str, Any]:
    evidence = {
        "kind": kind,
        "checked_at": checked_at,
        "observation_id": _clean((observation or {}).get("observation_id")) or None,
        "observation_fingerprint_sha256": _digest(observation) if observation is not None else None,
        "observation_store_fingerprint_sha256": _clean((store or {}).get("store_fingerprint_sha256")) or None,
        "provider_reread_authorized": provider_reread_authorized,
        "provider_network_call_performed": False,
    }
    evidence["recovery_evidence_fingerprint_sha256"] = _digest(evidence)
    return evidence


def _persist_reconciled_state(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    state: dict[str, Any],
    previous_fp: str | None,
    *,
    authorization_fingerprint: str,
    now: str,
    target_status: str,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    key = runtime.checkpoint_key(job)
    entry = state.get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return {"persisted": False, "status": "HOLD_RECOVERY_STATE", "hard_blocks": ["RECOVERY_ENTRY_MISSING"]}
    checked = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if checked.get("valid") is not True:
        return {"persisted": False, "status": "HOLD_RECOVERY_RECEIPT", "hard_blocks": checked.get("hard_blocks", [])}
    latest = receipt._latest_receipt(entry)
    if not latest:
        return {"persisted": False, "status": "HOLD_RECOVERY_RECEIPT", "hard_blocks": ["RECOVERY_RECEIPT_MISSING"]}
    if _clean(entry.get("status")).upper() != "RECOVERY_REQUIRED" or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return {"persisted": False, "status": "HOLD_RECOVERY_STATE", "hard_blocks": ["RECOVERY_REQUIRED_STATE_EXPECTED"]}

    entry["status"] = target_status
    entry["lease_expires_at"] = None
    entry["completed_at"] = runtime._iso(runtime._dt(now)) if target_status == "COMPLETED" else None
    entry["retry_after_at"] = runtime._iso(runtime._dt(now)) if target_status == "RETRY_WAIT" else None
    entry["last_result_status"] = (
        "RECOVERED_FROM_DURABLE_OBSERVATION" if target_status == "COMPLETED"
        else "RECOVERY_RECONCILED_NO_DURABLE_OBSERVATION"
    )
    latest["status"] = target_status
    latest["checkpoint_status"] = target_status
    latest["provider_result_status"] = entry["last_result_status"]
    latest["updated_at"] = runtime._iso(runtime._dt(now))
    latest["recovery_evidence"] = _clone(evidence)
    latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    return runtime.persist_checkpoint_state_cas(
        repo_root,
        channel,
        state,
        expected_previous_fingerprint_sha256=previous_fp,
    )


def reconcile_recovery(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
    authorize_provider_reread: bool = False,
) -> dict[str, Any]:
    """Reconcile one sealed RECOVERY_REQUIRED checkpoint without provider I/O."""
    if not isinstance(channel, dict) or not isinstance(job, dict):
        raise TypeError("channel and job must be mappings")
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _hold(job, "HOLD_RECOVERY_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    try:
        runtime._dt(now)
    except ValueError:
        return _hold(job, "HOLD_RECOVERY_TIME", ["RECOVERY_NOW_INVALID"])
    job_blocks = _job_blocks(channel, job)
    if job_blocks:
        return _hold(job, "HOLD_RECOVERY_JOB", job_blocks)

    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return _hold(job, "HOLD_RECOVERY_CHECKPOINT_STATE", state_blocks)
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return _hold(job, "HOLD_RECOVERY_CHECKPOINT_STATE", ["RECOVERY_ENTRY_MISSING"])
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return _hold(job, "HOLD_RECOVERY_CHECKPOINT_STATE", ["RECOVERY_JOB_FINGERPRINT_CONFLICT"], entry=entry)
    sealed = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if sealed.get("valid") is not True:
        changed = {"SEALED_ENTRY_AUTHORIZATION_CONTEXT_CHANGED", "SEALED_RECEIPT_AUTHORIZATION_CONTEXT_CHANGED"}
        status = "HOLD_RECOVERY_AUTHORIZATION_CHANGED" if changed.intersection(sealed.get("hard_blocks", [])) else "HOLD_RECOVERY_RECEIPT_TAMPERED"
        return _hold(job, status, list(sealed.get("hard_blocks", [])), entry=entry)

    current_status = _clean(entry.get("status")).upper()
    if current_status in {"COMPLETED", "COMPLETED_NO_DATA", "HOLD_ANALYTICS"}:
        result = _hold(job, "ALREADY_" + current_status, [], entry=entry)
        result["hard_blocks"] = []
        return result
    if current_status != "RECOVERY_REQUIRED":
        return _hold(job, "HOLD_RECOVERY_NOT_REQUIRED", ["RECOVERY_REQUIRED_STATE_EXPECTED"], entry=entry)

    latest = receipt._latest_receipt(entry)
    if not latest or _clean(latest.get("status")).upper() != "RECOVERY_REQUIRED":
        return _hold(job, "HOLD_RECOVERY_RECEIPT_TAMPERED", ["RECOVERY_REQUIRED_RECEIPT_EXPECTED"], entry=entry)
    if not hmac.compare_digest(_clean(latest.get("authorization_fingerprint")), authorization_fingerprint):
        return _hold(job, "HOLD_RECOVERY_AUTHORIZATION_CHANGED", ["RECOVERY_AUTHORIZATION_CONTEXT_CHANGED"], entry=entry)
    if not _clean(latest.get("network_started_at")):
        return _hold(job, "HOLD_RECOVERY_RECEIPT_TAMPERED", ["RECOVERY_NETWORK_START_PROOF_REQUIRED"], entry=entry)

    store, store_blocks, store_path = _load_store(repo_root, channel)
    if store_blocks:
        return _hold(job, "HOLD_RECOVERY_OBSERVATION_LEDGER", store_blocks, entry=entry)
    observation, evidence_blocks, evidence_kind = _covering_observation(job, entry, store)
    if evidence_blocks:
        return _hold(job, "HOLD_RECOVERY_OBSERVATION_CONFLICT", evidence_blocks, entry=entry)

    if observation is not None:
        evidence = _recovery_evidence(
            kind=evidence_kind or "DURABLE_COVERAGE_OBSERVATION",
            store=store,
            observation=observation,
            checked_at=runtime._iso(runtime._dt(now)),
            provider_reread_authorized=False,
        )
        persisted = _persist_reconciled_state(
            repo_root, channel, job, state, previous_fp,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            target_status="COMPLETED",
            evidence=evidence,
        )
        if persisted.get("persisted") is not True:
            return _hold(job, persisted.get("status") or "HOLD_RECOVERY_PERSISTENCE", list(persisted.get("hard_blocks", [])), entry=entry)
        return {
            "schema_version": SCHEMA_VERSION,
            "recovery_id": RECOVERY_ID,
            "status": "RECOVERED_COMPLETED",
            "checkpoint_key": runtime.checkpoint_key(job),
            "publication_id": _clean(job.get("publication_id")) or None,
            "checkpoint_status": "COMPLETED",
            "recovery_evidence": evidence,
            "provider_reread_authorized": False,
            "publication_blocked": False,
            "durable_paths": sorted(set([runtime.expected_checkpoint_state_path(channel), store_path] if store_path else [runtime.expected_checkpoint_state_path(channel)])),
            "hard_blocks": [],
            "guards": _guards(),
        }

    no_observation_evidence = _recovery_evidence(
        kind="NO_DURABLE_COVERAGE_OBSERVATION",
        store=store,
        observation=None,
        checked_at=runtime._iso(runtime._dt(now)),
        provider_reread_authorized=False,
    )
    if authorize_provider_reread:
        result = _hold(
            job,
            "HOLD_EXPLICIT_REREAD_HANDOFF_REQUIRED",
            ["EXPLICIT_PROVIDER_REREAD_HANDOFF_REQUIRED"],
            entry=entry,
        )
        result["recovery_evidence"] = no_observation_evidence
        return result

    result = _hold(job, "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION", [], entry=entry)
    result["hard_blocks"] = []
    result["recovery_evidence"] = no_observation_evidence
    return result


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
    parser.add_argument(
        "--authorize-provider-reread",
        action="store_true",
        help="Deprecated fail-closed flag; durable explicit re-read handoff is required.",
    )
    args = parser.parse_args()
    result = reconcile_recovery(
        args.repo_root,
        _load(args.channel),
        _load(args.job),
        authorization_fingerprint=args.authorization_fingerprint,
        now=args.now,
        authorize_provider_reread=args.authorize_provider_reread,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 2 if _clean(result.get("status")).startswith("HOLD_") else 0


if __name__ == "__main__":
    raise SystemExit(main())
