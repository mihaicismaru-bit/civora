from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import unittest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_expiry_revocation import compile_live_read_only_probe_authority_lease_expiry_revocation
from public_presence_os.live_read_only_probe_authority_lease_replay_stale_receipt import (
    build_authority_lease_replay_stale_receipt_dry_run,
    compile_live_read_only_probe_authority_lease_replay_stale_receipt,
)
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_reconciliation import (
    CHECKPOINT, NEXT_UNIT, PARENT_CONTROL_CHECKPOINT, RECONCILIATION_PHASES, STATE,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold,
    _entry,
    build_authority_lease_terminal_tombstone_reconciliation_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation,
    validate_authority_lease_terminal_tombstone_reconciliation_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract,
)


class CP73TerminalTombstoneReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.policy = load_json(cls.root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_policy.json")
        cls.cp72_policy = load_json(cls.root / "config" / "live_read_only_probe_authority_lease_replay_stale_receipt_policy.json")
        cls.cp71_policy = load_json(cls.root / "config" / "live_read_only_probe_authority_lease_expiry_revocation_policy.json")

    def parent_fixture(self):
        cp72 = compile_live_read_only_probe_authority_lease_replay_stale_receipt(self.root, deepcopy(self.cp72_policy))
        cp71 = compile_live_read_only_probe_authority_lease_expiry_revocation(self.root, deepcopy(self.cp71_policy))
        return cp72, build_authority_lease_replay_stale_receipt_dry_run(cp71)

    def test_contract_is_deterministic_and_control_checkpoint_stays_cp58(self) -> None:
        a = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(self.root, deepcopy(self.policy))
        b = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(self.root, deepcopy(self.policy))
        self.assertEqual((a.contract_id, a.contract_hash), (b.contract_id, b.contract_hash))
        self.assertEqual((a.checkpoint, a.parent_control_checkpoint, a.state, a.next_unit), (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, STATE, NEXT_UNIT))
        validate_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation_contract(a)

    def test_two_terminal_paths_reconcile_exactly(self) -> None:
        cp72, cp72_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72, cp72_dry)
        self.assertEqual(dry.phases, RECONCILIATION_PHASES)
        self.assertEqual(dry.expiry_tombstone.terminal_state, "EXPIRED")
        self.assertEqual(dry.revocation_tombstone.terminal_state, "REVOKED")
        self.assertEqual(sum(x.decision == "ACCEPTED" for x in dry.expiry_ledger), 1)
        self.assertEqual(sum(x.decision == "ACCEPTED" for x in dry.revocation_ledger), 1)
        self.assertTrue(any(x.reason == "EXACT_TERMINAL_RECEIPT_REPLAY" and x.decision == "REJECTED" for x in dry.expiry_ledger))
        self.assertTrue(any(x.reason == "STALE_ACTIVE_RECEIPT_AFTER_TERMINAL" and x.decision == "REJECTED" for x in dry.revocation_ledger))
        validate_authority_lease_terminal_tombstone_reconciliation_dry_run(dry, cp72)

    def test_tombstone_or_terminal_duplicate_tamper_fails_closed(self) -> None:
        cp72, cp72_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72, cp72_dry)
        bad_tombstone = replace(dry.expiry_tombstone, terminal_state="REVOKED")
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold):
            validate_authority_lease_terminal_tombstone_reconciliation_dry_run(replace(dry, expiry_tombstone=bad_tombstone), cp72)
        duplicate = replace(dry.expiry_ledger[1], decision="ACCEPTED", reason="TERMINAL_RECEIPT_ACCEPTED_ONCE")
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold):
            validate_authority_lease_terminal_tombstone_reconciliation_dry_run(replace(dry, expiry_ledger=(dry.expiry_ledger[0], duplicate, dry.expiry_ledger[2])), cp72)

    def test_post_terminal_active_acceptance_fails_closed(self) -> None:
        cp72, cp72_dry = self.parent_fixture()
        dry = build_authority_lease_terminal_tombstone_reconciliation_dry_run(cp72, cp72_dry)
        active = _entry(cp72_dry.expiry_stale_receipt, "ACCEPTED", "INVALID_ACCEPTANCE")
        active = replace(active, presented_at_utc=dry.expiry_tombstone.terminal_at_utc)
        with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold):
            validate_authority_lease_terminal_tombstone_reconciliation_dry_run(replace(dry, expiry_ledger=(dry.expiry_ledger[0], dry.expiry_ledger[1], active)), cp72)

    def test_policy_weakening_and_lane_drift_fail_closed(self) -> None:
        bads = []
        for key in ("terminal_entry_unique_required", "terminal_tombstone_exact_match_required", "replay_rejection_preservation_required", "stale_rejection_preservation_required", "post_terminal_active_acceptance_forbidden", "terminal_tombstone_immutable_required", "zero_io_required"):
            bad = deepcopy(self.policy); bad["tombstone_guard"][key] = False; bads.append(bad)
        bad_method = deepcopy(self.policy); bad_method["tombstone_guard"]["method_allowlist"] = ["GET", "POST"]; bads.append(bad_method)
        bad_lane = deepcopy(self.policy); bad_lane["active_platforms"].append("LINKEDIN"); bads.append(bad_lane)
        for bad in bads:
            with self.assertRaises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneReconciliationHold):
                compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(self.root, bad)

    def test_canonical_lanes_and_registry_are_locked(self) -> None:
        self.assertEqual(tuple(self.policy["active_platforms"]), EXPECTED_ACTIVE)
        self.assertEqual(self.policy["excluded_platforms"], {"LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS", "X": "EXCLUDED_WHILE_API_IS_PAID", "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES"})
        registry = load_json(self.root / "config" / "module_registry.json")
        states = {x["id"]: x["status"] for x in registry["modules"]}
        self.assertEqual(registry["checkpoint"], PARENT_CONTROL_CHECKPOINT)
        self.assertEqual(states["M42_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION"], "CP73_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECONCILIATION_DRY_RUN_LOCAL_ONLY_LEDGER_CONSISTENT_NO_RUNTIME_AUTHORITY_LIVE_HOLD")

    def test_contract_never_claims_live_authority_or_side_effects(self) -> None:
        c = compile_live_read_only_probe_authority_lease_terminal_tombstone_reconciliation(self.root, deepcopy(self.policy))
        self.assertTrue(c.global_kill_switch_engaged)
        self.assertTrue(c.terminal_tombstone_reconciliation_validated)
        self.assertTrue(c.receipt_ledger_consistency_validated)
        for field in ("external_authorization_ingested", "authorization_granted", "runtime_authorization_effective", "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed", "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated"):
            self.assertFalse(getattr(c, field), field)


if __name__ == "__main__":
    unittest.main()
