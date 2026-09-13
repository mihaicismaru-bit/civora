from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
import public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency as cp81_module
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency import (
    CHECKPOINT,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    RETRY_ORDINALS,
    STATE,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold,
    _build_cp81_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency,
    validate_atomic_replace_retry_idempotency_dry_run,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_policy.json"


@pytest.fixture(scope="module")
def cp81_evidence():
    return _build_cp81_evidence(ROOT)


def _compile_with_evidence(monkeypatch, evidence, policy=None):
    monkeypatch.setattr(cp81_module, "_build_cp81_evidence", lambda root: evidence)
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency(
        ROOT, policy or load_json(POLICY_PATH)
    )


def test_cp81_validates_forty_eight_parent_cases_and_192_retry_observations(cp81_evidence):
    cp80_contract, cp80_dry, dry = cp81_evidence
    assert len(cp80_dry.cases) == 48
    assert len(dry.observations) == 192
    assert dry.all_forty_eight_parent_cases_validated
    assert dry.all_one_hundred_ninety_two_observations_validated
    assert dry.candidate_generation_stable
    assert dry.exactly_once_ack_validated
    for parent_index, parent_case in enumerate(cp80_dry.cases):
        chunk = dry.observations[parent_index * 4:(parent_index + 1) * 4]
        assert tuple(x.retry_ordinal for x in chunk) == RETRY_ORDINALS
        assert all(x.parent_case_index == parent_index for x in chunk)
        assert all(x.visible_generation == "CANDIDATE_COMPLETE" for x in chunk)
        assert all(x.visible_sha256 == parent_case.candidate_sha256 for x in chunk)
        assert all(not x.duplicate_ack_observed for x in chunk)
        assert all(not x.duplicate_replace_observed for x in chunk)
        assert all(not x.transaction_resurrected for x in chunk)
        assert all(x.simulated_only for x in chunk)
        assert all(not x.storage_read_performed for x in chunk)
        assert all(not x.storage_write_performed for x in chunk)
        assert all(not x.runtime_mutated for x in chunk)
        assert chunk[-1].ack_finalized
        assert chunk[-1].ack_transition_count == 1
    validate_atomic_replace_retry_idempotency_dry_run(dry, cp80_contract, cp80_dry)


def test_cp81_baseline_visible_case_replays_replace_once_then_never_again(cp81_evidence):
    cp80_contract, cp80_dry, dry = cp81_evidence
    parent_index = next(i for i, x in enumerate(cp80_dry.cases) if x.visible_generation == "BASELINE_COMPLETE")
    chunk = dry.observations[parent_index * 4:(parent_index + 1) * 4]
    assert [x.action for x in chunk] == [
        "REPLAY_ATOMIC_REPLACE",
        "FINALIZE_ACK_ONCE",
        "NOOP_ALREADY_ACKED",
        "NOOP_ALREADY_ACKED",
    ]
    assert [x.replace_replay_count for x in chunk] == [1, 1, 1, 1]
    tampered = replace(chunk[2], action="REPLAY_ATOMIC_REPLACE", duplicate_replace_observed=True)
    observations = list(dry.observations)
    observations[parent_index * 4 + 2] = tampered
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold):
        validate_atomic_replace_retry_idempotency_dry_run(replace(dry, observations=tuple(observations)), cp80_contract, cp80_dry)


def test_cp81_candidate_visible_case_never_replays_replace_and_ack_is_exactly_once(cp81_evidence):
    cp80_contract, cp80_dry, dry = cp81_evidence
    parent_index = next(i for i, x in enumerate(cp80_dry.cases) if x.visible_generation == "CANDIDATE_COMPLETE")
    chunk = dry.observations[parent_index * 4:(parent_index + 1) * 4]
    assert [x.action for x in chunk] == [
        "FINALIZE_ACK_ONCE",
        "NOOP_ALREADY_ACKED",
        "NOOP_ALREADY_ACKED",
        "NOOP_ALREADY_ACKED",
    ]
    assert [x.replace_replay_count for x in chunk] == [0, 0, 0, 0]
    assert [x.ack_transition_count for x in chunk] == [1, 1, 1, 1]
    tampered = replace(chunk[1], ack_transition_count=2, duplicate_ack_observed=True)
    observations = list(dry.observations)
    observations[parent_index * 4 + 1] = tampered
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold):
        validate_atomic_replace_retry_idempotency_dry_run(replace(dry, observations=tuple(observations)), cp80_contract, cp80_dry)


def test_cp81_rejects_candidate_hash_drift_and_transaction_resurrection(cp81_evidence):
    cp80_contract, cp80_dry, dry = cp81_evidence
    index = 3
    tampered = replace(
        dry.observations[index],
        visible_sha256="0" * 64,
        transaction_resurrected=True,
    )
    observations = dry.observations[:index] + (tampered,) + dry.observations[index + 1:]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold):
        validate_atomic_replace_retry_idempotency_dry_run(replace(dry, observations=observations), cp80_contract, cp80_dry)


def test_cp81_contract_is_deterministic_and_keeps_control_plane_held(monkeypatch, cp81_evidence):
    first = _compile_with_evidence(monkeypatch, cp81_evidence)
    second = _compile_with_evidence(monkeypatch, cp81_evidence)
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP81"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.atomic_replace_retry_idempotency_validated
    assert first.all_forty_eight_parent_cases_validated
    assert first.four_recovery_invocations_per_case_validated
    assert first.all_one_hundred_ninety_two_observations_validated
    assert first.candidate_generation_stable
    assert first.exactly_once_ack_validated
    assert first.duplicate_replace_rejected
    assert first.post_ack_noop_validated


def test_cp81_policy_weakening_and_lane_drift_fail_closed(monkeypatch, cp81_evidence):
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["retry_idempotency_guard"]["duplicate_ack_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold):
        _compile_with_evidence(monkeypatch, cp81_evidence, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold):
        _compile_with_evidence(monkeypatch, cp81_evidence, lane_drift)


def test_cp81_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M50_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY"] == STATE


def test_cp81_contract_never_claims_live_authority_or_side_effects(monkeypatch, cp81_evidence):
    contract = _compile_with_evidence(monkeypatch, cp81_evidence)
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
