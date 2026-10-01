from dataclasses import replace
from hashlib import sha256
import json

import pytest

from public_presence_os.meta_cross_lane_read_coverage import (
    ACTIVE_LANES,
    compile_cross_lane_coverage,
)
from public_presence_os.meta_read_event_log import new_read_cursor
from public_presence_os.meta_read_observability import compile_read_observability_snapshot
from public_presence_os.meta_snapshot_persistence import (
    MetaSnapshotPersistenceHold,
    decode_snapshot,
    encode_snapshot,
    load_snapshot,
    persist_snapshot,
)

IDS = {
    "FACEBOOK_PAGE": "2816314015107071",
    "INSTAGRAM_PROFESSIONAL": "17841429701593250",
    "THREADS": "28391623420464631",
}


def _read_snapshot(platform="FACEBOOK_PAGE"):
    return compile_read_observability_snapshot(
        new_read_cursor(platform, IDS[platform]),
        (),
    )


def _coverage_snapshot():
    snapshots = tuple(_read_snapshot(lane) for lane in ACTIVE_LANES)
    return compile_cross_lane_coverage(snapshots)


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def test_sa2_6_read_snapshot_roundtrip_is_deterministic():
    snapshot = _read_snapshot()
    first = encode_snapshot(snapshot)
    second = encode_snapshot(snapshot)
    assert first == second
    assert decode_snapshot(first) == snapshot


def test_sa2_6_cross_lane_roundtrip_preserves_zero_authority():
    snapshot = _coverage_snapshot()
    restored = decode_snapshot(encode_snapshot(snapshot))
    assert restored == snapshot
    assert restored.network_execution_authority is False
    assert restored.external_write_authority is False
    assert restored.publish_authority is False
    assert restored.deploy_authority is False
    assert restored.kill_switch_must_remain_engaged is True


def test_sa2_6_atomic_local_persist_reload_is_byte_stable(tmp_path):
    snapshot = _coverage_snapshot()
    target = tmp_path / "coverage.snapshot.json"

    checksum_one = persist_snapshot(target, snapshot)
    bytes_one = target.read_bytes()
    checksum_two = persist_snapshot(target, snapshot)
    bytes_two = target.read_bytes()

    assert bytes_one == bytes_two
    assert checksum_one == checksum_two == sha256(bytes_one).hexdigest()
    assert load_snapshot(target) == snapshot
    assert not tuple(tmp_path.glob("*.tmp"))


def test_sa2_6_corrupted_envelope_checksum_fails_closed():
    envelope = json.loads(encode_snapshot(_read_snapshot()))
    envelope["payload"]["latest_name"] = "CORRUPTED"

    with pytest.raises(MetaSnapshotPersistenceHold) as exc:
        decode_snapshot(_canonical(envelope))
    assert exc.value.reason == "HOLD_SA2_6_CHECKSUM_MISMATCH"


def test_sa2_6_rechecks_inner_snapshot_hash_after_valid_envelope_checksum():
    envelope = json.loads(encode_snapshot(_read_snapshot()))
    envelope["payload"]["latest_name"] = "CORRUPTED"
    body = dict(envelope)
    body.pop("checksum_sha256")
    envelope["checksum_sha256"] = sha256(_canonical(body).encode("utf-8")).hexdigest()

    with pytest.raises(MetaSnapshotPersistenceHold):
        decode_snapshot(_canonical(envelope))


def test_sa2_6_rejects_authority_widening_even_with_recomputed_checksum():
    envelope = json.loads(encode_snapshot(_coverage_snapshot()))
    envelope["publish_authority"] = True
    body = dict(envelope)
    body.pop("checksum_sha256")
    envelope["checksum_sha256"] = sha256(_canonical(body).encode("utf-8")).hexdigest()

    with pytest.raises(MetaSnapshotPersistenceHold) as exc:
        decode_snapshot(_canonical(envelope))
    assert exc.value.reason == "HOLD_SA2_6_EXTERNAL_AUTHORITY_FORBIDDEN"


def test_sa2_6_rejects_inner_snapshot_authority_widening():
    snapshot = _coverage_snapshot()
    with pytest.raises(Exception):
        encode_snapshot(replace(snapshot, publish_authority=True))
