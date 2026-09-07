from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.authorization_receipt_validator import (
    AuthorizationReceiptValidatorHold,
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    READ_ONLY_GATE,
    PUBLISH_GATE,
    STATE,
    _synthetic_submission,
    compile_authorization_receipt_validator,
    compile_immutable_authorization_receipt,
    simulate_control_promotion_dry_run,
    validate_authorization_receipt_validator_contract,
    validate_control_promotion_dry_run_receipt,
    validate_immutable_authorization_receipt,
)
from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.control_plane_authorization_intake import (
    compile_control_plane_authorization_intake,
    validate_authorization_submission_shape,
)


class CP62AuthorizationReceiptValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(cls.root / "config" / "authorization_receipt_validator_policy.json")
        cls.cp61_policy = load_json(cls.root / "config" / "control_plane_authorization_intake_policy.json")

    def setUp(self) -> None:
        self.contract = compile_authorization_receipt_validator(self.root, deepcopy(self.policy))
        self.cp61 = compile_control_plane_authorization_intake(self.root, deepcopy(self.cp61_policy))
        self.shape = validate_authorization_submission_shape(self.cp61, _synthetic_submission(self.cp61))
        self.receipt = compile_immutable_authorization_receipt(self.cp61, self.shape, synthetic_fixture=True)
        self.dry_run = simulate_control_promotion_dry_run(self.receipt)

    def test_contract_compiles_deterministically(self) -> None:
        other = compile_authorization_receipt_validator(self.root, deepcopy(self.policy))
        self.assertEqual(self.contract.contract_id, other.contract_id)
        self.assertEqual(self.contract.contract_hash, other.contract_hash)
        self.assertEqual(self.contract.state, STATE)
        self.assertEqual(self.contract.checkpoint, CHECKPOINT)
        self.assertEqual(self.contract.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(self.contract.next_unit, NEXT_UNIT)

    def test_immutable_receipt_hash_binds_cp61_and_redacts_raw_operator_values(self) -> None:
        validate_immutable_authorization_receipt(self.cp61, self.shape, self.receipt)
        payload = json.dumps(self.receipt.to_dict(), sort_keys=True)
        self.assertEqual(self.receipt.cp61_contract_id, self.cp61.contract_id)
        self.assertEqual(self.receipt.cp61_shape_receipt_id, self.shape.receipt_id)
        self.assertNotIn(self.shape.authorizer_reference, payload)
        self.assertNotIn(_synthetic_submission(self.cp61)["nonce"], payload)
        self.assertEqual(len(self.receipt.authorizer_reference_sha256), 64)
        self.assertEqual(len(self.receipt.nonce_sha256), 64)
        self.assertTrue(self.receipt.immutable)
        self.assertFalse(self.receipt.authority_activated)
        self.assertFalse(self.receipt.control_promotion_allowed)

    def test_tampered_immutable_receipt_is_rejected(self) -> None:
        tampered = replace(self.receipt, authorization_evidence_sha256="b" * 64)
        with self.assertRaises(AuthorizationReceiptValidatorHold):
            validate_immutable_authorization_receipt(self.cp61, self.shape, tampered)

    def test_read_only_grant_dry_run_never_promotes_control_plane(self) -> None:
        validate_control_promotion_dry_run_receipt(self.receipt, self.dry_run)
        self.assertEqual(self.dry_run.gate_code, READ_ONLY_GATE)
        self.assertEqual(
            self.dry_run.outcome,
            "PASS_CP62_DRY_RUN_VALIDATED_RECEIPT_CANDIDATE_ONLY_NO_AUTHORITY",
        )
        self.assertTrue(self.dry_run.global_kill_switch_engaged)
        self.assertFalse(self.dry_run.registry_mutated)
        self.assertFalse(self.dry_run.runtime_policy_mutated)
        self.assertFalse(self.dry_run.network_attempted)
        self.assertFalse(self.dry_run.live_probe_attempted)
        self.assertFalse(self.dry_run.publish_attempted)
        self.assertFalse(self.dry_run.authority_activated)
        self.assertFalse(self.dry_run.promotion_committed)

    def _shape_for(self, gate_code: str, decision: str):
        template = next(item for item in self.cp61.intake_templates if item.gate_code == gate_code)
        suffix = "publish" if gate_code == PUBLISH_GATE else "readonly"
        submission = {
            "authorization_id": f"auth_cp62_{suffix}_001",
            "gate_code": gate_code,
            "decision": decision,
            "allowed_platforms": list(EXPECTED_ACTIVE),
            "scope": template.scope,
            "authorizer_reference": "HUMAN:CP62_SYNTHETIC_FIXTURE",
            "authorized_at": "2026-09-07T00:00:00Z",
            "expires_at": "2026-09-07T01:00:00Z",
            "authorization_evidence_sha256": "c" * 64,
            "cp60_packet_id": self.cp61.cp60_packet_id,
            "cp60_packet_hash": self.cp61.cp60_packet_hash,
            "nonce": f"cp62_{suffix}_nonce_0001",
        }
        return validate_authorization_submission_shape(self.cp61, submission)

    def test_publish_grant_stays_on_hold_in_dry_run(self) -> None:
        shape = self._shape_for(PUBLISH_GATE, "GRANT")
        receipt = compile_immutable_authorization_receipt(self.cp61, shape, synthetic_fixture=True)
        dry_run = simulate_control_promotion_dry_run(receipt)
        self.assertEqual(
            dry_run.outcome,
            "HOLD_PILOT_PUBLISH_REQUIRES_LIVE_EVIDENCE_AND_LATER_GATE",
        )
        self.assertFalse(dry_run.publish_attempted)
        self.assertFalse(dry_run.authority_activated)
        self.assertFalse(dry_run.promotion_committed)

    def test_deny_stays_on_hold_in_dry_run(self) -> None:
        shape = self._shape_for(READ_ONLY_GATE, "DENY")
        receipt = compile_immutable_authorization_receipt(self.cp61, shape, synthetic_fixture=True)
        dry_run = simulate_control_promotion_dry_run(receipt)
        self.assertEqual(dry_run.outcome, "HOLD_EXTERNAL_AUTHORIZATION_DENIED_NO_AUTHORITY")
        self.assertFalse(dry_run.authority_activated)
        self.assertFalse(dry_run.promotion_committed)

    def test_dry_run_side_effect_tamper_is_rejected(self) -> None:
        tampered = replace(self.dry_run, network_attempted=True)
        with self.assertRaises(AuthorizationReceiptValidatorHold):
            validate_control_promotion_dry_run_receipt(self.receipt, tampered)

    def test_policy_guard_cannot_relax_network_boundary(self) -> None:
        policy = deepcopy(self.policy)
        policy["receipt_contract"]["network_forbidden"] = False
        with self.assertRaises(AuthorizationReceiptValidatorHold):
            compile_authorization_receipt_validator(self.root, policy)

    def test_global_checkpoint_remains_cp58_and_lanes_remain_canonical(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M31_AUTHORIZATION_RECEIPT_VALIDATOR"],
            "CP62_AUTHORIZATION_RECEIPT_VALIDATOR_DRY_RUN_LOCAL_ONLY_CONTROL_PROMOTION_HOLD",
        )
        self.assertEqual(self.contract.active_platforms, EXPECTED_ACTIVE)

    def test_contract_is_zero_authority_and_zero_external_io(self) -> None:
        validate_authorization_receipt_validator_contract(self.contract)
        self.assertTrue(self.contract.global_kill_switch_engaged)
        for field in (
            "external_authorization_ingested",
            "live_evidence_captured",
            "secret_reference_resolved",
            "environment_read",
            "keychain_read",
            "oauth_attempted",
            "real_account_lookup_attempted",
            "account_connected",
            "network_attempted",
            "live_probe_attempted",
            "publish_attempted",
            "external_write_performed",
            "control_plane_promoted",
            "deploy_performed",
            "paid_service_used",
            "authority_activated",
        ):
            self.assertFalse(getattr(self.contract, field), field)


if __name__ == "__main__":
    unittest.main()
