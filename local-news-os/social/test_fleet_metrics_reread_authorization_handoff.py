#!/usr/bin/env python3
"""Acceptance tests for explicit single-use fleet metrics provider re-read handoffs."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import fleet_metrics_reread_authorization_handoff as handoff
import metrics_harvest_runtime as runtime
from test_authorization_sealed_harvest_recovery import (
    FP1,
    FP2,
    channel,
    job,
    make_recovery,
    persist_observation,
    read_state,
)


def decision(decision_id: str = "decision:1", actor: str = "operator:metrics-recovery") -> dict:
    return {
        "decision": handoff.DECISION,
        "reason_code": handoff.REASON_CODE,
        "decision_id": decision_id,
        "decision_actor_ref": actor,
        "decided_at": "2026-08-16T10:20:00Z",
    }


def issue(root: Path, ch: dict, jb: dict, **overrides) -> dict:
    params = {
        "authorization_fingerprint": FP1,
        "decision": decision(),
        "now": "2026-08-16T10:20:00Z",
    }
    params.update(overrides)
    return handoff.issue_handoff(root, ch, jb, **params)


def consume(root: Path, ch: dict, jb: dict, issued: dict, **overrides) -> dict:
    params = {
        "authorization_fingerprint": FP1,
        "handoff_id": issued["handoff"]["handoff_id"],
        "now": "2026-08-16T10:21:00Z",
    }
    params.update(overrides)
    return handoff.consume_handoff(root, ch, jb, **params)


def read_handoff_store(root: Path, ch: dict) -> dict:
    return json.loads((root / handoff.expected_handoff_store_path(ch)).read_text(encoding="utf-8"))


def test_explicit_decision_issues_durable_secret_free_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = issue(root, ch, jb)
        assert result["status"] == "REREAD_HANDOFF_AUTHORIZED", result
        assert result["provider_reread_authorized"] is True
        assert result["provider_network_call_performed"] is False
        record = result["handoff"]
        assert record["status"] == "AUTHORIZED"
        assert record["authorization"]["max_provider_reads"] == 1
        assert record["authorization"]["authorization_fingerprint"] == FP1
        assert handoff.validate_handoff_store(ch, read_handoff_store(root, ch))["valid"] is True
        encoded = json.dumps(result, sort_keys=True).lower()
        for forbidden in ("access_token_value", "secret_value", "credential_value", "provider_payload"):
            assert forbidden not in encoded


def test_same_explicit_decision_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        first = issue(root, ch, jb)
        second = issue(root, ch, jb)
        assert first["handoff"]["handoff_id"] == second["handoff"]["handoff_id"]
        assert second["status"] == "REREAD_HANDOFF_ALREADY_EXISTS", second
        assert len(read_handoff_store(root, ch)["records"]) == 1


def test_handoff_consumption_moves_checkpoint_to_retry_wait_without_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        result = consume(root, ch, jb, issued)
        assert result["status"] == "REREAD_HANDOFF_CONSUMED", result
        assert result["checkpoint_status"] == "RETRY_WAIT"
        assert result["provider_reread_authorized"] is True
        assert result["provider_network_call_performed"] is False
        state = read_state(root, ch)
        entry = next(iter(state["entries"].values()))
        assert entry["status"] == "RETRY_WAIT"
        evidence = entry["execution_receipts"][-1]["recovery_evidence"]
        assert evidence["authorization_mode"] == "EXPLICIT_SINGLE_USE_HANDOFF"
        assert evidence["reread_handoff_id"] == issued["handoff"]["handoff_id"]
        store = read_handoff_store(root, ch)
        assert store["records"][issued["handoff"]["handoff_id"]]["status"] == "CONSUMED"


def test_consumed_handoff_is_single_use_and_cannot_create_third_attempt() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        first = consume(root, ch, jb, issued)
        second = consume(root, ch, jb, issued, now="2026-08-16T10:22:00Z")
        assert first["status"] == "REREAD_HANDOFF_CONSUMED", first
        assert second["status"] == "REREAD_HANDOFF_ALREADY_CONSUMED", second
        reclaimed = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z")
        assert reclaimed["claimed"] is True, reclaimed
        assert reclaimed["entry"]["attempt"] == 2
        assert [row["attempt"] for row in reclaimed["entry"]["execution_receipts"]] == [1, 2]


def test_missing_explicit_decision_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        result = handoff.issue_handoff(root, ch, jb, authorization_fingerprint=FP1, decision={}, now="2026-08-16T10:20:00Z")
        assert result["status"] == "HOLD_REREAD_EXPLICIT_DECISION", result
        assert result["provider_reread_authorized"] is False
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_decision_with_secret_like_material_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        bad = decision()
        bad["secret_value"] = "do-not-persist"
        result = issue(root, ch, jb, decision=bad)
        assert result["status"] == "HOLD_REREAD_EXPLICIT_DECISION", result
        assert "REREAD_EXPLICIT_DECISION_FORBIDDEN_MATERIAL" in result["hard_blocks"]


def test_authorization_drift_between_issue_and_consume_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        result = consume(root, ch, jb, issued, authorization_fingerprint=FP2)
        assert result["status"] == "HOLD_REREAD_AUTHORIZATION_CHANGED", result
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_durable_observation_before_issue_makes_reread_unnecessary() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        result = issue(root, ch, jb)
        assert result["status"] == "HOLD_REREAD_NOT_NEEDED", result
        assert result["provider_reread_authorized"] is False
        assert not (root / handoff.expected_handoff_store_path(ch)).exists()


def test_observation_arriving_after_issue_supersedes_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:30:00Z")
        result = consume(root, ch, jb, issued, now="2026-08-16T10:31:00Z")
        assert result["status"] == "HOLD_REREAD_SUPERSEDED_BY_DURABLE_OBSERVATION", result
        assert result["provider_reread_authorized"] is False
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_handoff_expires_before_consumption() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb, ttl_minutes=5)
        result = consume(root, ch, jb, issued, now="2026-08-16T10:26:00Z")
        assert result["status"] == "HOLD_REREAD_HANDOFF_EXPIRED", result
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_checkpoint_drift_after_issue_invalidates_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = next(iter(state["entries"].values()))
        entry["last_result_status"] = "AMBIGUOUS_NETWORK_EXECUTION_REVIEWED"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        path.write_text(json.dumps(state), encoding="utf-8")
        result = consume(root, ch, jb, issued)
        assert result["status"] == "HOLD_REREAD_HANDOFF_STALE", result
        assert "REREAD_CHECKPOINT_STATE_CHANGED_AFTER_HANDOFF_ISSUE" in result["hard_blocks"]


def test_handoff_store_tamper_is_rejected() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        path = root / handoff.expected_handoff_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["records"][issued["handoff"]["handoff_id"]]["authorization"]["max_provider_reads"] = 2
        path.write_text(json.dumps(store), encoding="utf-8")
        result = consume(root, ch, jb, issued)
        assert result["status"] == "HOLD_REREAD_HANDOFF_STORE", result
        assert result["provider_reread_authorized"] is False


def test_cross_instance_handoff_cannot_be_consumed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alpha = channel(instance="alpha")
        alpha_job = job(alpha)
        make_recovery(root, alpha, alpha_job)
        issued = issue(root, alpha, alpha_job)
        beta = channel(instance="beta")
        beta_job = job(beta)
        make_recovery(root, beta, beta_job)
        result = handoff.consume_handoff(
            root, beta, beta_job, authorization_fingerprint=FP1,
            handoff_id=issued["handoff"]["handoff_id"], now="2026-08-16T10:21:00Z",
        )
        assert result["status"] == "HOLD_REREAD_HANDOFF_MISSING", result
        assert next(iter(read_state(root, beta)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_zero_paid_dependency_cannot_be_weakened() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good = channel()
        jb = job(good)
        make_recovery(root, good, jb)
        bad = copy.deepcopy(good)
        bad["zero_paid_dependency"] = False
        result = issue(root, bad, jb)
        assert result["status"] == "HOLD_REREAD_JOB", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"]


def test_guards_keep_reread_handoff_network_free_and_advisory_only() -> None:
    guards = handoff._guards()
    assert guards["provider_network_calls_performed"] is False
    assert guards["credential_values_read"] is False
    assert guards["credential_values_persisted"] is False
    assert guards["provider_payload_persisted"] is False
    assert guards["explicit_decision_required"] is True
    assert guards["single_use_handoff_required"] is True
    assert guards["observation_ledger_rechecked_before_retry_eligibility"] is True
    assert guards["blind_retry_after_ambiguous_network_call"] is False
    assert guards["publication_blocked_by_analytics"] is False
    assert guards["zero_paid_dependency"] is True


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS fleet metrics reread authorization handoff acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
