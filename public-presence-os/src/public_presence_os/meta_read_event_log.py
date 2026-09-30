from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from .meta_read_only_transport import NormalizedReadRecord

MODEL_VERSION = "PPOS_META_READ_CURSOR_EVENT_LOG_V1"
ENGINE_VERSION = "ppos-meta-read-cursor-event-log-v1.0.0"
EMPTY_EVENT_ID = "NONE"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class MetaReadEventLogHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class ReadCursor:
    cursor_id: str
    cursor_hash: str
    platform: str
    external_id: str
    next_sequence: int
    last_event_id: str
    accepted_count: int
    duplicate_count: int
    state: str = "READ_CURSOR_VALID"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ReadEvent:
    event_id: str
    event_hash: str
    sequence: int
    operation: str
    platform: str
    external_id: str
    name: str
    username: str
    linked_instagram_id: str
    tasks: tuple[str, ...]
    source_response_sha256: str
    unknown_fields: tuple[str, ...]
    normalized_record_fingerprint: str
    state: str = "READ_EVENT_ACCEPTED"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class IngestResult:
    action: str
    cursor: ReadCursor
    events: tuple[ReadEvent, ...]
    event_id: str
    normalized_record_fingerprint: str


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _cursor_body(platform: str, external_id: str, next_sequence: int, last_event_id: str,
                 accepted_count: int, duplicate_count: int) -> dict:
    return {
        "platform": platform,
        "external_id": external_id,
        "next_sequence": next_sequence,
        "last_event_id": last_event_id,
        "accepted_count": accepted_count,
        "duplicate_count": duplicate_count,
        "state": "READ_CURSOR_VALID",
    }


def _make_cursor(platform: str, external_id: str, next_sequence: int, last_event_id: str,
                 accepted_count: int, duplicate_count: int) -> ReadCursor:
    body = _cursor_body(platform, external_id, next_sequence, last_event_id, accepted_count, duplicate_count)
    cursor_hash = _hash(body)
    cursor = ReadCursor(
        cursor_id="mrc_" + cursor_hash[:24],
        cursor_hash=cursor_hash,
        platform=platform,
        external_id=external_id,
        next_sequence=next_sequence,
        last_event_id=last_event_id,
        accepted_count=accepted_count,
        duplicate_count=duplicate_count,
    )
    validate_read_cursor(cursor)
    return cursor


def new_read_cursor(platform: str, external_id: str) -> ReadCursor:
    if not isinstance(platform, str) or not platform:
        raise MetaReadEventLogHold("HOLD_SA2_3_PLATFORM_REQUIRED")
    if not isinstance(external_id, str) or not external_id:
        raise MetaReadEventLogHold("HOLD_SA2_3_EXTERNAL_ID_REQUIRED")
    return _make_cursor(platform, external_id, 1, EMPTY_EVENT_ID, 0, 0)


def validate_read_cursor(cursor: ReadCursor) -> None:
    if not isinstance(cursor, ReadCursor):
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_TYPE")
    if not cursor.platform or not cursor.external_id:
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_STREAM_IDENTITY")
    if cursor.next_sequence != cursor.accepted_count + 1 or cursor.duplicate_count < 0:
        raise MetaReadEventLogHold("HOLD_SA2_3_NON_MONOTONIC_SEQUENCE")
    if cursor.accepted_count == 0 and cursor.last_event_id != EMPTY_EVENT_ID:
        raise MetaReadEventLogHold("HOLD_SA2_3_EMPTY_CURSOR_LAST_EVENT")
    if cursor.accepted_count > 0 and cursor.last_event_id == EMPTY_EVENT_ID:
        raise MetaReadEventLogHold("HOLD_SA2_3_LAST_EVENT_REQUIRED")
    if cursor.state != "READ_CURSOR_VALID":
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_STATE")
    body = cursor.to_dict()
    body.pop("cursor_id")
    body.pop("cursor_hash")
    expected_hash = _hash(body)
    if cursor.cursor_hash != expected_hash or cursor.cursor_id != "mrc_" + expected_hash[:24]:
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_HASH_MISMATCH")


def normalized_record_fingerprint(record: NormalizedReadRecord) -> str:
    if not isinstance(record, NormalizedReadRecord):
        raise MetaReadEventLogHold("HOLD_SA2_3_NORMALIZED_RECORD_TYPE")
    if not record.platform or not record.external_id or record.state != "NORMALIZED_READ_ONLY_EVIDENCE":
        raise MetaReadEventLogHold("HOLD_SA2_3_NORMALIZED_RECORD_STATE")
    if not HEX64.fullmatch(record.source_response_sha256):
        raise MetaReadEventLogHold("HOLD_SA2_3_SOURCE_HASH_INVALID")
    return _hash(record.to_dict())


def _make_event(record: NormalizedReadRecord, sequence: int, fingerprint: str) -> ReadEvent:
    body = {
        "sequence": sequence,
        "operation": record.operation,
        "platform": record.platform,
        "external_id": record.external_id,
        "name": record.name,
        "username": record.username,
        "linked_instagram_id": record.linked_instagram_id,
        "tasks": list(record.tasks),
        "source_response_sha256": record.source_response_sha256,
        "unknown_fields": list(record.unknown_fields),
        "normalized_record_fingerprint": fingerprint,
        "state": "READ_EVENT_ACCEPTED",
    }
    event_hash = _hash(body)
    event = ReadEvent(
        event_id="mre_" + fingerprint[:24],
        event_hash=event_hash,
        sequence=sequence,
        operation=record.operation,
        platform=record.platform,
        external_id=record.external_id,
        name=record.name,
        username=record.username,
        linked_instagram_id=record.linked_instagram_id,
        tasks=record.tasks,
        source_response_sha256=record.source_response_sha256,
        unknown_fields=record.unknown_fields,
        normalized_record_fingerprint=fingerprint,
    )
    validate_read_event(event)
    return event


def validate_read_event(event: ReadEvent) -> None:
    if not isinstance(event, ReadEvent) or event.sequence < 1:
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENT_TYPE_OR_SEQUENCE")
    if not HEX64.fullmatch(event.source_response_sha256) or not HEX64.fullmatch(event.normalized_record_fingerprint):
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENT_HASH_FIELD_INVALID")
    if event.event_id != "mre_" + event.normalized_record_fingerprint[:24]:
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENT_ID_MISMATCH")
    if event.state != "READ_EVENT_ACCEPTED":
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENT_STATE")
    body = event.to_dict()
    body.pop("event_id")
    body.pop("event_hash")
    body["tasks"] = list(event.tasks)
    body["unknown_fields"] = list(event.unknown_fields)
    if event.event_hash != _hash(body):
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENT_HASH_MISMATCH")


def validate_read_event_log(cursor: ReadCursor, events: tuple[ReadEvent, ...]) -> None:
    validate_read_cursor(cursor)
    if not isinstance(events, tuple):
        raise MetaReadEventLogHold("HOLD_SA2_3_EVENTS_TUPLE_REQUIRED")
    if tuple(event.sequence for event in events) != tuple(range(1, len(events) + 1)):
        raise MetaReadEventLogHold("HOLD_SA2_3_NON_MONOTONIC_SEQUENCE")
    seen = set()
    for event in events:
        validate_read_event(event)
        if event.platform != cursor.platform or event.external_id != cursor.external_id:
            raise MetaReadEventLogHold("HOLD_SA2_3_STREAM_IDENTITY_MISMATCH")
        if event.normalized_record_fingerprint in seen:
            raise MetaReadEventLogHold("HOLD_SA2_3_DUPLICATE_EVENT_PERSISTED")
        seen.add(event.normalized_record_fingerprint)
    if cursor.accepted_count != len(events):
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_EVENT_COUNT_MISMATCH")
    expected_last = events[-1].event_id if events else EMPTY_EVENT_ID
    if cursor.last_event_id != expected_last:
        raise MetaReadEventLogHold("HOLD_SA2_3_CURSOR_LAST_EVENT_MISMATCH")


def ingest_normalized_record(cursor: ReadCursor, events: tuple[ReadEvent, ...],
                             record: NormalizedReadRecord) -> IngestResult:
    validate_read_event_log(cursor, events)
    fingerprint = normalized_record_fingerprint(record)
    if record.platform != cursor.platform or record.external_id != cursor.external_id:
        raise MetaReadEventLogHold("HOLD_SA2_3_STREAM_IDENTITY_MISMATCH")

    for event in events:
        if event.normalized_record_fingerprint == fingerprint:
            duplicate_cursor = _make_cursor(
                cursor.platform, cursor.external_id, cursor.next_sequence,
                cursor.last_event_id, cursor.accepted_count, cursor.duplicate_count + 1,
            )
            return IngestResult("DUPLICATE_NOOP", duplicate_cursor, events, event.event_id, fingerprint)

    event = _make_event(record, cursor.next_sequence, fingerprint)
    new_events = events + (event,)
    new_cursor = _make_cursor(
        cursor.platform, cursor.external_id, cursor.next_sequence + 1,
        event.event_id, cursor.accepted_count + 1, cursor.duplicate_count,
    )
    validate_read_event_log(new_cursor, new_events)
    return IngestResult("ACCEPTED", new_cursor, new_events, event.event_id, fingerprint)
