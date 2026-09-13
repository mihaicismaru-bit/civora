from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
import public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window as cp80_module
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window import (
    CHECKPOINT,
    CRASH_WINDOWS,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold,
    _build_cp80_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window,
    validate_atomic_replace_crash_window_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_policy.json"


@pytest.fixture(scope="module")
def cp80_evidence():
    return _build_cp80_evidence(ROOT)


def _compile_with_evidence(monkeypatch, evidence, policy=None):
    monkeypatch.setattr(cp80_module, "_build_cp80_evidence", lambda root: evidence)
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window(
        ROOT, policy or load_json(POLICY_PATH)
    )


def test_cp80_validates_twelve_pairs_and_forty_eight_crash_windows(cp80_evidence):
    cp79_contract, cp79_dry, dry = cp80_evidence
    assert len(dry.cases) == 48
    assert dry.all_twelve_pairs_validated
    assert dry.all_forty_eight_crash_cases_validated
    assert dry.exact_one_complete_generation_after_restart
    assert dry.deterministic_retry_or_finalize_validated
    for index in range(12):
        chunk = dry.cases[index * 4:(index + 1) * 4]
        assert tuple(x.crash_window for x in chunk) == CRASH_WINDOWS
        assert all(x.slot_index == index for x in chunk)
        assert chunk[0].baseline_sha256 != chunk[0].candidate_sha256
        for case in chunk:
            assert case.visible_sha256 in (case.baseline_sha256, case.candidate_sha256)
            assert case.restart_converged_sha256 == case.candidate_sha256
            assert case.complete_generation_visible
            assert not case.absent_visibility_observed
            assert not case.partial_visibility_observed
            assert not case.mixed_generation_observed
            assert case.simulated_only
            assert not case.storage_read_performed
            assert not case.storage_write_performed
            assert not case.runtime_mutated
    validate_atomic_replace_crash_window_dry_run(dry, cp79_contract, cp79_dry)


def test_cp80_baseline_winner_requires_replace_replay(cp80_evidence):
    cp79_contract, cp79_dry, dry = cp80_evidence
    index = next(i for i, x in enumerate(dry.cases) if x.crash_window == "REPLACE_BOUNDARY_BASELINE_WINS")
    tampered = replace(dry.cases[index], restart_action="FINALIZE_ACK_IDEMPOTENTLY")
    cases = dry.cases[:index] + (tampered,) + dry.cases[index + 1:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold):
        validate_atomic_replace_crash_window_dry_run(replace(dry, cases=cases), cp79_contract, cp79_dry)


def test_cp80_candidate_winner_rejects_mixed_visibility(cp80_evidence):
    cp79_contract, cp79_dry, dry = cp80_evidence
    index = next(i for i, x in enumerate(dry.cases) if x.crash_window == "REPLACE_BOUNDARY_CANDIDATE_WINS")
    tampered = replace(dry.cases[index], mixed_generation_observed=True)
    cases = dry.cases[:index] + (tampered,) + dry.cases[index + 1:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold):
        validate_atomic_replace_crash_window_dry_run(replace(dry, cases=cases), cp79_contract, cp79_dry)


def test_cp80_contract_is_deterministic_and_keeps_control_plane_held(monkeypatch, cp80_evidence):
    first = _compile_with_evidence(monkeypatch, cp80_evidence)
    second = _compile_with_evidence(monkeypatch, cp80_evidence)
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP80"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.atomic_replace_crash_window_validated
    assert first.all_twelve_pairs_validated
    assert first.all_four_crash_windows_validated
    assert first.all_forty_eight_restart_cases_validated
    assert first.deterministic_retry_or_finalize_validated


def test_cp80_policy_weakening_and_lane_drift_fail_closed(monkeypatch, cp80_evidence):
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["atomic_replace_guard"]["mixed_generation_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold):
        _compile_with_evidence(monkeypatch, cp80_evidence, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold):
        _compile_with_evidence(monkeypatch, cp80_evidence, lane_drift)


def test_cp80_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M49_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW"] == STATE


def test_cp80_contract_never_claims_live_authority_or_side_effects(monkeypatch, cp80_evidence):
    contract = _compile_with_evidence(monkeypatch, cp80_evidence)
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
