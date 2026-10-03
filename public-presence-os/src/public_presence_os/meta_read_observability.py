from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from .meta_read_event_log import ReadCursor, ReadEvent, validate_read_event_log
from .meta_read_only_transport import UNKNOWN

MODEL_VERSION = "PPOS_META_READ_OBSERVABILITY_V1"
ENGINE_VERSION = "ppos-meta-read-observability-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

EXPECTED_STREAM_IDENTITIES = {
    "FACEBOOK_PAGE": "2816314015107071",
    "INSTAGRAM_PROFESSIONAL": "17841429701593250",
    "THREADS": "28391623420464631",
}

EXTERNAL_METRICS = (
    "VIEWS",
    "REACH",
    "IMPRESSIONS",
    "LIKES",
    "REACTIONS",
    "COMMENTS",
    "REPLIES",
    "SHARES",
    "REPOSTS",
    "QUOTES",
    "SAVES",
    "CLICKS",
    "CONVERSIONS",
    "PROFILE_VISITS",
    "FOLLOWERS",
)


class MetaReadObservabilityHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ReadObservabilitySnapshot:
    snapshot_id: str
    snapshot_hash: str
    model_version: str
    engine_version: str
    platform: str
    external_id: str
    cursor_id: str
    cursor_hash: str
    accepted_event_count: int
    duplicate_replay_count: int
    persisted_event_count: int
    latest_sequence: int | str
    latest_event_id: str
    observed_operations: tuple[str, ...]
    latest_name: str
    latest_username: str
    latest_linked_instagram_id: str
    latest_tasks: tuple[str, ...]
    latest_unknown_fields: tuple[str, ...]
    external_metrics: tuple[tuple[str, str], ...]
    external_metric_state: str
    coverage_state: str
    state: str = "READ_OBSERVABILITY_SNAPSHOT_COMPILED"
    network_execution_authority: bool = False
    external_write_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False
    kill_switch_must_remain_engaged: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _snapshot_body(snapshot: ReadObservabilitySnapshot) -> dict:
    body = snapshot.to_dict()
    body.pop("snapshot_id")
    body.pop("snapshot_hash")
    return body


def _validate_stream_identity(platform: str, external_id: str) -> None:
    expected = EXPECTED_STREAM_IDENTITIES.get(platform)
    if expected is None:
        raise MetaReadObservabilityHold("HOLD_SA2_4_PLATFORM_NOT_ACTIVE")
    if external_id != expected:
        raise MetaReadObservabilityHold("HOLD_SA2_4_STREAM_IDENTITY_MISMATCH")


def validate_read_observability_snapshot(snapshot: ReadObservabilitySnapshot) -> None:
    if not isinstance(snapshot, ReadObservabilitySnapshot):
        raise MetaReadObservabilityHold("HOLD_SA2_4_SNAPSHOT_TYPE")
    if (snapshot.model_version, snapshot.engine_version) != (MODEL_VERSION, ENGINE_VERSION):
        raise MetaReadObservabilityHold("HOLD_SA2_4_VERSION_DRIFT")
    _validate_stream_identity(snapshot.platform, snapshot.external_id)

    if not HEX64.fullmatch(snapshot.cursor_hash) or not snapshot.cursor_id.startswith("mrc_"):
        raise MetaReadObservabilityHold("HOLD_SA2_4_CURSOR_BINDING_INVALID")
    if min(snapshot.accepted_event_count, snapshot.duplicate_replay_count, snapshot.persisted_event_count) < 0:
        raise MetaReadObservabilityHold("HOLD_SA2_4_NEGATIVE_COUNTER")
    if snapshot.accepted_event_count != snapshot.persisted_event_count:
        raise MetaReadObservabilityHold("HOLD_SA2_4_EVENT_COUNT_MISMATCH")

    metric_names = tuple(name for name, _ in snapshot.external_metrics)
    metric_values = tuple(value for _, value in snapshot.external_metrics)
    if metric_names != EXTERNAL_METRICS:
        raise MetaReadObservabilityHold("HOLD_SA2_4_EXTERNAL_METRIC_SET_DRIFT")
    if any(value != UNKNOWN for value in metric_values):
        raise MetaReadObservabilityHold("HOLD_SA2_4_EXTERNAL_METRIC_NOT_UNKNOWN")
    if snapshot.external_metric_state != "UNKNOWN_WHERE_UNAVAILABLE":
        raise MetaReadObservabilityHold("HOLD_SA2_4_EXTERNAL_METRIC_STATE")

    if snapshot.accepted_event_count == 0:
        if snapshot.coverage_state != "NO_ACCEPTED_EVENTS":
            raise MetaReadObservabilityHold("HOLD_SA2_4_EMPTY_COVERAGE_STATE")
        if snapshot.latest_sequence != UNKNOWN or snapshot.latest_event_id != UNKNOWN:
            raise MetaReadObservabilityHold("HOLD_SA2_4_EMPTY_LATEST_EVENT")
        if any((
            snapshot.latest_name != UNKNOWN,
            snapshot.latest_username != UNKNOWN,
            snapshot.latest_linked_instagram_id != UNKNOWN,
            bool(snapshot.latest_tasks),
            bool(snapshot.latest_unknown_fields),
            bool(snapshot.observed_operations),
        )):
            raise MetaReadObservabilityHold("HOLD_SA2_4_EMPTY_STREAM_FALSE_OBSERVATION")
    else:
        if snapshot.coverage_state != "READ_EVENT_OBSERVED":
            raise MetaReadObservabilityHold("HOLD_SA2_4_OBSERVED_COVERAGE_STATE")
        if snapshot.latest_sequence != snapshot.accepted_event_count:
            raise MetaReadObservabilityHold("HOLD_SA2_4_LATEST_SEQUENCE_MISMATCH")
        if not isinstance(snapshot.latest_event_id, str) or not snapshot.latest_event_id.startswith("mre_"):
            raise MetaReadObservabilityHold("HOLD_SA2_4_LATEST_EVENT_ID")
        if not snapshot.observed_operations:
            raise MetaReadObservabilityHold("HOLD_SA2_4_OBSERVED_OPERATIONS_REQUIRED")

    if snapshot.state != "READ_OBSERVABILITY_SNAPSHOT_COMPILED":
        raise MetaReadObservabilityHold("HOLD_SA2_4_SNAPSHOT_STATE")
    if any((
        snapshot.network_execution_authority,
        snapshot.external_write_authority,
        snapshot.publish_authority,
        snapshot.deploy_authority,
    )):
        raise MetaReadObservabilityHold("HOLD_SA2_4_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not snapshot.kill_switch_must_remain_engaged:
        raise MetaReadObservabilityHold("HOLD_SA2_4_KILL_SWITCH_DRIFT")

    expected_hash = _hash(_snapshot_body(snapshot))
    if not HEX64.fullmatch(snapshot.snapshot_hash) or snapshot.snapshot_hash != expected_hash:
        raise MetaReadObservabilityHold("HOLD_SA2_4_SNAPSHOT_HASH_MISMATCH")
    if snapshot.snapshot_id != "mros_" + expected_hash[:24]:
        raise MetaReadObservabilityHold("HOLD_SA2_4_SNAPSHOT_ID_MISMATCH")


def compile_read_observability_snapshot(
    cursor: ReadCursor,
    events: tuple[ReadEvent, ...],
) -> ReadObservabilitySnapshot:
    validate_read_event_log(cursor, events)
    _validate_stream_identity(cursor.platform, cursor.external_id)

    if events:
        latest = events[-1]
        latest_sequence: int | str = latest.sequence
        latest_event_id = latest.event_id
        latest_name = latest.name
        latest_username = latest.username
        latest_linked_instagram_id = latest.linked_instagram_id
        latest_tasks = latest.tasks
        latest_unknown_fields = latest.unknown_fields
        observed_operations = tuple(sorted({event.operation for event in events}))
        coverage_state = "READ_EVENT_OBSERVED"
    else:
        latest_sequence = UNKNOWN
        latest_event_id = UNKNOWN
        latest_name = UNKNOWN
        latest_username = UNKNOWN
        latest_linked_instagram_id = UNKNOWN
        latest_tasks = ()
        latest_unknown_fields = ()
        observed_operations = ()
        coverage_state = "NO_ACCEPTED_EVENTS"

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "platform": cursor.platform,
        "external_id": cursor.external_id,
        "cursor_id": cursor.cursor_id,
        "cursor_hash": cursor.cursor_hash,
        "accepted_event_count": cursor.accepted_count,
        "duplicate_replay_count": cursor.duplicate_count,
        "persisted_event_count": len(events),
        "latest_sequence": latest_sequence,
        "latest_event_id": latest_event_id,
        "observed_operations": observed_operations,
        "latest_name": latest_name,
        "latest_username": latest_username,
        "latest_linked_instagram_id": latest_linked_instagram_id,
        "latest_tasks": latest_tasks,
        "latest_unknown_fields": latest_unknown_fields,
        "external_metrics": tuple((metric, UNKNOWN) for metric in EXTERNAL_METRICS),
        "external_metric_state": "UNKNOWN_WHERE_UNAVAILABLE",
        "coverage_state": coverage_state,
        "state": "READ_OBSERVABILITY_SNAPSHOT_COMPILED",
        "network_execution_authority": False,
        "external_write_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
        "kill_switch_must_remain_engaged": True,
    }
    snapshot_hash = _hash(body)
    snapshot = ReadObservabilitySnapshot(
        snapshot_id="mros_" + snapshot_hash[:24],
        snapshot_hash=snapshot_hash,
        **body,
    )
    validate_read_observability_snapshot(snapshot)
    return snapshot
