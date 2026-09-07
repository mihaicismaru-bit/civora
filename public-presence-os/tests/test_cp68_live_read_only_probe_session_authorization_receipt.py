from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import json
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authorized_session_request import (
    FUTURE_RECEIPT_SCHEMA,
    REQUESTED_SCOPE,
    build_authorized_session_request_packet,
    build_operator_authorization_handoff,
    compile_live_read_only_probe_authorized_session_request,
)
from public_presence_os.live_read_only_probe_single_session_harness import (
    compile_live_read_only_probe_single_session_harness,
)
from public_presence_os.live_read_only_probe_session_authorization_receipt import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    RECEIPT_INPUT_FIELDS,
    REQUIRED_BLOCKERS,
    STATE,
    LiveReadOnlyProbeSessionAuthorizationReceiptHold,
    build_activation_dry_run,
    compile_immutable_session_authorization_receipt,
    compile_live_read_only_probe_session_authorization_receipt,
    validate_activation_dry_run,
    validate_immutable_session_authorization_receipt,
    validate_live_read_only_probe_session_authorization_receipt_contract,
    validate_session_authorization_submission,
)


class CP68LiveReadOnlyProbeSessionAuthorizationReceiptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_session_authorization_receipt_policy.json"
        )
        cls.cp67_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authorized_session_request_policy.json"
        )
        cls.cp66_policy = load_json(
            cls.root / "config" / "live_read_only_probe_single_session_harness_policy.json"
        )

    def setUp(self) -> None:
        self.cp67 = compile_live_read_only_probe_authorized_session_request(
            self.root, deepcopy(self.cp67_policy)
        )
        cp66 = compile_live_read_only_probe_single_session_harness(
            self.root, deepcopy(self.cp66_policy)
        )
        self.packet = build_authorized_session_request_packet(cp66)
        self.handoff = build_operator_authorization_handoff(self.packet, cp66)
        self.submission = {
            "schema_version": FUTURE_RECEIPT_SCHEMA,
            "request_id": self.packet.request_id,
            "request_hash": self.packet.request_hash,
            "handoff_id": self.handoff.handoff_id,
            "handoff_hash": self.handoff.handoff_hash,
            "decision": "GRANT",
            "scope": REQUESTED_SCOPE,
            "platform_subset": list(EXPECTED_ACTIVE),
            "valid_from_utc": "2030-01-01T00:00:00Z",
            "valid_until_utc": "2030-01-01T01:00:00Z",
            "human_reference_sha256": sha256(b"human").hexdigest(),
            "evidence_sha256": sha256(b"evidence").hexdigest(),
            "nonce": "cp68-test-nonce-0001",
        }

    def test_contract_compiles_deterministically_and_keeps_cp58_control(self) -> None:
        first = compile_live_read_only_probe_session_authorization_receipt(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_session_authorization_receipt(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_session_authorization_receipt_contract(first)

    def test_grant_submission_is_shape_validated_and_nonce_is_hash_only_in_receipt(self) -> None:
        normalized = validate_session_authorization_submission(
            deepcopy(self.submission), self.cp67, self.packet, self.handoff
        )
        self.assertEqual(normalized["decision"], "GRANT")
        self.assertEqual(normalized["platform_subset"], EXPECTED_ACTIVE)
        self.assertNotIn("nonce", normalized)
        self.assertEqual(
            normalized["nonce_sha256"],
            sha256(self.submission["nonce"].encode()).hexdigest(),
        )
        receipt = compile_immutable_session_authorization_receipt(
            self.cp67, self.packet, self.handoff, deepcopy(self.submission),
            synthetic_fixture=False,
        )
        rendered = json.dumps(receipt.to_dict(), sort_keys=True)
        self.assertNotIn(self.submission["nonce"], rendered)
        self.assertFalse(receipt.runtime_authorization_effective)
        self.assertFalse(receipt.authority_activated)
        validate_immutable_session_authorization_receipt(receipt, self.cp67)

    def test_grant_and_deny_dry_runs_never_activate_authority(self) -> None:
        grant_receipt = compile_immutable_session_authorization_receipt(
            self.cp67, self.packet, self.handoff, deepcopy(self.submission),
            synthetic_fixture=True,
        )
        grant = build_activation_dry_run(grant_receipt, self.cp67)
        self.assertEqual(
            grant.outcome,
            "VALIDATED_GRANT_CANDIDATE_ONLY_ZERO_IO_NO_AUTHORITY",
        )
        self.assertFalse(grant.authority_activated)
        self.assertFalse(grant.promotion_committed)
        validate_activation_dry_run(grant, grant_receipt)

        deny_submission = deepcopy(self.submission)
        deny_submission["decision"] = "DENY"
        deny_receipt = compile_immutable_session_authorization_receipt(
            self.cp67, self.packet, self.handoff, deny_submission,
            synthetic_fixture=True,
        )
        deny = build_activation_dry_run(deny_receipt, self.cp67)
        self.assertEqual(deny.outcome, "HOLD_EXTERNAL_AUTHORIZATION_DENIED")
        self.assertFalse(deny.authority_activated)

    def test_exact_field_set_parent_hash_scope_lane_and_time_drift_fail_closed(self) -> None:
        cases = []
        extra = deepcopy(self.submission); extra["extra"] = "forbidden"; cases.append(extra)
        parent = deepcopy(self.submission); parent["request_hash"] = "0" * 64; cases.append(parent)
        scope = deepcopy(self.submission); scope["scope"] = "PILOT_PUBLISH"; cases.append(scope)
        lane = deepcopy(self.submission); lane["platform_subset"] = ["LINKEDIN"]; cases.append(lane)
        duplicate = deepcopy(self.submission); duplicate["platform_subset"] = ["FACEBOOK_PAGE", "FACEBOOK_PAGE"]; cases.append(duplicate)
        time = deepcopy(self.submission); time["valid_until_utc"] = time["valid_from_utc"]; cases.append(time)
        for bad in cases:
            with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
                validate_session_authorization_submission(
                    bad, self.cp67, self.packet, self.handoff
                )

    def test_raw_url_credentials_and_account_identifiers_fail_closed(self) -> None:
        bad_url = deepcopy(self.submission)
        bad_url["nonce"] = "https://example.invalid"
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            validate_session_authorization_submission(
                bad_url, self.cp67, self.packet, self.handoff
            )

        bad_secret = deepcopy(self.submission)
        bad_secret["access_token"] = "forbidden"
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            validate_session_authorization_submission(
                bad_secret, self.cp67, self.packet, self.handoff
            )

        bad_policy = deepcopy(self.policy)
        bad_policy["receipt_intake"]["account_id"] = "forbidden"
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            compile_live_read_only_probe_session_authorization_receipt(
                self.root, bad_policy
            )

    def test_policy_cannot_enable_network_authority_or_control_promotion(self) -> None:
        for section, key in (
            ("receipt_intake", "network_forbidden"),
            ("receipt_intake", "grant_does_not_activate_runtime_authority"),
            ("activation_dry_run", "authority_activation_forbidden"),
            ("activation_dry_run", "promotion_commit_forbidden"),
        ):
            bad = deepcopy(self.policy)
            bad[section][key] = False
            with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
                compile_live_read_only_probe_session_authorization_receipt(
                    self.root, bad
                )

        bad_authority = deepcopy(self.policy)
        bad_authority["authority"]["network_allowed"] = True
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            compile_live_read_only_probe_session_authorization_receipt(
                self.root, bad_authority
            )

    def test_tampered_immutable_receipt_and_dry_run_fail_closed(self) -> None:
        receipt = compile_immutable_session_authorization_receipt(
            self.cp67, self.packet, self.handoff, deepcopy(self.submission),
            synthetic_fixture=True,
        )
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            validate_immutable_session_authorization_receipt(
                replace(receipt, authority_activated=True), self.cp67
            )
        dry = build_activation_dry_run(receipt, self.cp67)
        with self.assertRaises(LiveReadOnlyProbeSessionAuthorizationReceiptHold):
            validate_activation_dry_run(
                replace(dry, network_attempted=True), receipt
            )

    def test_contract_is_zero_io_zero_authority_and_registry_keeps_cp58(self) -> None:
        contract = compile_live_read_only_probe_session_authorization_receipt(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(contract.global_kill_switch_engaged)
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

        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M37_LIVE_READ_ONLY_PROBE_SESSION_AUTHORIZATION_RECEIPT"],
            "CP68_SESSION_AUTHORIZATION_RECEIPT_INTAKE_VALIDATOR_DRY_RUN_LOCAL_ONLY_AUTHORITY_NOT_ACTIVATED_LIVE_HOLD",
        )
        self.assertEqual(tuple(self.policy["receipt_intake"]["input_fields"]), RECEIPT_INPUT_FIELDS)
        self.assertEqual(tuple(self.policy["required_blockers"]), REQUIRED_BLOCKERS)


if __name__ == "__main__":
    unittest.main()
