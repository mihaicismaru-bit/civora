from __future__ import annotations

from public_presence_os.meta_read_event_log import new_read_cursor, validate_read_cursor


def test_sa2_3_empty_cursor_contract():
    cursor = new_read_cursor("INSTAGRAM_PROFESSIONAL", "acct-1")
    validate_read_cursor(cursor)
    assert cursor.next_sequence == 1
    assert cursor.accepted_count == 0
    assert cursor.duplicate_count == 0
