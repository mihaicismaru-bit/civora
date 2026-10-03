from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import re

from .meta_read_observability import (
    EXTERNAL_METRICS,
    ReadObservabilitySnapshot,
    validate_read_observability_snapshot,
)
from .meta_read_only_transport import UNKNOWN

MODEL_VERSION = "PPOS_META_CROSS_LANE_READ_COVERAGE_V1"
ENGINE_VERSION = "ppos-meta-cross-lane-read-coverage-v1.0.0"
HEX64 = re.compile(r"^[0-9a-f]{64}$")

ACTIVE_LANES = (
    "FACEBOOK_PAGE",
    "INSTAGRAM_PROFESSIONAL",
    "THREADS",
)


class MetaCrossLaneCoverageHold(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class CrossLaneCoverageSnapshot:
    coverage_id: str
    coverage_hash: str
    model_version: str
    engine_version: str
    active_lanes: tuple[str, ...]
    present_lanes: tuple[str, ...]
    missing_lanes: tuple[str, ...]
    lane_snapshot_ids: tuple[tuple[str, str], ...]
    lane_snapshot_hashes: tuple[tuple[str, str], ...]
    lane_coverage_states: tuple[tuple[str, str], ...]
    lane_accepted_event_counts: tuple[tuple[str, int], ...]
    lane_duplicate_replay_counts: tuple[tuple[str, int], ...]
    lane_unknown_metric_counts: tuple[tuple[str, int], ...]
    observed_lane_count: int
    external_metrics: tuple[tuple[str, str], ...]
    external_metric_state: str
    coverage_state: str
    state: str = "CROSS_LANE_READ_COVERAGE_COMPILED"
    network_execution_authority: bool = False
    external_write_authority: bool = False
    publish_authority: bool = False
    deploy_authority: bool = False
    kill_switch_must_remain_engaged: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class CoverageReplayResult:
    action: str
    snapshot: CrossLaneCoverageSnapshot


def _canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(value) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _coverage_body(snapshot: CrossLaneCoverageSnapshot) -> dict:
    body = snapshot.to_dict()
    body.pop("coverage_id")
    body.pop("coverage_hash")
    return body


def _keyed_tuple_keys(value: tuple[tuple[str, object], ...]) -> tuple[str, ...]:
    return tuple(key for key, _ in value)


def _expected_coverage_state(
    present_lanes: tuple[str, ...],
    lane_coverage_states: tuple[tuple[str, str], ...],
) -> str:
    if not present_lanes:
        return "NO_ACTIVE_LANE_SNAPSHOTS"
    if present_lanes != ACTIVE_LANES:
        return "PARTIAL_ACTIVE_LANE_COVERAGE"
    if all(state == "READ_EVENT_OBSERVED" for _, state in lane_coverage_states):
        return "ALL_ACTIVE_LANES_OBSERVED"
    return "ALL_ACTIVE_LANES_PRESENT"


def validate_cross_lane_coverage_snapshot(snapshot: CrossLaneCoverageSnapshot) -> None:
    if not isinstance(snapshot, CrossLaneCoverageSnapshot):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_COVERAGE_TYPE")
    if (snapshot.model_version, snapshot.engine_version) != (MODEL_VERSION, ENGINE_VERSION):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_VERSION_DRIFT")
    if snapshot.active_lanes != ACTIVE_LANES:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_ACTIVE_LANE_DRIFT")

    expected_present = tuple(lane for lane in ACTIVE_LANES if lane in set(snapshot.present_lanes))
    if snapshot.present_lanes != expected_present or len(set(snapshot.present_lanes)) != len(snapshot.present_lanes):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_PRESENT_LANES_NOT_CANONICAL")
    expected_missing = tuple(lane for lane in ACTIVE_LANES if lane not in set(snapshot.present_lanes))
    if snapshot.missing_lanes != expected_missing:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_MISSING_LANES_MISMATCH")

    keyed_fields = (
        snapshot.lane_snapshot_ids,
        snapshot.lane_snapshot_hashes,
        snapshot.lane_coverage_states,
        snapshot.lane_accepted_event_counts,
        snapshot.lane_duplicate_replay_counts,
        snapshot.lane_unknown_metric_counts,
    )
    if any(_keyed_tuple_keys(field) != snapshot.present_lanes for field in keyed_fields):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_LANE_KEY_ALIGNMENT")

    for _, snapshot_id in snapshot.lane_snapshot_ids:
        if not isinstance(snapshot_id, str) or not snapshot_id.startswith("mros_"):
            raise MetaCrossLaneCoverageHold("HOLD_SA2_5_SOURCE_SNAPSHOT_ID")
    for _, snapshot_hash in snapshot.lane_snapshot_hashes:
        if not isinstance(snapshot_hash, str) or not HEX64.fullmatch(snapshot_hash):
            raise MetaCrossLaneCoverageHold("HOLD_SA2_5_SOURCE_SNAPSHOT_HASH")
    for _, state in snapshot.lane_coverage_states:
        if state not in {"NO_ACCEPTED_EVENTS", "READ_EVENT_OBSERVED"}:
            raise MetaCrossLaneCoverageHold("HOLD_SA2_5_LANE_COVERAGE_STATE")
    if any(count < 0 for _, count in snapshot.lane_accepted_event_counts):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_NEGATIVE_ACCEPTED_COUNT")
    if any(count < 0 for _, count in snapshot.lane_duplicate_replay_counts):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_NEGATIVE_DUPLICATE_COUNT")
    if any(count != len(EXTERNAL_METRICS) for _, count in snapshot.lane_unknown_metric_counts):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_UNKNOWN_METRIC_COUNT_DRIFT")

    expected_observed = sum(
        1 for _, state in snapshot.lane_coverage_states if state == "READ_EVENT_OBSERVED"
    )
    if snapshot.observed_lane_count != expected_observed:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_OBSERVED_LANE_COUNT")

    if tuple(name for name, _ in snapshot.external_metrics) != EXTERNAL_METRICS:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_EXTERNAL_METRIC_SET_DRIFT")
    if any(value != UNKNOWN for _, value in snapshot.external_metrics):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_EXTERNAL_METRIC_NOT_UNKNOWN")
    if snapshot.external_metric_state != "UNKNOWN_WHERE_UNAVAILABLE":
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_EXTERNAL_METRIC_STATE")

    expected_state = _expected_coverage_state(snapshot.present_lanes, snapshot.lane_coverage_states)
    if snapshot.coverage_state != expected_state:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_COVERAGE_STATE")

    if snapshot.state != "CROSS_LANE_READ_COVERAGE_COMPILED":
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_STATE")
    if any((
        snapshot.network_execution_authority,
        snapshot.external_write_authority,
        snapshot.publish_authority,
        snapshot.deploy_authority,
    )):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_EXTERNAL_AUTHORITY_FORBIDDEN")
    if not snapshot.kill_switch_must_remain_engaged:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_KILL_SWITCH_DRIFT")

    expected_hash = _hash(_coverage_body(snapshot))
    if snapshot.coverage_hash != expected_hash or not HEX64.fullmatch(snapshot.coverage_hash):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_COVERAGE_HASH_MISMATCH")
    if snapshot.coverage_id != "mrcc_" + expected_hash[:24]:
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_COVERAGE_ID_MISMATCH")


def compile_cross_lane_coverage(
    snapshots: tuple[ReadObservabilitySnapshot, ...],
) -> CrossLaneCoverageSnapshot:
    if not isinstance(snapshots, tuple):
        raise MetaCrossLaneCoverageHold("HOLD_SA2_5_SNAPSHOTS_TUPLE_REQUIRED")

    by_lane: dict[str, ReadObservabilitySnapshot] = {}
    for snapshot in snapshots:
        validate_read_observability_snapshot(snapshot)
        if snapshot.platform not in ACTIVE_LANES:
            raise MetaCrossLaneCoverageHold("HOLD_SA2_5_PLATFORM_NOT_ACTIVE")
        existing = by_lane.get(snapshot.platform)
        if existing is not None:
            if existing.snapshot_hash == snapshot.snapshot_hash:
                continue
            raise MetaCrossLaneCoverageHold("HOLD_SA2_5_CONFLICTING_LANE_REPLAY")
        by_lane[snapshot.platform] = snapshot

    present_lanes = tuple(lane for lane in ACTIVE_LANES if lane in by_lane)
    missing_lanes = tuple(lane for lane in ACTIVE_LANES if lane not in by_lane)

    lane_snapshot_ids = tuple((lane, by_lane[lane].snapshot_id) for lane in present_lanes)
    lane_snapshot_hashes = tuple((lane, by_lane[lane].snapshot_hash) for lane in present_lanes)
    lane_coverage_states = tuple((lane, by_lane[lane].coverage_state) for lane in present_lanes)
    lane_accepted_event_counts = tuple(
        (lane, by_lane[lane].accepted_event_count) for lane in present_lanes
    )
    lane_duplicate_replay_counts = tuple(
        (lane, by_lane[lane].duplicate_replay_count) for lane in present_lanes
    )
    lane_unknown_metric_counts = tuple(
        (
            lane,
            sum(1 for _, value in by_lane[lane].external_metrics if value == UNKNOWN),
        )
        for lane in present_lanes
    )
    observed_lane_count = sum(
        1 for _, state in lane_coverage_states if state == "READ_EVENT_OBSERVED"
    )

    body = {
        "model_version": MODEL_VERSION,
        "engine_version": ENGINE_VERSION,
        "active_lanes": ACTIVE_LANES,
        "present_lanes": present_lanes,
        "missing_lanes": missing_lanes,
        "lane_snapshot_ids": lane_snapshot_ids,
        "lane_snapshot_hashes": lane_snapshot_hashes,
        "lane_coverage_states": lane_coverage_states,
        "lane_accepted_event_counts": lane_accepted_event_counts,
        "lane_duplicate_replay_counts": lane_duplicate_replay_counts,
        "lane_unknown_metric_counts": lane_unknown_metric_counts,
        "observed_lane_count": observed_lane_count,
        "external_metrics": tuple((metric, UNKNOWN) for metric in EXTERNAL_METRICS),
        "external_metric_state": "UNKNOWN_WHERE_UNAVAILABLE",
        "coverage_state": _expected_coverage_state(present_lanes, lane_coverage_states),
        "state": "CROSS_LANE_READ_COVERAGE_COMPILED",
        "network_execution_authority": False,
        "external_write_authority": False,
        "publish_authority": False,
        "deploy_authority": False,
        "kill_switch_must_remain_engaged": True,
    }
    coverage_hash = _hash(body)
    coverage = CrossLaneCoverageSnapshot(
        coverage_id="mrcc_" + coverage_hash[:24],
        coverage_hash=coverage_hash,
        **body,
    )
    validate_cross_lane_coverage_snapshot(coverage)
    return coverage


def replay_cross_lane_coverage(
    previous: CrossLaneCoverageSnapshot,
    snapshots: tuple[ReadObservabilitySnapshot, ...],
) -> CoverageReplayResult:
    validate_cross_lane_coverage_snapshot(previous)
    candidate = compile_cross_lane_coverage(snapshots)
    if candidate.coverage_hash == previous.coverage_hash:
        return CoverageReplayResult("DUPLICATE_COVERAGE_NOOP", previous)
    return CoverageReplayResult("COVERAGE_RECOMPILED", candidate)
