#!/usr/bin/env python3
"""Bind explicit provider re-read completion to durable observed-metrics materialization.

The provider-outcome layer already proves that an explicit single-use re-read reached
NETWORK_CALL_STARTED under the exact authorization lineage. This layer closes the next
persistence gap: a COMPLETED re-read may not trust an arbitrary caller-supplied
materialization hash. Before the terminal checkpoint transition, it reads back the
channel-local observed-metrics ledger and feedback snapshot, validates their seals and
identity, and derives a new SHA-256 materialization fingerprint from that durable
read-back proof.

No provider call or credential read is performed here. Analytics remains advisory-only
and zero-paid dependency is mandatory. Normal non-reread and non-COMPLETED transitions
are delegated unchanged.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import authorization_sealed_harvest_receipt as receipt
import durable_feedback_snapshot
import metrics_harvest_runtime as runtime
import observed_metrics_collector
import reread_provider_outcome_binding as outcome
import reread_spend_reclaim_binding as reclaim

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-reread-result-materialization-binding-v1"
PATCH_ID = RUNTIME_ID + ":installed"
ACTION = "BIND_DURABLE_REREAD_RESULT_MATERIALIZATION"

outcome.install()
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


def _norm_time(value: Any) -> str:
    try:
        return runtime._iso(runtime._dt(_clean(value)))
    except (TypeError, ValueError):
        return ""


def materialization_guards() -> dict[str, Any]:
    return {
        "completed_reread_requires_exact_durable_observation": True,
        "observation_store_readback_validated": True,
        "feedback_snapshot_readback_validated_when_present": True,
        "feedback_snapshot_required_when_durable_store_yields_usable_feedback": True,
        "snapshot_sources_must_exist_in_observation_store": True,
        "persisted_materialization_fingerprint_derived_from_readback": True,
        "caller_bundle_fingerprint_not_trusted_as_persistence_proof": True,
        "normal_non_reread_transition_unchanged": True,
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def _load_object(path: Path, code: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not path.exists():
        return None, [code + "_MISSING"]
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None, [code + "_UNREADABLE"]
    if not isinstance(value, dict):
        return None, [code + "_NOT_OBJECT"]
    return value, []


def _exact_observation(store: dict[str, Any], job: dict[str, Any], now: str) -> tuple[dict[str, Any] | None, list[str]]:
    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    wanted = {
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "story_id": _clean(publication.get("story_id")),
        "product_id": _clean(publication.get("product_id")),
        "source": _clean(job.get("source")),
        "observed_at": _norm_time(now),
        "window_start_at": _norm_time(publication.get("published_at")),
        "window_end_at": _norm_time(now),
    }
    if any(not value for value in wanted.values()):
        return None, ["REREAD_RESULT_OBSERVATION_IDENTITY_INCOMPLETE"]
    matches: list[dict[str, Any]] = []
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
            "observed_at": _norm_time(row.get("observed_at")),
            "window_start_at": _norm_time(window.get("start_at")),
            "window_end_at": _norm_time(window.get("end_at")),
        }
        if actual == wanted:
            matches.append(row)
    if len(matches) != 1:
        return None, ["REREAD_RESULT_EXACT_DURABLE_OBSERVATION_CARDINALITY"]
    return matches[0], []


def _snapshot_context(
    repo_root: Path,
    channel: dict[str, Any],
    store: dict[str, Any],
    observation: dict[str, Any],
    *,
    now: str,
) -> tuple[dict[str, Any], list[str]]:
    blocks: list[str] = []
    snapshot_rel = durable_feedback_snapshot.expected_snapshot_path(channel)
    snapshot_path = runtime._safe_target(repo_root, snapshot_rel)

    # Whether a feedback file should exist is derived from the durable ledger itself,
    # not from the caller's in-memory bundle. min_samples changes hint generation only;
    # feedback usability is driven by the presence of an observed action-rate sample.
    try:
        candidate = durable_feedback_snapshot.build_snapshot(
            channel,
            list(store.get("observations", [])),
            now=_norm_time(now),
            ttl_hours=durable_feedback_snapshot.DEFAULT_TTL_HOURS,
            min_samples=2,
        )
        snapshot_required = candidate.get("usable") is True
    except (TypeError, ValueError):
        snapshot_required = False
        blocks.append("REREAD_RESULT_FEEDBACK_REBUILD_INVALID")

    if not snapshot_path.exists():
        if snapshot_required:
            blocks.append("REREAD_RESULT_FEEDBACK_SNAPSHOT_MISSING")
        return {
            "snapshot_path": snapshot_rel,
            "snapshot_present": False,
            "snapshot_required": snapshot_required,
            "snapshot_fingerprint_sha256": None,
            "feedback_fingerprint_sha256": None,
            "snapshot_source_observation_count": 0,
        }, blocks

    snapshot, read_blocks = _load_object(snapshot_path, "REREAD_RESULT_FEEDBACK_SNAPSHOT")
    blocks.extend(read_blocks)
    if not isinstance(snapshot, dict):
        return {
            "snapshot_path": snapshot_rel,
            "snapshot_present": True,
            "snapshot_required": snapshot_required,
            "snapshot_fingerprint_sha256": None,
            "feedback_fingerprint_sha256": None,
            "snapshot_source_observation_count": 0,
        }, blocks

    checked = durable_feedback_snapshot.validate_snapshot(channel, snapshot, now=_norm_time(now))
    if checked.get("valid") is not True:
        blocks.extend("REREAD_RESULT_FEEDBACK:" + str(code) for code in checked.get("hard_blocks", []))

    store_ids = {
        _clean(row.get("observation_id"))
        for row in store.get("observations", [])
        if isinstance(row, dict) and _clean(row.get("observation_id"))
    }
    snapshot_ids = {
        _clean(value)
        for value in snapshot.get("source_observation_ids", [])
        if _clean(value)
    }
    if not snapshot_ids.issubset(store_ids):
        blocks.append("REREAD_RESULT_SNAPSHOT_SOURCE_NOT_IN_DURABLE_LEDGER")
    exact_id = _clean(observation.get("observation_id"))
    if snapshot_required and exact_id not in snapshot_ids:
        blocks.append("REREAD_RESULT_EXACT_OBSERVATION_NOT_IN_FEEDBACK_SNAPSHOT")

    return {
        "snapshot_path": snapshot_rel,
        "snapshot_present": True,
        "snapshot_required": snapshot_required,
        "snapshot_fingerprint_sha256": _clean(snapshot.get("snapshot_fingerprint_sha256")) or None,
        "feedback_fingerprint_sha256": _clean(snapshot.get("feedback_fingerprint_sha256")) or None,
        "snapshot_source_observation_count": len(snapshot_ids),
    }, blocks


def build_durable_materialization_proof(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    now: str,
) -> dict[str, Any]:
    blocks: list[str] = []
    if channel.get("zero_paid_dependency") is not True:
        blocks.append("ZERO_PAID_DEPENDENCY_VIOLATION")
    try:
        store_rel = observed_metrics_collector.expected_observation_store_path(channel)
        store_path = runtime._safe_target(repo_root, store_rel)
    except (TypeError, ValueError):
        return {"valid": False, "hard_blocks": ["REREAD_RESULT_OBSERVATION_STORE_PATH_INVALID"], "proof": None}

    store, read_blocks = _load_object(store_path, "REREAD_RESULT_OBSERVATION_STORE")
    blocks.extend(read_blocks)
    if not isinstance(store, dict):
        return {"valid": False, "hard_blocks": sorted(set(blocks)), "proof": None}
    checked = observed_metrics_collector.validate_observation_store(channel, store)
    if checked.get("valid") is not True:
        blocks.extend("REREAD_RESULT_LEDGER:" + str(code) for code in checked.get("hard_blocks", []))
    observation, observation_blocks = _exact_observation(store, job, now)
    blocks.extend(observation_blocks)
    if not isinstance(observation, dict):
        return {"valid": False, "hard_blocks": sorted(set(blocks)), "proof": None}

    snapshot_context, snapshot_blocks = _snapshot_context(
        repo_root, channel, store, observation, now=now
    )
    blocks.extend(snapshot_blocks)
    if blocks:
        return {"valid": False, "hard_blocks": sorted(set(blocks)), "proof": None}

    publication = job.get("publication") if isinstance(job.get("publication"), dict) else {}
    proof: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "action": ACTION,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "checkpoint_key": runtime.checkpoint_key(job),
        "job_fingerprint_sha256": _clean(job.get("job_fingerprint_sha256")),
        "publication_id": _clean(job.get("publication_id")),
        "remote_publication_id": _clean(publication.get("remote_publication_id")),
        "story_id": _clean(publication.get("story_id")),
        "product_id": _clean(publication.get("product_id")),
        "source": _clean(job.get("source")),
        "observed_at": _norm_time(observation.get("observed_at")),
        "observation_id": _clean(observation.get("observation_id")),
        "observation_fingerprint_sha256": _digest(observation),
        "observation_store_path": store_rel,
        "observation_store_fingerprint_sha256": _clean(store.get("store_fingerprint_sha256")),
        **snapshot_context,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }
    proof["materialization_fingerprint_sha256"] = _digest(proof)
    return {"valid": True, "hard_blocks": [], "proof": proof}


def validate_durable_materialization_binding(
    repo_root: Path,
    channel: dict[str, Any],
    job: dict[str, Any],
    *,
    now: str,
    materialization_fingerprint_sha256: str,
) -> dict[str, Any]:
    built = build_durable_materialization_proof(repo_root, channel, job, now=now)
    if built.get("valid") is not True:
        return {
            "valid": False,
            "hard_blocks": list(built.get("hard_blocks", [])),
            "proof": None,
            "publication_blocked": False,
            "zero_paid_dependency": True,
        }
    proof = built["proof"]
    expected = _clean(proof.get("materialization_fingerprint_sha256"))
    supplied = _clean(materialization_fingerprint_sha256)
    blocks: list[str] = []
    if not receipt.RECEIPT_FINGERPRINT_RE.fullmatch(supplied):
        blocks.append("REREAD_RESULT_MATERIALIZATION_FINGERPRINT_INVALID")
    elif not hmac.compare_digest(expected, supplied):
        blocks.append("REREAD_RESULT_MATERIALIZATION_FINGERPRINT_MISMATCH")
    return {
        "valid": not blocks,
        "hard_blocks": blocks,
        "proof": _clone(proof) if not blocks else None,
        "publication_blocked": False,
        "zero_paid_dependency": True,
    }


def _explicit_reread_network_attempt(repo_root: Path, channel: dict[str, Any], job: dict[str, Any]) -> bool:
    state, blocks, _ = runtime.load_checkpoint_state(repo_root, channel)
    if blocks:
        return False
    entry = state.get("entries", {}).get(runtime.checkpoint_key(job))
    if not isinstance(entry, dict):
        return False
    current = receipt._latest_receipt(entry)
    return bool(
        isinstance(current, dict)
        and _clean(current.get("status")).upper() == "NETWORK_CALL_STARTED"
        and isinstance(current.get(reclaim.PROVENANCE_FIELD), dict)
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
    target_status = _clean(status).upper()
    if target_status != "COMPLETED" or not _explicit_reread_network_attempt(repo_root, channel, job):
        return _BASE_TRANSITION(
            repo_root, channel, job,
            authorization_fingerprint=authorization_fingerprint,
            now=now,
            status=status,
            last_result_status=last_result_status,
            retry_after_at=retry_after_at,
            materialization_fingerprint_sha256=materialization_fingerprint_sha256,
        )

    if _clean(last_result_status).upper() != "COLLECTED_AND_MATERIALIZED":
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESULT_MATERIALIZATION",
            "hard_blocks": ["REREAD_RESULT_COMPLETED_PROVIDER_STATUS_INVALID"],
            "publication_blocked": False,
        }
    source_bundle_fp = _clean(materialization_fingerprint_sha256)
    if not receipt.RECEIPT_FINGERPRINT_RE.fullmatch(source_bundle_fp):
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESULT_MATERIALIZATION",
            "hard_blocks": ["REREAD_RESULT_SOURCE_BUNDLE_FINGERPRINT_INVALID"],
            "publication_blocked": False,
        }

    built = build_durable_materialization_proof(repo_root, channel, job, now=now)
    if built.get("valid") is not True:
        return {
            "persisted": False,
            "status": "HOLD_REREAD_RESULT_MATERIALIZATION",
            "hard_blocks": list(built.get("hard_blocks", [])),
            "publication_blocked": False,
        }
    proof = built["proof"]
    durable_fp = _clean(proof.get("materialization_fingerprint_sha256"))
    transitioned = _BASE_TRANSITION(
        repo_root, channel, job,
        authorization_fingerprint=authorization_fingerprint,
        now=now,
        status=status,
        last_result_status=last_result_status,
        retry_after_at=retry_after_at,
        materialization_fingerprint_sha256=durable_fp,
    )
    if transitioned.get("persisted") is not True:
        return transitioned
    result = dict(transitioned)
    result.update({
        "reread_result_materialization_bound": True,
        "durable_materialization_fingerprint_sha256": durable_fp,
        "source_bundle_fingerprint_sha256": source_bundle_fp,
        "publication_blocked": False,
    })
    return result


def install() -> None:
    global _INSTALLED
    if _INSTALLED or getattr(receipt, "_reread_result_materialization_binding_patch_id", None) == PATCH_ID:
        _INSTALLED = True
        return
    receipt.transition_sealed = transition_sealed
    setattr(receipt, "_reread_result_materialization_binding_patch_id", PATCH_ID)
    _INSTALLED = True
