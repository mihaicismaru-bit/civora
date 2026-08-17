#!/usr/bin/env python3
"""Acceptance tests for fleet routing of explicit re-read materialization recovery."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import durable_feedback_snapshot
import fleet_reread_materialization_recovery_routing as routing
import metrics_harvest_runtime as runtime
import test_fleet_metrics_recovery_orchestrator as generic_fixtures
import test_reread_materialization_crash_reconciliation as reread_fixtures
from test_authorization_sealed_harvest_recovery import FP1
from test_reread_provider_outcome_binding import _network_started


def _entry(root: Path, channel: dict, job: dict) -> dict:
    state = json.loads(
        (root / runtime.expected_checkpoint_state_path(channel)).read_text(encoding="utf-8")
    )
    return state["entries"][runtime.checkpoint_key(job)]


def _explicit_materialized(root: Path):
    channel, job, issued, bundle = reread_fixtures._materialized_then_crashed(root)
    generic_fixtures.persist_catalog(root, channel, job["publication"])
    return channel, job, issued, bundle


def _explicit_unmaterialized(root: Path):
    channel, job, issued, *_ = _network_started(root)
    crashed = receipt.claim_checkpoint_sealed(
        root,
        channel,
        job,
        authorization_fingerprint=FP1,
        now="2026-08-16T11:00:00Z",
    )
    assert crashed["claimed"] is False, crashed
    assert crashed["status"] == "RECOVERY_REQUIRED", crashed
    generic_fixtures.persist_catalog(root, channel, job["publication"])
    return channel, job, issued


def test_explicit_reread_routes_to_exact_materialization_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel, job, _, bundle = _explicit_materialized(root)
        result = routing.reconcile_channel_recoveries(
            root, channel, authorization_fingerprint=FP1, now="2026-08-16T11:00:01Z"
        )
        assert result["status"] == "RECOVERY_RECONCILED", result
        assert result["recovered_count"] == 1, result
        row = result["results"][0]
        assert row["recovery_route"] == routing.ROUTE_EXPLICIT, row
        assert row["strict_recovery_status"] == "RECOVERED_COMPLETED_FROM_DURABLE_MATERIALIZATION", row
        assert row["recovery_evidence"]["observation_id"] == bundle["observation_id"], row
        assert row["provider_network_call_performed"] is False
        assert _entry(root, channel, job)["last_result_status"] == "RECOVERED_FROM_DURABLE_MATERIALIZATION"


def test_missing_feedback_snapshot_cannot_fall_back_to_generic_covering_observation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel, job, *_ = _explicit_materialized(root)
        snapshot = root / durable_feedback_snapshot.expected_snapshot_path(channel)
        assert snapshot.exists()
        snapshot.unlink()

        result = routing.reconcile_channel_recoveries(
            root, channel, authorization_fingerprint=FP1, now="2026-08-16T11:00:01Z"
        )
        assert result["status"] == "RECOVERY_HOLD", result
        row = result["results"][0]
        assert row["recovery_route"] == routing.ROUTE_EXPLICIT, row
        assert row["status"] == "HOLD_REREAD_MATERIALIZATION_RECOVERY_EVIDENCE", row
        assert "REREAD_RESULT_FEEDBACK_SNAPSHOT_MISSING" in row["hard_blocks"], row
        # The observed row exists, so the old generic covering-observation path would
        # have been able to close this checkpoint. Routing must keep it unresolved.
        assert _entry(root, channel, job)["status"] == "RECOVERY_REQUIRED"


def test_missing_exact_materialization_stays_unresolved_without_generic_fallback() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel, job, _ = _explicit_unmaterialized(root)
        before = json.loads(
            (root / runtime.expected_checkpoint_state_path(channel)).read_text(encoding="utf-8")
        )
        result = routing.reconcile_channel_recoveries(
            root, channel, authorization_fingerprint=FP1, now="2026-08-16T11:00:01Z"
        )
        after = json.loads(
            (root / runtime.expected_checkpoint_state_path(channel)).read_text(encoding="utf-8")
        )
        assert result["status"] == "RECOVERY_UNRESOLVED", result
        row = result["results"][0]
        assert row["recovery_route"] == routing.ROUTE_EXPLICIT, row
        assert row["strict_recovery_status"] == "RECOVERY_REQUIRED_NO_DURABLE_MATERIALIZATION", row
        assert row["status"] == "RECOVERY_REQUIRED_NO_DURABLE_OBSERVATION", row
        assert before == after
        assert _entry(root, channel, job)["status"] == "RECOVERY_REQUIRED"


def test_normal_sealed_recovery_remains_on_generic_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel = generic_fixtures.fixtures.channel()
        job = generic_fixtures.make_ready_recovery(root, channel)
        generic_fixtures.fixtures.persist_observation(root, channel, job, "2026-08-16T10:00:00Z")
        result = routing.reconcile_channel_recoveries(
            root, channel, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "RECOVERY_RECONCILED", result
        row = result["results"][0]
        assert row["recovery_route"] == routing.ROUTE_GENERIC, row
        assert row["status"] == "RECOVERED_COMPLETED", row


def test_sealed_job_reconstruction_mismatch_is_fail_closed_before_generic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel, job, *_ = _explicit_materialized(root)
        path = root / runtime.expected_checkpoint_state_path(channel)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = state["entries"][runtime.checkpoint_key(job)]
        first = entry["execution_receipts"][0]
        first["claimed_at"] = "2026-08-16T10:00:01Z"
        first["receipt_fingerprint_sha256"] = receipt._receipt_fingerprint(first)
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        runtime._atomic_write_json(path, state)

        result = routing.reconcile_channel_recoveries(
            root, channel, authorization_fingerprint=FP1, now="2026-08-16T11:00:01Z"
        )
        assert result["status"] == "RECOVERY_HOLD", result
        row = result["results"][0]
        assert row["status"] == "HOLD_RECOVERY_REREAD_JOB_RECONSTRUCTION", row
        assert "REREAD_ROUTE_SEALED_JOB_FINGERPRINT_RECONSTRUCTION_MISMATCH" in row["hard_blocks"], row
        assert row["recovery_route"] == routing.ROUTE_EXPLICIT, row
        assert _entry(root, channel, job)["status"] == "RECOVERY_REQUIRED"


def test_fleet_plan_uses_strict_route_operationally() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        channel, job, *_ = _explicit_materialized(root)
        runtime_registry, sealed_plan = generic_fixtures.write_fleet_files(root, channel)
        result = routing.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T11:00:01Z"
        )
        assert result["status"] == "FLEET_RECOVERY_RECONCILED", result
        assert result["recovered_count"] == 1, result
        assert result["channels"][0]["results"][0]["recovery_route"] == routing.ROUTE_EXPLICIT, result
        assert result["guards"]["generic_covering_observation_allowed_for_explicit_reread"] is False
        assert result["provider_reread_authorized"] is False
        assert _entry(root, channel, job)["status"] == "COMPLETED"


def test_router_guards_are_network_free_secret_free_and_zero_paid() -> None:
    guards = routing._guards()
    required = {
        "provider_network_calls_performed": False,
        "credential_values_read": False,
        "credential_values_persisted": False,
        "provider_payload_persisted": False,
        "provider_reread_authorized_automatically": False,
        "explicit_reread_materialization_recovery_routed_before_generic": True,
        "generic_covering_observation_allowed_for_explicit_reread": False,
        "explicit_reread_job_reconstruction_must_match_sealed_fingerprint": True,
        "provider_reread_authorized_by_router": False,
        "provider_network_calls_performed_by_router": False,
        "publication_blocked_by_analytics": False,
        "zero_paid_dependency": True,
    }
    for key, expected in required.items():
        assert guards.get(key) is expected, (key, guards.get(key))


def main() -> int:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"PASS fleet reread materialization recovery routing acceptance ({len(tests)} tests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
