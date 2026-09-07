from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_activation_precondition import (
    CHECKPOINT,
    MATRIX_ROWS,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    LiveReadOnlyProbeAuthorityActivationPreconditionHold,
    compile_live_read_only_probe_authority_activation_precondition_matrix,
    evaluate_from_root,
    validate_authority_activation_precondition_matrix,
    validate_live_read_only_probe_authority_activation_precondition_contract,
)
from public_presence_os.live_read_only_probe_session_authorization_receipt import (
    compile_live_read_only_probe_session_authorization_receipt,
)


class CP69LiveReadOnlyProbeAuthorityActivationPreconditionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_activation_precondition_policy.json"
        )

    def test_contract_compiles_deterministically_and_keeps_cp58_control(self) -> None:
        first = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_authority_activation_precondition_contract(first)

    def test_matrix_is_exact_cp68_bound_structurally_complete_and_zero_authority(self) -> None:
        matrix = evaluate_from_root(self.root, deepcopy(self.policy))
        cp68 = compile_live_read_only_probe_session_authorization_receipt(
            self.root,
            load_json(self.root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json"),
        )
        self.assertEqual(matrix.cp68_contract_id, cp68.contract_id)
        self.assertEqual(matrix.cp68_contract_hash, cp68.contract_hash)
        self.assertEqual(matrix.receipt_id, cp68.receipt_id)
        self.assertEqual(matrix.receipt_hash, cp68.receipt_hash)
        self.assertEqual(matrix.dry_run_id, cp68.dry_run_id)
        self.assertEqual(matrix.dry_run_hash, cp68.dry_run_hash)
        self.assertEqual(tuple(row.name for row in matrix.rows), MATRIX_ROWS)
        self.assertTrue(matrix.all_structural_preconditions_satisfied)
        self.assertTrue(all(row.satisfied for row in matrix.rows))
        self.assertEqual(matrix.outcome, "STRUCTURAL_PRECONDITIONS_SATISFIED_CANDIDATE_ONLY_NO_AUTHORITY")
        self.assertTrue(matrix.synthetic_fixture)
        self.assertTrue(matrix.global_kill_switch_engaged)
        self.assertTrue(matrix.zero_io_observed)
        for field in (
            "runtime_authorization_effective", "authority_activated", "network_allowed",
            "live_probe_allowed", "account_connection_allowed", "publish_allowed",
            "external_write_allowed", "deploy_allowed", "control_plane_promoted",
        ):
            self.assertFalse(getattr(matrix, field), field)

    def test_evaluation_time_is_injected_and_outside_window_holds_without_activation(self) -> None:
        matrix = evaluate_from_root(
            self.root, deepcopy(self.policy), evaluated_at_utc="2030-01-01T02:00:00Z"
        )
        rows = {row.name: row.satisfied for row in matrix.rows}
        self.assertFalse(rows["EVALUATION_TIME_WITHIN_RECEIPT_WINDOW"])
        self.assertFalse(matrix.all_structural_preconditions_satisfied)
        self.assertEqual(matrix.outcome, "HOLD_PRECONDITION_MATRIX_UNSATISFIED_NO_AUTHORITY")
        self.assertFalse(matrix.authority_activated)
        self.assertFalse(matrix.network_allowed)

    def test_policy_drift_that_weakens_zero_io_or_authority_fails_closed(self) -> None:
        cases = []
        weak_network = deepcopy(self.policy)
        weak_network["evaluation"]["network_forbidden"] = False
        cases.append(weak_network)
        weak_kill = deepcopy(self.policy)
        weak_kill["evaluation"]["global_kill_switch_must_remain_engaged"] = False
        cases.append(weak_kill)
        weak_authority = deepcopy(self.policy)
        weak_authority["authority"]["network_allowed"] = True
        cases.append(weak_authority)
        method = deepcopy(self.policy)
        method["evaluation"]["method_allowlist"] = ["GET", "POST"]
        cases.append(method)
        for bad in cases:
            with self.assertRaises(LiveReadOnlyProbeAuthorityActivationPreconditionHold):
                compile_live_read_only_probe_authority_activation_precondition_matrix(
                    self.root, bad
                )

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
        with self.assertRaises(LiveReadOnlyProbeAuthorityActivationPreconditionHold):
            compile_live_read_only_probe_authority_activation_precondition_matrix(
                self.root, bad
            )

    def test_matrix_hash_tampering_fails_closed(self) -> None:
        matrix = evaluate_from_root(self.root, deepcopy(self.policy))
        cp68 = compile_live_read_only_probe_session_authorization_receipt(
            self.root,
            load_json(self.root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json"),
        )
        with self.assertRaises(LiveReadOnlyProbeAuthorityActivationPreconditionHold):
            validate_authority_activation_precondition_matrix(
                replace(matrix, authority_activated=True), cp68,
                _ReceiptView(matrix), _DryRunView(matrix),
            )

    def test_registry_records_m38_but_global_checkpoint_stays_cp58(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M38_LIVE_READ_ONLY_PROBE_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX"],
            "CP69_AUTHORITY_ACTIVATION_PRECONDITION_MATRIX_ZERO_IO_DRY_RUN_LOCAL_ONLY_LIVE_HOLD",
        )
        self.assertEqual(tuple(self.policy["matrix_rows"]), MATRIX_ROWS)
        self.assertEqual(tuple(self.policy["required_blockers"]), REQUIRED_BLOCKERS)

    def test_contract_never_claims_real_authorization_or_external_side_effects(self) -> None:
        contract = compile_live_read_only_probe_authority_activation_precondition_matrix(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.synthetic_validation_only)
        for field in (
            "external_authorization_ingested", "authorization_granted",
            "runtime_authorization_effective", "secret_reference_resolved",
            "environment_read", "keychain_read", "oauth_attempted",
            "real_account_lookup_attempted", "account_connected", "network_allowed",
            "network_attempted", "live_probe_allowed", "live_probe_attempted",
            "publish_allowed", "publish_attempted", "external_write_allowed",
            "external_write_performed", "control_plane_promoted", "deploy_allowed",
            "deploy_performed", "paid_service_used", "authority_activated",
        ):
            self.assertFalse(getattr(contract, field), field)


class _ReceiptView:
    def __init__(self, matrix):
        self.receipt_id = matrix.receipt_id
        self.receipt_hash = matrix.receipt_hash


class _DryRunView:
    def __init__(self, matrix):
        self.dry_run_id = matrix.dry_run_id
        self.dry_run_hash = matrix.dry_run_hash


if __name__ == "__main__":
    unittest.main()
