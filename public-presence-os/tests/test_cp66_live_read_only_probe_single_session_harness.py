from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.authorization_receipt_validator import (
    compile_authorization_receipt_validator,
)
from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_evidence_import import (
    compile_live_read_only_probe_evidence_import,
)
from public_presence_os.live_read_only_probe_execution_admission import (
    build_operator_preflight_packet,
    compile_live_read_only_probe_execution_admission,
    evaluate_execution_admission,
)
from public_presence_os.live_read_only_probe_session import (
    compile_probe_session_envelope,
)
from public_presence_os.live_read_only_probe_single_session_harness import (
    ALLOWED_METHODS,
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    TRANSPORT_KIND,
    DeterministicMockTransport,
    LiveReadOnlyProbeSingleSessionHarnessHold,
    compile_live_read_only_probe_single_session_harness,
    run_single_session_harness,
    validate_live_read_only_probe_single_session_harness_contract,
    validate_single_session_harness_receipt,
)


class CP66LiveReadOnlyProbeSingleSessionHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_single_session_harness_policy.json"
        )
        cls.cp65_policy = load_json(
            cls.root / "config" / "live_read_only_probe_execution_admission_policy.json"
        )
        cls.cp64_policy = load_json(
            cls.root / "config" / "live_read_only_probe_evidence_import_policy.json"
        )
        cls.cp62_policy = load_json(
            cls.root / "config" / "authorization_receipt_validator_policy.json"
        )
        cls.cp56_policy = load_json(
            cls.root / "config" / "meta_live_read_only_probe_policy.json"
        )

    def setUp(self) -> None:
        self.cp65 = compile_live_read_only_probe_execution_admission(
            self.root, deepcopy(self.cp65_policy)
        )
        self.cp64 = compile_live_read_only_probe_evidence_import(
            self.root, deepcopy(self.cp64_policy)
        )
        self.cp62 = compile_authorization_receipt_validator(
            self.root, deepcopy(self.cp62_policy)
        )
        self.envelope = compile_probe_session_envelope(
            self.cp62, deepcopy(self.cp56_policy)
        )
        self.packet = build_operator_preflight_packet(self.cp64)
        self.admission = evaluate_execution_admission(self.packet, self.cp64)
        self.transport = DeterministicMockTransport()
        self.receipt = run_single_session_harness(
            self.cp65,
            self.cp64,
            self.packet,
            self.admission,
            self.envelope,
            self.transport,
        )

    def test_contract_compiles_deterministically(self) -> None:
        first = compile_live_read_only_probe_single_session_harness(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_single_session_harness(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_single_session_harness_contract(first)

    def test_harness_is_exact_parent_and_session_bound(self) -> None:
        self.assertEqual(self.receipt.cp65_contract_id, self.cp65.contract_id)
        self.assertEqual(self.receipt.cp65_contract_hash, self.cp65.contract_hash)
        self.assertEqual(self.receipt.preflight_packet_hash, self.packet.packet_hash)
        self.assertEqual(self.receipt.admission_hash, self.admission.admission_hash)
        self.assertEqual(self.receipt.session_envelope_id, self.envelope.envelope_id)
        self.assertEqual(self.receipt.session_envelope_hash, self.envelope.envelope_hash)

    def test_injected_transport_is_mock_only_get_only_and_zero_network(self) -> None:
        self.assertEqual(self.receipt.transport_kind, TRANSPORT_KIND)
        self.assertEqual(self.receipt.method_allowlist, ALLOWED_METHODS)
        self.assertEqual(self.receipt.method_allowlist, ("GET",))
        self.assertEqual(self.receipt.active_platforms, EXPECTED_ACTIVE)
        self.assertTrue(self.receipt.global_kill_switch_engaged)
        self.assertTrue(self.receipt.zero_network_proof)
        self.assertEqual(self.receipt.network_attempt_count, 0)
        self.assertFalse(self.receipt.live_probe_execution_performed)

    def test_exactly_one_transport_call_per_step_and_no_retry(self) -> None:
        self.assertEqual(self.receipt.expected_step_count, len(self.envelope.steps))
        self.assertEqual(self.receipt.executed_step_count, len(self.envelope.steps))
        self.assertEqual(self.receipt.transport_call_count, len(self.envelope.steps))
        self.assertEqual(self.transport.call_count, len(self.envelope.steps))
        self.assertEqual(self.receipt.retry_count, 0)
        self.assertTrue(self.receipt.zero_retry_proof)
        self.assertEqual(
            tuple(event.transport_call_index for event in self.receipt.events),
            tuple(range(1, len(self.envelope.steps) + 1)),
        )

    def test_trace_persists_fingerprints_not_payloads_or_credentials(self) -> None:
        rendered = json.dumps(self.receipt.to_dict(), sort_keys=True).lower()
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
        for event in self.receipt.events:
            self.assertEqual(len(event.request_fingerprint_sha256), 64)
            self.assertEqual(len(event.response_fingerprint_sha256), 64)
            self.assertTrue(event.endpoint_label.startswith("SYNTHETIC_ENDPOINT::"))

    def test_fault_injection_fails_closed_without_retry(self) -> None:
        transport = DeterministicMockTransport(fail_sequence=1)
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold) as ctx:
            run_single_session_harness(
                self.cp65,
                self.cp64,
                self.packet,
                self.admission,
                self.envelope,
                transport,
            )
        self.assertEqual(ctx.exception.reason, "HOLD_CP66_TRANSPORT_FAULT_FAIL_CLOSED")
        self.assertEqual(transport.call_count, 1)

    def test_network_capable_or_wrong_transport_is_rejected_before_execution(self) -> None:
        class UnsafeTransport:
            kind = "REAL_HTTP"
            network_capable = True
            call_count = 0

            def execute(self, request):  # pragma: no cover - must never be reached
                raise AssertionError("unsafe transport executed")

        unsafe = UnsafeTransport()
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            run_single_session_harness(
                self.cp65,
                self.cp64,
                self.packet,
                self.admission,
                self.envelope,
                unsafe,
            )
        self.assertEqual(unsafe.call_count, 0)

    def test_policy_cannot_enable_network_retry_or_live_execution(self) -> None:
        for key in (
            "network_forbidden",
            "automatic_retry_forbidden_in_cp66",
            "live_probe_execution_forbidden",
        ):
            bad = deepcopy(self.policy)
            bad["harness"][key] = False
            with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
                compile_live_read_only_probe_single_session_harness(self.root, bad)

    def test_policy_cannot_change_method_lane_or_transport_kind(self) -> None:
        bad_method = deepcopy(self.policy)
        bad_method["harness"]["method_allowlist"] = ["GET", "POST"]
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            compile_live_read_only_probe_single_session_harness(self.root, bad_method)

        bad_lane = deepcopy(self.policy)
        bad_lane["active_platforms"].append("LINKEDIN")
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            compile_live_read_only_probe_single_session_harness(self.root, bad_lane)

        bad_transport = deepcopy(self.policy)
        bad_transport["harness"]["transport_kind_must_equal"] = "REAL_HTTP"
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            compile_live_read_only_probe_single_session_harness(self.root, bad_transport)

    def test_receipt_tamper_is_fail_closed(self) -> None:
        bad_hash = replace(self.receipt, cp65_contract_hash="0" * 64)
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            validate_single_session_harness_receipt(
                bad_hash, self.cp65, self.packet, self.admission, self.envelope
            )

        bad_network = replace(self.receipt, network_attempt_count=1, zero_network_proof=False)
        with self.assertRaises(LiveReadOnlyProbeSingleSessionHarnessHold):
            validate_single_session_harness_receipt(
                bad_network, self.cp65, self.packet, self.admission, self.envelope
            )

    def test_contract_remains_zero_authority_and_zero_io(self) -> None:
        contract = compile_live_read_only_probe_single_session_harness(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.injected_mock_transport_validated)
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

    def test_global_checkpoint_remains_cp58_and_m35_is_registered(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M35_LIVE_READ_ONLY_PROBE_SINGLE_SESSION_HARNESS"],
            "CP66_SINGLE_SESSION_EXECUTION_HARNESS_DRY_RUN_MOCK_ONLY_LIVE_HOLD",
        )
        self.assertEqual(self.receipt.active_platforms, EXPECTED_ACTIVE)
        self.assertEqual(REQUIRED_BLOCKERS[-2:], (
            "HOLD_CP66_MOCK_TRANSPORT_ONLY",
            "HOLD_CP66_LIVE_EXECUTION_NOT_AUTHORIZED",
        ))


if __name__ == "__main__":
    unittest.main()
