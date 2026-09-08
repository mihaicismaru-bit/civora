from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from public_presence_os.control import EXPECTED_ACTIVE, load_json
import public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection as cp78_module
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_corruption_rejection import build_valid_recovery_journal
from public_presence_os.live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection import (
    CHECKPOINT,
    EXPECTED_HOLD,
    NEXT_UNIT,
    PARENT_CONTROL_CHECKPOINT,
    STATE,
    TRUNCATION_CLASSES,
    LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold,
    _build_cp78_evidence,
    _cut_offset,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection,
    serialize_recovery_journal,
    validate_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run,
    validate_complete_serialized_recovery_journal,
)

ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = ROOT / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_policy.json"


@pytest.fixture(scope="module")
def cp78_evidence():
    return _build_cp78_evidence(ROOT)


def _compile_with_evidence(monkeypatch, evidence, policy=None):
    monkeypatch.setattr(cp78_module, "_build_cp78_evidence", lambda root: evidence)
    return compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection(
        ROOT, policy or load_json(POLICY_PATH)
    )


def test_cp78_dry_run_accepts_twelve_complete_controls_and_rejects_sixty_strict_prefixes(cp78_evidence):
    cp76, cp76_dry, cp77_dry, dry = cp78_evidence
    assert len(dry.positive_control_serialized_sha256s) == 12
    assert len(dry.rejection_cases) == 60
    assert tuple(x.truncation_class for x in dry.rejection_cases) == TRUNCATION_CLASSES * 12
    assert dry.all_complete_controls_accepted
    assert dry.all_partial_writes_rejected
    for result in dry.rejection_cases:
        assert result.rejected
        assert result.rejection_before_parse
        assert result.rejection_before_recovery_effect
        assert result.recovery_effect_count == 0
        assert result.baseline_preserved
        assert result.expected_hold == EXPECTED_HOLD
        assert result.observed_hold == EXPECTED_HOLD
        assert 0 <= result.observed_length < result.expected_length
        assert result.simulated_journal_only
        assert not result.storage_write_performed
        assert not result.runtime_mutated
    validate_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
        dry, cp76, cp76_dry, cp77_dry
    )


def test_cp78_complete_bytes_are_accepted_and_each_truncation_class_fails_before_parse(cp78_evidence):
    cp76, cp76_dry, _, _ = cp78_evidence
    for parent_case in cp76_dry.crash_cases:
        journal = build_valid_recovery_journal(parent_case, cp76)
        raw = serialize_recovery_journal(journal)
        import hashlib
        digest = hashlib.sha256(raw).hexdigest()
        assert validate_complete_serialized_recovery_journal(raw, len(raw), digest, parent_case, cp76) == journal
        for truncation_class in TRUNCATION_CLASSES:
            cut = _cut_offset(raw, truncation_class)
            assert 0 <= cut < len(raw)
            with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold) as exc:
                validate_complete_serialized_recovery_journal(raw[:cut], len(raw), digest, parent_case, cp76)
            assert str(exc.value) == EXPECTED_HOLD


def test_cp78_exact_length_digest_tamper_is_rejected(cp78_evidence):
    cp76, cp76_dry, _, _ = cp78_evidence
    parent_case = cp76_dry.crash_cases[0]
    raw = serialize_recovery_journal(build_valid_recovery_journal(parent_case, cp76))
    import hashlib
    digest = hashlib.sha256(raw).hexdigest()
    tampered = raw[:-2] + (b"0" if raw[-2:-1] != b"0" else b"1") + raw[-1:]
    assert len(tampered) == len(raw)
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold) as exc:
        validate_complete_serialized_recovery_journal(tampered, len(raw), digest, parent_case, cp76)
    assert str(exc.value) == "HOLD_CP78_SERIALIZED_SHA256"


def test_cp78_contract_is_deterministic_and_keeps_control_plane_held(monkeypatch, cp78_evidence):
    first = _compile_with_evidence(monkeypatch, cp78_evidence)
    second = _compile_with_evidence(monkeypatch, cp78_evidence)
    assert first == second
    assert first.checkpoint == CHECKPOINT == "CP78"
    assert first.parent_control_checkpoint == PARENT_CONTROL_CHECKPOINT == "CP58"
    assert first.next_unit == NEXT_UNIT
    assert first.state == STATE
    assert first.active_platforms == EXPECTED_ACTIVE
    assert first.complete_journal_positive_controls_validated
    assert first.partial_write_truncation_rejection_validated
    assert first.all_five_truncation_classes_validated
    assert first.all_twelve_parent_journals_validated
    assert first.all_sixty_partial_writes_rejected
    assert first.baseline_preservation_validated


def test_cp78_dry_run_tamper_and_policy_weakening_fail_closed(monkeypatch, cp78_evidence):
    cp76, cp76_dry, cp77_dry, dry = cp78_evidence
    broken_case = replace(dry.rejection_cases[0], baseline_preserved=False)
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold):
        validate_authority_lease_terminal_tombstone_recovery_journal_partial_write_truncation_rejection_dry_run(
            replace(dry, rejection_cases=(broken_case,) + dry.rejection_cases[1:]), cp76, cp76_dry, cp77_dry
        )
    policy = load_json(POLICY_PATH)
    weakened = deepcopy(policy)
    weakened["partial_write_guard"]["storage_write_forbidden"] = False
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold):
        _compile_with_evidence(monkeypatch, cp78_evidence, weakened)
    lane_drift = deepcopy(policy)
    lane_drift["active_platforms"] = ["FACEBOOK_PAGE", "THREADS"]
    with pytest.raises(LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalPartialWriteTruncationRejectionHold):
        _compile_with_evidence(monkeypatch, cp78_evidence, lane_drift)


def test_cp78_registry_is_locked_without_promoting_global_checkpoint():
    registry = load_json(ROOT / "config" / "module_registry.json")
    states = {x["id"]: x["status"] for x in registry["modules"]}
    assert registry["checkpoint"] == "CP58"
    assert states["M47_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_PARTIAL_WRITE_TRUNCATION_REJECTION"] == STATE


def test_cp78_contract_never_claims_live_authority_or_side_effects(monkeypatch, cp78_evidence):
    contract = _compile_with_evidence(monkeypatch, cp78_evidence)
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
