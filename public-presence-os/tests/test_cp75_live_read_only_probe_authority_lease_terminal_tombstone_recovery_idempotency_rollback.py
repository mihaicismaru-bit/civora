from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery,
)
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    VALIDATION_CASES,
    VALIDATION_PHASES,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold,
    _build_cp74_dry_run,
    build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback,
    validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract,
)


class CP75TerminalTombstoneRecoveryIdempotencyRollbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json"
        )
        cls.cp74_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json"
        )

    def parent_fixture(self):
        cp74 = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(
            self.root, deepcopy(self.cp74_policy)
        )
        return cp74, _build_cp74_dry_run(self.root, cp74)

    def test_contract_is_deterministic_and_control_checkpoint_stays_cp58(self) -> None:
        a = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(
            self.root, deepcopy(self.policy)
        )
        b = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual((a.contract_id, a.contract_hash), (b.contract_id, b.contract_hash))
        self.assertEqual(
            (a.checkpoint, a.parent_control_checkpoint, a.state, a.next_unit),
            (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, STATE, NEXT_UNIT),
        )
        validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_contract(a)

    def test_all_recovery_cases_are_idempotent_and_rollback_exactly(self) -> None:
        cp74, cp74_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(cp74, cp74_dry)
        self.assertEqual(dry.phases, VALIDATION_PHASES)
        self.assertEqual(tuple((x.scenario, x.failure_mode) for x in dry.validation_cases), VALIDATION_CASES)
        for case in dry.validation_cases:
            self.assertTrue(case.idempotent)
            self.assertFalse(case.duplicate_recovery_effect_observed)
            self.assertTrue(case.rollback_exact)
            self.assertEqual(case.first_apply_proposal_hash, case.second_apply_proposal_hash)
            self.assertEqual(case.first_apply_result_hash, case.second_apply_result_hash)
            self.assertEqual(case.rollback_result_hash, case.baseline_snapshot_hash)
            self.assertEqual(case.simulated_apply_count, 2)
            self.assertFalse(case.storage_write_performed)
            self.assertFalse(case.runtime_mutated)
        validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(dry, cp74, cp74_dry)

    def test_duplicate_effect_or_rollback_drift_fails_closed(self) -> None:
        cp74, cp74_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(cp74, cp74_dry)
        first = dry.validation_cases[0]
        duplicate = replace(first, duplicate_recovery_effect_observed=True)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold):
            validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(
                replace(dry, validation_cases=(duplicate,) + dry.validation_cases[1:]), cp74, cp74_dry
            )
        rollback_drift = replace(first, rollback_result_hash=first.first_apply_result_hash)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold):
            validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(
                replace(dry, validation_cases=(rollback_drift,) + dry.validation_cases[1:]), cp74, cp74_dry
            )
        write_case = replace(first, storage_write_performed=True)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold):
            validate_authority_lease_terminal_tombstone_recovery_idempotency_rollback_dry_run(
                replace(dry, validation_cases=(write_case,) + dry.validation_cases[1:]), cp74, cp74_dry
            )

    def test_policy_weakening_and_lane_drift_fail_closed(self) -> None:
        bads = []
        for key in (
            "synthetic_cp74_recovery_only",
            "identical_recovery_replay_required",
            "duplicate_recovery_effect_forbidden",
            "rollback_baseline_exact_restore_required",
            "rollback_after_simulated_apply_only",
            "storage_write_forbidden",
            "zero_io_required",
        ):
            bad = deepcopy(self.policy)
            bad["idempotency_rollback_guard"][key] = False
            bads.append(bad)
        bad_method = deepcopy(self.policy)
        bad_method["idempotency_rollback_guard"]["method_allowlist"] = ["GET", "POST"]
        bads.append(bad_method)
        bad_lane = deepcopy(self.policy)
        bad_lane["active_platforms"].append("LINKEDIN")
        bads.append(bad_lane)
        for bad in bads:
            with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryIdempotencyRollbackHold):
                compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(self.root, bad)

    def test_canonical_lanes_and_registry_are_locked(self) -> None:
        self.assertEqual(tuple(self.policy["active_platforms"]), EXPECTED_ACTIVE)
        self.assertEqual(
            self.policy["excluded_platforms"],
            {
                "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
                "X": "EXCLUDED_WHILE_API_IS_PAID",
                "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
            },
        )
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {x["id"]: x["status"] for x in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M44_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK"],
            "CP75_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_IDEMPOTENCY_ROLLBACK_DRY_RUN_LOCAL_ONLY_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD",
        )

    def test_contract_never_claims_live_authority_or_side_effects(self) -> None:
        c = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(c.global_kill_switch_engaged)
        self.assertTrue(c.idempotency_validated)
        self.assertTrue(c.rollback_validated)
        self.assertTrue(c.simulated_recovery_only)
        for field in (
            "external_authorization_ingested",
            "authorization_granted",
            "runtime_authorization_effective",
            "secret_reference_resolved",
            "environment_read",
            "keychain_read",
            "oauth_attempted",
            "real_account_lookup_attempted",
            "account_connected",
            "network_allowed",
            "network_attempted",
            "live_probe_allowed",
            "live_probe_attempted",
            "publish_allowed",
            "publish_attempted",
            "external_write_allowed",
            "external_write_performed",
            "storage_write_allowed",
            "storage_write_performed",
            "control_plane_promoted",
            "deploy_allowed",
            "deploy_performed",
            "paid_service_used",
            "authority_activated",
            "runtime_mutated",
        ):
            self.assertFalse(getattr(c, field), field)


if __name__ == "__main__":
    unittest.main()
