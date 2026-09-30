from dataclasses import replace

import pytest

from public_presence_os.meta_cross_lane_read_coverage import (
    ACTIVE_LANES,
    MetaCrossLaneCoverageHold,
    compile_cross_lane_coverage,
    replay_cross_lane_coverage,
    validate_cross_lane_coverage_snapshot,
)
from public_presence_os.meta_read_event_log import ingest_normalized_record, new_read_cursor
from public_presence_os.meta_read_observability import compile_read_observability_snapshot
from public_presence_os.meta_read_only_transport import NormalizedReadRecord, UNKNOWN

IDS = {
    "FACEBOOK_PAGE": "2816314015107071",
    "INSTAGRAM_PROFESSIONAL": "17841429701593250",
    "THREADS": "28391623420464631",
}


def _empty(platform):
    return compile_read_observability_snapshot(new_read_cursor(platform, IDS[platform]), ())


def _observed_ig():
    record = NormalizedReadRecord(
        operation="INSTAGRAM_PROFILE",
        platform="INSTAGRAM_PROFESSIONAL",
        external_id=IDS["INSTAGRAM_PROFESSIONAL"],
        name="Profile",
        username=UNKNOWN,
        linked_instagram_id=UNKNOWN,
        tasks=(),
        source_response_sha256="b" * 64,
        unknown_fields=("username",),
    )
    cursor = new_read_cursor("INSTAGRAM_PROFESSIONAL", IDS["INSTAGRAM_PROFESSIONAL"])
    result = ingest_normalized_record(cursor, (), record)
    return compile_read_observability_snapshot(result.cursor, result.events)


def test_sa2_5_order_invariant_and_exact_replay_is_noop():
    fb, ig, th = (_empty(lane) for lane in ACTIVE_LANES)
    first = compile_cross_lane_coverage((fb, ig, th))
    reordered = compile_cross_lane_coverage((th, ig, fb, ig))
    assert reordered.coverage_hash == first.coverage_hash
    assert reordered.coverage_id == first.coverage_id

    replay = replay_cross_lane_coverage(first, (ig, th, fb, ig))
    assert replay.action == "DUPLICATE_COVERAGE_NOOP"
    assert replay.snapshot == first


def test_sa2_5_all_active_lanes_present_unknown_preserved():
    snapshots = tuple(_empty(lane) for lane in ACTIVE_LANES)
    coverage = compile_cross_lane_coverage(snapshots)
    assert coverage.present_lanes == ACTIVE_LANES
    assert coverage.missing_lanes == ()
    assert coverage.coverage_state == "ALL_ACTIVE_LANES_PRESENT"
    assert coverage.observed_lane_count == 0
    assert all(count == len(coverage.external_metrics) for _, count in coverage.lane_unknown_metric_counts)
    assert all(value == UNKNOWN for _, value in coverage.external_metrics)
    assert coverage.kill_switch_must_remain_engaged is True


def test_sa2_5_partial_and_observed_lane_coverage():
    observed = _observed_ig()
    coverage = compile_cross_lane_coverage((observed,))
    assert coverage.present_lanes == ("INSTAGRAM_PROFESSIONAL",)
    assert coverage.missing_lanes == ("FACEBOOK_PAGE", "THREADS")
    assert coverage.coverage_state == "PARTIAL_ACTIVE_LANE_COVERAGE"
    assert coverage.observed_lane_count == 1


def test_sa2_5_conflicting_same_lane_replay_fails_closed():
    empty = _empty("INSTAGRAM_PROFESSIONAL")
    observed = _observed_ig()
    with pytest.raises(MetaCrossLaneCoverageHold) as exc:
        compile_cross_lane_coverage((empty, observed))
    assert exc.value.reason == "HOLD_SA2_5_CONFLICTING_LANE_REPLAY"


def test_sa2_5_aggregate_cannot_invent_external_metric():
    coverage = compile_cross_lane_coverage(tuple(_empty(lane) for lane in ACTIVE_LANES))
    changed = tuple(
        (name, "0" if name == "REACH" else value)
        for name, value in coverage.external_metrics
    )
    with pytest.raises(MetaCrossLaneCoverageHold):
        validate_cross_lane_coverage_snapshot(replace(coverage, external_metrics=changed))
