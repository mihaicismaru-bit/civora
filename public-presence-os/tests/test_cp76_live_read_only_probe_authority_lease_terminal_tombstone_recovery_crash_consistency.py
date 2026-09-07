from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback import (
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback,
)
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency import (
    CHECKPOINT,
    CRASH_POINTS,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    VALIDATION_CASES,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold,
    _build_cp75_dry_run,
    build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency,
    validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency_policy.json"
CP75_POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback_policy.json"


def _compile():
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency(ROOT, load_json(POLICY_PATH))


def _parent():
    cp75 = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_idempotency_rollback(ROOT, load_json(CP75_POLICY_PATH))
    return cp75, _build_cp75_dry_run(ROOT, cp75)


def _dry_run():
    cp75, cp75_dry = _parent()
    dry = build_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(cp75, cp75_dry)
    return cp75, cp75_dry, dry


def test_cp76_contract_is_deterministic_and_keeps_control_plane_held():
    first = _compile()
    second = _compile()
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP76"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.crash_consistency_validated
    assert first.no_torn_state_validated
    assert first.no_duplicate_effect_validated


def test_cp76_covers_all_four_recovery_cases_at_three_bounded_crash_points():
    cp75, cp75_dry, dry = _dry_run()
    assert len(dry.crash_cases) == 12
    assert tuple((x.scenario, x.failure_mode, x.crash_point) for x in dry.crash_cases) == VALIDATION_CASES
    assert set(x.crash_point for x in dry.crash_cases) == set(CRASH_POINTS)
    parent_results = {(x.scenario, x.failure_mode): x.first_apply_result_hash for x in cp75_dry.validation_cases}
    for case in dry.crash_cases:
        assert case.restart_converged_result_hash == parent_results[(case.scenario, case.failure_mode)]
        assert case.intended_recovery_result_hash == parent_results[(case.scenario, case.failure_mode)]
        assert case.recovery_effect_count == 1
        assert case.crash_consistent
        assert not case.torn_state_observed
        assert not case.duplicate_recovery_effect_observed
        assert case.simulated_journal_only
        assert not case.storage_write_performed
        assert not case.runtime_mutated
    validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(dry, cp75, cp75_dry)


def test_cp76_crash_point_shapes_are_atomic_and_unambiguous():
    _, _, dry = _dry_run()
    for case in dry.crash_cases:
        if case.crash_point == "AFTER_PREPARE_BEFORE_STAGE":
            assert case.staged_record_hash is None
            assert case.commit_marker_hash is None
            assert case.restart_action == "DISCARD_PREPARE_AND_REPLAY_CP75_RECOVERY"
        elif case.crash_point == "AFTER_STAGE_BEFORE_COMMIT_MARKER":
            assert case.staged_record_hash is not None
            assert case.commit_marker_hash is None
            assert case.restart_action == "DISCARD_STAGED_ROLLBACK_BASELINE_AND_REPLAY_CP75_RECOVERY"
        else:
            assert case.staged_record_hash is not None
            assert case.commit_marker_hash is not None
            assert case.restart_action == "FINALIZE_COMMITTED_RESULT_IDEMPOTENTLY"


def test_cp76_torn_state_and_duplicate_effect_fail_closed():
    cp75, cp75_dry, dry = _dry_run()
    torn_case = replace(dry.crash_cases[0], torn_state_observed=True)
    torn = replace(dry, crash_cases=(torn_case,) + dry.crash_cases[1:])
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(torn, cp75, cp75_dry)
    duplicate_case = replace(dry.crash_cases[-1], duplicate_recovery_effect_observed=True, recovery_effect_count=2)
    duplicate = replace(dry, crash_cases=dry.crash_cases[:-1] + (duplicate_case,))
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(duplicate, cp75, cp75_dry)


def test_cp76_corrupt_commit_marker_and_parent_result_drift_fail_closed():
    cp75, cp75_dry, dry = _dry_run()
    index = next(i for i, x in enumerate(dry.crash_cases) if x.crash_point == "AFTER_COMMIT_MARKER_BEFORE_ACK")
    broken_marker = replace(dry.crash_cases[index], commit_marker_hash=None)
    broken_cases = dry.crash_cases[:index] + (broken_marker,) + dry.crash_cases[index + 1:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(replace(dry, crash_cases=broken_cases), cp75, cp75_dry)
    drifted = replace(dry.crash_cases[0], restart_converged_result_hash="0" * 64)
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        validate_authority_lease_terminal_tombstone_recovery_crash_consistency_dry_run(replace(dry, crash_cases=(drifted,) + dry.crash_cases[1:]), cp75, cp75_dry)


def test_cp76_policy_weakening_and_lane_drift_fail_closed():
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["crash_consistency_guard"]["storage_write_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency(ROOT, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryCrashConsistencyHold):
        compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_crash_consistency(ROOT, lane_drift)


def test_cp76_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M45_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY"] == "CP76_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_CRASH_CONSISTENCY_DRY_RUN_LOCAL_ONLY_NO_TORN_STATE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"


def test_cp76_contract_never_claims_live_authority_or_side_effects():
    contract = _compile()
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
