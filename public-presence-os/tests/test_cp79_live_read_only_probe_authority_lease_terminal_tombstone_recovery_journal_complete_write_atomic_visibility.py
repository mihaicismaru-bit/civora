from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
import public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility as cp79_module
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    VISIBILITY_PHASES,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold,
    _build_cp79_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility,
    validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_policy.json"


@pytest.fixture(scope="module")
def cp79_evidence():
    return _build_cp79_evidence(ROOT)


def _compile_with_evidence(monkeypatch, evidence, policy=None):
    monkeypatch.setattr(cp79_module, "_build_cp79_evidence", lambda root: evidence)
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility(
        ROOT, policy or load_json(POLICY_PATH)
    )


def test_cp79_dry_run_validates_twelve_journals_and_forty_eight_atomic_observations(cp79_evidence):
    cp76, cp76_dry, _, cp78_contract, cp78_dry, dry = cp79_evidence
    assert len(dry.visibility_cases) == 12
    assert sum(len(case.observations) for case in dry.visibility_cases) == 48
    assert dry.all_twelve_complete_journals_validated
    assert dry.all_forty_eight_observations_validated
    assert dry.zero_partial_visibility_observed
    assert dry.all_commit_snapshots_exact
    for case in dry.visibility_cases:
        assert tuple(obs.phase for obs in case.observations) == VISIBILITY_PHASES
        assert len(case.forbidden_prefix_sha256s) == 5
        for index, obs in enumerate(case.observations):
            assert not obs.partial_visible
            assert obs.baseline_preserved
            assert obs.simulated_only
            assert not obs.storage_read_performed
            assert not obs.storage_write_performed
            assert not obs.runtime_mutated
            if index < 2:
                assert obs.visible_state == "ABSENT"
                assert obs.visible_length == 0
                assert obs.visible_sha256 is None
                assert not obs.complete_visible
            else:
                assert obs.visible_state == "COMPLETE"
                assert obs.visible_length == case.complete_serialized_length
                assert obs.visible_sha256 == case.complete_serialized_sha256
                assert obs.complete_visible
                assert obs.visible_sha256 not in case.forbidden_prefix_sha256s
    validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
        dry, cp76, cp76_dry, cp78_contract, cp78_dry
    )


def test_cp79_precommit_partial_visibility_tamper_fails_closed(cp79_evidence):
    cp76, cp76_dry, _, cp78_contract, cp78_dry, dry = cp79_evidence
    case = dry.visibility_cases[0]
    tampered_observation = replace(
        case.observations[1],
        visible_state="PARTIAL",
        visible_length=1,
        visible_sha256=case.forbidden_prefix_sha256s[1],
        partial_visible=True,
        baseline_preserved=False,
    )
    tampered_case = replace(case, observations=(case.observations[0], tampered_observation) + case.observations[2:])
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold):
        validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
            replace(dry, visibility_cases=(tampered_case,) + dry.visibility_cases[1:]),
            cp76,
            cp76_dry,
            cp78_contract,
            cp78_dry,
        )


def test_cp79_commit_boundary_must_expose_exact_complete_digest(cp79_evidence):
    cp76, cp76_dry, _, cp78_contract, cp78_dry, dry = cp79_evidence
    case = dry.visibility_cases[0]
    tampered_observation = replace(
        case.observations[2],
        visible_length=case.complete_serialized_length - 1,
        visible_sha256=case.forbidden_prefix_sha256s[-1],
        complete_visible=False,
        partial_visible=True,
    )
    tampered_case = replace(case, observations=case.observations[:2] + (tampered_observation,) + case.observations[3:])
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold):
        validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
            replace(dry, visibility_cases=(tampered_case,) + dry.visibility_cases[1:]),
            cp76,
            cp76_dry,
            cp78_contract,
            cp78_dry,
        )


def test_cp79_contract_is_deterministic_and_keeps_control_plane_held(monkeypatch, cp79_evidence):
    first = _compile_with_evidence(monkeypatch, cp79_evidence)
    second = _compile_with_evidence(monkeypatch, cp79_evidence)
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP79"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.complete_write_atomic_visibility_validated
    assert first.all_twelve_parent_journals_validated
    assert first.all_four_visibility_phases_validated
    assert first.all_forty_eight_observations_validated
    assert first.zero_partial_visibility_observed
    assert first.baseline_preservation_validated


def test_cp79_policy_weakening_and_lane_drift_fail_closed(monkeypatch, cp79_evidence):
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["atomic_visibility_guard"]["strict_prefix_visibility_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold):
        _compile_with_evidence(monkeypatch, cp79_evidence, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCompleteWriteAtomicVisibilityHold):
        _compile_with_evidence(monkeypatch, cp79_evidence, lane_drift)


def test_cp79_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M48_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY"] == STATE


def test_cp79_contract_never_claims_live_authority_or_side_effects(monkeypatch, cp79_evidence):
    contract = _compile_with_evidence(monkeypatch, cp79_evidence)
    false_fields = (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "storage_write_allowed", "storage_write_performed",
        "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    )
    assert contract.global_kill_switch_engaged
    assert contract.simulated_journal_only
    assert all(getattr(contract, field) is False for field in false_fields)
