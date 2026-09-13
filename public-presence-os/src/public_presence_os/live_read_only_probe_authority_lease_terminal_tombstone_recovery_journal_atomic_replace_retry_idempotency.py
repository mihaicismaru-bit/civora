from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window import (
    CHECKPOINT as CP80_CHECKPOINT,
    STATE as CP80_STATE,
    _build_cp80_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window,
    validate_atomic_replace_crash_window_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-atomic-replace-retry-idempotency-dry-run-v1.0.0"
STATE = "PASS_CP81_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_DRY_RUN_LOCAL_ONLY_EXACTLY_ONCE_ACK_NO_DUPLICATE_REPLACE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP81"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP82_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_EXHAUSTION_FAIL_CLOSED_DRY_RUN"
RETRY_ORDINALS = (1, 2, 3, 4)
VALIDATION_PHASES = (
    "CP80_PARENT_EXACT_BOUND",
    "FORTY_EIGHT_PARENT_CRASH_CASES_BOUND",
    "FOUR_RECOVERY_INVOCATIONS_APPLIED_TO_EACH_CASE",
    "ONE_HUNDRED_NINETY_TWO_RETRY_OBSERVATIONS_VALIDATED",
    "CANDIDATE_GENERATION_STABLE_AFTER_FIRST_RECOVERY",
    "BASELINE_VISIBLE_REPLACE_REPLAY_OCCURS_AT_MOST_ONCE",
    "CANDIDATE_VISIBLE_REPLACE_REPLAY_NEVER_OCCURS",
    "ACK_FINALIZATION_TRANSITIONS_EXACTLY_ONCE",
    "POST_ACK_RETRIES_ARE_NOOP",
    "DUPLICATE_ACK_REPLACE_AND_TRANSACTION_RESURRECTION_FORBIDDEN",
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
    "HOLD_CP81_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP81_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold(ValueError):
    pass


@dataclass(frozen=True)
class AtomicReplaceRetryObservation:
    parent_case_index: int
    slot_index: int
    crash_window: str
    retry_ordinal: int
    parent_visible_generation: str
    candidate_sha256: str
    visible_generation: str
    visible_sha256: str
    action: str
    replace_replay_count: int
    ack_transition_count: int
    ack_finalized: bool
    duplicate_ack_observed: bool = False
    duplicate_replace_observed: bool = False
    transaction_resurrected: bool = False
    simulated_only: bool = True
    storage_read_performed: bool = False
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtomicReplaceRetryIdempotencyDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp80_contract_id: str
    cp80_contract_hash: str
    cp80_dry_run_id: str
    cp80_dry_run_hash: str
    lease_id: str
    lease_hash: str
    observations: tuple[AtomicReplaceRetryObservation, ...]
    phases: tuple[str, ...]
    outcome: str
    all_forty_eight_parent_cases_validated: bool = True
    all_one_hundred_ninety_two_observations_validated: bool = True
    candidate_generation_stable: bool = True
    exactly_once_ack_validated: bool = True
    duplicate_replace_rejected: bool = True
    post_ack_noop_validated: bool = True
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
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyContract:
    contract_id: str
    contract_hash: str
    cp80_contract_id: str
    cp80_contract_hash: str
    cp80_dry_run_id: str
    cp80_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp80_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP80_CHECKPOINT
    parent_cp80_state: str = CP80_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    atomic_replace_retry_idempotency_validated: bool = True
    all_forty_eight_parent_cases_validated: bool = True
    four_recovery_invocations_per_case_validated: bool = True
    all_one_hundred_ninety_two_observations_validated: bool = True
    candidate_generation_stable: bool = True
    exactly_once_ack_validated: bool = True
    duplicate_replace_rejected: bool = True
    post_ack_noop_validated: bool = True
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
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_POLICY_V1",
        CHECKPOINT,
        "M50_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP80_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_SCOPE_DRIFT")
    if tuple(policy.get("retry_ordinals", ())) != RETRY_ORDINALS or tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_RETRY_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP80_CHECKPOINT or policy.get("next_after_cp81") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTINUITY_DRIFT")
    guard = policy.get("retry_idempotency_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp80_crash_cases_only",
        "exact_cp80_contract_binding_required", "exact_cp80_dry_run_binding_required", "exact_lease_binding_required",
        "all_forty_eight_parent_cases_required", "four_recovery_invocations_per_case_required",
        "exactly_one_hundred_ninety_two_observations_required", "candidate_generation_stable_after_first_recovery_required",
        "baseline_visible_replace_replay_occurs_at_most_once", "candidate_visible_replace_replay_never_occurs",
        "ack_finalized_exactly_once_required", "duplicate_ack_forbidden", "duplicate_replace_forbidden",
        "transaction_resurrection_forbidden", "post_ack_retry_must_be_noop",
        "retry_trace_must_converge_to_candidate_hash", "simulated_journal_only",
        "storage_read_forbidden", "storage_write_forbidden", "runtime_mutation_forbidden", "registry_mutation_forbidden",
        "policy_mutation_forbidden", "global_kill_switch_must_remain_engaged",
        "runtime_network_must_remain_disabled", "account_connection_must_remain_disabled",
        "publish_must_remain_disabled", "deploy_must_remain_disabled", "control_plane_must_remain_unpromoted",
        "secret_resolution_forbidden", "environment_read_forbidden", "keychain_read_forbidden", "oauth_forbidden",
        "real_account_lookup_forbidden", "network_forbidden", "live_probe_execution_forbidden",
        "publish_forbidden", "external_write_forbidden", "control_plane_promotion_forbidden",
        "deploy_forbidden", "paid_service_forbidden", "authority_activation_forbidden",
    )
    if any(guard.get(key) is not True for key in required) or tuple(guard.get("method_allowlist", ())) != ("GET",):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_GUARD_WEAKENED")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTROL_PROMOTION")
    if states.get("M49_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW") != CP80_STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CP80_STATE")
    if states.get("M50_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY") != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_MODULE_STATE")


def _expected_trace(parent_case: Any, retry_ordinal: int) -> tuple[str, int, int, bool]:
    baseline_initial = parent_case.visible_generation == "BASELINE_COMPLETE"
    if baseline_initial and retry_ordinal == 1:
        return "REPLAY_ATOMIC_REPLACE", 1, 0, False
    if (baseline_initial and retry_ordinal == 2) or (not baseline_initial and retry_ordinal == 1):
        return "FINALIZE_ACK_ONCE", 1 if baseline_initial else 0, 1, True
    return "NOOP_ALREADY_ACKED", 1 if baseline_initial else 0, 1, True


def _validate_observation(observation: AtomicReplaceRetryObservation, parent_case: Any) -> None:
    if observation.parent_case_index < 0 or observation.slot_index != parent_case.slot_index:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_OBSERVATION_IDENTITY")
    if observation.crash_window != parent_case.crash_window or observation.retry_ordinal not in RETRY_ORDINALS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_OBSERVATION_RETRY")
    if observation.parent_visible_generation != parent_case.visible_generation:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_PARENT_VISIBILITY_DRIFT")
    if not all(_hex(x) for x in (observation.candidate_sha256, observation.visible_sha256)):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_DIGEST")
    if observation.candidate_sha256 != parent_case.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CANDIDATE_BINDING")
    if observation.visible_generation != "CANDIDATE_COMPLETE" or observation.visible_sha256 != parent_case.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CANDIDATE_NOT_STABLE")
    expected = _expected_trace(parent_case, observation.retry_ordinal)
    if (
        observation.action,
        observation.replace_replay_count,
        observation.ack_transition_count,
        observation.ack_finalized,
    ) != expected:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_RETRY_TRACE")
    if (
        observation.duplicate_ack_observed or observation.duplicate_replace_observed or observation.transaction_resurrected
        or not observation.simulated_only or observation.storage_read_performed or observation.storage_write_performed
        or observation.runtime_mutated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_DUPLICATE_OR_MUTATION")


def build_atomic_replace_retry_idempotency_dry_run(cp80_contract: Any, cp80_dry_run: Any) -> AtomicReplaceRetryIdempotencyDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_contract(cp80_contract)
    if (cp80_contract.dry_run_id, cp80_contract.dry_run_hash) != (cp80_dry_run.dry_run_id, cp80_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CP80_DRY_RUN_BINDING")
    if len(cp80_dry_run.cases) != 48:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_PARENT_CASE_SET")
    observations: list[AtomicReplaceRetryObservation] = []
    for parent_index, parent_case in enumerate(cp80_dry_run.cases):
        for retry_ordinal in RETRY_ORDINALS:
            action, replace_count, ack_count, ack_finalized = _expected_trace(parent_case, retry_ordinal)
            observation = AtomicReplaceRetryObservation(
                parent_case_index=parent_index,
                slot_index=parent_case.slot_index,
                crash_window=parent_case.crash_window,
                retry_ordinal=retry_ordinal,
                parent_visible_generation=parent_case.visible_generation,
                candidate_sha256=parent_case.candidate_sha256,
                visible_generation="CANDIDATE_COMPLETE",
                visible_sha256=parent_case.candidate_sha256,
                action=action,
                replace_replay_count=replace_count,
                ack_transition_count=ack_count,
                ack_finalized=ack_finalized,
            )
            _validate_observation(observation, parent_case)
            observations.append(observation)
    dry = AtomicReplaceRetryIdempotencyDryRun(
        dry_run_id="",
        dry_run_hash="",
        cp80_contract_id=cp80_contract.contract_id,
        cp80_contract_hash=cp80_contract.contract_hash,
        cp80_dry_run_id=cp80_dry_run.dry_run_id,
        cp80_dry_run_hash=cp80_dry_run.dry_run_hash,
        lease_id=cp80_contract.lease_id,
        lease_hash=cp80_contract.lease_hash,
        observations=tuple(observations),
        phases=VALIDATION_PHASES,
        outcome="SIMULATED_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_PASS_48_PARENT_CASES_192_OF_192_RECOVERY_INVOCATIONS_EXACTLY_ONCE_ACK_NO_DUPLICATE_REPLACE_CANDIDATE_HASH_STABLE_NO_STORAGE_WRITE_NO_AUTHORITY",
    )
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    dry = replace(dry, dry_run_id=f"cp81_dry_run_{digest[:24]}", dry_run_hash=digest)
    validate_atomic_replace_retry_idempotency_dry_run(dry, cp80_contract, cp80_dry_run)
    return dry


def validate_atomic_replace_retry_idempotency_dry_run(
    dry: AtomicReplaceRetryIdempotencyDryRun,
    cp80_contract: Any,
    cp80_dry_run: Any,
) -> None:
    if (
        dry.cp80_contract_id,
        dry.cp80_contract_hash,
        dry.cp80_dry_run_id,
        dry.cp80_dry_run_hash,
        dry.lease_id,
        dry.lease_hash,
    ) != (
        cp80_contract.contract_id,
        cp80_contract.contract_hash,
        cp80_dry_run.dry_run_id,
        cp80_dry_run.dry_run_hash,
        cp80_contract.lease_id,
        cp80_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_PARENT_BINDING")
    if len(dry.observations) != 192:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_OBSERVATION_SET")
    for parent_index, parent_case in enumerate(cp80_dry_run.cases):
        chunk = dry.observations[parent_index * 4:(parent_index + 1) * 4]
        if tuple(x.retry_ordinal for x in chunk) != RETRY_ORDINALS:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_RETRY_ORDINAL_SET")
        if any(x.parent_case_index != parent_index for x in chunk):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_PARENT_CASE_INDEX_DRIFT")
        for observation in chunk:
            _validate_observation(observation, parent_case)
        if chunk[-1].visible_sha256 != parent_case.candidate_sha256 or not chunk[-1].ack_finalized:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_FINAL_STATE")
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_PASS_48_PARENT_CASES_192_OF_192_RECOVERY_INVOCATIONS_EXACTLY_ONCE_ACK_NO_DUPLICATE_REPLACE_CANDIDATE_HASH_STABLE_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_OUTCOME_OR_PHASES")
    if (
        not dry.all_forty_eight_parent_cases_validated
        or not dry.all_one_hundred_ninety_two_observations_validated
        or not dry.candidate_generation_stable
        or not dry.exactly_once_ack_validated
        or not dry.duplicate_replace_rejected
        or not dry.post_ack_noop_validated
        or not dry.global_kill_switch_engaged
        or not dry.zero_io_observed
        or not dry.simulated_journal_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_GUARD")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed",
        "deploy_allowed", "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp81_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_DRY_RUN_HASH")


def _build_cp81_evidence(root: Path) -> tuple[Any, Any, Any]:
    cp79_contract, cp79_dry, cp80_dry = _build_cp80_evidence(root)
    cp80_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_policy.json")
    cp80_contract = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window(root, cp80_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_contract(cp80_contract)
    validate_atomic_replace_crash_window_dry_run(cp80_dry, cp79_contract, cp79_dry)
    dry = build_atomic_replace_retry_idempotency_dry_run(cp80_contract, cp80_dry)
    return cp80_contract, cp80_dry, dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp80_contract, cp80_dry, dry = _build_cp81_evidence(root)
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyContract(
        contract_id="",
        contract_hash="",
        cp80_contract_id=cp80_contract.contract_id,
        cp80_contract_hash=cp80_contract.contract_hash,
        cp80_dry_run_id=cp80_dry.dry_run_id,
        cp80_dry_run_hash=cp80_dry.dry_run_hash,
        lease_id=cp80_contract.lease_id,
        lease_hash=cp80_contract.lease_hash,
        dry_run_id=dry.dry_run_id,
        dry_run_hash=dry.dry_run_hash,
        policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_policy.json").read_bytes()).hexdigest(),
        cp80_policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_policy.json").read_bytes()).hexdigest(),
        runtime_policy_sha256=sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        module_registry_sha256=sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        active_platforms=EXPECTED_ACTIVE,
        blockers=REQUIRED_BLOCKERS,
    )
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    contract = replace(contract, contract_id=f"cp81_contract_{digest[:24]}", contract_hash=digest)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_retry_idempotency_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyContract,
) -> None:
    if (
        contract.checkpoint,
        contract.parent_control_checkpoint,
        contract.parent_activation_checkpoint,
        contract.parent_cp80_state,
        contract.state,
        contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP80_CHECKPOINT, CP80_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE
        or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged
        or not contract.synthetic_validation_only
        or not contract.simulated_journal_only
        or not contract.atomic_replace_retry_idempotency_validated
        or not contract.all_forty_eight_parent_cases_validated
        or not contract.four_recovery_invocations_per_case_validated
        or not contract.all_one_hundred_ninety_two_observations_validated
        or not contract.candidate_generation_stable
        or not contract.exactly_once_ack_validated
        or not contract.duplicate_replace_rejected
        or not contract.post_ack_noop_validated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted",
        "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed",
        "storage_write_allowed", "storage_write_performed", "control_plane_promoted", "deploy_allowed",
        "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(getattr(contract, key)) for key in (
        "cp80_contract_hash", "cp80_dry_run_hash", "lease_hash", "dry_run_hash",
        "policy_sha256", "cp80_policy_sha256", "runtime_policy_sha256", "module_registry_sha256",
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp81_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceRetryIdempotencyHold("HOLD_CP81_CONTRACT_HASH")
