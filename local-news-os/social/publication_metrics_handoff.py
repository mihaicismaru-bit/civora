#!/usr/bin/env python3
"""Operational post-publication metrics catalog materialization for LOCAL NEWS OS.

This runtime begins only after a social publication has durable remote proof. It
binds the already-verified fact kernel and exact native product to the confirmed
publication, persists the channel-local metrics catalog with compare-and-swap
semantics, then hands the persisted catalog to the existing 1h/6h/24h/72h
metrics harvest scheduler.

Analytics remain outside the editorial/publication critical path: any failure in
catalog binding, persistence or harvest planning leaves the publication itself
untouched and reported as already published.

Safety properties:
- no network calls and no credential values are read or persisted here;
- only a PUBLISHED record with remote_publication_id may enter the catalog;
- catalog writes are channel-local, atomic and compare-and-swap guarded;
- the scheduler sees the catalog only after successful/idem durable persistence;
- predictive/estimated analytics never influence binding or scheduling;
- no legacy publication descriptor fabrication;
- metrics failures never roll back or block the confirmed publication;
- zero paid dependency is mandatory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

import durable_dispatch_executor
import metrics_harvest_scheduler
import publication_metrics_catalog

SCHEMA_VERSION = "1.0"
RUNTIME_ID = "local-news-os-publication-metrics-handoff"


def _clean(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _safe_target(repo_root: Path, relative_path: str) -> Path:
    relative = PurePosixPath(_clean(relative_path).replace("\\", "/"))
    if relative.is_absolute() or ".." in relative.parts or relative.name in {"", "."}:
        raise ValueError("unsafe catalog path")
    return repo_root.joinpath(*relative.parts)


def _load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def load_existing_catalog(repo_root: Path, channel: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate the channel-local catalog without fabricating one."""
    try:
        relative = publication_metrics_catalog.expected_catalog_path(channel)
        target = _safe_target(repo_root, relative)
    except (TypeError, ValueError) as exc:
        return None, ["CATALOG_PATH_INVALID:" + str(exc)]
    if not target.exists():
        return None, []
    try:
        catalog = _load_json_object(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return None, ["CATALOG_READ_INVALID:" + str(exc)]
    checked = publication_metrics_catalog.validate_catalog(channel, catalog)
    if checked.get("valid") is not True:
        return None, ["EXISTING_" + str(code) for code in checked.get("hard_blocks", [])]
    return catalog, []


def _extract_published_record(dispatch_result: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Extract remote proof from durable dispatch/reconciliation output.

    Normal durable reconciliation returns ``record`` directly. Crash recovery may
    return only a validated durable executor state, so that path is accepted only
    after re-validating the executor state's own seal and identity contract.
    """
    if not isinstance(dispatch_result, dict):
        raise TypeError("dispatch_result must be a mapping")
    blocks: list[str] = []
    if dispatch_result.get("blocked") is True:
        blocks.append("DISPATCH_RESULT_BLOCKED")
    declared_status = _clean(dispatch_result.get("publication_status")).upper()
    record = dispatch_result.get("record") if isinstance(dispatch_result.get("record"), dict) else None

    if record is None:
        state = dispatch_result.get("state") if isinstance(dispatch_result.get("state"), dict) else None
        if state is None:
            blocks.append("PUBLISHED_RECORD_MISSING")
        else:
            state_blocks = durable_dispatch_executor._validate_state(state)  # same-core invariant check
            if state_blocks:
                blocks.extend("DISPATCH_STATE:" + str(code) for code in state_blocks)
            else:
                handoff_id = _clean(state.get("handoff_id"))
                outbox = state.get("outbox") if isinstance(state.get("outbox"), dict) else {}
                items = outbox.get("items") if isinstance(outbox.get("items"), dict) else {}
                item = items.get(handoff_id) if isinstance(items.get(handoff_id), dict) else None
                publication_id = _clean((item or {}).get("publication_id"))
                ledger = state.get("ledger") if isinstance(state.get("ledger"), dict) else {}
                records = ledger.get("records") if isinstance(ledger.get("records"), dict) else {}
                candidate = records.get(publication_id) if isinstance(records.get(publication_id), dict) else None
                if candidate is None:
                    blocks.append("PUBLISHED_RECORD_MISSING_FROM_VALIDATED_STATE")
                else:
                    record = candidate

    if record is not None:
        record_status = _clean(record.get("status")).upper()
        if record_status != "PUBLISHED":
            blocks.append("REMOTE_PUBLICATION_NOT_CONFIRMED")
        if declared_status and declared_status != "PUBLISHED":
            blocks.append("DISPATCH_PUBLICATION_STATUS_NOT_PUBLISHED")
        if not _clean(record.get("remote_publication_id")):
            blocks.append("MISSING_REMOTE_PUBLICATION_ID")
        if not _clean(record.get("published_at")):
            blocks.append("MISSING_PUBLISHED_AT")
    return (_clone(record) if record is not None else None), sorted(set(blocks))


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def persist_catalog_cas(
    repo_root: Path,
    channel: dict[str, Any],
    catalog: dict[str, Any],
    *,
    expected_previous_catalog_fingerprint_sha256: str | None,
) -> dict[str, Any]:
    """Atomically persist one validated catalog under compare-and-swap semantics."""
    if not isinstance(channel, dict) or not isinstance(catalog, dict):
        raise TypeError("channel and catalog must be mappings")
    checked = publication_metrics_catalog.validate_catalog(channel, catalog)
    if checked.get("valid") is not True:
        return {
            "persisted": False,
            "status": "HOLD_TARGET_CATALOG_INVALID",
            "hard_blocks": list(checked.get("hard_blocks", [])),
            "path": None,
        }

    relative = publication_metrics_catalog.expected_catalog_path(channel)
    target = _safe_target(repo_root, relative)
    existing: dict[str, Any] | None = None
    if target.exists():
        try:
            existing = _load_json_object(target)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {
                "persisted": False,
                "status": "HOLD_EXISTING_CATALOG_INVALID",
                "hard_blocks": ["CATALOG_READ_INVALID:" + str(exc)],
                "path": relative,
            }
        existing_check = publication_metrics_catalog.validate_catalog(channel, existing)
        if existing_check.get("valid") is not True:
            return {
                "persisted": False,
                "status": "HOLD_EXISTING_CATALOG_INVALID",
                "hard_blocks": list(existing_check.get("hard_blocks", [])),
                "path": relative,
            }

    actual_previous = _clean((existing or {}).get("catalog_fingerprint_sha256")) or None
    expected_previous = _clean(expected_previous_catalog_fingerprint_sha256) or None
    if actual_previous != expected_previous:
        return {
            "persisted": False,
            "status": "HOLD_CATALOG_CAS_CONFLICT",
            "hard_blocks": ["CATALOG_COMPARE_AND_SWAP_CONFLICT"],
            "path": relative,
            "expected_previous_catalog_fingerprint_sha256": expected_previous,
            "actual_previous_catalog_fingerprint_sha256": actual_previous,
        }

    target_fp = _clean(catalog.get("catalog_fingerprint_sha256"))
    if existing is not None and actual_previous == target_fp:
        return {
            "persisted": True,
            "status": "IDEMPOTENT_CATALOG",
            "hard_blocks": [],
            "path": relative,
            "written": False,
            "catalog_fingerprint_sha256": target_fp,
        }

    _atomic_write_json(target, catalog)
    try:
        persisted = _load_json_object(target)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {
            "persisted": False,
            "status": "HOLD_CATALOG_READBACK_FAILED",
            "hard_blocks": ["CATALOG_READBACK_INVALID:" + str(exc)],
            "path": relative,
        }
    readback = publication_metrics_catalog.validate_catalog(channel, persisted)
    if readback.get("valid") is not True or _clean(persisted.get("catalog_fingerprint_sha256")) != target_fp:
        return {
            "persisted": False,
            "status": "HOLD_CATALOG_READBACK_FAILED",
            "hard_blocks": list(readback.get("hard_blocks", [])) or ["CATALOG_READBACK_FINGERPRINT_MISMATCH"],
            "path": relative,
        }
    return {
        "persisted": True,
        "status": "CATALOG_PERSISTED",
        "hard_blocks": [],
        "path": relative,
        "written": True,
        "catalog_fingerprint_sha256": target_fp,
    }


def _hold(channel: dict[str, Any], status: str, blocks: list[str], *, persistence: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")) or None,
        "channel_id": _clean(channel.get("channel_id")) or None,
        "platform": _clean(channel.get("platform")).lower() or None,
        "status": status,
        "hard_blocks": sorted(set(blocks)),
        "publication_blocked": False,
        "publication_rolled_back": False,
        "catalog_persistence": _clone(persistence) if persistence is not None else None,
        "harvest_plan": None,
        "guards": {
            "remote_publication_proof_required": True,
            "catalog_persisted_before_scheduler": False,
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "publication_blocked_by_metrics": False,
            "zero_paid_dependency": True,
        },
    }
    result["runtime_fingerprint_sha256"] = _digest(result)
    return result


def materialize_after_remote_publication(
    channel: dict[str, Any],
    story: dict[str, Any],
    runtime_result: dict[str, Any],
    dispatch_result: dict[str, Any],
    access_attestation: dict[str, Any],
    *,
    repo_root: Path,
    now: str,
    observation_store: dict[str, Any] | None = None,
    windows_hours: Any = None,
    max_publications: int = metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS,
) -> dict[str, Any]:
    """Bind -> CAS persist -> scheduler handoff after durable remote proof."""
    if not all(isinstance(value, dict) for value in (channel, story, runtime_result, dispatch_result, access_attestation)):
        raise TypeError("channel, story, runtime_result, dispatch_result and access_attestation must be mappings")
    if channel.get("zero_paid_dependency") is not True:
        return _hold(channel, "HOLD_METRICS_CATALOG", ["ZERO_PAID_DEPENDENCY_VIOLATION"])

    published_record, proof_blocks = _extract_published_record(dispatch_result)
    if proof_blocks or published_record is None:
        return _hold(channel, "HOLD_REMOTE_PUBLICATION_PROOF", proof_blocks or ["PUBLISHED_RECORD_MISSING"])

    existing_catalog, load_blocks = load_existing_catalog(repo_root, channel)
    if load_blocks:
        return _hold(channel, "HOLD_METRICS_CATALOG", load_blocks)

    binding = publication_metrics_catalog.bind_published_publication(
        channel,
        story,
        runtime_result,
        published_record,
        existing_catalog,
    )
    if binding.get("blocked") is True:
        return _hold(channel, "HOLD_DESCRIPTOR_BINDING", list(binding.get("hard_blocks", [])))

    materialization = binding.get("materialization") if isinstance(binding.get("materialization"), dict) else {}
    persistence = persist_catalog_cas(
        repo_root,
        channel,
        binding["catalog"],
        expected_previous_catalog_fingerprint_sha256=materialization.get("expected_previous_catalog_fingerprint_sha256"),
    )
    if persistence.get("persisted") is not True:
        return _hold(
            channel,
            "HOLD_CATALOG_PERSISTENCE",
            list(persistence.get("hard_blocks", [])),
            persistence=persistence,
        )

    persisted_catalog, read_blocks = load_existing_catalog(repo_root, channel)
    if read_blocks or persisted_catalog is None:
        return _hold(
            channel,
            "HOLD_CATALOG_READBACK",
            read_blocks or ["PERSISTED_CATALOG_MISSING"],
            persistence=persistence,
        )

    harvest_plan = metrics_harvest_scheduler.plan_harvest(
        channel,
        persisted_catalog,
        access_attestation,
        now=now,
        observation_store=observation_store,
        windows_hours=windows_hours,
        max_publications=max_publications,
    )
    scheduler_status = _clean(harvest_plan.get("status"))
    if scheduler_status not in {"HARVEST_READY", "NO_HARVEST_DUE"}:
        status = "CATALOG_PERSISTED_HARVEST_HOLD"
    elif scheduler_status == "HARVEST_READY":
        status = "CATALOG_PERSISTED_HARVEST_READY"
    else:
        status = "CATALOG_PERSISTED_NO_HARVEST_DUE"

    result = {
        "schema_version": SCHEMA_VERSION,
        "runtime_id": RUNTIME_ID,
        "instance_id": _clean(channel.get("instance_id")),
        "channel_id": _clean(channel.get("channel_id")),
        "platform": _clean(channel.get("platform")).lower(),
        "status": status,
        "hard_blocks": [] if scheduler_status in {"HARVEST_READY", "NO_HARVEST_DUE"} else list(harvest_plan.get("hard_blocks", [])),
        "publication_blocked": False,
        "publication_rolled_back": False,
        "publication_id": _clean(published_record.get("publication_id")),
        "remote_publication_id": _clean(published_record.get("remote_publication_id")),
        "descriptor_fingerprint_sha256": _clean((binding.get("descriptor") or {}).get("descriptor_fingerprint_sha256")),
        "catalog_fingerprint_sha256": _clean(persisted_catalog.get("catalog_fingerprint_sha256")),
        "catalog_persistence": persistence,
        "harvest_plan": harvest_plan,
        "guards": {
            "remote_publication_proof_required": True,
            "catalog_persisted_before_scheduler": True,
            "scheduler_catalog_fingerprint_sha256": _clean(persisted_catalog.get("catalog_fingerprint_sha256")),
            "network_calls_performed": False,
            "credential_values_read": False,
            "credential_values_persisted": False,
            "predictive_or_estimated_analytics_used": False,
            "publication_blocked_by_metrics": False,
            "publication_state_mutated": False,
            "zero_paid_dependency": True,
        },
    }
    result["runtime_fingerprint_sha256"] = _digest(result)
    return result


def _load_optional(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return _load_json_object(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("channel", type=Path)
    parser.add_argument("story", type=Path)
    parser.add_argument("runtime_result", type=Path)
    parser.add_argument("dispatch_result", type=Path)
    parser.add_argument("access_attestation", type=Path)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--now", required=True)
    parser.add_argument("--observation-store", type=Path)
    parser.add_argument("--windows-hours", default="1,6,24,72")
    parser.add_argument("--max-publications", type=int, default=metrics_harvest_scheduler.DEFAULT_MAX_PUBLICATIONS)
    args = parser.parse_args()

    windows = [int(item.strip()) for item in args.windows_hours.split(",") if item.strip()]
    result = materialize_after_remote_publication(
        _load_json_object(args.channel),
        _load_json_object(args.story),
        _load_json_object(args.runtime_result),
        _load_json_object(args.dispatch_result),
        _load_json_object(args.access_attestation),
        repo_root=args.repo_root,
        now=args.now,
        observation_store=_load_optional(args.observation_store),
        windows_hours=windows,
        max_publications=args.max_publications,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not result.get("hard_blocks") else 2


if __name__ == "__main__":
    raise SystemExit(main())
