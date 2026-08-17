#!/usr/bin/env python3
"""Acceptance tests for RESERVED re-read spend crash recovery/reconciliation."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import reread_spend_reauthorization as spend
import reread_spend_reservation_recovery as recovery
from test_reread_attempt_provenance_binding import _prepare_consumed, _write_state
from test_authorization_sealed_harvest_recovery import FP1, channel, job, read_state

spend.install()
recovery.install()


def _reserved_only(root: Path, *, lease_minutes: int = 1):
    ch, jb, issued, consumed = _prepare_consumed(root)
    claim = receipt.claim_checkpoint_sealed(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now="2026-08-16T10:22:00Z",
        lease_minutes=lease_minutes,
    )
    assert claim["claimed"] is True, claim
    entry = read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]
    latest = entry["execution_receipts"][-1]
    provenance = latest["reread_attempt_provenance"]
    reserved = spend._reserve_spend(
        root,
        ch,
        jb,
        FP1,
        entry,
        provenance,
        "2026-08-16T10:22:10Z",
    )
    assert reserved["persisted"] is True, reserved
    assert reserved["record"]["status"] == "RESERVED", reserved
    return ch, jb, issued, consumed, claim, reserved


def _spend_store(root: Path, ch: dict) -> dict:
    store, blocks, _ = spend.load_spend_store(root, ch)
    assert not blocks, blocks
    return store


def test_expired_claimed_reservation_is_released_then_reclaimed_safely() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, first_claim, _ = _reserved_only(root, lease_minutes=1)

        second = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
            lease_minutes=1,
        )
        assert second["claimed"] is True, second
        assert second["reread_reservation_reconciled"] == "RELEASED_NO_NETWORK_START", second
        assert second["released_handoff_id"] == issued["handoff"]["handoff_id"]
        assert second["entry"]["attempt"] == first_claim["entry"]["attempt"] + 1
        assert _spend_store(root, ch)["records"] == {}

        state = read_state(root, ch)
        receipts = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"]
        evidence = receipts[-2][recovery.EVIDENCE_FIELD]
        assert evidence["action"] == "RELEASE_AUTHORIZED_NO_NETWORK_START"
        assert evidence["network_start_proven"] is False
        assert evidence["provider_network_call_performed_by_recovery"] is False

        started = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert started["persisted"] is True, started
        record = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert record["status"] == "SPENT", record
        assert record["provider_reads_spent"] == 1


def test_active_claimed_lease_never_releases_reservation() -> None:
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
        assert blocked["reread_reservation_release_allowed"] is False
        record = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert record["status"] == "RESERVED"
        assert record["record_fingerprint_sha256"] == reserved["record"]["record_fingerprint_sha256"]


def test_network_start_receipt_forces_reserved_record_to_spent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _ = _reserved_only(root, lease_minutes=1)
        persisted = spend._BASE_MARK_NETWORK_STARTED(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:22:20Z",
        )
        assert persisted["persisted"] is True, persisted
        before = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert before["status"] == "RESERVED"

        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_REAUTHORIZATION_REQUIRED", blocked
        assert blocked["reread_reservation_reconciled"] == "SPENT"
        assert "REREAD_RESERVATION_NETWORK_START_PROOF_REQUIRES_FRESH_REAUTHORIZATION" in blocked["hard_blocks"]
        after = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert after["status"] == "SPENT", after
        assert after["provider_reads_spent"] == 1


def test_release_evidence_is_durable_before_reservation_removal_and_replay_safe() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, reserved = _reserved_only(root, lease_minutes=1)
        record = reserved["record"]
        evidenced = recovery._persist_release_evidence(
            root,
            ch,
            jb,
            FP1,
            record,
            issued["handoff"]["handoff_id"],
            now="2026-08-16T10:24:00Z",
        )
        assert evidenced["persisted"] is True, evidenced
        assert _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]["status"] == "RESERVED"

        replay = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert replay["claimed"] is True, replay
        assert replay["reread_reservation_reconciled"] == "RELEASED_NO_NETWORK_START"
        assert _spend_store(root, ch)["records"] == {}


def test_tampered_release_evidence_is_fail_closed_and_reservation_stays() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, reserved = _reserved_only(root, lease_minutes=1)
        evidenced = recovery._persist_release_evidence(
            root,
            ch,
            jb,
            FP1,
            reserved["record"],
            issued["handoff"]["handoff_id"],
            now="2026-08-16T10:24:00Z",
        )
        assert evidenced["persisted"] is True, evidenced

        state = read_state(root, ch)
        entry = state["entries"][runtime.checkpoint_key(jb)]
        latest = entry["execution_receipts"][-1]
        latest[recovery.EVIDENCE_FIELD]["action"] = "FORGED_RELEASE"
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:01Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESERVATION_RECOVERY_EVIDENCE", blocked
        assert any(code.startswith("REREAD_RESERVATION_RECOVERY_") for code in blocked["hard_blocks"])
        assert _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]["status"] == "RESERVED"


def test_spend_identity_drift_blocks_release_even_with_valid_store_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _ = _reserved_only(root, lease_minutes=1)
        path = root / spend.expected_spend_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        record = store["records"][issued["handoff"]["handoff_id"]]
        record["execution_id"] = "harvest-execution:" + "f" * 32
        record["record_fingerprint_sha256"] = spend._record_fingerprint(record)
        store["store_fingerprint_sha256"] = spend._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_RESERVATION_RECOVERY", blocked
        assert "REREAD_RESERVATION_RECOVERY_IDENTITY_MISMATCH:execution_id" in blocked["hard_blocks"]


def test_invalid_or_missing_lease_is_ambiguous_and_never_released() -> None:
    for lease_value, expected in (
        (None, "REREAD_RESERVATION_LEASE_PROOF_REQUIRED"),
        ("not-a-date", "REREAD_RESERVATION_LEASE_TIMESTAMP_INVALID"),
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ch, jb, issued, _, _, _ = _reserved_only(root, lease_minutes=1)
            state = read_state(root, ch)
            entry = state["entries"][runtime.checkpoint_key(jb)]
            entry["lease_expires_at"] = lease_value
            _write_state(root, ch, state)
            blocked = receipt.claim_checkpoint_sealed(
                root,
                ch,
                jb,
                authorization_fingerprint=FP1,
                now="2026-08-16T10:24:00Z",
            )
            assert blocked["claimed"] is False, blocked
            assert blocked["status"] == "HOLD_REREAD_RESERVATION_RECOVERY_AMBIGUOUS", blocked
            assert expected in blocked["hard_blocks"]
            assert _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]["status"] == "RESERVED"


def test_normal_transient_retry_remains_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        first = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:00:00Z",
        )
        assert first["claimed"] is True, first
        assert receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:00:01Z",
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
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:02:00Z",
        )
        assert second["claimed"] is True, second
        assert not (root / spend.expected_spend_store_path(ch)).exists()


def test_recovery_evidence_is_secret_free_advisory_only_and_zero_paid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _ = _reserved_only(root, lease_minutes=1)
        second = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
        )
        assert second["claimed"] is True, second
        receipts = read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]["execution_receipts"]
        evidence = receipts[-2][recovery.EVIDENCE_FIELD]
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True).lower()
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
        guards = recovery.recovery_guards()
        assert guards["provider_network_call_performed_by_recovery"] is False
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
    print(f"PASS reread spend reservation recovery acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
