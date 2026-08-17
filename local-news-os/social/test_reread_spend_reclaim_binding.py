#!/usr/bin/env python3
"""Acceptance tests for binding a released re-read reservation to its reclaim attempt."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import reread_spend_reauthorization as spend
import reread_spend_reservation_recovery as recovery
import reread_spend_reclaim_binding as reclaim
from test_reread_attempt_provenance_binding import _write_state
from test_reread_spend_reservation_recovery import _reserved_only, _spend_store
from test_authorization_sealed_harvest_recovery import FP1, channel, job, read_state

spend.install()
recovery.install()
reclaim.install()


def _released_then_reclaimed(root: Path, *, reclaim_time: str = "2026-08-16T10:24:00Z"):
    ch, jb, issued, consumed, first_claim, reserved = _reserved_only(root, lease_minutes=1)
    second = receipt.claim_checkpoint_sealed(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now=reclaim_time,
        lease_minutes=1,
    )
    assert second["claimed"] is True, second
    assert second["reread_reservation_reconciled"] == "RELEASED_NO_NETWORK_START", second
    assert second["reread_reservation_reclaim_provenance_bound"] is True, second
    return ch, jb, issued, consumed, first_claim, reserved, second


def _latest(root: Path, ch: dict, jb: dict) -> dict:
    return read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]


def test_safe_release_is_bound_to_exact_reclaim_attempt_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, first_claim, reserved, second = _released_then_reclaimed(root)
        state = read_state(root, ch)
        receipts = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"]
        release_receipt = receipts[-2]
        current = receipts[-1]
        evidence = release_receipt[recovery.EVIDENCE_FIELD]
        provenance = current[reclaim.PROVENANCE_FIELD]

        assert provenance["action"] == reclaim.ACTION
        assert provenance["handoff_id"] == issued["handoff"]["handoff_id"]
        assert provenance["released_spend_id"] == reserved["record"]["spend_id"]
        assert provenance["source_release_recovery_id"] == evidence["recovery_id"]
        assert provenance["source_release_evidence_fingerprint_sha256"] == evidence["evidence_fingerprint_sha256"]
        assert provenance["released_execution_id"] == first_claim["entry"]["execution_receipts"][-1]["execution_id"]
        assert provenance["reclaim_execution_id"] == current["execution_id"]
        assert provenance["released_attempt"] < provenance["reclaim_attempt"]
        assert second["reread_reclaim_binding_id"] == provenance["reclaim_binding_id"]
        assert receipt.validate_sealed_entry(state["entries"][runtime.checkpoint_key(jb)], FP1)["valid"] is True

        started = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert started["persisted"] is True, started
        assert started["reread_reservation_reclaim_provenance_verified"] is True, started
        record = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert record["status"] == "SPENT", record
        assert record["provider_reads_spent"] == 1


def test_missing_reclaim_binding_blocks_network_and_does_not_reserve_spend() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, _ = _released_then_reclaimed(root)
        state = read_state(root, ch)
        latest = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]
        latest.pop(reclaim.PROVENANCE_FIELD, None)
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", blocked
        assert "REREAD_RECLAIM_PROVENANCE_REQUIRED_BEFORE_NETWORK" in blocked["hard_blocks"]
        assert issued["handoff"]["handoff_id"] not in _spend_store(root, ch)["records"]
        assert _latest(root, ch, jb)["network_started_at"] is None


def test_release_evidence_tamper_is_fail_closed_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, _ = _released_then_reclaimed(root)
        state = read_state(root, ch)
        receipts = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"]
        source = receipts[-2]
        evidence = source[recovery.EVIDENCE_FIELD]
        evidence["action"] = "FORGED_RELEASE"
        evidence["evidence_fingerprint_sha256"] = recovery._evidence_fingerprint(evidence)
        source["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(source)
        _write_state(root, ch, state)

        blocked = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", blocked
        assert "REREAD_RECLAIM_RELEASE_ACTION_INVALID" in blocked["hard_blocks"]
        assert issued["handoff"]["handoff_id"] not in _spend_store(root, ch)["records"]


def test_reclaim_provenance_tamper_is_fail_closed_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, _ = _released_then_reclaimed(root)
        state = read_state(root, ch)
        current = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]
        provenance = current[reclaim.PROVENANCE_FIELD]
        provenance["source_release_evidence_fingerprint_sha256"] = "f" * 64
        provenance["provenance_fingerprint_sha256"] = reclaim._provenance_fingerprint(provenance)
        current["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(current)
        _write_state(root, ch, state)

        blocked = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_PRE_NETWORK_REREAD_RECLAIM_PROVENANCE", blocked
        assert "REREAD_RECLAIM_PROVENANCE_IDENTITY_MISMATCH:source_release_evidence_fingerprint_sha256" in blocked["hard_blocks"]
        assert issued["handoff"]["handoff_id"] not in _spend_store(root, ch)["records"]


def test_reclaim_binding_survives_another_pre_network_crash_and_rebinds_latest_attempt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, second = _released_then_reclaimed(root)
        second_latest = second["entry"]["execution_receipts"][-1]

        third = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:26:00Z",
            lease_minutes=1,
        )
        assert third["claimed"] is True, third
        assert third["reread_reservation_reclaim_provenance_bound"] is True, third
        latest = third["entry"]["execution_receipts"][-1]
        provenance = latest[reclaim.PROVENANCE_FIELD]
        assert provenance["handoff_id"] == issued["handoff"]["handoff_id"]
        assert provenance["reclaim_execution_id"] == latest["execution_id"]
        assert provenance["reclaim_execution_id"] != second_latest["execution_id"]
        assert provenance["reclaim_attempt"] == second_latest["attempt"] + 1

        started = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:26:01Z",
        )
        assert started["persisted"] is True, started
        assert _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]["status"] == "SPENT"


def test_binding_is_idempotent_for_same_claim_receipt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, second = _released_then_reclaimed(root)
        before = second["entry"]["execution_receipts"][-1][reclaim.PROVENANCE_FIELD]
        replay = reclaim._persist_reclaim_provenance(
            root,
            ch,
            jb,
            FP1,
            now="2026-08-16T10:24:00Z",
        )
        assert replay["persisted"] is True, replay
        assert replay["status"] == "REREAD_RECLAIM_PROVENANCE_ALREADY_BOUND", replay
        assert replay["written"] is False
        assert replay["provenance"] == before


def test_active_reserved_lease_behavior_is_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, reserved = _reserved_only(root, lease_minutes=10)
        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:23:00Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "LEASE_ACTIVE", blocked
        record = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert record["record_fingerprint_sha256"] == reserved["record"]["record_fingerprint_sha256"]


def test_normal_transient_retry_gets_no_reclaim_binding() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        first = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z"
        )
        assert first["claimed"] is True, first
        assert reclaim.PROVENANCE_FIELD not in first["entry"]["execution_receipts"][-1]
        assert receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:01Z"
        )["persisted"] is True
        assert receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:00:02Z",
            status="RETRY_WAIT",
            last_result_status="RETRY_LATER",
            retry_after_at="2026-08-16T10:01:00Z",
        )["persisted"] is True
        second = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:02:00Z"
        )
        assert second["claimed"] is True, second
        assert reclaim.PROVENANCE_FIELD not in second["entry"]["execution_receipts"][-1]


def test_reclaim_provenance_is_secret_free_advisory_only_and_zero_paid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, second = _released_then_reclaimed(root)
        provenance = second["entry"]["execution_receipts"][-1][reclaim.PROVENANCE_FIELD]
        encoded = json.dumps(provenance, ensure_ascii=False, sort_keys=True).lower()
        for forbidden in (
            "access_token",
            "refresh_token",
            "password",
            "api_key",
            "credential_value",
            "provider_payload",
            "predicted",
            "estimated",
        ):
            assert forbidden not in encoded
        guards = reclaim.reclaim_guards()
        assert guards["provider_network_call_performed_by_binding"] is False
        assert guards["credential_values_read"] is False
        assert guards["credential_values_persisted"] is False
        assert guards["provider_payload_persisted"] is False
        assert guards["publication_blocked_by_analytics"] is False
        assert guards["zero_paid_dependency"] is True


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS reread spend reclaim binding acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
