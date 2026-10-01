from hashlib import sha256
import json

import pytest

from public_presence_os.meta_cross_lane_read_coverage import (
    ACTIVE_LANES,
    compile_cross_lane_coverage,
)
from public_presence_os.meta_read_event_log import new_read_cursor
from public_presence_os.meta_read_observability import compile_read_observability_snapshot
from public_presence_os.meta_snapshot_generation import (
    MetaSnapshotGenerationHold,
    accept_next_generation,
    decode_generation_record,
    encode_generation_record,
    require_minimum_generation,
)

IDS = {
    "FACEBOOK_PAGE": "1000000000000001",
    "INSTAGRAM_PROFESSIONAL": "2000000000000002",
    "THREADS": "3000000000000003",
}


def _read_snapshot(platform="FACEBOOK_PAGE"):
    return compile_read_observability_snapshot(
        new_read_cursor(platform, IDS[platform]),
        (),
    )


def _coverage_snapshot():
    return compile_cross_lane_coverage(
        tuple(_read_snapshot(lane) for lane in ACTIVE_LANES)
    )


def _record(snapshot, generation, previous=None):
    return decode_generation_record(
        encode_generation_record(snapshot, generation, previous)
    )


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_sa2_7_initial_generation_roundtrips():
    record = _record(_read_snapshot(), 1)
    assert record.generation == 1
    assert record.previous_generation is None
    assert record.previous_record_sha256 is None


def test_sa2_7_exact_next_generation_is_accepted():
    first = _record(_coverage_snapshot(), 1)
    second = _record(_coverage_snapshot(), 2, first)
    accepted = accept_next_generation(first, second)
    assert accepted.generation == 2
    assert accepted.previous_record_sha256 == first.record_sha256


def test_sa2_7_stale_candidate_is_rejected():
    first = _record(_read_snapshot(), 1)
    with pytest.raises(MetaSnapshotGenerationHold) as exc:
        accept_next_generation(first, first)
    assert exc.value.reason == "HOLD_SA2_7_STALE_PERSISTED_STATE"


def test_sa2_7_generation_gap_is_rejected():
    first = _record(_coverage_snapshot(), 1)
    second = _record(_coverage_snapshot(), 2, first)
    third = _record(_coverage_snapshot(), 3, second)
    with pytest.raises(MetaSnapshotGenerationHold) as exc:
        accept_next_generation(first, third)
    assert exc.value.reason == "HOLD_SA2_7_GENERATION_GAP"


def test_sa2_7_wrong_predecessor_hash_is_rejected():
    first = _record(_read_snapshot("FACEBOOK_PAGE"), 1)
    other_first = _record(_read_snapshot("THREADS"), 1)
    candidate = _record(_read_snapshot("FACEBOOK_PAGE"), 2, other_first)
    with pytest.raises(MetaSnapshotGenerationHold) as exc:
        accept_next_generation(first, candidate)
    assert exc.value.reason == "HOLD_SA2_7_PREDECESSOR_HASH_MISMATCH"


def test_sa2_7_minimum_generation_rejects_stale_state():
    first = _record(_read_snapshot(), 1)
    with pytest.raises(MetaSnapshotGenerationHold) as exc:
        require_minimum_generation(first, 2)
    assert exc.value.reason == "HOLD_SA2_7_STALE_PERSISTED_STATE"


def test_sa2_7_authority_widening_fails_even_after_rehash():
    serialized = encode_generation_record(_coverage_snapshot(), 1)
    envelope = json.loads(serialized)
    envelope["publish_authority"] = True
    body = dict(envelope)
    body.pop("record_sha256")
    envelope["record_sha256"] = sha256(
        _canonical(body).encode("utf-8")
    ).hexdigest()

    with pytest.raises(MetaSnapshotGenerationHold) as exc:
        decode_generation_record(_canonical(envelope))
    assert exc.value.reason == "HOLD_SA2_7_EXTERNAL_AUTHORITY_FORBIDDEN"
