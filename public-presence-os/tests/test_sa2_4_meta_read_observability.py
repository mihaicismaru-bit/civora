from dataclasses import replace

import pytest

from public_presence_os.meta_read_event_log import ingest_normalized_record, new_read_cursor
from public_presence_os.meta_read_observability import (
    MetaReadObservabilityHold,
    compile_read_observability_snapshot,
    validate_read_observability_snapshot,
)
from public_presence_os.meta_read_only_transport import NormalizedReadRecord, UNKNOWN

IG_ID = "17841429701593250"


def _record(username=UNKNOWN):
    return NormalizedReadRecord(
        operation="INSTAGRAM_PROFILE",
        platform="INSTAGRAM_PROFESSIONAL",
        external_id=IG_ID,
        name="Profile",
        username=username,
        linked_instagram_id=UNKNOWN,
        tasks=(),
        source_response_sha256="a" * 64,
        unknown_fields=("username",) if username == UNKNOWN else (),
    )


def test_sa2_4_empty_snapshot():
    snapshot = compile_read_observability_snapshot(
        new_read_cursor("INSTAGRAM_PROFESSIONAL", IG_ID), ()
    )
    assert snapshot.latest_sequence == UNKNOWN
    assert snapshot.coverage_state == "NO_ACCEPTED_EVENTS"
    assert all(value == UNKNOWN for _, value in snapshot.external_metrics)
    assert snapshot.kill_switch_must_remain_engaged is True


def test_sa2_4_observed_and_duplicate_counts():
    cursor = new_read_cursor("INSTAGRAM_PROFESSIONAL", IG_ID)
    first = ingest_normalized_record(cursor, (), _record())
    replay = ingest_normalized_record(first.cursor, first.events, _record())
    snapshot = compile_read_observability_snapshot(replay.cursor, replay.events)
    assert snapshot.accepted_event_count == 1
    assert snapshot.persisted_event_count == 1
    assert snapshot.duplicate_replay_count == 1
    assert snapshot.latest_username == UNKNOWN
    assert snapshot.latest_unknown_fields == ("username",)


def test_sa2_4_identity_drift_fails_closed():
    with pytest.raises(MetaReadObservabilityHold):
        compile_read_observability_snapshot(
            new_read_cursor("INSTAGRAM_PROFESSIONAL", "wrong-id"), ()
        )


def test_sa2_4_external_metric_cannot_be_invented():
    snapshot = compile_read_observability_snapshot(
        new_read_cursor("INSTAGRAM_PROFESSIONAL", IG_ID), ()
    )
    changed = tuple(
        (name, "0" if name == "REACH" else value)
        for name, value in snapshot.external_metrics
    )
    with pytest.raises(MetaReadObservabilityHold):
        validate_read_observability_snapshot(replace(snapshot, external_metrics=changed))
