from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_evidence_import import (
    compile_live_read_only_probe_evidence_import,
)
from public_presence_os.live_read_only_probe_execution_admission import (
    ALLOWED_METHODS,
    AUTHORIZATION_GATE,
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    LiveReadOnlyProbeExecutionAdmissionHold,
    build_operator_preflight_packet,
    compile_live_read_only_probe_execution_admission,
    evaluate_execution_admission,
    validate_execution_admission_receipt,
    validate_live_read_only_probe_execution_admission_contract,
    validate_operator_preflight_packet,
)


class CP65LiveReadOnlyProbeExecutionAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_execution_admission_policy.json"
        )
        cls.cp64_policy = load_json(
            cls.root / "config" / "live_read_only_probe_evidence_import_policy.json"
        )

    def setUp(self) -> None:
        self.cp64 = compile_live_read_only_probe_evidence_import(
            self.root, deepcopy(self.cp64_policy)
        )
        self.packet = build_operator_preflight_packet(self.cp64)
        self.admission = evaluate_execution_admission(self.packet, self.cp64)

    def test_contract_compiles_deterministically(self) -> None:
        first = compile_live_read_only_probe_execution_admission(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_execution_admission(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.next_unit, NEXT_UNIT)

    def test_preflight_packet_is_exact_cp64_bound_and_deterministic(self) -> None:
        other = build_operator_preflight_packet(self.cp64)
        self.assertEqual(self.packet.packet_id, other.packet_id)
        self.assertEqual(self.packet.packet_hash, other.packet_hash)
        self.assertEqual(self.packet.cp64_contract_id, self.cp64.contract_id)
        self.assertEqual(self.packet.cp64_contract_hash, self.cp64.contract_hash)
        self.assertEqual(
            self.packet.cp64_evidence_import_hash, self.cp64.evidence_import_hash
        )
        self.assertEqual(
            self.packet.cp64_replay_validation_hash, self.cp64.replay_validation_hash
        )

    def test_packet_keeps_exact_lanes_get_only_and_kill_switch(self) -> None:
        self.assertEqual(self.packet.active_platforms, EXPECTED_ACTIVE)
        self.assertEqual(self.packet.authorization_gate, AUTHORIZATION_GATE)
        self.assertEqual(self.packet.method_allowlist, ALLOWED_METHODS)
        self.assertEqual(self.packet.method_allowlist, ("GET",))
        self.assertTrue(self.packet.global_kill_switch_engaged)
        self.assertTrue(self.packet.zero_write_required)
        self.assertTrue(self.packet.immutable)
        self.assertFalse(self.packet.network_allowed)

    def test_admission_is_structurally_ready_but_explicitly_held(self) -> None:
        self.assertTrue(self.admission.structural_readiness_validated)
        self.assertTrue(self.admission.preflight_packet_validated)
        self.assertTrue(self.admission.get_only_validated)
        self.assertTrue(self.admission.zero_write_validated)
        self.assertFalse(self.admission.external_authorization_present)
        self.assertFalse(self.admission.admission_granted)
        self.assertFalse(self.admission.live_probe_allowed)
        self.assertFalse(self.admission.network_allowed)
        self.assertFalse(self.admission.authority_activated)
        self.assertEqual(
            self.admission.state,
            "HOLD_EXTERNAL_HUMAN_AUTHORIZATION_REQUIRED_NO_EXECUTION",
        )

    def test_packet_contains_no_raw_credentials_or_urls(self) -> None:
        rendered = json.dumps(self.packet.to_dict(), sort_keys=True).lower()
        for forbidden in (
            "access_token",
            "refresh_token",
            "client_secret",
            "authorization:",
            "bearer ",
            "http://",
            "https://",
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn("reference_only_not_resolved_no_values", rendered)

    def test_policy_cannot_relax_external_authorization_requirement(self) -> None:
        bad = deepcopy(self.policy)
        bad["admission_gate"]["external_human_authorization_required"] = False
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            compile_live_read_only_probe_execution_admission(self.root, bad)

    def test_policy_cannot_enable_network_or_live_execution(self) -> None:
        bad_network = deepcopy(self.policy)
        bad_network["admission_gate"]["network_forbidden_in_cp65"] = False
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            compile_live_read_only_probe_execution_admission(self.root, bad_network)

        bad_live = deepcopy(self.policy)
        bad_live["admission_gate"]["live_probe_execution_forbidden_in_cp65"] = False
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            compile_live_read_only_probe_execution_admission(self.root, bad_live)

    def test_policy_cannot_change_method_allowlist_or_lane_set(self) -> None:
        bad_method = deepcopy(self.policy)
        bad_method["admission_gate"]["method_allowlist"] = ["GET", "POST"]
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            compile_live_read_only_probe_execution_admission(self.root, bad_method)

        bad_lane = deepcopy(self.policy)
        bad_lane["active_platforms"].append("LINKEDIN")
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            compile_live_read_only_probe_execution_admission(self.root, bad_lane)

    def test_preflight_cp64_hash_tamper_is_fail_closed(self) -> None:
        bad = replace(self.packet, cp64_contract_hash="0" * 64)
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            validate_operator_preflight_packet(bad, self.cp64)

    def test_preflight_method_or_kill_switch_tamper_is_fail_closed(self) -> None:
        bad_method = replace(self.packet, method_allowlist=("GET", "POST"))
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            validate_operator_preflight_packet(bad_method, self.cp64)

        bad_kill = replace(self.packet, global_kill_switch_engaged=False)
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            validate_operator_preflight_packet(bad_kill, self.cp64)

    def test_admission_cannot_be_flipped_to_granted_or_network_allowed(self) -> None:
        bad_grant = replace(self.admission, admission_granted=True)
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            validate_execution_admission_receipt(bad_grant, self.packet, self.cp64)

        bad_network = replace(self.admission, network_allowed=True)
        with self.assertRaises(LiveReadOnlyProbeExecutionAdmissionHold):
            validate_execution_admission_receipt(bad_network, self.packet, self.cp64)

    def test_contract_remains_zero_authority_and_zero_io(self) -> None:
        contract = compile_live_read_only_probe_execution_admission(
            self.root, deepcopy(self.policy)
        )
        validate_live_read_only_probe_execution_admission_contract(contract)
        self.assertTrue(contract.external_human_authorization_required)
        self.assertTrue(contract.global_kill_switch_engaged)
        for field in (
            "external_authorization_ingested",
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
            "control_plane_promoted",
            "deploy_allowed",
            "deploy_performed",
            "paid_service_used",
            "authority_activated",
        ):
            self.assertFalse(getattr(contract, field), field)

    def test_global_checkpoint_remains_cp58_and_m34_is_registered(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M34_LIVE_READ_ONLY_PROBE_EXECUTION_ADMISSION"],
            "CP65_EXECUTION_ADMISSION_PREFLIGHT_PACKET_LOCAL_ONLY_AUTHORIZATION_REQUIRED_LIVE_HOLD",
        )
        self.assertEqual(self.admission.blockers, REQUIRED_BLOCKERS)


if __name__ == "__main__":
    unittest.main()
