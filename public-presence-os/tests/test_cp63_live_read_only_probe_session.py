from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.authorization_receipt_validator import compile_authorization_receipt_validator
from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_session import (
    ALLOWED_METHODS,
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    LiveReadOnlyProbeSessionHold,
    compile_live_read_only_probe_session,
    compile_probe_session_envelope,
    record_zero_write_dry_run,
    validate_live_read_only_probe_session_contract,
    validate_probe_session_envelope,
    validate_zero_write_recorder,
)


class CP63LiveReadOnlyProbeSessionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(cls.root / "config" / "live_read_only_probe_session_policy.json")
        cls.cp62_policy = load_json(cls.root / "config" / "authorization_receipt_validator_policy.json")
        cls.cp56_policy = load_json(cls.root / "config" / "meta_live_read_only_probe_policy.json")

    def setUp(self) -> None:
        self.contract = compile_live_read_only_probe_session(self.root, deepcopy(self.policy))
        self.cp62 = compile_authorization_receipt_validator(self.root, deepcopy(self.cp62_policy))
        self.envelope = compile_probe_session_envelope(self.cp62, deepcopy(self.cp56_policy))
        self.recorder = record_zero_write_dry_run(self.envelope)

    def test_contract_compiles_deterministically(self) -> None:
        other = compile_live_read_only_probe_session(self.root, deepcopy(self.policy))
        self.assertEqual(self.contract.contract_id, other.contract_id)
        self.assertEqual(self.contract.contract_hash, other.contract_hash)
        self.assertEqual(self.contract.state, STATE)
        self.assertEqual(self.contract.checkpoint, CHECKPOINT)
        self.assertEqual(self.contract.next_unit, NEXT_UNIT)

    def test_envelope_is_exactly_bound_to_cp62(self) -> None:
        validate_probe_session_envelope(self.cp62, self.cp56_policy, self.envelope)
        self.assertEqual(self.envelope.cp62_contract_id, self.cp62.contract_id)
        self.assertEqual(self.envelope.cp62_contract_hash, self.cp62.contract_hash)
        self.assertEqual(self.envelope.cp62_immutable_receipt_id, self.cp62.immutable_receipt_id)
        self.assertEqual(self.envelope.cp62_immutable_receipt_hash, self.cp62.immutable_receipt_hash)
        self.assertEqual(self.envelope.cp62_dry_run_id, self.cp62.dry_run_id)
        self.assertEqual(self.envelope.cp62_dry_run_hash, self.cp62.dry_run_hash)

    def test_envelope_uses_only_get_and_synthetic_endpoint_labels(self) -> None:
        self.assertEqual(self.envelope.allowed_methods, ALLOWED_METHODS)
        self.assertGreater(len(self.envelope.steps), 0)
        for step in self.envelope.steps:
            self.assertEqual(step.method, "GET")
            self.assertTrue(step.endpoint_label.startswith("SYNTHETIC_ENDPOINT::"))
            self.assertNotIn("://", step.endpoint_label)
        self.assertFalse(self.envelope.network_attempted)
        self.assertFalse(self.envelope.live_probe_attempted)

    def test_cp56_probe_classes_and_evidence_codes_are_preserved(self) -> None:
        expected_step_count = sum(
            len(self.cp56_policy["platform_probe_classes"][platform])
            for platform in EXPECTED_ACTIVE
        )
        self.assertEqual(len(self.envelope.steps), expected_step_count)
        self.assertEqual(
            self.envelope.evidence_codes,
            tuple(self.cp56_policy["required_evidence_codes"]),
        )
        self.assertIn("ZERO_WRITE_CONFIRMATION", self.envelope.evidence_codes)

    def test_mutating_method_tamper_is_fail_closed(self) -> None:
        bad_step = replace(self.envelope.steps[0], method="POST")
        tampered = replace(self.envelope, steps=(bad_step,) + self.envelope.steps[1:])
        with self.assertRaises(LiveReadOnlyProbeSessionHold):
            validate_probe_session_envelope(self.cp62, self.cp56_policy, tampered)

    def test_real_url_tamper_is_fail_closed(self) -> None:
        bad_step = replace(self.envelope.steps[0], endpoint_label="https://graph.example.invalid/me")
        tampered = replace(self.envelope, steps=(bad_step,) + self.envelope.steps[1:])
        with self.assertRaises(LiveReadOnlyProbeSessionHold):
            validate_probe_session_envelope(self.cp62, self.cp56_policy, tampered)

    def test_zero_write_recorder_is_deterministic_and_all_counters_are_zero(self) -> None:
        other = record_zero_write_dry_run(self.envelope)
        validate_zero_write_recorder(self.envelope, self.recorder)
        self.assertEqual(self.recorder.recorder_id, other.recorder_id)
        self.assertEqual(self.recorder.recorder_hash, other.recorder_hash)
        self.assertTrue(self.recorder.zero_write_proof)
        self.assertEqual(self.recorder.write_attempt_count, 0)
        self.assertEqual(self.recorder.mutating_method_count, 0)
        self.assertEqual(self.recorder.network_attempt_count, 0)
        self.assertEqual(self.recorder.secret_material_count, 0)
        self.assertEqual(self.recorder.external_write_count, 0)
        self.assertEqual(self.recorder.total_events, len(self.envelope.steps))

    def test_recorder_event_side_effect_tamper_is_rejected(self) -> None:
        bad_event = replace(self.recorder.events[0], network_attempted=True)
        tampered = replace(self.recorder, events=(bad_event,) + self.recorder.events[1:])
        with self.assertRaises(LiveReadOnlyProbeSessionHold):
            validate_zero_write_recorder(self.envelope, tampered)

    def test_recorder_persists_only_fingerprints_not_request_or_response_payloads(self) -> None:
        payload = json.dumps(self.recorder.to_dict(), sort_keys=True)
        self.assertNotIn("access_token", payload.lower())
        self.assertNotIn("authorization:", payload.lower())
        for event in self.recorder.events:
            self.assertEqual(len(event.request_fingerprint_sha256), 64)
            self.assertEqual(len(event.response_fingerprint_sha256), 64)
            self.assertFalse(event.raw_secret_present)
            self.assertFalse(event.external_write_performed)

    def test_policy_cannot_relax_network_boundary(self) -> None:
        policy = deepcopy(self.policy)
        policy["session_envelope"]["network_forbidden"] = False
        with self.assertRaises(LiveReadOnlyProbeSessionHold):
            compile_live_read_only_probe_session(self.root, policy)

    def test_global_checkpoint_and_contract_remain_zero_authority(self) -> None:
        validate_live_read_only_probe_session_contract(self.contract)
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M32_LIVE_READ_ONLY_PROBE_SESSION"],
            "CP63_SESSION_ENVELOPE_ZERO_WRITE_RECORDER_DRY_RUN_LOCAL_ONLY_LIVE_HOLD",
        )
        self.assertEqual(self.contract.active_platforms, EXPECTED_ACTIVE)
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
