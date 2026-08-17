#!/usr/bin/env python3
"""Acceptance tests for single-use explicit provider re-read spend sealing."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import fleet_metrics_reread_authorization_handoff as handoff
import metrics_harvest_runtime as runtime
import reread_spend_reauthorization as spend
from test_reread_attempt_provenance_binding import _decision, _prepare_consumed
from test_authorization_sealed_harvest_recovery import FP1, channel, job, read_state

spend.install()


def _spend_store(root: Path, ch: dict) -> tuple[Path, dict]:
    path = root / spend.expected_spend_store_path(ch)
    return path, json.loads(path.read_text(encoding="utf-8"))


def _first_reread_to_network_start(root: Path):
    ch, jb, issued, consumed = _prepare_consumed(root)
    claim = receipt.claim_checkpoint_sealed(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now="2026-08-16T10:22:00Z",
        lease_minutes=1,
    )
    assert claim["claimed"] is True, claim
    started = receipt.mark_network_started(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now="2026-08-16T10:22:01Z",
    )
    assert started["persisted"] is True, started
    assert started["reread_handoff_spent"] is True, started
    return ch, jb, issued, consumed, claim, started


def test_explicit_reread_is_spent_before_provider_call_boundary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, claim, started = _first_reread_to_network_start(root)
        path, store = _spend_store(root, ch)
        assert path.exists()
        record = store["records"][issued["handoff"]["handoff_id"]]
        latest = read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]
        assert record["status"] == "SPENT", record
        assert record["provider_reads_spent"] == 1, record
        assert record["execution_id"] == latest["execution_id"] == claim["entry"]["execution_receipts"][-1]["execution_id"]
        assert record["network_started_at"] == latest["network_started_at"]
        assert record["network_receipt_fingerprint_sha256"] == latest["receipt_fingerprint_sha256"]
        assert started["reauthorization_required_for_next_provider_read"] is True
        assert spend.validate_spend_store(ch, store)["valid"] is True


def test_second_provider_read_requires_new_explicit_authorization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _ = _first_reread_to_network_start(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:22:02Z",
            status="RETRY_WAIT",
            last_result_status="RETRY_LATER",
            retry_after_at="2026-08-16T10:23:00Z",
        )
        assert transitioned["persisted"] is True, transitioned
        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_REAUTHORIZATION_REQUIRED", blocked
        assert "REREAD_SINGLE_USE_PROVIDER_READ_ALREADY_SPENT" in blocked["hard_blocks"]


def test_new_explicit_handoff_after_ambiguous_reread_can_be_spent_once() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued1, _, _, _ = _first_reread_to_network_start(root)
        recovery = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:00Z",
            lease_minutes=1,
        )
        assert recovery["status"] == "RECOVERY_REQUIRED", recovery
        decision2 = _decision()
        decision2["decision_id"] = "decision:attempt-provenance:second"
        decision2["decided_at"] = "2026-08-16T10:25:00Z"
        issued2 = handoff.issue_handoff(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            decision=decision2,
            now="2026-08-16T10:25:00Z",
        )
        assert issued2["status"] == "REREAD_HANDOFF_AUTHORIZED", issued2
        assert issued2["handoff"]["handoff_id"] != issued1["handoff"]["handoff_id"]
        consumed2 = handoff.consume_handoff(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            handoff_id=issued2["handoff"]["handoff_id"],
            now="2026-08-16T10:26:00Z",
        )
        assert consumed2["status"] == "REREAD_HANDOFF_CONSUMED", consumed2
        claim2 = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:27:00Z",
            lease_minutes=1,
        )
        assert claim2["claimed"] is True, claim2
        started2 = receipt.mark_network_started(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:27:01Z",
        )
        assert started2["persisted"] is True, started2
        _, store = _spend_store(root, ch)
        assert store["records"][issued1["handoff"]["handoff_id"]]["status"] == "SPENT"
        assert store["records"][issued2["handoff"]["handoff_id"]]["status"] == "SPENT"
        assert len(store["records"]) == 2


def test_normal_transient_retry_is_unchanged_and_creates_no_spend_record() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        first = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z"
        )
        assert first["claimed"] is True, first
        started = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:01Z"
        )
        assert started["persisted"] is True, started
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:00:02Z",
            status="RETRY_WAIT",
            last_result_status="RETRY_LATER",
            retry_after_at="2026-08-16T10:01:00Z",
        )
        assert transitioned["persisted"] is True, transitioned
        second = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:02:00Z"
        )
        assert second["claimed"] is True, second
        path = root / spend.expected_spend_store_path(ch)
        assert not path.exists()


def test_handoff_tamper_before_network_does_not_create_spend_record() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _ = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert claim["claimed"] is True, claim
        handoff_path = root / handoff.expected_handoff_store_path(ch)
        handoff_store = json.loads(handoff_path.read_text(encoding="utf-8"))
        handoff_store["records"].pop(issued["handoff"]["handoff_id"])
        handoff_store["store_fingerprint_sha256"] = handoff._store_fingerprint(handoff_store)
        handoff_path.write_text(json.dumps(handoff_store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        blocked = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:01Z"
        )
        assert blocked["persisted"] is False, blocked
        assert "REREAD_ATTEMPT_HANDOFF_RECORD_MISSING" in blocked["hard_blocks"]
        spend_path = root / spend.expected_spend_store_path(ch)
        assert not spend_path.exists()


def test_spend_store_tamper_blocks_reuse_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _ = _first_reread_to_network_start(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:22:02Z",
            status="RETRY_WAIT",
            last_result_status="RETRY_LATER",
            retry_after_at="2026-08-16T10:23:00Z",
        )
        assert transitioned["persisted"] is True, transitioned
        path, store = _spend_store(root, ch)
        record = store["records"][issued["handoff"]["handoff_id"]]
        record["provider_reads_spent"] = 0
        store["store_fingerprint_sha256"] = spend._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        blocked = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:24:00Z"
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_SPEND_TAMPERED", blocked
        assert any(code.startswith("REREAD_SPEND_") for code in blocked["hard_blocks"])


def test_spend_reservation_is_idempotent_only_for_same_execution() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _ = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert claim["claimed"] is True, claim
        state = read_state(root, ch)
        entry = state["entries"][runtime.checkpoint_key(jb)]
        provenance = entry["execution_receipts"][-1]["reread_attempt_provenance"]
        first = spend._reserve_spend(root, ch, jb, FP1, entry, provenance, "2026-08-16T10:22:01Z")
        assert first["persisted"] is True, first
        second = spend._reserve_spend(root, ch, jb, FP1, entry, provenance, "2026-08-16T10:22:02Z")
        assert second["persisted"] is True, second
        assert second["status"] == "REREAD_SPEND_ALREADY_RESERVED", second
        _, store = _spend_store(root, ch)
        assert len(store["records"]) == 1
        assert store["records"][issued["handoff"]["handoff_id"]]["status"] == "RESERVED"


def test_spend_ledger_is_secret_free_advisory_only_and_zero_paid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, _, _, _, _, _ = _first_reread_to_network_start(root)
        _, store = _spend_store(root, ch)
        encoded = json.dumps(store, ensure_ascii=False, sort_keys=True).lower()
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
        guards = store["guards"]
        assert guards["provider_network_call_performed_by_spend_boundary"] is False
        assert guards["publication_blocked_by_analytics"] is False
        assert guards["spent_handoff_reuse_allowed"] is False
        assert guards["new_explicit_reauthorization_required_after_spend"] is True
        assert guards["zero_paid_dependency"] is True


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS reread spend / reauthorization acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
