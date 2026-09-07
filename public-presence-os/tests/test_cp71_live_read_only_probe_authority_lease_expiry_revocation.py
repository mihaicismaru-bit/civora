from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_activation_transaction import (
    compile_live_read_only_probe_authority_activation_transaction,
)
from public_presence_os.live_read_only_probe_authority_lease_expiry_revocation import (
    CHECKPOINT,
    LEASE_PHASES,
    LEASE_TTL_SECONDS,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    REQUIRED_BLOCKERS,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold,
    build_authority_lease_expiry_revocation_dry_run,
    compile_live_read_only_probe_authority_lease_expiry_revocation,
    validate_authority_lease_expiry_revocation_dry_run,
    validate_live_read_only_probe_authority_lease_expiry_revocation_contract,
)


class CP71LiveReadOnlyProbeAuthorityLeaseExpiryRevocationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json"
        )
        cls.cp70_policy = load_json(
            cls.root / "config" / "live_read_only_probe_authority_activation_transaction_policy.json"
        )

    def test_contract_compiles_deterministically_and_keeps_cp58_control(self) -> None:
        first = compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, deepcopy(self.policy))
        second = compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, deepcopy(self.policy))
        self.assertEqual(first.contract_id, second.contract_id)
        self.assertEqual(first.contract_hash, second.contract_hash)
        self.assertEqual(first.checkpoint, CHECKPOINT)
        self.assertEqual(first.parent_control_checkpoint, PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(first.state, STATE)
        self.assertEqual(first.next_unit, NEXT_UNIT)
        validate_live_read_only_probe_authority_lease_expiry_revocation_contract(first)

    def test_dry_run_is_exact_cp70_bound_and_covers_expiry_and_revocation(self) -> None:
        cp70_contract = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.cp70_policy))
        dry_run = build_authority_lease_expiry_revocation_dry_run(cp70_contract)
        self.assertEqual(
            (dry_run.cp70_contract_id, dry_run.cp70_contract_hash),
            (cp70_contract.contract_id, cp70_contract.contract_hash),
        )
        self.assertEqual(
            (dry_run.cp70_transaction_id, dry_run.cp70_transaction_hash),
            (cp70_contract.transaction_id, cp70_contract.transaction_hash),
        )
        self.assertEqual(tuple(row.name for row in dry_run.phases), LEASE_PHASES)
        self.assertTrue(all(row.satisfied for row in dry_run.phases))
        self.assertTrue(dry_run.candidate_valid_before_expiry)
        self.assertTrue(dry_run.expired_at_boundary)
        self.assertTrue(dry_run.explicit_revocation_before_expiry)
        self.assertTrue(dry_run.terminal_state_non_reusable)
        self.assertEqual(dry_run.lease_ttl_seconds, LEASE_TTL_SECONDS)
        self.assertEqual(
            dry_run.outcome,
            "SIMULATED_LEASE_EXPIRY_REVOCATION_PASS_NO_AUTHORITY_NO_REUSE_NO_MUTATION",
        )
        validate_authority_lease_expiry_revocation_dry_run(dry_run, cp70_contract)

    def test_policy_drift_that_weakens_expiry_or_revocation_guards_fails_closed(self) -> None:
        cases = []
        weak_expiry = deepcopy(self.policy)
        weak_expiry["lease"]["expiry_fail_closed_required"] = False
        cases.append(weak_expiry)
        weak_revocation = deepcopy(self.policy)
        weak_revocation["lease"]["explicit_revocation_fail_closed_required"] = False
        cases.append(weak_revocation)
        weak_reuse = deepcopy(self.policy)
        weak_reuse["lease"]["terminal_state_reuse_forbidden"] = False
        cases.append(weak_reuse)
        weak_zero_io = deepcopy(self.policy)
        weak_zero_io["lease"]["zero_io_required"] = False
        cases.append(weak_zero_io)
        method = deepcopy(self.policy)
        method["lease"]["method_allowlist"] = ["GET", "POST"]
        cases.append(method)
        ttl = deepcopy(self.policy)
        ttl["lease"]["lease_ttl_seconds"] = LEASE_TTL_SECONDS + 1
        cases.append(ttl)
        for bad in cases:
            with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold):
                compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, bad)

    def test_clock_fixture_drift_fails_closed(self) -> None:
        bad = deepcopy(self.policy)
        bad["lease"]["synthetic_expires_at_utc"] = "2030-01-01T00:20:00Z"
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold):
            compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, bad)

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
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold):
            compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, bad)

    def test_terminal_dry_run_cannot_be_tampered_into_runtime_authority(self) -> None:
        cp70_contract = compile_live_read_only_probe_authority_activation_transaction(self.root, deepcopy(self.cp70_policy))
        dry_run = build_authority_lease_expiry_revocation_dry_run(cp70_contract)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold):
            validate_authority_lease_expiry_revocation_dry_run(replace(dry_run, authority_activated=True), cp70_contract)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseExpiryRevocationHold):
            validate_authority_lease_expiry_revocation_dry_run(replace(dry_run, terminal_state_non_reusable=False), cp70_contract)

    def test_registry_records_m40_but_global_checkpoint_stays_cp58(self) -> None:
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {row["id"]: row["status"] for row in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(
            states["M40_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_EXPIRY_REVOCATION"],
            "CP71_AUTHORITY_LEASE_EXPIRY_REVOCATION_DRY_RUN_LOCAL_ONLY_NO_RUNTIME_AUTHORITY_LIVE_HOLD",
        )
        self.assertEqual(tuple(self.policy["lease_phases"]), LEASE_PHASES)
        self.assertEqual(tuple(self.policy["required_blockers"]), REQUIRED_BLOCKERS)

    def test_contract_never_claims_authority_or_side_effects(self) -> None:
        contract = compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, deepcopy(self.policy))
        self.assertTrue(contract.global_kill_switch_engaged)
        self.assertTrue(contract.lease_validated)
        self.assertTrue(contract.expiry_fail_closed_validated)
        self.assertTrue(contract.explicit_revocation_fail_closed_validated)
        self.assertTrue(contract.terminal_reuse_rejected)
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
