from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from pathlib import Path
import re
from typing import Any

from .control import EXPECTED_ACTIVE, canonical_json, load_json, validate_policy
from .live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility import (
    CHECKPOINT as CP79_CHECKPOINT,
    STATE as CP79_STATE,
    _build_cp79_evidence,
    compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility,
    validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run,
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_contract,
)

MODEL_VERSION = "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW_DRY_RUN_V1"
ENGINE_VERSION = "ppos-live-read-only-probe-authority-lease-terminal-tombstone-recovery-journal-atomic-replace-crash-window-dry-run-v1.0.0"
STATE = "PASS_CP80_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW_DRY_RUN_LOCAL_ONLY_NO_TORN_REPLACE_NO_STORAGE_MUTATION_NO_RUNTIME_AUTHORITY_LIVE_HOLD"
CHECKPOINT = "CP80"
PARENT_CONTROL_CHECKPOINT = "CP58"
NEXT_UNIT = "CP81_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_RETRY_IDEMPOTENCY_DRY_RUN"
CRASH_WINDOWS = (
    "AFTER_STAGE_BEFORE_REPLACE",
    "REPLACE_BOUNDARY_BASELINE_WINS",
    "REPLACE_BOUNDARY_CANDIDATE_WINS",
    "AFTER_REPLACE_BEFORE_ACK",
)
VALIDATION_PHASES = (
    "CP79_PARENT_EXACT_BOUND",
    "TWELVE_DISTINCT_COMPLETE_GENERATION_PAIRS_BOUND",
    "FOUR_CRASH_WINDOWS_APPLIED_TO_EACH_PAIR",
    "FORTY_EIGHT_RESTART_CASES_VALIDATED",
    "RESTART_SEES_EXACTLY_ONE_COMPLETE_GENERATION",
    "ABSENT_PARTIAL_AND_MIXED_GENERATIONS_FORBIDDEN",
    "BASELINE_WIN_REPLAYS_REPLACE_DETERMINISTICALLY",
    "CANDIDATE_WIN_FINALIZES_ACK_IDEMPOTENTLY",
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
    "HOLD_CP80_RECOVERY_JOURNAL_SOURCE_SYNTHETIC_ONLY",
    "HOLD_CP80_ATOMIC_REPLACE_CRASH_WINDOW_PASS_IS_NOT_RUNTIME_AUTHORITY",
)
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold(ValueError):
    pass


@dataclass(frozen=True)
class AtomicReplaceCrashCase:
    slot_index: int
    crash_window: str
    baseline_parent_transaction_id: str
    candidate_parent_transaction_id: str
    baseline_length: int
    baseline_sha256: str
    candidate_length: int
    candidate_sha256: str
    visible_generation: str
    visible_length: int
    visible_sha256: str
    restart_action: str
    restart_converged_sha256: str
    complete_generation_visible: bool = True
    absent_visibility_observed: bool = False
    partial_visibility_observed: bool = False
    mixed_generation_observed: bool = False
    simulated_only: bool = True
    storage_read_performed: bool = False
    storage_write_performed: bool = False
    runtime_mutated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AtomicReplaceCrashWindowDryRun:
    dry_run_id: str
    dry_run_hash: str
    cp79_contract_id: str
    cp79_contract_hash: str
    cp79_dry_run_id: str
    cp79_dry_run_hash: str
    lease_id: str
    lease_hash: str
    cases: tuple[AtomicReplaceCrashCase, ...]
    phases: tuple[str, ...]
    outcome: str
    all_twelve_pairs_validated: bool = True
    all_forty_eight_crash_cases_validated: bool = True
    exact_one_complete_generation_after_restart: bool = True
    deterministic_retry_or_finalize_validated: bool = True
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
        d["cases"] = [x.to_dict() for x in self.cases]
        d["phases"] = list(self.phases)
        return d


@dataclass(frozen=True)
class LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowContract:
    contract_id: str
    contract_hash: str
    cp79_contract_id: str
    cp79_contract_hash: str
    cp79_dry_run_id: str
    cp79_dry_run_hash: str
    lease_id: str
    lease_hash: str
    dry_run_id: str
    dry_run_hash: str
    policy_sha256: str
    cp79_policy_sha256: str
    runtime_policy_sha256: str
    module_registry_sha256: str
    active_platforms: tuple[str, ...]
    blockers: tuple[str, ...]
    next_unit: str = NEXT_UNIT
    checkpoint: str = CHECKPOINT
    parent_control_checkpoint: str = PARENT_CONTROL_CHECKPOINT
    parent_activation_checkpoint: str = CP79_CHECKPOINT
    parent_cp79_state: str = CP79_STATE
    model_version: str = MODEL_VERSION
    engine_version: str = ENGINE_VERSION
    atomic_replace_crash_window_validated: bool = True
    all_twelve_pairs_validated: bool = True
    all_four_crash_windows_validated: bool = True
    all_forty_eight_restart_cases_validated: bool = True
    deterministic_retry_or_finalize_validated: bool = True
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
        "PPOS_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW_POLICY_V1",
        CHECKPOINT,
        "M49_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW",
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_POLICY_IDENTITY")
    if policy.get("parent_activation_checkpoint") != CP79_CHECKPOINT or policy.get("parent_control_checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_PARENT_DRIFT")
    if tuple(policy.get("active_platforms", ())) != EXPECTED_ACTIVE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_SCOPE_DRIFT")
    if tuple(policy.get("crash_windows", ())) != CRASH_WINDOWS or tuple(policy.get("validation_phases", ())) != VALIDATION_PHASES:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_WINDOW_OR_PHASE_DRIFT")
    if tuple(policy.get("required_blockers", ())) != REQUIRED_BLOCKERS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_BLOCKER_DRIFT")
    if policy.get("rollback_target") != CP79_CHECKPOINT or policy.get("next_after_cp80") != NEXT_UNIT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTINUITY_DRIFT")
    guard = policy.get("atomic_replace_guard", {})
    required = (
        "local_only", "zero_io_required", "synthetic_cp79_journal_only",
        "exact_cp79_contract_binding_required", "exact_cp79_dry_run_binding_required", "exact_lease_binding_required",
        "all_twelve_replacement_pairs_required", "all_four_crash_windows_required",
        "exactly_forty_eight_restart_cases_required", "baseline_and_candidate_must_be_distinct_complete_generations",
        "restart_visibility_must_be_one_complete_generation", "absent_visibility_forbidden",
        "partial_visibility_forbidden", "mixed_generation_forbidden",
        "baseline_winner_must_retry_replace", "candidate_winner_must_finalize_ack_idempotently",
        "restart_must_converge_to_candidate_generation", "simulated_journal_only",
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
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_GUARD_WEAKENED")
    if policy.get("excluded_platforms") != {
        "LINKEDIN": "HOLD_UNTIL_PRODUCTION_API_ACCESS",
        "X": "EXCLUDED_WHILE_API_IS_PAID",
        "BLUESKY": "HOLD_UNTIL_LOCAL_ROI_TEST_PASSES",
    }:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_DEFERRED_LANE_DRIFT")
    if not isinstance(policy.get("authority"), dict) or any(policy["authority"].values()):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_AUTHORITY_NOT_ZERO")


def _validate_root(root: Path) -> None:
    runtime = load_json(root / "config" / "runtime_policy.json")
    registry = load_json(root / "config" / "module_registry.json")
    if not validate_policy(runtime).ok or runtime.get("global_kill_switch_engaged") is not True:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_RUNTIME_POLICY")
    if any(runtime.get(key) is not False for key in ("network_enabled", "account_connection_enabled", "publish_enabled", "deploy_enabled")):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_LIVE_BOUNDARY")
    states = {x.get("id"): x.get("status") for x in registry.get("modules", [])}
    if registry.get("checkpoint") != PARENT_CONTROL_CHECKPOINT:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTROL_PROMOTION")
    if states.get("M48_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_COMPLETE_WRITE_ATOMIC_VISIBILITY") != CP79_STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CP79_STATE")
    if states.get("M49_LIVE_READ_ONLY_PROBE_AUTHORITY_LEASE_TERMINAL_TOMBSTONE_RECOVERY_JOURNAL_ATOMIC_REPLACE_CRASH_WINDOW") != STATE:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_MODULE_STATE")


def _validate_case(case: AtomicReplaceCrashCase) -> None:
    if case.slot_index < 0 or case.crash_window not in CRASH_WINDOWS:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CASE_IDENTITY")
    if case.baseline_length <= 0 or case.candidate_length <= 0:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_LENGTH")
    if not all(_hex(x) for x in (case.baseline_sha256, case.candidate_sha256, case.visible_sha256, case.restart_converged_sha256)):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_DIGEST")
    if case.baseline_sha256 == case.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_GENERATIONS_NOT_DISTINCT")
    if (
        not case.complete_generation_visible or case.absent_visibility_observed or case.partial_visibility_observed
        or case.mixed_generation_observed or not case.simulated_only
        or case.storage_read_performed or case.storage_write_performed or case.runtime_mutated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_TORN_OR_MUTATING_RESTART")
    baseline_wins = case.crash_window in ("AFTER_STAGE_BEFORE_REPLACE", "REPLACE_BOUNDARY_BASELINE_WINS")
    if baseline_wins:
        expected = ("BASELINE_COMPLETE", case.baseline_length, case.baseline_sha256, "REPLAY_ATOMIC_REPLACE")
    else:
        expected = ("CANDIDATE_COMPLETE", case.candidate_length, case.candidate_sha256, "FINALIZE_ACK_IDEMPOTENTLY")
    if (case.visible_generation, case.visible_length, case.visible_sha256, case.restart_action) != expected:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_RESTART_VISIBILITY")
    if case.restart_converged_sha256 != case.candidate_sha256:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_RESTART_CONVERGENCE")


def build_atomic_replace_crash_window_dry_run(cp79_contract: Any, cp79_dry_run: Any) -> AtomicReplaceCrashWindowDryRun:
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_contract(cp79_contract)
    if (cp79_contract.dry_run_id, cp79_contract.dry_run_hash) != (cp79_dry_run.dry_run_id, cp79_dry_run.dry_run_hash):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CP79_DRY_RUN_BINDING")
    generations = cp79_dry_run.visibility_cases
    if len(generations) != 12:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_PARENT_CASE_SET")
    cases = []
    for index, baseline in enumerate(generations):
        candidate = generations[(index + 1) % len(generations)]
        if baseline.complete_serialized_sha256 == candidate.complete_serialized_sha256:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_GENERATIONS_NOT_DISTINCT")
        for window in CRASH_WINDOWS:
            baseline_wins = window in ("AFTER_STAGE_BEFORE_REPLACE", "REPLACE_BOUNDARY_BASELINE_WINS")
            visible = baseline if baseline_wins else candidate
            case = AtomicReplaceCrashCase(
                slot_index=index,
                crash_window=window,
                baseline_parent_transaction_id=baseline.parent_transaction_id,
                candidate_parent_transaction_id=candidate.parent_transaction_id,
                baseline_length=baseline.complete_serialized_length,
                baseline_sha256=baseline.complete_serialized_sha256,
                candidate_length=candidate.complete_serialized_length,
                candidate_sha256=candidate.complete_serialized_sha256,
                visible_generation="BASELINE_COMPLETE" if baseline_wins else "CANDIDATE_COMPLETE",
                visible_length=visible.complete_serialized_length,
                visible_sha256=visible.complete_serialized_sha256,
                restart_action="REPLAY_ATOMIC_REPLACE" if baseline_wins else "FINALIZE_ACK_IDEMPOTENTLY",
                restart_converged_sha256=candidate.complete_serialized_sha256,
            )
            _validate_case(case)
            cases.append(case)
    dry = AtomicReplaceCrashWindowDryRun(
        dry_run_id="",
        dry_run_hash="",
        cp79_contract_id=cp79_contract.contract_id,
        cp79_contract_hash=cp79_contract.contract_hash,
        cp79_dry_run_id=cp79_dry_run.dry_run_id,
        cp79_dry_run_hash=cp79_dry_run.dry_run_hash,
        lease_id=cp79_contract.lease_id,
        lease_hash=cp79_contract.lease_hash,
        cases=tuple(cases),
        phases=VALIDATION_PHASES,
        outcome="SIMULATED_ATOMIC_REPLACE_CRASH_WINDOW_PASS_12_PAIRS_48_OF_48_EXACT_ONE_COMPLETE_GENERATION_RESTART_CONVERGES_NO_STORAGE_WRITE_NO_AUTHORITY",
    )
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    dry = replace(dry, dry_run_id=f"cp80_dry_run_{digest[:24]}", dry_run_hash=digest)
    validate_atomic_replace_crash_window_dry_run(dry, cp79_contract, cp79_dry_run)
    return dry


def validate_atomic_replace_crash_window_dry_run(dry: AtomicReplaceCrashWindowDryRun, cp79_contract: Any, cp79_dry_run: Any) -> None:
    if (
        dry.cp79_contract_id, dry.cp79_contract_hash, dry.cp79_dry_run_id, dry.cp79_dry_run_hash,
        dry.lease_id, dry.lease_hash,
    ) != (
        cp79_contract.contract_id, cp79_contract.contract_hash, cp79_dry_run.dry_run_id, cp79_dry_run.dry_run_hash,
        cp79_contract.lease_id, cp79_contract.lease_hash,
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_PARENT_BINDING")
    if len(dry.cases) != 48:
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CASE_SET")
    for index in range(12):
        chunk = dry.cases[index * 4:(index + 1) * 4]
        if tuple(x.crash_window for x in chunk) != CRASH_WINDOWS or any(x.slot_index != index for x in chunk):
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_WINDOW_SET")
    for case in dry.cases:
        _validate_case(case)
    if dry.phases != VALIDATION_PHASES or dry.outcome != "SIMULATED_ATOMIC_REPLACE_CRASH_WINDOW_PASS_12_PAIRS_48_OF_48_EXACT_ONE_COMPLETE_GENERATION_RESTART_CONVERGES_NO_STORAGE_WRITE_NO_AUTHORITY":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_OUTCOME_OR_PHASES")
    if (
        not dry.all_twelve_pairs_validated or not dry.all_forty_eight_crash_cases_validated
        or not dry.exact_one_complete_generation_after_restart or not dry.deterministic_retry_or_finalize_validated
        or not dry.global_kill_switch_engaged or not dry.zero_io_observed or not dry.simulated_journal_only
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_GUARD")
    for key in (
        "storage_write_allowed", "storage_write_performed", "runtime_authorization_effective", "authority_activated",
        "network_allowed", "account_connection_allowed", "publish_allowed", "external_write_allowed",
        "deploy_allowed", "control_plane_promoted", "runtime_mutated",
    ):
        if getattr(dry, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_AUTHORITY_OR_MUTATION")
    digest = _hash(_without(dry.to_dict(), "dry_run_id", "dry_run_hash"))
    if dry.dry_run_hash != digest or dry.dry_run_id != f"cp80_dry_run_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_DRY_RUN_HASH")


def _build_cp80_evidence(root: Path) -> tuple[Any, Any, Any]:
    cp76, cp76_dry, _cp77_dry, cp78_contract, cp78_dry, cp79_dry = _build_cp79_evidence(root)
    cp79_policy = load_json(root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_policy.json")
    cp79_contract = compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility(root, cp79_policy)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_contract(cp79_contract)
    validate_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_dry_run(
        cp79_dry, cp76, cp76_dry, cp78_contract, cp78_dry
    )
    dry = build_atomic_replace_crash_window_dry_run(cp79_contract, cp79_dry)
    return cp79_contract, cp79_dry, dry


def compile_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window(
    root: Path,
    policy: dict[str, Any],
) -> LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowContract:
    root = root.resolve()
    _validate_policy(policy)
    _validate_root(root)
    cp79_contract, cp79_dry, dry = _build_cp80_evidence(root)
    contract = LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowContract(
        contract_id="",
        contract_hash="",
        cp79_contract_id=cp79_contract.contract_id,
        cp79_contract_hash=cp79_contract.contract_hash,
        cp79_dry_run_id=cp79_dry.dry_run_id,
        cp79_dry_run_hash=cp79_dry.dry_run_hash,
        lease_id=cp79_contract.lease_id,
        lease_hash=cp79_contract.lease_hash,
        dry_run_id=dry.dry_run_id,
        dry_run_hash=dry.dry_run_hash,
        policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_policy.json").read_bytes()).hexdigest(),
        cp79_policy_sha256=sha256((root / "config" / "live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_complete_write_atomic_visibility_policy.json").read_bytes()).hexdigest(),
        runtime_policy_sha256=sha256((root / "config" / "runtime_policy.json").read_bytes()).hexdigest(),
        module_registry_sha256=sha256((root / "config" / "module_registry.json").read_bytes()).hexdigest(),
        active_platforms=EXPECTED_ACTIVE,
        blockers=REQUIRED_BLOCKERS,
    )
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    contract = replace(contract, contract_id=f"cp80_contract_{digest[:24]}", contract_hash=digest)
    validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_contract(contract)
    return contract


def validate_live_read_only_probe_authority_lease_terminal_tombstone_recovery_journal_atomic_replace_crash_window_contract(
    contract: LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowContract,
) -> None:
    if (
        contract.checkpoint, contract.parent_control_checkpoint, contract.parent_activation_checkpoint,
        contract.parent_cp79_state, contract.state, contract.next_unit,
    ) != (CHECKPOINT, PARENT_CONTROL_CHECKPOINT, CP79_CHECKPOINT, CP79_STATE, STATE, NEXT_UNIT):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTRACT_IDENTITY")
    if (
        contract.active_platforms != EXPECTED_ACTIVE or contract.blockers != REQUIRED_BLOCKERS
        or not contract.global_kill_switch_engaged or not contract.synthetic_validation_only or not contract.simulated_journal_only
        or not contract.atomic_replace_crash_window_validated or not contract.all_twelve_pairs_validated
        or not contract.all_four_crash_windows_validated or not contract.all_forty_eight_restart_cases_validated
        or not contract.deterministic_retry_or_finalize_validated
    ):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTRACT_SCOPE_OR_GUARD")
    for key in (
        "external_authorization_ingested", "authorization_granted", "runtime_authorization_effective",
        "secret_reference_resolved", "environment_read", "keychain_read", "oauth_attempted", "real_account_lookup_attempted",
        "account_connected", "network_allowed", "network_attempted", "live_probe_allowed", "live_probe_attempted",
        "publish_allowed", "publish_attempted", "external_write_allowed", "external_write_performed",
        "storage_write_allowed", "storage_write_performed", "control_plane_promoted", "deploy_allowed",
        "deploy_performed", "paid_service_used", "authority_activated", "runtime_mutated",
    ):
        if getattr(contract, key) is not False:
            raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTRACT_AUTHORITY_OR_MUTATION")
    if not all(_hex(getattr(contract, key)) for key in (
        "cp79_contract_hash", "cp79_dry_run_hash", "lease_hash", "dry_run_hash",
        "policy_sha256", "cp79_policy_sha256", "runtime_policy_sha256", "module_registry_sha256",
    )):
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTRACT_DIGEST")
    digest = _hash(_without(contract.to_dict(), "contract_id", "contract_hash"))
    if contract.contract_hash != digest or contract.contract_id != f"cp80_contract_{digest[:24]}":
        raise LiveReadOnlyProbeAuthorityLeaseTerminalTombstoneRecoveryJournalAtomicReplaceCrashWindowHold("HOLD_CP80_CONTRACT_HASH")
