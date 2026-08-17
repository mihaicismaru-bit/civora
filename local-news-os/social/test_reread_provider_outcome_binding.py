#!/usr/bin/env python3
"""Acceptance tests for atomic provider re-read outcome provenance binding."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import reread_provider_outcome_binding as outcome
import reread_spend_reauthorization as spend
import reread_spend_reclaim_binding as reclaim
from test_authorization_sealed_harvest_recovery import FP1, channel, job, read_state
from test_reread_attempt_provenance_binding import _write_state
from test_reread_spend_reclaim_binding import _released_then_reclaimed
from test_reread_spend_reservation_recovery import _spend_store

outcome.install()


def _network_started(root: Path):
    ch, jb, issued, consumed, first_claim, reserved, second = _released_then_reclaimed(root)
    started = receipt.mark_network_started(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        now="2026-08-16T10:24:01Z",
    )
    assert started["persisted"] is True, started
    assert started["reread_handoff_spent"] is True, started
    return ch, jb, issued, consumed, first_claim, reserved, second, started


def _latest(root: Path, ch: dict, jb: dict) -> dict:
    return read_state(root, ch)["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]


def test_completed_reread_binds_exact_outcome_atomically() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, reserved, _, _ = _network_started(root)
        handoff_id = issued["handoff"]["handoff_id"]
        pre = _latest(root, ch, jb)
        pre_fp = pre["receipt_fingerprint_sha256"]
        spent = _spend_store(root, ch)["records"][handoff_id]
        assert spent["status"] == "SPENT"
        assert spent["spend_id"] != reserved["record"]["spend_id"]
        assert spent["network_receipt_fingerprint_sha256"] == pre_fp

        materialization_fp = "a" * 64
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED",
            last_result_status="COLLECTED_AND_MATERIALIZED",
            materialization_fingerprint_sha256=materialization_fp,
        )
        assert transitioned["persisted"] is True, transitioned
        assert transitioned["reread_provider_outcome_bound"] is True, transitioned

        state = read_state(root, ch)
        entry = state["entries"][runtime.checkpoint_key(jb)]
        latest = entry["execution_receipts"][-1]
        bound = latest[outcome.OUTCOME_FIELD]
        assert entry["status"] == "COMPLETED"
        assert latest["status"] == "COMPLETED"
        assert bound["handoff_id"] == handoff_id
        assert bound["released_spend_id"] == reserved["record"]["spend_id"]
        assert bound["current_spend_id"] == spent["spend_id"]
        assert bound["current_spend_id"] != bound["released_spend_id"]
        assert bound["network_receipt_fingerprint_sha256"] == pre_fp
        assert bound["spend_record_fingerprint_sha256"] == spent["record_fingerprint_sha256"]
        assert bound["checkpoint_status"] == "COMPLETED"
        assert bound["provider_result_status"] == "COLLECTED_AND_MATERIALIZED"
        assert bound["materialization_fingerprint_sha256"] == materialization_fp
        assert bound["reclaim_provenance_fingerprint_sha256"] == latest[reclaim.PROVENANCE_FIELD]["provenance_fingerprint_sha256"]
        assert receipt.validate_sealed_entry(entry, FP1)["valid"] is True


def test_no_data_reread_binds_terminal_outcome_without_materialization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, _, _ = _network_started(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert transitioned["persisted"] is True, transitioned
        latest = _latest(root, ch, jb)
        bound = latest[outcome.OUTCOME_FIELD]
        assert bound["checkpoint_status"] == "COMPLETED_NO_DATA"
        assert bound["provider_result_status"] == "NO_OBSERVED_METRICS"
        assert bound["materialization_fingerprint_sha256"] is None


def test_transient_provider_result_is_bound_and_single_use_spend_remains_spent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, _, _ = _network_started(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="RETRY_WAIT",
            last_result_status="RETRY_LATER",
            retry_after_at="2026-08-16T10:30:00Z",
        )
        assert transitioned["persisted"] is True, transitioned
        latest = _latest(root, ch, jb)
        assert latest[outcome.OUTCOME_FIELD]["checkpoint_status"] == "RETRY_WAIT"
        record = _spend_store(root, ch)["records"][issued["handoff"]["handoff_id"]]
        assert record["status"] == "SPENT"
        blocked = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:31:00Z",
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_REAUTHORIZATION_REQUIRED", blocked


def test_missing_reclaim_provenance_after_network_start_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, _, _ = _network_started(root)
        state = read_state(root, ch)
        entry = state["entries"][runtime.checkpoint_key(jb)]
        latest = entry["execution_receipts"][-1]
        latest.pop(reclaim.PROVENANCE_FIELD, None)
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_OUTCOME_LINEAGE", blocked
        assert "REREAD_OUTCOME_RECLAIM_PROVENANCE_REQUIRED" in blocked["hard_blocks"], blocked
        assert _latest(root, ch, jb)["status"] == "NETWORK_CALL_STARTED"


def test_spent_record_tamper_blocks_terminal_transition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _, _, _, _, _ = _network_started(root)
        path = root / spend.expected_spend_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        record = store["records"][issued["handoff"]["handoff_id"]]
        record["network_receipt_fingerprint_sha256"] = "f" * 64
        record["record_fingerprint_sha256"] = spend._record_fingerprint(record)
        store["store_fingerprint_sha256"] = spend._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        blocked = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_OUTCOME_LINEAGE", blocked
        assert "REREAD_OUTCOME_NETWORK_RECEIPT_FINGERPRINT_MISMATCH" in blocked["hard_blocks"], blocked


def test_reclaim_provenance_tamper_blocks_terminal_transition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, _, _ = _network_started(root)
        state = read_state(root, ch)
        latest = state["entries"][runtime.checkpoint_key(jb)]["execution_receipts"][-1]
        latest[reclaim.PROVENANCE_FIELD]["source_release_evidence_fingerprint_sha256"] = "f" * 64
        latest[reclaim.PROVENANCE_FIELD]["provenance_fingerprint_sha256"] = reclaim._provenance_fingerprint(latest[reclaim.PROVENANCE_FIELD])
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_OUTCOME_LINEAGE", blocked


def test_invalid_materialization_fingerprint_fails_before_transition() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, _, _ = _network_started(root)
        blocked = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED",
            last_result_status="COLLECTED_AND_MATERIALIZED",
            materialization_fingerprint_sha256="not-a-sha256",
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_OUTCOME_MATERIALIZATION", blocked
        assert _latest(root, ch, jb)["status"] == "NETWORK_CALL_STARTED"


def test_normal_non_reread_transition_is_unchanged() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:00Z"
        )
        assert claim["claimed"] is True, claim
        assert receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T09:00:01Z"
        )["persisted"] is True
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
        latest = _latest(root, ch, jb)
        assert outcome.OUTCOME_FIELD not in latest


def test_outcome_is_secret_free_advisory_only_and_zero_paid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _, _, _, _, _ = _network_started(root)
        transitioned = receipt.transition_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:24:02Z",
            status="COMPLETED_NO_DATA",
            last_result_status="NO_OBSERVED_METRICS",
        )
        assert transitioned["persisted"] is True, transitioned
        bound = _latest(root, ch, jb)[outcome.OUTCOME_FIELD]
        encoded = json.dumps(bound, ensure_ascii=False, sort_keys=True).lower()
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
        guards = outcome.outcome_guards()
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
    print(f"PASS reread provider outcome binding acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
