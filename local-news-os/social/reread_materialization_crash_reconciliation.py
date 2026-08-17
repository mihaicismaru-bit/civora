#!/usr/bin/env python3
"""Recover an explicit metrics re-read after durable materialization but before outcome.

This boundary closes the crash window where an explicitly authorized provider re-read
has already written the exact observed-metrics row (and feedback snapshot when
required), but the process dies before the terminal checkpoint/outcome is persisted.
Recovery is local-only: it validates the sealed authorization/re-read lineage, the
SPENT handoff record, and durable materialization read-back, then completes the
RECOVERY_REQUIRED checkpoint by CAS. Missing or ambiguous evidence remains
RECOVERY_REQUIRED and never authorizes another provider read.

No provider call, credential value, raw provider payload, or predictive analytics are
accepted or persisted. Editorial publication is never blocked and zero-paid dependency
is mandatory.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import observed_metrics_collector as collector
import reread_provider_outcome_binding as outcome
import reread_result_materialization_binding as materialization
import reread_spend_reauthorization as spend
import reread_spend_reclaim_binding as reclaim

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-materialization-crash-reconciliation-v1"
ACTION = "RECOVER_REREAD_FROM_DURABLE_MATERIALIZATION"
EVIDENCE_FIELD = "reread_materialization_crash_recovery"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def guards() -> dict[str, Any]:
    return {
        "recovery_requires_explicit_reread_lineage": True,
        "recovery_requires_spent_handoff": True,
        "recovery_requires_network_start_proof": True,
        "recovery_requires_exact_durable_materialization": True,
        "feedback_snapshot_readback_required_when_materialization_requires_it": True,
        "ambiguous_or_missing_evidence_remains_recovery_required": True,
        "completed_no_data_inferred_from_absence": False,
        "provider_reread_authorized_by_recovery": False,
        "provider_network_call_performed_by_recovery": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "predictive_analytics_used": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _result(job: dict[str, Any], status: str, blocks: list[str], **extra: Any) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "action": ACTION,
        "status": status,
        "checkpoint_key": runtime.checkpoint_key(job),
        "publication_id": _clean(job.get("publication_id")) or None,
        "hard_blocks": sorted(set(blocks)),
        "provider_reread_authorized": False,
        "provider_network_call_performed": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
        "durable_paths": [],
        "guards": guards(),
    }
    value.update(extra)
    return value


def is_explicit_reread_recovery(entry: dict[str, Any]) -> bool:
    latest = receipt._latest_receipt(entry) if isinstance(entry, dict) else None
    return bool(
        isinstance(latest, dict)
        and _clean(entry.get("status")).upper() == "RECOVERY_REQUIRED"
        and _clean(latest.get("status")).upper() == "RECOVERY_REQUIRED"
        and isinstance(latest.get(reclaim.PROVENANCE_FIELD), dict)
    )


def _identity_blocks(channel: dict[str, Any], job: dict[str, Any]) -> list[str]:
    blocks: list[str] = []
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    expected = {
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
    }
    actual = {
        "instance_id": _clean(publication.get("instance_id")),
        "channel_id": _clean(publication.get("channel_id")),
        "platform": _clean(publication.get("platform")).lower(),
    }
    for key in expected:
        if not expected[key] or actual[key] != expected[key]:
            blocks.append("REREAD_MATERIALIZATION_RECOVERY_" + key.upper() + "_MISMATCH")
    if _clean(job.get("publication_id")) != _clean(publication.get("publication_id")):
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_PUBLICATION_ID_MISMATCH")
    supplied = _clean(job.get("job_fingerprint_sha256"))
    unsigned = _clone(job)
    unsigned.pop("job_fingerprint_sha256", None)
    if not supplied or supplied != runtime._digest(unsigned):
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_JOB_FINGERPRINT_MISMATCH")
    metrics = channel.get("metrics") if isinstance(channel.get("metrics"), dict) else {}
    sources = metrics.get("sources") if isinstance(metrics.get("sources"), list) else []
    if _clean(job.get("source")) not in {_clean(value) for value in sources if _clean(value)}:
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_SOURCE_NOT_DECLARED")
    if metrics.get("observed_only") is not True:
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_OBSERVED_ONLY_REQUIRED")
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    return sorted(set(blocks))


def _lineage(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    entry: dict[str, Any],
    authorization_fingerprint: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    latest = receipt._latest_receipt(entry)
    if not isinstance(latest, dict):
        return None, None, ["REREAD_MATERIALIZATION_RECOVERY_RECEIPT_MISSING"]
    if not _clean(latest.get("network_started_at")):
        return None, None, ["REREAD_MATERIALIZATION_RECOVERY_NETWORK_START_PROOF_REQUIRED"]
    provenance = latest.get(reclaim.PROVENANCE_FIELD)
    if not isinstance(provenance, dict):
        return None, None, ["REREAD_MATERIALIZATION_RECOVERY_RECLAIM_PROVENANCE_REQUIRED"]

    source, evidence, source_blocks = outcome._find_release_source(
        entry, provenance, job, authorization_fingerprint
    )
    blocks = list(source_blocks)
    if isinstance(source, dict) and isinstance(evidence, dict):
        blocks.extend(
            reclaim._provenance_blocks(
                provenance,
                evidence=evidence,
                source_receipt=source,
                current_receipt=latest,
                job=job,
                authorization_fingerprint=authorization_fingerprint,
            )
        )

    store, spend_blocks, existed = spend.load_spend_store(repo_root, channel)
    blocks.extend(spend_blocks)
    handoff_id = _clean(provenance.get("handoff_id"))
    record = store.get("records", {}).get(handoff_id) if isinstance(store.get("records"), dict) else None
    if not existed or not isinstance(record, dict):
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_SPENT_RECORD_REQUIRED")
        return None, None, sorted(set(blocks))
    if _clean(record.get("status")).upper() != "SPENT":
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_HANDOFF_NOT_SPENT")
    pairs = {
        "handoff_id": handoff_id,
        "authorization_fingerprint": authorization_fingerprint,
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "execution_id": _clean(latest.get("execution_id")),
        "network_started_at": _clean(latest.get("network_started_at")),
    }
    for key, expected in pairs.items():
        if not expected or not hmac.compare_digest(_clean(record.get(key)), expected):
            blocks.append("REREAD_MATERIALIZATION_RECOVERY_SPEND_IDENTITY_MISMATCH:" + key)
    try:
        if int(record.get("attempt") or 0) != int(latest.get("attempt") or 0):
            blocks.append("REREAD_MATERIALIZATION_RECOVERY_SPEND_ATTEMPT_MISMATCH")
    except (TypeError, ValueError):
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_SPEND_ATTEMPT_MISMATCH")
    if record.get("provider_reads_spent") != 1:
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_SPEND_COUNT_INVALID")
    if not receipt.RECEIPT_FINGERPRINT_RE.fullmatch(_clean(record.get("network_receipt_fingerprint_sha256"))):
        blocks.append("REREAD_MATERIALIZATION_RECOVERY_NETWORK_RECEIPT_PROOF_INVALID")
    return (provenance if not blocks else None), (record if not blocks else None), sorted(set(blocks))


def _durable_candidate_now(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    network_started_at: str,
) -> tuple[str | None, list[str]]:
    try:
        relative = collector.expected_observation_store_path(channel)
        path = runtime._safe_target(repo_root, relative)
    except (TypeError, ValueError):
        return None, ["REREAD_MATERIALIZATION_RECOVERY_OBSERVATION_STORE_PATH_INVALID"]
    if not path.exists():
        return None, []
    try:
        store = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, ["REREAD_MATERIALIZATION_RECOVERY_OBSERVATION_STORE_UNREADABLE"]
    checked = collector.validate_observation_store(channel, store)
    if checked.get("valid") is not True:
        return None, ["REREAD_MATERIALIZATION_RECOVERY_LEDGER:" + str(code) for code in checked.get("hard_blocks", [])]

    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    wanted = {
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "story_id": _clean(publication.get("story_id")),
        "product_id": _clean(publication.get("product_id")),
        "source": _clean(job.get("source")),
        "window_start_at": materialization._norm_time(publication.get("published_at")),
    }
    try:
        network_dt = runtime._dt(network_started_at)
    except ValueError:
        return None, ["REREAD_MATERIALIZATION_RECOVERY_NETWORK_START_TIME_INVALID"]
    candidates: list[str] = []
    for row in store.get("observations", []):
        if not isinstance(row, dict):
            continue
        window = row.get("window") if isinstance(row.get("window"), dict) else {}
        actual = {
            "publication_id": _clean(row.get("publication_id")),
            "remote_publication_id": _clean(row.get("remote_publication_id")),
            "story_id": _clean(row.get("story_id")),
            "product_id": _clean(row.get("product_id")),
            "source": _clean(row.get("source")),
            "window_start_at": materialization._norm_time(window.get("start_at")),
        }
        if actual != wanted:
            continue
        observed_at = materialization._norm_time(row.get("observed_at"))
        window_end = materialization._norm_time(window.get("end_at"))
        if not observed_at or observed_at != window_end:
            continue
        try:
            if runtime._dt(observed_at) < network_dt:
                continue
        except ValueError:
            continue
        candidates.append(observed_at)
    candidates = sorted(set(candidates))
    if len(candidates) > 1:
        return None, ["REREAD_MATERIALIZATION_RECOVERY_DURABLE_OBSERVATION_AMBIGUOUS"]
    return (candidates[0] if candidates else None), []


def _recovery_evidence(
    proof: dict[str, Any], provenance: dict[str, Any], spend_record: dict[str, Any], latest: dict[str, Any], *, recovered_at: str,
) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "action": ACTION,
        "handoff_id": _clean(provenance.get("handoff_id")),
        "reclaim_provenance_fingerprint_sha256": _clean(provenance.get("provenance_fingerprint_sha256")),
        "spend_record_fingerprint_sha256": _clean(spend_record.get("record_fingerprint_sha256")),
        "network_execution_id": _clean(latest.get("execution_id")),
        "network_started_at": _clean(latest.get("network_started_at")),
        "materialization_fingerprint_sha256": _clean(proof.get("materialization_fingerprint_sha256")),
        "observation_id": _clean(proof.get("observation_id")),
        "observation_fingerprint_sha256": _clean(proof.get("observation_fingerprint_sha256")),
        "observation_store_fingerprint_sha256": _clean(proof.get("observation_store_fingerprint_sha256")),
        "snapshot_fingerprint_sha256": _clean(proof.get("snapshot_fingerprint_sha256")) or None,
        "feedback_fingerprint_sha256": _clean(proof.get("feedback_fingerprint_sha256")) or None,
        "recovered_at": runtime._iso(runtime._dt(recovered_at)),
        "provider_reread_authorized": False,
        "provider_network_call_performed_by_recovery": False,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    evidence["evidence_fingerprint_sha256"] = _digest(evidence)
    return evidence


def reconcile_materialized_reread_crash(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    authorization_fingerprint: str,
    now: str,
) -> dict[str, Any]:
    """Complete a RECOVERY_REQUIRED explicit re-read only from exact disk evidence."""
    if not isinstance(channel, dict) or not isinstance(job, dict):
        raise TypeError("channel and job must be mappings")
    if not receipt._valid_authorization_fingerprint(authorization_fingerprint):
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_AUTHORIZATION", ["AUTHORIZATION_FINGERPRINT_INVALID"])
    try:
        runtime._dt(now)
    except ValueError:
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_TIME", ["RECOVERY_NOW_INVALID"])
    identity_blocks = _identity_blocks(channel, job)
    if identity_blocks:
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_IDENTITY", identity_blocks)

    state, state_blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if state_blocks:
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_CHECKPOINT", state_blocks)
    previous_fp = _clean(state.get("state_fingerprint_sha256")) or None
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_CHECKPOINT", ["REREAD_MATERIALIZATION_RECOVERY_ENTRY_MISSING"])
    if _clean(entry.get("job_fingerprint_sha256")) != _clean(job.get("job_fingerprint_sha256")):
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_CHECKPOINT", ["REREAD_MATERIALIZATION_RECOVERY_JOB_FINGERPRINT_CONFLICT"])
    sealed = receipt.validate_sealed_entry(entry, authorization_fingerprint)
    if sealed.get("valid") is not True:
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_RECEIPT", list(sealed.get("hard_blocks", [])))
    if not is_explicit_reread_recovery(entry):
        status = _clean(entry.get("status")).upper()
        if status == "COMPLETED":
            return _result(job, "ALREADY_COMPLETED", [])
        return _result(job, "NOT_EXPLICIT_REREAD_RECOVERY", [])

    latest = receipt._latest_receipt(entry)
    assert isinstance(latest, dict)
    provenance, spend_record, lineage_blocks = _lineage(
        repo_root, channel, job, entry, authorization_fingerprint
    )
    if lineage_blocks or not isinstance(provenance, dict) or not isinstance(spend_record, dict):
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_LINEAGE", lineage_blocks or ["REREAD_MATERIALIZATION_RECOVERY_LINEAGE_REQUIRED"])

    durable_now, candidate_blocks = _durable_candidate_now(
        repo_root, channel, job, network_started_at=_clean(latest.get("network_started_at"))
    )
    if candidate_blocks:
        return _result(job, "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE", candidate_blocks)
    if not durable_now:
        return _result(job, "RECOVERY_REQUIRED_NO_DURABLE_MATERIALIZATION", [])

    built = materialization.build_durable_materialization_proof(
        repo_root, channel, job, now=durable_now
    )
    if built.get("valid") is not True or not isinstance(built.get("proof"), dict):
        return _result(
            job,
            "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE",
            list(built.get("hard_blocks", [])) or ["REREAD_MATERIALIZATION_RECOVERY_PROOF_INVALID"],
        )
    proof = built["proof"]
    evidence = _recovery_evidence(
        proof, provenance, spend_record, latest, recovered_at=now
    )

    entry["status"] = "COMPLETED"
    entry["lease_expires_at"] = None
    entry["retry_after_at"] = None
    entry["completed_at"] = runtime._iso(runtime._dt(now))
    entry["last_result_status"] = "RECOVERED_FROM_DURABLE_MATERIALIZATION"
    latest["status"] = "COMPLETED"
    latest["checkpoint_status"] = "COMPLETED"
    latest["provider_result_status"] = "RECOVERED_FROM_DURABLE_MATERIALIZATION"
    latest["materialization_fingerprint_sha256"] = _clean(proof.get("materialization_fingerprint_sha256"))
    latest["updated_at"] = runtime._iso(runtime._dt(now))
    latest[EVIDENCE_FIELD] = _clone(evidence)
    latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    persisted = runtime.persist_checkpoint_state_cas(
        repo_root,
        channel,
        state,
        expected_previous_fingerprint_sha256=previous_fp,
    )
    if persisted.get("persisted") is not True:
        return _result(
            job,
            _clean(persisted.get("status")) or "HOLD_REREAD_MATERIALIZATION_RECOVERY_PERSISTENCE",
            list(persisted.get("hard_blocks", [])),
        )
    durable_paths = [runtime.expected_checkpoint_state_path(channel), _clean(proof.get("observation_store_path"))]
    if proof.get("snapshot_present") is True:
        durable_paths.append(_clean(proof.get("snapshot_path")))
    durable_paths.append(spend.expected_spend_store_path(channel))
    return _result(
        job,
        "RECOVERED_COMPLETED_FROM_DURABLE_MATERIALIZATION",
        [],
        checkpoint_status="COMPLETED",
        recovery_evidence=evidence,
        durable_materialization_fingerprint_sha256=_clean(proof.get("materialization_fingerprint_sha256")),
        durable_paths=sorted({value for value in durable_paths if value}),
    )
