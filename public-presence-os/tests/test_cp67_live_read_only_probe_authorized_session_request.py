from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authorized_session_request import (
    ALLOWED_METHODS,
    CHECKPOINT,
    DECISION_VALUES,
    FUTURE_RECEIPT_SCHEMA,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUESTED_SCOPE,
    REQUIRED_BLOCKERS,
    REQUIRED_HANDOFF_FIELDS,
    STATE,
    LiveReadOnlyProbeAuthorizedSessionRequestHold,
    build_authorized_session_request_packet,
    build_operator_authorization_handoff,
    compile_live_read_only_probe_authorized_session_request,
    validate_authorized_session_request_packet,
    validate_live_read_only_probe_authorized_session_request_contract,
    validate_operator_authorization_handoff,
)
from public_presence_os.live_read_only_probe_single_session_harness import (
    compile_live_read_only_probe_single_session_harness,
)


class CP67LiveReadOnlyProbeAuthorizedSessionRequestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authorized_session_request_policy.json"
        )
        cls.cp66_policy = load_json(
            cls.root / "config" / "live_read_only_probe_single_session_harness_policy.json"
        )

    def setUp(self) -> None:
        self.cp66 = compile_live_read_only_probe_single_session_harness(
            self.root, deepcopy(self.cp66_policy)
        )
        self.packet = build_authorized_session_request_packet(self.cp66)
        self.handoff = build_operator_authorization_handoff(self.packet, self.cp66)

    def test_contract_compiles_deterministically(self) -> None:
        first = compile_live_read_only_probe_authorized_session_request(
            self.root, deepcopy(self.policy)
        )
        second = compile_live_read_only_probe_authorized_session_request(
            self.root, deepcopy(self.policy)
        )
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_authorized_session_request_contract(first)

    def test_request_is_exact_cp66_bound_and_not_authorization(self) -> None:
        self.assertEqual(self.packet.cp66_contract_id, self.cp66.contract_id)
        self.assertEqual(self.packet.cp66_contract_hash, self.cp66.contract_hash)
        self.assertEqual(self.packet.cp66_harness_run_id, self.cp66.harness_run_id)
        self.assertEqual(self.packet.cp66_harness_run_hash, self.cp66.harness_run_hash)
        self.assertEqual(self.packet.active_platforms, EXPECTED_ACTIVE)
        self.assertEqual(self.packet.method_allowlist, ALLOWED_METHODS)
        self.assertEqual(self.packet.authorization_gate, "LIVE_READ_ONLY_CONNECTION_PROBE")
        self.assertEqual(self.packet.requested_scope, REQUESTED_SCOPE)
        self.assertEqual(self.packet.requested_session_count, 1)
        self.assertEqual(self.packet.authorization_state, "REQUEST_NOT_GRANTED")
        self.assertTrue(self.packet.request_is_not_authorization)
        self.assertTrue(self.packet.external_human_authorization_required)
        self.assertFalse(self.packet.external_authorization_present)
        self.assertFalse(self.packet.authorization_granted)

    def test_operator_handoff_defines_future_receipt_without_grant_material(self) -> None:
        self.assertEqual(self.handoff.request_id, self.packet.request_id)
        self.assertEqual(self.handoff.request_hash, self.packet.request_hash)
        self.assertEqual(self.handoff.decision_values, DECISION_VALUES)
        self.assertEqual(self.handoff.required_fields, REQUIRED_HANDOFF_FIELDS)
        self.assertEqual(self.handoff.future_receipt_schema, FUTURE_RECEIPT_SCHEMA)
        self.assertTrue(self.handoff.operator_only)
        self.assertTrue(self.handoff.decision_required)
        self.assertTrue(self.handoff.no_grant_material_embedded)
        self.assertTrue(self.handoff.no_automatic_promotion)
        self.assertFalse(self.handoff.authorization_present)
        self.assertFalse(self.handoff.authorization_granted)

    def test_packet_and_handoff_contain_no_raw_credentials_urls_or_account_ids(self) -> None:
        rendered = json.dumps(
            {"packet": self.packet.to_dict(), "handoff": self.handoff.to_dict()},
            sort_keys=True,
        ).lower()
        for forbidden in (
            "access_token",
            "refresh_token",
            "client_secret",
            "authorization:",
            "bearer ",
            "http://",
            "https://",
            "page_id",
            "instagram_account_id",
            "threads_user_id",
        ):
            self.assertNotIn(forbidden, rendered)

    def test_tampered_request_or_handoff_fails_closed(self) -> None:
        bad_request = replace(self.packet, cp66_contract_hash="0" * 64)
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            validate_authorized_session_request_packet(bad_request, self.cp66)

        bad_handoff = replace(self.handoff, authorization_granted=True)
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            validate_operator_authorization_handoff(bad_handoff, self.packet, self.cp66)

    def test_policy_cannot_embed_grant_or_enable_live_boundaries(self) -> None:
        for section, key in (
            ("request_packet", "authorization_must_remain_absent_in_cp67"),
            ("request_packet", "network_forbidden"),
            ("request_packet", "live_probe_execution_forbidden"),
            ("operator_handoff", "no_automatic_promotion"),
        ):
            bad = deepcopy(self.policy)
            bad[section][key] = False
            with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
                compile_live_read_only_probe_authorized_session_request(self.root, bad)

        bad_authority = deepcopy(self.policy)
        bad_authority["authority"]["authorization_granted"] = True
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            compile_live_read_only_probe_authorized_session_request(self.root, bad_authority)

    def test_policy_rejects_sensitive_fields_urls_lane_and_method_drift(self) -> None:
        bad_secret = deepcopy(self.policy)
        bad_secret["request_packet"]["access_token"] = "synthetic-but-forbidden"
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            compile_live_read_only_probe_authorized_session_request(self.root, bad_secret)

        bad_url = deepcopy(self.policy)
        bad_url["request_packet"]["endpoint"] = "https://graph.example.invalid"
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            compile_live_read_only_probe_authorized_session_request(self.root, bad_url)

        bad_lane = deepcopy(self.policy)
        bad_lane["active_platforms"].append("LINKEDIN")
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            compile_live_read_only_probe_authorized_session_request(self.root, bad_lane)

        bad_method = deepcopy(self.policy)
        bad_method["request_packet"]["method_allowlist"] = ["GET", "POST"]
        with self.assertRaises(LiveReadOnlyProbeAuthorizedSessionRequestHold):
            compile_live_read_only_probe_authorized_session_request(self.root, bad_method)

    def test_contract_remains_zero_authority_and_zero_io(self) -> None:
        contract = compile_live_read_only_probe_authorized_session_request(
            self.root, deepcopy(self.policy)
        )
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.request_is_not_authorization)
        self.assertTrue(contract.external_human_authorization_required)
        for field in (
            "external_authorization_ingested",
            "authorization_granted",
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

    def test_global_checkpoint_remains_cp58_and_m36_is_registered(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M36_LIVE_READ_ONLY_PROBE_AUTHORIZED_SESSION_REQUEST"],
            "CP67_AUTHORIZED_SESSION_REQUEST_PACKET_HANDOFF_LOCAL_ONLY_AUTHORIZATION_NOT_GRANTED_LIVE_HOLD",
        )
        self.assertEqual(REQUIRED_BLOCKERS[-2:], (
            "HOLD_CP67_REQUEST_IS_NOT_AUTHORIZATION",
            "HOLD_CP67_OPERATOR_DECISION_NOT_PRESENT",
        ))


if __name__ == "__main__":
    unittest.main()
