from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_expiry_revocation import (
    compile_live_read_only_probe_authority_lease_expiry_revocation,
)
from public_presence_os.live_read_only_probe_authority_lease_replay_stale_receipt import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REPLAY_PHASES,
    REQUIRED_BLOCKERS,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold,
    build_authority_lease_replay_stale_receipt_dry_run,
    compile_live_read_only_probe_authority_lease_replay_stale_receipt,
    validate_authority_lease_replay_stale_receipt_dry_run,
    validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract,
)


class CP72LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json"
        )
        cls.cp71_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json"
        )

    def test_contract_compiles_deterministically_and_keeps_cp58_control(self) -> None:
        first = compile_live_read_only_probe_authority_lease_replay_stale_receipt(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_authority_lease_replay_stale_receipt(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_authority_lease_replay_stale_receipt_contract(first)

    def test_dry_run_is_exact_cp71_bound_and_rejects_replay_and_stale_receipts(self) -> None:
        cp71_contract = compile_live_read_only_probe_authority_lease_expiry_revocation(
            self.root, deepcopy(self.cp71_policy)
        )
        dry_run = build_authority_lease_replay_stale_receipt_dry_run(cp71_contract)
        self.assertEqual(
            (dry_run.cp71_contract_id, dry_run.cp71_contract_hash),
            (cp71_contract.contract_id, cp71_contract.contract_hash),
        )
        self.assertEqual(
            (dry_run.cp71_dry_run_id, dry_run.cp71_dry_run_hash),
            (cp71_contract.dry_run_id, cp71_contract.dry_run_hash),
        )
        self.assertEqual(
            (dry_run.lease_id, dry_run.lease_hash),
            (cp71_contract.lease_id, cp71_contract.lease_hash),
        )
        self.assertEqual(tuple(row.name for row in dry_run.phases), REPLAY_PHASES)
        self.assertTrue(all(row.satisfied for row in dry_run.phases))
        self.assertTrue(dry_run.expiry_terminal_accepted_once)
        self.assertTrue(dry_run.expiry_exact_replay_rejected)
        self.assertTrue(dry_run.expiry_stale_active_rejected)
        self.assertTrue(dry_run.revocation_terminal_accepted_once)
        self.assertTrue(dry_run.revocation_exact_replay_rejected)
        self.assertTrue(dry_run.revocation_stale_active_rejected)
        self.assertTrue(dry_run.terminal_state_resurrection_rejected)
        self.assertEqual(
            dry_run.outcome,
            "SIMULATED_REPLAY_STALE_RECEIPT_REJECTION_PASS_NO_AUTHORITY_NO_RESURRECTION_NO_MUTATION",
        )
        validate_authority_lease_replay_stale_receipt_dry_run(dry_run, cp71_contract)

    def test_policy_drift_that_weakens_replay_or_stale_guards_fails_closed(self) -> None:
        cases = []
        weak_replay = deepcopy(self.policy)
        weak_replay["receipt_guard"]["exact_replay_rejection_required"] = False
        cases.append(weak_replay)
        weak_stale = deepcopy(self.policy)
        weak_stale["receipt_guard"]["stale_receipt_rejection_required"] = False
        cases.append(weak_stale)
        weak_resurrection = deepcopy(self.policy)
        weak_resurrection["receipt_guard"]["terminal_state_resurrection_forbidden"] = False
        cases.append(weak_resurrection)
        weak_single_acceptance = deepcopy(self.policy)
        weak_single_acceptance["receipt_guard"]["terminal_receipt_single_acceptance_required"] = False
        cases.append(weak_single_acceptance)
        weak_zero_io = deepcopy(self.policy)
        weak_zero_io["receipt_guard"]["zero_io_required"] = False
        cases.append(weak_zero_io)
        method = deepcopy(self.policy)
        method["receipt_guard"]["method_allowlist"] = ["GET", "POST"]
        cases.append(method)
        for bad in cases:
            with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
                compile_live_read_only_probe_authority_lease_replay_stale_receipt(self.root, bad)

    def test_clock_and_terminal_state_policy_drift_fails_closed(self) -> None:
        bad_clock = deepcopy(self.policy)
        bad_clock["receipt_guard"]["synthetic_pre_revocation_at_utc"] = "2030-01-01T00:04:58Z"
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            compile_live_read_only_probe_authority_lease_replay_stale_receipt(self.root, bad_clock)
        bad_states = deepcopy(self.policy)
        bad_states["receipt_guard"]["terminal_states"] = ["EXPIRED"]
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            compile_live_read_only_probe_authority_lease_replay_stale_receipt(self.root, bad_states)

    def test_active_lane_and_deferred_lane_canon_is_locked(self) -> None:
        self.assertEqual(tuple(self.policy["active_platforms"]), EXPECTED_ACTIVE)
        self.assertEqual(
            self.policy["excluded_platforms"],
            {
                "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
                "X": "EXCLUDED_WHILE_API_IS_PAID",
                "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
            },
        )
        bad = deepcopy(self.policy)
        bad["active_platforms"].append("LINKEDIN")
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            compile_live_read_only_probe_authority_lease_replay_stale_receipt(self.root, bad)

    def test_dry_run_cannot_be_tampered_into_authority_or_receipt_reuse(self) -> None:
        cp71_contract = compile_live_read_only_probe_authority_lease_expiry_revocation(
            self.root, deepcopy(self.cp71_policy)
        )
        dry_run = build_authority_lease_replay_stale_receipt_dry_run(cp71_contract)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            validate_authority_lease_replay_stale_receipt_dry_run(
                replace(dry_run, authority_activated=True), cp71_contract
            )
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            validate_authority_lease_replay_stale_receipt_dry_run(
                replace(dry_run, expiry_exact_replay_rejected=False), cp71_contract
            )
        tampered_receipt = replace(dry_run.expiry_terminal_receipt, receipt_hash="0" * 64)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseReplayStaleReceiptHold):
            validate_authority_lease_replay_stale_receipt_dry_run(
                replace(dry_run, expiry_terminal_receipt=tampered_receipt), cp71_contract
            )

    def test_registry_records_m41_but_global_checkpoint_stays_cp58(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M41_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION"],
            "CP72_AUTHORITY_LEASE_REPLAY_STALE_RECEIPT_REJECTION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD",
        )
        self.assertEqual(tuple(self.policy["replay_phases"]), REPLAY_PHASES)
        self.assertEqual(tuple(self.policy["required_blockers"]), REQUIRED_BLOCKERS)

    def test_contract_never_claims_authority_or_side_effects(self) -> None:
        contract = compile_live_read_only_probe_authority_lease_replay_stale_receipt(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.replay_rejection_validated)
        self.assertTrue(contract.stale_receipt_rejection_validated)
        self.assertTrue(contract.terminal_resurrection_rejected)
        self.assertTrue(contract.terminal_receipt_single_acceptance_validated)
        self.assertTrue(contract.synthetic_validation_only)
        for field in (
            "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
            "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
            "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
            "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
            "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed",
            "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated",
            "registry_mutated", "policy_mutated",
        ):
            self.assertFalse(getattr(contract, field), field)


if __name__ == "__main__":
    unittest.main()
