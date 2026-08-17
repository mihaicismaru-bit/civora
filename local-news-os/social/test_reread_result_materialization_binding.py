#!/usr/bin/env python3
"""Acceptance tests for durable provider re-read result materialization binding."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import durable_feedback_snapshot
import metrics_harvest_runtime as runtime
import observed_metrics_collector as collector
import reread_provider_outcome_binding as outcome
import reread_result_materialization_binding as binding
from test_authorization_sealed_harvest_recovery import FP1, channel, job, persist_observation, read_state
from test_reread_provider_outcome_binding import _network_started

binding.install()
NOW = "2026-08-16T10:24:02Z"


def _latest(root: Path, ch: dict, jb: dict) -> dict:
    state = read_state(root, ch)
    return state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]


def _complete(root: Path, ch: dict, jb: dict, source_bundle_fp: str) -> dict:
    return receipt.transition_sealed(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now=NOW,
        status="COMPLETED",
        last_result_status="COLLECTED_AND_MATERIALIZED",
        materialization_fingerprint_sha256=source_bundle_fp,
    )


def _materialize_exact(root: Path, ch: dict, jb: dict) -> tuple[dict, str]:
    bundle = persist_observation(root, ch, jb, NOW)
    return bundle, receipt._digest(bundle)


def test_arbitrary_valid_hash_without_durable_observation_cannot_complete() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        blocked = _complete(root, ch, jb, "a" * 64)
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESULT_MATERIALIZATION", blocked
        assert "REREAD_RESULT_OBSERVATION_STORE_MISSING" in blocked["hard_blocks"]
        assert _latest(root, ch, jb)["status"] == "NETWORK_CALL_STARTED"


def test_completed_reread_uses_readback_fingerprint_not_source_bundle_hash() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        bundle, source_fp = _materialize_exact(root, ch, jb)
        transitioned = _complete(root, ch, jb, source_fp)
        assert transitioned["persisted"] is True, transitioned
        assert transitioned["reread_result_materialization_bound"] is True
        durable_fp = transitioned["durable_materialization_fingerprint_sha256"]
        assert durable_fp != source_fp
        latest = _latest(root, ch, jb)
        bound = latest[outcome.OUTCOME_FIELD]
        assert bound["checkpoint_status"] == "COMPLETED"
        assert bound["materialization_fingerprint_sha256"] == durable_fp
        checked = binding.validate_durable_materialization_binding(
            root, ch, jb, now=NOW, materialization_fingerprint_sha256=durable_fp
        )
        assert checked["valid"] is True, checked
        proof = checked["proof"]
        store = json.loads((root / collector.expected_observation_store_path(ch)).read_text(encoding="utf-8"))
        assert proof["observation_store_fingerprint_sha256"] == store["store_fingerprint_sha256"]
        assert proof["observation_id"] == bundle["observation_id"]
        assert proof["snapshot_present"] is True
        assert proof["snapshot_required"] is True
        assert proof["zero_paid_dependency"] is True


def test_tampered_observation_ledger_blocks_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        _, source_fp = _materialize_exact(root, ch, jb)
        path = root / collector.expected_observation_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["observations"][0]["metrics"]["impressions"] = 999999
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        blocked = _complete(root, ch, jb, source_fp)
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESULT_MATERIALIZATION"
        assert any("STORE_FINGERPRINT_MISMATCH" in value for value in blocked["hard_blocks"])
        assert _latest(root, ch, jb)["status"] == "NETWORK_CALL_STARTED"


def test_missing_required_feedback_snapshot_blocks_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        _, source_fp = _materialize_exact(root, ch, jb)
        snapshot_path = root / durable_feedback_snapshot.expected_snapshot_path(ch)
        assert snapshot_path.exists()
        snapshot_path.unlink()
        blocked = _complete(root, ch, jb, source_fp)
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESULT_MATERIALIZATION"
        assert "REREAD_RESULT_FEEDBACK_SNAPSHOT_MISSING" in blocked["hard_blocks"]


def test_tampered_feedback_snapshot_blocks_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        _, source_fp = _materialize_exact(root, ch, jb)
        path = root / durable_feedback_snapshot.expected_snapshot_path(ch)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["source_observation_count"] = 999
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        blocked = _complete(root, ch, jb, source_fp)
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESULT_MATERIALIZATION"
        assert any("SNAPSHOT_FINGERPRINT_MISMATCH" in value for value in blocked["hard_blocks"])


def test_completed_no_data_reread_keeps_existing_outcome_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now=NOW,
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert transitioned["persisted"] is True, transitioned
        latest = _latest(root, ch, jb)
        assert latest[outcome.OUTCOME_FIELD]["checkpoint_status"] == "COMPLETED_NO_DATA"
        assert latest[outcome.OUTCOME_FIELD]["materialization_fingerprint_sha256"] is None


def test_normal_non_reread_transition_is_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        claimed = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:00Z"
        )
        assert claimed["claimed"] is True, claimed
        started = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:01Z"
        )
        assert started["persisted"] is True, started
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T09:00:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert transitioned["persisted"] is True, transitioned
        assert outcome.OUTCOME_FIELD not in _latest(root, ch, jb)


def test_binding_guards_are_secret_free_advisory_and_zero_paid() -> None:
    guards = binding.materialization_guards()
    required = {
        "completed_reread_requires_exact_durable_observation": True,
        "observation_store_readback_validated": True,
        "feedback_snapshot_readback_validated_when_present": True,
        "feedback_snapshot_required_when_durable_store_yields_usable_feedback": True,
        "snapshot_sources_must_exist_in_observation_store": True,
        "persisted_materialization_fingerprint_derived_from_readback": True,
        "caller_bundle_fingerprint_not_trusted_as_persistence_proof": True,
        "provider_network_call_performed_by_binding": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required.items():
        assert guards.get(key) is expected, (key, guards.get(key))


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS reread result materialization binding acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
