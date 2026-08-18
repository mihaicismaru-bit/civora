#!/usr/bin/env python3
"""Acceptance tests for explicit re-read crash recovery from durable materialization."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import durable_feedback_snapshot
import metrics_harvest_runtime as runtime
import observed_metrics_collector as collector
import reread_materialization_crash_reconciliation as recovery
import reread_spend_reauthorization as spend
import reread_spend_reclaim_binding as reclaim
from test_authorization_sealed_harvest_recovery import FP1, persist_observation, read_state
from test_reread_provider_outcome_binding import _network_started

OBSERVED_AT = "2026-08-16T10:24:02Z"
CRASH_RECOVERY_AT = "2026-08-16T11:00:01Z"


def _entry(root: Path, ch: dict, jb: dict) -> dict:
    return read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]


def _materialized_then_crashed(root: Path):
    ch, jb, issued, *_ = _network_started(root)
    bundle = persist_observation(root, ch, jb, OBSERVED_AT)
    crashed = receipt.claim_checkpoint_sealed(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now="2026-08-16T11:00:00Z",
    )
    assert crashed["claimed"] is False, crashed
    assert crashed["status"] == "RECOVERY_REQUIRED", crashed
    assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"
    return ch, jb, issued, bundle


def _recover(root: Path, ch: dict, jb: dict, *, auth: str = FP1):
    return recovery.reconcile_materialized_reread_crash(
        root,
        ch,
        jb,
        authorization_fingerprint=auth,
        now=CRASH_RECOVERY_AT,
    )


def test_exact_durable_materialization_recovers_without_provider_read() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, bundle = _materialized_then_crashed(root)
        result = _recover(root, ch, jb)
        assert result["status"] == "RECOVERED_COMPLETED_FROM_DURABLE_MATERIALIZATION", result
        assert result["checkpoint_status"] == "COMPLETED"
        assert result["provider_reread_authorized"] is False
        assert result["provider_network_call_performed"] is False
        entry = _entry(root, ch, jb)
        latest = entry["execution_receipts"][-1]
        assert entry["status"] == latest["status"] == "COMPLETED"
        assert entry["last_result_status"] == "RECOVERED_FROM_DURABLE_MATERIALIZATION"
        evidence = latest[recovery.EVIDENCE_FIELD]
        assert evidence["observation_id"] == bundle["observation_id"]
        assert evidence["materialization_fingerprint_sha256"] == latest["materialization_fingerprint_sha256"]
        assert evidence["provider_network_call_performed_by_recovery"] is False
        readback = result["post_cas_readback"]
        assert readback["verified_from_durable_checkpoint_state"] is True
        assert readback["durable_materialization_reverified_after_cas"] is True
        assert readback["receipt_fingerprint_sha256"] == latest["receipt_fingerprint_sha256"]
        assert readback["recovery_evidence_fingerprint_sha256"] == evidence["evidence_fingerprint_sha256"]
        assert readback["materialization_fingerprint_sha256"] == latest["materialization_fingerprint_sha256"]
        assert readback["post_cas_materialization_fingerprint_sha256"] == latest["materialization_fingerprint_sha256"]
        assert len(readback["readback_fingerprint_sha256"]) == 64
        assert receipt.validate_sealed_entry(entry, FP1)["valid"] is True


def test_post_cas_same_checkpoint_divergence_blocks_success_claim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        original_persist = recovery.runtime.persist_checkpoint_state_cas

        def persist_then_diverge(*args, **kwargs):
            result = original_persist(*args, **kwargs)
            if result.get("persisted") is True:
                state = read_state(root, ch)
                entry = state["entries"][runtime.checkpoint_key(jb)]
                latest = entry["execution_receipts"][-1]
                latest["provider_result_status"] = "CONCURRENT_SAME_CHECKPOINT_MUTATION"
                latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
                state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
                runtime._atomic_write_json(root / runtime.expected_checkpoint_state_path(ch), state)
            return result

        recovery.runtime.persist_checkpoint_state_cas = persist_then_diverge
        try:
            result = _recover(root, ch, jb)
        finally:
            recovery.runtime.persist_checkpoint_state_cas = original_persist
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_POST_CAS_READBACK", result
        assert result["checkpoint_status"] == "COMPLETED"
        assert result["recovery_state_may_be_committed"] is True
        assert result["provider_reread_authorized"] is False
        assert result["provider_network_call_performed"] is False
        assert any("POST_CAS" in code for code in result["hard_blocks"])


def test_post_cas_feedback_snapshot_loss_blocks_success_claim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        original_persist = recovery.runtime.persist_checkpoint_state_cas

        def persist_then_remove_snapshot(*args, **kwargs):
            result = original_persist(*args, **kwargs)
            if result.get("persisted") is True:
                snapshot_path = root / durable_feedback_snapshot.expected_snapshot_path(ch)
                assert snapshot_path.exists()
                snapshot_path.unlink()
            return result

        recovery.runtime.persist_checkpoint_state_cas = persist_then_remove_snapshot
        try:
            result = _recover(root, ch, jb)
        finally:
            recovery.runtime.persist_checkpoint_state_cas = original_persist
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_POST_CAS_READBACK", result
        assert result["checkpoint_status"] == "COMPLETED"
        assert result["recovery_state_may_be_committed"] is True
        assert result["provider_reread_authorized"] is False
        assert result["provider_network_call_performed"] is False
        assert any(
            code.startswith("REREAD_MATERIALIZATION_RECOVERY_POST_CAS_DURABLE_MATERIALIZATION:")
            and "REREAD_RESULT_FEEDBACK_SNAPSHOT_MISSING" in code
            for code in result["hard_blocks"]
        ), result


def test_post_cas_observation_ledger_loss_blocks_success_claim() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        original_persist = recovery.runtime.persist_checkpoint_state_cas

        def persist_then_remove_ledger(*args, **kwargs):
            result = original_persist(*args, **kwargs)
            if result.get("persisted") is True:
                ledger_path = root / collector.expected_observation_store_path(ch)
                assert ledger_path.exists()
                ledger_path.unlink()
            return result

        recovery.runtime.persist_checkpoint_state_cas = persist_then_remove_ledger
        try:
            result = _recover(root, ch, jb)
        finally:
            recovery.runtime.persist_checkpoint_state_cas = original_persist
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_POST_CAS_READBACK", result
        assert result["checkpoint_status"] == "COMPLETED"
        assert result["recovery_state_may_be_committed"] is True
        assert result["provider_reread_authorized"] is False
        assert result["provider_network_call_performed"] is False
        assert any(
            code.startswith("REREAD_MATERIALIZATION_RECOVERY_POST_CAS_DURABLE_MATERIALIZATION:")
            and "REREAD_RESULT_OBSERVATION_STORE_MISSING" in code
            for code in result["hard_blocks"]
        ), result


def test_recovery_is_idempotent_after_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        first = _recover(root, ch, jb)
        assert first["status"] == "RECOVERED_COMPLETED_FROM_DURABLE_MATERIALIZATION"
        second = _recover(root, ch, jb)
        assert second["status"] == "ALREADY_COMPLETED", second
        assert second["provider_network_call_performed"] is False


def test_missing_exact_observation_stays_recovery_required_and_never_infers_no_data() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _network_started(root)
        crashed = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T11:00:00Z"
        )
        assert crashed["status"] == "RECOVERY_REQUIRED", crashed
        result = _recover(root, ch, jb)
        assert result["status"] == "RECOVERY_REQUIRED_NO_DURABLE_MATERIALIZATION", result
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"
        assert result["provider_reread_authorized"] is False
        assert recovery.guards()["completed_no_data_inferred_from_absence"] is False


def test_missing_required_snapshot_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        path = root / durable_feedback_snapshot.expected_snapshot_path(ch)
        assert path.exists()
        path.unlink()
        result = _recover(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE", result
        assert "REREAD_RESULT_FEEDBACK_SNAPSHOT_MISSING" in result["hard_blocks"]
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"


def test_tampered_observation_ledger_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        path = root / collector.expected_observation_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["observations"][0]["metrics"]["impressions"] = 987654
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _recover(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE", result
        assert any("STORE_FINGERPRINT_MISMATCH" in code for code in result["hard_blocks"])
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"


def test_tampered_snapshot_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        path = root / durable_feedback_snapshot.expected_snapshot_path(ch)
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        snapshot["source_observation_count"] = 999
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _recover(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE", result
        assert any("SNAPSHOT_FINGERPRINT_MISMATCH" in code for code in result["hard_blocks"])


def test_authorization_drift_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        result = _recover(root, ch, jb, auth="sha256:" + "b" * 64)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_RECEIPT", result
        assert any("AUTHORIZATION_CONTEXT_CHANGED" in code for code in result["hard_blocks"])
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"


def test_reclaim_lineage_tamper_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        state = read_state(root, ch)
        entry = state["entries"][runtime.checkpoint_key(jb)]
        latest = entry["execution_receipts"][-1]
        provenance = latest[reclaim.PROVENANCE_FIELD]
        provenance["handoff_id"] = "tampered-handoff"
        provenance["provenance_fingerprint_sha256"] = reclaim._provenance_fingerprint(provenance)
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        runtime._atomic_write_json(root / runtime.expected_checkpoint_state_path(ch), state)
        result = _recover(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_LINEAGE", result
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"


def test_spent_record_tamper_blocks_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, *_ = _materialized_then_crashed(root)
        path = root / spend.expected_spend_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        record = store["records"][issued["handoff"]["handoff_id"]]
        record["network_started_at"] = "2026-08-16T10:25:01Z"
        record["record_fingerprint_sha256"] = spend._record_fingerprint(record)
        store["store_fingerprint_sha256"] = spend._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        result = _recover(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_LINEAGE", result
        assert "REREAD_MATERIALIZATION_RECOVERY_SPEND_IDENTITY_MISMATCH:network_started_at" in result["hard_blocks"]


def test_cross_channel_identity_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, *_ = _materialized_then_crashed(root)
        other = json.loads(json.dumps(ch))
        other["channel_id"] = "instagram-valcea-clar"
        result = _recover(root, other, jb)
        assert result["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_IDENTITY", result
        assert "REREAD_MATERIALIZATION_RECOVERY_CHANNEL_ID_MISMATCH" in result["hard_blocks"]


def test_normal_non_reread_recovery_is_not_claimed_by_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        from test_authorization_sealed_harvest_recovery import channel, job
        ch = channel()
        jb = job(ch)
        claimed = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:00Z"
        )
        assert claimed["claimed"] is True
        started = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:01Z"
        )
        assert started["persisted"] is True
        crashed = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z"
        )
        assert crashed["status"] == "RECOVERY_REQUIRED"
        result = _recover(root, ch, jb)
        assert result["status"] == "NOT_EXPLICIT_REREAD_RECOVERY", result
        assert _entry(root, ch, jb)["status"] == "RECOVERY_REQUIRED"


def test_guards_keep_recovery_network_free_secret_free_and_zero_paid() -> None:
    expected = {
        "recovery_requires_explicit_reread_lineage": True,
        "recovery_requires_spent_handoff": True,
        "recovery_requires_network_start_proof": True,
        "recovery_requires_exact_durable_materialization": True,
        "feedback_snapshot_readback_required_when_materialization_requires_it": True,
        "recovery_completion_requires_post_cas_readback": True,
        "post_cas_readback_revalidates_durable_materialization": True,
        "post_cas_materialization_toctou_success_allowed": False,
        "recovery_success_claims_without_post_cas_readback": False,
        "ambiguous_or_missing_evidence_remains_recovery_required": True,
        "completed_no_data_inferred_from_absence": False,
        "provider_reread_authorized_by_recovery": False,
        "provider_network_call_performed_by_recovery": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "predictive_analytics_used": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }
    actual = recovery.guards()
    for key, value in expected.items():
        assert actual.get(key) is value, (key, actual.get(key))


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS reread materialization crash reconciliation acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())