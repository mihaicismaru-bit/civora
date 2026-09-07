from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection import (
    CHECKPOINT,
    CORRUPTION_CLASSES,
    EXPECTED_HOLDS,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold,
    _build_cp76_parent,
    _inject_corruption,
    _representative_case,
    build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run,
    build_valid_recovery_journal,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection,
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run,
    validate_recovery_journal,
    validate_recovery_journal_ledger,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_policy.json"


def _compile():
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection(
        ROOT, load_json(POLICY_PATH)
    )


@pytest.fixture(scope="module")
def cp76_parent():
    return _build_cp76_parent(ROOT)


@pytest.fixture(scope="module")
def cp77_dry(cp76_parent):
    cp76, cp76_dry = cp76_parent
    dry = build_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(cp76, cp76_dry)
    return cp76, cp76_dry, dry


@pytest.fixture(scope="module")
def cp77_contract():
    return _compile()


def test_cp77_contract_is_deterministic_and_keeps_control_plane_held(cp77_contract):
    first = cp77_contract
    second = _compile()
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP77"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.valid_journal_positive_control_validated
    assert first.corruption_rejection_validated
    assert first.all_eight_corruption_classes_validated
    assert first.baseline_preservation_validated


def test_cp77_accepts_all_twelve_valid_cp76_journals_as_positive_controls(cp77_dry):
    cp76, cp76_dry, dry = cp77_dry
    assert len(dry.positive_control_journal_hashes) == 12
    journals = tuple(build_valid_recovery_journal(case, cp76) for case in cp76_dry.crash_cases)
    assert tuple(x["journal_hash"] for x in journals) == dry.positive_control_journal_hashes
    for journal, case in zip(journals, cp76_dry.crash_cases):
        validate_recovery_journal(journal, case, cp76)
    validate_recovery_journal_ledger(journals)


def test_cp77_rejects_exactly_eight_corruption_classes_before_any_recovery_effect(cp77_dry):
    cp76, cp76_dry, dry = cp77_dry
    assert tuple(x.corruption_class for x in dry.rejection_cases) == CORRUPTION_CLASSES
    assert len(dry.rejection_cases) == 8
    for result in dry.rejection_cases:
        assert result.rejected
        assert result.rejection_before_recovery_effect
        assert result.recovery_effect_count == 0
        assert result.baseline_preserved
        assert result.expected_hold == EXPECTED_HOLDS[result.corruption_class]
        assert result.observed_hold == result.expected_hold
        assert result.simulated_journal_only
        assert not result.storage_write_performed
        assert not result.runtime_mutated
    validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(dry, cp76, cp76_dry)


def test_cp77_each_corruption_mutation_fails_closed_for_the_expected_reason(cp76_parent):
    cp76, cp76_dry = cp76_parent
    for corruption_class in CORRUPTION_CLASSES:
        case = _representative_case(cp76_dry, corruption_class)
        valid = build_valid_recovery_journal(case, cp76)
        corrupted = _inject_corruption(valid, corruption_class)
        with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold) as exc:
            if corruption_class == "DUPLICATE_CONFLICTING_ENTRY":
                validate_recovery_journal_ledger((valid, corrupted))
            else:
                validate_recovery_journal(corrupted, case, cp76)
        assert str(exc.value) == EXPECTED_HOLDS[corruption_class]


def test_cp77_dry_run_tamper_and_policy_weakening_fail_closed(cp77_dry):
    cp76, cp76_dry, dry = cp77_dry
    broken_case = replace(dry.rejection_cases[0], baseline_preserved=False)
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold):
        validate_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection_dry_run(
            replace(dry, rejection_cases=(broken_case,) + dry.rejection_cases[1:]), cp76, cp76_dry
        )
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["journal_corruption_guard"]["storage_write_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold):
        compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection(ROOT, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalCorruptionRejectionHold):
        compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection(ROOT, lane_drift)


def test_cp77_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M46_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION"] == "CP77_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_CORRUPTION_REJECTION_DRY_RUN_LOCAL_ONLY_FAIL_CLOSED_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"


def test_cp77_contract_never_claims_live_authority_or_side_effects(cp77_contract):
    contract = cp77_contract
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
