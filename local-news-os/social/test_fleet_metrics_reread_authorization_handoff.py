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
from test_authorization_sealed_harvest_recovery import FP1, FP2, channel, job, make_recovery, persist_observation, read_state


def decision(decision_id: str = "decision:1") -> dict:
    return {
        "decision": handoff.DECISION,
        "reason_code": handoff.REASON_CODE,
        "decision_id": decision_id,
        "decision_actor_ref": "operator:metrics-recovery",
        "decided_at": "2026-08-16T10:20:00Z",
    }


def issue(root: Path, ch: dict, jb: dict, **overrides) -> dict:
    params = {"authorization_fingerprint": FP1, "decision": decision(), "now": "2026-08-16T10:20:00Z"}
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


def read_store(root: Path, ch: dict) -> dict:
    return json.loads((root / handoff.expected_handoff_store_path(ch)).read_text(encoding="utf-8"))


def test_issue_is_durable_sealed_secret_free_and_network_free() -> None:
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
        assert handoff.validate_handoff_store(ch, read_store(root, ch))["valid"] is True
        encoded = json.dumps(result, sort_keys=True).lower()
        assert '"access_token_value":' not in encoded
        assert '"secret_value":' not in encoded
        assert '"credential_value":' not in encoded
        assert '"provider_payload":' not in encoded


def test_same_decision_is_idempotent() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        first, second = issue(root, ch, jb), issue(root, ch, jb)
        assert first["handoff"]["handoff_id"] == second["handoff"]["handoff_id"]
        assert second["status"] == "REREAD_HANDOFF_ALREADY_EXISTS", second
        assert len(read_store(root, ch)["records"]) == 1


def test_consume_moves_only_to_retry_wait_and_is_single_use() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        first = consume(root, ch, jb, issued)
        second = consume(root, ch, jb, issued, now="2026-08-16T10:22:00Z")
        assert first["status"] == "REREAD_HANDOFF_CONSUMED", first
        assert first["checkpoint_status"] == "RETRY_WAIT"
        assert first["provider_network_call_performed"] is False
        assert second["status"] == "REREAD_HANDOFF_ALREADY_CONSUMED", second
        entry = next(iter(read_state(root, ch)["entries"].values()))
        assert entry["status"] == "RETRY_WAIT"
        evidence = entry["execution_receipts"][-1]["recovery_evidence"]
        assert evidence["authorization_mode"] == "EXPLICIT_SINGLE_USE_HANDOFF"
        reclaimed = receipt.claim_checkpoint_sealed(root, ch, jb, authorization_fingerprint=FP1, now="2026-08-16T10:22:00Z")
        assert reclaimed["claimed"] is True, reclaimed
        assert reclaimed["entry"]["attempt"] == 2
        assert [row["attempt"] for row in reclaimed["entry"]["execution_receipts"]] == [1, 2]


def test_missing_or_secret_bearing_explicit_decision_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        missing = handoff.issue_handoff(root, ch, jb, authorization_fingerprint=FP1, decision={}, now="2026-08-16T10:20:00Z")
        assert missing["status"] == "HOLD_REREAD_EXPLICIT_DECISION", missing
        bad = decision("decision:secret")
        bad["secret_value"] = "must-not-persist"
        rejected = issue(root, ch, jb, decision=bad)
        assert rejected["status"] == "HOLD_REREAD_EXPLICIT_DECISION", rejected
        assert "REREAD_EXPLICIT_DECISION_FORBIDDEN_MATERIAL" in rejected["hard_blocks"]
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_authorization_drift_and_expiry_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb, ttl_minutes=5)
        drift = consume(root, ch, jb, issued, authorization_fingerprint=FP2)
        assert drift["status"] == "HOLD_REREAD_AUTHORIZATION_CHANGED", drift
        expired = consume(root, ch, jb, issued, now="2026-08-16T10:26:00Z")
        assert expired["status"] == "HOLD_REREAD_HANDOFF_EXPIRED", expired
        assert next(iter(read_state(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_durable_observation_blocks_issue_or_supersedes_existing_handoff() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:30:00Z")
        superseded = consume(root, ch, jb, issued, now="2026-08-16T10:31:00Z")
        assert superseded["status"] == "HOLD_REREAD_SUPERSEDED_BY_DURABLE_OBSERVATION", superseded
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        unnecessary = issue(root, ch, jb)
        assert unnecessary["status"] == "HOLD_REREAD_NOT_NEEDED", unnecessary
        assert not (root / handoff.expected_handoff_store_path(ch)).exists()


def test_checkpoint_or_handoff_tamper_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        state_path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        next(iter(state["entries"].values()))["last_result_status"] = "reviewed"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        state_path.write_text(json.dumps(state), encoding="utf-8")
        stale = consume(root, ch, jb, issued)
        assert stale["status"] == "HOLD_REREAD_HANDOFF_STALE", stale
    with tempfile.TemporaryDirectory() as tmp:
        root, ch = Path(tmp), channel()
        jb = job(ch)
        make_recovery(root, ch, jb)
        issued = issue(root, ch, jb)
        store_path = root / handoff.expected_handoff_store_path(ch)
        store = json.loads(store_path.read_text(encoding="utf-8"))
        store["records"][issued["handoff"]["handoff_id"]]["authorization"]["max_provider_reads"] = 2
        store_path.write_text(json.dumps(store), encoding="utf-8")
        tampered = consume(root, ch, jb, issued)
        assert tampered["status"] == "HOLD_REREAD_HANDOFF_STORE", tampered


def test_instance_isolation_and_zero_paid_policy_are_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alpha = channel(instance="alpha")
        alpha_job = job(alpha)
        make_recovery(root, alpha, alpha_job)
        issued = issue(root, alpha, alpha_job)
        beta = channel(instance="beta")
        beta_job = job(beta)
        make_recovery(root, beta, beta_job)
        isolated = handoff.consume_handoff(root, beta, beta_job, authorization_fingerprint=FP1, handoff_id=issued["handoff"]["handoff_id"], now="2026-08-16T10:21:00Z")
        assert isolated["status"] == "HOLD_REREAD_HANDOFF_MISSING", isolated
        bad = copy.deepcopy(alpha)
        bad["zero_paid_dependency"] = False
        blocked = issue(root, bad, alpha_job, decision=decision("decision:paid"))
        assert blocked["status"] == "HOLD_REREAD_JOB", blocked
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in blocked["hard_blocks"]


def test_guards_are_network_free_single_use_and_advisory_only() -> None:
    guards = handoff._guards()
    assert guards == {
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "explicit_decision_required": True,
        "single_use_handoff_required": True,
        "authorization_sealed": True,
        "observation_ledger_rechecked_before_retry_eligibility": True,
        "blind_retry_after_ambiguous_network_call": False,
        "analytics_advisory_only": True,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }


def main() -> int:
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS fleet metrics reread authorization handoff acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
