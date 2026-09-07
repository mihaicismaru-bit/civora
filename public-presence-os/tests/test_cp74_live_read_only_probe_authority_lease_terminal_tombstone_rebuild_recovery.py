from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    RECOVERY_CASES,
    RECOVERY_PHASES,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold,
    _build_cp73_dry_run,
    build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery,
    validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract,
)
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_reconciliation import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation,
)


class CP74TerminalTombstoneRebuildRecoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_policy.json"
        )
        cls.cp73_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json"
        )

    def parent_fixture(self):
        cp73 = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(
            self.root, deepcopy(self.cp73_policy)
        )
        return cp73, _build_cp73_dry_run(self.root, cp73)

    def test_contract_is_deterministic_and_control_checkpoint_stays_cp58(self) -> None:
        a = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(
            self.root, deepcopy(self.policy)
        )
        b = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual((a.contract_id, a.contract_hash), (b.contract_id, b.contract_hash))
        self.assertEqual(
            (a.checkpoint, a.parent_control_checkpoint, a.state, a.next_unit),
            (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, STATE, NEXT_UNIT),
        )
        validate_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery_contract(a)

    def test_missing_and_corrupted_tombstones_rebuild_exactly(self) -> None:
        cp73, cp73_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(cp73, cp73_dry)
        self.assertEqual(dry.phases, RECOVERY_PHASES)
        self.assertEqual(tuple((x.scenario, x.failure_mode) for x in dry.recovery_cases), RECOVERY_CASES)
        originals = {
            "EXPIRY_PATH": cp73_dry.expiry_tombstone,
            "REVOCATION_PATH": cp73_dry.revocation_tombstone,
        }
        for case in dry.recovery_cases:
            self.assertTrue(case.exact_rebuild)
            self.assertEqual(case.rebuilt_tombstone.to_dict(), originals[case.scenario].to_dict())
            self.assertFalse(case.storage_write_performed)
            self.assertFalse(case.runtime_mutated)
            if case.failure_mode == "MISSING_TOMBSTONE":
                self.assertIsNone(case.observed_tombstone_hash)
            else:
                self.assertNotEqual(case.observed_tombstone_hash, case.original_tombstone_hash)
        validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(dry, cp73, cp73_dry)

    def test_tampered_rebuild_or_storage_write_fails_closed(self) -> None:
        cp73, cp73_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(cp73, cp73_dry)
        first = dry.recovery_cases[0]
        bad_rebuild = replace(first.rebuilt_tombstone, terminal_state="REVOKED")
        bad_case = replace(first, rebuilt_tombstone=bad_rebuild)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold):
            validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(
                replace(dry, recovery_cases=(bad_case,) + dry.recovery_cases[1:]),
                cp73,
                cp73_dry,
            )
        write_case = replace(first, storage_write_performed=True)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold):
            validate_authority_lease_terminal_tombstone_rebuild_recovery_dry_run(
                replace(dry, recovery_cases=(write_case,) + dry.recovery_cases[1:]),
                cp73,
                cp73_dry,
            )

    def test_policy_weakening_and_lane_drift_fail_closed(self) -> None:
        bads = []
        for key in (
            "recovery_source_ledger_only",
            "terminal_entry_unique_required",
            "missing_tombstone_rebuild_required",
            "corrupted_tombstone_rebuild_required",
            "exact_original_tombstone_hash_reproduction_required",
            "simulated_restore_only",
            "storage_write_forbidden",
            "zero_io_required",
        ):
            bad = deepcopy(self.policy)
            bad["recovery_guard"][key] = False
            bads.append(bad)
        bad_method = deepcopy(self.policy)
        bad_method["recovery_guard"]["method_allowlist"] = ["GET", "POST"]
        bads.append(bad_method)
        bad_lane = deepcopy(self.policy)
        bad_lane["active_platforms"].append("LINKEDIN")
        bads.append(bad_lane)
        for bad in bads:
            with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRebuildRecoveryHold):
                compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(self.root, bad)

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
            states["M43_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY"],
            "CP74_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_REBUILD_RECOVERY_DRY_RUN_LOCAL_ONLY_EXACT_REBUILD_NO_RUNTIME_AUTHORITY_LIVE_HOLD",
        )

    def test_contract_never_claims_live_authority_or_side_effects(self) -> None:
        c = compile_live_read_only_probe_authority_lease_terminal_tombstone_rebuild_recovery(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(c.global_kill_switch_engaged)
        self.assertTrue(c.exact_rebuild_validated)
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
