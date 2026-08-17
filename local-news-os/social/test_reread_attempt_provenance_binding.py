#!/usr/bin/env python3
"""Acceptance tests for provenance-bound provider re-read attempts after ambiguous recovery."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import fleet_metrics_reread_authorization_handoff as handoff
import metrics_harvest_runtime as runtime
from test_authorization_sealed_harvest_recovery import FP1, channel, job, make_recovery, read_state


def _decision() -> dict:
    return {
        "decision": handoff.DECISION,
        "reason_code": handoff.REASON_CODE,
        "decision_id": "decision:attempt-provenance",
        "decision_actor_ref": "operator:metrics-recovery",
        "decided_at": "2026-08-16T10:20:00Z",
    }


def _prepare_consumed(root: Path):
    ch = channel()
    jb = job(ch)
    make_recovery(root, ch, jb)
    issued = handoff.issue_handoff(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        decision=_decision(),
        now="2026-08-16T10:20:00Z",
    )
    assert issued["status"] == "REREAD_HANDOFF_AUTHORIZED", issued
    consumed = handoff.consume_handoff(
        root,
        ch,
        jb,
        authorization_fingerprint=FP1,
        handoff_id=issued["handoff"]["handoff_id"],
        now="2026-08-16T10:21:00Z",
    )
    assert consumed["status"] == "REREAD_HANDOFF_CONSUMED", consumed
    return ch, jb, issued, consumed


def _handoff_store(root: Path, ch: dict) -> tuple[Path, dict]:
    path = root / handoff.expected_handoff_store_path(ch)
    return path, json.loads(path.read_text(encoding="utf-8"))


def _write_state(root: Path, ch: dict, state: dict) -> None:
    state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
    path = root / runtime.expected_checkpoint_state_path(ch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_consumed_handoff_is_bound_into_next_execution_receipt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, consumed = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert claim["claimed"] is True, claim
        latest = claim["entry"]["execution_receipts"][-1]
        provenance = latest.get("reread_attempt_provenance")
        assert isinstance(provenance, dict), latest
        assert provenance["provenance_id"] == receipt.REREAD_ATTEMPT_PROVENANCE_ID
        assert provenance["handoff_id"] == issued["handoff"]["handoff_id"]
        assert provenance["handoff_authorization_fingerprint_sha256"] == consumed["recovery_evidence"]["reread_handoff_authorization_fingerprint_sha256"]
        assert provenance["authorization_fingerprint"] == FP1
        assert provenance["checkpoint_key"] == runtime.checkpoint_key(jb)
        checked = receipt.validate_sealed_entry(claim["entry"], FP1)
        assert checked["valid"] is True, checked
        started = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:01Z"
        )
        assert started["persisted"] is True, started


def test_recovery_retry_without_explicit_handoff_evidence_cannot_be_claimed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        latest = entry["execution_receipts"][-1]
        entry["status"] = "RETRY_WAIT"
        entry["retry_after_at"] = "2026-08-16T10:21:00Z"
        entry["last_result_status"] = receipt.RECOVERY_REREAD_RESULT
        latest["status"] = "RETRY_WAIT"
        latest["checkpoint_status"] = "RETRY_WAIT"
        latest["provider_result_status"] = receipt.RECOVERY_REREAD_RESULT
        latest.pop("recovery_evidence", None)
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_ATTEMPT_PROVENANCE", blocked
        assert "REREAD_ATTEMPT_RECOVERY_EVIDENCE_REQUIRED" in blocked["hard_blocks"]


def test_consumed_handoff_record_must_still_exist_at_claim_time() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _ = _prepare_consumed(root)
        path, store = _handoff_store(root, ch)
        store["records"].pop(issued["handoff"]["handoff_id"])
        store["store_fingerprint_sha256"] = handoff._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        blocked = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert blocked["claimed"] is False, blocked
        assert blocked["status"] == "HOLD_REREAD_ATTEMPT_PROVENANCE", blocked
        assert "REREAD_ATTEMPT_HANDOFF_RECORD_MISSING" in blocked["hard_blocks"]


def test_handoff_is_rechecked_again_immediately_before_network_start() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, issued, _ = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert claim["claimed"] is True, claim

        path, store = _handoff_store(root, ch)
        store["records"].pop(issued["handoff"]["handoff_id"])
        store["store_fingerprint_sha256"] = handoff._store_fingerprint(store)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        blocked = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:01Z"
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_PRE_NETWORK_REREAD_PROVENANCE", blocked
        assert "REREAD_ATTEMPT_HANDOFF_RECORD_MISSING" in blocked["hard_blocks"]
        latest = next(iter(read_state(root, ch)["entries"].values()))["execution_receipts"][-1]
        assert latest["status"] == "CLAIMED"
        assert latest["network_started_at"] is None


def test_receipt_provenance_tamper_is_fail_closed_before_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _ = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        assert claim["claimed"] is True, claim
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        latest = entry["execution_receipts"][-1]
        latest["reread_attempt_provenance"]["handoff_id"] = "metrics-reread:forged"
        latest["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(latest)
        _write_state(root, ch, state)

        blocked = receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:01Z"
        )
        assert blocked["persisted"] is False, blocked
        assert blocked["status"] == "HOLD_PRE_NETWORK_REREAD_PROVENANCE", blocked
        assert "REREAD_ATTEMPT_HANDOFF_RECORD_MISSING" in blocked["hard_blocks"]


def test_normal_transient_retry_remains_compatible_without_handoff_provenance() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = channel()
        jb = job(ch)
        first = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:00Z"
        )
        assert first["claimed"] is True, first
        assert receipt.mark_network_started(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:00:01Z"
        )["persisted"] is True
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
        assert "reread_attempt_provenance" not in second["entry"]["execution_receipts"][-1]


def test_provenance_is_secret_free_advisory_only_and_zero_paid() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb, _, _ = _prepare_consumed(root)
        claim = receipt.claim_checkpoint_sealed(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z"
        )
        provenance = claim["entry"]["execution_receipts"][-1]["reread_attempt_provenance"]
        encoded = json.dumps(provenance, sort_keys=True).lower()
        for forbidden in ("access_token", "refresh_token", "password", "api_key", "credential_value", "provider_payload", "predicted", "estimated"):
            assert forbidden not in encoded
        assert provenance["provider_network_call_performed"] is False
        assert provenance["publication_blocked"] is False
        assert provenance["zero_paid_dependency"] is True


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS reread attempt provenance binding acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
