from __future__ import annotations

from dataclasses import fields
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Union

from .meta_cross_lane_read_coverage import (
    CrossLaneCoverageSnapshot,
    validate_cross_lane_coverage_snapshot,
)
from .meta_read_observability import (
    ReadObservabilitySnapshot,
    validate_read_observability_snapshot,
)

MODEL_VERSION = "PPOS_META_SNAPSHOT_PERSISTENCE_V1"
ENGINE_VERSION = "ppos-meta-snapshot-persistence-v1.0.0"

KIND_READ_OBSERVABILITY = "READ_OBSERVABILITY_SNAPSHOT"
KIND_CROSS_LANE_COVERAGE = "CROSS_LANE_COVERAGE_SNAPSHOT"
SUPPORTED_KINDS = (KIND_READ_OBSERVABILITY, KIND_CROSS_LANE_COVERAGE)

Snapshot = Union[ReadObservabilitySnapshot, CrossLaneCoverageSnapshot]

_ENVELOPE_KEYS = {
    "model_version",
    "engine_version",
    "kind",
    "payload",
    "state",
    "network_execution_authority",
    "external_write_authority",
    "publish_authority",
    "deploy_authority",
    "kill_switch_must_remain_engaged",
    "checksum_sha256",
}


class MetaSnapshotPersistenceHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _checksum(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _payload_keys(cls) -> set[str]:
    return {field.name for field in fields(cls)}


def _tuple_of_strings(value, reason: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise MetaSnapshotPersistenceHold(reason)
    return tuple(value)


def _pair_tuple(value, reason: str) -> tuple[tuple[object, object], ...]:
    if not isinstance(value, list):
        raise MetaSnapshotPersistenceHold(reason)
    output = []
    for pair in value:
        if not isinstance(pair, list) or len(pair) != 2:
            raise MetaSnapshotPersistenceHold(reason)
        output.append((pair[0], pair[1]))
    return tuple(output)


def _snapshot_kind(snapshot: Snapshot) -> str:
    if isinstance(snapshot, ReadObservabilitySnapshot):
        validate_read_observability_snapshot(snapshot)
        return KIND_READ_OBSERVABILITY
    if isinstance(snapshot, CrossLaneCoverageSnapshot):
        validate_cross_lane_coverage_snapshot(snapshot)
        return KIND_CROSS_LANE_COVERAGE
    raise MetaSnapshotPersistenceHold("HOLD_SA2_6_UNSUPPORTED_SNAPSHOT_TYPE")


def _envelope_body(snapshot: Snapshot) -> dict:
    kind = _snapshot_kind(snapshot)
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "kind": kind,
        "payload": snapshot.to_dict(),
        "state": "LOCAL_SNAPSHOT_PERSISTENCE_ENVELOPE",
        "network_execution_authority": False,
        "external_write_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
        "kill_switch_must_remain_engaged": True,
    }


def encode_snapshot(snapshot: Snapshot) -> str:
    body = _envelope_body(snapshot)
    envelope = dict(body)
    envelope["checksum_sha256"] = _checksum(body)
    return _canonical(envelope)


def _restore_read_observability(payload: dict) -> ReadObservabilitySnapshot:
    if set(payload) != _payload_keys(ReadObservabilitySnapshot):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_READ_PAYLOAD_SCHEMA_DRIFT")
    restored = dict(payload)
    restored["observed_operations"] = _tuple_of_strings(
        restored["observed_operations"], "HOLD_SA2_6_READ_OBSERVED_OPERATIONS_SHAPE"
    )
    restored["latest_tasks"] = _tuple_of_strings(
        restored["latest_tasks"], "HOLD_SA2_6_READ_LATEST_TASKS_SHAPE"
    )
    restored["latest_unknown_fields"] = _tuple_of_strings(
        restored["latest_unknown_fields"], "HOLD_SA2_6_READ_UNKNOWN_FIELDS_SHAPE"
    )
    restored["external_metrics"] = _pair_tuple(
        restored["external_metrics"], "HOLD_SA2_6_READ_EXTERNAL_METRICS_SHAPE"
    )
    try:
        snapshot = ReadObservabilitySnapshot(**restored)
        validate_read_observability_snapshot(snapshot)
    except MetaSnapshotPersistenceHold:
        raise
    except Exception as exc:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_READ_PAYLOAD_INVALID") from exc
    return snapshot


def _restore_cross_lane_coverage(payload: dict) -> CrossLaneCoverageSnapshot:
    if set(payload) != _payload_keys(CrossLaneCoverageSnapshot):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_COVERAGE_PAYLOAD_SCHEMA_DRIFT")
    restored = dict(payload)
    for name in ("active_lanes", "present_lanes", "missing_lanes"):
        restored[name] = _tuple_of_strings(
            restored[name], f"HOLD_SA2_6_COVERAGE_{name.upper()}_SHAPE"
        )
    for name in (
        "lane_snapshot_ids",
        "lane_snapshot_hashes",
        "lane_coverage_states",
        "lane_accepted_event_counts",
        "lane_duplicate_replay_counts",
        "lane_unknown_metric_counts",
        "external_metrics",
    ):
        restored[name] = _pair_tuple(
            restored[name], f"HOLD_SA2_6_COVERAGE_{name.upper()}_SHAPE"
        )
    try:
        snapshot = CrossLaneCoverageSnapshot(**restored)
        validate_cross_lane_coverage_snapshot(snapshot)
    except MetaSnapshotPersistenceHold:
        raise
    except Exception as exc:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_COVERAGE_PAYLOAD_INVALID") from exc
    return snapshot


def decode_snapshot(serialized: str) -> Snapshot:
    if not isinstance(serialized, str) or not serialized:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_SERIALIZED_TEXT_REQUIRED")
    try:
        envelope = json.loads(serialized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_INVALID_JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != _ENVELOPE_KEYS:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_ENVELOPE_SCHEMA_DRIFT")

    checksum = envelope.get("checksum_sha256")
    if not isinstance(checksum, str) or len(checksum) != 64:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_CHECKSUM_SHAPE")
    body = dict(envelope)
    body.pop("checksum_sha256")
    if checksum != _checksum(body):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_CHECKSUM_MISMATCH")

    if (body["model_version"], body["engine_version"]) != (MODEL_VERSION, ENGINE_VERSION):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_VERSION_DRIFT")
    if body["state"] != "LOCAL_SNAPSHOT_PERSISTENCE_ENVELOPE":
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_STATE_DRIFT")
    if any(
        (
            body["network_execution_authority"],
            body["external_write_authority"],
            body["publish_authority"],
            body["deploy_authority"],
        )
    ):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_EXTERNAL_AUTHORITY_FORBIDDEN")
    if body["kill_switch_must_remain_engaged"] is not True:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_KILL_SWITCH_DRIFT")
    if not isinstance(body["payload"], dict):
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_PAYLOAD_OBJECT_REQUIRED")

    if body["kind"] == KIND_READ_OBSERVABILITY:
        return _restore_read_observability(body["payload"])
    if body["kind"] == KIND_CROSS_LANE_COVERAGE:
        return _restore_cross_lane_coverage(body["payload"])
    raise MetaSnapshotPersistenceHold("HOLD_SA2_6_UNSUPPORTED_KIND")


def persist_snapshot(path: str | Path, snapshot: Snapshot) -> str:
    target = Path(path)
    if not target.parent.exists():
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_PARENT_DIRECTORY_MISSING")

    serialized = encode_snapshot(snapshot)
    data = serialized.encode("utf-8")
    temp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, target)
        temp_name = None
    except OSError as exc:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_LOCAL_PERSISTENCE_IO") from exc
    finally:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
    return sha256(data).hexdigest()


def load_snapshot(path: str | Path) -> Snapshot:
    target = Path(path)
    try:
        serialized = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise MetaSnapshotPersistenceHold("HOLD_SA2_6_LOCAL_RELOAD_IO") from exc
    return decode_snapshot(serialized)
