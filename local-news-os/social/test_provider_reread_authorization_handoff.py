#!/usr/bin/env python3
"""Acceptance tests for explicit, single-use provider reread authorization handoffs."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import metrics_harvest_runtime as runtime
import provider_reread_authorization_handoff as handoff
import test_authorization_sealed_harvest_recovery as fixtures

FP1 = fixtures.FP1
FP2 = fixtures.FP2
NOW = "2026-08-16T10:20:00Z"


def setup_recovery(root: Path):
    ch = fixtures.channel()
    jb = fixtures.job(ch)
    fixtures.make_recovery(root, ch, jb)
    return ch, jb


def issue(root: Path, ch: dict, jb: dict, **overrides):
    args = {
        "authorization_fingerprint": FP1,
        "now": NOW,
        "decision_id": "operator-review:case-001",
        "reason_code": "NO_DURABLE_OBSERVATION_CONFIRMED",
        "ttl_minutes": 30,
    }
    args.update(overrides)
    return handoff.issue_provider_reread_handoff(root, ch, jb, **args)


def read_entry(root: Path, ch: dict) -> dict:
    state = json.loads((root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8"))
    return next(iter(state["entries"].values()))


def test_issue_persists_handoff_but_keeps_checkpoint_in_recovery_required() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        result = issue(root, ch, jb)
        assert result["status"] == "REREAD_HANDOFF_READY", result
        assert result["provider_network_call_performed"] is False
        entry = read_entry(root, ch)
        assert entry["status"] == "RECOVERY_REQUIRED", entry
        assert entry["provider_reread_handoff"]["status"] == "AUTHORIZED", entry
        assert result["handoff"]["authorization_fingerprint"] == FP1
        assert result["guards"]["single_use_handoff"] is True


def test_same_explicit_decision_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        first = issue(root, ch, jb)
        before = read_entry(root, ch)
        second = issue(root, ch, jb)
        after = read_entry(root, ch)
        assert first["status"] == second["status"] == "REREAD_HANDOFF_READY"
        assert first["handoff"] == second["handoff"]
        assert before == after


def test_second_different_decision_cannot_replace_live_authorization() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        assert issue(root, ch, jb)["status"] == "REREAD_HANDOFF_READY"
        result = issue(root, ch, jb, decision_id="operator-review:case-002")
        assert result["status"] == "HOLD_REREAD_HANDOFF_ALREADY_AUTHORIZED", result
        assert "REREAD_HANDOFF_DECISION_CONFLICT" in result["hard_blocks"]


def test_durable_observation_prevents_handoff_and_completes_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        result = issue(root, ch, jb)
        assert result["status"] == "NO_REREAD_DURABLE_OBSERVATION_RECOVERED", result
        assert read_entry(root, ch)["status"] == "COMPLETED"


def test_issue_requires_real_recovery_required_receipt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = fixtures.job(ch)
        result = issue(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECONCILIATION", result
        assert result["provider_network_call_performed"] is False


def test_authorization_drift_is_rejected_before_handoff_persistence() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        result = issue(root, ch, jb, authorization_fingerprint=FP2)
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECONCILIATION", result
        assert "provider_reread_handoff" not in read_entry(root, ch)


def test_consume_rechecks_ledger_and_moves_once_to_retry_wait() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        assert issue(root, ch, jb)["status"] == "REREAD_HANDOFF_READY"
        result = handoff.consume_provider_reread_handoff(
            root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z"
        )
        assert result["status"] == "REREAD_HANDOFF_CONSUMED", result
        assert result["checkpoint_status"] == "RETRY_WAIT"
        assert result["provider_reread_authorized"] is True
        assert result["provider_network_call_performed"] is False
        entry = read_entry(root, ch)
        assert entry["status"] == "RETRY_WAIT"
        assert entry["provider_reread_handoff"]["status"] == "CONSUMED"
        evidence = entry["execution_receipts"][-1]["recovery_evidence"]
        assert evidence["kind"] == "EXPLICIT_PROVIDER_REREAD_HANDOFF_CONSUMED"
        assert evidence["reread_handoff_fingerprint_sha256"] == entry["provider_reread_handoff"]["handoff_fingerprint_sha256"]
        assert receipt.validate_sealed_entry(entry, FP1)["valid"] is True


def test_handoff_is_single_use_and_cannot_be_consumed_twice() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        issue(root, ch, jb)
        first = handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z")
        second = handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z")
        assert first["status"] == "REREAD_HANDOFF_CONSUMED"
        assert second["status"] == "HOLD_REREAD_HANDOFF_RECONCILIATION", second
        assert read_entry(root, ch)["attempt"] == 1


def test_observation_arriving_between_issue_and_consume_cancels_reread() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        issue(root, ch, jb)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        result = handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z")
        assert result["status"] == "NO_REREAD_DURABLE_OBSERVATION_RECOVERED", result
        assert read_entry(root, ch)["status"] == "COMPLETED"


def test_expired_handoff_fails_closed_without_requeue() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        issue(root, ch, jb, ttl_minutes=1)
        result = handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z")
        assert result["status"] == "HOLD_REREAD_HANDOFF_INVALID", result
        assert "REREAD_HANDOFF_EXPIRED" in result["hard_blocks"]
        assert read_entry(root, ch)["status"] == "RECOVERY_REQUIRED"


def test_tampered_handoff_is_rejected_by_checkpoint_fingerprint() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        issue(root, ch, jb)
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = next(iter(state["entries"].values()))
        entry["provider_reread_handoff"]["reason_code"] = "ALTERED_REASON"
        path.write_text(json.dumps(state), encoding="utf-8")
        result = handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z")
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECONCILIATION", result
        assert any("CHECKPOINT_STATE_FINGERPRINT_MISMATCH" in code for code in result["hard_blocks"])


def test_cross_instance_job_cannot_receive_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        beta = fixtures.channel(instance="beta")
        result = issue(root, beta, jb)
        assert result["status"] == "HOLD_REREAD_HANDOFF_RECONCILIATION", result
        assert result["provider_network_call_performed"] is False


def test_zero_paid_dependency_and_observed_only_are_mandatory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        bad_paid = copy.deepcopy(ch)
        bad_paid["zero_paid_dependency"] = False
        result = issue(root, bad_paid, jb)
        assert result["status"] == "HOLD_REREAD_HANDOFF_POLICY", result
        bad_observed = copy.deepcopy(ch)
        bad_observed["metrics"]["observed_only"] = False
        result = issue(root, bad_observed, jb)
        assert result["status"] == "HOLD_REREAD_HANDOFF_POLICY", result


def test_handoff_and_checkpoint_are_secret_free() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        result = issue(root, ch, jb)
        text = json.dumps(result, ensure_ascii=False).lower()
        text += (root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8").lower()
        for forbidden in ('"access_token":', '"credential_value":', '"secret_value":', '"provider_payload":'):
            assert forbidden not in text, forbidden
        assert result["guards"]["credential_values_read"] is False
        assert result["guards"]["credential_values_persisted"] is False
        assert result["guards"]["provider_payload_persisted"] is False


def test_consumed_handoff_allows_exactly_next_sealed_claim_without_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch, jb = setup_recovery(root)
        issue(root, ch, jb)
        handoff.consume_provider_reread_handoff(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z")
        claim = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:21:00Z")
        assert claim["claimed"] is True, claim
        assert claim["entry"]["attempt"] == 2, claim
        assert [row["attempt"] for row in claim["entry"]["execution_receipts"]] == [1, 2]
        assert claim["entry"]["execution_receipts"][0]["recovery_evidence"]["kind"] == "EXPLICIT_PROVIDER_REREAD_HANDOFF_CONSUMED"
        assert claim["entry"]["execution_receipts"][1]["network_started_at"] is None


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS provider reread authorization handoff acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
