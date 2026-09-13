from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
import public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed as cp82_module
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed import (
    CHECKPOINT,
    MAX_RETRY_ATTEMPTS,
    NEXT_UNIT,
    OBSERVATIONS_PER_CASE,
    PARENT_CONTROL_CHECKPOINT,
    POST_EXHAUSTION_ORDINAL,
    STATE,
    TERMINAL_HOLD_REASON,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold,
    _build_cp82_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed,
    validate_retry_exhaustion_fail_closed_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed_policy.json"


@pytest.fixture(scope="module")
def cp82_evidence():
    return _build_cp82_evidence(ROOT)


def _compile_with_evidence(monkeypatch, evidence, policy=None):
    monkeypatch.setattr(cp82_module, "_build_cp82_evidence", lambda root: evidence)
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed(
        ROOT, policy or load_json(POLICY_PATH)
    )


def test_cp82_validates_forty_eight_cases_and_240_observations(cp82_evidence):
    cp81_contract, cp81_dry, dry = cp82_evidence
    assert len(cp81_dry.observations) == 192
    assert len(dry.observations) == 240
    assert dry.all_forty_eight_parent_cases_validated
    assert dry.all_two_hundred_forty_observations_validated
    assert dry.retry_budget_exactly_four_validated
    assert dry.terminal_hold_exactly_once_validated
    assert dry.post_exhaustion_noop_validated
    assert dry.no_resurrection_validated
    assert dry.no_duplicate_external_effect_validated
    for parent_index in range(48):
        chunk = dry.observations[parent_index * OBSERVATIONS_PER_CASE:(parent_index + 1) * OBSERVATIONS_PER_CASE]
        assert [x.invocation_ordinal for x in chunk] == [1, 2, 3, 4, POST_EXHAUSTION_ORDINAL]
        assert [x.retry_failure_count for x in chunk] == [1, 2, 3, MAX_RETRY_ATTEMPTS, MAX_RETRY_ATTEMPTS]
        assert [x.terminal_hold for x in chunk] == [False, False, False, True, True]
        assert [x.terminal_hold_transition_count for x in chunk] == [0, 0, 0, 1, 1]
        assert chunk[3].terminal_hold_reason == TERMINAL_HOLD_REASON
        assert chunk[4].action == "NOOP_TERMINAL_HOLD"
        assert all(x.visible_generation == "CANDIDATE_COMPLETE" for x in chunk)
        assert all(x.visible_sha256 == x.candidate_sha256 for x in chunk)
        assert all(x.ack_transition_count == 0 for x in chunk)
        assert all(x.replace_replay_count == 0 for x in chunk)
        assert all(x.external_effect_count == 0 for x in chunk)
        assert all(not x.transaction_resurrected for x in chunk)
        assert all(x.simulated_only for x in chunk)
        assert all(not x.storage_read_performed for x in chunk)
        assert all(not x.storage_write_performed for x in chunk)
        assert all(not x.runtime_mutated for x in chunk)
    validate_retry_exhaustion_fail_closed_dry_run(dry, cp81_contract, cp81_dry)


def test_cp82_exhaustion_enters_terminal_hold_once_and_post_hold_is_noop(cp82_evidence):
    cp81_contract, cp81_dry, dry = cp82_evidence
    chunk = dry.observations[:OBSERVATIONS_PER_CASE]
    assert [x.action for x in chunk] == [
        "SYNTHETIC_RETRYABLE_FAILURE",
        "SYNTHETIC_RETRYABLE_FAILURE",
        "SYNTHETIC_RETRYABLE_FAILURE",
        "ENTER_TERMINAL_HOLD_RETRY_EXHAUSTED",
        "NOOP_TERMINAL_HOLD",
    ]
    tampered = replace(chunk[-1], terminal_hold=False, terminal_hold_reason=None, action="SYNTHETIC_RETRYABLE_FAILURE")
    observations = list(dry.observations)
    observations[4] = tampered
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        validate_retry_exhaustion_fail_closed_dry_run(replace(dry, observations=tuple(observations)), cp81_contract, cp81_dry)


def test_cp82_rejects_retry_budget_overrun_and_transaction_resurrection(cp82_evidence):
    cp81_contract, cp81_dry, dry = cp82_evidence
    tampered = replace(
        dry.observations[4],
        retry_failure_count=5,
        external_effect_count=1,
        transaction_resurrected=True,
    )
    observations = dry.observations[:4] + (tampered,) + dry.observations[5:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        validate_retry_exhaustion_fail_closed_dry_run(replace(dry, observations=observations), cp81_contract, cp81_dry)


def test_cp82_rejects_candidate_hash_drift_or_duplicate_replace(cp82_evidence):
    cp81_contract, cp81_dry, dry = cp82_evidence
    tampered = replace(dry.observations[2], visible_sha256="0" * 64, replace_replay_count=1)
    observations = dry.observations[:2] + (tampered,) + dry.observations[3:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        validate_retry_exhaustion_fail_closed_dry_run(replace(dry, observations=observations), cp81_contract, cp81_dry)


def test_cp82_contract_is_deterministic_and_keeps_control_plane_held(monkeypatch, cp82_evidence):
    first = _compile_with_evidence(monkeypatch, cp82_evidence)
    second = _compile_with_evidence(monkeypatch, cp82_evidence)
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP82"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT == "CP83_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE"
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.retry_exhaustion_fail_closed_validated
    assert first.all_forty_eight_parent_cases_validated
    assert first.four_retry_failures_per_case_validated
    assert first.all_two_hundred_forty_observations_validated
    assert first.terminal_hold_exactly_once_validated
    assert first.post_exhaustion_noop_validated
    assert first.no_resurrection_validated
    assert first.no_duplicate_external_effect_validated
    assert first.candidate_generation_stable


def test_cp82_policy_weakening_lane_drift_and_budget_drift_fail_closed(monkeypatch, cp82_evidence):
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["retry_exhaustion_guard"]["terminal_hold_transition_exactly_once_required"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        _compile_with_evidence(monkeypatch, cp82_evidence, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        _compile_with_evidence(monkeypatch, cp82_evidence, lane_drift)
    budget_drift = deepcopy(policy)
    budget_drift["max_retry_attempts"] = 5
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold):
        _compile_with_evidence(monkeypatch, cp82_evidence, budget_drift)


def test_cp82_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M51_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED"] == STATE


def test_cp82_contract_never_claims_live_authority_or_side_effects(monkeypatch, cp82_evidence):
    contract = _compile_with_evidence(monkeypatch, cp82_evidence)
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
