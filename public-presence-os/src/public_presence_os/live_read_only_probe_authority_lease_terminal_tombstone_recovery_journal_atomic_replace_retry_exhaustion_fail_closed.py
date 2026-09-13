from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency import (
    CHECKPOINT as CP81_CHECKPOINT,
    STATE as CP81_STATE,
    _build_cp81_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency,
    validate_atomic_replace_retry_idempotency_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-atomic-replace-retry-exhaustion-fail-closed-dry-run-v1.0.0"
STATE = "PASS_CP82_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED_DRY_RUN_LOCAL_ONLY_TERMINAL_HOLD_NO_RESURRECTION_NO_DUPLICATE_EFFECT_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP82"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP83_GROWTH_CAPABILITY_MATRIX_ENGAGEMENT_API_GATE"
MAX_RETRY_ATTEMPTS = 4
POST_EXHAUSTION_ORDINAL = 5
OBSERVATIONS_PER_CASE = 5
EXPECTED_PARENT_CASES = 48
EXPECTED_OBSERVATIONS = EXPECTED_PARENT_CASES * OBSERVATIONS_PER_CASE
TERMINAL_HOLD_REASON = "HOLD_CP82_RETRY_EXHAUSTED"
VALIDATION_PHASES = (
    "CP81_PARENT_EXACT_BOUND",
    "FORTY_EIGHT_PARENT_CASES_BOUND",
    "FOUR_RETRY_FAILURES_APPLIED_TO_EACH_CASE",
    "RETRY_BUDGET_EXHAUSTS_AT_EXACTLY_FOUR",
    "TERMINAL_HOLD_TRANSITIONS_EXACTLY_ONCE",
    "POST_EXHAUSTION_INVOCATION_IS_NOOP",
    "CANDIDATE_GENERATION_REMAINS_STABLE",
    "NO_ACK_OR_REPLACE_SIDE_EFFECT_DURING_FAULT_INJECTION",
    "NO_TRANSACTION_RESURRECTION_AFTER_TERMINAL_HOLD",
    "NO_DUPLICATE_EXTERNAL_EFFECT",
    "TWO_HUNDRED_FORTY_OBSERVATIONS_VALIDATED",
    "SIMULATED_ONLY_NO_STORAGE_WRITE",
    "ZERO_IO_OBSERVED",
    "AUTHORITY_REMAINS_INACTIVE",
)
REQUIRED_BLOCKERS = (
    "HOLD_REAL_EXTERNAL_AUTHORIZATION_RECEIPT_NOT_INGESTED",
    "HOLD_SECRET_REFERENCE_NOT_RESOLVED",
    "HOLD_REAL_ACCOUNT_NOT_CONNECTED",
    "HOLD_CONTROL_PLANE_PROMOTION_NOT_EXECUTED",
    "HOLD_LIVE_READ_ONLY_PROBE_NOT_EXECUTED",
    "HOLD_PILOT_PUBLISH_NOT_AUTHORIZED",
    "HOLD_CP82_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP82_RETRY_EXHAUSTION_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold(ValueError):
    pass


@dataclass(frozen=True)
class RetryExhaustionObservation:
    parent_case_index: int
    slot_index: int
    crash_window: str
    invocation_ordinal: int
    max_retry_attempts: int
    candidate_sha256: str
    visible_generation: str
    visible_sha256: str
    action: str
    retry_failure_count: int
    terminal_hold_transition_count: int
    terminal_hold: bool
    terminal_hold_reason: str | None
    ack_transition_count: int = 0
    replace_replay_count: int = 0
    external_effect_count: int = 0
    transaction_resurrected: bool = False
    simulated_only: bool = True
    storage_read_performed: bool = False
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RetryExhaustionFailClosedDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp81_contract_id: str
    cp81_contract_hash: str
    cp81_dry_run_id: str
    cp81_dry_run_hash: str
    observations: tuple[RetryExhaustionObservation, ...]
    phases: tuple[str, ...]
    outcome: str
    all_forty_eight_parent_cases_validated: bool = True
    all_two_hundred_forty_observations_validated: bool = True
    retry_budget_exactly_four_validated: bool = True
    terminal_hold_exactly_once_validated: bool = True
    post_exhaustion_noop_validated: bool = True
    no_resurrection_validated: bool = True
    no_duplicate_external_effect_validated: bool = True
    candidate_generation_stable: bool = True
    global_kill_switch_engaged: bool = True
    zero_io_observed: bool = True
    simulated_journal_only: bool = True
    storage_write_allowed: bool = False
    storage_write_performed: bool = False
    runtime_authorization_effective: bool = False
    authority_activated: bool = False
    network_allowed: bool = False
    account_connection_allowed: bool = False
    publish_allowed: bool = False
    external_write_allowed: bool = False
    deploy_allowed: bool = False
    control_plane_promoted: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["observations"] = [x.to_dict() for x in self.observations]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedContract:
    contract_id: str
    contract_hash: str
    cp81_contract_id: str
    cp81_contract_hash: str
    cp81_dry_run_id: str
    cp81_dry_run_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp81_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP81_CHECKPOINT
    parent_cp81_state: str = CP81_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    retry_exhaustion_fail_closed_validated: bool = True
    all_forty_eight_parent_cases_validated: bool = True
    four_retry_failures_per_case_validated: bool = True
    all_two_hundred_forty_observations_validated: bool = True
    terminal_hold_exactly_once_validated: bool = True
    post_exhaustion_noop_validated: bool = True
    no_resurrection_validated: bool = True
    no_duplicate_external_effect_validated: bool = True
    candidate_generation_stable: bool = True
    synthetic_validation_only: bool = True
    simulated_journal_only: bool = True
    global_kill_switch_engaged: bool = True
    external_authorization_ingested: bool = False
    authorization_granted: bool = False
    runtime_authorization_effective: bool = False
    secret_reference_resolved: bool = False
    environment_read: bool = False
    keychain_read: bool = False
    oauth_attempted: bool = False
    real_account_lookup_attempted: bool = False
    account_connected: bool = False
    network_allowed: bool = False
    network_attempted: bool = False
    live_probe_allowed: bool = False
    live_probe_attempted: bool = False
    publish_allowed: bool = False
    publish_attempted: bool = False
    external_write_allowed: bool = False
    external_write_performed: bool = False
    storage_write_allowed: bool = False
    storage_write_performed: bool = False
    control_plane_promoted: bool = False
    deploy_allowed: bool = False
    deploy_performed: bool = False
    paid_service_used: bool = False
    authority_activated: bool = False
    runtime_mutated: bool = False
    state: str = STATE

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["active_platforms"] = list(self.active_platforms)
        d["blockers"] = list(self.blockers)
        return d


def _hash(value: Any) -> str:
    return sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _without(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


def _hex(value: Any) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _validate_policy(policy: dict[str, Any]) -> None:
    if (policy.get("schema_version"), policy.get("checkpoint"), policy.get("module_id")) != (
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED_POLICY_V1",
        CHECKPOINT,
        "M51_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP81_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_SCOPE_DRIFT")
    if policy.get("max_retry_attempts") != MAX_RETRY_ATTEMPTS or policy.get("post_exhaustion_ordinal") != POST_EXHAUSTION_ORDINAL:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_RETRY_BUDGET_DRIFT")
    if tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES or tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PHASE_OR_BLOCKER_DRIFT")
    if policy.get("terminal_hold_reason") != TERMINAL_HOLD_REASON:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_TERMINAL_REASON_DRIFT")
    if policy.get("rollback_target") != CP81_CHECKPOINT or policy.get("next_after_cp82") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTINUITY_DRIFT")
    guard = policy.get("retry_exhaustion_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp81_cases_only", "exact_cp81_contract_binding_required",
        "exact_cp81_dry_run_binding_required", "all_forty_eight_parent_cases_required",
        "four_failed_attempts_before_exhaustion_required", "retry_budget_must_not_exceed_four",
        "terminal_hold_transition_exactly_once_required", "post_exhaustion_invocation_must_be_noop",
        "candidate_generation_stable_required", "ack_transition_forbidden_in_exhaustion_fixture",
        "replace_replay_forbidden_in_exhaustion_fixture", "transaction_resurrection_forbidden",
        "duplicate_external_effect_forbidden", "simulated_journal_only", "storage_read_forbidden",
        "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged",
        "runtime_network_must_remain_disabled", "account_connection_must_remain_disabled",
        "publish_must_remain_disabled", "deploy_must_remain_disabled", "control_plane_must_remain_unpromoted",
        "secret_resolution_forbidden", "environment_read_forbidden", "keychain_read_forbidden", "oauth_forbidden",
        "real_account_lookup_forbidden", "network_forbidden", "live_probe_execution_forbidden",
        "publish_forbidden", "external_write_forbidden", "control_plane_promotion_forbidden",
        "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required) or tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_GUARD_WEAKENED")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTROL_PROMOTION")
    if states.get("M50_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY") != CP81_STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CP81_STATE")
    if states.get("M51_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED") != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_MODULE_STATE")


def _expected(invocation_ordinal: int) -> tuple[str, int, int, bool, str | None]:
    if invocation_ordinal < MAX_RETRY_ATTEMPTS:
        return "SYNTHETIC_RETRYABLE_FAILURE", invocation_ordinal, 0, False, None
    if invocation_ordinal == MAX_RETRY_ATTEMPTS:
        return "ENTER_TERMINAL_HOLD_RETRY_EXHAUSTED", MAX_RETRY_ATTEMPTS, 1, True, TERMINAL_HOLD_REASON
    if invocation_ordinal == POST_EXHAUSTION_ORDINAL:
        return "NOOP_TERMINAL_HOLD", MAX_RETRY_ATTEMPTS, 1, True, TERMINAL_HOLD_REASON
    raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_INVOCATION_ORDINAL")


def _validate_observation(observation: RetryExhaustionObservation, parent_case_index: int, parent_observation: Any) -> None:
    if observation.parent_case_index != parent_case_index or observation.slot_index != parent_observation.slot_index:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_OBSERVATION_IDENTITY")
    if observation.crash_window != parent_observation.crash_window or observation.max_retry_attempts != MAX_RETRY_ATTEMPTS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_OR_BUDGET_DRIFT")
    if not _hex(observation.candidate_sha256) or observation.candidate_sha256 != parent_observation.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CANDIDATE_DIGEST")
    if observation.visible_generation != "CANDIDATE_COMPLETE" or observation.visible_sha256 != observation.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_VISIBLE_GENERATION_DRIFT")
    action, failures, hold_transitions, hold, reason = _expected(observation.invocation_ordinal)
    if (
        observation.action != action
        or observation.retry_failure_count != failures
        or observation.terminal_hold_transition_count != hold_transitions
        or observation.terminal_hold is not hold
        or observation.terminal_hold_reason != reason
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_EXHAUSTION_TRACE_DRIFT")
    if (
        observation.ack_transition_count != 0
        or observation.replace_replay_count != 0
        or observation.external_effect_count != 0
        or observation.transaction_resurrected
        or not observation.simulated_only
        or observation.storage_read_performed
        or observation.storage_write_performed
        or observation.runtime_mutated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_DUPLICATE_EFFECT_OR_MUTATION")


def build_retry_exhaustion_fail_closed_dry_run(cp81_contract: Any, cp81_dry_run: Any) -> RetryExhaustionFailClosedDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract(cp81_contract)
    if (cp81_contract.dry_run_id, cp81_contract.dry_run_hash) != (cp81_dry_run.dry_run_id, cp81_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CP81_DRY_RUN_BINDING")
    if len(cp81_dry_run.observations) != 192:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_OBSERVATION_SET")
    observations: list[RetryExhaustionObservation] = []
    for parent_case_index in range(EXPECTED_PARENT_CASES):
        parent_chunk = cp81_dry_run.observations[parent_case_index * 4:(parent_case_index + 1) * 4]
        if len(parent_chunk) != 4:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_CASE_CHUNK")
        parent_observation = parent_chunk[-1]
        if any(x.candidate_sha256 != parent_observation.candidate_sha256 for x in parent_chunk):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_CANDIDATE_DRIFT")
        for invocation_ordinal in range(1, POST_EXHAUSTION_ORDINAL + 1):
            action, failures, hold_transitions, hold, reason = _expected(invocation_ordinal)
            observation = RetryExhaustionObservation(
                parent_case_index=parent_case_index,
                slot_index=parent_observation.slot_index,
                crash_window=parent_observation.crash_window,
                invocation_ordinal=invocation_ordinal,
                max_retry_attempts=MAX_RETRY_ATTEMPTS,
                candidate_sha256=parent_observation.candidate_sha256,
                visible_generation="CANDIDATE_COMPLETE",
                visible_sha256=parent_observation.candidate_sha256,
                action=action,
                retry_failure_count=failures,
                terminal_hold_transition_count=hold_transitions,
                terminal_hold=hold,
                terminal_hold_reason=reason,
            )
            _validate_observation(observation, parent_case_index, parent_observation)
            observations.append(observation)
    dry = RetryExhaustionFailClosedDryRun(
        dry_run_id="",
        dry_run_hash="",
        cp81_contract_id=cp81_contract.contract_id,
        cp81_contract_hash=cp81_contract.contract_hash,
        cp81_dry_run_id=cp81_dry_run.dry_run_id,
        cp81_dry_run_hash=cp81_dry_run.dry_run_hash,
        observations=tuple(observations),
        phases=VALIDATION_PHASES,
        outcome=STATE,
    )
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    dry = replace(dry, dry_run_id=f"cp82_dry_run_{digest[:24]}", dry_run_hash=digest)
    validate_retry_exhaustion_fail_closed_dry_run(dry, cp81_contract, cp81_dry_run)
    return dry


def validate_retry_exhaustion_fail_closed_dry_run(dry: RetryExhaustionFailClosedDryRun, cp81_contract: Any, cp81_dry_run: Any) -> None:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract(cp81_contract)
    if (dry.cp81_contract_id, dry.cp81_contract_hash) != (cp81_contract.contract_id, cp81_contract.contract_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CP81_CONTRACT_BINDING")
    if (dry.cp81_dry_run_id, dry.cp81_dry_run_hash) != (cp81_dry_run.dry_run_id, cp81_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CP81_DRY_RUN_BINDING")
    if len(dry.observations) != EXPECTED_OBSERVATIONS or tuple(dry.phases) != VALIDATION_PHASES or dry.outcome != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_DRY_RUN_SHAPE")
    if len(cp81_dry_run.observations) != 192:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_PARENT_OBSERVATION_SET")
    for parent_case_index in range(EXPECTED_PARENT_CASES):
        parent_observation = cp81_dry_run.observations[parent_case_index * 4 + 3]
        chunk = dry.observations[parent_case_index * OBSERVATIONS_PER_CASE:(parent_case_index + 1) * OBSERVATIONS_PER_CASE]
        if tuple(x.invocation_ordinal for x in chunk) != (1, 2, 3, 4, 5):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_INVOCATION_SEQUENCE")
        for x in chunk:
            _validate_observation(x, parent_case_index, parent_observation)
        if [x.retry_failure_count for x in chunk] != [1, 2, 3, 4, 4]:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_RETRY_FAILURE_COUNT")
        if [x.terminal_hold_transition_count for x in chunk] != [0, 0, 0, 1, 1]:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_TERMINAL_HOLD_COUNT")
        if [x.terminal_hold for x in chunk] != [False, False, False, True, True]:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_TERMINAL_HOLD_STATE")
        if chunk[-1].action != "NOOP_TERMINAL_HOLD":
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_POST_EXHAUSTION_NOT_NOOP")
    flags = (
        dry.all_forty_eight_parent_cases_validated,
        dry.all_two_hundred_forty_observations_validated,
        dry.retry_budget_exactly_four_validated,
        dry.terminal_hold_exactly_once_validated,
        dry.post_exhaustion_noop_validated,
        dry.no_resurrection_validated,
        dry.no_duplicate_external_effect_validated,
        dry.candidate_generation_stable,
        dry.global_kill_switch_engaged,
        dry.zero_io_observed,
        dry.simulated_journal_only,
    )
    if not all(flags):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_VALIDATION_FLAG")
    if any((
        dry.storage_write_allowed, dry.storage_write_performed, dry.runtime_authorization_effective,
        dry.authority_activated, dry.network_allowed, dry.account_connection_allowed,
        dry.publish_allowed, dry.external_write_allowed, dry.deploy_allowed,
        dry.control_plane_promoted, dry.runtime_mutated,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_LIVE_OR_MUTATION_CLAIM")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp82_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_DRY_RUN_HASH")


def _build_cp82_evidence(root: Path) -> tuple[Any, Any, Any]:
    cp80_contract, cp80_dry, cp81_dry = _build_cp81_evidence(root)
    cp81_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_policy.json")
    cp81_contract = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency(root, cp81_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract(cp81_contract)
    validate_atomic_replace_retry_idempotency_dry_run(cp81_dry, cp80_contract, cp80_dry)
    dry = build_retry_exhaustion_fail_closed_dry_run(cp81_contract, cp81_dry)
    return cp81_contract, cp81_dry, dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp81_contract, cp81_dry, dry = _build_cp82_evidence(root)
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedContract(
        contract_id="",
        contract_hash="",
        cp81_contract_id=cp81_contract.contract_id,
        cp81_contract_hash=cp81_contract.contract_hash,
        cp81_dry_run_id=cp81_dry.dry_run_id,
        cp81_dry_run_hash=cp81_dry.dry_run_hash,
        dry_run_id=dry.dry_run_id,
        dry_run_hash=dry.dry_run_hash,
        policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed_policy.json").read_bytes()).hexdigest(),
        cp81_policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_policy.json").read_bytes()).hexdigest(),
        runtime_policy_sha256=sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        module_registry_sha256=sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        active_platforms=EXPECTED_ACTIVE,
        blockers=REQUIRED_BLOCKERS,
    )
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    contract = replace(contract, contract_id=f"cp82_contract_{digest[:24]}", contract_hash=digest)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_exhaustion_fail_closed_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedContract,
) -> None:
    if (
        contract.checkpoint,
        contract.parent_control_checkpoint,
        contract.parent_activation_checkpoint,
        contract.parent_cp81_state,
        contract.next_unit,
        contract.state,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP81_CHECKPOINT, CP81_STATE, NEXT_UNIT, STATE):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_IDENTITY")
    if contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_SCOPE")
    if not all(_hex(x) for x in (
        contract.contract_hash, contract.cp81_contract_hash, contract.cp81_dry_run_hash,
        contract.dry_run_hash, contract.policy_sha256, contract.cp81_policy_sha256,
        contract.runtime_policy_sha256, contract.module_registry_sha256,
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_DIGEST")
    true_flags = (
        contract.retry_exhaustion_fail_closed_validated,
        contract.all_forty_eight_parent_cases_validated,
        contract.four_retry_failures_per_case_validated,
        contract.all_two_hundred_forty_observations_validated,
        contract.terminal_hold_exactly_once_validated,
        contract.post_exhaustion_noop_validated,
        contract.no_resurrection_validated,
        contract.no_duplicate_external_effect_validated,
        contract.candidate_generation_stable,
        contract.synthetic_validation_only,
        contract.simulated_journal_only,
        contract.global_kill_switch_engaged,
    )
    if not all(true_flags):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_VALIDATION_FLAG")
    false_fields = (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted",
        "real_account_lookup_attempted", "account_connected", "network_allowed", "network_attempted",
        "live_probe_allowed", "live_probe_attempted", "publish_allowed", "publish_attempted",
        "external_write_allowed", "external_write_performed", "storage_write_allowed", "storage_write_performed",
        "control_plane_promoted", "deploy_allowed", "deploy_performed", "paid_service_used",
        "authority_activated", "runtime_mutated",
    )
    if any(getattr(contract, field) for field in false_fields):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_LIVE_OR_MUTATION_CLAIM")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp82_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryExhaustionFailClosedHold("HOLD_CP82_CONTRACT_HASH")
