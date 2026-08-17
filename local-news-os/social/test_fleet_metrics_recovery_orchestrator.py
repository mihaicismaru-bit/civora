#!/usr/bin/env python3
"""Acceptance tests for fleet-level sealed harvest recovery orchestration."""
from __future__ import annotations

import copy
import json
import tempfile
from pathlib import Path

import authorization_sealed_harvest_receipt as receipt
import fleet_metrics_recovery_orchestrator as fleet_recovery
import metrics_harvest_runtime as runtime
import publication_metrics_catalog as catalog
import test_authorization_sealed_harvest_recovery as fixtures

FP1 = fixtures.FP1
FP2 = fixtures.FP2
collector = runtime.observed_metrics_collector


def persist_catalog(root: Path, ch: dict, publication: dict) -> dict:
    value = catalog.empty_catalog(ch)
    descriptor = copy.deepcopy(publication)
    descriptor["descriptor_fingerprint_sha256"] = catalog._descriptor_fingerprint(descriptor)
    value["records"][descriptor["publication_id"]] = descriptor
    value["catalog_fingerprint_sha256"] = catalog._catalog_fingerprint(value)
    path = root / catalog.expected_catalog_path(ch)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checked = catalog.validate_catalog(ch, value)
    assert checked["valid"] is True, checked
    return value


def read_checkpoint(root: Path, ch: dict) -> dict:
    return json.loads(
        (root / runtime.expected_checkpoint_state_path(ch)).read_text(encoding="utf-8")
    )


def make_ready_recovery(root: Path, ch: dict, *, fp: str = FP1) -> dict:
    jb = fixtures.job(ch)
    persist_catalog(root, ch, jb["publication"])
    fixtures.make_recovery(root, ch, jb, fp)
    return jb


def test_exact_durable_observation_is_auto_reconciled_without_network() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "RECOVERY_RECONCILED", result
        assert result["recovered_count"] == 1, result
        assert result["unresolved_count"] == 0, result
        assert result["provider_reread_authorized"] is False, result
        state = read_checkpoint(root, ch)
        entry = next(iter(state["entries"].values()))
        assert entry["status"] == "COMPLETED", entry
        assert (
            entry["execution_receipts"][-1]["recovery_evidence"]["kind"]
            == "EXACT_ATTEMPT_OBSERVATION"
        ), entry


def test_later_cumulative_observation_can_close_recovery() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T11:00:00Z")

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T11:05:00Z"
        )
        assert result["status"] == "RECOVERY_RECONCILED", result
        evidence = result["results"][0]["recovery_evidence"]
        assert evidence["kind"] == "CUMULATIVE_COVERAGE_OBSERVATION", result
        assert evidence["provider_reread_authorized"] is False, result


def test_missing_observation_remains_recovery_required_and_cannot_blind_retry() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        before = read_checkpoint(root, ch)

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        after = read_checkpoint(root, ch)
        assert result["status"] == "RECOVERY_UNRESOLVED", result
        assert result["unresolved_count"] == 1, result
        assert result["provider_reread_authorized"] is False, result
        assert before == after
        retry = receipt.claim_checkpoint_sealed(
            root,
            ch,
            jb,
            authorization_fingerprint=FP1,
            now="2026-08-16T10:21:00Z",
        )
        assert retry["claimed"] is False, retry
        assert retry["status"] == "RECOVERY_REQUIRED", retry


def test_fleet_layer_never_auto_authorizes_provider_reread() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        make_ready_recovery(root, ch)
        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T12:00:00Z"
        )
        assert result["provider_reread_authorized"] is False, result
        assert (
            fleet_recovery._guards()["provider_reread_authorized_automatically"] is False
        )
        entry = next(iter(read_checkpoint(root, ch)["entries"].values()))
        assert entry["status"] == "RECOVERY_REQUIRED", entry
        assert entry["retry_after_at"] is None, entry


def test_authorization_drift_holds_before_any_reconciliation() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP2, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "RECOVERY_HOLD", result
        assert result["results"][0]["status"] == "HOLD_RECOVERY_AUTHORIZATION_CHANGED", result
        assert next(iter(read_checkpoint(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_receipt_tamper_fails_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        path = root / runtime.expected_checkpoint_state_path(ch)
        state = json.loads(path.read_text(encoding="utf-8"))
        entry = next(iter(state["entries"].values()))
        entry["execution_receipts"][-1]["updated_at"] = "2026-08-16T10:17:00Z"
        state["state_fingerprint_sha256"] = runtime._state_fingerprint(state)
        path.write_text(json.dumps(state), encoding="utf-8")

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "RECOVERY_HOLD", result
        assert result["results"][0]["status"] == "HOLD_RECOVERY_RECEIPT_TAMPERED", result
        assert "SEALED_RECEIPT_FINGERPRINT_MISMATCH" in result["hard_blocks"], result


def test_observation_store_tamper_holds_before_completion() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        path = root / collector.expected_observation_store_path(ch)
        store = json.loads(path.read_text(encoding="utf-8"))
        store["observations"][0]["metrics"]["impressions"] = 999999
        path.write_text(json.dumps(store), encoding="utf-8")

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "HOLD_RECOVERY_OBSERVATION_LEDGER", result
        assert next(iter(read_checkpoint(root, ch)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_catalog_remote_proof_conflict_is_fail_closed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        wrong = copy.deepcopy(jb["publication"])
        wrong["remote_publication_id"] = "remote_conflict"
        persist_catalog(root, ch, wrong)

        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "RECOVERY_HOLD", result
        assert "RECOVERY_ENTRY_REMOTE_PUBLICATION_ID_MISMATCH" in result["hard_blocks"], result


def test_no_recovery_checkpoint_is_clean_noop() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "NO_RECOVERY_REQUIRED", result
        assert result["recovery_required_count"] == 0, result
        assert result["durable_paths"] == [], result


def write_fleet_files(root: Path, ch: dict) -> tuple[dict, dict]:
    instance_id = ch["instance_id"]
    instance_root = instance_id
    config_rel = f"{instance_root}/social/channels/{ch['platform']}.json"
    registry_rel = f"{instance_root}/social/channel_registry.json"
    config_path = root / config_rel
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(ch), encoding="utf-8")
    registry = {
        "instance_id": instance_id,
        "channels": [
            {
                "channel_id": ch["channel_id"],
                "config": config_rel,
            }
        ],
    }
    registry_path = root / registry_rel
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry), encoding="utf-8")
    runtime_registry = {
        "instances": [
            {
                "instance_id": instance_id,
                "instance_root": instance_root,
                "channel_registry": registry_rel,
            }
        ]
    }
    sealed_plan = {
        "authorization_seal_status": "AUTHORIZATION_SEAL_READY",
        "workflow_matrix": [
            {
                "binding_id": f"{instance_id}-metrics",
                "instance_id": instance_id,
                "authorization_fingerprint": FP1,
            }
        ],
    }
    return runtime_registry, sealed_plan


def test_fleet_plan_discovers_and_reconciles_bound_instance_channel() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        runtime_registry, sealed_plan = write_fleet_files(root, ch)

        result = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "FLEET_RECOVERY_RECONCILED", result
        assert result["recovered_count"] == 1, result
        assert result["unresolved_count"] == 0, result
        assert result["provider_reread_authorized"] is False, result
        assert result["guards"]["provider_network_calls_performed"] is False, result
        assert result["guards"]["recovery_runs_before_normal_harvest"] is True, result
        assert result["publication_blocked"] is False, result


def test_fleet_unresolved_state_is_reported_without_secret_or_network_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        make_ready_recovery(root, ch)
        runtime_registry, sealed_plan = write_fleet_files(root, ch)

        first = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:20:00Z"
        )
        second = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:20:00Z"
        )
        assert first["status"] == "FLEET_RECOVERY_UNRESOLVED", first
        assert first == second, (first, second)
        encoded = json.dumps(first, sort_keys=True).lower()
        assert "access_token" not in encoded
        assert "secret_value" not in encoded
        assert first["guards"]["credential_values_read"] is False, first
        assert first["guards"]["provider_network_calls_performed"] is False, first


def test_fleet_instance_isolation_does_not_touch_other_instance_state() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        alpha = fixtures.channel(instance="alpha")
        beta = fixtures.channel(instance="beta")
        alpha_job = make_ready_recovery(root, alpha)
        make_ready_recovery(root, beta)
        fixtures.persist_observation(root, alpha, alpha_job, "2026-08-16T10:00:00Z")
        before_beta = read_checkpoint(root, beta)

        runtime_registry, sealed_plan = write_fleet_files(root, alpha)
        result = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:20:00Z"
        )
        assert result["recovered_count"] == 1, result
        assert read_checkpoint(root, beta) == before_beta
        assert next(iter(read_checkpoint(root, beta)["entries"].values()))["status"] == "RECOVERY_REQUIRED"


def test_invalid_sealed_plan_is_fail_closed_but_never_blocks_publication() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        result = fleet_recovery.reconcile_fleet_from_plan(
            Path(tmp),
            {"instances": []},
            {"authorization_seal_status": "AUTHORIZATION_SEAL_HOLD", "workflow_matrix": []},
            now="2026-08-16T10:20:00Z",
        )
        assert result["status"] == "FLEET_RECOVERY_HOLD", result
        assert result["publication_blocked"] is False, result
        assert result["guards"]["zero_paid_dependency"] is True, result


def test_zero_paid_policy_is_mandatory() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel(zero_paid_dependency=False)
        result = fleet_recovery.reconcile_channel_recoveries(
            root, ch, authorization_fingerprint=FP1, now="2026-08-16T10:20:00Z"
        )
        assert result["status"] == "HOLD_RECOVERY_POLICY", result
        assert "ZERO_PAID_DEPENDENCY_VIOLATION" in result["hard_blocks"], result
        assert result["publication_blocked"] is False, result


def test_recovered_checkpoint_is_idempotent_on_second_fleet_pass() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        ch = fixtures.channel()
        jb = make_ready_recovery(root, ch)
        fixtures.persist_observation(root, ch, jb, "2026-08-16T10:00:00Z")
        runtime_registry, sealed_plan = write_fleet_files(root, ch)

        first = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:20:00Z"
        )
        state_after_first = read_checkpoint(root, ch)
        second = fleet_recovery.reconcile_fleet_from_plan(
            root, runtime_registry, sealed_plan, now="2026-08-16T10:21:00Z"
        )
        state_after_second = read_checkpoint(root, ch)
        assert first["status"] == "FLEET_RECOVERY_RECONCILED", first
        assert second["status"] == "FLEET_RECOVERY_IDLE", second
        assert state_after_first == state_after_second


def main() -> None:
    tests = [
        value
        for name, value in sorted(globals().items())
        if name.startswith("test_") and callable(value)
    ]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} fleet recovery acceptance tests passed")


if __name__ == "__main__":
    main()
