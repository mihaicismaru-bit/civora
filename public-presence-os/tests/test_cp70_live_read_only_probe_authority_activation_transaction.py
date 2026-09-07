from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_activation_precondition import (
    compile_live_read_only_probe_authority_activation_precondition_matrix,
    evaluate_from_root as evaluate_cp69_from_root,
)
from public_presence_os.live_read_only_probe_authority_activation_transaction import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    TRANSACTION_PHASES,
    LiveReadOnlyProbeAuthorityActivationTransactionHold,
    build_authority_activation_transaction_dry_run,
    compile_live_read_only_probe_authority_activation_transaction,
    validate_authority_activation_transaction_dry_run,
    validate_live_read_only_probe_authority_activation_transaction_contract,
)


class CP70LiveReadOnlyProbeAuthorityActivationTransactionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_activation_transaction_policy.json"
        )
        cls.cp69_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_activation_precondition_policy.json"
        )

    def test_contract_compiles_deterministically_and_keeps_cp58_control(self) -> None:
        first = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.policy))
        second = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.policy))
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_authority_activation_transaction_contract(first)

    def test_transaction_is_exact_cp69_bound_and_all_phases_pass(self) -> None:
        contract = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.policy))
        cp69_contract = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.cp69_policy)
        )
        cp69_matrix = evaluate_cp69_from_root(self.root, deepcopy(self.cp69_policy))
        self.assertEqual((contract.cp69_contract_id, contract.cp69_contract_hash), (cp69_contract.contract_id, cp69_contract.contract_hash))
        self.assertEqual((contract.cp69_matrix_id, contract.cp69_matrix_hash), (cp69_matrix.matrix_id, cp69_matrix.matrix_hash))

        baseline = {
            "global_kill_switch_engaged": True,
            "network_enabled": False,
            "account_connection_enabled": False,
            "publish_enabled": False,
            "deploy_enabled": False,
            "control_checkpoint": PARENT_CONTROL_CHECKPOINT,
            "environment_reads": 0,
            "keychain_reads": 0,
            "oauth_attempts": 0,
            "real_account_lookups": 0,
            "network_attempts": 0,
            "live_probe_attempts": 0,
            "publish_attempts": 0,
            "external_writes": 0,
            "deploy_attempts": 0,
            "paid_service_uses": 0,
        }
        transaction = build_authority_activation_transaction_dry_run(
            cp69_contract, cp69_matrix, baseline_snapshot=baseline
        )
        self.assertEqual(tuple(row.name for row in transaction.phases), TRANSACTION_PHASES)
        self.assertTrue(all(row.satisfied for row in transaction.phases))
        self.assertTrue(transaction.prepare_passed)
        self.assertTrue(transaction.commit_simulated)
        self.assertTrue(transaction.rollback_simulated)
        self.assertTrue(transaction.rollback_exact)
        self.assertEqual(transaction.baseline_snapshot_sha256, transaction.rollback_snapshot_sha256)
        self.assertEqual(transaction.outcome, "SIMULATED_PREPARE_COMMIT_ROLLBACK_PASS_NO_AUTHORITY_NO_MUTATION")
        validate_authority_activation_transaction_dry_run(transaction, cp69_contract, cp69_matrix)

    def test_policy_drift_that_weakens_transaction_guards_fails_closed(self) -> None:
        cases = []
        weak_zero_io = deepcopy(self.policy)
        weak_zero_io["transaction"]["zero_io_required"] = False
        cases.append(weak_zero_io)
        weak_commit = deepcopy(self.policy)
        weak_commit["transaction"]["commit_simulation_required"] = False
        cases.append(weak_commit)
        weak_mutation = deepcopy(self.policy)
        weak_mutation["transaction"]["runtime_mutation_forbidden"] = False
        cases.append(weak_mutation)
        weak_authority = deepcopy(self.policy)
        weak_authority["authority"]["authority_activated"] = True
        cases.append(weak_authority)
        method = deepcopy(self.policy)
        method["transaction"]["method_allowlist"] = ["GET", "POST"]
        cases.append(method)
        for bad in cases:
            with self.assertRaises(LiveReadOnlyProbeAuthorityActivationTransactionHold):
                compile_live_read_only_probe_authority_activation_transaction(self.root, bad)

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
        with self.assertRaises(LiveReadOnlyProbeAuthorityActivationTransactionHold):
            compile_live_read_only_probe_authority_activation_transaction(self.root, bad)

    def test_transaction_tampering_to_runtime_authority_fails_closed(self) -> None:
        cp69_contract = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.cp69_policy)
        )
        cp69_matrix = evaluate_cp69_from_root(self.root, deepcopy(self.cp69_policy))
        baseline = {
            "global_kill_switch_engaged": True,
            "network_enabled": False,
            "account_connection_enabled": False,
            "publish_enabled": False,
            "deploy_enabled": False,
            "control_checkpoint": PARENT_CONTROL_CHECKPOINT,
            "environment_reads": 0,
            "keychain_reads": 0,
            "oauth_attempts": 0,
            "real_account_lookups": 0,
            "network_attempts": 0,
            "live_probe_attempts": 0,
            "publish_attempts": 0,
            "external_writes": 0,
            "deploy_attempts": 0,
            "paid_service_uses": 0,
        }
        transaction = build_authority_activation_transaction_dry_run(
            cp69_contract, cp69_matrix, baseline_snapshot=baseline
        )
        with self.assertRaises(LiveReadOnlyProbeAuthorityActivationTransactionHold):
            validate_authority_activation_transaction_dry_run(
                replace(transaction, authority_activated=True), cp69_contract, cp69_matrix
            )

    def test_nonzero_io_baseline_fails_closed(self) -> None:
        cp69_contract = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.cp69_policy)
        )
        cp69_matrix = evaluate_cp69_from_root(self.root, deepcopy(self.cp69_policy))
        baseline = {
            "global_kill_switch_engaged": True,
            "network_enabled": False,
            "account_connection_enabled": False,
            "publish_enabled": False,
            "deploy_enabled": False,
            "control_checkpoint": PARENT_CONTROL_CHECKPOINT,
            "environment_reads": 0,
            "keychain_reads": 0,
            "oauth_attempts": 0,
            "real_account_lookups": 0,
            "network_attempts": 1,
            "live_probe_attempts": 0,
            "publish_attempts": 0,
            "external_writes": 0,
            "deploy_attempts": 0,
            "paid_service_uses": 0,
        }
        with self.assertRaises(LiveReadOnlyProbeAuthorityActivationTransactionHold):
            build_authority_activation_transaction_dry_run(
                cp69_contract, cp69_matrix, baseline_snapshot=baseline
            )

    def test_registry_records_m39_but_global_checkpoint_stays_cp58(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M39_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_TRANSACTION"],
            "CP70_AUTHORITY_ACTIVATION_TRANSACTION_DRY_RUN_LOCAL_ONLY_NO_COMMIT_LIVE_HOLD",
        )
        self.assertEqual(tuple(self.policy["transaction_phases"]), TRANSACTION_PHASES)
        self.assertEqual(tuple(self.policy["required_blockers"]), REQUIRED_BLOCKERS)

    def test_contract_never_claims_authority_or_side_effects(self) -> None:
        contract = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.policy))
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.synthetic_validation_only)
        self.assertTrue(contract.transaction_validated)
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
