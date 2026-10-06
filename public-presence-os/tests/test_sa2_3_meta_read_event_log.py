from __future__ import annotations

from public_presence_os.meta_read_event_log import new_read_cursor, validate_read_cursor
import json
from public_presence_os.meta_read_event_log import ReadCursor, ReadEvent, ingest_normalized_record, validate_read_event_log
from public_presence_os.meta_read_only_transport import NormalizedReadRecord


def test_sa2_3_empty_cursor_contract():
    cursor = new_read_cursor("INSTAGRAM_PROFESSIONAL", "acct-1")
    validate_read_cursor(cursor)
    assert cursor.next_sequence == 1
    assert cursor.accepted_count == 0
    assert cursor.duplicate_count == 0


def test_duplicate_replay_after_serialized_restart_preserves_sequence():
    record = NormalizedReadRecord("INSTAGRAM_PROFILE", "INSTAGRAM_PROFESSIONAL", "acct-1",
                                  "name", "username", "UNKNOWN", (), "a" * 64, ())
    result = ingest_normalized_record(new_read_cursor(record.platform, record.external_id), (), record)
    for replay in range(1, 11):
        cursor = ReadCursor(**json.loads(json.dumps(result.cursor.to_dict())))
        restored = []
        for event in result.events:
            data = json.loads(json.dumps(event.to_dict()))
            data["tasks"] = tuple(data["tasks"])
            data["unknown_fields"] = tuple(data["unknown_fields"])
            restored.append(ReadEvent(**data))
        events = tuple(restored)
        validate_read_event_log(cursor, events)
        result = ingest_normalized_record(cursor, events, record)
        assert result.action == "DUPLICATE_NOOP"
        assert result.cursor.next_sequence == 2
        assert result.cursor.last_event_id == events[0].event_id
        assert result.cursor.accepted_count == 1
        assert result.cursor.duplicate_count == replay
        assert result.events == events
