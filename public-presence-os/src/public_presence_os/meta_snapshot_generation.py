from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from .meta_snapshot_persistence import (
    MetaSnapshotPersistenceHold,
    Snapshot,
    decode_snapshot,
    encode_snapshot,
)

MODEL_VERSION = "PPOS_META_SNAPSHOT_GENERATION_V1"
ENGINE_VERSION = "ppos-meta-snapshot-generation-v1.0.0"
STATE = "LOCAL_GENERATION_ORDERED_SNAPSHOT"


class MetaSnapshotGenerationHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class SnapshotGenerationRecord:
    generation: int
    previous_generation: int | None
    previous_record_sha256: str | None
    snapshot_sha256: str
    snapshot_serialized: str
    record_sha256: str


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _is_sha(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _generation(value) -> int:
    if type(value) is not int or value < 1:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_GENERATION_INVALID")
    return value


def _body(
    snapshot_serialized: str,
    generation: int,
    previous_generation: int | None,
    previous_record_sha256: str | None,
) -> dict:
    return {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "state": STATE,
        "generation": generation,
        "previous_generation": previous_generation,
        "previous_record_sha256": previous_record_sha256,
        "snapshot_sha256": _sha(snapshot_serialized),
        "snapshot_serialized": snapshot_serialized,
        "network_execution_authority": False,
        "external_write_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
        "kill_switch_must_remain_engaged": True,
    }


def encode_generation_record(
    snapshot: Snapshot,
    generation: int,
    previous: SnapshotGenerationRecord | None = None,
) -> str:
    generation = _generation(generation)
    if generation == 1:
        if previous is not None:
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_INITIAL_PREDECESSOR_FORBIDDEN")
        previous_generation = None
        previous_sha = None
    else:
        if previous is None:
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_REQUIRED")
        if previous.generation != generation - 1:
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_GENERATION_DRIFT")
        if not _is_sha(previous.record_sha256):
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_HASH_INVALID")
        previous_generation = previous.generation
        previous_sha = previous.record_sha256

    snapshot_serialized = encode_snapshot(snapshot)
    body = _body(snapshot_serialized, generation, previous_generation, previous_sha)
    envelope = dict(body)
    envelope["record_sha256"] = _sha(_canonical(body))
    return _canonical(envelope)


def decode_generation_record(serialized: str) -> SnapshotGenerationRecord:
    try:
        envelope = json.loads(serialized)
    except (json.JSONDecodeError, TypeError) as exc:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_INVALID_JSON") from exc

    required = {
        "model_version",
        "engine_version",
        "state",
        "generation",
        "previous_generation",
        "previous_record_sha256",
        "snapshot_sha256",
        "snapshot_serialized",
        "network_execution_authority",
        "external_write_authority",
        "publish_authority",
        "deploy_authority",
        "kill_switch_must_remain_engaged",
        "record_sha256",
    }
    if not isinstance(envelope, dict) or set(envelope) != required:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_RECORD_SCHEMA_DRIFT")

    record_sha = envelope["record_sha256"]
    body = dict(envelope)
    body.pop("record_sha256")
    if not _is_sha(record_sha) or record_sha != _sha(_canonical(body)):
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_RECORD_HASH_MISMATCH")

    if (body["model_version"], body["engine_version"], body["state"]) != (
        MODEL_VERSION,
        ENGINE_VERSION,
        STATE,
    ):
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_VERSION_OR_STATE_DRIFT")
    if any(
        (
            body["network_execution_authority"],
            body["external_write_authority"],
            body["publish_authority"],
            body["deploy_authority"],
        )
    ):
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_EXTERNAL_AUTHORITY_FORBIDDEN")
    if body["kill_switch_must_remain_engaged"] is not True:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_KILL_SWITCH_DRIFT")

    generation = _generation(body["generation"])
    previous_generation = body["previous_generation"]
    previous_sha = body["previous_record_sha256"]
    if generation == 1:
        if previous_generation is not None or previous_sha is not None:
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_INITIAL_PREDECESSOR_FORBIDDEN")
    else:
        if previous_generation != generation - 1:
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_GENERATION_DRIFT")
        if not _is_sha(previous_sha):
            raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_HASH_INVALID")

    snapshot_serialized = body["snapshot_serialized"]
    if body["snapshot_sha256"] != _sha(snapshot_serialized):
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_SNAPSHOT_HASH_MISMATCH")
    try:
        decode_snapshot(snapshot_serialized)
    except MetaSnapshotPersistenceHold as exc:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_INNER_SNAPSHOT_INVALID") from exc

    return SnapshotGenerationRecord(
        generation=generation,
        previous_generation=previous_generation,
        previous_record_sha256=previous_sha,
        snapshot_sha256=body["snapshot_sha256"],
        snapshot_serialized=snapshot_serialized,
        record_sha256=record_sha,
    )


def require_minimum_generation(
    record: SnapshotGenerationRecord,
    minimum_generation: int,
) -> SnapshotGenerationRecord:
    minimum_generation = _generation(minimum_generation)
    if record.generation < minimum_generation:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_STALE_PERSISTED_STATE")
    return record


def accept_next_generation(
    current: SnapshotGenerationRecord,
    candidate: SnapshotGenerationRecord,
) -> SnapshotGenerationRecord:
    if candidate.generation <= current.generation:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_STALE_PERSISTED_STATE")
    if candidate.generation != current.generation + 1:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_GENERATION_GAP")
    if candidate.previous_generation != current.generation:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_GENERATION_DRIFT")
    if candidate.previous_record_sha256 != current.record_sha256:
        raise MetaSnapshotGenerationHold("HOLD_SA2_7_PREDECESSOR_HASH_MISMATCH")
    return candidate
