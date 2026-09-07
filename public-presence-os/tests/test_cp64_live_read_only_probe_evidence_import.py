from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.authorization_receipt_validator import compile_authorization_receipt_validator
from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_evidence_import import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    LiveReadOnlyProbeEvidenceImportHold,
    build_synthetic_redacted_bundle,
    compile_live_read_only_probe_evidence_import,
    replay_imported_bundle,
    validate_and_import_evidence_bundle,
    validate_live_read_only_probe_evidence_import_contract,
)
from public_presence_os.live_read_only_probe_session import (
    compile_live_read_only_probe_session,
    compile_probe_session_envelope,
    record_zero_write_dry_run,
)


class CP64LiveReadOnlyProbeEvidenceImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(cls.root / "config" / "live_read_only_probe_evidence_import_policy.json")
        cls.cp63_policy = load_json(cls.root / "config" / "live_read_only_probe_session_policy.json")
        cls.cp62_policy = load_json(cls.root / "config" / "authorization_receipt_validator_policy.json")
        cls.cp56_policy = load_json(cls.root / "config" / "meta_live_read_only_probe_policy.json")

    def setUp(self) -> None:
        self.cp63 = compile_live_read_only_probe_session(self.root, deepcopy(self.cp63_policy))
        cp62 = compile_authorization_receipt_validator(self.root, deepcopy(self.cp62_policy))
        self.envelope = compile_probe_session_envelope(cp62, deepcopy(self.cp56_policy))
        self.recorder = record_zero_write_dry_run(self.envelope)
        self.bundle = build_synthetic_redacted_bundle(
            self.cp63,
            self.envelope,
            self.recorder,
            deepcopy(self.cp56_policy),
        )
        self.imported = validate_and_import_evidence_bundle(
            deepcopy(self.bundle),
            self.cp63,
            self.envelope,
            self.recorder,
            deepcopy(self.cp56_policy),
        )

    def test_contract_compiles_deterministically(self) -> None:
        first = compile_live_read_only_probe_evidence_import(self.root, deepcopy(self.policy))
        second = compile_live_read_only_probe_evidence_import(self.root, deepcopy(self.policy))
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.next_unit, NEXT_UNIT)

    def test_synthetic_bundle_preserves_exact_evidence_codes_and_trace(self) -> None:
        expected_codes = self.cp56_policy["required_evidence_codes"]
        self.assertEqual([item["code"] for item in self.bundle["evidence_items"]], expected_codes)
        self.assertEqual(len(self.bundle["replay_trace"]), len(self.envelope.steps))
        self.assertEqual(len(self.bundle["replay_trace"]), len(self.recorder.events))
        self.assertEqual(self.bundle["active_platforms"], list(EXPECTED_ACTIVE))
        self.assertFalse(self.bundle["live_evidence"])

    def test_import_receipt_is_hash_bound_and_zero_authority(self) -> None:
        other = validate_and_import_evidence_bundle(
            deepcopy(self.bundle), self.cp63, self.envelope, self.recorder, deepcopy(self.cp56_policy)
        )
        self.assertEqual(self.imported.import_id, other.import_id)
        self.assertEqual(self.imported.import_hash, other.import_hash)
        self.assertEqual(len(self.imported.bundle_sha256), 64)
        self.assertTrue(self.imported.redaction_validated)
        self.assertTrue(self.imported.hash_binding_validated)
        self.assertFalse(self.imported.live_evidence_imported)
        self.assertFalse(self.imported.network_attempted)
        self.assertFalse(self.imported.authority_activated)

    def test_replay_is_structural_deterministic_and_zero_io(self) -> None:
        replay = replay_imported_bundle(self.bundle, self.imported, self.envelope, self.recorder)
        other = replay_imported_bundle(self.bundle, self.imported, self.envelope, self.recorder)
        self.assertEqual(replay.replay_id, other.replay_id)
        self.assertEqual(replay.replay_hash, other.replay_hash)
        self.assertEqual(replay.matched_trace_count, len(self.envelope.steps))
        self.assertTrue(replay.structural_replay_validated)
        self.assertTrue(replay.get_only_validated)
        self.assertTrue(replay.zero_write_validated)
        self.assertTrue(replay.zero_network_validated)
        self.assertFalse(replay.live_execution_performed)

    def test_extra_sensitive_field_is_fail_closed(self) -> None:
        bad = deepcopy(self.bundle)
        bad["access_token"] = "synthetic-but-forbidden"
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_bearer_material_is_fail_closed(self) -> None:
        bad = deepcopy(self.bundle)
        bad["evidence_items"][0]["redacted_value_sha256"] = "Bearer not-allowed"
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_missing_or_duplicate_evidence_is_fail_closed(self) -> None:
        missing = deepcopy(self.bundle)
        missing["evidence_items"].pop()
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(missing, self.cp63, self.envelope, self.recorder, self.cp56_policy)
        duplicate = deepcopy(self.bundle)
        duplicate["evidence_items"][1] = deepcopy(duplicate["evidence_items"][0])
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(duplicate, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_mutating_method_and_real_url_are_fail_closed(self) -> None:
        bad_method = deepcopy(self.bundle)
        bad_method["replay_trace"][0]["method"] = "POST"
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad_method, self.cp63, self.envelope, self.recorder, self.cp56_policy)
        bad_url = deepcopy(self.bundle)
        bad_url["replay_trace"][0]["endpoint_label"] = "https://graph.example.invalid/me"
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad_url, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_parent_hash_tamper_is_fail_closed(self) -> None:
        bad = deepcopy(self.bundle)
        bad["cp63_contract_hash"] = "0" * 64
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_side_effect_counter_or_authority_claim_is_fail_closed(self) -> None:
        bad_counter = deepcopy(self.bundle)
        bad_counter["network_attempt_count"] = 1
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad_counter, self.cp63, self.envelope, self.recorder, self.cp56_policy)
        bad_authority = deepcopy(self.bundle)
        bad_authority["authority_claimed"] = True
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            validate_and_import_evidence_bundle(bad_authority, self.cp63, self.envelope, self.recorder, self.cp56_policy)

    def test_bundle_contains_only_hash_bound_redacted_material(self) -> None:
        rendered = json.dumps(self.bundle, sort_keys=True).lower()
        self.assertNotIn("access_token", rendered)
        self.assertNotIn("authorization:", rendered)
        self.assertNotIn("bearer ", rendered)
        for item in self.bundle["evidence_items"]:
            self.assertTrue(item["redacted"])
            self.assertFalse(item["live_captured"])
            self.assertEqual(len(item["redacted_value_sha256"]), 64)

    def test_policy_cannot_relax_network_or_live_evidence_boundary(self) -> None:
        network_relaxed = deepcopy(self.policy)
        network_relaxed["import_gate"]["network_forbidden"] = False
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            compile_live_read_only_probe_evidence_import(self.root, network_relaxed)
        live_relaxed = deepcopy(self.policy)
        live_relaxed["import_gate"]["live_evidence_import_forbidden_in_cp64"] = False
        with self.assertRaises(LiveReadOnlyProbeEvidenceImportHold):
            compile_live_read_only_probe_evidence_import(self.root, live_relaxed)

    def test_global_checkpoint_and_contract_remain_zero_authority(self) -> None:
        contract = compile_live_read_only_probe_evidence_import(self.root, deepcopy(self.policy))
        validate_live_read_only_probe_evidence_import_contract(contract)
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M33_LIVE_READ_ONLY_PROBE_EVIDENCE_IMPORT"],
            "CP64_EVIDENCE_IMPORT_GATE_REPLAY_VALIDATOR_DRY_RUN_LOCAL_ONLY_LIVE_HOLD",
        )
        self.assertEqual(contract.active_platforms, EXPECTED_ACTIVE)
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.synthetic_fixture_only)
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
            self.assertFalse(getattr(contract, field), field)


if __name__ == "__main__":
    unittest.main()
